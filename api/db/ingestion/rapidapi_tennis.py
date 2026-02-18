"""
RapidAPI tennis events ingestion into Neo4j.

Transforms previous-events data returned by the RapidAPI tennis endpoint
(/api/tennis/player/{id}/events/previous/{page}) into the existing graph
schema: Player, Tournament, and Match nodes with PLAYED_IN and PART_OF
relationships.

All IDs are prefixed with "rapid_" to avoid collision with the Sackmann
historical data that uses numeric IDs like "atp_123456".

Usage (standalone):
    RAPIDAPI_KEY=<key> NEO4J_URI=<uri> NEO4J_PASSWORD=<pw> \\
        python -m api.db.ingestion.rapidapi_tennis --player-id 275923 --pages 2

Usage (from another module):
    from api.db.ingestion.rapidapi_tennis import fetch_and_ingest
    fetch_and_ingest("275923", pages=2)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

# Make sure repo root is on sys.path when run as __main__
_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from api.db.neo4j_client import run_batch_write  # noqa: E402

# ---------------------------------------------------------------------------
# RapidAPI config (mirrors tennis-analytics.py)
# ---------------------------------------------------------------------------

_BASE_URL   = os.getenv("RAPIDAPI_TENNIS_BASE_URL",  "https://tennisapi1.p.rapidapi.com")
_HOST       = os.getenv("RAPIDAPI_TENNIS_HOST",       "tennisapi1.p.rapidapi.com")
_API_KEY    = os.getenv("RAPIDAPI_KEY", "")
_PREV_PATH  = os.getenv(
    "RAPIDAPI_TENNIS_PREV_EVENTS_PATH",
    "/api/tennis/player/{player_id}/events/previous/{page}",
)
_TIMEOUT    = 12

# ---------------------------------------------------------------------------
# Surface normalisation
# ---------------------------------------------------------------------------

_SURFACE_MAP = {
    "hardcourt": "hard",
    "hard":      "hard",
    "clay":      "clay",
    "grass":     "grass",
    "carpet":    "carpet",
    "indoor":    "hard",   # rare – treat indoor as hard
}


def _normalise_surface(raw: str | None) -> str | None:
    if not raw:
        return None
    lowered = raw.lower()
    for key, val in _SURFACE_MAP.items():
        if key in lowered:
            return val
    return None


# ---------------------------------------------------------------------------
# Score formatting
# ---------------------------------------------------------------------------

def _format_score(home_score: dict, away_score: dict) -> str:
    """Build a set-by-set score string, e.g. '6-4 3-6 7-5'."""
    parts: list[str] = []
    for period in ("period1", "period2", "period3", "period4", "period5"):
        hs = home_score.get(period)
        aw = away_score.get(period)
        if hs is not None and aw is not None:
            parts.append(f"{hs}-{aw}")
    if parts:
        return " ".join(parts)
    # Fallback: just sets won
    hs_cur = home_score.get("current", "?")
    aw_cur = away_score.get("current", "?")
    return f"{hs_cur}-{aw_cur}"


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------

def _is_doubles(name: str) -> bool:
    """Doubles match names contain a '/' separator (e.g. 'Alcaraz C / Ruud C')."""
    return "/" in (name or "")


def parse_events(
    events: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """
    Parse a list of RapidAPI event dicts into four row-lists suitable for
    batch upsert into Neo4j:

        players      – Player node rows
        tournaments  – Tournament node rows
        matches      – Match node rows
        rel_rows     – PLAYED_IN relationship rows

    Doubles events are skipped (no stable single-player IDs in that context).
    Events without a winnerCode (abandoned, in-progress) are also skipped.
    """
    players:     dict[str, dict] = {}
    tournaments: dict[str, dict] = {}
    matches:     list[dict]      = []
    rel_rows:    list[dict]      = []

    for ev in events:
        event_id = ev.get("id")
        if event_id is None:
            continue

        # Skip events that haven't finished
        status = (ev.get("status") or {}).get("type", "")
        if status not in ("finished",):
            continue

        winner_code = ev.get("winnerCode")  # 1 = home wins, 2 = away wins
        if winner_code not in (1, 2):
            continue

        home = ev.get("homeTeam") or {}
        away = ev.get("awayTeam") or {}
        home_name = home.get("name") or ""
        away_name = away.get("name") or ""

        # Skip doubles
        if _is_doubles(home_name) or _is_doubles(away_name):
            continue

        home_raw_id = str(home.get("id") or "")
        away_raw_id = str(away.get("id") or "")
        if not home_raw_id or not away_raw_id:
            continue

        rapid_home_id = f"rapid_{home_raw_id}"
        rapid_away_id = f"rapid_{away_raw_id}"

        # ── Players ──────────────────────────────────────────────────────────
        home_country = (home.get("country") or {}).get("alpha3") or ""
        away_country = (away.get("country") or {}).get("alpha3") or ""

        players[rapid_home_id] = {
            "id":          rapid_home_id,
            "name":        home_name,
            "nationality": home_country,
            "rank":        home.get("ranking"),
            "sport":       "tennis",
        }
        players[rapid_away_id] = {
            "id":          rapid_away_id,
            "name":        away_name,
            "nationality": away_country,
            "rank":        away.get("ranking"),
            "sport":       "tennis",
        }

        # ── Tournament ───────────────────────────────────────────────────────
        tourn        = ev.get("tournament") or {}
        unique_tourn = tourn.get("uniqueTournament") or {}
        # Prefer the uniqueTournament ID (stable across editions) for deduplication
        tourn_raw_id = unique_tourn.get("id") or tourn.get("id") or ""
        tournament_id: str | None = f"rapid_{tourn_raw_id}" if tourn_raw_id else None

        if tournament_id and tournament_id not in tournaments:
            tourn_surface = _normalise_surface(unique_tourn.get("groundType"))
            tournaments[tournament_id] = {
                "id":      tournament_id,
                "name":    unique_tourn.get("name") or tourn.get("name") or "",
                "surface": tourn_surface,
                "sport":   "tennis",
            }

        # ── Match ────────────────────────────────────────────────────────────
        home_score = ev.get("homeScore") or {}
        away_score = ev.get("awayScore") or {}
        surface    = _normalise_surface(ev.get("groundType"))

        match_id = f"rapid_{event_id}"
        ts       = ev.get("startTimestamp")
        iso_date = time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else ""

        matches.append({
            "id":            match_id,
            "date":          iso_date,
            "surface":       surface,
            "score":         _format_score(home_score, away_score),
            "tournament_id": tournament_id,
            "sport":         "tennis",
            "source":        "rapidapi",
        })

        # ── Relationships ─────────────────────────────────────────────────────
        rel_rows.append({
            "match_id":      match_id,
            "home_id":       rapid_home_id,
            "away_id":       rapid_away_id,
            "home_result":   "win"  if winner_code == 1 else "loss",
            "away_result":   "win"  if winner_code == 2 else "loss",
            "home_rank":     home.get("ranking"),
            "away_rank":     away.get("ranking"),
            "tournament_id": tournament_id,
        })

    return list(players.values()), list(tournaments.values()), matches, rel_rows


# ---------------------------------------------------------------------------
# Cypher templates
# ---------------------------------------------------------------------------

_UPSERT_PLAYERS = """
UNWIND $rows AS r
MERGE (p:Player {id: r.id})
SET p.name        = r.name,
    p.nationality = r.nationality,
    p.sport       = 'tennis',
    p.rank        = r.rank,
    p.source      = 'rapidapi'
