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
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request
from api.db.neo4j_client import run_query

# ── In-memory caches ─────────────────────────────────────────────────────────
_model_cache: dict = {}
_data_cache:  dict = {}
MODEL_CACHE_TTL  = 3600    # reload model file once per hour
DATA_CACHE_TTL   = 3600    # re-fetch Sackmann CSVs once per hour
RAPID_CACHE_TTL  = 86400   # call RapidAPI at most once per day per cache key

SACKMANN_ATP = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
SACKMANN_WTA = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"

RAPIDAPI_BASE_URL = os.getenv("RAPIDAPI_TENNIS_BASE_URL", "https://tennisapi1.p.rapidapi.com")
RAPIDAPI_HOST = os.getenv("RAPIDAPI_TENNIS_HOST", "tennisapi1.p.rapidapi.com")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_SEARCH_PATH = os.getenv("RAPIDAPI_TENNIS_SEARCH_PATH", "/api/tennis/search/{query}")
RAPIDAPI_PLAYER_PATH = os.getenv("RAPIDAPI_TENNIS_PLAYER_PATH", "/api/tennis/player/{player_id}")
RAPIDAPI_PREV_EVENTS_PATH = os.getenv("RAPIDAPI_TENNIS_PREV_EVENTS_PATH", "/api/tennis/player/{player_id}/events/previous/{page}")
RAPIDAPI_TIMEOUT = 10
RAPID_CACHE_PATH = pathlib.Path("/tmp/rapid_tennis_cache.json")
RAPID_MATCH_PAGES = 2

ENSEMBLE_BASE_WEIGHTS = {
    "default": 0.22,
    "atp": 0.28,
    "wta": 0.26,
}

SURFACE_WEIGHT_BONUS = {
    "hard": 0.04,
    "clay": 0.02,
    "grass": 0.02,
    "carpet": 0.00,
}


NEO_CACHE_TTL = 3600


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


def _load_rapid_cache() -> dict:
    cached = _data_cache.get("rapid_daily")
    if cached:
        return cached
    if RAPID_CACHE_PATH.exists():
        try:
            with RAPID_CACHE_PATH.open("r", encoding="utf-8") as f:
                payload = json.load(f)
                if isinstance(payload, dict):
                    _data_cache["rapid_daily"] = payload
                    return payload
        except Exception:
            pass
    payload = {"records": {}}
    _data_cache["rapid_daily"] = payload
    return payload


