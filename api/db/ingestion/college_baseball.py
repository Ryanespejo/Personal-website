"""
College Baseball data ingestion into Neo4j.

Pulls game and team data from the ESPN public API (same source as
/api/college-baseball.py) and upserts Team and Match nodes.

Usage (standalone):
    python -m api.db.ingestion.college_baseball
    python -m api.db.ingestion.college_baseball --date 2025-05-10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from api.db.neo4j_client import run_batch_write  # noqa: E402

_ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/scoreboard"
)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SportsDB/1.0)"}


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


_UPSERT_TEAMS = """
UNWIND $rows AS r
MERGE (t:Team {id: r.id})
SET t.name         = r.name,
    t.display_name = r.display_name,
    t.abbreviation = r.abbreviation,
    t.city         = r.city,
    t.sport        = 'college_baseball'
WITH t
MATCH (s:Sport {name: 'college_baseball'})
MERGE (t)-[:BELONGS_TO]->(s)
"""

_UPSERT_MATCHES = """
UNWIND $rows AS r
MERGE (m:Match {id: r.id})
SET m.date         = r.date,
    m.status       = r.status,
    m.home_score   = r.home_score,
    m.away_score   = r.away_score,
    m.sport        = 'college_baseball',
    m.venue        = r.venue,
    m.conference   = r.conference

WITH m, r
MATCH (home:Team {id: r.home_team_id})
MERGE (home)-[hr:PLAYED_IN]->(m)
SET hr.home           = true,
    hr.score          = r.home_score,
    hr.opponent_score = r.away_score

WITH m, r
MATCH (away:Team {id: r.away_team_id})
MERGE (away)-[ar:PLAYED_IN]->(m)
SET ar.home           = false,
    ar.score          = r.away_score,
    ar.opponent_score = r.home_score
"""


def ingest_date(date_str: str = "", verbose: bool = True) -> dict[str, int]:
    """
    Ingest one day's college baseball scoreboard into Neo4j.

    date_str: ISO date e.g. '2025-05-10', or '' for today.
    """
    url = _ESPN_SCOREBOARD
    if date_str:
        url += f"?dates={date_str.replace('-', '')}&limit=200"
    else:
        url += "?limit=200"

    if verbose:
        label = date_str or "today"
        print(f"Fetching college baseball scoreboard ({label}) from ESPN...")

    data   = _fetch_json(url)
    events = data.get("events", [])

    team_rows:  dict[str, dict] = {}
    match_rows: list[dict]      = []

    for event in events:
        for comp in (event.get("competitions") or []):
            competitors = comp.get("competitors") or []
            if len(competitors) < 2:
                continue

            home_comp = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away_comp = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

            for c in competitors:
                t   = c.get("team") or {}
                tid = str(t.get("id", ""))
                if not tid:
                    continue
                team_rows[f"cbaseball_{tid}"] = {
                    "id":           f"cbaseball_{tid}",
                    "name":         t.get("name", ""),
                    "display_name": t.get("displayName", ""),
                    "abbreviation": t.get("abbreviation", ""),
                    "city":         t.get("location", ""),
                }

            def _score(c: dict) -> int | None:
                s = c.get("score", "")
                return int(s) if s and str(s).isdigit() else None

            venue_obj  = comp.get("venue")  or {}
            status_obj = comp.get("status") or {}
            # Pull conference/group info when available
            conf = ""
            for note in (event.get("notes") or []):
                if note.get("type") == "event":
                    conf = note.get("headline", "")
                    break

            home_tid = str((home_comp.get("team") or {}).get("id", ""))
            away_tid = str((away_comp.get("team") or {}).get("id", ""))

            match_rows.append({
                "id":           f"cbaseball_{comp.get('id', '')}",
                "date":         (comp.get("date") or "")[:10],
                "status":       (status_obj.get("type") or {}).get("description", ""),
                "home_team_id": f"cbaseball_{home_tid}",
                "away_team_id": f"cbaseball_{away_tid}",
                "home_score":   _score(home_comp),
                "away_score":   _score(away_comp),
                "venue":        venue_obj.get("fullName", ""),
                "conference":   conf,
            })

    if verbose:
        print(f"  {len(team_rows)} teams | {len(match_rows)} matches")

    total_teams   = run_batch_write(_UPSERT_TEAMS,   list(team_rows.values()))
    total_matches = run_batch_write(_UPSERT_MATCHES, match_rows)

    return {"teams": total_teams, "matches": total_matches}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest college baseball data into Neo4j")
    parser.add_argument("--date", default="", help="ISO date (YYYY-MM-DD), defaults to today")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    result = ingest_date(date_str=args.date, verbose=not args.quiet)
    print(f"Done: {result}")
