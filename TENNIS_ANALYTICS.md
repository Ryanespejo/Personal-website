# Tennis Analytics & ML Match Predictions

Machine learning-powered tennis match prediction system integrated into the Tennis Live Center. Built on [Jeff Sackmann's](https://github.com/JeffSackmann) open tennis datasets (CC BY-NC-SA 4.0).

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Tennis Live Center                           │
│                        (tennis/index.html)                           │
│                                                                      │
│   Live Scores ──── Match Insights ──── ML Prediction (NEW)           │
│       │                  │                    │                       │
│   ESPN API          H2H / Form          /api/tennis-analytics        │
│   /api/tennis       /api/tennis-news     (pure-Python inference)     │
└──────────────────────────────────────────────────────────────────────┘
                                                │
                         ┌──────────────────────┘
                         ▼
              ┌─────────────────────┐
              │  data/model/        │   Pre-trained model (JSON)
              │    model.json       │   — coefficients, scaler, metadata
              └─────────────────────┘
                         ▲
                         │  Daily retrain (GitHub Action)
                         │
              ┌─────────────────────┐
              │  analytics/         │   Training pipeline
              │    train.py         │   — fetch → features → fit → save
              │    data_cache.py    │
              │    features.py      │
              │    model.py         │
              └─────────────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │  Jeff Sackmann's    │   Raw CSV data
              │  tennis_atp/        │   50+ years of ATP matches
              │  tennis_wta/        │   50+ years of WTA matches
              └─────────────────────┘
```

## Data Source

| Repository | Coverage | Files |
|---|---|---|
| [tennis_atp](https://github.com/JeffSackmann/tennis_atp) | 1968–present, tour + challengers + futures | `atp_matches_YYYY.csv`, `atp_players.csv`, `atp_rankings_current.csv` |
| [tennis_wta](https://github.com/JeffSackmann/tennis_wta) | 1968–present, tour + qualifying/ITF | `wta_matches_YYYY.csv`, `wta_players.csv`, `wta_rankings_current.csv` |

Match CSVs contain ~49 columns per row: tournament info, player biographics, rankings at time of match, and detailed serve statistics (aces, double faults, 1st/2nd serve won, break points saved/faced).

## ML Model

**Algorithm:** Logistic Regression (scikit-learn)

**Why logistic regression?** It's interpretable, fast to train, produces calibrated probabilities, and exports cleanly to JSON coefficients for pure-Python inference with zero heavy dependencies at runtime.

### Features (22 total)

| Category | Features |
|---|---|
| Rankings | `rank_diff`, `rank_ratio`, `points_diff`, `points_ratio` |
| Biographic | `age_diff`, `height_diff` |
| Head-to-head | `h2h_ratio` |
| Recent form | `p1_win_rate_52w`, `p2_win_rate_52w` |
| Surface form | `p1_surface_win_rate`, `p2_surface_win_rate` |
| Serve stats | `ace_rate`, `bp_save_rate`, `first_serve_win_pct` (per player) |
| Match context | `surface_clay/grass/hard/carpet`, `best_of_5` |

### Training Pipeline

1. **Fetch** — Downloads CSVs from Sackmann repos (2005–present by default)
2. **Player stats** — Walks matches chronologically to build rolling per-player statistics
3. **Feature engineering** — Converts each match to a 22-feature vector; randomly assigns player 1/2 to avoid label leakage
4. **Fit** — Trains logistic regression with 80/20 chronological split
5. **Export** — Saves coefficients + scaler as `data/model/model.json`

## Caching Strategy

| Layer | Cache TTL | Purpose |
|---|---|---|
| CSV file cache (`data/cache/`) | 24 hours | Avoid re-downloading unchanged CSVs from GitHub |
| API in-memory cache | 1 hour | Avoid re-fetching Sackmann data on every serverless cold start |
| Model file cache | 1 hour | Avoid re-reading model JSON on every request |
| GitHub Action | Runs daily at 06:00 UTC | Fetches fresh data, retrains, commits updated model |

## RapidAPI Custom Analytics (New)

`/api/tennis-analytics?action=predict` now optionally enriches predictions with RapidAPI Tennis data when `RAPIDAPI_KEY` is set.

- Pulls player lookup, player-level stats, and H2H from RapidAPI.
- Builds a lightweight custom score (`rapidapi_elo_logit_blend`) from rankings, points, W/L form, and H2H.
- Returns both custom model probabilities and an ensemble blend with the trained logistic model.
- Uses a **daily cache (24h)** so each RapidAPI key/player combo is fetched at most once per day.

### Environment variables

- `RAPIDAPI_KEY` (required to enable RapidAPI enrichment; `RAPIDAPI_TENNIS_KEY` also supported as fallback)
- `RAPIDAPI_TENNIS_BASE_URL` (default `https://tennisapi1.p.rapidapi.com`)
- `RAPIDAPI_TENNIS_HOST` (default `tennisapi1.p.rapidapi.com`)
- `RAPIDAPI_TENNIS_SEARCH_PATH` (default `/api/tennis/search/{query}`)
- `RAPIDAPI_TENNIS_PLAYER_STATS_PATH` (default `/api/tennis/player/{player_id}/stats`)
- `RAPIDAPI_TENNIS_H2H_PATH` (default `/api/tennis/h2h/{player1_id}/{player2_id}`)

If RapidAPI is unavailable, the endpoint still returns baseline ML predictions.

- If RapidAPI auth fails (401/403), the endpoint now gracefully falls back to baseline ML and returns a status message in `custom_analytics.rapidapi_status`.

## Usage

### Train the model locally

```bash
# Install training dependencies (not needed at runtime)
pip install -r requirements-analytics.txt

# Train with defaults (ATP + WTA, 2005–present)
python analytics/train.py

# ATP only, recent data
python analytics/train.py --tours atp --start-year 2015

# Force re-download all cached CSVs
python analytics/train.py --force
```

### API Endpoints

**Predict match outcome:**
```
GET /api/tennis-analytics?action=predict&player1=Carlos Alcaraz&player2=Jannik Sinner&tour=atp&surface=hard
```

Response:
```json
{
  "p1_win_prob": 0.5832,
  "p2_win_prob": 0.4168,
  "confidence": 0.1664,
  "key_factors": [
    {"feature": "rank_diff", "label": "Ranking difference", "impact": 0.342, "direction": "favors_p1"},
    {"feature": "p1_surface_win_rate", "label": "Surface win rate (P1)", "impact": 0.218, "direction": "favors_p1"}
  ],
  "player1": "Carlos Alcaraz",
  "player2": "Jannik Sinner",
  "h2h": {"p1_wins": 5, "p2_wins": 4, "total": 9},
  "model_info": {"accuracy": 0.665, "auc": 0.728}
}
```

**Check model status:**
```
GET /api/tennis-analytics?action=status
```

### Frontend

The ML prediction appears automatically in the Match Insights panel when you click any match. It shows:
- Win probability bar with percentages
- Confidence indicator
- Top 5 factors driving the prediction
- Model accuracy and training date

## Project Structure

```
analytics/
├── __init__.py          # Package init
├── config.py            # URLs, paths, feature list
├── data_cache.py        # Fetch & cache Sackmann CSVs
├── features.py          # Feature engineering & player stats
├── model.py             # Train (sklearn) + predict (pure Python)
└── train.py             # CLI training script

api/
└── tennis-analytics.py  # Vercel serverless endpoint

data/
├── cache/               # Cached CSV files (gitignored)
└── model/
    └── model.json       # Trained model coefficients

.github/workflows/
└── tennis-data-update.yml  # Daily cron: fetch → train → commit
```

## Design Decisions

- **Pure-Python inference**: The API endpoint uses only `math.exp()` for sigmoid — no numpy/sklearn at runtime. This keeps Vercel cold starts fast and deployment size small.
- **JSON model format**: Model weights stored as plain JSON (coefficients + scaler means/scales) instead of pickle. Portable, auditable, and small.
- **Chronological train/test split**: Prevents future data leaking into training. The model sees only past matches when evaluated.
- **Random p1/p2 assignment**: During training, winner/loser are randomly assigned as player 1 or 2 so the model can't learn that p1 always wins.
- **Daily GitHub Action**: Fetches the latest Sackmann data and retrains automatically. Model updates are committed back to the repo.

## Ideas for Expansion

- **Elo ratings**: Build a custom Elo system from historical results for a stronger ranking signal
- **Surface-specific models**: Train separate models for clay, grass, and hard courts
- **Tournament momentum**: Track performance within the current tournament (did the player struggle in early rounds?)
- **Fatigue signal**: Estimate match load from recent schedule density
- **Live odds integration**: Compare ML predictions against betting markets for value detection
- **Point-by-point data**: Use Sackmann's `tennis_slam_pointbypoint` repo for Grand Slam deep dives
- **Ensemble models**: Combine logistic regression with gradient boosting for better accuracy
- **Player embedding**: Use neural network embeddings to capture latent player styles

## Attribution

Match data from [Jeff Sackmann's tennis repositories](https://github.com/JeffSackmann) under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
