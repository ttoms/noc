#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Add a VC field to an Experiment 1 trace without changing packet timing.

The base trace from ``experiment/1-.../scripts/gen_trace.py`` contains
``seq/src/dst/len/arrival``.  E1 needs a ``vc`` field for the shared FIFO; the
VOQ baseline ignores it.  Deriving the VC from the base trace guarantees that
both architectures see identical packet arrivals, destinations, and lengths.

Modes:
  per_dst  vc = dst (requires vc_num >= number of destinations)
  multi    vc ~ Uniform(0, vc_num), independent of dst
"""

from __future__ import annotations

import argparse
import json
import random
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--vc-mode", choices=("per_dst", "multi"), required=True)
    ap.add_argument("--vc-num", type=int, required=True)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    if args.vc_num <= 0:
        print("ERROR: vc-num must be positive", file=sys.stderr)
        return 2

    rng = random.Random(args.seed * 1009 + args.vc_num)
    rows = []
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            dst = int(row["dst"])
            if args.vc_mode == "per_dst":
                if dst >= args.vc_num:
                    print(
                        f"ERROR: dst {dst} >= vc-num {args.vc_num}",
                        file=sys.stderr,
                    )
                    return 2
                vc = dst
            else:
                vc = rng.randrange(args.vc_num)
            row["vc"] = vc
            rows.append(row)

    with open(args.out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts = [0] * args.vc_num
    for row in rows:
        counts[row["vc"]] += 1
    print(
        f"wrote {len(rows)} packets to {args.out} "
        f"(vc_mode={args.vc_mode}, vc_num={args.vc_num}, counts={counts})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
