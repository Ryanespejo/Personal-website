"""Vercel serverless endpoint — tennis ML predictions.

GET /api/tennis-analytics?action=predict&player1=...&player2=...&tour=atp&surface=hard
GET /api/tennis-analytics?action=status

The heavy ML training happens offline (analytics/train.py).  This endpoint
loads the pre-trained model (JSON coefficients) and does lightweight
pure-Python inference — no numpy/sklearn imports at runtime.
"""

from http.server import BaseHTTPRequestHandler
import csv
import gzip
import io
import json
import math
import os
import time
import urllib.error
import urllib.request

# ── In-memory caches ─────────────────────────────────────────────────────────
_model_cache: dict = {}
_data_cache:  dict = {}
MODEL_CACHE_TTL  = 3600    # reload model file once per hour
DATA_CACHE_TTL   = 3600    # re-fetch Sackmann CSVs once per hour

SACKMANN_ATP = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
SACKMANN_WTA = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"

# Feature list must match analytics/config.py exactly
FEATURES = [
    "rank_diff", "rank_ratio", "points_diff", "points_ratio",
    "age_diff", "height_diff", "h2h_ratio",
    "p1_win_rate_52w", "p2_win_rate_52w",
    "p1_surface_win_rate", "p2_surface_win_rate",
    "p1_ace_rate", "p2_ace_rate",
    "p1_bp_save_rate", "p2_bp_save_rate",
    "p1_first_serve_win_pct", "p2_first_serve_win_pct",
    "surface_clay", "surface_grass", "surface_hard", "surface_carpet",
    "best_of_5",
]

FEATURE_LABELS = {
    "rank_diff":              "Ranking difference",
    "rank_ratio":             "Ranking closeness",
    "points_diff":            "Rating-points gap",
    "points_ratio":           "Rating-points ratio",
    "age_diff":               "Age difference",
    "height_diff":            "Height difference",
    "h2h_ratio":              "Head-to-head record",
    "p1_win_rate_52w":        "52-week win rate (P1)",
    "p2_win_rate_52w":        "52-week win rate (P2)",
    "p1_surface_win_rate":    "Surface win rate (P1)",
    "p2_surface_win_rate":    "Surface win rate (P2)",
    "p1_ace_rate":            "Ace rate (P1)",
    "p2_ace_rate":            "Ace rate (P2)",
    "p1_bp_save_rate":        "Break-point save % (P1)",
    "p2_bp_save_rate":        "Break-point save % (P2)",
    "p1_first_serve_win_pct": "1st-serve win % (P1)",
    "p2_first_serve_win_pct": "1st-serve win % (P2)",
    "surface_clay":           "Clay court",
    "surface_grass":          "Grass court",
    "surface_hard":           "Hard court",
    "surface_carpet":         "Carpet court",
    "best_of_5":              "Best-of-5 format",
}


# ── Model loading ────────────────────────────────────────────────────────────

def _load_model() -> dict | None:
    now = time.time()
    cached = _model_cache.get("m")
    if cached and now - cached["ts"] < MODEL_CACHE_TTL:
        return cached["data"]

    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "data", "model", "model.json")
    if not os.path.exists(path):
        return None

    with open(path, "r") as f:
        model = json.load(f)
    _model_cache["m"] = {"ts": now, "data": model}
    return model


# ── Pure-Python sigmoid + predict ────────────────────────────────────────────

def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _predict(model: dict, features: dict) -> dict:
    names  = model["features"]
    coefs  = model["coefficients"]
    bias   = model["intercept"]
    means  = model["scaler"]["mean"]
    scales = model["scaler"]["scale"]

    z = bias
    contribs: list[tuple[str, float, float]] = []
    for i, name in enumerate(names):
        raw = features.get(name, 0.0)
        s = (raw - means[i]) / scales[i] if scales[i] != 0 else 0.0
        c = coefs[i] * s
        z += c
        contribs.append((name, abs(c), c))

    prob = _sigmoid(z)
    contribs.sort(key=lambda x: x[1], reverse=True)
    key_factors = [
        {"feature": n, "label": FEATURE_LABELS.get(n, n),
         "impact": round(m, 3), "direction": "favors_p1" if d > 0 else "favors_p2"}
        for n, m, d in contribs[:5]
    ]
    return {
        "p1_win_prob": round(prob, 4),
        "p2_win_prob": round(1 - prob, 4),
        "confidence": round(abs(prob - 0.5) * 2, 4),
        "key_factors": key_factors,
    }


