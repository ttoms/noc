#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compute paired 95% confidence intervals from a raw_runs.json file.

Usage:
  ci_from_raw.py raw_runs.json --pair fifo:voq --by capacity load
  ci_from_raw.py raw_runs.json --pair fifo:voq --by capacity --equal-buffer

The input records are produced by run_matrix.py / run_phase3.py.  Only runs
with the same key dimensions except the queue type are paired.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict


def tcrit(n: int) -> float:
    # 95% two-sided t critical values for small samples; normal beyond 30.
    table = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571,
             7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262}
    return table.get(n, 1.96)


def mean_ci(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], 0.0
    return statistics.mean(values), tcrit(len(values)) * statistics.stdev(values) / math.sqrt(len(values))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", help="raw_runs.json")
    ap.add_argument("--pair", default="fifo:voq", help="left:right queue types")
    ap.add_argument("--by", nargs="+", default=["capacity", "load"])
    ap.add_argument("--equal-buffer", action="store_true",
                    help="pair fifo capacity C with right capacity C/2")
    args = ap.parse_args()
    left_q, right_q = args.pair.split(":")
    payload = json.load(open(args.raw, encoding="utf-8"))
    runs = payload["runs"] if isinstance(payload, dict) else payload

    # Key = all dimensions except queue type; optionally capacity pairing.
    def key(r):
        k = tuple(r[d] for d in args.by)
        return k

    by_key = defaultdict(dict)
    for r in runs:
        q = r["queue"]
        if q not in (left_q, right_q):
            continue
        k = key(r)
        if args.equal_buffer and q == right_q:
            # The right side is paired to the fifo capacity / 2.
            continue
        by_key[k].setdefault(q, []).append(r)

    # Equal-buffer: explicitly match fifo C to right C/2.
    pairs = []
    if args.equal_buffer:
        right = [r for r in runs if r["queue"] == right_q]
        left = [r for r in runs if r["queue"] == left_q]
        for l in left:
            lc = l["capacity"]
            for r in right:
                if r["capacity"] * 2 != lc:
                    continue
                if all(l[d] == r[d] for d in args.by if d != "capacity") and \
                        l["seed"] == r["seed"] and \
                        l["length_mode"] == r["length_mode"] and \
                        l["traffic"] == r["traffic"]:
                    pairs.append((l, r))
    else:
        for k, sides in by_key.items():
            if left_q not in sides or right_q not in sides:
                continue
            # Pair by remaining dimensions + seed.
            for l in sides[left_q]:
                for r in sides[right_q]:
                    if l["seed"] != r["seed"]:
                        continue
                    if l["length_mode"] != r["length_mode"] or l["traffic"] != r["traffic"]:
                        continue
                    if l["capacity"] != r["capacity"]:
                        continue
                    pairs.append((l, r))

    groups = defaultdict(list)
    for l, r in pairs:
        g = tuple(l[d] for d in args.by)
        groups[g].append(r["metrics"]["utilization"] - l["metrics"]["utilization"])

    for g, ds in sorted(groups.items(), key=lambda x: str(x[0])):
        m, ci = mean_ci(ds)
        print(f"{g}: n={len(ds)} mean={m:+.4f} ci95=±{ci:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