def _save_rapid_cache(payload: dict):
    try:
        RAPID_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with RAPID_CACHE_PATH.open("w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass


def _rapid_fetch_json(path: str, params: dict | None = None) -> dict:
    if not RAPIDAPI_KEY:
        return {}
    q = ""
    if params:
        from urllib.parse import urlencode
        q = "?" + urlencode(params)
    url = f"{RAPIDAPI_BASE_URL.rstrip('/')}/{path.lstrip('/')}{q}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 TennisAnalytics/1.0",
        "Accept": "application/json",
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": RAPIDAPI_KEY,
    })
    with urllib.request.urlopen(req, timeout=RAPIDAPI_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _rapid_daily(key: str, loader) -> dict:
    now = time.time()
    cache = _load_rapid_cache()
    records = cache.setdefault("records", {})
    rec = records.get(key)
    if rec and now - rec.get("ts", 0) < RAPID_CACHE_TTL:
        return rec.get("data", {})

    data = loader()
    if data:
        records[key] = {"ts": now, "data": data}
        _save_rapid_cache(cache)
    return data


def _rapid_find_player_id(name: str) -> str:
    q = (name or "").strip()
    if not q or not RAPIDAPI_KEY:
        return ""

    def _loader():
        path = RAPIDAPI_SEARCH_PATH.format(query=urllib.parse.quote(q))
        return _rapid_fetch_json(path)

    data = _rapid_daily(f"search::{q.lower()}", _loader)
    candidates = data.get("results") or data.get("players") or data.get("data") or []
    if isinstance(candidates, dict):
        candidates = candidates.get("players") or []
    for c in candidates[:5]:
        # API wraps player data inside "entity" object
        entity = c.get("entity") or c
        pid = entity.get("id") or entity.get("player_id") or entity.get("playerId")
        if pid is not None:
            return str(pid)
    return ""


def _rapid_player_detail(player_id: str) -> dict:
    """Fetch player detail (ranking, name, etc.) from /api/tennis/player/{id}."""
    if not player_id:
        return {}

    def _loader():
        path = RAPIDAPI_PLAYER_PATH.format(player_id=player_id)
        return _rapid_fetch_json(path)

    return _rapid_daily(f"player_detail::{player_id}", _loader)


def _rapid_player_matches(player_id: str, page: int = 0) -> dict:
    if not player_id:
        return {}

    def _loader():
        path = RAPIDAPI_PREV_EVENTS_PATH.format(player_id=player_id, page=page)
        return _rapid_fetch_json(path)

    return _rapid_daily(f"prev_events::{player_id}::{page}", _loader)


def _rapid_recent_events(player_id: str, max_pages: int = RAPID_MATCH_PAGES) -> list[dict]:
    events: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(max_pages):
        raw = _rapid_player_matches(player_id, page=page)
        page_events = raw.get("events") or []
        if not page_events:
            break
        for ev in page_events:
            eid = str(ev.get("id") or "")
            if eid and eid in seen_ids:
                continue
            if eid:
                seen_ids.add(eid)
            events.append(ev)

    events.sort(key=lambda e: e.get("startTimestamp") or 0, reverse=True)
    return events


def _rank_to_elo(rank: float) -> float:
    """Convert ATP/WTA ranking to approximate Elo rating.

    Uses a logarithmic mapping so the gap between #1 and #5 is larger
    than between #95 and #100, reflecting actual skill distribution.
    Calibrated: #1 ≈ 2150, #10 ≈ 1870, #50 ≈ 1660, #100 ≈ 1570, #500 ≈ 1330.
    """
    if rank <= 0:
        return 1500.0
    return max(2150 - 120 * math.log(rank), 1200.0)


ELO_K = 32  # standard K-factor for tennis


def _rapid_fav_underdog(player_id: str) -> dict | None:
    """Compute favorite/underdog record from RapidAPI match history using Elo."""
    if not player_id or not RAPIDAPI_KEY:
        return None

    raw = _rapid_player_matches(player_id)
    events = raw.get("events") or []
    if not events:
        return None

    # Sort oldest-first so Elo accumulates chronologically
    sorted_ev = sorted(events, key=lambda e: e.get("startTimestamp") or 0)

    # Initialize player Elo from their ranking in the earliest match
    player_elo = 1500.0
    for ev in sorted_ev:
        home = ev.get("homeTeam") or {}
        away = ev.get("awayTeam") or {}
        hid = str(home.get("id") or "")
        aid = str(away.get("id") or "")
        if hid == player_id:
            r = _sf(home.get("ranking"), 0)
        elif aid == player_id:
            r = _sf(away.get("ranking"), 0)
        else:
            continue
        if r > 0:
            player_elo = _rank_to_elo(r)
            break

    fav_w = fav_l = dog_w = dog_l = 0
    for ev in sorted_ev:
        home = ev.get("homeTeam") or {}
        away = ev.get("awayTeam") or {}
        home_id = str(home.get("id") or "")
        away_id = str(away.get("id") or "")

        if home_id == player_id:
            opp_rank = _sf(away.get("ranking"), 0)
        elif away_id == player_id:
            opp_rank = _sf(home.get("ranking"), 0)
        else:
            continue

        if opp_rank <= 0:
            continue  # skip doubles / unranked
        opp_elo = _rank_to_elo(opp_rank)

        # Determine winner
        wc = ev.get("winnerCode")
        if wc == 1:
            won = (home_id == player_id)
        elif wc == 2:
            won = (away_id == player_id)
        else:
            continue

        # Favorite = higher Elo (captures form, not just ranking)
        is_fav = player_elo > opp_elo

        if is_fav:
            if won:
                fav_w += 1
            else:
                fav_l += 1
        else:
            if won:
                dog_w += 1
            else:
                dog_l += 1

        # Update running Elo
        expected = 1.0 / (1.0 + math.pow(10, (opp_elo - player_elo) / 400))
        player_elo += ELO_K * ((1.0 if won else 0.0) - expected)

    if (fav_w + fav_l + dog_w + dog_l) == 0:
        return None

    return {
        "fav_wins": fav_w, "fav_losses": fav_l,
        "fav_total": fav_w + fav_l,
        "fav_win_pct": round(fav_w / (fav_w + fav_l), 4) if (fav_w + fav_l) else 0,
        "dog_wins": dog_w, "dog_losses": dog_l,
        "dog_total": dog_w + dog_l,
        "dog_win_pct": round(dog_w / (dog_w + dog_l), 4) if (dog_w + dog_l) else 0,
        "current_elo": round(player_elo),
        "source": "rapidapi",
    }


def _extract_rapid_metrics(detail: dict, match_events: list, fallback_rank: float, fallback_points: float) -> dict:
    """Extract player metrics from /player/{id} detail and recent match history."""
    team = detail.get("team") or detail
    rank = _sf(team.get("ranking") or team.get("rank"), fallback_rank or 500)
    points = _sf(team.get("points") or team.get("rankingPoints"), fallback_points)

    pid = str(team.get("id") or "")
    wins = losses = 0
    recent_results: list[int] = []
    surface_record = {
        "hard": {"w": 0, "t": 0},
        "clay": {"w": 0, "t": 0},
        "grass": {"w": 0, "t": 0},
        "carpet": {"w": 0, "t": 0},
    }

    for ev in sorted(match_events, key=lambda e: e.get("startTimestamp") or 0, reverse=True):
        home = ev.get("homeTeam") or {}
        away = ev.get("awayTeam") or {}
        wc = ev.get("winnerCode")
        if not wc:
            continue

        in_match = False
        if str(home.get("id") or "") == pid:
            won = wc == 1
            in_match = True
        elif str(away.get("id") or "") == pid:
            won = wc == 2
            in_match = True
        if not in_match:
            continue

        if won:
            wins += 1
        else:
            losses += 1

        if len(recent_results) < 10:
            recent_results.append(1 if won else 0)

        gs = (ev.get("groundType") or {}).get("name")
        surface = str(gs or "").lower()
        if surface in surface_record:
            surface_record[surface]["t"] += 1
            if won:
                surface_record[surface]["w"] += 1

    total = wins + losses
    win_rate = wins / total if total else 0.5
    last_5 = recent_results[:5]
    last_10 = recent_results[:10]

    surface_win_rates = {
        key: (vals["w"] / vals["t"] if vals["t"] else 0.5)
        for key, vals in surface_record.items()
    }

    return {
        "rank": rank,
        "points": points,
        "wins": int(wins),
        "losses": int(losses),
        "win_rate": win_rate,
        "recent": {
            "last_5_win_rate": (sum(last_5) / len(last_5)) if last_5 else 0.5,
            "last_10_win_rate": (sum(last_10) / len(last_10)) if last_10 else 0.5,
            "sample_size": len(recent_results),
            "streak": _compute_streak(recent_results),
        },
        "surface_win_rates": surface_win_rates,
        "surface_sample": {k: v["t"] for k, v in surface_record.items()},
    }


def _compute_streak(results: list[int]) -> int:
    """Positive for win streak, negative for losing streak."""
    if not results:
        return 0
    first = results[0]
    streak = 0
    for r in results:
        if r != first:
            break
        streak += 1
    return streak if first == 1 else -streak


def _rapid_h2h_from_matches(p1_id: str, p2_id: str, p1_events: list, p2_events: list) -> dict:
    """Compute H2H record from both players' match histories."""
    p1_wins = p2_wins = 0
    seen = set()
    for ev in p1_events + p2_events:
        eid = ev.get("id")
        if eid in seen:
            continue
        seen.add(eid)
        home = ev.get("homeTeam") or {}
        away = ev.get("awayTeam") or {}
        hid = str(home.get("id") or "")
        aid = str(away.get("id") or "")
        # Only count matches between p1 and p2
        if not ({hid, aid} == {p1_id, p2_id}):
            continue
        wc = ev.get("winnerCode")
        if wc == 1:
            winner_id = hid
        elif wc == 2:
            winner_id = aid
        else:
            continue
        if winner_id == p1_id:
            p1_wins += 1
        elif winner_id == p2_id:
            p2_wins += 1
    return {"p1_wins": p1_wins, "p2_wins": p2_wins, "total": p1_wins + p2_wins}


def _custom_analytics(p1_name: str, p2_name: str, p1_rank: float, p2_rank: float, p1_points: float, p2_points: float) -> dict:
    p1_id = _rapid_find_player_id(p1_name)
    p2_id = _rapid_find_player_id(p2_name)

    # Fetch player details and recent match histories (multiple pages for recency quality)
    p1_detail = _rapid_player_detail(p1_id)
    p2_detail = _rapid_player_detail(p2_id)
    p1_events = _rapid_recent_events(p1_id)
    p2_events = _rapid_recent_events(p2_id)

    s1 = _extract_rapid_metrics(p1_detail, p1_events, p1_rank, p1_points)
    s2 = _extract_rapid_metrics(p2_detail, p2_events, p2_rank, p2_points)

    # Compute H2H from match histories (no dedicated H2H endpoint)
    h2h = _rapid_h2h_from_matches(p1_id, p2_id, p1_events, p2_events)
    h2h_total = h2h["total"]
    h2h_ratio = h2h["p1_wins"] / h2h_total if h2h_total else 0.5

    # Recency-aware custom score combining rank, points, overall form, short-form, streak and H2H.
    rank_gap = s2["rank"] - s1["rank"]
    points_gap = s1["points"] - s2["points"]
    form_gap = s1["win_rate"] - s2["win_rate"]
    recency5_gap = s1["recent"]["last_5_win_rate"] - s2["recent"]["last_5_win_rate"]
    recency10_gap = s1["recent"]["last_10_win_rate"] - s2["recent"]["last_10_win_rate"]
    streak_gap = s1["recent"]["streak"] - s2["recent"]["streak"]
    h2h_gap = h2h_ratio - 0.5

    custom_z = (
        (rank_gap * 0.011)
        + (points_gap * 0.00008)
        + (form_gap * 1.8)
        + (recency5_gap * 1.7)
        + (recency10_gap * 1.1)
        + (streak_gap * 0.12)
        + (h2h_gap * 1.3)
    )
    custom_prob = _sigmoid(custom_z)

    # Compute favorite/underdog from RapidAPI match history
    p1_fav_dog = _rapid_fav_underdog(p1_id)
    p2_fav_dog = _rapid_fav_underdog(p2_id)

    return {
        "rapidapi_enabled": bool(RAPIDAPI_KEY),
        "cache_ttl_hours": int(RAPID_CACHE_TTL / 3600),
        "data_freshness": {
            "p1_latest_match_ts": p1_events[0].get("startTimestamp") if p1_events else None,
            "p2_latest_match_ts": p2_events[0].get("startTimestamp") if p2_events else None,
            "events_scanned": {"p1": len(p1_events), "p2": len(p2_events)},
        },
        "player_ids": {"p1": p1_id, "p2": p2_id},
        "player_stats": {"p1": s1, "p2": s2},
        "h2h": {
            "p1_wins": h2h["p1_wins"],
            "p2_wins": h2h["p2_wins"],
            "total": h2h_total,
        },
        "fav_underdog": {"p1": p1_fav_dog, "p2": p2_fav_dog},
        "custom_model": {
            "type": "rapidapi_recency_logit_blend",
            "p1_win_prob": round(custom_prob, 4),
            "p2_win_prob": round(1 - custom_prob, 4),
            "components": {
                "rank_gap": round(rank_gap, 3),
                "points_gap": round(points_gap, 3),
                "form_gap": round(form_gap, 4),
                "recency5_gap": round(recency5_gap, 4),
                "recency10_gap": round(recency10_gap, 4),
                "streak_gap": int(streak_gap),
                "h2h_gap": round(h2h_gap, 4),
            },
        },
    }


def _neo_enabled() -> bool:
    return bool(os.getenv("NEO4J_URI") and os.getenv("NEO4J_PASSWORD"))


def _neo_cached(key: str, loader):
    now = time.time()
    rec = _data_cache.get(key)
    if rec and now - rec.get("ts", 0) < NEO_CACHE_TTL:
        return rec.get("data")
    data = loader()
    _data_cache[key] = {"ts": now, "data": data}
    return data


def _neo_find_player(name: str, tour: str) -> dict | None:
    q = (name or "").strip()
    if not q or not _neo_enabled():
        return None

    def _exact_loader():
        return run_query(
            """
            MATCH (p:Player {sport:'tennis'})
            WHERE toLower(p.name) = toLower($name)
              AND ($tour = '' OR p.tour = $tour)
            RETURN p.id AS id, p.name AS name,
                   coalesce(p.rank, 500) AS rank,
                   coalesce(p.rank_points, 0) AS points,
                   coalesce(p.tour, '') AS tour
            LIMIT 1
            """,
            {"name": q, "tour": tour or ""},
        )

    rows = _neo_cached(f"neo_find_exact::{tour}::{q.lower()}", _exact_loader)
    if rows:
        return rows[0]

    last = q.split()[-1].lower()
    def _fuzzy_loader():
        return run_query(
            """
            MATCH (p:Player {sport:'tennis'})
            WHERE toLower(p.name) CONTAINS $needle
              AND ($tour = '' OR p.tour = $tour)
            RETURN p.id AS id, p.name AS name,
                   coalesce(p.rank, 500) AS rank,
                   coalesce(p.rank_points, 0) AS points,
                   coalesce(p.tour, '') AS tour
            ORDER BY coalesce(p.rank, 9999) ASC
            LIMIT 3
            """,
            {"needle": last, "tour": tour or ""},
        )

    rows = _neo_cached(f"neo_find_fuzzy::{tour}::{last}", _fuzzy_loader)
    return rows[0] if rows else None


def _neo_player_recent_stats(player_id: str, surface: str) -> dict:
    if not player_id or not _neo_enabled():
        return {}

    def _loader():
        return run_query(
            """
            MATCH (:Player {id:$pid})-[r:PLAYED_IN]->(m:Match {sport:'tennis'})
            RETURN coalesce(r.result,'') AS result,
                   coalesce(m.surface,'') AS surface,
                   coalesce(m.date,'') AS date,
                   coalesce(r.aces,0) AS aces,
                   coalesce(r.serve_points,0) AS serve_points,
                   coalesce(r.first_serve_won,0) AS first_serve_won,
                   coalesce(r.first_serves_in,0) AS first_serves_in,
                   coalesce(r.bp_saved,0) AS bp_saved,
                   coalesce(r.bp_faced,0) AS bp_faced
            ORDER BY m.date DESC
            LIMIT 80
            """,
            {"pid": player_id},
        )

    rows = _neo_cached(f"neo_player_rows::{player_id}", _loader)
    wins = losses = 0
    sw = st = 0
    recent_results = []
    ace = svpt = fsw = fsi = bps = bpf = 0

    sl = (surface or "").lower()
    for row in rows:
        is_win = (row.get("result") == "win")
        if is_win:
            wins += 1
        else:
            losses += 1
        if len(recent_results) < 10:
            recent_results.append(1 if is_win else 0)
        if sl and row.get("surface") == sl:
            st += 1
            if is_win:
                sw += 1

        ace += int(row.get("aces") or 0)
        svpt += int(row.get("serve_points") or 0)
        fsw += int(row.get("first_serve_won") or 0)
        fsi += int(row.get("first_serves_in") or 0)
        bps += int(row.get("bp_saved") or 0)
        bpf += int(row.get("bp_faced") or 0)

    total = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / total) if total else 0.5,
        "recent": {
            "last_5_win_rate": (sum(recent_results[:5]) / len(recent_results[:5])) if recent_results[:5] else 0.5,
            "last_10_win_rate": (sum(recent_results) / len(recent_results)) if recent_results else 0.5,
            "sample_size": len(recent_results),
            "streak": _compute_streak(recent_results),
        },
        "surface_win_rate": (sw / st) if st else 0.5,
        "ace_rate": (ace / svpt) if svpt else 0.0,
        "first_serve_win_pct": (fsw / fsi) if fsi else 0.0,
        "bp_save_rate": (bps / bpf) if bpf else 0.0,
    }


