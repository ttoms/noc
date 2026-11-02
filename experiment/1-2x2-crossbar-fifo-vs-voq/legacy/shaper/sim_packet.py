#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Packet-level 2x2 crossbar simulator.

New assumptions over sim.py:
  - packet length is random in [1, 8] flits
  - arbitration is packet-granular: once a packet wins an output, it occupies
    that output and its input for the whole packet (no flit interleaving)
  - input queues can be shared FIFO (HOL) or per-destination VOQ
  - optional token bucket in flits/cycle; a packet is admitted only if it can
    pay its full length

This model is for testing the claim:
  "without shaping, collisions waste bandwidth; with shaping, total delivered
   bandwidth can be higher."

Run the lossless controls first. In a work-conserving buffered crossbar with
sufficient buffers, shaping should not increase total delivered flits.
"""

from __future__ import annotations

import argparse
import csv
import json
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
    length: int
    birth: int
    seq: int


@dataclass
class Service:
    packet: Packet
    remaining: int


class InputQueue:
    def __init__(self, mode: str, depth: int | None):
        if mode not in ("fifo", "voq"):
            raise ValueError(mode)
        self.mode = mode
        self.depth = depth
        self.fifo: Deque[Packet] = deque()
        self.voqs: list[Deque[Packet]] = [deque(), deque()]
        self.flits = 0
        self.voq_flits = [0, 0]

    def can_enqueue(self, packet: Packet) -> bool:
        if self.depth is None:
            return True
        if self.mode == "fifo":
            return self.flits + packet.length <= self.depth
        return self.voq_flits[packet.dst] + packet.length <= self.depth

    def enqueue(self, packet: Packet) -> bool:
        if not self.can_enqueue(packet):
            return False
        if self.mode == "fifo":
            self.fifo.append(packet)
        else:
            self.voqs[packet.dst].append(packet)
            self.voq_flits[packet.dst] += packet.length
        self.flits += packet.length
        return True

    def has_for(self, dst: int) -> bool:
        if self.mode == "fifo":
            return bool(self.fifo) and self.fifo[0].dst == dst
        return bool(self.voqs[dst])

    def pop_for(self, dst: int) -> Packet | None:
        if self.mode == "fifo":
            if self.fifo and self.fifo[0].dst == dst:
                packet = self.fifo.popleft()
                self.flits -= packet.length
                return packet
            return None
        if self.voqs[dst]:
            packet = self.voqs[dst].popleft()
            self.voq_flits[dst] -= packet.length
            self.flits -= packet.length
            return packet
        return None


class TokenBucket:
    def __init__(self, rate: float, burst: float):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last = 0.0

    def allow(self, cost: int, now: int) -> bool:
        self.tokens = min(self.burst, self.tokens + self.rate * (now - self.last))
        self.last = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class CreditSource:
    """Offered flit load is approximately `load` per input per cycle.

    Packet length is sampled uniformly from [min_len, max_len] independently
    of the credit level. A long packet may wait for enough credit, but it is
    not biased toward short lengths.
    """

    def __init__(
        self,
        load: float,
        min_len: int,
        max_len: int,
        rng: random.Random,
    ):
        self.load = load
        self.min_len = min_len
        self.max_len = max_len
        self.rng = rng
        self.credit = 0.0
        self.pending: Packet | None = None

    def generate(self, src: int, cycle: int, pkt_id: int) -> Packet | None:
        self.credit += self.load
        if self.pending is None:
            self.pending = Packet(
                src=src,
                dst=self.rng.randrange(2),
                length=self.rng.randint(self.min_len, self.max_len),
                birth=cycle,
                seq=pkt_id,
            )
        if self.credit >= self.pending.length:
            self.credit -= self.pending.length
            packet = self.pending
            self.pending = None
            packet.birth = cycle
            return packet
        return None


@dataclass
class Stats:
    offered_flits: int = 0
    offered_pkts: int = 0
    accepted_flits: int = 0
    accepted_pkts: int = 0
    delivered_flits: int = 0
    delivered_pkts: int = 0
    shaper_drop_flits: int = 0
    shaper_drop_pkts: int = 0
    buffer_drop_flits: int = 0
    buffer_drop_pkts: int = 0
    latency_sum: int = 0
    latency_n: int = 0
    per_src_flits: list[int] = field(default_factory=lambda: [0, 0])
    per_dst_flits: list[int] = field(default_factory=lambda: [0, 0])

    def reset(self) -> None:
        self.__dict__.update(Stats().__dict__)


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
        self.services: list[Service] = []
        self.out_rr = [0, 0]
        self.arb_phase = 0
        self.stats = Stats()
        self.pkt_id = 0
        self.sources = [
            CreditSource(0.0, 1, 8, random.Random(0)) for _ in range(2)
        ]  # replaced in run_once

    def step(self, sources: list[CreditSource], cycle: int) -> None:
        # 1) offer -> shaper -> input queue
        for src in range(2):
            packet = sources[src].generate(src, cycle, self.pkt_id)
            if packet is None:
                continue
            self.pkt_id += 1
            self.stats.offered_flits += packet.length
            self.stats.offered_pkts += 1
            if self.buckets is not None and not self.buckets[src].allow(
                packet.length, cycle
            ):
                self.stats.shaper_drop_flits += packet.length
                self.stats.shaper_drop_pkts += 1
                continue
            if self.queues[src].enqueue(packet):
                self.stats.accepted_flits += packet.length
                self.stats.accepted_pkts += 1
            else:
                self.stats.buffer_drop_flits += packet.length
                self.stats.buffer_drop_pkts += 1

        # 2) advance in-flight packets; a packet completes after its last flit
        finished: list[Service] = []
        for service in self.services:
            service.remaining -= 1
            if service.remaining <= 0:
                finished.append(service)
        for service in finished:
            self.services.remove(service)
            pkt = service.packet
            self.stats.delivered_flits += pkt.length
            self.stats.delivered_pkts += 1
            self.stats.per_src_flits[pkt.src] += pkt.length
            self.stats.per_dst_flits[pkt.dst] += pkt.length
            self.stats.latency_sum += cycle - pkt.birth
            self.stats.latency_n += 1

        # 3) packet-granular arbitration: start at most one packet per input and
        # one per output; the winner holds both for the entire packet.
        busy_inputs = {s.packet.src for s in self.services}
        busy_outputs = {s.packet.dst for s in self.services}
        output_order = [self.arb_phase, 1 - self.arb_phase]
        for out in output_order:
            if out in busy_outputs:
                continue
            for offset in range(2):
                src = (self.out_rr[out] + offset) % 2
                if src in busy_inputs:
                    continue
                packet = self.queues[src].pop_for(out)
                if packet is None:
                    continue
                self.services.append(Service(packet=packet, remaining=packet.length))
                busy_inputs.add(src)
                busy_outputs.add(out)
                self.out_rr[out] = (src + 1) % 2
                break
        self.arb_phase ^= 1


def jain(values: list[int]) -> float:
    total = sum(values)
    if total == 0:
        return 0.0
    return (total * total) / (len(values) * sum(v * v for v in values))


def summarize(stats: Stats, cycles: int) -> dict[str, float]:
    drops_flits = stats.shaper_drop_flits + stats.buffer_drop_flits
    drops_pkts = stats.shaper_drop_pkts + stats.buffer_drop_pkts
    delivered_tp = stats.delivered_flits / cycles
    return {
        "offered_tp": stats.offered_flits / cycles,
        "accepted_tp": stats.accepted_flits / cycles,
        "delivered_tp": delivered_tp,
        "utilization": delivered_tp / 2.0,
        "drop_rate_flits": drops_flits / stats.offered_flits if stats.offered_flits else 0.0,
        "drop_rate_pkts": drops_pkts / stats.offered_pkts if stats.offered_pkts else 0.0,
        "shaper_drop_flits": float(stats.shaper_drop_flits),
        "buffer_drop_flits": float(stats.buffer_drop_flits),
        "avg_pkt_latency": (
            stats.latency_sum / stats.latency_n if stats.latency_n else 0.0
        ),
        "pkt_rate": stats.delivered_pkts / cycles,
        "avg_pkt_len": (
            stats.delivered_flits / stats.delivered_pkts
            if stats.delivered_pkts
            else 0.0
        ),
        "jain_flits": jain(stats.per_src_flits),
        "per_src_0_tp": stats.per_src_flits[0] / cycles,
        "per_src_1_tp": stats.per_src_flits[1] / cycles,
        "per_dst_0_tp": stats.per_dst_flits[0] / cycles,
        "per_dst_1_tp": stats.per_dst_flits[1] / cycles,
    }


def run_once(
    *,
    mode: str,
    depth: int | None,
    shaper_rate: float | None,
    shaper_burst: float,
    load: float,
    min_len: int,
    max_len: int,
    cycles: int,
    warmup: int,
    seed: int,
) -> dict[str, float | int | str | None]:
    rng = random.Random(seed)
    sources = [
        CreditSource(load, min_len, max_len, rng) for _ in range(2)
    ]
    crossbar = Crossbar(mode, depth, shaper_rate, shaper_burst)
    measured = cycles - warmup
    if measured <= 0:
        raise ValueError("cycles must be greater than warmup")
    for cycle in range(cycles):
        if cycle == warmup:
            crossbar.stats.reset()
        crossbar.step(sources, cycle)
    result = summarize(crossbar.stats, measured)
    result.update(
        {
            "mode": mode,
            "depth": depth,
            "shaper_rate": shaper_rate,
            "shaper_burst": shaper_burst,
            "load": load,
            "min_len": min_len,
            "max_len": max_len,
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
        "drop_rate_flits",
        "drop_rate_pkts",
        "avg_pkt_latency",
        "pkt_rate",
        "avg_pkt_len",
        "jain_flits",
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
    parser = argparse.ArgumentParser(description="packet-level 2x2 crossbar simulator")
    parser.add_argument("--mode", choices=["voq", "fifo"], default="fifo")
    parser.add_argument("--depth", type=int, default=0, help="flits per queue; 0=infinite")
    parser.add_argument("--shaper-rate", type=float, default=0.0, help="flits/cycle; 0=off")
    parser.add_argument("--shaper-burst", type=float, default=16.0)
    parser.add_argument("--load", type=float, default=1.0, help="offered flits/cycle per input")
    parser.add_argument("--min-len", type=int, default=1)
    parser.add_argument("--max-len", type=int, default=8)
    parser.add_argument("--cycles", type=int, default=50_000)
    parser.add_argument("--warmup", type=int, default=5_000)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--csv", default=None)
    args = parser.parse_args()

    if not 0.0 <= args.load <= 1.0:
        print("ERROR: --load must be in [0, 1]", file=sys.stderr)
        return 2
    if not 0.0 <= args.shaper_rate <= 1.0:
        print("ERROR: --shaper-rate must be in [0, 1]", file=sys.stderr)
        return 2
    if not 1 <= args.min_len <= args.max_len:
        print("ERROR: need 1 <= min-len <= max-len", file=sys.stderr)
        return 2
    if args.cycles <= args.warmup:
        print("ERROR: cycles must exceed warmup", file=sys.stderr)
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
                min_len=args.min_len,
                max_len=args.max_len,
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
            "min_len": args.min_len,
            "max_len": args.max_len,
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
        f"burst={args.shaper_burst:g} load={args.load} "
        f"pkt={args.min_len}-{args.max_len} cycles={args.cycles - args.warmup} "
        f"seeds={args.seeds}"
    )
    for key in (
        "offered_tp",
        "accepted_tp",
        "delivered_tp",
        "utilization",
        "drop_rate_flits",
        "drop_rate_pkts",
        "avg_pkt_latency",
        "pkt_rate",
        "avg_pkt_len",
        "jain_flits",
        "per_src_0_tp",
        "per_src_1_tp",
        "per_dst_0_tp",
        "per_dst_1_tp",
    ):
        print(f"{key:18s} {agg[key]['mean']:.4f} ± {agg[key]['stdev']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
