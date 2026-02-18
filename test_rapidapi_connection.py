#!/usr/bin/env python3
"""
RapidAPI Tennis Connection Test
================================
Tests the three API endpoints used by tennis-analytics.py:
  1. Search  — /api/tennis/search/{query}
  2. Player  — /api/tennis/player/{player_id}
  3. Events  — /api/tennis/player/{player_id}/events/previous/{page}

Usage:
  RAPIDAPI_KEY=<your-key> python3 test_rapidapi_connection.py

Or export the key first:
  export RAPIDAPI_KEY=<your-key>
  python3 test_rapidapi_connection.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ── Config (mirrors tennis-analytics.py) ─────────────────────────────────────
RAPIDAPI_KEY      = os.getenv("RAPIDAPI_KEY", "")
BASE_URL          = os.getenv("RAPIDAPI_TENNIS_BASE_URL", "https://tennisapi1.p.rapidapi.com")
HOST              = os.getenv("RAPIDAPI_TENNIS_HOST",     "tennisapi1.p.rapidapi.com")
SEARCH_PATH       = os.getenv("RAPIDAPI_TENNIS_SEARCH_PATH",    "/api/tennis/search/{query}")
PLAYER_PATH       = os.getenv("RAPIDAPI_TENNIS_PLAYER_PATH",    "/api/tennis/player/{player_id}")
PREV_EVENTS_PATH  = os.getenv("RAPIDAPI_TENNIS_PREV_EVENTS_PATH",
                               "/api/tennis/player/{player_id}/events/previous/{page}")
TIMEOUT           = 10

# Player to use for the test
TEST_PLAYER = "Carlos Alcaraz"

# ── Helpers ───────────────────────────────────────────────────────────────────

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
SKIP = "\033[94mSKIP\033[0m"

def _hdr():
    return {
        "User-Agent":      "TennisAnalyticsTest/1.0",
        "Accept":          "application/json",
        "x-rapidapi-host": HOST,
        "x-rapidapi-key":  RAPIDAPI_KEY,
    }


def _get(path: str, params: dict | None = None) -> tuple[dict | None, str]:
    """Return (data, error_message). data is None on failure."""
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    url = f"{BASE_URL.rstrip('/')}/{path.lstrip('/')}{q}"
    print(f"  URL: {url}")
    try:
        req = urllib.request.Request(url, headers=_hdr())
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8", errors="replace")
            if status != 200:
                return None, f"HTTP {status}"
            return json.loads(raw), ""
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:300]
        except Exception:
            pass
        return None, f"HTTP {e.code}: {body}"
    except urllib.error.URLError as e:
        return None, f"URLError: {e.reason}"
    except Exception as e:
        return None, f"Exception: {e}"


def _pp(data: dict | list, max_keys: int = 6, indent: int = 4) -> str:
    """Pretty-print a truncated view of the response."""
    if isinstance(data, dict):
        preview = dict(list(data.items())[:max_keys])
        if len(data) > max_keys:
            preview["..."] = f"({len(data) - max_keys} more keys)"
    elif isinstance(data, list):
        preview = data[:3]
        if len(data) > 3:
            preview.append(f"... ({len(data) - 3} more items)")
    else:
        preview = data
    return json.dumps(preview, indent=indent, default=str)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_env() -> bool:
    print("\n[1/4] Environment check")
    if not RAPIDAPI_KEY:
        print(f"  [{FAIL}] RAPIDAPI_KEY is not set.")
        print("         Set it before running:  export RAPIDAPI_KEY=<your-key>")
        return False
    masked = RAPIDAPI_KEY[:6] + "..." + RAPIDAPI_KEY[-4:]
    print(f"  [{PASS}] RAPIDAPI_KEY found  ({masked})")
    print(f"  [{PASS}] Base URL: {BASE_URL}")
    print(f"  [{PASS}] Host:     {HOST}")
    return True


def test_search() -> str | None:
    """Returns player_id on success, None on failure."""
    print(f"\n[2/4] Search endpoint — query: '{TEST_PLAYER}'")
    path = SEARCH_PATH.format(query=urllib.parse.quote(TEST_PLAYER))
    data, err = _get(path)
    if data is None:
        print(f"  [{FAIL}] {err}")
        return None

    # Unwrap candidates — API may nest them differently
    candidates = (
        data.get("results") or
        data.get("players") or
        data.get("data") or
        []
    )
    if isinstance(candidates, dict):
        candidates = candidates.get("players") or []

    if not candidates:
        print(f"  [{WARN}] Response received but no candidates found.")
        print(f"  Response preview:\n{_pp(data)}")
        return None

    # Grab first candidate
    entity = candidates[0].get("entity") or candidates[0]
    player_id = str(
        entity.get("id") or
        entity.get("player_id") or
        entity.get("playerId") or ""
    )
    name = entity.get("name") or entity.get("fullName") or "(unknown)"

    print(f"  [{PASS}] {len(candidates)} result(s) returned")
    print(f"  [{PASS}] Top match: '{name}'  (id={player_id})")
    print(f"  Response preview:\n{_pp(data)}")

    if not player_id:
        print(f"  [{WARN}] Could not extract player_id from response; skipping further tests.")
        return None
    return player_id


def test_player_detail(player_id: str) -> bool:
    print(f"\n[3/4] Player detail endpoint — id={player_id}")
    path = PLAYER_PATH.format(player_id=player_id)
    data, err = _get(path)
    if data is None:
        print(f"  [{FAIL}] {err}")
        return False

    # Extract a few fields for readability
    player = data.get("player") or data
    name    = player.get("name") or player.get("fullName") or "(unknown)"
    ranking = player.get("ranking") or player.get("rank") or "N/A"
    points  = player.get("rankingPoints") or player.get("points") or "N/A"
    country = (player.get("country") or {}).get("alpha3") or player.get("nationality") or "N/A"

    print(f"  [{PASS}] Player data received")
    print(f"         Name:    {name}")
    print(f"         Ranking: {ranking}")
    print(f"         Points:  {points}")
    print(f"         Country: {country}")
    print(f"  Response preview:\n{_pp(data)}")
    return True


def test_prev_events(player_id: str) -> bool:
    print(f"\n[4/4] Previous events endpoint — id={player_id}, page=0")
    path = PREV_EVENTS_PATH.format(player_id=player_id, page=0)
    data, err = _get(path)
    if data is None:
        print(f"  [{FAIL}] {err}")
        return False

    events = data.get("events") or []
    if not events:
        print(f"  [{WARN}] Response OK but no events returned.")
        print(f"  Response preview:\n{_pp(data)}")
        return True  # endpoint responded; empty events is valid

    # Show summary of most recent 3 events
    print(f"  [{PASS}] {len(events)} event(s) on page 0")
    for ev in events[:3]:
        home    = ev.get("homeTeam") or {}
        away    = ev.get("awayTeam") or {}
        ts      = ev.get("startTimestamp", 0)
        date_s  = time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else "unknown"
        winner  = ev.get("winnerCode")  # 1=home, 2=away
        h_score = ev.get("homeScore") or {}
        a_score = ev.get("awayScore") or {}
        print(
            f"         {date_s}  {home.get('name','?')} vs {away.get('name','?')}"
            f"  winner={winner}  "
            f"sets: {h_score.get('current','?')}-{a_score.get('current','?')}"
        )
    print(f"  Response preview:\n{_pp(data)}")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  RapidAPI Tennis Connection Test")
    print("=" * 60)

    results = {}

    # 1. env
    ok = test_env()
    results["env"] = ok
    if not ok:
        _summary(results)
        sys.exit(1)

    # 2. search → get player_id
    player_id = test_search()
    results["search"] = player_id is not None

    if player_id:
        # 3. player detail
        results["player_detail"] = test_player_detail(player_id)
        # 4. previous events
        results["prev_events"] = test_prev_events(player_id)
    else:
        results["player_detail"] = None
        results["prev_events"]   = None

    _summary(results)
    all_passed = all(v for v in results.values() if v is not None)
    sys.exit(0 if all_passed else 1)


def _summary(results: dict):
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    labels = {
        "env":           "Environment check   ",
        "search":        "Search endpoint     ",
        "player_detail": "Player detail       ",
        "prev_events":   "Previous events     ",
    }
    for key, label in labels.items():
        v = results.get(key)
        if v is None:
            tag = SKIP
        elif v:
            tag = PASS
        else:
            tag = FAIL
        print(f"  {label}  [{tag}]")
    print("=" * 60)


if __name__ == "__main__":
    main()