WITH p
MATCH (s:Sport {name: 'tennis'})
MERGE (p)-[:BELONGS_TO]->(s)
"""

_UPSERT_TOURNAMENTS = """
UNWIND $rows AS r
MERGE (t:Tournament {id: r.id})
SET t.name    = r.name,
    t.surface = r.surface,
    t.sport   = 'tennis',
    t.source  = 'rapidapi'
WITH t
MATCH (s:Sport {name: 'tennis'})
MERGE (t)-[:BELONGS_TO]->(s)
"""

_UPSERT_MATCHES = """
UNWIND $rows AS r
MERGE (m:Match {id: r.id})
SET m.date          = r.date,
    m.surface       = r.surface,
    m.score         = r.score,
    m.sport         = 'tennis',
    m.tournament_id = r.tournament_id,
    m.source        = 'rapidapi'
WITH m, r
OPTIONAL MATCH (t:Tournament {id: r.tournament_id})
FOREACH (_ IN CASE WHEN t IS NOT NULL THEN [1] ELSE [] END |
    MERGE (m)-[:PART_OF]->(t)
)
"""

_UPSERT_RELATIONSHIPS = """
UNWIND $rows AS r
MATCH (m:Match {id: r.match_id})
OPTIONAL MATCH (home:Player {id: r.home_id})
FOREACH (_ IN CASE WHEN home IS NOT NULL THEN [1] ELSE [] END |
    MERGE (home)-[rel:PLAYED_IN]->(m)
    SET rel.result        = r.home_result,
        rel.rank_at_match = r.home_rank
)
WITH m, r
OPTIONAL MATCH (away:Player {id: r.away_id})
FOREACH (_ IN CASE WHEN away IS NOT NULL THEN [1] ELSE [] END |
    MERGE (away)-[rel:PLAYED_IN]->(m)
    SET rel.result        = r.away_result,
        rel.rank_at_match = r.away_rank
)
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_events(events: list[dict], verbose: bool = True) -> dict[str, int]:
    """
    Upsert a list of raw RapidAPI event dicts into Neo4j.

    Steps:
        1. Upsert Player nodes
        2. Upsert Tournament nodes
        3. Upsert Match nodes + PART_OF relationships
        4. Upsert PLAYED_IN relationships

    Returns counts: {"players": N, "tournaments": N, "matches": N, "relationships": N}
    """
    players, tournaments, matches, rel_rows = parse_events(events)

    if verbose:
        print(
            f"  Parsed  → {len(players)} players | "
            f"{len(tournaments)} tournaments | "
            f"{len(matches)} matches"
        )

    if not matches:
        if verbose:
            print("  Nothing to ingest (no completed singles events found).")
        return {"players": 0, "tournaments": 0, "matches": 0, "relationships": 0}

    p_count = run_batch_write(_UPSERT_PLAYERS,       players)       if players       else 0
    t_count = run_batch_write(_UPSERT_TOURNAMENTS,   tournaments)   if tournaments   else 0
    m_count = run_batch_write(_UPSERT_MATCHES,       matches)
    r_count = run_batch_write(_UPSERT_RELATIONSHIPS, rel_rows)      if rel_rows      else 0

    if verbose:
        print(
            f"  Saved   → {p_count} players | {t_count} tournaments | "
            f"{m_count} matches | {r_count} relationship rows"
        )

    return {
        "players":       p_count,
        "tournaments":   t_count,
        "matches":       m_count,
        "relationships": r_count,
    }