# ── Sackmann data helpers (lightweight, for live feature computation) ────────

def _fetch_csv_text(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 TennisAnalytics/1.0",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        if resp.info().get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")


def _get_matches(tour: str, year: int) -> list[dict]:
    key = f"{tour}_{year}"
    now = time.time()
    cached = _data_cache.get(key)
    if cached and now - cached["ts"] < DATA_CACHE_TTL:
        return cached["data"]

    base = SACKMANN_ATP if tour == "atp" else SACKMANN_WTA
    try:
        text = _fetch_csv_text(f"{base}/{tour}_matches_{year}.csv")
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception:
        rows = []
    _data_cache[key] = {"ts": now, "data": rows}
    return rows


def _sf(v, d=0.0):
    try:
        f = float(v)
        return f if math.isfinite(f) else d
    except (ValueError, TypeError):
        return d


def _compute_features(
    p1_name: str, p2_name: str, tour: str, surface: str,
    p1_rank: float, p2_rank: float, p1_points: float, p2_points: float,
    best_of: int = 3,
) -> dict:
    """Build feature dict from available parameters + recent Sackmann data."""
    import datetime
    year = datetime.datetime.now().year
    recent = _get_matches(tour, year)
    prev   = _get_matches(tour, year - 1)
    all_m  = prev + recent

    def _find_id(name: str) -> str:
        last = name.lower().strip().split()[-1] if name.strip() else ""
        for m in reversed(all_m):
            for role in ("winner", "loser"):
                mname = (m.get(f"{role}_name") or "").lower()
                if last and last in mname:
                    return m.get(f"{role}_id", "")
        return ""

    p1_id = _find_id(p1_name)
    p2_id = _find_id(p2_name)

    def _stats(pid: str, opp_id: str):
        w = l = sw = st = h2h_w = h2h_l = 0
        t_ace = t_svpt = t_1W = t_1I = t_bpS = t_bpF = 0
        for m in all_m:
            wid, lid = m.get("winner_id", ""), m.get("loser_id", "")
            surf = (m.get("surface") or "").lower()
            if wid == pid:
                w += 1
                if surface and surf == surface.lower():
                    sw += 1; st += 1
                if lid == opp_id: h2h_w += 1
                t_ace += int(m.get("w_ace") or 0)
                t_svpt += int(m.get("w_svpt") or 0)
                t_1W += int(m.get("w_1stWon") or 0)
                t_1I += int(m.get("w_1stIn") or 0)
                t_bpS += int(m.get("w_bpSaved") or 0)
                t_bpF += int(m.get("w_bpFaced") or 0)
            elif lid == pid:
                l += 1
                if surface and surf == surface.lower():
                    st += 1
                if wid == opp_id: h2h_l += 1
                t_ace += int(m.get("l_ace") or 0)
                t_svpt += int(m.get("l_svpt") or 0)
                t_1W += int(m.get("l_1stWon") or 0)
                t_1I += int(m.get("l_1stIn") or 0)
                t_bpS += int(m.get("l_bpSaved") or 0)
                t_bpF += int(m.get("l_bpFaced") or 0)
        total = w + l
        return {
            "wr": w / total if total else 0.5,
            "swr": sw / st if st else 0.5,
            "h2h_w": h2h_w, "h2h_l": h2h_l,
            "ace": t_ace / t_svpt if t_svpt else 0.0,
            "fsw": t_1W / t_1I if t_1I else 0.0,
            "bps": t_bpS / t_bpF if t_bpF else 0.0,
        }

    s1 = _stats(p1_id, p2_id) if p1_id else {"wr": .5, "swr": .5, "h2h_w": 0, "h2h_l": 0, "ace": 0, "fsw": 0, "bps": 0}
    s2 = _stats(p2_id, p1_id) if p2_id else {"wr": .5, "swr": .5, "h2h_w": 0, "h2h_l": 0, "ace": 0, "fsw": 0, "bps": 0}

    if p1_rank == 0: p1_rank = 500
    if p2_rank == 0: p2_rank = 500
    mr = max(p1_rank, p2_rank)
    mp = max(p1_points, p2_points, 1)
    h2h_t = s1["h2h_w"] + s1["h2h_l"]
    sl = (surface or "").lower()

    feats = {
        "rank_diff": p1_rank - p2_rank,
        "rank_ratio": min(p1_rank, p2_rank) / mr if mr else 0.5,
        "points_diff": p1_points - p2_points,
        "points_ratio": min(p1_points, p2_points) / mp if mp else 0.5,
        "age_diff": 0, "height_diff": 0,
        "h2h_ratio": s1["h2h_w"] / h2h_t if h2h_t else 0.5,
        "p1_win_rate_52w": s1["wr"], "p2_win_rate_52w": s2["wr"],
        "p1_surface_win_rate": s1["swr"], "p2_surface_win_rate": s2["swr"],
        "p1_ace_rate": s1["ace"], "p2_ace_rate": s2["ace"],
        "p1_bp_save_rate": s1["bps"], "p2_bp_save_rate": s2["bps"],
        "p1_first_serve_win_pct": s1["fsw"], "p2_first_serve_win_pct": s2["fsw"],
        "surface_clay": 1.0 if sl == "clay" else 0.0,
        "surface_grass": 1.0 if sl == "grass" else 0.0,
        "surface_hard": 1.0 if sl == "hard" else 0.0,
        "surface_carpet": 1.0 if sl == "carpet" else 0.0,
        "best_of_5": 1.0 if best_of == 5 else 0.0,
    }
    extra = {
        "h2h": {"p1_wins": s1["h2h_w"], "p2_wins": s1["h2h_l"], "total": h2h_t},
        "stats": {"p1": s1, "p2": s2},
        "p1_id": p1_id, "p2_id": p2_id,
    }
    return feats, extra


