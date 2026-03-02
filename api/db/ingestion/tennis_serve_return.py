"""
Tennis serve & return stats ingestion into Neo4j.

Parses the Tennis Abstract leaders JS data files, aggregates per-player
serve and return statistics, and upserts them onto Player nodes.

Data sources (match-level JS arrays, aggregated here):
  ATP 1-50:   https://www.tennisabstract.com/jsmatches/leadersource.js
  ATP 51-100: https://www.tennisabstract.com/jsmatches/leadersource51.js
  WTA 1-50:   https://www.tennisabstract.com/jsmatches/leadersource_wta.js
  WTA 51-100: https://www.tennisabstract.com/jsmatches/leadersource51_wta.js

Usage (standalone):
    python -m api.db.ingestion.tennis_serve_return --tours atp wta
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import gzip
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from api.db.neo4j_client import run_write  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'en-US,en;q=0.9',
}

# Each tour has multiple JS sources covering different rank ranges.
_JS_URLS: dict[str, list[str]] = {
    'atp': [
        'https://www.tennisabstract.com/jsmatches/leadersource.js',
        'https://www.tennisabstract.com/jsmatches/leadersource51.js',
    ],
    'wta': [
        'https://www.tennisabstract.com/jsmatches/leadersource_wta.js',
        'https://www.tennisabstract.com/jsmatches/leadersource51_wta.js',
    ],
}

# Column mapping from Tennis Abstract's matchhead array (indices 0-44).
# Stat columns start at index 22.
_MATCHHEAD = [
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

_STAT_START = 22  # index where numeric stats begin


# ---------------------------------------------------------------------------
# Fetching & parsing
# ---------------------------------------------------------------------------

def _fetch_js(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.info().get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        return raw.decode('utf-8', errors='replace')


def _parse_matchmx(js_text: str) -> list[list[str]]:
    """Extract the matchmx array from the JS source."""
    # The JS file contains: var matchmx = [ [...], [...], ... ];
    # We find the array and parse it as JSON.
    match = re.search(r'var\s+matchmx\s*=\s*(\[.*?\])\s*;', js_text, re.DOTALL)
    if not match:
        return []
    return json.loads(match.group(1))


def _parse_crank(js_text: str) -> dict[str, int]:
    """Extract the crank (player → ATP/WTA rank) dict from JS source."""
    match = re.search(r'crank\s*=\s*(\{.*?\})\s*;', js_text, re.DOTALL)
    if not match:
        return {}
    # JS object uses single quotes; convert to valid JSON
    raw = match.group(1)
    raw = raw.replace("'", '"')
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _safe_int(v: str) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


def _aggregate_stats(matches: list[list[str]]) -> dict[str, dict]:
    """Aggregate match-level data into per-player stat totals.

    Replicates the aggregation logic from Tennis Abstract's makeMatchTable().
    """
    pstats: dict[str, dict] = {}

    for row in matches:
        if len(row) < len(_MATCHHEAD):
            continue

        m = dict(zip(_MATCHHEAD, row))

        # Skip walkovers / retirements for W/L counting
        score = m.get('score', '')
        wl = m.get('wl', '')
        player = m.get('player', '').strip()
        if not player:
            continue

        if player not in pstats:
            pstats[player] = {
                'W': 0, 'L': 0, 'oranks': [],
                **{k: 0 for k in _MATCHHEAD[_STAT_START:]},
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

        # Accumulate all stat columns
        for key in _MATCHHEAD[_STAT_START:]:
            ps[key] += _safe_int(m.get(key, '0'))

    return pstats


def _compute_player_stats(
    name: str, ps: dict, rank: int | None,
) -> dict | None:
    """Compute derived serve/return percentages from raw totals."""
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

    # Opponent rank stats
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

    return {
        'name': name,
        'rank': rank,
        'matches': matches,
        'wins': ps['W'],
        'losses': ps['L'],
        'match_win_pct': _pct(ps['W'], matches),
        # Serve stats
        'spw': _pct(serve_won, ps['pts']),
        'spw_in_play': _pct(serve_won - ps['aces'],
                            ps['pts'] - ps['aces'] - ps['dfs']),
        'ace_rate': _pct(ps['aces'], ps['pts']),
        'df_rate': _pct(ps['dfs'], ps['pts']),
        'df_per_second_serve': _pct(ps['dfs'], second_serves),
        'first_serve_in': _pct(ps['firsts'], ps['pts']),
        'first_serve_won': _pct(ps['fwon'], ps['firsts']),
        'second_serve_won': _pct(ps['swon'], second_serves),
        'hold_pct': _pct(holds, ps['games']),
        'aces': ps['aces'],
        'dfs': ps['dfs'],
        # Return stats
        'rpw': _pct(ps['opts'] - opp_serve_won, ps['opts']),
        'rpw_in_play': _pct(
            ps['opts'] - opp_serve_won - ps['oaces'],
            ps['opts'] - ps['oaces'] - ps['odfs'],
        ) if (ps['opts'] - ps['oaces'] - ps['odfs']) else None,
        'v_ace_rate': _pct(ps['oaces'], ps['opts']),
        'v_df_rate': _pct(ps['odfs'], ps['opts']),
        'v_first_serve_won': _pct(ps['ofirsts'] - ps['ofwon'],
                                  ps['ofirsts']),
        'v_second_serve_won': _pct(
            ps['opts'] - ps['ofirsts'] - ps['oswon'],
            ps['opts'] - ps['ofirsts'],
        ),
        'break_pct': _pct(bp_conv, ps['ogames']),
        # Overall
        'dominance_ratio': round(
            _pct(ps['opts'] - opp_serve_won, ps['opts'])
            / (1 - _pct(serve_won, ps['pts'])), 2
        ) if _pct(serve_won, ps['pts']) and _pct(serve_won, ps['pts']) < 1 else None,
        'tpw': _pct(
            serve_won + (ps['opts'] - opp_serve_won),
            ps['pts'] + ps['opts'],
        ),
        'median_opp_rank': median_opp_rank,
        'mean_opp_rank': mean_opp_rank,
    }


def scrape_serve_return(tour: str) -> list[dict]:
    """Fetch all JS sources for a tour and return aggregated per-player stats."""
    urls = _JS_URLS.get(tour, _JS_URLS['atp'])
    all_matches: list[list[str]] = []
    all_cranks: dict[str, int] = {}

    for url in urls:
        print(f"  Fetching {url} ...")
        js_text = _fetch_js(url)
        matches = _parse_matchmx(js_text)
        cranks = _parse_crank(js_text)
        print(f"    → {len(matches)} match rows, {len(cranks)} ranked players")
        all_matches.extend(matches)
        all_cranks.update(cranks)

    print(f"  Total: {len(all_matches)} match rows")
    pstats = _aggregate_stats(all_matches)
    print(f"  Aggregated stats for {len(pstats)} players")

    players = []
    for name, ps in pstats.items():
        rank = all_cranks.get(name)
        computed = _compute_player_stats(name, ps, rank)
        if computed:
            players.append(computed)

    # Sort by SPW descending (serve ranking)
    players.sort(key=lambda p: p.get('spw') or 0, reverse=True)

    # Assign serve and return ranks
    by_spw = sorted(players, key=lambda p: p.get('spw') or 0, reverse=True)
    by_rpw = sorted(players, key=lambda p: p.get('rpw') or 0, reverse=True)
    spw_ranks = {p['name']: i + 1 for i, p in enumerate(by_spw)}
    rpw_ranks = {p['name']: i + 1 for i, p in enumerate(by_rpw)}

    for p in players:
        p['serve_rank'] = spw_ranks.get(p['name'])
        p['return_rank'] = rpw_ranks.get(p['name'])

    print(f"  Computed stats for {len(players)} players")
    return players


# ---------------------------------------------------------------------------
# Neo4j ingestion
# ---------------------------------------------------------------------------

_UPSERT_SERVE_RETURN = """
MATCH (p:Player)
WHERE toLower(p.name) = toLower($name)
SET p.spw                = $spw,
    p.spw_in_play        = $spw_in_play,
    p.ace_rate           = $ace_rate,
    p.df_rate            = $df_rate,
    p.first_serve_in     = $first_serve_in,
    p.first_serve_won    = $first_serve_won,
    p.second_serve_won   = $second_serve_won,
    p.hold_pct           = $hold_pct,
    p.rpw                = $rpw,
    p.rpw_in_play        = $rpw_in_play,
    p.v_ace_rate         = $v_ace_rate,
    p.v_first_serve_won  = $v_first_serve_won,
    p.v_second_serve_won = $v_second_serve_won,
    p.break_pct          = $break_pct,
    p.dominance_ratio    = $dominance_ratio,
    p.tpw                = $tpw,
    p.serve_rank         = $serve_rank,
    p.return_rank        = $return_rank,
    p.serve_return_updated_at = $updated_at
"""


def ingest_serve_return(tour: str) -> dict:
    """Scrape serve/return stats and upsert into Neo4j Player nodes."""
    print(f"\n{'='*60}")
    print(f"Ingesting {tour.upper()} serve/return stats")
    print(f"{'='*60}")

    players = scrape_serve_return(tour)
    if not players:
        print("  No players scraped — skipping")
        return {'tour': tour, 'scraped': 0, 'updated': 0}

    updated_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    updated = 0

    for p in players:
        if not p.get('name'):
            continue
        run_write(_UPSERT_SERVE_RETURN, {
            'name': p['name'],
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
            'updated_at': updated_at,
        })
        updated += 1

    print(f"  Updated {updated} player nodes")
    return {'tour': tour, 'scraped': len(players), 'updated': updated}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ingest Tennis Abstract serve/return stats into Neo4j",
    )
    parser.add_argument(
        "--tours", nargs="+", default=["atp"],
        choices=["atp", "wta"],
        help="Tours to ingest (default: atp)",
    )
    args = parser.parse_args()

    results = []
    for tour in args.tours:
        result = ingest_serve_return(tour)
        results.append(result)

    print(f"\nDone. Results: {results}")


if __name__ == "__main__":
    main()