def fetch_events(player_id: str, pages: int = 2) -> list[dict]:
    """
    Fetch up to `pages` pages of previous events from RapidAPI for one player.

    Returns a flat list of raw event dicts (duplicates removed by event ID).
    """
    if not _API_KEY:
        raise RuntimeError("RAPIDAPI_KEY environment variable is not set.")

    headers = {
        "User-Agent":      "TennisAnalytics/1.0",
        "Accept":          "application/json",
        "x-rapidapi-host": _HOST,
        "x-rapidapi-key":  _API_KEY,
    }

    all_events: dict[str, dict] = {}

    for page in range(pages):
        path = _PREV_PATH.format(player_id=player_id, page=page)
        url  = f"{_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
        req  = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            print(f"  Warning: failed to fetch page {page}: {exc}")
            break

        events = data.get("events") or []
        for ev in events:
            eid = ev.get("id")
            if eid is not None:
                all_events[str(eid)] = ev

        if not data.get("hasNextPage", False):
            break

    return list(all_events.values())


def fetch_and_ingest(
    player_id: str,
    pages: int = 2,
    verbose: bool = True,
) -> dict[str, int]:
    """
    Fetch previous events from RapidAPI for `player_id` and ingest into Neo4j.

    This is the main entry point for callers that don't already have the raw
    events list (e.g., the analytics endpoint after a prediction request).
    """
    if verbose:
        print(f"Fetching events for player {player_id} ({pages} page(s))...")

    events = fetch_events(player_id, pages=pages)

    if verbose:
        print(f"  Fetched {len(events)} raw events")

    return ingest_events(events, verbose=verbose)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch RapidAPI tennis events and ingest into Neo4j"
    )
    parser.add_argument(
        "--player-id", required=True,
        help="RapidAPI numeric player ID (e.g. 275923 for Carlos Alcaraz)",
    )
    parser.add_argument(
        "--pages", type=int, default=2,
        help="Number of event pages to fetch (default: 2, ~60 matches)",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    counts = fetch_and_ingest(
        player_id=args.player_id,
        pages=args.pages,
        verbose=not args.quiet,
    )
    print(f"\nDone: {counts}")
