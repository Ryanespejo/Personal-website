"""
Neo4j connection client for sports analytics.

Reads connection credentials from environment variables:
  NEO4J_URI      - e.g. neo4j+s://xxxxxxxx.databases.neo4j.io
  NEO4J_USERNAME - usually 'neo4j'
  NEO4J_PASSWORD - the database password

The module exposes a single module-level driver instance (lazily created) and
helper functions for running queries.  Import get_driver() wherever you need a
live connection, and call close_driver() on application shutdown.
"""

from __future__ import annotations

import os
import time
from typing import Any

# neo4j is a runtime dependency - imported lazily so that endpoints that don't
# touch the database can still import this module without crashing.
_driver = None


# ---------------------------------------------------------------------------
# Driver lifecycle
# ---------------------------------------------------------------------------

def get_driver():
    """Return (or lazily create) the shared Neo4j driver."""
    global _driver
    if _driver is None:
        from neo4j import GraphDatabase  # noqa: PLC0415

        uri = os.environ.get("NEO4J_URI")
        username = os.environ.get("NEO4J_USERNAME", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD")

        if not uri or not password:
            raise RuntimeError(
                "NEO4J_URI and NEO4J_PASSWORD environment variables must be set. "
                "See README for Neo4j Aura setup instructions."
            )

        _driver = GraphDatabase.driver(uri, auth=(username, password))
    return _driver


def close_driver():
    """Close the shared driver.  Call this on application shutdown."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def verify_connectivity() -> dict[str, Any]:
    """
    Verify that the database is reachable and return basic server info.

    Returns a dict with keys: connected (bool), server_info (str), error (str|None).
    """
    try:
        driver = get_driver()
        driver.verify_connectivity()
        info = driver.get_server_info()
        return {
            "connected": True,
            "server_info": str(info.agent),
            "address": str(info.address),
            "protocol_version": str(info.protocol_version),
            "error": None,
        }
    except Exception as exc:
        return {
            "connected": False,
            "server_info": None,
            "address": None,
            "protocol_version": None,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def run_query(
    cypher: str,
    parameters: dict[str, Any] | None = None,
    database: str = "neo4j",
) -> list[dict[str, Any]]:
    """
    Execute a Cypher read query and return results as a list of plain dicts.

    Example:
        rows = run_query(
            "MATCH (p:Player {sport: $sport}) RETURN p.name AS name, p.rank AS rank",
            {"sport": "tennis"},
        )
    """
    driver = get_driver()
    with driver.session(database=database) as session:
        result = session.run(cypher, parameters or {})
        return [dict(record) for record in result]


def run_write(
    cypher: str,
    parameters: dict[str, Any] | None = None,
    database: str = "neo4j",
) -> list[dict[str, Any]]:
    """
    Execute a Cypher write query inside a transaction and return results.

    Example:
        run_write(
            "MERGE (p:Player {id: $id}) SET p += $props",
            {"id": "djokovic", "props": {"name": "Novak Djokovic"}},
        )
    """
    driver = get_driver()
    with driver.session(database=database) as session:
        result = session.execute_write(_write_tx, cypher, parameters or {})
        return result


def _write_tx(tx, cypher: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
    result = tx.run(cypher, parameters)
    return [dict(record) for record in result]


def run_batch_write(
    cypher: str,
    rows: list[dict[str, Any]],
    batch_size: int = 500,
    database: str = "neo4j",
) -> int:
    """
    Execute a parameterised Cypher write in batches for large datasets.

    The query must reference `$rows` as the parameter name.  For example:

        UNWIND $rows AS row
        MERGE (p:Player {id: row.id})
        SET p += row

    Returns the total number of rows processed.
    """
    driver = get_driver()
    total = 0
    with driver.session(database=database) as session:
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            session.execute_write(_write_tx, cypher, {"rows": chunk})
            total += len(chunk)
    return total
