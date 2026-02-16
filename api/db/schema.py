"""
Neo4j schema initialisation for the sports analytics database.

Run this once (or after wiping the DB) to create all constraints and indexes.
The script is idempotent – it uses CREATE CONSTRAINT IF NOT EXISTS / CREATE INDEX
IF NOT EXISTS so it's safe to re-run at any time.

Usage (standalone):
    python -m api.db.schema

Usage (from another module):
    from api.db.schema import init_schema
    init_schema()

Graph model overview
--------------------
Nodes
    (:Player  {id, name, full_name, nationality, hand, height_cm, dob, sport})
    (:Team    {id, name, city, abbreviation, conference, division, sport})
    (:Match   {id, date, round, surface, best_of, score, sport, tournament_id})
    (:Tournament {id, name, location, surface, level, prize_money, sport})
    (:Sport   {name})   # "tennis" | "nba" | "cbb" | "college_baseball"

Relationships
    (:Player)-[:PLAYED_IN  {result, aces, double_faults, bp_saved, bp_faced,
                             first_serve_pct, first_serve_won_pct,
                             second_serve_won_pct}]->(:Match)
    (:Match)  -[:PART_OF]                          ->(:Tournament)
    (:Tournament)-[:BELONGS_TO]                    ->(:Sport)
    (:Player)  -[:BELONGS_TO]                      ->(:Sport)
    (:Player)  -[:MEMBER_OF {season, from_date, to_date}]->(:Team)
    (:Team)    -[:PLAYED_IN {home, score, opponent_score}]->(:Match)
    (:Match)   -[:PART_OF]                         ->(:Tournament)
"""

from __future__ import annotations

from .neo4j_client import run_write, get_driver

# ---------------------------------------------------------------------------
# Constraints  (enforce uniqueness and existence)
# ---------------------------------------------------------------------------

_CONSTRAINTS = [
    # Player
    "CREATE CONSTRAINT player_id_unique IF NOT EXISTS "
    "FOR (p:Player) REQUIRE p.id IS UNIQUE",

    # Team
    "CREATE CONSTRAINT team_id_unique IF NOT EXISTS "
    "FOR (t:Team) REQUIRE t.id IS UNIQUE",

    # Match
    "CREATE CONSTRAINT match_id_unique IF NOT EXISTS "
    "FOR (m:Match) REQUIRE m.id IS UNIQUE",

    # Tournament
    "CREATE CONSTRAINT tournament_id_unique IF NOT EXISTS "
    "FOR (t:Tournament) REQUIRE t.id IS UNIQUE",

    # Sport
    "CREATE CONSTRAINT sport_name_unique IF NOT EXISTS "
    "FOR (s:Sport) REQUIRE s.name IS UNIQUE",
]

# ---------------------------------------------------------------------------
# Indexes  (speed up common look-ups)
# ---------------------------------------------------------------------------

_INDEXES = [
    # Players by sport and nationality – used when filtering leaderboards
    "CREATE INDEX player_sport_idx IF NOT EXISTS "
    "FOR (p:Player) ON (p.sport)",

    "CREATE INDEX player_nationality_idx IF NOT EXISTS "
    "FOR (p:Player) ON (p.nationality)",

    "CREATE INDEX player_rank_idx IF NOT EXISTS "
    "FOR (p:Player) ON (p.rank)",

    # Matches by date – used in time-range analytics
    "CREATE INDEX match_date_idx IF NOT EXISTS "
    "FOR (m:Match) ON (m.date)",

    "CREATE INDEX match_sport_idx IF NOT EXISTS "
    "FOR (m:Match) ON (m.sport)",

    "CREATE INDEX match_surface_idx IF NOT EXISTS "
    "FOR (m:Match) ON (m.surface)",

    # Tournaments by sport and level
    "CREATE INDEX tournament_sport_idx IF NOT EXISTS "
    "FOR (t:Tournament) ON (t.sport)",

    "CREATE INDEX tournament_level_idx IF NOT EXISTS "
    "FOR (t:Tournament) ON (t.level)",

    # Teams by sport
    "CREATE INDEX team_sport_idx IF NOT EXISTS "
    "FOR (t:Team) ON (t.sport)",
]

# ---------------------------------------------------------------------------
# Seed data  (base Sport nodes)
# ---------------------------------------------------------------------------

_SPORTS = ["tennis", "nba", "cbb", "college_baseball"]

_SEED_SPORTS = (
    "UNWIND $sports AS s "
    "MERGE (:Sport {name: s})"
)


def init_schema(verbose: bool = True) -> dict[str, int]:
    """
    Apply all constraints, indexes, and seed data to the connected Neo4j instance.

    Returns a summary dict: {"constraints": N, "indexes": N, "sports": N}.
    """
    driver = get_driver()

    def _log(msg: str):
        if verbose:
            print(msg)

    results = {"constraints": 0, "indexes": 0, "sports": 0}

    with driver.session(database="neo4j") as session:
        _log("Creating constraints...")
        for stmt in _CONSTRAINTS:
            session.run(stmt)
            results["constraints"] += 1
            _log(f"  OK: {stmt[:70]}...")

        _log("Creating indexes...")
        for stmt in _INDEXES:
            session.run(stmt)
            results["indexes"] += 1
            _log(f"  OK: {stmt[:70]}...")

        _log("Seeding Sport nodes...")
        session.run(_SEED_SPORTS, {"sports": _SPORTS})
        results["sports"] = len(_SPORTS)
        _log(f"  Seeded {len(_SPORTS)} Sport nodes: {_SPORTS}")

    _log(
        f"\nSchema initialisation complete: "
        f"{results['constraints']} constraints, "
        f"{results['indexes']} indexes, "
        f"{results['sports']} sport nodes."
    )
    return results


if __name__ == "__main__":
    init_schema()
