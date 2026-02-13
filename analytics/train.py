#!/usr/bin/env python3
"""CLI — fetch Sackmann data, engineer features, and train the prediction model.

Usage:
    python analytics/train.py                        # defaults
    python analytics/train.py --force                # re-download all CSVs
    python analytics/train.py --tours atp            # ATP only
    python analytics/train.py --start-year 2015      # smaller dataset
"""

import argparse
import os
import random
import sys

# Ensure project root is on sys.path so `analytics` is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics import config
from analytics.data_cache import ensure_dirs, fetch_all_matches
from analytics.features import build_dataset, build_player_stats
from analytics.model import save_model, train


def main():
    parser = argparse.ArgumentParser(description="Train the tennis match-prediction model")
    parser.add_argument("--start-year", type=int, default=config.TRAINING_YEAR_START)
    parser.add_argument("--end-year",   type=int, default=config.TRAINING_YEAR_END)
    parser.add_argument("--tours",      nargs="+", default=["atp", "wta"], choices=["atp", "wta"])
    parser.add_argument("--force",      action="store_true", help="Force re-download of cached CSVs")
    parser.add_argument("--output",     default=config.MODEL_PATH)
    parser.add_argument("--seed",       type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    ensure_dirs()

    # 1. Fetch ────────────────────────────────────────────────────────────────
    print("=" * 60)
    print("STEP 1 — Fetching match data from Sackmann repos")
    print("=" * 60)
    all_matches: list[dict] = []
    for tour in args.tours:
        print(f"\n{tour.upper()}:")
        matches = fetch_all_matches(tour, args.start_year, args.end_year, force=args.force)
        all_matches.extend(matches)
    print(f"\nTotal raw matches: {len(all_matches):,}")

    # 2. Player stats ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 2 — Building rolling player statistics")
    print("=" * 60)
    player_stats = build_player_stats(all_matches)
    print(f"Unique players tracked: {len(player_stats):,}")

    # 3. Feature engineering ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 3 — Building feature dataset")
    print("=" * 60)
    features_list, targets = build_dataset(all_matches, player_stats)
    n = len(features_list)
    print(f"Usable training samples: {n:,}")
    if n == 0:
        print("ERROR: no usable samples — cannot train.")
        sys.exit(1)
    p1_wins = sum(targets)
    print(f"P1-win rate: {p1_wins / n:.1%}  (should be ~50 %)")

    # 4. Train ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 4 — Training logistic-regression model")
    print("=" * 60)
    model_data = train(features_list, targets)
    meta = model_data["metadata"]

    print(f"\n{'─' * 40}")
    print(f"  Accuracy : {meta['accuracy']:.1%}")
    print(f"  AUC      : {meta['auc']:.4f}")
    print(f"  Log-loss : {meta['log_loss']:.4f}")
    print(f"  Train    : {meta['training_samples']:,} samples")
    print(f"  Test     : {meta['test_samples']:,} samples")
    print(f"{'─' * 40}")
    print("\n  Top features by |coefficient|:")
    for f in meta["top_features"]:
        print(f"    {f['name']:30s}  {f['importance']:.4f}")

    # 5. Save ─────────────────────────────────────────────────────────────────
    save_model(model_data, args.output)
    print(f"\nDone!  Model → {args.output}")


if __name__ == "__main__":
    main()
