#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2x2 crossbar + optional flow shaper, cycle-level simulator.

This is the control-group skeleton for the "shaping can improve delivered
throughput under congestion collapse" experiment. It is intentionally small:

  - 2 inputs, 2 outputs, 1 packet/input/cycle, 1 packet/output/cycle
  - input queues: shared FIFO (HOL blocking) or per-destination VOQ
  - optional token bucket per input
  - uniform Bernoulli traffic or synchronized on/off bursts
  - finite or infinite input buffers, drop on overflow

Important: with a lossless work-conserving baseline, shaping cannot increase
total delivered throughput. The interesting regime needs drops/retries or
HOL-induced output idling. Run the lossless control first.

Usage:
  python3 sim.py --mode voq --load 0.95 --cycles 20000 --seeds 5
  python3 sim.py --mode fifo --depth 8 --shaper-rate 0.8 --load 1.0
  python3 sim.py --mode fifo --depth 8 --traffic bursty --on 16 --off 16
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


@dataclass
class Packet:
    src: int
    dst: int
    birth: int
    seq: int


class InputQueue:
    """Shared FIFO (one head for both outputs) or per-output VOQ."""

    def __init__(self, mode: str, depth: int | None):
        if mode not in ("fifo", "voq"):
            raise ValueError(f"unknown queue mode: {mode}")
        self.mode = mode
        self.depth = depth
        self.fifo: Deque[Packet] = deque()
        self.voqs: list[Deque[Packet]] = [deque(), deque()]

    def __len__(self) -> int:
        if self.mode == "fifo":
            return len(self.fifo)
        return len(self.voqs[0]) + len(self.voqs[1])

    def enqueue(self, packet: Packet) -> bool:
        if self.mode == "fifo":
            if self.depth is not None and len(self.fifo) >= self.depth:
                return False
            self.fifo.append(packet)
            return True
        q = self.voqs[packet.dst]
        if self.depth is not None and len(q) >= self.depth:
            return False
        q.append(packet)
        return True

    def has_for(self, dst: int) -> bool:
        if self.mode == "fifo":
            return bool(self.fifo) and self.fifo[0].dst == dst
        return bool(self.voqs[dst])

    def pop_for(self, dst: int) -> Packet | None:
        if self.mode == "fifo":
            if self.fifo and self.fifo[0].dst == dst:
                return self.fifo.popleft()
            return None
        if self.voqs[dst]:
            return self.voqs[dst].popleft()
        return None


class TokenBucket:
    """One packet costs one token; tokens refill continuously per cycle."""

    def __init__(self, rate: float, burst: float):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last = 0.0

    def allow(self, now: int) -> bool:
        self.tokens = min(self.burst, self.tokens + self.rate * (now - self.last))
        self.last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class UniformTraffic:
    def __init__(self, load: float, rng: random.Random):
        self.load = load
        self.rng = rng

    def generate(self, src: int, cycle: int) -> int | None:
        if self.rng.random() < self.load:
            return self.rng.randrange(2)
        return None


class BurstyTraffic:
    """Synchronized on/off bursts; both inputs use the same phase and dest."""

    def __init__(
        self,
        on: int,
        off: int,
        dest_mode: str,
        rng: random.Random,
    ):
        self.on = max(1, on)
        self.off = max(1, off)
        self.dest_mode = dest_mode
        self.rng = rng
        self.phase_on = True
        self.left = self.on
        self.dst = 0

    def _next_dest(self) -> int:
        if self.dest_mode == "fixed0":
            return 0
        if self.dest_mode == "fixed1":
            return 1
        if self.dest_mode == "random":
            return self.rng.randrange(2)
        # alternate: flip every on-burst
        return 1 - self.dst

    def generate(self, src: int, cycle: int) -> int | None:
        if self.left <= 0:
            self.phase_on = not self.phase_on
            self.left = self.on if self.phase_on else self.off
            if self.phase_on:
                self.dst = self._next_dest()
        self.left -= 1
        return self.dst if self.phase_on else None


@dataclass
class Stats:
    offered: int = 0
    accepted: int = 0
    delivered: int = 0
    shaper_drop: int = 0
    buffer_drop: int = 0
    latency_sum: int = 0
    latency_n: int = 0
    per_src: list[int] = field(default_factory=lambda: [0, 0])
    per_dst: list[int] = field(default_factory=lambda: [0, 0])

    def reset(self) -> None:
        self.offered = 0
        self.accepted = 0
        self.delivered = 0
        self.shaper_drop = 0
        self.buffer_drop = 0
        self.latency_sum = 0
        self.latency_n = 0
        self.per_src = [0, 0]
        self.per_dst = [0, 0]


