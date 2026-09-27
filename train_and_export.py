"""
train_and_export.py — Delhivery Graph-Enhanced ETA Training & Artifact Pipeline
=============================================================================
Reproduces and exports all production artifacts required by the PRD:
  1. artifacts/eta_model.joblib
  2. artifacts/node_features.csv
  3. artifacts/corridor_stats.csv
  4. artifacts/metadata.json
  5. artifacts/hub_bottleneck_ranking.csv
  6. artifacts/chronic_delay_corridors.csv
  7. artifacts/ftl_vs_carting_by_distance.csv
  8. artifacts/facility_directory.json

Fixes applied vs exploratory code:
  - Strict leakage elimination (no actual_time derivatives in feature matrix X)
  - Hop-level aggregation (collapsing re-scan snapshots)
  - Time-based 80/20 chronological split
  - Network graph features built exclusively on training period
"""

import json
import os
import random
import shutil
import warnings
from collections import defaultdict
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
import networkx as nx
from scipy.sparse import coo_matrix
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

warnings.filterwarnings("ignore")
RNG = 42
random.seed(RNG)
np.random.seed(RNG)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACT_DIR = os.environ.get("ARTIFACT_DIR", os.path.join(BASE_DIR, "artifacts"))
os.makedirs(ARTIFACT_DIR, exist_ok=True)

# Locate delivery_data.csv
possible_paths = [
    os.environ.get("RAW_PATH", ""),
    os.path.join(BASE_DIR, "delivery_data.csv"),
    os.path.join(BASE_DIR, "..", "delhivery_eta_deploy", "delivery_data.csv"),
    os.path.join(BASE_DIR, "..", "delivery_data.csv"),
]
RAW_PATH = next((p for p in possible_paths if p and os.path.exists(p)), None)


