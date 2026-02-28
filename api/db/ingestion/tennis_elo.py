"""
Tennis Elo ratings ingestion into Neo4j.

Scrapes Tennis Abstract Elo ratings and updates Player nodes with
surface-specific Elo ratings, peak Elo, and Elo rank.

Source: https://www.tennisabstract.com/reports/atp_elo_ratings.html
        https://www.tennisabstract.com/reports/wta_elo_ratings.html

Usage (standalone):
    python -m api.db.ingestion.tennis_elo --tours atp wta
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import gzip
import urllib.request
from html.parser import HTMLParser

# Make sure repo root is importable when running as __main__
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from api.db.neo4j_client import run_write  # noqa: E402

# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'en-US,en;q=0.9',
}

ELO_URLS = {
    'atp': 'https://www.tennisabstract.com/reports/atp_elo_ratings.html',
    'wta': 'https://www.tennisabstract.com/reports/wta_elo_ratings.html',
}


def _fetch_html(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.info().get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        return raw.decode('utf-8', errors='replace')


class _EloTableParser(HTMLParser):
    """Parse the Tennis Abstract Elo ratings HTML table."""

    def __init__(self):
        super().__init__()
        self.players: list = []
        self._in_table = False
        self._in_thead = False
        self._in_tbody = False
        self._in_row = False
        self._in_cell = False
        self._cells: list = []
        self._cell_buf: list = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'table':
            table_id = attrs_dict.get('id', '')
            table_class = attrs_dict.get('class', '')
            if 'reportable' in table_id or 'tablesorter' in table_class:
                self._in_table = True
        if not self._in_table:
            return
        if tag == 'thead':
            self._in_thead = True
        elif tag == 'tbody':
            self._in_tbody = True
        elif tag == 'tr':
            self._in_row = True
            self._cells = []
        elif tag in ('td', 'th') and self._in_row:
            self._in_cell = True
            self._cell_buf = []

    def handle_data(self, data):
        if self._in_cell:
            self._cell_buf.append(data.strip())

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self._in_cell:
            text = ' '.join(t for t in self._cell_buf if t)
            self._cells.append(text)
            self._in_cell = False
            self._cell_buf = []
        elif tag == 'tr' and self._in_row:
            if self._in_tbody and self._cells and len(self._cells) >= 12:
                self._parse_row(self._cells)
            self._in_row = False
            self._cells = []
        elif tag == 'thead':
            self._in_thead = False
        elif tag == 'tbody':
            self._in_tbody = False
        elif tag == 'table' and self._in_table:
            self._in_table = False

    def _parse_row(self, cells: list):
        # Replace non-breaking spaces and strip empty spacer columns
        cells = [c.replace('\xa0', ' ') for c in cells]
        non_empty = [c for c in cells if c.strip()]
        if len(non_empty) < 12:
            return

        def safe_float(v):
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        def safe_int(v):
            try:
                return int(v)
            except (ValueError, TypeError):
                return None

        # Non-empty column indices:
        # 0: Elo Rank  1: Player  2: Age  3: Elo
        # 4: hElo Rank  5: hElo  6: cElo Rank  7: cElo
        # 8: gElo Rank  9: gElo  10: Peak Elo  11: Peak Month
        # 12: ATP Rank  13: Log diff
        name = non_empty[1].strip()
        if not name:
            return

        self.players.append({
            'elo_rank': safe_int(non_empty[0]),
            'name': name,
            'age': safe_float(non_empty[2]),
            'elo': safe_float(non_empty[3]),
            'hard_elo_rank': safe_int(non_empty[4]),
            'hard_elo': safe_float(non_empty[5]),
            'clay_elo_rank': safe_int(non_empty[6]),
            'clay_elo': safe_float(non_empty[7]),
            'grass_elo_rank': safe_int(non_empty[8]),
            'grass_elo': safe_float(non_empty[9]),
            'peak_elo': safe_float(non_empty[10]),
            'peak_month': non_empty[11].strip() if len(non_empty) > 11 else '',
            'atp_rank': safe_int(non_empty[12]) if len(non_empty) > 12 else None,
        })


def scrape_elo(tour: str) -> list[dict]:
    """Scrape and return the full Elo ratings table for a tour."""
    url = ELO_URLS.get(tour, ELO_URLS['atp'])
    print(f"  Fetching {url} ...")
    html = _fetch_html(url)
    parser = _EloTableParser()
    parser.feed(html)
    print(f"  Parsed {len(parser.players)} players")
    return parser.players


# ---------------------------------------------------------------------------
# Neo4j ingestion
# ---------------------------------------------------------------------------

_UPSERT_ELO = """
MATCH (p:Player)
WHERE toLower(p.name) = toLower($name)
SET p.elo            = $elo,
    p.elo_rank       = $elo_rank,
    p.hard_elo       = $hard_elo,
    p.hard_elo_rank  = $hard_elo_rank,
    p.clay_elo       = $clay_elo,
    p.clay_elo_rank  = $clay_elo_rank,
    p.grass_elo      = $grass_elo,
    p.grass_elo_rank = $grass_elo_rank,
    p.peak_elo       = $peak_elo,
    p.peak_elo_month = $peak_month,
    p.elo_updated_at = $updated_at
"""


def ingest_elo(tour: str) -> dict:
    """Scrape Elo ratings and upsert into Neo4j Player nodes."""
    print(f"\n{'='*60}")
    print(f"Ingesting {tour.upper()} Elo ratings")
    print(f"{'='*60}")

    players = scrape_elo(tour)
    if not players:
        print("  No players scraped — skipping")
        return {'tour': tour, 'scraped': 0, 'updated': 0}

    updated_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    updated = 0

    for p in players:
        if not p.get('name'):
            continue
        run_write(_UPSERT_ELO, {
            'name': p['name'],
            'elo': p.get('elo'),
            'elo_rank': p.get('elo_rank'),
            'hard_elo': p.get('hard_elo'),
            'hard_elo_rank': p.get('hard_elo_rank'),
            'clay_elo': p.get('clay_elo'),
            'clay_elo_rank': p.get('clay_elo_rank'),
            'grass_elo': p.get('grass_elo'),
            'grass_elo_rank': p.get('grass_elo_rank'),
            'peak_elo': p.get('peak_elo'),
            'peak_month': p.get('peak_month', ''),
            'updated_at': updated_at,
        })
        updated += 1

    print(f"  Updated {updated} player nodes")
    return {'tour': tour, 'scraped': len(players), 'updated': updated}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ingest Tennis Abstract Elo ratings into Neo4j")
    parser.add_argument(
        "--tours", nargs="+", default=["atp"],
        choices=["atp", "wta"],
        help="Tours to ingest (default: atp)"
    )
    args = parser.parse_args()

    results = []
    for tour in args.tours:
        result = ingest_elo(tour)
        results.append(result)

    print(f"\nDone. Results: {results}")


if __name__ == "__main__":
    main()