class Crossbar:
    def __init__(
        self,
        mode: str,
        depth: int | None,
        shaper_rate: float | None,
        shaper_burst: float,
    ):
        self.queues = [InputQueue(mode, depth) for _ in range(2)]
        self.buckets = (
            [TokenBucket(shaper_rate, shaper_burst) for _ in range(2)]
            if shaper_rate is not None
            else None
        )
        self.out_rr = [0, 0]
        self.arb_phase = 0
        self.stats = Stats()
        self.seq = 0

    def step(self, traffic, cycle: int) -> None:
        # 1) offered -> shaper -> queue
        for src in range(2):
            dst = traffic.generate(src, cycle)
            if dst is None:
                continue
            self.stats.offered += 1
            if self.buckets is not None and not self.buckets[src].allow(cycle):
                self.stats.shaper_drop += 1
                continue
            packet = Packet(src=src, dst=dst, birth=cycle, seq=self.seq)
            self.seq += 1
            if self.queues[src].enqueue(packet):
                self.stats.accepted += 1
            else:
                self.stats.buffer_drop += 1

        # 2) one cycle of output arbitration; each input can serve one output
        used_inputs: set[int] = set()
        output_order = [self.arb_phase, 1 - self.arb_phase]
        for out in output_order:
            granted = None
            for offset in range(2):
                src = (self.out_rr[out] + offset) % 2
                if src in used_inputs or not self.queues[src].has_for(out):
                    continue
                packet = self.queues[src].pop_for(out)
                if packet is None:
                    continue
                granted = src
                used_inputs.add(src)
                self.stats.delivered += 1
                self.stats.per_src[src] += 1
                self.stats.per_dst[out] += 1
                self.stats.latency_sum += cycle - packet.birth
                self.stats.latency_n += 1
                break
            if granted is not None:
                self.out_rr[out] = (granted + 1) % 2
        self.arb_phase ^= 1


def jain(values: list[int]) -> float:
    total = sum(values)
    if total == 0:
        return 0.0
    return (total * total) / (len(values) * sum(v * v for v in values))


def summarize(stats: Stats, cycles: int) -> dict[str, float]:
    if cycles <= 0:
        raise ValueError("cycles must be positive")
    offered_tp = stats.offered / cycles
    accepted_tp = stats.accepted / cycles
    delivered_tp = stats.delivered / cycles
    drops = stats.shaper_drop + stats.buffer_drop
    return {
        "offered_tp": offered_tp,
        "accepted_tp": accepted_tp,
        "delivered_tp": delivered_tp,
        "utilization": delivered_tp / 2.0,
        "drop_rate": drops / stats.offered if stats.offered else 0.0,
        "shaper_drop": float(stats.shaper_drop),
        "buffer_drop": float(stats.buffer_drop),
        "avg_latency": (
            stats.latency_sum / stats.latency_n if stats.latency_n else 0.0
        ),
        "jain": jain(stats.per_src),
        "per_src_0_tp": stats.per_src[0] / cycles,
        "per_src_1_tp": stats.per_src[1] / cycles,
        "per_dst_0_tp": stats.per_dst[0] / cycles,
        "per_dst_1_tp": stats.per_dst[1] / cycles,
    }


def run_once(
    *,
    mode: str,
    depth: int | None,
    shaper_rate: float | None,
    shaper_burst: float,
    load: float,
    traffic_name: str,
    on: int,
    off: int,
    dest_mode: str,
    cycles: int,
    warmup: int,
    seed: int,
) -> dict[str, float | int | str | None]:
    rng = random.Random(seed)
    if traffic_name == "uniform":
        traffic = UniformTraffic(load, rng)
    elif traffic_name == "bursty":
        traffic = BurstyTraffic(on, off, dest_mode, rng)
    else:
        raise ValueError(f"unknown traffic: {traffic_name}")

    crossbar = Crossbar(mode, depth, shaper_rate, shaper_burst)
    measured = cycles - warmup
    if measured <= 0:
        raise ValueError("cycles must be greater than warmup")

    for cycle in range(cycles):
        if cycle == warmup:
            crossbar.stats.reset()
        crossbar.step(traffic, cycle)

    result = summarize(crossbar.stats, measured)
    result.update(
        {
            "mode": mode,
            "depth": depth,
            "shaper_rate": shaper_rate,
            "shaper_burst": shaper_burst,
            "load": load,
            "traffic": traffic_name,
            "on": on,
            "off": off,
            "dest_mode": dest_mode,
            "cycles": measured,
            "warmup": warmup,
            "seed": seed,
        }
    )
    return result


