"""
Tennis data ingestion into Neo4j.

Reads Jeff Sackmann match CSVs (already downloaded by the analytics pipeline)
and upserts Player, Tournament, and Match nodes plus their relationships.

CSV columns used (Sackmann format):
  tourney_id, tourney_name, surface, tourney_level, tourney_date
  winner_id, winner_name, winner_hand, winner_ht, winner_ioc, winner_age,
  winner_rank, winner_rank_points
  loser_id, loser_name, loser_hand, loser_ht, loser_ioc, loser_age,
  loser_rank, loser_rank_points
  score, best_of, round, minutes
  w_ace, w_df, w_svpt, w_1stIn, w_1stWon, w_2ndWon, w_SvGms, w_bpSaved, w_bpFaced
  l_ace, l_df, l_svpt, l_1stIn, l_1stWon, l_2ndWon, l_SvGms, l_bpSaved, l_bpFaced

Usage (standalone):
    python -m api.db.ingestion.tennis --tour atp --start-year 2020 --end-year 2026
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

# Make sure repo root is importable when running as __main__
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from api.db.neo4j_client import run_batch_write, run_write  # noqa: E402

# ---------------------------------------------------------------------------
# Sackmann data sources
# ---------------------------------------------------------------------------

_SACKMANN = {
    "atp": "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master",
    "wta": "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master",
}

_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SportsDB/1.0)"}


def _fetch_csv(url: str, timeout: int = 30) -> list[dict]:
    req = urllib.request.Request(url, headers=_HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _int(val: str | None) -> int | None:
    try:
        return int(val) if val and val.strip() else None
    except (ValueError, TypeError):
        return None


def _float(val: str | None) -> float | None:
    try:
        return float(val) if val and val.strip() else None
    except (ValueError, TypeError):
        return None


def _str(val: str | None) -> str | None:
    if val is None:
        return None
    s = val.strip()
    return s if s else None


# ---------------------------------------------------------------------------
# Cypher templates
# ---------------------------------------------------------------------------

# Upsert a batch of Player nodes.
_UPSERT_PLAYERS = """
UNWIND $rows AS r
MERGE (p:Player {id: r.id})
SET p.name          = r.name,
    p.hand          = r.hand,
    p.height_cm     = r.height_cm,
    p.nationality   = r.nationality,
    p.sport         = 'tennis',
    p.tour          = r.tour,
    p.rank          = r.rank,
    p.rank_points   = r.rank_points
WITH p
MATCH (s:Sport {name: 'tennis'})
MERGE (p)-[:BELONGS_TO]->(s)
"""

# Upsert a batch of Tournament nodes.
_UPSERT_TOURNAMENTS = """
UNWIND $rows AS r
MERGE (t:Tournament {id: r.id})
SET t.name    = r.name,
    t.surface = r.surface,
    t.level   = r.level,
    t.date    = r.date,
    t.sport   = 'tennis'
WITH t
MATCH (s:Sport {name: 'tennis'})
MERGE (t)-[:BELONGS_TO]->(s)
"""

# Upsert a batch of Match nodes + PLAYED_IN and PART_OF relationships.
_UPSERT_MATCHES = """
UNWIND $rows AS r
MERGE (m:Match {id: r.id})
SET m.date          = r.date,
    m.round         = r.round,
    m.surface       = r.surface,
    m.best_of       = r.best_of,
    m.score         = r.score,
    m.duration_min  = r.duration_min,
    m.sport         = 'tennis',
    m.tour          = r.tour,
    m.tournament_id = r.tournament_id

WITH m, r
MATCH (tournament:Tournament {id: r.tournament_id})
MERGE (m)-[:PART_OF]->(tournament)

WITH m, r
MATCH (winner:Player {id: r.winner_id})
MERGE (winner)-[wr:PLAYED_IN]->(m)
SET wr.result              = 'win',
    wr.aces                = r.w_ace,
    wr.double_faults       = r.w_df,
    wr.serve_points        = r.w_svpt,
    wr.first_serves_in     = r.w_1stIn,
    wr.first_serve_won     = r.w_1stWon,
    wr.second_serve_won    = r.w_2ndWon,
    wr.serve_games         = r.w_SvGms,
    wr.bp_saved            = r.w_bpSaved,
    wr.bp_faced            = r.w_bpFaced,
    wr.rank_at_match       = r.winner_rank,
    wr.rank_points_at_match= r.winner_rank_points

