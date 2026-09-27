# DELHI-OPS-STRAT-2026-Q3
# Executive Operations Strategy Memo: Graph-Enhanced ETA & Network Bottleneck Mitigation

**To:** Network Operations Leadership, Regional Dispatch Operations, Fleet Routing Committee  
**From:** Vineet Chauhan (Head of Logistics Intelligence & Ops Analytics)  
**Date:** September 27, 2026  
**Subject:** Network Operations Strategy Memo — Resolving Chronic Corridor Delay, Hub Staging Friction, and FTL vs Carting Route Optimization  
**Model Version:** v1.0.0 (Graph-Enhanced HistGradientBoosting, Held-out MAE 33.6 min)  

---

## 1. Executive Summary & Root Cause Analysis

OSRM (Open Source Routing Machine) routing engines systematically underestimate real-world transit time across Delhivery's national network. OSRM assumes empty-road free-flow speeds and zero facility dwell time. In reality, actual hop duration is driven primarily by **structural network topology, facility processing congestion, and transshipment queue delays**.

### Key Baseline vs. Production Metrics
* **Baseline OSRM + Time Features MAE:** 47.9 minutes (only 28.6% of predictions within ±15% of actual).
* **Graph-Enhanced Model MAE:** **33.6 minutes** (**43.9% of predictions within ±15%** of actual — a **29.8% precision improvement**).
* **Network Scope Monitored:** 1,609 active transit facilities and 2,580 inter-facility corridors.
* **Identified Chronic Delay Corridors:** 2,480 corridors exhibiting median delay ratio > 1.20x OSRM baseline.

The persistent gap between OSRM promises and customer delivery reality has been the primary driver of customer SLA penalties, cascading trailer misconnections, and broken sorting schedules.

---

## 2. Structural Bottleneck Hubs (Top 5 Priority Interventions)

Centrality and flow modeling on the directed delivery graph identifies that delay is concentrated in a tiny fraction of critical distribution centers. High betweenness centrality combined with transshipment congestion turns these facilities into network choke points:

| Priority | Facility Code | Hub Name & Location | Betweenness Centrality | PageRank | SLA Breach Contribution | Primary Operational Issue |
|:---:|:---:|:---|:---:|:---:|:---:|:---|
| **#1** | `IND000000ACB` | **Gurgaon Bilaspur Mega-Hub (Haryana)** | **0.2192** | **0.01054** | **1,842.0** | Inbound trailer dwell > 3.4 hrs; dock queuing spillover during evening peak (18:00–22:00). |
| **#2** | `IND562132AAA` | **Bangalore Nelamangala Hub (Karnataka)** | **0.1154** | **0.00953** | **1,286.5** | South-corridor consolidation choke; heavy Carting vehicle turnaround latency. |
| **#3** | `IND501359AAE` | **Hyderabad Shamshabad Hub (Telangana)** | **0.0817** | **0.00934** | **948.0** | Cross-dock transshipment delay connecting western and southern transit corridors. |
| **#4** | `IND421302AAG` | **Bhiwandi Mankoli Mega-Hub (Maharashtra)** | **0.0591** | **0.00673** | **892.3** | High degree feeder convergence; entry congestion on NH48 freight approach corridors. |
| **#5** | `IND160002AAC` | **Chandigarh Mehmdpur Hub (Punjab)** | **0.0517** | **0.00949** | **781.4** | Upper North linehaul turnaround and seasonal weather staging buffers. |

### Immediate Hub Action Directives:
1. **Dynamic Dock Staging at Bilaspur & Nelamangala:** Enforce pre-scheduled linehaul appointment slots (`±30 min`) rather than first-come-first-served trailer admission.
2. **Dedicated Fast-Track Bays for High-Centrality Linehauls:** Corridors with betweenness > 0.05 must receive dedicated dock clearance to avoid starvation from local feeder unloading.

---

## 3. FTL vs. Carting Strategic Routing Rules

Empirical analysis of 26,368 completed hop records across distance tiers reveals clear structural cost and delay differentials between Full Truckload (FTL) and multi-stop Carting feeder routes:

```
+----------------------------------------------------------------------------------------------------+
| Distance Band | Carting Median Ratio | Carting SLA Breach | FTL Median Ratio | FTL SLA Breach | Action |
|---------------|----------------------|--------------------|------------------|----------------|--------|
| < 50 km       | 2.15x OSRM           | 94.3%              | 1.84x OSRM       | 91.7%          | SHIFT  |
| 50 - 150 km   | 2.09x OSRM           | 97.6%              | 2.00x OSRM       | 95.9%          | SHIFT  |
| 150 - 400 km  | 1.97x OSRM           | 100.0%             | 1.93x OSRM       | 99.7%          | SELECT |
| 400 - 1000 km | N/A (Consolidated)   | N/A                | 1.94x OSRM       | 100.0%         | FTL    |
| 1000+ km      | N/A (Direct Trunk)   | N/A                | 1.95x OSRM       | 100.0%         | FTL    |
+----------------------------------------------------------------------------------------------------+
```

### Policy Rules for Dispatchers:
1. **Under 50 km (Short-haul Feeder):**
   * *Rule:* Shift high-volume Carting runs to dedicated small-format FTL shuttles where vehicle utilization exceeds 70%. Carting incurs severe staging and multi-drop penalties (+16.8% higher delay ratio than FTL).
2. **50–150 km (Regional Distribution):**
   * *Rule:* Shift Carting volume to direct FTL point-to-point where daily parcel count justifies a 14-ft/20-ft vehicle. Bypassing intermediate mother-hub sorting saves an average of 42 minutes per shipment.
3. **150–400 km (Inter-city Corridors):**
   * *Rule:* Use Carting only for low-density secondary hubs; enforce FTL for express and committed SLA tiers.
4. **400 km+ (National Long-Haul):**
   * *Rule:* 100% FTL linehaul. Enforce dual-driver crew rotations on routes exceeding 800 km to eliminate night-time driver rest delays.

---

## 4. Operational Playbook for Network Dispatchers

When dispatching any hop via the **ETA Predictor**:
1. Check the **Predicted vs. OSRM Ratio**. If the ratio exceeds **1.50x**, verify corridor historical friction and review departure time against peak gate congestion hours (17:00–21:00).
2. Inspect the **Facility & Corridor Trust Badges**:
   * If `source_known_facility == false` or `corridor_seen_in_training == false`: Apply an additional 15% operational buffer, as the estimate relies on network-median graph fallback features.
   * If both flags are `known`: Commit the ETA directly to downstream sorting schedules and driver manifest cutoffs.

---

## 5. Retraining Cadence & Governance Controls

* **Mandatory Monthly Retrain:** Run `train_and_export.py` on the 1st of each calendar month to capture new facility launches, updated corridor speeds, and seasonal shifts.
* **Regression Quality Gate:** The production model must meet or exceed **MAE ≤ 35.0 min** and **% within 15% ≥ 40.0%** before the artifact directory can be replaced in deployment.
* **Drift Monitoring Alert:** If unobserved facility queries exceed 10% of total API volume over a 72-hour rolling window, an off-cycle retrain will be automatically triggered.
