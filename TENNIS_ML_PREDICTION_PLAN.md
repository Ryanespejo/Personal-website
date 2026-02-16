# Tennis Match Prediction ML Plan

## 1) Problem framing and success criteria

- **Primary goal:** Predict pre-match win probability for Player A vs Player B.
- **Secondary goals:**
  - Explain *why* the model favors a player (feature-level explanations).
  - Produce stable probabilities that can be monitored and calibrated over time.
- **Success metrics:**
  - Classification: Log loss, Brier score, ROC-AUC, accuracy.
  - Calibration: Expected calibration error (ECE), reliability curves.
  - Business/product: % of matches with prediction coverage, latency per prediction, model freshness.

## 2) Data strategy

### Core historical data
- Use ATP/WTA historical results from Jeff Sackmann datasets (already used in this repo).
- Keep data separated by event date and build all rolling features strictly from prior matches.

### Optional enrichment
- Current ranking/points snapshots.
- Injury/news indicators (if available and reliable).
- Market odds (if legal/available) for benchmarking, not as training labels.

### RapidAPI recency layer (recommended)
Use RapidAPI tennis endpoints to inject **most recent, pre-match context** that static historical CSVs may miss:
- Player form snapshots (recent W/L, streaks, set-level trends).
- Updated rank/points and player profile stats.
- Fresh head-to-head results and matchup metadata.
- Injury/withdrawal flags if exposed by provider.

Design pattern:
1. Train the base model on stable historical data (Sackmann).
2. Fetch RapidAPI features at prediction time with a 24h cache.
3. Build a recency score from RapidAPI signals.
4. Blend base probability + recency score with calibrated weights.
5. Fall back cleanly to base model if RapidAPI fails/rate-limits.

### Data quality checks
- Duplicate match detection.
- Player identity normalization (name variants, IDs).
- Missingness profiling by column, tour, surface, and year.
- Leakage audit: ensure no post-match statistics enter feature vectors.

## 3) Feature engineering roadmap

### Baseline feature families
1. **Ranking strength**: rank difference, ranking points difference/ratio.
2. **Recent form**: last 5/10/20 matches win rate, rolling Elo delta.
3. **Surface skill**: clay/grass/hard-specific win rates and serve-return performance.
4. **Head-to-head**: lifetime and recent H2H, surface-filtered H2H.
5. **Serve/return quality**: ace%, double-fault%, first-serve-in%, break points saved/converted.
6. **Fatigue/travel proxies**: matches played in last 7/14 days, long-match frequency.
7. **Tournament context**: round, best-of-3/5, indoor/outdoor, altitude indicator if available.

### Guardrails
- Build features in chronological order only.
- Add feature availability tags (historical-only vs requires live API).
- Keep a versioned feature registry for reproducibility.
- Freeze and log RapidAPI response timestamp per prediction for auditability.
- Keep provider-mapping logic deterministic (name→player_id resolution + confidence checks).

## 4) Modeling approach (staged)

### Stage A: Strong interpretable baseline
- Logistic Regression + standardized features.
- Add regularization search (L1/L2/elastic net).
- Use probability calibration (Platt or isotonic) if needed.

### Stage B: Nonlinear tabular models
- Gradient boosting (XGBoost/LightGBM/CatBoost).
- Compare to baseline on out-of-time splits.
- Tune for log loss and calibration, not just accuracy.

### Stage C: Ensemble
- Blend calibrated logistic + boosted model + Elo-based prior.
- Use simple weighted average first, then stacking if lift is stable.

## 5) Validation framework

- **Out-of-time backtesting** (e.g., train up to year N, validate on N+1).
- Rolling-window evaluation by:
  - Tour (ATP/WTA)
  - Surface (hard/clay/grass)
  - Tournament tier (slam/masters/250 etc.)
- Report confidence intervals via bootstrap.
- Add challenger baseline comparisons:
  - Rank-only heuristic.
  - Elo-only model.

## 6) Explainability and product outputs

- Per-match output:
  - Win probability for each player.
  - Confidence band / uncertainty proxy.
  - Top contributing factors (e.g., SHAP for tree models, coefficient impact for logistic).
- Model-level dashboard:
  - 30/90-day performance trends.
  - Calibration drift.
  - Coverage and latency.

## 7) MLOps and deployment plan

- **Data pipeline:** daily ingestion + feature refresh with cache.
- **Training cadence:** daily/weekly retraining depending on drift.
- **Model registry:** save model artifact + schema + metrics + training data window.
- **Promotion policy:** deploy only if log loss and calibration beat production thresholds.
- **Runtime strategy:**
  - Keep lightweight inference path for serverless.
  - Fallback to baseline model when enrichment APIs fail.
  - Use stale-while-revalidate cache for RapidAPI data to reduce latency/cost.
  - Add rate-limit-aware retry/backoff + partial-response handling.

## 8) Monitoring and maintenance

- **Data drift:** feature distribution shift alerts by tour/surface.
- **Performance drift:** rolling log loss and Brier degradation alerts.
- **Calibration drift:** reliability bins monitored over trailing windows.
- **Operational alerts:** API timeout/error-rate monitoring.

## 9) Milestone timeline (example 8-week plan)

- **Week 1:** data audit, leakage tests, baseline split design.
- **Week 2:** feature registry v1 + logistic baseline retrain.
- **Week 3:** Elo module + fatigue/travel features.
- **Week 4:** gradient boosting experiments + calibration study.
- **Week 5:** ensemble prototype + explainability outputs.
- **Week 6:** backtesting by cohorts + error analysis.
- **Week 7:** productionization (registry, gating, monitoring).
- **Week 8:** shadow deployment, then full rollout if metrics pass.

## 10) Immediate next actions for this repo

1. Add explicit rolling backtest script (year-by-year evaluation).
2. Implement Elo feature generator and include it in `analytics/features.py`.
3. Add probability calibration step to training and persist calibration parameters.
4. Expand `/api/tennis-analytics` RapidAPI enrichment to include recency-form features (last N matches, streaks, updated points/rank) and return them in `custom_analytics` metadata.
5. Add a calibrated blend policy between logistic probability and RapidAPI recency score (with tunable weight by tour/surface).
6. Create a metrics report artifact committed by CI after each retrain, including blend-vs-baseline deltas.

