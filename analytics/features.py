"""Feature engineering for tennis match prediction.

Builds per-player rolling statistics (including Elo ratings and
expanded serve/return metrics) and converts raw Sackmann CSV rows
into feature vectors suitable for a logistic-regression classifier.
"""

import math
import random
from collections import defaultdict
from datetime import datetime, timedelta


# ── Helpers ──────────────────────────────────────────────────────────────────

ELO_K = 32
ELO_INIT = 1500.0

def safe_float(val, default=0.0):
    try:
        v = float(val)
        return v if math.isfinite(v) else default
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def parse_tourney_date(date_str: str):
    """Parse Sackmann YYYYMMDD format → datetime (or None)."""
    try:
        return datetime.strptime(str(date_str).strip(), "%Y%m%d")
    except (ValueError, TypeError):
        return None


# ── Per-player rolling statistics ────────────────────────────────────────────

class PlayerStats:
    """Accumulates a single player's match history over time."""

    __slots__ = (
        "results", "serve_stats", "return_stats", "h2h",
        "elo", "surface_elo",
    )

    def __init__(self):
        self.results: list[tuple] = []       # (date, won, surface)
        self.serve_stats: list[tuple] = []   # (date, ace, svpt, 1stIn, 1stWon, 2ndWon, bpSaved, bpFaced, svGms)
        self.return_stats: list[tuple] = []  # (date, opp_svpt, opp_1stIn, opp_1stWon, opp_2ndWon, bpConv, bpChances, opp_svGms)
        self.h2h: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        self.elo: float = ELO_INIT
        self.surface_elo: dict[str, float] = defaultdict(lambda: ELO_INIT)

    # ── ingest ──

    def add_match(
        self, date, won: bool, surface: str, opponent_id: str,
        ace=0, svpt=0, first_in=0, first_won=0, second_won=0,
        bp_saved=0, bp_faced=0, sv_gms=0,
        opp_svpt=0, opp_first_in=0, opp_first_won=0, opp_second_won=0,
        opp_bp_saved=0, opp_bp_faced=0, opp_sv_gms=0,
    ):
        surf = surface.lower() if surface else ""
        self.results.append((date, won, surf))
        if svpt > 0:
            self.serve_stats.append((date, ace, svpt, first_in, first_won, second_won, bp_saved, bp_faced, sv_gms))
        if opp_svpt > 0:
            self.return_stats.append((date, opp_svpt, opp_first_in, opp_first_won, opp_second_won,
                                      opp_bp_faced - opp_bp_saved, opp_bp_faced, opp_sv_gms))
        if opponent_id:
            self.h2h[opponent_id][0 if won else 1] += 1

    def update_elo(self, opponent_elo: float, won: bool, surface: str):
        """Update overall and surface Elo after a match."""
        expected = 1.0 / (1.0 + math.pow(10, (opponent_elo - self.elo) / 400))
        self.elo += ELO_K * ((1.0 if won else 0.0) - expected)

        surf = surface.lower() if surface else ""
        if surf:
            opp_surf_elo = opponent_elo  # approximation
            s_expected = 1.0 / (1.0 + math.pow(10, (opp_surf_elo - self.surface_elo[surf]) / 400))
            self.surface_elo[surf] += ELO_K * ((1.0 if won else 0.0) - s_expected)

    # ── queries ──

    def win_rate(self, lookback_days=365, before_date=None, surface=None):
        if not self.results:
            return 0.5
        cutoff = (before_date - timedelta(days=lookback_days)) if before_date else None
        wins = total = 0
        for date, won, surf in reversed(self.results):
            if before_date and date >= before_date:
                continue
            if cutoff and date < cutoff:
                break
            if surface and surf != surface.lower():
                continue
            total += 1
            wins += won
        return wins / total if total > 0 else 0.5

    def serve_averages(self, lookback_days=365, before_date=None):
        if not self.serve_stats:
            return {"ace_rate": 0.0, "first_serve_win_pct": 0.0, "bp_save_rate": 0.0,
                    "spw": 0.0, "second_serve_win_pct": 0.0, "hold_pct": 0.0}
        cutoff = (before_date - timedelta(days=lookback_days)) if before_date else None
        t_ace = t_svpt = t_1stW = t_1stIn = t_2ndW = t_bpS = t_bpF = t_svGms = 0
        count = 0
        for date, ace, svpt, fin, fwon, swon, bps, bpf, svg in reversed(self.serve_stats):
            if before_date and date >= before_date:
                continue
            if cutoff and date < cutoff:
                break
            t_ace += ace; t_svpt += svpt; t_1stW += fwon; t_1stIn += fin
            t_2ndW += swon; t_bpS += bps; t_bpF += bpf; t_svGms += svg
            count += 1
        if count == 0:
            return {"ace_rate": 0.0, "first_serve_win_pct": 0.0, "bp_save_rate": 0.0,
                    "spw": 0.0, "second_serve_win_pct": 0.0, "hold_pct": 0.0}
        serve_won = t_1stW + t_2ndW
        second_serves = t_svpt - t_1stIn
        bp_lost = t_bpF - t_bpS
        holds = t_svGms - bp_lost if t_svGms > bp_lost else 0
        return {
            "ace_rate": t_ace / t_svpt if t_svpt else 0.0,
            "first_serve_win_pct": t_1stW / t_1stIn if t_1stIn else 0.0,
            "bp_save_rate": t_bpS / t_bpF if t_bpF else 0.0,
            "spw": serve_won / t_svpt if t_svpt else 0.0,
            "second_serve_win_pct": t_2ndW / second_serves if second_serves > 0 else 0.0,
            "hold_pct": holds / t_svGms if t_svGms else 0.0,
        }

    def return_averages(self, lookback_days=365, before_date=None):
        if not self.return_stats:
            return {"rpw": 0.0, "break_pct": 0.0}
        cutoff = (before_date - timedelta(days=lookback_days)) if before_date else None
        t_opp_svpt = t_opp_1stW = t_opp_2ndW = t_bp_conv = t_bp_ch = t_opp_svGms = 0
        count = 0
        for date, osvpt, ofin, ofwon, oswon, bpc, bpch, osvg in reversed(self.return_stats):
            if before_date and date >= before_date:
                continue
            if cutoff and date < cutoff:
                break
            t_opp_svpt += osvpt; t_opp_1stW += ofwon; t_opp_2ndW += oswon
            t_bp_conv += bpc; t_bp_ch += bpch; t_opp_svGms += osvg
            count += 1
        if count == 0:
            return {"rpw": 0.0, "break_pct": 0.0}
        opp_serve_won = t_opp_1stW + t_opp_2ndW
        return {
            "rpw": (t_opp_svpt - opp_serve_won) / t_opp_svpt if t_opp_svpt else 0.0,
            "break_pct": t_bp_conv / t_opp_svGms if t_opp_svGms else 0.0,
        }

    def get_h2h(self, opponent_id: str) -> tuple[int, int]:
        rec = self.h2h.get(opponent_id, [0, 0])
        return rec[0], rec[1]


