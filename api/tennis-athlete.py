from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error
import time
import gzip
from urllib.parse import urlparse, parse_qs, quote

BASE = 'https://site.api.espn.com/apis/site/v2/sports/tennis'
TOURS = {'atp', 'wta'}
CACHE_TTL = 300
_cache: dict = {}


def _fetch_json(url: str) -> dict:
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
        return json.loads(raw.decode('utf-8'))


def _extract_athlete_ids(tour: str, query: str = '') -> list:
    data = _fetch_json(f'{BASE}/{tour}/scoreboard')
    out = []
    query_l = query.lower().strip()
    for event in data.get('events', []):
        for grouping in event.get('groupings', []):
            for comp in grouping.get('competitions', []):
                for c in comp.get('competitors', []):
                    athlete = c.get('athlete') or {}
                    roster = c.get('roster') or {}
                    cid = str(c.get('id') or '').strip()
                    if not cid:
                        continue
                    name = (
                        athlete.get('displayName')
                        or athlete.get('shortName')
                        or roster.get('displayName')
                        or roster.get('shortDisplayName')
                        or c.get('name')
                        or ''
                    )
                    if query_l and query_l not in name.lower():
                        continue
                    out.append({'id': cid, 'name': name})
    dedup = {}
    for row in out:
        dedup[row['id']] = row
    return list(dedup.values())


def _normalize_athlete(payload: dict) -> dict:
    athlete = payload.get('athlete') or payload
    country = athlete.get('citizenshipCountry') or {}
    return {
        'id': str(athlete.get('id') or ''),
        'displayName': athlete.get('displayName') or athlete.get('shortName') or 'Unknown',
        'shortName': athlete.get('shortName') or athlete.get('displayName') or 'Unknown',
        'rank': (athlete.get('rankings') or [{}])[0].get('current') if athlete.get('rankings') else athlete.get('rank'),
        'age': athlete.get('age'),
        'birthDate': athlete.get('dateOfBirth'),
        'height': athlete.get('displayHeight') or athlete.get('height'),
        'weight': athlete.get('displayWeight') or athlete.get('weight'),
        'hand': athlete.get('hand'),
        'country': {
            'name': country.get('name'),
            'abbreviation': country.get('abbreviation'),
            'flag': country.get('flag')
        },
    }


def _get_athlete(tour: str, athlete_id: str) -> dict:
    key = f'{tour}:{athlete_id}'
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached['ts'] < CACHE_TTL:
        return cached['data']

    payload = _fetch_json(f'{BASE}/{tour}/athletes/{quote(athlete_id)}')
    data = _normalize_athlete(payload)
    _cache[key] = {'ts': now, 'data': data}
    return data


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        tour = (params.get('tour') or ['atp'])[0].lower()
        if tour not in TOURS:
            self._send_json(400, {'error': 'tour must be one of atp,wta'})
            return

        athlete_id = (params.get('athleteId') or [''])[0].strip()
        name = (params.get('name') or [''])[0].strip()

        try:
            if athlete_id:
                athlete = _get_athlete(tour, athlete_id)
                self._send_json(200, {'tour': tour, 'athlete': athlete})
                return

            matches = _extract_athlete_ids(tour, name)
            if name and matches:
                athlete = _get_athlete(tour, matches[0]['id'])
                self._send_json(200, {'tour': tour, 'athlete': athlete, 'candidateIds': matches[:10]})
                return

            self._send_json(200, {
                'tour': tour,
                'candidateIds': matches[:20],
                'message': 'Provide athleteId, or pass name to resolve from current scoreboard.'
            })
        except urllib.error.HTTPError as e:
            self._send_json(e.code, {'error': f'ESPN HTTPError: {e.reason}'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

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
