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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'en-US,en;q=0.9',
}


def fetch_html(url: str, timeout: int = 7) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.info().get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        return raw.decode('utf-8', errors='replace')


# ── Article list parser (category / section pages) ───────────────────────────

class ArticleListParser(HTMLParser):
    """Extract article titles + links from WordPress-style listing pages."""

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


def filter_articles(articles: list, terms: list, limit: int = 4) -> list:
    """Return articles whose title contains any of the search terms."""
    lower_terms = [t.lower() for t in terms if t]
    matched = [
        a for a in articles
        if any(term in a['title'].lower() for term in lower_terms)
    ]
    # Fall back to most recent articles if nothing matched
    return matched[:limit] if matched else articles[:limit]


def fetch_list_source(list_url: str, filter_terms: list, limit: int = 4) -> list:
    try:
        html = fetch_html(list_url)
    except Exception:
        return []
    parser = ArticleListParser()
    parser.feed(html)
    return filter_articles(parser.articles, filter_terms, limit)


# ── Tennis Tonic H2H content scraper ─────────────────────────────────────────

class H2HContentParser(HTMLParser):
    """Extract prediction paragraphs from a Tennis Tonic H2H page."""

    PRED_KEYWORDS = (
        'prediction', 'predict', 'pick', 'winner', 'expect',
        'favor', 'favour', 'odds', 'bet', 'tip', 'preview',
        'should win', 'likely to', 'advantage',
    )

    def __init__(self, player_terms: list):
        super().__init__()
        self.snippets: list = []
        self.page_title: str = ''
        self._player_terms = [t.lower() for t in player_terms if t]
        self._in_content = False
        self._content_depth = 0
        self._in_p = False
        self._p_text: list = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = (attrs_dict.get('class', '') or '').lower()
        if tag == 'title':
            self._in_title = True
        if tag == 'div' and any(kw in cls for kw in (
            'entry-content', 'post-content', 'article-content',
            'post-body', 'the-content',
        )):
            self._in_content = True
            self._content_depth = 1
        elif self._in_content and tag == 'div':
            self._content_depth += 1
        if self._in_content and tag == 'p':
            self._in_p = True
            self._p_text = []

    def handle_data(self, data):
        if self._in_title:
            self.page_title += data
        if self._in_p:
            self._p_text.append(data)

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        if self._in_content and tag == 'div':
            self._content_depth -= 1
            if self._content_depth <= 0:
                self._in_content = False
        if tag == 'p' and self._in_p:
            text = ' '.join(self._p_text).strip()
            if len(text) > 40:
                text_lower = text.lower()
                has_pred_kw = any(kw in text_lower for kw in self.PRED_KEYWORDS)
                has_player  = any(t in text_lower for t in self._player_terms)
                if has_pred_kw or (has_player and len(text) > 80):
                    self.snippets.append(text[:300])
            self._in_p = False
            self._p_text = []


def fetch_tennistonic_h2h(fullname1: str, fullname2: str) -> list:
    """Fetch the Tennis Tonic H2H page and return prediction snippets."""
    def slugify(n):
        return n.strip().replace(' ', '-')

    slug = f"{slugify(fullname1)}-Vs-{slugify(fullname2)}"
    url  = f"https://tennistonic.com/head-to-head-compare/{slug}/"

    try:
        html = fetch_html(url)
    except Exception:
        return []

    last1 = fullname1.split()[-1] if fullname1 else ''
    last2 = fullname2.split()[-1] if fullname2 else ''
    parser = H2HContentParser([last1, last2, fullname1, fullname2])
    parser.feed(html)

    if not parser.snippets:
        return []

    title = parser.page_title.split('|')[0].strip() or f"{fullname1} vs {fullname2}"
    snippet = ' … '.join(parser.snippets[:3])
    return [{'title': title, 'url': url, 'snippet': snippet}]


# ── Request handler ───────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        player1    = (params.get('player1')    or [''])[0].strip()
        player2    = (params.get('player2')    or [''])[0].strip()
        fullname1  = (params.get('fullname1')  or [''])[0].strip() or player1
        fullname2  = (params.get('fullname2')  or [''])[0].strip() or player2
        tournament = (params.get('tournament') or [''])[0].strip()

        if not player1 and not player2 and not tournament:
            self._send_json(400, {'error': 'player1, player2, or tournament required'})
            return

        cache_key = f"{fullname1}|{fullname2}|{tournament}".lower()
        now = time.time()
        if cache_key in _cache and now - _cache[cache_key]['ts'] < CACHE_TTL:
            self._send_json(200, _cache[cache_key]['data'])
            return

        # Filter terms for list sources: last names + tournament
        last1 = fullname1.split()[-1] if fullname1 else ''
        last2 = fullname2.split()[-1] if fullname2 else ''
        filter_terms = [t for t in [last1, last2, tournament] if t]

        results = []

        # 1. Tennis Tonic H2H — direct structured page
        tt_articles = fetch_tennistonic_h2h(fullname1, fullname2)
        results.append({
            'id': 'tennistonic',
            'name': 'Tennis Tonic H2H',
            'color': '#62f2a6',
            'articles': tt_articles,
        })

        # 2. The Grandstand — match previews category page, filtered by player name
        gs_articles = fetch_list_source(
            'https://tenngrand.com/category/match-previews/',
            filter_terms,
        )
        results.append({
            'id': 'grandstand',
            'name': 'The Grandstand',
            'color': '#7dd3fc',
            'articles': gs_articles,
        })

        # 3. Last Word on Sports — tennis section, filtered by player name
        lwos_articles = fetch_list_source(
            'https://lastwordonsports.com/tennis/',
            filter_terms,
        )
        results.append({
            'id': 'lwos',
            'name': 'Last Word on Sports',
            'color': '#f9a8d4',
            'articles': lwos_articles,
        })

        response = {'sources': results}
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