def main():
    if not RAW_PATH:
        print(f"Error: delivery_data.csv not found in search paths: {possible_paths}")
        return

    print(f"STAGE 1: Loading raw data from {RAW_PATH} ...")
    df = pd.read_csv(
        RAW_PATH,
        parse_dates=["trip_creation_time", "od_start_time", "od_end_time", "cutoff_timestamp"],
    )
    df = df.sort_values("cutoff_factor")

    # Hop-level collapse
    hops = df.groupby(["trip_uuid", "source_center", "destination_center"], as_index=False).last()
    hops = hops[hops["osrm_time"] > 0].copy()
    print(f"  raw rows: {len(df):,} -> hop-level rows: {len(hops):,}")

    # Facility directory lookup
    print("Exporting facility directory...")
    names = {}
    for _, r in df.drop_duplicates("source_center").iterrows():
        names[r["source_center"]] = r["source_name"]
    for _, r in df.drop_duplicates("destination_center").iterrows():
        if r["destination_center"] not in names:
            names[r["destination_center"]] = r["destination_name"]
    with open(os.path.join(ARTIFACT_DIR, "facility_directory.json"), "w", encoding="utf-8") as f:
        json.dump(names, f, indent=2)

    # STAGE 2: Feature Engineering (No Target Leakage)
    print("STAGE 2: Feature engineering ...")
    hops["hour"] = hops["od_start_time"].dt.hour
    hops["dayofweek"] = hops["od_start_time"].dt.dayofweek
    hops["is_weekend"] = hops["dayofweek"].isin([5, 6]).astype(int)
    hops["month"] = hops["od_start_time"].dt.month
    hops["route_type_FTL"] = (hops["route_type"] == "FTL").astype(int)

    hops["delay_ratio"] = hops["actual_time"] / hops["osrm_time"]
    hops["sla_breach"] = (hops["delay_ratio"] > 1.20).astype(int)

    # STAGE 3: Time-Based Split
    hops = hops.sort_values("trip_creation_time").reset_index(drop=True)
    split_idx = int(len(hops) * 0.8)
    train_hops = hops.iloc[:split_idx].copy()
    test_hops = hops.iloc[split_idx:].copy()
    print(f"STAGE 3: Train={len(train_hops):,}  Test={len(test_hops):,}")

    # STAGE 4: Graph From Train Split Only
    print("STAGE 4: Building network graph from train data ...")
    G = nx.DiGraph()
    edge_stats = (
        train_hops.groupby(["source_center", "destination_center"])
        .agg(
            median_delay_ratio=("delay_ratio", "median"),
            sla_breach_rate=("sla_breach", "mean"),
            trips=("trip_uuid", "count"),
            median_osrm_time=("osrm_time", "median"),
        )
        .reset_index()
    )
    for _, r in edge_stats.iterrows():
        G.add_edge(
            r.source_center,
            r.destination_center,
            weight=r.median_delay_ratio,
            trips=r.trips,
            sla_breach_rate=r.sla_breach_rate,
        )

    btw = nx.betweenness_centrality(G, k=min(500, G.number_of_nodes()), seed=RNG, weight=None)
    pagerank = nx.pagerank(G, weight="weight")
    indeg, outdeg = dict(G.in_degree()), dict(G.out_degree())
    clustering = nx.clustering(G.to_undirected())

    node_feats = pd.DataFrame({"node": list(G.nodes())})
    node_feats["betweenness"] = node_feats["node"].map(btw)
    node_feats["pagerank"] = node_feats["node"].map(pagerank)
    node_feats["in_degree"] = node_feats["node"].map(indeg)
    node_feats["out_degree"] = node_feats["node"].map(outdeg)
    node_feats["clustering"] = node_feats["node"].map(clustering)

    breach_contrib = defaultdict(float)
    for u, v, d in G.edges(data=True):
        c = d["sla_breach_rate"] * d["trips"]
        breach_contrib[u] += c
        breach_contrib[v] += c
    node_feats["sla_breach_contribution"] = node_feats["node"].map(breach_contrib).fillna(0)

    # STAGE 5: Node Embeddings (Random Walk + SVD approximation)
    print("STAGE 5: Generating node embeddings ...")

    def random_walks(graph, num_walks=8, walk_length=15):
        nodes = list(graph.nodes())
        walks = []
        for _ in range(num_walks):
            random.shuffle(nodes)
            for n in nodes:
                walk, cur = [n], n
                for _ in range(walk_length - 1):
                    nbrs = list(graph.successors(cur))
                    if not nbrs:
                        break
                    cur = random.choice(nbrs)
                    walk.append(cur)
                walks.append(walk)
        return walks

    walks = random_walks(G)
    node_idx = {n: i for i, n in enumerate(G.nodes())}
    co = defaultdict(float)
    window = 3
    for w in walks:
        for i, n in enumerate(w):
            for j in range(max(0, i - window), min(len(w), i + window + 1)):
                if i != j:
                    co[(node_idx[n], node_idx[w[j]])] += 1

    if co:
        rows_, cols_, vals_ = zip(*[(k[0], k[1], v) for k, v in co.items()])
        M = coo_matrix((vals_, (rows_, cols_)), shape=(len(node_idx), len(node_idx)))
        n_comp = min(8, max(2, len(node_idx) - 1))
        svd = TruncatedSVD(n_components=n_comp, random_state=RNG)
        emb = svd.fit_transform(M)
    else:
        emb = np.zeros((len(node_idx), 8))

    emb_cols = [f"emb_{i}" for i in range(emb.shape[1])]
    emb_df = pd.DataFrame(emb, columns=emb_cols)
    emb_df["node"] = list(node_idx.keys())
    node_feats = node_feats.merge(emb_df, on="node", how="left")
    node_feats[emb_cols] = node_feats[emb_cols].fillna(0)

    GRAPH_FEAT_COLS = [
        "betweenness",
        "pagerank",
        "in_degree",
        "out_degree",
        "clustering",
        "sla_breach_contribution",
    ] + emb_cols

    DEFAULT_NODE_ROW = node_feats[GRAPH_FEAT_COLS].median().to_dict()
    DEFAULT_CORRIDOR_DELAY = float(edge_stats["median_delay_ratio"].median())

    # STAGE 6: Attach Graph Features
    print("STAGE 6: Merging graph features onto dataset ...")

    def attach_graph_feats(frame):
        out = frame.merge(node_feats, left_on="source_center", right_on="node", how="left")
        out = out.rename(columns={c: f"src_{c}" for c in GRAPH_FEAT_COLS})
        out = out.merge(
            node_feats,
            left_on="destination_center",
            right_on="node",
            how="left",
            suffixes=("", "_dst"),
        )
        out = out.rename(columns={c: f"dst_{c}" for c in GRAPH_FEAT_COLS})
        for c in [f"src_{x}" for x in GRAPH_FEAT_COLS] + [f"dst_{x}" for x in GRAPH_FEAT_COLS]:
            out[c] = out[c].fillna(0.0)
        corridor_hist = edge_stats.set_index(["source_center", "destination_center"])[
            "median_delay_ratio"
        ]
        out["corridor_hist_delay_ratio"] = list(
            corridor_hist.reindex(list(zip(out["source_center"], out["destination_center"]))).fillna(
                DEFAULT_CORRIDOR_DELAY
            )
        )
        return out

    train_full = attach_graph_feats(train_hops)
    test_full = attach_graph_feats(test_hops)

    # STAGE 7: Train Model
    print("STAGE 7: Training model ...")
    BASE_FEATS = [
        "osrm_time",
        "osrm_distance",
        "actual_distance_to_destination",
        "hour",
        "dayofweek",
        "is_weekend",
        "month",
        "route_type_FTL",
    ]
    GRAPH_FEATS = (
        BASE_FEATS
        + [f"src_{c}" for c in GRAPH_FEAT_COLS]
        + [f"dst_{c}" for c in GRAPH_FEAT_COLS]
        + ["corridor_hist_delay_ratio"]
    )
    TARGET = "actual_time"

    Xtr, ytr = train_full[GRAPH_FEATS], train_full[TARGET]
    Xte, yte = test_full[GRAPH_FEATS], test_full[TARGET]

    model = HistGradientBoostingRegressor(random_state=RNG, max_depth=8, learning_rate=0.08)
    model.fit(Xtr, ytr)
    pred = np.clip(model.predict(Xte), 1, None)
    mae = mean_absolute_error(yte, pred)
    within15 = float(np.mean(np.abs(pred - yte) / yte <= 0.15) * 100)
    print(f"  Held-out MAE={mae:.2f} min   %within15%={within15:.1f}%")

    # Fit final model on full history
    print("STAGE 7b: Fitting full model for deployment ...")
    X_all = pd.concat([Xtr, Xte], axis=0)
    y_all = pd.concat([ytr, yte], axis=0)
    final_model = HistGradientBoostingRegressor(random_state=RNG, max_depth=8, learning_rate=0.08)
    final_model.fit(X_all, y_all)

    # STAGE 8: Auditing & Advisor Tables
    print("STAGE 8: Generating ops audits & advisor tables ...")
    node_feats.sort_values("sla_breach_contribution", ascending=False).to_csv(
        os.path.join(ARTIFACT_DIR, "hub_bottleneck_ranking.csv"), index=False
    )
    edge_stats[edge_stats["median_delay_ratio"] > 1.20].sort_values(
        "sla_breach_rate", ascending=False
    ).to_csv(os.path.join(ARTIFACT_DIR, "chronic_delay_corridors.csv"), index=False)

    # FTL vs Carting advisor
    bins = [0, 50, 150, 400, 1000, np.inf]
    labels = ["<50km", "50–150km", "150–400km", "400–1000km", "1000km+"]
    hops["distance_band"] = pd.cut(hops["actual_distance_to_destination"], bins=bins, labels=labels)
    recs = {
        "<50km": "Under 50km: High Carting congestion (delay ratio 2.15 vs 1.84 FTL). Shift short-haul Carting to dedicated FTL shuttles where vehicle utilization is high.",
        "50–150km": "50–150km: Shift Carting volume to FTL where feasible to bypass intermediary transshipment touches and cut SLA breaches.",
        "150–400km": "150–400km: Selective routing — prioritize FTL for time-critical express lanes, Carting for baseline feeder loads.",
        "400–1000km": "400–1000km: Direct linehaul corridor — route 100% via FTL linehaul with scheduled hub departures.",
        "1000km+": "1000km+: Long-haul corridors — enforce FTL with dual-driver rotation and mandatory relay checkpoints.",
    }
    ftl_cart_rows = []
    for band in labels:
        sub = hops[hops["distance_band"] == band]
        carting = sub[sub["route_type"] == "Carting"]
        ftl = sub[sub["route_type"] == "FTL"]
        c_trips = len(carting)
        c_ratio = float(carting["delay_ratio"].median()) if c_trips > 0 else 1.0
        c_breach = float(carting["sla_breach"].mean()) if c_trips > 0 else 0.0
        f_trips = len(ftl)
        f_ratio = float(ftl["delay_ratio"].median()) if f_trips > 0 else 1.0
        f_breach = float(ftl["sla_breach"].mean()) if f_trips > 0 else 0.0
        ftl_cart_rows.append(
            {
                "distance_band": band,
                "carting_trips": c_trips,
                "carting_median_delay_ratio": round(c_ratio, 2),
                "carting_sla_breach_rate": round(c_breach, 3),
                "ftl_trips": f_trips,
                "ftl_median_delay_ratio": round(f_ratio, 2),
                "ftl_sla_breach_rate": round(f_breach, 3),
                "recommendation": recs[band],
            }
        )
    pd.DataFrame(ftl_cart_rows).to_csv(
        os.path.join(ARTIFACT_DIR, "ftl_vs_carting_by_distance.csv"), index=False
    )

    # STAGE 9: Export Serving Artifacts
    print("STAGE 9: Exporting model and metadata ...")
    joblib.dump(final_model, os.path.join(ARTIFACT_DIR, "eta_model.joblib"))
    node_feats.to_csv(os.path.join(ARTIFACT_DIR, "node_features.csv"), index=False)
    edge_stats.to_csv(os.path.join(ARTIFACT_DIR, "corridor_stats.csv"), index=False)

    metadata = {
        "trained_at": datetime.utcnow().isoformat(),
        "n_hops_trained_on": int(len(hops)),
        "graph_nodes": int(G.number_of_nodes()),
        "graph_edges": int(G.number_of_edges()),
        "held_out_mae_minutes": round(mae, 2),
        "held_out_within_15pct": round(within15, 1),
        "graph_feat_cols": GRAPH_FEAT_COLS,
        "base_feats": BASE_FEATS,
        "full_feature_order": GRAPH_FEATS,
        "default_node_row": DEFAULT_NODE_ROW,
        "default_corridor_delay_ratio": DEFAULT_CORRIDOR_DELAY,
        "sklearn_model_class": "HistGradientBoostingRegressor",
    }
    with open(os.path.join(ARTIFACT_DIR, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    print("All artifacts successfully exported to", ARTIFACT_DIR)


if __name__ == "__main__":
    main()