def aggregate(runs: list[dict]) -> dict[str, dict[str, float]]:
    keys = [
        "offered_tp",
        "accepted_tp",
        "delivered_tp",
        "utilization",
        "drop_rate",
        "avg_latency",
        "jain",
        "per_src_0_tp",
        "per_src_1_tp",
        "per_dst_0_tp",
        "per_dst_1_tp",
    ]
    out = {}
    for key in keys:
        values = [float(r[key]) for r in runs]
        out[key] = {
            "mean": statistics.fmean(values),
            "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="2x2 crossbar shaping simulator")
    parser.add_argument("--mode", choices=["voq", "fifo"], default="voq")
    parser.add_argument(
        "--depth", type=int, default=0, help="per-queue buffer depth; 0=infinite"
    )
    parser.add_argument(
        "--shaper-rate",
        type=float,
        default=0.0,
        help="token bucket rate; 0=disabled; max 1.0",
    )
    parser.add_argument("--shaper-burst", type=float, default=1_000_000.0)
    parser.add_argument("--load", type=float, default=0.95)
    parser.add_argument("--traffic", choices=["uniform", "bursty"], default="uniform")
    parser.add_argument("--on", type=int, default=16)
    parser.add_argument("--off", type=int, default=16)
    parser.add_argument(
        "--dest-mode",
        choices=["fixed0", "fixed1", "alternate", "random"],
        default="fixed0",
    )
    parser.add_argument("--cycles", type=int, default=20_000)
    parser.add_argument("--warmup", type=int, default=2_000)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--csv", default=None)
    args = parser.parse_args()

    if not 0.0 <= args.load <= 1.0:
        print("ERROR: --load must be in [0, 1]", file=sys.stderr)
        return 2
    if args.shaper_rate < 0.0 or args.shaper_rate > 1.0:
        print("ERROR: --shaper-rate must be in [0, 1]", file=sys.stderr)
        return 2
    if args.cycles <= args.warmup:
        print("ERROR: --cycles must be greater than --warmup", file=sys.stderr)
        return 2

    depth = None if args.depth <= 0 else args.depth
    shaper_rate = None if args.shaper_rate <= 0.0 else args.shaper_rate

    runs = []
    for seed in range(args.seed_start, args.seed_start + args.seeds):
        runs.append(
            run_once(
                mode=args.mode,
                depth=depth,
                shaper_rate=shaper_rate,
                shaper_burst=args.shaper_burst,
                load=args.load,
                traffic_name=args.traffic,
                on=args.on,
                off=args.off,
                dest_mode=args.dest_mode,
                cycles=args.cycles,
                warmup=args.warmup,
                seed=seed,
            )
        )

    agg = aggregate(runs)
    payload = {
        "config": {
            "mode": args.mode,
            "depth": depth,
            "shaper_rate": shaper_rate,
            "shaper_burst": args.shaper_burst,
            "load": args.load,
            "traffic": args.traffic,
            "on": args.on,
            "off": args.off,
            "dest_mode": args.dest_mode,
            "cycles": args.cycles - args.warmup,
            "warmup": args.warmup,
            "seeds": args.seeds,
        },
        "runs": runs,
        "aggregate": agg,
    }

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(runs[0].keys()))
            writer.writeheader()
            writer.writerows(runs)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(
        f"mode={args.mode} depth={depth} shaper={shaper_rate or 'off'} "
        f"burst={args.shaper_burst:g} load={args.load} traffic={args.traffic} "
        f"cycles={args.cycles - args.warmup} seeds={args.seeds}"
    )
    for key in (
        "offered_tp",
        "accepted_tp",
        "delivered_tp",
        "utilization",
        "drop_rate",
        "avg_latency",
        "jain",
        "per_src_0_tp",
        "per_src_1_tp",
        "per_dst_0_tp",
        "per_dst_1_tp",
    ):
        mean = agg[key]["mean"]
        stdev = agg[key]["stdev"]
        print(f"{key:16s} {mean:.4f} ± {stdev:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