WITH m, r
MATCH (loser:Player {id: r.loser_id})
MERGE (loser)-[lr:PLAYED_IN]->(m)
SET lr.result              = 'loss',
    lr.aces                = r.l_ace,
    lr.double_faults       = r.l_df,
    lr.serve_points        = r.l_svpt,
    lr.first_serves_in     = r.l_1stIn,
    lr.first_serve_won     = r.l_1stWon,
    lr.second_serve_won    = r.l_2ndWon,
    lr.serve_games         = r.l_SvGms,
    lr.bp_saved            = r.l_bpSaved,
    lr.bp_faced            = r.l_bpFaced,
    lr.rank_at_match       = r.loser_rank,
    lr.rank_points_at_match= r.loser_rank_points
"""


# ---------------------------------------------------------------------------
# Data transformation helpers
# ---------------------------------------------------------------------------

def _parse_match_row(row: dict, tour: str) -> dict[str, Any] | None:
    """Transform one Sackmann CSV row into a flat dict suitable for Neo4j."""
    tourney_id  = _str(row.get("tourney_id"))
    winner_id   = _str(row.get("winner_id"))
    loser_id    = _str(row.get("loser_id"))
    match_num   = _str(row.get("match_num", "1"))
    tourney_date = _str(row.get("tourney_date", ""))

    if not all([tourney_id, winner_id, loser_id]):
        return None

    # Build a stable match ID from the source keys
    match_id = f"{tour}_{tourney_id}_{match_num}"

    # Derive ISO date from tourney_date (format: YYYYMMDD)
    iso_date = ""
    if tourney_date and len(tourney_date) == 8:
        iso_date = f"{tourney_date[:4]}-{tourney_date[4:6]}-{tourney_date[6:]}"

    return {
        "id":             match_id,
        "date":           iso_date,
        "round":          _str(row.get("round")),
        "surface":        (_str(row.get("surface")) or "").lower(),
        "best_of":        _int(row.get("best_of")),
        "score":          _str(row.get("score")),
        "duration_min":   _int(row.get("minutes")),
        "sport":          "tennis",
        "tour":           tour,
        "tournament_id":  f"{tour}_{tourney_id}",
        "winner_id":      f"{tour}_{winner_id}",
        "loser_id":       f"{tour}_{loser_id}",
        "winner_rank":         _int(row.get("winner_rank")),
        "winner_rank_points":  _int(row.get("winner_rank_points")),
        "loser_rank":          _int(row.get("loser_rank")),
        "loser_rank_points":   _int(row.get("loser_rank_points")),
        # Winner serve stats
        "w_ace":     _int(row.get("w_ace")),
        "w_df":      _int(row.get("w_df")),
        "w_svpt":    _int(row.get("w_svpt")),
        "w_1stIn":   _int(row.get("w_1stIn")),
        "w_1stWon":  _int(row.get("w_1stWon")),
        "w_2ndWon":  _int(row.get("w_2ndWon")),
        "w_SvGms":   _int(row.get("w_SvGms")),
        "w_bpSaved": _int(row.get("w_bpSaved")),
        "w_bpFaced": _int(row.get("w_bpFaced")),
        # Loser serve stats
        "l_ace":     _int(row.get("l_ace")),
        "l_df":      _int(row.get("l_df")),
        "l_svpt":    _int(row.get("l_svpt")),
        "l_1stIn":   _int(row.get("l_1stIn")),
        "l_1stWon":  _int(row.get("l_1stWon")),
        "l_2ndWon":  _int(row.get("l_2ndWon")),
        "l_SvGms":   _int(row.get("l_SvGms")),
        "l_bpSaved": _int(row.get("l_bpSaved")),
        "l_bpFaced": _int(row.get("l_bpFaced")),
    }


def _parse_player_from_row(row: dict, role: str, tour: str) -> dict[str, Any]:
    """Extract a player dict from a match row (role = 'winner' | 'loser')."""
    return {
        "id":          f"{tour}_{_str(row.get(f'{role}_id', ''))}",
        "name":        _str(row.get(f"{role}_name")),
        "hand":        _str(row.get(f"{role}_hand")),
        "height_cm":   _float(row.get(f"{role}_ht")),
        "nationality": _str(row.get(f"{role}_ioc")),
        "tour":        tour,
        "rank":        _int(row.get(f"{role}_rank")),
        "rank_points": _int(row.get(f"{role}_rank_points")),
    }


def _parse_tournament_from_row(row: dict, tour: str) -> dict[str, Any] | None:
    tourney_id = _str(row.get("tourney_id"))
    if not tourney_id:
        return None
    tourney_date = _str(row.get("tourney_date", ""))
    iso_date = ""
    if tourney_date and len(tourney_date) == 8:
        iso_date = f"{tourney_date[:4]}-{tourney_date[4:6]}-{tourney_date[6:]}"
    return {
        "id":      f"{tour}_{tourney_id}",
        "name":    _str(row.get("tourney_name")),
        "surface": (_str(row.get("surface")) or "").lower(),
        "level":   _str(row.get("tourney_level")),
        "date":    iso_date,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_year(tour: str, year: int, verbose: bool = True) -> dict[str, int]:
    """
    Fetch and ingest one year of Sackmann match data for a tour.

    Returns a dict: {"players": N, "tournaments": N, "matches": N}.
    """
    base = _SACKMANN[tour]
    url  = f"{base}/{tour}_matches_{year}.csv"

    if verbose:
        print(f"  Fetching {url}...")

    try:
        rows = _fetch_csv(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            if verbose:
                print(f"    Not found (year may not exist yet): {year}")
            return {"players": 0, "tournaments": 0, "matches": 0}
        raise

    if not rows:
        return {"players": 0, "tournaments": 0, "matches": 0}

    players: dict[str, dict] = {}
    tournaments: dict[str, dict] = {}
    matches: list[dict]         = []

    for row in rows:
        for role in ("winner", "loser"):
            p = _parse_player_from_row(row, role, tour)
            if p["id"]:
                players[p["id"]] = p

        t = _parse_tournament_from_row(row, tour)
        if t:
            tournaments[t["id"]] = t

        m = _parse_match_row(row, tour)
        if m:
            matches.append(m)

    if verbose:
        print(f"    {len(players)} players | {len(tournaments)} tournaments | {len(matches)} matches")

    total_players      = run_batch_write(_UPSERT_PLAYERS,      list(players.values()))
    total_tournaments  = run_batch_write(_UPSERT_TOURNAMENTS,  list(tournaments.values()))
    total_matches      = run_batch_write(_UPSERT_MATCHES,       matches)

    return {
        "players":     total_players,
        "tournaments": total_tournaments,
        "matches":     total_matches,
    }


def ingest_range(
    tours: list[str] | None = None,
    start_year: int = 2020,
    end_year: int = 2026,
    verbose: bool = True,
) -> dict[str, int]:
    """
    Ingest multiple years and tours in one call.

    Returns aggregated totals: {"players": N, "tournaments": N, "matches": N}.
    """
    if tours is None:
        tours = ["atp", "wta"]

    totals: dict[str, int] = {"players": 0, "tournaments": 0, "matches": 0}

    for tour in tours:
        if verbose:
            print(f"\n=== {tour.upper()} ===")
        for year in range(start_year, end_year + 1):
            t0 = time.time()
            counts = ingest_year(tour, year, verbose=verbose)
            elapsed = time.time() - t0
            for k in totals:
                totals[k] += counts[k]
            if verbose:
                print(f"    Done in {elapsed:.1f}s")

    return totals


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest tennis data into Neo4j")
    parser.add_argument("--tours", nargs="+", default=["atp", "wta"],
                        choices=["atp", "wta"])
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year",   type=int, default=2026)
    parser.add_argument("--quiet",      action="store_true")
    args = parser.parse_args()

    totals = ingest_range(
        tours=args.tours,
        start_year=args.start_year,
        end_year=args.end_year,
        verbose=not args.quiet,
    )
    print(f"\nIngestion complete: {totals}")
