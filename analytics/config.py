"""Configuration for the tennis analytics pipeline."""

import os

# ── Sackmann GitHub raw base URLs ────────────────────────────────────────────
SACKMANN_ATP = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
SACKMANN_WTA = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"

# ── Local paths ──────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_ROOT, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
MODEL_PATH = os.path.join(DATA_DIR, "model", "model.json")

# ── Training parameters ─────────────────────────────────────────────────────
TRAINING_YEAR_START = 2005
TRAINING_YEAR_END = 2027        # exclusive
MIN_MATCHES_FOR_STATS = 5      # min matches before a player's stats are used
CACHE_TTL_HOURS = 24            # re-fetch CSVs after this many hours

# ── Feature names (order matters — must match model coefficients) ────────────
FEATURES = [
    "rank_diff",
    "rank_ratio",
    "points_diff",
    "points_ratio",
    "age_diff",
    "height_diff",
    "h2h_ratio",
    "p1_win_rate_52w",
    "p2_win_rate_52w",
    "p1_surface_win_rate",
    "p2_surface_win_rate",
    "p1_ace_rate",
    "p2_ace_rate",
    "p1_bp_save_rate",
    "p2_bp_save_rate",
    "p1_first_serve_win_pct",
    "p2_first_serve_win_pct",
    "surface_clay",
    "surface_grass",
    "surface_hard",
    "surface_carpet",
    "best_of_5",
]