def _neo_h2h(p1_id: str, p2_id: str) -> dict:
    if not p1_id or not p2_id or not _neo_enabled():
        return {"p1_wins": 0, "p2_wins": 0, "total": 0}

    def _loader():
        return run_query(
            """
            MATCH (:Player {id:$p1})-[r1:PLAYED_IN]->(m:Match)<-[r2:PLAYED_IN]-(:Player {id:$p2})
            RETURN coalesce(r1.result,'') AS p1_result
            ORDER BY m.date DESC
            LIMIT 30
            """,
            {"p1": p1_id, "p2": p2_id},
        )

    rows = _neo_cached(f"neo_h2h::{p1_id}::{p2_id}", _loader)
    p1_w = sum(1 for r in rows if r.get("p1_result") == "win")
    p2_w = sum(1 for r in rows if r.get("p1_result") == "loss")
    return {"p1_wins": p1_w, "p2_wins": p2_w, "total": p1_w + p2_w}


def _neo_custom_analytics(
    p1_name: str,
    p2_name: str,
    tour: str,
    surface: str,
    p1_rank: float,
    p2_rank: float,
    p1_points: float,
    p2_points: float,
) -> dict | None:
    if not _neo_enabled():
        return None

    try:
        p1 = _neo_find_player(p1_name, tour)
        p2 = _neo_find_player(p2_name, tour)
        if not p1 or not p2:
            return None

        s1 = _neo_player_recent_stats(str(p1.get("id")), surface)
        s2 = _neo_player_recent_stats(str(p2.get("id")), surface)
        if not s1 or not s2:
            return None

        rank1 = _sf(p1.get("rank"), p1_rank or 500)
        rank2 = _sf(p2.get("rank"), p2_rank or 500)
        pts1 = _sf(p1.get("points"), p1_points)
        pts2 = _sf(p2.get("points"), p2_points)

        h2h = _neo_h2h(str(p1.get("id")), str(p2.get("id")))
        h2h_ratio = (h2h["p1_wins"] / h2h["total"]) if h2h["total"] else 0.5

        rank_gap = rank2 - rank1
        points_gap = pts1 - pts2
        form_gap = s1["win_rate"] - s2["win_rate"]
        recency5_gap = s1["recent"]["last_5_win_rate"] - s2["recent"]["last_5_win_rate"]
        recency10_gap = s1["recent"]["last_10_win_rate"] - s2["recent"]["last_10_win_rate"]
        streak_gap = s1["recent"]["streak"] - s2["recent"]["streak"]
        h2h_gap = h2h_ratio - 0.5

        z = (
            (rank_gap * 0.011)
            + (points_gap * 0.00008)
            + (form_gap * 1.8)
            + (recency5_gap * 1.7)
            + (recency10_gap * 1.1)
            + (streak_gap * 0.12)
            + (h2h_gap * 1.3)
        )
        cp = _sigmoid(z)

        return {
            "source": "neo4j",
            "neo4j_enabled": True,
            "player_ids": {"p1": str(p1.get("id")), "p2": str(p2.get("id"))},
            "player_stats": {
                "p1": {
                    "rank": rank1,
                    "points": pts1,
                    "wins": s1["wins"],
                    "losses": s1["losses"],
                    "win_rate": s1["win_rate"],
                    "recent": s1["recent"],
                    "surface_win_rate": s1["surface_win_rate"],
                },
                "p2": {
                    "rank": rank2,
                    "points": pts2,
                    "wins": s2["wins"],
                    "losses": s2["losses"],
                    "win_rate": s2["win_rate"],
                    "recent": s2["recent"],
                    "surface_win_rate": s2["surface_win_rate"],
                },
            },
            "h2h": h2h,
            "fav_underdog": {
                "p1": _rapid_fav_underdog(_rapid_find_player_id(p1_name)),
                "p2": _rapid_fav_underdog(_rapid_find_player_id(p2_name)),
            },
            "custom_model": {
                "type": "neo4j_recency_logit_blend",
                "p1_win_prob": round(cp, 4),
                "p2_win_prob": round(1 - cp, 4),
                "components": {
                    "rank_gap": round(rank_gap, 3),
                    "points_gap": round(points_gap, 3),
                    "form_gap": round(form_gap, 4),
                    "recency5_gap": round(recency5_gap, 4),
                    "recency10_gap": round(recency10_gap, 4),
                    "streak_gap": int(streak_gap),
                    "h2h_gap": round(h2h_gap, 4),
                },
            },
        }
    except Exception:
        return None


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

    # Compute favorite/underdog stats using Elo (adjusts for form, not just ranking)
    def _fav_underdog(pid: str):
        # Initialize Elo from the player's earliest available ranking
        elo = 1500.0
        for m in all_m:
            wid, lid = m.get("winner_id", ""), m.get("loser_id", "")
            if wid == pid:
                r = _sf(m.get("winner_rank"), 0)
                if r > 0:
                    elo = _rank_to_elo(r)
                    break
            elif lid == pid:
                r = _sf(m.get("loser_rank"), 0)
                if r > 0:
                    elo = _rank_to_elo(r)
                    break

        fav_w = fav_l = dog_w = dog_l = 0
        for m in all_m:
            wid, lid = m.get("winner_id", ""), m.get("loser_id", "")
            if wid != pid and lid != pid:
                continue
            if wid == pid:
                opp_rank = _sf(m.get("loser_rank"), 0)
                won = True
            else:
                opp_rank = _sf(m.get("winner_rank"), 0)
                won = False
            if opp_rank <= 0:
                continue
            opp_elo = _rank_to_elo(opp_rank)

            # Favorite = higher Elo
            is_fav = elo > opp_elo
            if is_fav:
                if won:
                    fav_w += 1
                else:
                    fav_l += 1
            else:
                if won:
                    dog_w += 1
                else:
                    dog_l += 1

            # Update running Elo after this match
            expected = 1.0 / (1.0 + math.pow(10, (opp_elo - elo) / 400))
            elo += ELO_K * ((1.0 if won else 0.0) - expected)

        if (fav_w + fav_l + dog_w + dog_l) == 0:
            return None
        return {
            "fav_wins": fav_w, "fav_losses": fav_l,
            "fav_total": fav_w + fav_l,
            "fav_win_pct": round(fav_w / (fav_w + fav_l), 4) if (fav_w + fav_l) else 0,
            "dog_wins": dog_w, "dog_losses": dog_l,
            "dog_total": dog_w + dog_l,
            "dog_win_pct": round(dog_w / (dog_w + dog_l), 4) if (dog_w + dog_l) else 0,
            "current_elo": round(elo),
        }

    p1_fav_dog = _fav_underdog(p1_id) if p1_id else None
    p2_fav_dog = _fav_underdog(p2_id) if p2_id else None

    extra = {
        "h2h": {"p1_wins": s1["h2h_w"], "p2_wins": s1["h2h_l"], "total": h2h_t},
        "stats": {"p1": s1, "p2": s2},
        "p1_id": p1_id, "p2_id": p2_id,
        "fav_underdog": {"p1": p1_fav_dog, "p2": p2_fav_dog},
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
                custom = _neo_custom_analytics(
                    p1, p2, tour, surface, p1_rank, p2_rank, p1_pts, p2_pts
                )
                if not custom:
                    custom = _custom_analytics(p1, p2, p1_rank, p2_rank, p1_pts, p2_pts)
                custom_prob = ((custom.get("custom_model") or {}).get("p1_win_prob"))
                if isinstance(custom_prob, (int, float)):
                    base_weight = ENSEMBLE_BASE_WEIGHTS.get(tour, ENSEMBLE_BASE_WEIGHTS["default"])
                    weight = min(0.45, max(0.10, base_weight + SURFACE_WEIGHT_BONUS.get(surface, 0.0)))
                    blended = (pred["p1_win_prob"] * (1 - weight)) + (custom_prob * weight)
                    pred["ensemble_win_prob"] = {
                        "p1": round(blended, 4),
                        "p2": round(1 - blended, 4),
                        "weights": {
                            "base_model": round(1 - weight, 3),
                            "live_recency": round(weight, 3),
                        },
                    }
                # Merge fav/underdog: prefer RapidAPI (richer match history),
                # fall back to Sackmann when RapidAPI has no data.
                sack_fd = extra.get("fav_underdog") or {}
                rapid_fd = custom.get("fav_underdog") or {}
                merged_fd = {}
                for pkey in ("p1", "p2"):
                    r = rapid_fd.get(pkey)
                    s = sack_fd.get(pkey)
                    if r and (r.get("fav_total", 0) + r.get("dog_total", 0)) > 0:
                        merged_fd[pkey] = r
                    elif s and (s.get("fav_total", 0) + s.get("dog_total", 0)) > 0:
                        s["source"] = "sackmann"
                        merged_fd[pkey] = s
                    else:
                        merged_fd[pkey] = None

                pred.update({
                    "player1": p1, "player2": p2,
                    "tour": tour, "surface": surface,
                    "h2h": extra["h2h"],
                    "player_stats": extra["stats"],
                    "fav_underdog": merged_fd,
                    "custom_analytics": custom,
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
