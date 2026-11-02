#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a shared packet trace for the cycle model and RTL testbench.

Each input has at most one new packet per cycle. Packet lengths are uniform in
[min_len, max_len]; destinations are uniform over outputs. `load` is the
target offered flit rate per input, so the per-cycle packet arrival probability
is load / mean_packet_len.
"""

from __future__ import annotations

import argparse
import json
import random
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="generate shared crossbar trace")
    parser.add_argument("--out", required=True)
    parser.add_argument("--csv-out", default=None)
    parser.add_argument("--inputs", type=int, default=2)
    parser.add_argument("--outputs", type=int, default=2)
    parser.add_argument("--load", type=float, default=0.9)
    parser.add_argument("--min-len", type=int, default=1)
    parser.add_argument("--max-len", type=int, default=8)
    parser.add_argument("--cycles", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    if args.inputs != 2 or args.outputs != 2:
        print("ERROR: this experiment currently fixes 2 inputs / 2 outputs", file=sys.stderr)
        return 2
    if not 0.0 <= args.load <= 4.0:
        print("ERROR: load must be in [0, 4]", file=sys.stderr)
        return 2
    if not 1 <= args.min_len <= args.max_len:
        print("ERROR: need 1 <= min-len <= max-len", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    mean_len = (args.min_len + args.max_len) / 2.0
    arrival_p = min(1.0, args.load / mean_len)
    seq = 0
    rows = []
    for src in range(args.inputs):
        for cycle in range(args.cycles):
            if rng.random() >= arrival_p:
                continue
            rows.append(
                {
                    "seq": seq,
                    "src": src,
                    "dst": rng.randrange(args.outputs),
                    "len": rng.randint(args.min_len, args.max_len),
                    "arrival": cycle,
                }
            )
            seq += 1
    rows.sort(key=lambda r: (r["arrival"], r["seq"]))
    with open(args.out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if args.csv_out:
        with open(args.csv_out, "w", encoding="utf-8") as f:
            f.write("seq,src,dst,len,arrival\n")
            for row in rows:
                f.write(
                    f"{row['seq']},{row['src']},{row['dst']},"
                    f"{row['len']},{row['arrival']}\n"
                )
    print(
        f"wrote {len(rows)} packets to {args.out} "
        f"(load={args.load}, pkt_len={args.min_len}-{args.max_len}, "
        f"arrival_p={arrival_p:.4f})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
