from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import urllib.error
import time
import gzip
from html.parser import HTMLParser

_cache: dict = {}
CACHE_TTL = 300  # 5 minutes

SOURCES = [
    {
        'id': 'tennistonic',
        'name': 'Tennis Tonic',
        'search_url': 'https://tennistonic.com/?s={}',
        'color': '#62f2a6',
    },
    {
        'id': 'grandstand',
        'name': 'The Grandstand',
        'search_url': 'https://tenngrand.com/?s={}',
        'color': '#7dd3fc',
    },
    {
        'id': 'lwos',
        'name': 'Last Word on Sports',
        'search_url': 'https://lastwordonsports.com/?s={}',
        'color': '#f9a8d4',
    },
]


class ArticleParser(HTMLParser):
    """Extract article titles + links from WordPress-style search results."""

    def __init__(self):
        super().__init__()
        self.articles: list = []
        self._in_heading = False
        self._in_link = False
        self._href = ''
        self._text: list = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get('class', '') or ''
        if tag in ('h2', 'h3') and any(
            kw in cls for kw in ('entry-title', 'post-title', 'article-title', 'title')
        ):
            self._in_heading = True
        if self._in_heading and tag == 'a':
            self._in_link = True
            self._href = attrs_dict.get('href', '')
            self._text = []

    def handle_data(self, data):
        if self._in_link:
            self._text.append(data.strip())

    def handle_endtag(self, tag):
        if tag == 'a' and self._in_link:
            title = ' '.join(t for t in self._text if t)
            if title and self._href and len(title) > 8:
                self.articles.append({'title': title[:130], 'url': self._href})
            self._in_link = False
            self._href = ''
            self._text = []
        if tag in ('h2', 'h3'):
            self._in_heading = False


def fetch_articles(source: dict, query: str, limit: int = 4) -> list:
    encoded = urllib.parse.quote_plus(query)
    url = source['search_url'].format(encoded)
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Encoding': 'gzip, deflate',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
            if resp.info().get('Content-Encoding') == 'gzip':
                raw = gzip.decompress(raw)
            html = raw.decode('utf-8', errors='replace')
        parser = ArticleParser()
        parser.feed(html)
        return parser.articles[:limit]
    except Exception:
        return []


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        player1    = (params.get('player1')    or [''])[0].strip()
        player2    = (params.get('player2')    or [''])[0].strip()
        tournament = (params.get('tournament') or [''])[0].strip()
        year       = (params.get('year')       or [''])[0].strip()

        if not player1 and not player2 and not tournament:
            self._send_json(400, {'error': 'player1, player2, or tournament required'})
            return

        # Primary: tournament + year (sites publish tournament-level previews)
        # Fallback: player names when no tournament is known
        if tournament:
            primary_query   = f"{tournament} {year} tennis predictions".strip()
            secondary_query = f"{player1} {player2} {tournament} {year} tennis".strip()
        else:
            primary_query   = f"{player1} {player2} tennis".strip()
            secondary_query = None

        cache_key = primary_query.lower()
        now = time.time()
        if cache_key in _cache and now - _cache[cache_key]['ts'] < CACHE_TTL:
            self._send_json(200, _cache[cache_key]['data'])
            return

        results = []
        for source in SOURCES:
            articles = fetch_articles(source, primary_query)
            # If primary turned up nothing, try the player-name query
            if not articles and secondary_query:
                articles = fetch_articles(source, secondary_query)
            results.append({
                'id': source['id'],
                'name': source['name'],
                'color': source['color'],
                'searchUrl': source['search_url'].format(urllib.parse.quote_plus(primary_query)),
                'articles': articles,
            })

        response = {'sources': results, 'query': primary_query}
        _cache[cache_key] = {'ts': now, 'data': response}
        self._send_json(200, response)

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
