from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error
import time
import gzip

ESPN_ENDPOINTS = {
    'atp': 'https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard',
    'wta': 'https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard',
}

_cache: dict = {}
CACHE_TTL = 30  # seconds — serve cached data for 30s before re-fetching


def fetch_tour(tour: str) -> list:
    now = time.time()
    if tour in _cache and now - _cache[tour]['ts'] < CACHE_TTL:
        return _cache[tour]['data']

    url = ESPN_ENDPOINTS[tour]
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate',
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
        if resp.info().get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        data = json.loads(raw.decode('utf-8'))

    matches = []
    for event in data.get('events', []):
        event_name = event.get('shortName') or event.get('name') or 'Tournament'
        for grouping in event.get('groupings', []):
            for comp in grouping.get('competitions', []):
                m = normalize(comp, tour, event_name)
                if m:
                    matches.append(m)
    _cache[tour] = {'ts': now, 'data': matches}
    return matches


def normalize(comp: dict, tour: str, event_name: str = ''):
    competitors = comp.get('competitors') or []
    if len(competitors) < 2:
        return None

    status_obj = comp.get('status') or {}
    status_type = status_obj.get('type') or {}
    status = status_type.get('shortDetail') or status_type.get('description') or 'Scheduled'
    state = status_type.get('state', '')   # 'pre' | 'in' | 'post'
    is_live = state == 'in'
    is_complete = state == 'post'

    round_name = (comp.get('round') or {}).get('displayName', '')
    tournament = f"{tour.upper()} · {event_name}"
    if round_name:
        tournament += f" · {round_name}"

    date_str = (comp.get('startDate') or comp.get('date') or '')[:10]
    sorted_competitors = sorted(competitors, key=lambda x: x.get('order', 99))
    player_ids = [str(c.get('id', '')) for c in sorted_competitors]

    players = []
    for c in sorted_competitors:
        athlete = c.get('athlete') or {}
        name = athlete.get('shortName') or athlete.get('displayName') or c.get('name') or 'Player'
        # If the name looks like a match summary ("A vs B"), this is not a real player entry
        if ' vs ' in name.lower():
            return None
        lines = c.get('linescores') or []
        sets = []
        for line in lines:
            val = line.get('value')
            sets.append(str(int(float(val))) if val is not None else '—')
        game = str(c.get('score') or '').strip() or '—'
        c_status = c.get('status') or {}
        serving = bool(c_status.get('isCurrent'))
        players.append({
            'name': name,
            'sets': sets,
            'game': game,
            'serving': serving,
            'winner': bool(c.get('winner')),
        })

    return {
        'id': comp.get('id', ''),
        'tour': tour,
        'tournamentName': event_name,
        'round': round_name,
        'tournament': tournament,
        'date': date_str,
        'playerIds': player_ids,
        'status': status,
        'isLive': is_live,
        'isComplete': is_complete,
        'players': players,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        tour_param = (params.get('tour') or ['all'])[0]

        try:
            tours = ['atp', 'wta'] if tour_param == 'all' else [tour_param]
            all_matches: list = []
            errors: list = []

            for t in tours:
                if t not in ESPN_ENDPOINTS:
                    continue
                try:
                    all_matches.extend(fetch_tour(t))
                except Exception as e:
                    errors.append({'tour': t, 'error': str(e)})

            response: dict = {
                'matches': all_matches,
                'total': len(all_matches),
                'live': sum(1 for m in all_matches if m.get('isLive')),
                'fetchedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            }
            if errors:
                response['errors'] = errors

            self._send_json(200, response)

        except Exception as e:
            self._send_json(500, {'error': str(e), 'matches': []})

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
        pass  # suppress access logs
