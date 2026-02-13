from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error
import time
import gzip

ESPN_URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard'

_cache: dict = {}
CACHE_TTL = 30  # seconds


def fetch_scoreboard(date_str: str = '', conference: str = '', top25: bool = False, limit: int = 200) -> list:
    now = time.time()
    key = f'{date_str}_{conference}_{top25}'
    if key in _cache and now - _cache[key]['ts'] < CACHE_TTL:
        return _cache[key]['data']

    url = ESPN_URL
    params = []
    if date_str:
        params.append(f'dates={date_str.replace("-", "")}')
    if conference:
        params.append(f'groups={conference}')
    params.append(f'limit={limit}')
    if params:
        url += '?' + '&'.join(params)

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

    games = []
    for event in data.get('events', []):
        for comp in event.get('competitions', []):
            g = normalize(comp, event)
            if g:
                games.append(g)

    if top25:
        games = [g for g in games if g.get('awayRank') or g.get('homeRank')]

    _cache[key] = {'ts': now, 'data': games}
    return games


def normalize(comp: dict, event: dict):
    competitors = comp.get('competitors') or []
    if len(competitors) < 2:
        return None

    status_obj = comp.get('status') or {}
    status_type = status_obj.get('type') or {}
    state = status_type.get('state', '')  # 'pre' | 'in' | 'post'
    is_live = state == 'in'
    is_complete = state == 'post'

    detail = status_type.get('shortDetail') or status_type.get('detail') or status_type.get('description') or 'Scheduled'
    clock = status_obj.get('displayClock', '')
    period = status_obj.get('period', 0)

    date_str = (comp.get('date') or event.get('date', ''))[:10]

    # Broadcasts
    broadcasts = []
    for b in comp.get('broadcasts', []):
        broadcasts.extend(b.get('names', []))

    # Conference
    conference_name = ''
    groups = comp.get('groups') or {}
    if groups:
        conference_name = groups.get('name', '')

    teams = []
    for c in competitors:
        team_data = c.get('team') or {}
        records = c.get('records') or []
        record_str = records[0].get('summary', '') if records else ''

        # Half scores from linescores
        linescores = c.get('linescores') or []
        halves = []
        for ls in linescores:
            val = ls.get('value')
            halves.append(str(int(float(val))) if val is not None else '—')

        # Ranking (curatedRank or rank)
        rank = 0
        curated = c.get('curatedRank') or {}
        if curated.get('current'):
            rank = curated['current']
        elif c.get('rank'):
            rank = c['rank']

        teams.append({
            'id': str(team_data.get('id', '')),
            'name': team_data.get('displayName', ''),
            'shortName': team_data.get('shortDisplayName', team_data.get('name', '')),
            'abbreviation': team_data.get('abbreviation', ''),
            'logo': team_data.get('logo', ''),
            'score': str(c.get('score', '—')),
            'homeAway': c.get('homeAway', ''),
            'winner': bool(c.get('winner')),
            'record': record_str,
            'halves': halves,
            'rank': rank if rank and rank <= 25 else 0,
        })

    # Sort: away team first, home team second
    teams.sort(key=lambda t: 0 if t['homeAway'] == 'away' else 1)

    # Venue
    venue = comp.get('venue') or {}
    venue_name = venue.get('fullName', '')

    # Odds
    odds_str = ''
    odds_list = comp.get('odds') or []
    if odds_list:
        odds_str = odds_list[0].get('details', '')

    away = teams[0] if teams else {}
    home = teams[1] if len(teams) > 1 else {}

    return {
        'id': str(comp.get('id', '')),
        'date': date_str,
        'status': detail,
        'clock': clock,
        'period': period,
        'isLive': is_live,
        'isComplete': is_complete,
        'teams': teams,
        'venue': venue_name,
        'broadcasts': broadcasts,
        'odds': odds_str,
        'conference': conference_name,
        'awayRank': away.get('rank', 0),
        'homeRank': home.get('rank', 0),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        date_param = (params.get('date') or [''])[0]
        conference_param = (params.get('conference') or [''])[0]
        top25_param = (params.get('top25') or [''])[0]

        try:
            games = fetch_scoreboard(
                date_param,
                conference=conference_param,
                top25=top25_param.lower() == 'true',
            )

            response: dict = {
                'games': games,
                'total': len(games),
                'live': sum(1 for g in games if g.get('isLive')),
                'fetchedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            }

            self._send_json(200, response)

        except Exception as e:
            self._send_json(500, {'error': str(e), 'games': []})

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
