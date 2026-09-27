# Delhivery Graph-Enhanced ETA & Network Intelligence Platform

> **Owner:** Vineet Chauhan | **Version:** 1.0.0 Production | **Status:** Deployed & Verified

A high-performance logistics intelligence platform designed to replace raw OSRM (Open Source Routing Machine) empty-road estimates with a graph-enhanced machine learning system that accounts for hub congestion, topological betweenness, and corridor friction across Delhivery's national network.

---

## 1. Key Value Proposition & Metrics

* **Held-Out Test MAE:** **33.6 minutes** (vs. **47.9 minutes** for distance + OSRM baseline — a **29.8% precision improvement**).
* **% Predictions within ±15% of Actual:** **43.9%** (vs. **28.6%** baseline).
* **Serving Latency (p95):** `< 20ms` (all network graph metrics and node embeddings are pre-computed static lookups).
* **Coverage:** 1,609 active transit facilities, 2,580 corridors, 2,480 chronic delay corridors audited.

---

## 2. Directory Structure

```
delhivery_graph_platform/
├── app.py                             # FastAPI serving microservice + frontend static routes
├── run_server.py                      # One-click Python launcher (opens browser at :8000)
├── run.bat                            # Windows double-click launcher
├── train_and_export.py                # Reproducible offline graph training & export pipeline
├── MODEL_COMPARISON_AND_AUDIT.md      # Detailed audit: original user notebook vs production model
├── requirements.txt                   # Production Python dependencies
├── Dockerfile                         # Container build definition for Cloud Run / Render / AWS
├── static/
│   └── index.html                     # Full Single-Page Application (5 PRD screens)
└── artifacts/
    ├── eta_model.joblib               # Trained HistGradientBoostingRegressor model
    ├── node_features.csv              # 1,609 facilities with graph centrality & embeddings
    ├── corridor_stats.csv             # Historical delay stats per facility pair
    ├── metadata.json                  # Pinned feature order, eval metrics, and fallbacks
    ├── hub_bottleneck_ranking.csv     # Prioritized ranking of bottleneck hubs by SLA contribution
    ├── chronic_delay_corridors.csv    # Corridors with median delay ratio > 1.20x
    ├── ftl_vs_carting_by_distance.csv # Empirical FTL vs Carting stats across 5 distance bands
    ├── facility_directory.json        # 1,657 facility codes mapped to human names & cities
    └── Network_Operations_Strategy_Memo.md # Strategic operations memorandum
```

---

## 3. Quick Start (Run Locally)

### Option 1: Double-click
Double-click `run.bat` in Windows Explorer.

### Option 2: Command Line
```bash
cd delhivery_graph_platform
python run_server.py
```
This automatically starts Uvicorn on port `8000` and opens `http://localhost:8000` in your default browser.

### Option 3: Direct Uvicorn
```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

---

## 4. The 5 Frontend Screens (PRD Compliance)

1. **Dashboard (Landing Screen):**
   * Top 4 KPI Cards: MAE (33.6 min), % within 15% (43.9%), # Chronic Delay Corridors (2,480), # Monitored Facilities (1,609).
   * Top 5 Bottleneck Hubs ranked by cumulative SLA-breach contribution. Click any hub row to jump directly to facility drill-down in Screen 3.
   * Model Freshness Banner: Displays training date and sample size, with an automated alert state if artifacts are older than 30 days.

2. **ETA Predictor:**
   * Form with searchable source & destination facility dropdowns (auto-suggesting facility codes and city/state names), FTL vs Carting toggle, pickup datetime picker, and OSRM numeric inputs.
   * On submit (`POST /predict`):
     * Large bold predicted ETA (minutes and hours:minutes format).
     * OSRM baseline comparison with percentage ratio badge ("42% longer than OSRM predicts").
     * Confidence badges: `Source facility: known / new`, `Destination facility: known / new`, `Corridor: seen in training / new`.
     * Dispatcher operational buffer recommendations.

3. **Bottleneck & Corridor Map:**
   * **Facility Bottleneck Ranking:** Sortable and searchable table of 1,609 facilities by Betweenness, PageRank, Degree, and SLA Breach Contribution.
   * **Chronic Delay Corridors:** Filterable table of corridors with median delay ratio > 1.20x, breach rate, and trip volume.
   * **Network Graph Visualizer (v1.1):** Interactive force-directed canvas visualizing hub centrality (node size) and corridor congestion (colored edges).

4. **FTL vs Carting Advisor:**
   * Distance-band selector: `<50km`, `50–150km`, `150–400km`, `400–1000km`, `1000km+`.
   * Head-to-head empirical comparison of Carting vs FTL median delay ratios and SLA breach rates.
   * High-contrast operational recommendation card (e.g., *"Under 50km: High Carting congestion (2.15 vs 1.84 FTL); shift short-haul volume to dedicated FTL shuttles"*).

5. **Strategy Reports:**
   * Renders the executive `Network_Operations_Strategy_Memo.md` with operational directives, root cause analysis, and monthly governance thresholds.

---

## 5. API Reference

### `POST /predict`
```json
// Request:
{
  "source_center": "IND000000ACB",
  "destination_center": "IND842001AAA",
  "osrm_time": 19.0,
  "osrm_distance": 11.9653,
  "actual_distance_to_destination": 10.4356,
  "route_type": "Carting",
  "pickup_datetime": "2026-09-27T14:30:00"
}

// Response:
{
  "predicted_actual_time_minutes": 53.5,
  "osrm_time_minutes": 19.0,
  "predicted_vs_osrm_ratio": 2.816,
  "source_known_facility": true,
  "destination_known_facility": true,
  "corridor_seen_in_training": true
}
```

### `GET /health`
```json
{
  "status": "ok",
  "model_trained_at": "2026-09-27T01:22:51.742113",
  "held_out_mae_minutes": 33.6,
  "held_out_within_15pct": 43.9
}
```

---

## 6. Retraining Pipeline

When new delivery batches arrive:
```bash
python train_and_export.py
```
This regenerates and validates all artifacts in `artifacts/`. If held-out MAE exceeds 35.0 minutes, the regression gate blocks deployment.
