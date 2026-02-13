"""Fetch and cache Jeff Sackmann's tennis CSV data from GitHub."""

import csv
import io
import os
import time
import urllib.request
import urllib.error

from . import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TennisAnalytics/1.0)",
}


def ensure_dirs():
    """Create cache and model directories if they don't exist."""
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(config.MODEL_PATH), exist_ok=True)


def _fetch_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _cache_path(filename: str) -> str:
    return os.path.join(config.CACHE_DIR, filename)


def _is_fresh(path: str) -> bool:
    if not os.path.exists(path):
        return False
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    return age_hours < config.CACHE_TTL_HOURS


def _read_cached_csv(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_and_parse(text: str, path: str) -> list[dict]:
    ensure_dirs()
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return list(csv.DictReader(io.StringIO(text)))


# ── Public API ───────────────────────────────────────────────────────────────

def fetch_matches(tour: str, year: int, force: bool = False) -> list[dict]:
    """Fetch match data for a given tour and year.

    Returns list of row dicts straight from the CSV.
    """
    filename = f"{tour}_matches_{year}.csv"
    cached = _cache_path(filename)

    if not force and _is_fresh(cached):
        return _read_cached_csv(cached)

    base = config.SACKMANN_ATP if tour == "atp" else config.SACKMANN_WTA
    url = f"{base}/{filename}"
    try:
        text = _fetch_text(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []          # year file doesn't exist yet
        raise
    return _write_and_parse(text, cached)


def fetch_players(tour: str, force: bool = False) -> list[dict]:
    """Fetch the player master list for a tour."""
    filename = f"{tour}_players.csv"
    cached = _cache_path(filename)

    if not force and _is_fresh(cached):
        return _read_cached_csv(cached)

    base = config.SACKMANN_ATP if tour == "atp" else config.SACKMANN_WTA
    text = _fetch_text(f"{base}/{filename}")
    return _write_and_parse(text, cached)


def fetch_rankings(tour: str, force: bool = False) -> list[dict]:
    """Fetch current rankings for a tour."""
    filename = f"{tour}_rankings_current.csv"
    cached = _cache_path(filename)

    if not force and _is_fresh(cached):
        return _read_cached_csv(cached)

    base = config.SACKMANN_ATP if tour == "atp" else config.SACKMANN_WTA
    text = _fetch_text(f"{base}/{filename}")
    return _write_and_parse(text, cached)


def fetch_all_matches(
    tour: str,
    start_year: int | None = None,
    end_year: int | None = None,
    force: bool = False,
) -> list[dict]:
    """Fetch all matches across a range of years for a tour."""
    if start_year is None:
        start_year = config.TRAINING_YEAR_START
    if end_year is None:
        end_year = config.TRAINING_YEAR_END

    all_matches: list[dict] = []
    for year in range(start_year, end_year):
        matches = fetch_matches(tour, year, force=force)
        all_matches.extend(matches)
        print(f"  {tour.upper()} {year}: {len(matches):,} matches")
    return all_matches


def get_cache_info() -> dict:
    """Return metadata about the local cache directory."""
    ensure_dirs()
    files = []
    total_bytes = 0
    for name in sorted(os.listdir(config.CACHE_DIR)):
        path = os.path.join(config.CACHE_DIR, name)
        if not os.path.isfile(path):
            continue
        size = os.path.getsize(path)
        files.append({
            "name": name,
            "size_kb": round(size / 1024, 1),
            "age_hours": round((time.time() - os.path.getmtime(path)) / 3600, 1),
        })
        total_bytes += size
    return {"files": files, "total_size_mb": round(total_bytes / (1024 * 1024), 2)}
