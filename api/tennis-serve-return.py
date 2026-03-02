"""
/api/tennis-serve-return  — ATP/WTA serve & return stats from Tennis Abstract.

GET /api/tennis-serve-return
    → All players' serve & return stats (default: atp, last 52 weeks).

GET /api/tennis-serve-return?player=Carlos+Alcaraz
    → Single player lookup (fuzzy name match).

GET /api/tennis-serve-return?tour=wta
    → WTA stats (default: atp).

GET /api/tennis-serve-return?action=ingest
    → Scrape and store serve/return stats into Neo4j.

Source: https://www.tennisabstract.com/cgi-bin/leaders.cgi
Data: Match-level JS data, aggregated server-side; cached 6 hours.
"""

from http.server import BaseHTTPRequestHandler
import json
import re
import gzip
import time
import urllib.request

# ── In-memory cache ───────────────────────────────────────────────────────────

_cache: dict = {}
CACHE_TTL = 21600  # 6 hours

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'en-US,en;q=0.9',
}

JS_URLS: dict[str, list[str]] = {
    'atp': [
        'https://www.tennisabstract.com/jsmatches/leadersource.js',
        'https://www.tennisabstract.com/jsmatches/leadersource51.js',
    ],
    'wta': [
        'https://www.tennisabstract.com/jsmatches/leadersource_wta.js',
        'https://www.tennisabstract.com/jsmatches/leadersource51_wta.js',
    ],
}

MATCHHEAD = [
    'date', 'tourn', 'surf', 'level', 'wl', 'player',
    'rank', 'seed', 'entry', 'round', 'score', 'max',
    'opp', 'orank', 'oseed', 'oentry', 'ohand', 'obh',
    'obday', 'oht', 'ocountry', 'oactive',
    'tbw', 'tbl', 'setw', 'setl',
    'time', 'aces', 'dfs', 'pts', 'firsts', 'fwon',
    'swon', 'games', 'saved', 'chances',
    'oaces', 'odfs', 'opts', 'ofirsts', 'ofwon',
    'oswon', 'ogames', 'osaved', 'ochances',
]

STAT_START = 22


# ── Fetching & parsing ────────────────────────────────────────────────────────

def fetch_js(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.info().get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        return raw.decode('utf-8', errors='replace')


def parse_matchmx(js_text: str) -> list[list[str]]:
    match = re.search(r'var\s+matchmx\s*=\s*(\[.*?\])\s*;', js_text, re.DOTALL)
    if not match:
        return []
    return json.loads(match.group(1))


def parse_crank(js_text: str) -> dict[str, int]:
    match = re.search(r'crank\s*=\s*(\{.*?\})\s*;', js_text, re.DOTALL)
    if not match:
        return {}
    raw = match.group(1).replace("'", '"')
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def safe_int(v: str) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


def aggregate_stats(matches: list[list[str]]) -> dict[str, dict]:
    pstats: dict[str, dict] = {}
    for row in matches:
        if len(row) < len(MATCHHEAD):
            continue
        m = dict(zip(MATCHHEAD, row))
        score = m.get('score', '')
        wl = m.get('wl', '')
        player = m.get('player', '').strip()
        if not player:
            continue
        if player not in pstats:
            pstats[player] = {
                'W': 0, 'L': 0, 'oranks': [],
                **{k: 0 for k in MATCHHEAD[STAT_START:]},
            }
        ps = pstats[player]
        if score in ('W/O', 'RET', ''):
            pass
        elif wl == 'W':
            ps['W'] += 1
        elif wl == 'L':
            ps['L'] += 1
        orank = m.get('orank', '')
        if orank and orank != 'UNR':
            try:
                ps['oranks'].append(int(orank))
            except ValueError:
                pass
        for key in MATCHHEAD[STAT_START:]:
            ps[key] += safe_int(m.get(key, '0'))
    return pstats


def compute_player_stats(name: str, ps: dict, rank) -> dict | None:
    matches = ps['W'] + ps['L']
    if matches == 0 or ps['pts'] == 0 or ps['opts'] == 0:
        return None

    second_serves = ps['pts'] - ps['firsts']
    serve_won = ps['fwon'] + ps['swon']
    opp_serve_won = ps['ofwon'] + ps['oswon']
    bp_lost = ps['chances'] - ps['saved']
    holds = ps['games'] - bp_lost
    bp_conv = ps['ochances'] - ps['osaved']

    def _pct(num, den):
        return round(num / den, 4) if den else None

    oranks = sorted(ps['oranks'])
    if oranks:
        half = len(oranks) // 2
        if len(oranks) % 2 == 0:
            median_opp_rank = round((oranks[half] + oranks[half - 1]) / 2, 1)
        else:
            median_opp_rank = oranks[half]
        mean_opp_rank = round(sum(oranks) / len(oranks), 1)
    else:
        median_opp_rank = None
        mean_opp_rank = None

    spw = _pct(serve_won, ps['pts'])
    rpw = _pct(ps['opts'] - opp_serve_won, ps['opts'])

    return {
        'name': name,
        'rank': rank,
        'matches': matches,
        'wins': ps['W'],
        'losses': ps['L'],
        'match_win_pct': _pct(ps['W'], matches),
        'spw': spw,
        'spw_in_play': _pct(
            serve_won - ps['aces'],
            ps['pts'] - ps['aces'] - ps['dfs'],
        ),
        'ace_rate': _pct(ps['aces'], ps['pts']),
        'df_rate': _pct(ps['dfs'], ps['pts']),
        'df_per_second_serve': _pct(ps['dfs'], second_serves),
        'first_serve_in': _pct(ps['firsts'], ps['pts']),
        'first_serve_won': _pct(ps['fwon'], ps['firsts']),
        'second_serve_won': _pct(ps['swon'], second_serves),
        'hold_pct': _pct(holds, ps['games']),
        'aces': ps['aces'],
        'dfs': ps['dfs'],
        'rpw': rpw,
        'rpw_in_play': _pct(
            ps['opts'] - opp_serve_won - ps['oaces'],
            ps['opts'] - ps['oaces'] - ps['odfs'],
        ) if (ps['opts'] - ps['oaces'] - ps['odfs']) else None,
        'v_ace_rate': _pct(ps['oaces'], ps['opts']),
        'v_df_rate': _pct(ps['odfs'], ps['opts']),
        'v_first_serve_won': _pct(
            ps['ofirsts'] - ps['ofwon'], ps['ofirsts'],
        ),
        'v_second_serve_won': _pct(
            ps['opts'] - ps['ofirsts'] - ps['oswon'],
            ps['opts'] - ps['ofirsts'],
        ),
        'break_pct': _pct(bp_conv, ps['ogames']),
        'dominance_ratio': round(rpw / (1 - spw), 2) if spw and spw < 1 and rpw else None,
        'tpw': _pct(
            serve_won + (ps['opts'] - opp_serve_won),
            ps['pts'] + ps['opts'],
        ),
        'median_opp_rank': median_opp_rank,
        'mean_opp_rank': mean_opp_rank,
    }


def scrape_serve_return(tour: str = 'atp') -> list[dict]:
    urls = JS_URLS.get(tour, JS_URLS['atp'])
    all_matches: list[list[str]] = []
    all_cranks: dict[str, int] = {}

    for url in urls:
        js_text = fetch_js(url)
        all_matches.extend(parse_matchmx(js_text))
        all_cranks.update(parse_crank(js_text))

    pstats = aggregate_stats(all_matches)
    players = []
    for name, ps in pstats.items():
        rank = all_cranks.get(name)
        computed = compute_player_stats(name, ps, rank)
        if computed:
            players.append(computed)

    # Assign serve and return ranks
    by_spw = sorted(players, key=lambda p: p.get('spw') or 0, reverse=True)
    by_rpw = sorted(players, key=lambda p: p.get('rpw') or 0, reverse=True)
    spw_ranks = {p['name']: i + 1 for i, p in enumerate(by_spw)}
    rpw_ranks = {p['name']: i + 1 for i, p in enumerate(by_rpw)}

    for p in players:
        p['serve_rank'] = spw_ranks.get(p['name'])
        p['return_rank'] = rpw_ranks.get(p['name'])

    players.sort(key=lambda p: p.get('spw') or 0, reverse=True)
    return players


def get_serve_return_data(tour: str = 'atp') -> dict:
    cache_key = f'serve_return_{tour}'
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key]['ts'] < CACHE_TTL:
        return _cache[cache_key]['data']

    players = scrape_serve_return(tour)
    data = {
        'tour': tour,
        'player_count': len(players),
        'scraped_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'players': players,
    }
    _cache[cache_key] = {'ts': now, 'data': data}
    return data