# ── Build stats from historical data ────────────────────────────────────────

def build_player_stats(matches: list[dict]) -> dict[str, PlayerStats]:
    """Walk through matches chronologically, accumulate per-player stats and Elo."""
    stats: dict[str, PlayerStats] = {}
    sorted_matches = sorted(matches, key=lambda m: m.get("tourney_date", ""))

    for m in sorted_matches:
        wid = m.get("winner_id", "")
        lid = m.get("loser_id", "")
        if not wid or not lid:
            continue
        date = parse_tourney_date(m.get("tourney_date", ""))
        if not date:
            continue
        surface = (m.get("surface") or "").lower()

        for pid in (wid, lid):
            if pid not in stats:
                stats[pid] = PlayerStats()

        # Snapshot Elo *before* this match (used later in feature vectors)
        m["_w_elo"] = stats[wid].elo
        m["_l_elo"] = stats[lid].elo
        m["_w_surf_elo"] = stats[wid].surface_elo[surface] if surface else stats[wid].elo
        m["_l_surf_elo"] = stats[lid].surface_elo[surface] if surface else stats[lid].elo

        # Update Elo ratings
        w_elo_before = stats[wid].elo
        l_elo_before = stats[lid].elo
        stats[wid].update_elo(l_elo_before, won=True, surface=surface)
        stats[lid].update_elo(w_elo_before, won=False, surface=surface)

        # Winner serve stats + opponent (loser) return data
        stats[wid].add_match(
            date=date, won=True, surface=surface, opponent_id=lid,
            ace=safe_int(m.get("w_ace")), svpt=safe_int(m.get("w_svpt")),
            first_in=safe_int(m.get("w_1stIn")), first_won=safe_int(m.get("w_1stWon")),
            second_won=safe_int(m.get("w_2ndWon")),
            bp_saved=safe_int(m.get("w_bpSaved")), bp_faced=safe_int(m.get("w_bpFaced")),
            sv_gms=safe_int(m.get("w_SvGms")),
            opp_svpt=safe_int(m.get("l_svpt")), opp_first_in=safe_int(m.get("l_1stIn")),
            opp_first_won=safe_int(m.get("l_1stWon")), opp_second_won=safe_int(m.get("l_2ndWon")),
            opp_bp_saved=safe_int(m.get("l_bpSaved")), opp_bp_faced=safe_int(m.get("l_bpFaced")),
            opp_sv_gms=safe_int(m.get("l_SvGms")),
        )
        # Loser serve stats + opponent (winner) return data
        stats[lid].add_match(
            date=date, won=False, surface=surface, opponent_id=wid,
            ace=safe_int(m.get("l_ace")), svpt=safe_int(m.get("l_svpt")),
            first_in=safe_int(m.get("l_1stIn")), first_won=safe_int(m.get("l_1stWon")),
            second_won=safe_int(m.get("l_2ndWon")),
            bp_saved=safe_int(m.get("l_bpSaved")), bp_faced=safe_int(m.get("l_bpFaced")),
            sv_gms=safe_int(m.get("l_SvGms")),
            opp_svpt=safe_int(m.get("w_svpt")), opp_first_in=safe_int(m.get("w_1stIn")),
            opp_first_won=safe_int(m.get("w_1stWon")), opp_second_won=safe_int(m.get("w_2ndWon")),
            opp_bp_saved=safe_int(m.get("w_bpSaved")), opp_bp_faced=safe_int(m.get("w_bpFaced")),
            opp_sv_gms=safe_int(m.get("w_SvGms")),
        )

    return stats


