"""
/api/tennis-elo  — Scrape ATP/WTA Elo ratings from Tennis Abstract.

GET /api/tennis-elo
    → All players' Elo ratings (overall + per-surface).

GET /api/tennis-elo?player=Carlos+Alcaraz
    → Single player lookup (fuzzy name match).

GET /api/tennis-elo?tour=wta
    → WTA Elo ratings (default: atp).

GET /api/tennis-elo?action=ingest
    → Scrape and store Elo ratings into Neo4j.

Source: https://www.tennisabstract.com/reports/atp_elo_ratings.html
Data: Updated weekly on the source site; cached 6 hours here.
"""

from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import time
import gzip
import re
from html.parser import HTMLParser

# ── In-memory cache ───────────────────────────────────────────────────────────

_cache: dict = {}
CACHE_TTL = 21600  # 6 hours — source updates weekly

HEADERS = {
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


def fetch_html(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.info().get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        return raw.decode('utf-8', errors='replace')


# ── HTML table parser ─────────────────────────────────────────────────────────

class EloTableParser(HTMLParser):
    """Parse the Tennis Abstract Elo ratings HTML table."""

    def __init__(self):
        super().__init__()
        self.players: list = []
        self._in_table = False
        self._in_thead = False
        self._in_tbody = False
        self._in_row = False
        self._in_cell = False
        self._cell_tag = ''
        self._cells: list = []
        self._cell_buf: list = []
        self._headers: list = []

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
            self._cell_tag = tag
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
            if self._in_thead and self._cells:
                self._headers = self._cells
            elif self._in_tbody and self._cells:
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
        """Convert a table row into a player dict.

        Actual column layout (Tennis Abstract, with empty spacer columns):
        0: Elo Rank  1: Player  2: Age  3: Elo  4: (empty)
        5: hElo Rank  6: hElo  7: cElo Rank  8: cElo
        9: gElo Rank  10: gElo  11: (empty)  12: Peak Elo
        13: Peak Month  14: (empty)  15: ATP Rank  16: Log diff
        """
        # Strip empty spacer columns
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

        # Use non-empty cells for reliable indexing:
        # 0: Elo Rank  1: Player  2: Age  3: Elo
        # 4: hElo Rank  5: hElo  6: cElo Rank  7: cElo
        # 8: gElo Rank  9: gElo  10: Peak Elo  11: Peak Month
        # 12: ATP Rank  13: Log diff
        player = {
            'elo_rank': safe_int(non_empty[0]),
            'name': non_empty[1].strip(),
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
        }
        if player['name'] and player['elo'] is not None:
            self.players.append(player)


def scrape_elo(tour: str = 'atp') -> list:
    """Scrape and return the full Elo ratings table."""
    url = ELO_URLS.get(tour, ELO_URLS['atp'])
    html = fetch_html(url)
    parser = EloTableParser()
    parser.feed(html)
    return parser.players


def get_elo_data(tour: str = 'atp') -> dict:
    """Return cached or freshly scraped Elo data."""
    cache_key = f'elo_{tour}'
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key]['ts'] < CACHE_TTL:
        return _cache[cache_key]['data']

    players = scrape_elo(tour)
    data = {
        'tour': tour,
        'player_count': len(players),
        'scraped_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'players': players,
    }
    _cache[cache_key] = {'ts': now, 'data': data}
    return data


def find_player(players: list, query: str) -> list:
    """Fuzzy match players by name."""
    query_lower = query.lower().strip()
    exact = [p for p in players if p['name'].lower() == query_lower]
    if exact:
        return exact

    # Try last-name match
    last_name_matches = [
        p for p in players
        if query_lower == p['name'].split()[-1].lower()
    ]
    if last_name_matches:
        return last_name_matches

    # Substring match
    return [p for p in players if query_lower in p['name'].lower()]


def ingest_to_neo4j(tour: str = 'atp') -> dict:
    """Store scraped Elo data into Neo4j Player nodes."""
    import sys
    import os
    _API_DIR = os.path.dirname(os.path.abspath(__file__))
    if _API_DIR not in sys.path:
        sys.path.insert(0, _API_DIR)

    from db.neo4j_client import run_write

    data = get_elo_data(tour)
    players = data.get('players', [])
    if not players:
        return {'ingested': 0, 'error': 'No players scraped'}

    updated = 0
    for p in players:
        name = p['name']
        if not name:
            continue
        run_write(
            """
            MATCH (player:Player)
            WHERE toLower(player.name) = toLower($name)
            SET player.elo            = $elo,
                player.elo_rank       = $elo_rank,
                player.hard_elo       = $hard_elo,
                player.hard_elo_rank  = $hard_elo_rank,
                player.clay_elo       = $clay_elo,
                player.clay_elo_rank  = $clay_elo_rank,
                player.grass_elo      = $grass_elo,
                player.grass_elo_rank = $grass_elo_rank,
                player.peak_elo       = $peak_elo,
                player.peak_elo_month = $peak_month,
                player.elo_updated_at = $updated_at
            """,
            {
                'name': name,
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
                'updated_at': data.get('scraped_at', ''),
            },
        )
        updated += 1

    return {'ingested': updated, 'tour': tour, 'scraped_at': data.get('scraped_at')}


# ── Request handler ───────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        tour = (params.get('tour') or ['atp'])[0].lower()
        action = (params.get('action') or [''])[0].lower()
        player_query = (params.get('player') or [''])[0].strip()

        if tour not in ('atp', 'wta'):
            tour = 'atp'

        try:
            if action == 'ingest':
                result = ingest_to_neo4j(tour)
                self._send_json(200, result)
                return

            data = get_elo_data(tour)

            if player_query:
                matches = find_player(data['players'], player_query)
                self._send_json(200, {
                    'tour': tour,
                    'query': player_query,
                    'results': matches,
                    'count': len(matches),
                    'scraped_at': data.get('scraped_at'),
                })
            else:
                self._send_json(200, data)

        except Exception as exc:
            self._send_json(500, {'error': str(exc)})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass
