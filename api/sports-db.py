"""
/api/sports-db  — Neo4j sports database REST API.

GET /api/sports-db?action=status
    → Database connectivity and node/relationship counts.

GET /api/sports-db?action=players&sport=tennis&limit=20
    → Top-ranked players for a sport.

GET /api/sports-db?action=matches&sport=tennis&surface=clay&limit=20
    → Recent matches, optionally filtered by surface.

GET /api/sports-db?action=h2h&p1=<player_id>&p2=<player_id>
    → Head-to-head record between two tennis players.

GET /api/sports-db?action=player_stats&id=<player_id>
    → Match stats and win rate for a single player.

GET /api/sports-db?action=init_schema
    → One-time schema initialisation (constraints + indexes + seed nodes).
      Safe to call multiple times — all statements are idempotent.
"""

from __future__ import annotations

import json
import sys
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Ensure api/ is importable when Vercel executes this file directly.
_API_DIR = os.path.dirname(os.path.abspath(__file__))
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

from db.neo4j_client import verify_connectivity, run_query  # noqa: E402

# ---------------------------------------------------------------------------
# Query definitions
# ---------------------------------------------------------------------------

_Q_COUNTS = """
MATCH (n)
RETURN labels(n)[0] AS label, count(n) AS count
ORDER BY count DESC
"""

_Q_RELATIONSHIP_COUNTS = """
MATCH ()-[r]->()
RETURN type(r) AS type, count(r) AS count
ORDER BY count DESC
"""

_Q_PLAYERS = """
MATCH (p:Player {sport: $sport})
WHERE p.rank IS NOT NULL
RETURN p.id         AS id,
       p.name       AS name,
       p.nationality AS nationality,
       p.rank       AS rank,
       p.rank_points AS rank_points,
       p.hand       AS hand,
       p.height_cm  AS height_cm,
       p.tour       AS tour
ORDER BY p.rank ASC
LIMIT $limit
"""

_Q_MATCHES = """
MATCH (m:Match {sport: $sport})
WHERE ($surface = '' OR m.surface = $surface)
RETURN m.id       AS id,
       m.date     AS date,
       m.round    AS round,
       m.surface  AS surface,
       m.best_of  AS best_of,
       m.score    AS score,
       m.tour     AS tour
ORDER BY m.date DESC
LIMIT $limit
"""

_Q_H2H = """
MATCH (p1:Player {id: $p1_id})-[:PLAYED_IN]->(m:Match)<-[:PLAYED_IN]-(p2:Player {id: $p2_id})
WITH m,
     [(p1)-[r:PLAYED_IN]->(m) | r.result][0] AS p1_result
RETURN m.id      AS match_id,
       m.date    AS date,
       m.surface AS surface,
       m.round   AS round,
       m.score   AS score,
       p1_result AS p1_result
ORDER BY m.date DESC
LIMIT 50
"""

_Q_PLAYER_STATS = """
MATCH (p:Player {id: $player_id})-[r:PLAYED_IN]->(m:Match)
RETURN p.name        AS name,
       p.nationality AS nationality,
       p.rank        AS rank,
       p.tour        AS tour,
       count(m)      AS total_matches,
       sum(CASE WHEN r.result = 'win' THEN 1 ELSE 0 END)  AS wins,
       sum(CASE WHEN r.result = 'loss' THEN 1 ELSE 0 END) AS losses,
       avg(r.aces)                AS avg_aces,
       avg(r.double_faults)      AS avg_double_faults,
       avg(r.bp_saved * 1.0 / CASE WHEN r.bp_faced > 0 THEN r.bp_faced ELSE 1 END) AS bp_save_rate
"""

_Q_TOP_SURFACES = """
MATCH (p:Player {id: $player_id})-[r:PLAYED_IN]->(m:Match)
WITH m.surface AS surface,
     sum(CASE WHEN r.result = 'win' THEN 1 ELSE 0 END) AS wins,
     count(m) AS total
WHERE total > 0
RETURN surface,
       wins,
       total,
       round(wins * 100.0 / total, 1) AS win_pct
ORDER BY win_pct DESC
"""


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _action_status() -> dict:
    conn = verify_connectivity()
    if not conn["connected"]:
        return {
            "connected": False,
            "error": conn["error"],
        }

    node_counts = run_query(_Q_COUNTS)
    rel_counts  = run_query(_Q_RELATIONSHIP_COUNTS)

    return {
        "connected":       True,
        "server_info":     conn["server_info"],
        "address":         conn["address"],
        "protocol":        conn["protocol_version"],
        "node_counts":     node_counts,
        "rel_counts":      rel_counts,
    }


