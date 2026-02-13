from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import urllib.error
import time
import gzip
from html.parser import HTMLParser
import re

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


def compact_whitespace(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '')).strip()


def normalize_name_tokens(full_name: str) -> list:
    parts = [p for p in re.split(r'[^A-Za-z]+', full_name or '') if p]
    if not parts:
        return []
    # First + last names are usually enough for tennis preview mentions.
    if len(parts) == 1:
        return [parts[0].lower()]
    return [parts[0].lower(), parts[-1].lower()]


def infer_predicted_winner(text: str, fullname1: str, fullname2: str) -> str:
    text_lower = (text or '').lower()

    def score_player(full_name: str):
        score = 0
        tokens = normalize_name_tokens(full_name)
        for token in tokens:
            if not token:
                continue
            if re.search(rf'\b{re.escape(token)}\b\s+(?:to win|wins|in \d|is the pick|edges|takes)', text_lower):
                score += 3
            if re.search(rf'(?:pick|prediction|expect|backing)\s*[:\-]?\s*[^.\n]{{0,45}}\b{re.escape(token)}\b', text_lower):
                score += 4
            score += len(re.findall(rf'\b{re.escape(token)}\b', text_lower))
        return score

    s1 = score_player(fullname1)
    s2 = score_player(fullname2)
    if s1 == 0 and s2 == 0:
        return ''
    if s1 == s2:
        return ''
    return fullname1 if s1 > s2 else fullname2


class ParagraphPredictionParser(HTMLParser):
    """Extract likely prediction paragraphs from article bodies."""

    KEYWORDS = (
        'prediction', 'predict', 'pick', 'winner', 'expect', 'should win',
        'to win', 'in two sets', 'in three sets', 'preview', 'odds',
    )

    def __init__(self):
        super().__init__()
        self.title = ''
        self.paragraphs = []
        self._in_title = False
        self._in_p = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self._in_title = True
        if tag == 'p':
            self._in_p = True
            self._buf = []

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_p:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        if tag == 'p' and self._in_p:
            text = compact_whitespace(' '.join(self._buf))
            if len(text) > 35:
                self.paragraphs.append(text)
            self._in_p = False
            self._buf = []


def fetch_lwos_predictions(fullname1: str, fullname2: str, tournament: str, limit: int = 3) -> list:
    """Crawl LWOS tennis index, then article pages, to detect explicit prediction text."""
    last1 = (fullname1.split()[-1] if fullname1 else '').lower()
    last2 = (fullname2.split()[-1] if fullname2 else '').lower()
    filter_terms = [t for t in (last1, last2, (tournament or '').lower()) if t]

    listing = fetch_list_source('https://lastwordonsports.com/tennis/', filter_terms, limit=10)
    found = []

    for article in listing:
        if len(found) >= limit:
            break
        url = article.get('url', '')
        if not url:
            continue
        try:
            html = fetch_html(url, timeout=8)
        except Exception:
            continue

        parser = ParagraphPredictionParser()
        parser.feed(html)
        if not parser.paragraphs:
            continue

        tokens1 = normalize_name_tokens(fullname1)
        tokens2 = normalize_name_tokens(fullname2)

        candidates = []
        for p in parser.paragraphs:
            lp = p.lower()
            has_kw = any(kw in lp for kw in ParagraphPredictionParser.KEYWORDS)
            has_p1 = any(re.search(rf'\b{re.escape(t)}\b', lp) for t in tokens1)
            has_p2 = any(re.search(rf'\b{re.escape(t)}\b', lp) for t in tokens2)
            if has_kw and (has_p1 or has_p2):
                candidates.append(p)

        if not candidates:
            continue

        snippet = ' … '.join(candidates[:2])[:320]
        predicted = infer_predicted_winner(' '.join(candidates[:3]), fullname1, fullname2)

        found.append({
            'title': compact_whitespace(article.get('title') or parser.title.split('|')[0]),
            'url': url,
            'snippet': snippet,
            'predictedWinner': predicted,
        })

    return found


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

        # 3. Last Word on Sports — crawl candidate stories and extract prediction text
        lwos_articles = fetch_lwos_predictions(fullname1, fullname2, tournament)
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