# ── Request handler ──────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        params = parse_qs(urlparse(self.path).query)
        action = (params.get("action") or ["predict"])[0]

        if action == "status":
            model = _load_model()
            if model:
                self._json(200, {"status": "ready", "model": model.get("metadata", {})})
            else:
                self._json(200, {"status": "no_model",
                                 "message": "Model not trained yet. Run: python analytics/train.py"})
            return

        if action == "predict":
            p1 = (params.get("player1") or [""])[0].strip()
            p2 = (params.get("player2") or [""])[0].strip()
            if not p1 or not p2:
                self._json(400, {"error": "player1 and player2 are required"})
                return

            model = _load_model()
            if not model:
                self._json(503, {"error": "Model not trained yet. Run: python analytics/train.py"})
                return

            tour     = (params.get("tour")      or ["atp"])[0].lower()
            surface  = (params.get("surface")   or ["hard"])[0].lower()
            p1_rank  = _sf((params.get("p1_rank")   or ["0"])[0])
            p2_rank  = _sf((params.get("p2_rank")   or ["0"])[0])
            p1_pts   = _sf((params.get("p1_points") or ["0"])[0])
            p2_pts   = _sf((params.get("p2_points") or ["0"])[0])
            best_of  = int((params.get("best_of")   or ["3"])[0])

            try:
                feats, extra = _compute_features(p1, p2, tour, surface,
                                                  p1_rank, p2_rank, p1_pts, p2_pts, best_of)
                pred = _predict(model, feats)
                pred.update({
                    "player1": p1, "player2": p2,
                    "tour": tour, "surface": surface,
                    "h2h": extra["h2h"],
                    "player_stats": extra["stats"],
                    "model_info": {
                        "accuracy": model.get("metadata", {}).get("accuracy"),
                        "auc": model.get("metadata", {}).get("auc"),
                        "trained_at": model.get("metadata", {}).get("trained_at"),
                    },
                })
                self._json(200, pred)
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

        self._json(400, {"error": f"Unknown action: {action}"})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass
