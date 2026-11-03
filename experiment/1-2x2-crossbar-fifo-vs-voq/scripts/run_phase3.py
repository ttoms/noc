#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3 driver: XP per-crosspoint FIFO vs IQ-FIFO / IQ-VOQ.

Default core matrix:
  queue type        fifo / voq / xp
  capacity / queue  4 / 8 / 16 / 32 flits
  load              0.5 / 0.8 / 0.95 / 1.0
  packet length     uniform1-8
  traffic           uniform
  seeds             1 / 2 / 3

Every (type, capacity) is compiled once into its own binary.  Every run is
compared exactly against the Python cycle model: per delivered packet and per
cycle debug row, with no tolerance.  Raw per-cycle / per-packet CSVs stay in
the work directory and are not committed.

The XP-only datapath has four crosspoint FIFOs.  In this 2x2,
one-outstanding-packet configuration its observable queue semantics match the
current IQ-VOQ reference; the Phase 3 analyzer makes that equivalence explicit
instead of assuming it.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time

from run_matrix import (
    compile_binaries,
    ensure_trace,
    run_case,
    run_key,
    save_record,
    split_list,
)
import analyze_phase3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_WORKDIR = os.path.expanduser("~/Temp/phase3")
DEFAULT_OUTDIR = os.path.join(ROOT, "results", "phase3")

CORE_LENGTH = "uniform1-8"
CORE_TRAFFIC = "uniform"


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 3 core matrix: FIFO/VOQ/XP")
    parser.add_argument("--queues", default="fifo,voq,xp")
    parser.add_argument("--capacities", default="4,8,16,32")
    parser.add_argument("--loads", default="0.5,0.8,0.95,1.0")
    parser.add_argument("--length-modes", default=CORE_LENGTH)
    parser.add_argument("--traffics", default=CORE_TRAFFIC)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--cycles", type=int, default=4000)
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--hotspot-dst", type=int, default=0)
    parser.add_argument("--hotspot-prob", type=float, default=0.8)
    parser.add_argument("--burst-on-mean", type=float, default=8.0)
    parser.add_argument("--workdir", default=DEFAULT_WORKDIR)
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR)
    parser.add_argument("--cbb-rtl", default=os.path.join(ROOT, "vendor", "cbb", "rtl"))
    parser.add_argument("--source-gap", type=int, choices=[0, 1], default=0)
    parser.add_argument("--rdy-period", type=int, default=0)
    parser.add_argument("--rdy-high", type=int, default=0)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--max-runs", type=int, default=0,
                        help="stop after N new runs (smoke testing)")
    args = parser.parse_args()

    queues = split_list(args.queues)
    capacities = [int(x) for x in split_list(args.capacities)]
    loads = [float(x) for x in split_list(args.loads)]
    lengths = split_list(args.length_modes)
    traffics = split_list(args.traffics)
    args.seed_list = [int(x) for x in split_list(args.seeds)]
    if args.cycles <= args.warmup:
        raise SystemExit("cycles must exceed warmup")
    for queue in queues:
        if queue not in ("fifo", "voq", "xp"):
            raise SystemExit(f"unknown queue type: {queue}")

    config = {
        "queues": queues,
        "capacities": capacities,
        "loads": loads,
        "length_modes": lengths,
        "traffics": traffics,
        "seeds": args.seed_list,
        "cycles": args.cycles,
        "warmup": args.warmup,
        "source_gap": args.source_gap,
        "rdy_period": args.rdy_period,
        "rdy_high": args.rdy_high,
        "hotspot_dst": args.hotspot_dst,
        "hotspot_prob": args.hotspot_prob,
        "burst_on_mean": args.burst_on_mean,
        "core_subset": {"length_mode": CORE_LENGTH, "traffic": CORE_TRAFFIC},
    }

    os.makedirs(args.workdir, exist_ok=True)
    os.makedirs(args.outdir, exist_ok=True)
    builddir = os.path.join(ROOT, "build", "phase3")
    binaries = compile_binaries(args, queues, capacities, builddir)

    cases = list(
        itertools.product(
            queues, capacities, loads, lengths, traffics, args.seed_list
        )
    )
    all_runs = []
    started = time.time()
    new_runs = 0
    for queue, capacity, load, length_mode, traffic, seed in cases:
        if args.max_runs and new_runs >= args.max_runs:
            print("stopped by --max-runs", file=sys.stderr)
            break
        record, cached = run_case(
            queue, capacity, load, length_mode, traffic,
            seed, args, binaries, args.workdir,
        )
        all_runs.append(record)
        if not cached:
            new_runs += 1
        status = "MATCH" if record["exact"] else "MISMATCH"
        print(
            f"{status} {queue} c={capacity} load={load:g} "
            f"len={length_mode} traffic={traffic} seed={seed} "
            f"util={record['metrics']['utilization']:.4f} "
            f"lat={record['metrics']['avg_pkt_latency']:.2f} "
            f"({time.time() - started:.0f}s)",
            file=sys.stderr,
        )
        if not record["exact"]:
            print(
                f"  packet errors: {record['packet_errors'][:3]}",
                file=sys.stderr,
            )
            print(
                f"  cycle errors : {record['cycle_errors'][:3]}",
                file=sys.stderr,
            )

    unique = {}
    for record in all_runs:
        key = run_key(
            record["queue"], record["capacity"], record["load"],
            record["length_mode"], record["traffic"], record["seed"],
            record.get("source_gap", 0),
            record.get("rdy_period", 0),
            record.get("rdy_high", 0),
        )
        unique[key] = record
    runs = sorted(
        unique.values(),
        key=lambda r: (
            r["queue"], r["capacity"], r["load"], r["length_mode"],
            r["traffic"], r["seed"],
        ),
    )
    payload = {"config": config, "runs": runs}
    raw_path = os.path.join(args.outdir, "raw_runs.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    summary = analyze_phase3.build_summary(runs, config)
    analyze_phase3.write_outputs(summary, args.outdir)
    print()
    print(analyze_phase3.core_table(summary))
    print()
    print(json.dumps(summary["coverage"], ensure_ascii=False, indent=2))
    print()
    for row in summary["effects"]["overall"]:
        print(
            f"{row['pair']}: strata={row['strata']} "
            f"mean_delta_util={row['delta_utilization_mean']:+.4f} "
            f"right_better={row['right_util_better_strata']} "
            f"left_better={row['left_util_better_strata']} "
            f"ties={row['util_tie_strata']}"
        )
    print(f"wrote {raw_path}")
    return 0 if summary["coverage"]["mismatch_runs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
