# Delhivery ETA Model: Comprehensive Audit, Comparison & Resolution Guide

## 1. Executive Summary

This document provides a technical audit comparing the original exploratory model built in the user notebook (`Untitled (2).ipynb` / `MY/project/`) against the graph-enhanced production model (`train_and_export.py` / `delhivery_eta_deploy`).

| Metric / Dimension | User Original Notebook (`Untitled (2).ipynb`) | Production Graph-Enhanced Model (`train_and_export.py`) | Operational Impact |
|:---|:---|:---|:---|
| **Primary Algorithm** | XGBoost / CatBoost / LightGBM | **HistGradientBoostingRegressor** | Fast native support for numerical bins & missing values |
| **Target Leakage** | **CRITICAL LEAKAGE PRESENT** | **ELIMINATED COMPLETELY** | Original model was completely unusable in real production |
| **Observation Level** | Raw GPS re-scan snapshot rows (144,867 rows) | Collapsed completed hops (26,368 rows) | Correctly weights shipments; eliminates duplicate inflation |
| **Train/Test Split** | Random 80/20 train_test_split | Strict chronological time-based split (80/20) | Reflects real-world deployment (predicting future from past) |
| **Graph Metrics Computation** | Calculated globally across all rows | Calculated **only on historical train window** | Prevents future information from bleeding into training |
| **Network Features** | Hub degree, betweenness, closeness | Betweenness, PageRank, In/Out-degree, Clustering, SLA Breach Contribution, 8-dim Random Walk SVD Embeddings, Corridor Historical Delay Ratio | Deep topological signals capturing network choke points |
| **Held-Out MAE** | Spurious R² ~0.99 (collapses in prod) | **33.6 minutes** (Held-out chronological test) | **29.8% error reduction vs OSRM baseline (47.9 min)** |
| **Predictions within 15%**| Artificial / Unreliable | **43.9%** (Held-out chronological test) | **+15.3 percentage points higher than OSRM baseline (28.6%)** |
| **Serving Architecture** | None (Jupyter code cells only) | FastAPI Microservice (`<100ms` p95) with Static Lookup Tables | Zero request-time graph recalculation; resilient fallbacks |

---

## 2. In-Depth Root Cause Analysis: Critical Deficiencies in the Original Model

### Defect 1: Critical Target Leakage in Feature Engineering
In the original notebook `Untitled (2).ipynb` (Cell 12, 13, 14, 17), the following features were created:
```python
# USER NOTEBOOK CODE:
df["delay"] = df["actual_time"] - df["osrm_time"]
df["delay_ratio"] = df["actual_time"] / df["osrm_time"]
df["segment_delay"] = df["segment_actual_time"] - df["segment_osrm_time"]
df["actual_speed"] = df["actual_distance_to_destination"] / df["actual_time"]
```
These four features were then included in `df_model` and passed to `model.fit(X_train, y_train)` to predict `y = df_model["actual_time"]`.
* **Why this is catastrophic:** `delay`, `delay_ratio`, `segment_delay`, and `actual_speed` are direct mathematical transformations of the target variable `actual_time`. In production, when a truck leaves facility `A` heading for facility `B`, **`actual_time` has not happened yet!** Passing `actual_speed` to predict `actual_time` is equivalent to telling the model the answer before asking the question.
* **The Fix:** All direct functions of `actual_time` were eliminated from the feature matrix `X`. However, historical delay patterns *across corridors* from the past were aggregated on the train split only (`corridor_hist_delay_ratio`), turning a leaked variable into a legitimate prior probability.

### Defect 2: Raw Re-scan Snapshots vs. Hop-Level Aggregation
The raw Delhivery tracking dataset contains 144,867 rows because scans are recorded at multiple checkpoints (`cutoff_factor`) along a journey.
* **Why this is problematic:** A single trip that is scanned 12 times produces 12 identical or near-identical rows. A random 80/20 split will place 10 scans in the training set and 2 scans in the test set, allowing the model to simply memorize the trip outcome.
* **The Fix:** The dataset is sorted by `cutoff_factor` and grouped by `['trip_uuid', 'source_center', 'destination_center']`, taking the `.last()` completed scan (26,368 distinct physical hops).

### Defect 3: Chronological Time Split vs. Random Split
Logistics is inherently sequential:
* **Why random split fails:** A random split tests the model on a delivery that occurred in July using patterns learned from deliveries in August.
* **The Fix:** Sorted strictly by `trip_creation_time`. The first 80% represents historical operations, and the remaining 20% represents unseen future operations.

### Defect 4: Graph Feature Leakage
The original code computed graph centrality using the full dataset. In real operations, graph metrics must be built only from past deliveries.
* **The Fix:** The directed graph `G` (1,609 facilities, 2,580 corridors) is built exclusively from the 80% training split. For new or unseen facilities at inference time, safe network-median fallbacks are used and clearly flagged to operations via `source_known_facility: false` or `corridor_seen_in_training: false`.

---

## 3. The Locked Production Model Specification

As defined in Section 2 of the PRD:
1. **Model Class:** `HistGradientBoostingRegressor(max_depth=8, learning_rate=0.08, random_state=42)`
2. **Artifact Location:** `artifacts/eta_model.joblib`
3. **Lookup Tables:**
   * `artifacts/node_features.csv`: 1,609 facilities with 14 graph metrics each
   * `artifacts/corridor_stats.csv`: 2,580 corridor historical performance statistics
   * `artifacts/metadata.json`: Feature orders, network default fallbacks, evaluation metrics
   * `artifacts/ftl_vs_carting_by_distance.csv`: Strategic routing recommendations
   * `artifacts/hub_bottleneck_ranking.csv`: Prioritized hub interventions
   * `artifacts/chronic_delay_corridors.csv`: Corridors exceeding 1.20x OSRM time
4. **Latency:** Under 20ms per prediction because all graph features are pre-computed static lookups.