# ── Feature-vector construction ──────────────────────────────────────────────

def build_feature_vector(match: dict, player_stats: dict[str, PlayerStats]) -> dict | None:
    """Convert one Sackmann CSV row into a feature dict (+ _target label).

    Player 1/2 assignment is randomised so the model can't learn
    that p1 always wins.  Returns None when data is insufficient.
    """
    wid = match.get("winner_id", "")
    lid = match.get("loser_id", "")
    if not wid or not lid:
        return None

    date = parse_tourney_date(match.get("tourney_date", ""))
    if not date:
        return None

    surface = (match.get("surface") or "").lower()
    best_of = safe_int(match.get("best_of"), 3)

    w_rank = safe_float(match.get("winner_rank"), 0)
    l_rank = safe_float(match.get("loser_rank"), 0)
    w_pts  = safe_float(match.get("winner_rank_points"), 0)
    l_pts  = safe_float(match.get("loser_rank_points"), 0)
    if w_rank == 0 and l_rank == 0:
        return None                 # both unranked → skip

    w_age = safe_float(match.get("winner_age"), 25)
    l_age = safe_float(match.get("loser_age"), 25)
    w_ht  = safe_float(match.get("winner_ht"), 180)
    l_ht  = safe_float(match.get("loser_ht"), 180)

    # Pre-match Elo snapshots (set by build_player_stats)
    w_elo = safe_float(match.get("_w_elo"), ELO_INIT)
    l_elo = safe_float(match.get("_l_elo"), ELO_INIT)
    w_surf_elo = safe_float(match.get("_w_surf_elo"), ELO_INIT)
    l_surf_elo = safe_float(match.get("_l_surf_elo"), ELO_INIT)

    # Random p1/p2 assignment
    if random.random() < 0.5:
        p1_id, p2_id = wid, lid
        p1_rank, p2_rank = w_rank, l_rank
        p1_pts, p2_pts = w_pts, l_pts
        p1_age, p2_age = w_age, l_age
        p1_ht, p2_ht = w_ht, l_ht
        p1_elo, p2_elo = w_elo, l_elo
        p1_surf_elo, p2_surf_elo = w_surf_elo, l_surf_elo
        target = 1
    else:
        p1_id, p2_id = lid, wid
        p1_rank, p2_rank = l_rank, w_rank
        p1_pts, p2_pts = l_pts, w_pts
        p1_age, p2_age = l_age, w_age
        p1_ht, p2_ht = l_ht, w_ht
        p1_elo, p2_elo = l_elo, w_elo
        p1_surf_elo, p2_surf_elo = l_surf_elo, w_surf_elo
        target = 0

    # Default rank for unranked players
    if p1_rank == 0: p1_rank = 500
    if p2_rank == 0: p2_rank = 500

    max_rank = max(p1_rank, p2_rank)
    max_pts  = max(p1_pts, p2_pts, 1)

    # Rolling player statistics (computed *before* this match's date)
    s1 = player_stats.get(p1_id)
    s2 = player_stats.get(p2_id)

    if s1:
        p1_wr  = s1.win_rate(before_date=date)
        p1_swr = s1.win_rate(before_date=date, surface=surface) if surface else p1_wr
        p1_srv = s1.serve_averages(before_date=date)
        p1_ret = s1.return_averages(before_date=date)
        h2h_w, h2h_l = s1.get_h2h(p2_id)
    else:
        p1_wr = p1_swr = 0.5
        p1_srv = {"ace_rate": 0.0, "first_serve_win_pct": 0.0, "bp_save_rate": 0.0,
                  "spw": 0.0, "second_serve_win_pct": 0.0, "hold_pct": 0.0}
        p1_ret = {"rpw": 0.0, "break_pct": 0.0}
        h2h_w = h2h_l = 0

    if s2:
        p2_wr  = s2.win_rate(before_date=date)
        p2_swr = s2.win_rate(before_date=date, surface=surface) if surface else p2_wr
        p2_srv = s2.serve_averages(before_date=date)
        p2_ret = s2.return_averages(before_date=date)
    else:
        p2_wr = p2_swr = 0.5
        p2_srv = {"ace_rate": 0.0, "first_serve_win_pct": 0.0, "bp_save_rate": 0.0,
                  "spw": 0.0, "second_serve_win_pct": 0.0, "hold_pct": 0.0}
        p2_ret = {"rpw": 0.0, "break_pct": 0.0}

    h2h_total = h2h_w + h2h_l

    return {
        "rank_diff":              p1_rank - p2_rank,
        "rank_ratio":             min(p1_rank, p2_rank) / max_rank if max_rank else 0.5,
        "points_diff":            p1_pts - p2_pts,
        "points_ratio":           min(p1_pts, p2_pts) / max_pts if max_pts else 0.5,
        "age_diff":               p1_age - p2_age,
        "height_diff":            p1_ht - p2_ht,
        "h2h_ratio":              h2h_w / h2h_total if h2h_total else 0.5,
        "p1_win_rate_52w":        p1_wr,
        "p2_win_rate_52w":        p2_wr,
        "p1_surface_win_rate":    p1_swr,
        "p2_surface_win_rate":    p2_swr,
        "p1_ace_rate":            p1_srv["ace_rate"],
        "p2_ace_rate":            p2_srv["ace_rate"],
        "p1_bp_save_rate":        p1_srv["bp_save_rate"],
        "p2_bp_save_rate":        p2_srv["bp_save_rate"],
        "p1_first_serve_win_pct": p1_srv["first_serve_win_pct"],
        "p2_first_serve_win_pct": p2_srv["first_serve_win_pct"],
        "elo_diff":               p1_elo - p2_elo,
        "surface_elo_diff":       p1_surf_elo - p2_surf_elo,
        "p1_spw":                 p1_srv["spw"],
        "p2_spw":                 p2_srv["spw"],
        "p1_rpw":                 p1_ret["rpw"],
        "p2_rpw":                 p2_ret["rpw"],
        "p1_second_serve_win_pct": p1_srv["second_serve_win_pct"],
        "p2_second_serve_win_pct": p2_srv["second_serve_win_pct"],
        "p1_hold_pct":            p1_srv["hold_pct"],
        "p2_hold_pct":            p2_srv["hold_pct"],
        "p1_break_pct":           p1_ret["break_pct"],
        "p2_break_pct":           p2_ret["break_pct"],
        "surface_clay":           1.0 if surface == "clay" else 0.0,
        "surface_grass":          1.0 if surface == "grass" else 0.0,
        "surface_hard":           1.0 if surface == "hard" else 0.0,
        "surface_carpet":         1.0 if surface == "carpet" else 0.0,
        "best_of_5":              1.0 if best_of == 5 else 0.0,
        "_target":                target,
    }


def build_dataset(
    matches: list[dict],
    player_stats: dict[str, PlayerStats],
) -> tuple[list[dict], list[int]]:
    """Build the full (features, targets) dataset from historical matches."""
    features_list: list[dict] = []
    targets: list[int] = []
    for m in matches:
        fv = build_feature_vector(m, player_stats)
        if fv is None:
            continue
        target = fv.pop("_target")
        features_list.append(fv)
        targets.append(target)
    return features_list, targets
