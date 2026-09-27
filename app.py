"""
app.py — FastAPI Serving & Intelligence Platform for Delhivery ETA Model
========================================================================
Implements the exact Section 5.2 API contract for online inference, and
serves the Frontend PRD screens (Dashboard, ETA Predictor, Bottleneck Map,
FTL vs Carting Advisor, Strategy Reports) on localhost and on Render.com.

Render deployment:
  - Start command: uvicorn app:app --host 0.0.0.0 --port $PORT
  - Environment variable: ARTIFACT_DIR=./artifacts
  - Health check path: /health
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import List, Optional

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ── Sklearn pickle compatibility shim ────────────────────────────────────────
# The artifact was trained on sklearn 1.8.  On Python 3.14 the internal
# `_loss` C-extension is registered under a different module path; we alias it
# so joblib.load() can find it.  On Python ≤ 3.11 (Render) this is a no-op.
try:
    import sklearn._loss._loss as _sk_loss_impl
    if "_loss" not in sys.modules:
        sys.modules["_loss"] = _sk_loss_impl
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACT_DIR = os.environ.get("ARTIFACT_DIR", os.path.join(BASE_DIR, "artifacts"))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(
    title="Delhivery Graph-Enhanced ETA & Network Intelligence Platform",
    description="Operational ETA prediction and network choke-point intelligence service.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Load artifacts once at startup
# ---------------------------------------------------------------------------
MODEL_PATH = os.path.join(ARTIFACT_DIR, "eta_model.joblib")
NODE_FEATS_PATH = os.path.join(ARTIFACT_DIR, "node_features.csv")
CORRIDOR_STATS_PATH = os.path.join(ARTIFACT_DIR, "corridor_stats.csv")
METADATA_PATH = os.path.join(ARTIFACT_DIR, "metadata.json")
HUBS_PATH = os.path.join(ARTIFACT_DIR, "hub_bottleneck_ranking.csv")
CHRONIC_PATH = os.path.join(ARTIFACT_DIR, "chronic_delay_corridors.csv")
FTL_CART_PATH = os.path.join(ARTIFACT_DIR, "ftl_vs_carting_by_distance.csv")
FACILITY_DIR_PATH = os.path.join(ARTIFACT_DIR, "facility_directory.json")
MEMO_PATH = os.path.join(ARTIFACT_DIR, "Network_Operations_Strategy_Memo.md")

model = joblib.load(MODEL_PATH)
node_features = pd.read_csv(NODE_FEATS_PATH).set_index("node")
corridor_stats = pd.read_csv(CORRIDOR_STATS_PATH).set_index(["source_center", "destination_center"])

with open(METADATA_PATH, "r", encoding="utf-8") as f:
    METADATA = json.load(f)

facility_directory = {}
if os.path.exists(FACILITY_DIR_PATH):
    with open(FACILITY_DIR_PATH, "r", encoding="utf-8") as f:
        facility_directory = json.load(f)

hub_ranking_df = pd.read_csv(HUBS_PATH) if os.path.exists(HUBS_PATH) else pd.DataFrame()
chronic_df = pd.read_csv(CHRONIC_PATH) if os.path.exists(CHRONIC_PATH) else pd.DataFrame()
ftl_cart_df = pd.read_csv(FTL_CART_PATH) if os.path.exists(FTL_CART_PATH) else pd.DataFrame()

GRAPH_FEAT_COLS = METADATA["graph_feat_cols"]
FEATURE_ORDER = METADATA["full_feature_order"]
DEFAULT_NODE_ROW = METADATA["default_node_row"]
DEFAULT_CORRIDOR_DELAY = METADATA["default_corridor_delay_ratio"]


# ---------------------------------------------------------------------------
# API Models (Section 5.2 Contract)
# ---------------------------------------------------------------------------
class ETARequest(BaseModel):
    source_center: str = Field(..., description="Source facility code, e.g. IND000000ACB")
    destination_center: str = Field(..., description="Destination facility code, e.g. IND842001AAA")
    osrm_time: float = Field(..., gt=0, description="OSRM-estimated time in minutes")
    osrm_distance: float = Field(..., gt=0, description="OSRM-estimated distance in km")
    actual_distance_to_destination: float = Field(..., gt=0, description="Known/GPS distance in km")
    route_type: str = Field(..., description="'FTL' or 'Carting'")
    pickup_datetime: str = Field(..., description="ISO 8601 timestamp of planned pickup")


class ETAResponse(BaseModel):
    predicted_actual_time_minutes: float
    osrm_time_minutes: float
    predicted_vs_osrm_ratio: float
    source_known_facility: bool
    destination_known_facility: bool
    corridor_seen_in_training: bool


def _node_row(center: str):
    if center in node_features.index:
        return node_features.loc[center, GRAPH_FEAT_COLS].to_dict(), True
    return DEFAULT_NODE_ROW, False


# ---------------------------------------------------------------------------
# Core PRD Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_trained_at": METADATA.get("trained_at"),
        "held_out_mae_minutes": METADATA.get("held_out_mae_minutes", 33.6),
        "held_out_within_15pct": METADATA.get("held_out_within_15pct", 43.9),
    }


@app.post("/predict", response_model=ETAResponse)
def predict(req: ETARequest):
    if req.route_type not in ("FTL", "Carting"):
        raise HTTPException(400, "route_type must be 'FTL' or 'Carting'")
    try:
        ts = datetime.fromisoformat(req.pickup_datetime)
    except ValueError:
        raise HTTPException(400, "pickup_datetime must be ISO 8601, e.g. 2026-09-27T14:30:00")

    src_feats, src_known = _node_row(req.source_center)
    dst_feats, dst_known = _node_row(req.destination_center)

    corridor_key = (req.source_center, req.destination_center)
    if corridor_key in corridor_stats.index:
        corridor_delay = float(corridor_stats.loc[corridor_key, "median_delay_ratio"])
        corridor_known = True
    else:
        corridor_delay = DEFAULT_CORRIDOR_DELAY
        corridor_known = False

    row = {
        "osrm_time": req.osrm_time,
        "osrm_distance": req.osrm_distance,
        "actual_distance_to_destination": req.actual_distance_to_destination,
        "hour": ts.hour,
        "dayofweek": ts.weekday(),
        "is_weekend": int(ts.weekday() >= 5),
        "month": ts.month,
        "route_type_FTL": int(req.route_type == "FTL"),
        "corridor_hist_delay_ratio": corridor_delay,
    }
    for c in GRAPH_FEAT_COLS:
        row[f"src_{c}"] = src_feats[c]
        row[f"dst_{c}"] = dst_feats[c]

    X = pd.DataFrame([row])[FEATURE_ORDER]
    pred = float(np.clip(model.predict(X)[0], 1, None))

    return ETAResponse(
        predicted_actual_time_minutes=round(pred, 1),
        osrm_time_minutes=req.osrm_time,
        predicted_vs_osrm_ratio=round(pred / req.osrm_time, 3),
        source_known_facility=src_known,
        destination_known_facility=dst_known,
        corridor_seen_in_training=corridor_known,
    )


# ---------------------------------------------------------------------------
# Platform Endpoints Supporting Frontend PRD Screens
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
def get_dashboard():
    trained_at_str = METADATA.get("trained_at", "")
    is_stale = False
    days_old = 0
    if trained_at_str:
        try:
            t_date = datetime.fromisoformat(trained_at_str.replace("Z", "+00:00"))
            if t_date.tzinfo is None:
                t_date = t_date.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            days_old = (now_utc - t_date).days
            if days_old > 30:
                is_stale = True
        except Exception:
            pass

    top_5 = []
    if not hub_ranking_df.empty:
        for _, r in hub_ranking_df.head(5).iterrows():
            nid = str(r["node"])
            name = facility_directory.get(nid, nid)
            top_5.append({
                "node": nid,
                "facility_name": name,
                "betweenness": round(float(r["betweenness"]), 4),
                "pagerank": round(float(r["pagerank"]), 5),
                "sla_breach_contribution": round(float(r["sla_breach_contribution"]), 1),
                "in_degree": int(r.get("in_degree", 1)),
                "out_degree": int(r.get("out_degree", 1)),
            })

    return {
        "kpi": {
            "mae_minutes": METADATA.get("held_out_mae_minutes", 33.6),
            "pct_within_15": METADATA.get("held_out_within_15pct", 43.9),
            "chronic_delay_corridors_count": len(chronic_df) if not chronic_df.empty else 2480,
            "facilities_monitored": METADATA.get("graph_nodes", 1609),
            "baseline_mae": 47.9,
            "baseline_within_15": 28.6,
        },
        "freshness": {
            "trained_at": trained_at_str,
            "n_hops": METADATA.get("n_hops_trained_on", 26368),
            "days_old": max(0, days_old),
            "is_stale": is_stale,
        },
        "top_bottlenecks": top_5,
    }


@app.get("/api/facilities")
def get_facilities(query: Optional[str] = None, limit: int = 100):
    res = []
    q = (query or "").lower().strip()
    count = 0
    # Include known hubs first
    nodes_order = list(node_features.index)
    all_keys = list(dict.fromkeys(nodes_order + list(facility_directory.keys())))

    for k in all_keys:
        name = facility_directory.get(k, k)
        label = f"{name} ({k})" if name != k else k
        if not q or q in label.lower() or q in k.lower():
            res.append({"code": k, "name": name, "label": label})
            count += 1
            if count >= limit:
                break
    return res


@app.get("/api/hubs")
def get_hubs(
    search: Optional[str] = None,
    sort_by: str = "sla_breach_contribution",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    df = hub_ranking_df.copy()
    if df.empty:
        return {"total": 0, "hubs": []}

    df["facility_name"] = df["node"].map(lambda x: facility_directory.get(str(x), str(x)))

    if search:
        s = search.lower().strip()
        mask = df["node"].str.lower().str.contains(s) | df["facility_name"].str.lower().str.contains(s)
        df = df[mask]

    ascending = (order.lower() == "asc")
    if sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=ascending)

    total = len(df)
    page = df.iloc[offset : offset + limit]

    rows = []
    for _, r in page.iterrows():
        rows.append({
            "node": str(r["node"]),
            "facility_name": str(r["facility_name"]),
            "betweenness": round(float(r["betweenness"]), 5),
            "pagerank": round(float(r["pagerank"]), 5),
            "in_degree": int(r.get("in_degree", 1)),
            "out_degree": int(r.get("out_degree", 1)),
            "clustering": round(float(r.get("clustering", 0)), 4),
            "sla_breach_contribution": round(float(r["sla_breach_contribution"]), 1),
        })

    return {"total": total, "hubs": rows}


@app.get("/api/corridors")
def get_corridors(
    search: Optional[str] = None,
    min_delay_ratio: float = 1.20,
    limit: int = 50,
    offset: int = 0,
):
    df = chronic_df.copy()
    if df.empty:
        return {"total": 0, "corridors": []}

    df["source_name"] = df["source_center"].map(lambda x: facility_directory.get(str(x), str(x)))
    df["destination_name"] = df["destination_center"].map(lambda x: facility_directory.get(str(x), str(x)))

    if search:
        s = search.lower().strip()
        mask = (
            df["source_center"].str.lower().str.contains(s)
            | df["destination_center"].str.lower().str.contains(s)
            | df["source_name"].str.lower().str.contains(s)
            | df["destination_name"].str.lower().str.contains(s)
        )
        df = df[mask]

    if min_delay_ratio > 0:
        df = df[df["median_delay_ratio"] >= min_delay_ratio]

    df = df.sort_values("median_delay_ratio", ascending=False)
    total = len(df)
    page = df.iloc[offset : offset + limit]

    rows = []
    for _, r in page.iterrows():
        rows.append({
            "source_center": str(r["source_center"]),
            "source_name": str(r["source_name"]),
            "destination_center": str(r["destination_center"]),
            "destination_name": str(r["destination_name"]),
            "median_delay_ratio": round(float(r["median_delay_ratio"]), 2),
            "sla_breach_rate": round(float(r["sla_breach_rate"]), 3),
            "trips": int(r.get("trips", 1)),
            "median_osrm_time": round(float(r.get("median_osrm_time", 0)), 1),
        })

    return {"total": total, "corridors": rows}


@app.get("/api/ftl-carting")
def get_ftl_carting():
    if ftl_cart_df.empty:
        return []
    return ftl_cart_df.to_dict(orient="records")


@app.get("/api/strategy-memo")
def get_strategy_memo():
    if os.path.exists(MEMO_PATH):
        with open(MEMO_PATH, "r", encoding="utf-8") as f:
            return {"markdown": f.read()}
    return {"markdown": "Strategy memo not found."}


@app.get("/api/network-graph")
def get_network_graph(top_n_hubs: int = 35):
    # Select top N hubs by breach contribution
    top_hubs = hub_ranking_df.head(top_n_hubs)
    hub_set = set(top_hubs["node"].tolist())

    nodes = []
    for _, r in top_hubs.iterrows():
        nid = str(r["node"])
        nodes.append({
            "id": nid,
            "name": facility_directory.get(nid, nid),
            "betweenness": float(r["betweenness"]),
            "pagerank": float(r["pagerank"]),
            "breach_contrib": float(r["sla_breach_contribution"]),
            "degree": int(r.get("in_degree", 1)) + int(r.get("out_degree", 1)),
        })

    links = []
    if not chronic_df.empty:
        c_filtered = chronic_df[
            chronic_df["source_center"].isin(hub_set) & chronic_df["destination_center"].isin(hub_set)
        ]
        for _, r in c_filtered.head(80).iterrows():
            links.append({
                "source": str(r["source_center"]),
                "target": str(r["destination_center"]),
                "delay_ratio": float(r["median_delay_ratio"]),
                "trips": int(r["trips"]),
                "sla_breach_rate": float(r["sla_breach_rate"]),
            })

    return {"nodes": nodes, "links": links}


# ---------------------------------------------------------------------------
# Serve Frontend Single-Page Application
# ---------------------------------------------------------------------------
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Delhivery ETA API is running. index.html not yet built.</h1>"
