"""
NBA data ingestion into Neo4j.

Pulls game and team data from the ESPN public API (same source as /api/nba.py)
and upserts Team and Match nodes with PLAYED_IN relationships.

Graph model (NBA):
    (:Team  {id, name, city, abbreviation, conference, division, sport: 'nba'})
    (:Match {id, date, home_score, away_score, season, sport: 'nba'})
    (:Team)-[:PLAYED_IN {home: true|false,  score, opponent_score}]->(:Match)

Usage (standalone):
    python -m api.db.ingestion.nba
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from api.db.neo4j_client import run_batch_write  # noqa: E402

_ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)
_ESPN_TEAMS = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SportsDB/1.0)"}


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Cypher templates
# ---------------------------------------------------------------------------

_UPSERT_TEAMS = """
UNWIND $rows AS r
MERGE (t:Team {id: r.id})
SET t.name         = r.name,
    t.display_name = r.display_name,
    t.abbreviation = r.abbreviation,
    t.city         = r.city,
    t.color        = r.color,
    t.sport        = 'nba'
WITH t
MATCH (s:Sport {name: 'nba'})
MERGE (t)-[:BELONGS_TO]->(s)
"""

_UPSERT_MATCHES = """
UNWIND $rows AS r
MERGE (m:Match {id: r.id})
SET m.date         = r.date,
    m.status       = r.status,
    m.home_score   = r.home_score,
    m.away_score   = r.away_score,
    m.sport        = 'nba',
    m.season_year  = r.season_year,
    m.season_type  = r.season_type,
    m.venue        = r.venue

WITH m, r
MATCH (home:Team {id: r.home_team_id})
MERGE (home)-[hr:PLAYED_IN]->(m)
SET hr.home             = true,
    hr.score            = r.home_score,
    hr.opponent_score   = r.away_score

WITH m, r
MATCH (away:Team {id: r.away_team_id})
MERGE (away)-[ar:PLAYED_IN]->(m)
SET ar.home             = false,
    ar.score            = r.away_score,
    ar.opponent_score   = r.home_score
"""


def _parse_competitor(comp: dict, event: dict) -> dict[str, Any] | None:
    team = comp.get("team") or {}
    tid  = str(team.get("id", ""))
    if not tid:
        return None

    score_str = comp.get("score", "")
    score     = int(score_str) if score_str and score_str.isdigit() else None
    is_home   = comp.get("homeAway") == "home"

    return {
        "team_id":  f"nba_{tid}",
        "is_home":  is_home,
        "score":    score,
    }


def ingest_today(verbose: bool = True) -> dict[str, int]:
    """
    Ingest today's NBA scoreboard (teams + games) into Neo4j.
    Returns {"teams": N, "matches": N}.
    """
    if verbose:
        print("Fetching NBA scoreboard from ESPN...")

    data = _fetch_json(_ESPN_SCOREBOARD)
    events = data.get("events", [])

    team_rows:  dict[str, dict] = {}
    match_rows: list[dict]      = []

    for event in events:
        comps = event.get("competitions") or []
        for comp in comps:
            competitors = comp.get("competitors") or []
            if len(competitors) < 2:
                continue

            parsed = [_parse_competitor(c, event) for c in competitors]
            parsed = [p for p in parsed if p]
            if len(parsed) < 2:
                continue

            home = next((p for p in parsed if p["is_home"]),  parsed[0])
            away = next((p for p in parsed if not p["is_home"]), parsed[1])

            # Collect teams
            for c in competitors:
                t = c.get("team") or {}
                tid = str(t.get("id", ""))
                if not tid:
                    continue
                record = t.get("record") or []
                team_rows[f"nba_{tid}"] = {
                    "id":           f"nba_{tid}",
                    "name":         t.get("name", ""),
                    "display_name": t.get("displayName", ""),
                    "abbreviation": t.get("abbreviation", ""),
                    "city":         t.get("location", ""),
                    "color":        t.get("color", ""),
                }

            # Collect match
            season     = data.get("season") or {}
            status_obj = comp.get("status") or {}
            status_type = status_obj.get("type") or {}
            venue_obj  = comp.get("venue") or {}

            date_str = (comp.get("date") or "")[:10]
            match_id = f"nba_{comp.get('id', '')}"

            match_rows.append({
                "id":           match_id,
                "date":         date_str,
                "status":       status_type.get("description", ""),
                "home_team_id": home["team_id"],
                "away_team_id": away["team_id"],
                "home_score":   home["score"],
                "away_score":   away["score"],
                "season_year":  season.get("year"),
                "season_type":  season.get("type", {}).get("name", ""),
                "venue":        venue_obj.get("fullName", ""),
            })

    if verbose:
        print(f"  {len(team_rows)} teams | {len(match_rows)} matches")

    total_teams   = run_batch_write(_UPSERT_TEAMS,   list(team_rows.values()))
    total_matches = run_batch_write(_UPSERT_MATCHES, match_rows)

    return {"teams": total_teams, "matches": total_matches}


if __name__ == "__main__":
    result = ingest_today()
    print(f"Done: {result}")
