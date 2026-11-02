#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a shared packet trace for the cycle model and RTL testbench.

Each input has at most one new packet per cycle.  The offered `load` is the
target flit rate per input, so the per-cycle packet arrival probability is
load / mean_packet_len.

Phase 2 adds two orthogonal trace dimensions:

  --length-mode fixed1 | fixed8 | uniform1-8 | bimodal1-8
      fixed1/fixed8: constant packet length
      uniform1-8:    uniform integer length in [min_len, max_len]
      bimodal1-8:    50/50 choice of length 1 and length 8

  --traffic uniform | hotspot | bursty
      uniform: Bernoulli arrivals, destination uniform over outputs
      hotspot: Bernoulli arrivals, `hotspot_prob` of packets target
               `hotspot_dst`, the rest choose uniformly among the others
      bursty:  ON/OFF arrival process (line-rate bursts separated by idle
               gaps, calibrated to the same average offered load) with
               uniform destinations

The trace format is unchanged; the model and the RTL testbench read exactly
the same JSONL/CSV.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys


LENGTH_MODES = ("fixed1", "fixed8", "uniform1-8", "bimodal1-8")
TRAFFICS = ("uniform", "hotspot", "bursty")


def mean_length(mode: str, min_len: int, max_len: int) -> float:
    if mode == "fixed1":
        return 1.0
    if mode == "fixed8":
        return 8.0
    if mode == "uniform1-8":
        return (min_len + max_len) / 2.0
    if mode == "bimodal1-8":
        return 4.5
    raise ValueError(mode)


def draw_length(rng: random.Random, mode: str, min_len: int, max_len: int) -> int:
    if mode == "fixed1":
        return 1
    if mode == "fixed8":
        return 8
    if mode == "uniform1-8":
        return rng.randint(min_len, max_len)
    if mode == "bimodal1-8":
        return 1 if rng.random() < 0.5 else 8
    raise ValueError(mode)


def draw_dst(rng: random.Random, traffic: str, outputs: int,
             hotspot_dst: int, hotspot_prob: float) -> int:
    if traffic == "hotspot":
        if rng.random() < hotspot_prob:
            return hotspot_dst
        if outputs <= 1:
            return 0
        # Uniform over the non-hotspot outputs.
        other = rng.randrange(outputs - 1)
        return other if other < hotspot_dst else other + 1
    return rng.randrange(outputs)


class BurstArrival:
    """ON/OFF arrival process with a target long-run ON fraction.

    During ON a packet is offered every cycle.  Durations are exponential
    rounded to the nearest integer; OFF durations may round to zero when the
    required idle fraction is tiny.  Taking mean_off = mean_on * (1-p) / p
    makes the stationary ON fraction p, hence the long-run packet arrival
    rate equals the Bernoulli rate p.
    """

    def __init__(self, rng: random.Random, target_p: float, mean_on: float):
        self.rng = rng
        self.p = min(1.0, max(0.0, target_p))
        self.mean_on = max(1.0, mean_on)
        if self.p <= 0.0:
            self.mean_off = float("inf")
        elif self.p >= 1.0:
            self.mean_off = 0.0
        else:
            self.mean_off = self.mean_on * (1.0 - self.p) / self.p
        self.on = True
        self.remaining = self._duration(self.mean_on, allow_zero=False)

    def _duration(self, mean: float, allow_zero: bool) -> int:
        if math.isinf(mean):
            return 10**9
        if mean <= 0:
            return 0 if allow_zero else 1
        n = int(self.rng.expovariate(1.0 / mean) + 0.5)
        return max(0, n) if allow_zero else max(1, n)

    def _advance(self) -> None:
        # Zero-length OFF intervals are allowed, so loop until a non-empty
        # state is reached.  ON is always at least one cycle.
        while self.remaining <= 0:
            self.on = not self.on
            mean = self.mean_on if self.on else self.mean_off
            self.remaining = self._duration(mean, allow_zero=not self.on)

    def step(self) -> bool:
        if self.p >= 1.0:
            return True
        if self.p <= 0.0:
            return False
        self._advance()
        emitted = self.on
        self.remaining -= 1
        return emitted


def main() -> int:
    parser = argparse.ArgumentParser(description="generate shared crossbar trace")
    parser.add_argument("--out", required=True)
    parser.add_argument("--csv-out", default=None)
    parser.add_argument("--inputs", type=int, default=2)
    parser.add_argument("--outputs", type=int, default=2)
    parser.add_argument("--load", type=float, default=0.9)
    parser.add_argument("--min-len", type=int, default=1)
    parser.add_argument("--max-len", type=int, default=8)
    parser.add_argument("--length-mode", choices=LENGTH_MODES, default=None,
                        help="default: uniform1-8 (uses --min-len/--max-len)")
    parser.add_argument("--traffic", choices=TRAFFICS, default="uniform")
    parser.add_argument("--hotspot-dst", type=int, default=0)
    parser.add_argument("--hotspot-prob", type=float, default=0.8)
    parser.add_argument("--burst-on-mean", type=float, default=8.0,
                        help="mean ON duration in cycles for --traffic bursty")
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
    if not 0 <= args.hotspot_dst < args.outputs:
        print("ERROR: hotspot-dst must be a valid output", file=sys.stderr)
        return 2
    if not 0.0 <= args.hotspot_prob <= 1.0:
        print("ERROR: hotspot-prob must be in [0, 1]", file=sys.stderr)
        return 2

    length_mode = args.length_mode or "uniform1-8"
    rng = random.Random(args.seed)
    mean_len = mean_length(length_mode, args.min_len, args.max_len)
    target_p = min(1.0, args.load / mean_len)

    if args.traffic == "bursty":
        arrivals = [
            BurstArrival(rng, target_p, args.burst_on_mean)
            for _ in range(args.inputs)
        ]
    else:
        arrivals = [None] * args.inputs

    seq = 0
    rows = []
    for src in range(args.inputs):
        for cycle in range(args.cycles):
            if args.traffic == "bursty":
                emit = arrivals[src].step()
            else:
                emit = rng.random() < target_p
            if not emit:
                continue
            rows.append(
                {
                    "seq": seq,
                    "src": src,
                    "dst": draw_dst(
                        rng, args.traffic, args.outputs,
                        args.hotspot_dst, args.hotspot_prob,
                    ),
                    "len": draw_length(rng, length_mode, args.min_len, args.max_len),
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
        f"(load={args.load}, len_mode={length_mode}, traffic={args.traffic}, "
        f"mean_len={mean_len:g}, arrival_p={target_p:.4f})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