def _action_init_schema() -> dict:
    from db.schema import init_schema  # local import — only needed once
    results = init_schema(verbose=False)
    return {"schema_initialized": True, **results}


def _action_players(params: dict) -> dict:
    sport  = (params.get("sport") or ["tennis"])[0]
    limit  = int((params.get("limit") or ["20"])[0])
    limit  = min(limit, 100)
    rows   = run_query(_Q_PLAYERS, {"sport": sport, "limit": limit})
    return {"sport": sport, "players": rows, "count": len(rows)}


def _action_matches(params: dict) -> dict:
    sport   = (params.get("sport")   or ["tennis"])[0]
    surface = (params.get("surface") or [""])[0].lower()
    limit   = int((params.get("limit") or ["20"])[0])
    limit   = min(limit, 100)
    rows    = run_query(_Q_MATCHES, {"sport": sport, "surface": surface, "limit": limit})
    return {"sport": sport, "surface": surface or "all", "matches": rows, "count": len(rows)}


def _action_h2h(params: dict) -> dict:
    p1 = (params.get("p1") or [""])[0]
    p2 = (params.get("p2") or [""])[0]
    if not p1 or not p2:
        raise ValueError("Both 'p1' and 'p2' player IDs are required.")
    rows = run_query(_Q_H2H, {"p1_id": p1, "p2_id": p2})
    p1_wins = sum(1 for r in rows if r.get("p1_result") == "win")
    p2_wins = sum(1 for r in rows if r.get("p1_result") == "loss")
    return {
        "p1_id":    p1,
        "p2_id":    p2,
        "p1_wins":  p1_wins,
        "p2_wins":  p2_wins,
        "matches":  rows,
        "total":    len(rows),
    }


def _action_player_stats(params: dict) -> dict:
    pid  = (params.get("id") or [""])[0]
    if not pid:
        raise ValueError("Player 'id' parameter is required.")
    rows     = run_query(_Q_PLAYER_STATS,  {"player_id": pid})
    surfaces = run_query(_Q_TOP_SURFACES,  {"player_id": pid})
    if not rows:
        return {"found": False, "id": pid}
    stat = rows[0]
    return {
        "found":          True,
        "id":             pid,
        "name":           stat.get("name"),
        "nationality":    stat.get("nationality"),
        "rank":           stat.get("rank"),
        "tour":           stat.get("tour"),
        "total_matches":  stat.get("total_matches"),
        "wins":           stat.get("wins"),
        "losses":         stat.get("losses"),
        "win_rate":       round(stat["wins"] / stat["total_matches"], 4)
                          if stat.get("total_matches") else None,
        "avg_aces":       round(stat["avg_aces"], 2)
                          if stat.get("avg_aces") is not None else None,
        "avg_double_faults": round(stat["avg_double_faults"], 2)
                              if stat.get("avg_double_faults") is not None else None,
        "bp_save_rate":   round(stat["bp_save_rate"], 4)
                          if stat.get("bp_save_rate") is not None else None,
        "surface_stats":  surfaces,
    }


# ---------------------------------------------------------------------------
# Vercel handler
# ---------------------------------------------------------------------------

_ACTIONS = {
    "status":       _action_status,
    "init_schema":  _action_init_schema,
    "players":      _action_players,
    "matches":      _action_matches,
    "h2h":          _action_h2h,
    "player_stats": _action_player_stats,
}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        action = (params.get("action") or ["status"])[0]

        try:
            fn = _ACTIONS.get(action)
            if fn is None:
                raise ValueError(
                    f"Unknown action '{action}'. "
                    f"Valid actions: {list(_ACTIONS.keys())}"
                )
            # Actions that don't need params
            if action in ("status", "init_schema"):
                data = fn()
            else:
                data = fn(params)

            self._send_json(200, data)

        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except RuntimeError as exc:
            # e.g. missing env vars
            self._send_json(503, {"error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # suppress access logs