def find_player(players: list, query: str) -> list:
    query_lower = query.lower().strip()
    exact = [p for p in players if p['name'].lower() == query_lower]
    if exact:
        return exact
    last_name_matches = [
        p for p in players
        if query_lower == p['name'].split()[-1].lower()
    ]
    if last_name_matches:
        return last_name_matches
    return [p for p in players if query_lower in p['name'].lower()]


# ── Neo4j ingestion ───────────────────────────────────────────────────────────

def ingest_to_neo4j(tour: str = 'atp') -> dict:
    import sys
    import os
    _API_DIR = os.path.dirname(os.path.abspath(__file__))
    if _API_DIR not in sys.path:
        sys.path.insert(0, _API_DIR)

    from db.neo4j_client import run_write

    data = get_serve_return_data(tour)
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
            SET player.spw                = $spw,
                player.spw_in_play        = $spw_in_play,
                player.ace_rate           = $ace_rate,
                player.df_rate            = $df_rate,
                player.first_serve_in     = $first_serve_in,
                player.first_serve_won    = $first_serve_won,
                player.second_serve_won   = $second_serve_won,
                player.hold_pct           = $hold_pct,
                player.rpw                = $rpw,
                player.rpw_in_play        = $rpw_in_play,
                player.v_ace_rate         = $v_ace_rate,
                player.v_first_serve_won  = $v_first_serve_won,
                player.v_second_serve_won = $v_second_serve_won,
                player.break_pct          = $break_pct,
                player.dominance_ratio    = $dominance_ratio,
                player.tpw                = $tpw,
                player.serve_rank         = $serve_rank,
                player.return_rank        = $return_rank,
                player.serve_return_updated_at = $updated_at
            """,
            {
                'name': name,
                'spw': p.get('spw'),
                'spw_in_play': p.get('spw_in_play'),
                'ace_rate': p.get('ace_rate'),
                'df_rate': p.get('df_rate'),
                'first_serve_in': p.get('first_serve_in'),
                'first_serve_won': p.get('first_serve_won'),
                'second_serve_won': p.get('second_serve_won'),
                'hold_pct': p.get('hold_pct'),
                'rpw': p.get('rpw'),
                'rpw_in_play': p.get('rpw_in_play'),
                'v_ace_rate': p.get('v_ace_rate'),
                'v_first_serve_won': p.get('v_first_serve_won'),
                'v_second_serve_won': p.get('v_second_serve_won'),
                'break_pct': p.get('break_pct'),
                'dominance_ratio': p.get('dominance_ratio'),
                'tpw': p.get('tpw'),
                'serve_rank': p.get('serve_rank'),
                'return_rank': p.get('return_rank'),
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

            data = get_serve_return_data(tour)

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
