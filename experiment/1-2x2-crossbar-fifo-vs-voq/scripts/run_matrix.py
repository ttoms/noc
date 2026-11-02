#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2 driver: full-factorial capacity x queue-type experiment.

Matrix (default):
  queue type        fifo / voq
  capacity / queue  4 / 8 / 16 / 32 flits
  load              0.5 / 0.8 / 0.95 / 1.0
  packet length     fixed1 / fixed8 / uniform1-8 / bimodal1-8 (50/50)
  traffic           uniform / hotspot / bursty
  seeds             1 / 2 / 3

Every (type, capacity) is compiled once into its own binary; load, packet
length, traffic and seed reuse that binary.  Every run is compared exactly
against the Python cycle model: per delivered packet and per cycle debug row,
with no tolerance.

The core capacity curve (capacity x load x type, uniform1-8 + uniform
traffic) runs first, then the rest of the matrix.  Raw per-run records are
kept in results/phase2/raw_runs.json; the aggregate JSON/CSVs are produced by
analyze_phase2.py.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

from run_cosim import DEFAULT_CBB_RTL, compile_rtl, run_one
import analyze_phase2

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_WORKDIR = os.path.expanduser("~/Temp/phase2")
DEFAULT_OUTDIR = os.path.join(ROOT, "results", "phase2")

CORE_LENGTH = "uniform1-8"
CORE_TRAFFIC = "uniform"


def split_list(text):
    return [x.strip() for x in text.split(",") if x.strip()]


def trace_name(load, length_mode, traffic, seed):
    return f"l{load:g}_{length_mode}_{traffic}_s{seed}"


def trace_paths(workdir, load, length_mode, traffic, seed):
    base = trace_name(load, length_mode, traffic, seed)
    tdir = os.path.join(workdir, "traces")
    return (
        os.path.join(tdir, base + ".jsonl"),
        os.path.join(tdir, base + ".csv"),
    )


def ensure_trace(workdir, load, length_mode, traffic, seed, cycles, args):
    jsonl, csv_path = trace_paths(workdir, load, length_mode, traffic, seed)
    if os.path.exists(jsonl) and os.path.exists(csv_path):
        return jsonl, csv_path
    os.makedirs(os.path.dirname(jsonl), exist_ok=True)
    cmd = [
        sys.executable,
        os.path.join(HERE, "gen_trace.py"),
        "--out", jsonl,
        "--csv-out", csv_path,
        "--load", str(load),
        "--cycles", str(cycles),
        "--seed", str(seed),
        "--length-mode", length_mode,
        "--traffic", traffic,
        "--hotspot-dst", str(args.hotspot_dst),
        "--hotspot-prob", str(args.hotspot_prob),
        "--burst-on-mean", str(args.burst_on_mean),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"trace generation failed for {jsonl}")
    return jsonl, csv_path


def run_key(queue, capacity, load, length_mode, traffic, seed):
    return (
        f"{queue}_c{capacity}_l{load:g}_"
        f"{length_mode}_{traffic}_s{seed}"
    )


def record_path(workdir, key):
    return os.path.join(workdir, "run_records", key + ".json")


def load_record(workdir, key, cycles, warmup):
    path = record_path(workdir, key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if record.get("cycles") != cycles or record.get("warmup") != warmup:
        return None
    return record


def save_record(workdir, key, record):
    path = record_path(workdir, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)


def run_case(queue, capacity, load, length_mode, traffic, seed, args,
             binaries, workdir):
    key = run_key(queue, capacity, load, length_mode, traffic, seed)
    if not args.no_resume:
        cached = load_record(workdir, key, args.cycles, args.warmup)
        if cached is not None:
            return cached, True

    jsonl, csv_path = ensure_trace(
        workdir, load, length_mode, traffic, seed, args.cycles, args
    )
    outdir = os.path.join(workdir, "cosim", key)
    os.makedirs(outdir, exist_ok=True)
    binary = binaries[(queue, capacity)]
    result = run_one(
        jsonl,
        csv_path,
        args.cycles,
        outdir,
        binary,
        queue,
        capacity * (2 if queue == "fifo" else 4),
        args.warmup,
        False,
        args.cbb_rtl,
        True,
        queue,
        capacity,
    )
    model_json = os.path.join(
        outdir, os.path.splitext(os.path.basename(jsonl))[0] + ".model.json"
    )
    with open(model_json, encoding="utf-8") as f:
        metrics = json.load(f)

    record = {
        "queue": queue,
        "capacity": capacity,
        "load": load,
        "length_mode": length_mode,
        "traffic": traffic,
        "seed": seed,
        "cycles": args.cycles,
        "warmup": args.warmup,
        "exact": bool(result["match"]),
        "packet_errors": result["packet_errors"],
        "cycle_errors": result["cycle_errors"],
        "rtl_packets": result["rtl_packets"],
        "model_packets": result["model_packets"],
        "metrics": metrics,
    }
    save_record(workdir, key, record)

    if record["exact"]:
        shutil.rmtree(outdir, ignore_errors=True)
    else:
        failure_dir = os.path.join(workdir, "failures", key)
        os.makedirs(os.path.dirname(failure_dir), exist_ok=True)
        shutil.move(outdir, failure_dir)
    return record, False


def compile_binaries(args, queues, capacities, builddir):
    os.makedirs(builddir, exist_ok=True)
    binaries = {}
    for queue in queues:
        for capacity in capacities:
            binary = os.path.join(builddir, f"{queue}_c{capacity}")
            print(
                f"compile {queue} depth={capacity} -> {binary}",
                file=sys.stderr,
            )
            compile_rtl(binary, args.cbb_rtl, queue, capacity)
            binaries[(queue, capacity)] = binary
    return binaries


def iter_cases(args, queues, capacities, loads, lengths, traffics, core):
    for queue in queues:
        for capacity in capacities:
            for load in loads:
                for length_mode in lengths:
                    for traffic in traffics:
                        if core != (
                            length_mode == CORE_LENGTH and traffic == CORE_TRAFFIC
                        ):
                            continue
                        for seed in args.seed_list:
                            yield (
                                queue, capacity, load, length_mode, traffic, seed
                            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2 full-factorial matrix")
    parser.add_argument("--queues", default="fifo,voq")
    parser.add_argument("--capacities", default="4,8,16,32")
    parser.add_argument("--loads", default="0.5,0.8,0.95,1.0")
    parser.add_argument(
        "--length-modes",
        default="fixed1,fixed8,uniform1-8,bimodal1-8",
    )
    parser.add_argument("--traffics", default="uniform,hotspot,bursty")
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--cycles", type=int, default=4000)
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--hotspot-dst", type=int, default=0)
    parser.add_argument("--hotspot-prob", type=float, default=0.8)
    parser.add_argument("--burst-on-mean", type=float, default=8.0)
    parser.add_argument("--workdir", default=DEFAULT_WORKDIR)
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR)
    parser.add_argument("--cbb-rtl", default=DEFAULT_CBB_RTL)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--max-runs", type=int, default=0,
                        help="stop after N new runs (smoke testing)")
    parser.add_argument("--skip-core", action="store_true")
    args = parser.parse_args()

    queues = split_list(args.queues)
    capacities = [int(x) for x in split_list(args.capacities)]
    loads = [float(x) for x in split_list(args.loads)]
    lengths = split_list(args.length_modes)
    traffics = split_list(args.traffics)
    args.seed_list = [int(x) for x in split_list(args.seeds)]
    if args.cycles <= args.warmup:
        raise SystemExit("cycles must exceed warmup")

    config = {
        "queues": queues,
        "capacities": capacities,
        "loads": loads,
        "length_modes": lengths,
        "traffics": traffics,
        "seeds": args.seed_list,
        "cycles": args.cycles,
        "warmup": args.warmup,
        "hotspot_dst": args.hotspot_dst,
        "hotspot_prob": args.hotspot_prob,
        "burst_on_mean": args.burst_on_mean,
        "core_subset": {
            "length_mode": CORE_LENGTH,
            "traffic": CORE_TRAFFIC,
        },
        "traffic_definition": {
            "uniform": "Bernoulli arrivals, uniform destination",
            "hotspot": (
                f"{args.hotspot_prob:g} to dst {args.hotspot_dst}, "
                "rest uniform over other outputs"
            ),
            "bursty": (
                "ON/OFF line-rate arrivals, mean ON "
                f"{args.burst_on_mean:g} cycles, OFF calibrated to the same "
                "average offered load; uniform destination"
            ),
        },
    }

    os.makedirs(args.workdir, exist_ok=True)
    os.makedirs(args.outdir, exist_ok=True)
    builddir = os.path.join(ROOT, "build", "phase2")
    binaries = compile_binaries(args, queues, capacities, builddir)

    all_runs = []
    started = time.time()
    new_runs = 0

    def execute(cases, phase_name):
        nonlocal new_runs
        for queue, capacity, load, length_mode, traffic, seed in cases:
            if args.max_runs and new_runs >= args.max_runs:
                return False
            record, cached = run_case(
                queue, capacity, load, length_mode, traffic, seed,
                args, binaries, args.workdir,
            )
            all_runs.append(record)
            if not cached:
                new_runs += 1
            status = "MATCH" if record["exact"] else "MISMATCH"
            print(
                f"[{phase_name}] {status} {queue} c={capacity} load={load:g} "
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
        return True

    if not args.skip_core:
        core_cases = list(
            iter_cases(
                args, queues, capacities, loads, lengths, traffics, core=True
            )
        )
        print(
            f"core phase: {len(core_cases)} runs (capacity x load x type, "
            f"{CORE_LENGTH} + {CORE_TRAFFIC})",
            file=sys.stderr,
        )
        if execute(core_cases, "core"):
            core_summary = analyze_phase2.build_summary(
                [r for r in all_runs if r["length_mode"] == CORE_LENGTH
                 and r["traffic"] == CORE_TRAFFIC],
                config,
            )
            analyze_phase2.write_outputs(core_summary, args.outdir)
            print("\nCore capacity curve written.\n", file=sys.stderr)
            print(analyze_phase2.core_table(core_summary))
        elif args.max_runs:
            print("stopped by --max-runs during core phase", file=sys.stderr)
            return 0

    full_cases = list(
        iter_cases(
            args, queues, capacities, loads, lengths, traffics, core=False
        )
    )
    print(f"full-matrix remainder: {len(full_cases)} runs", file=sys.stderr)
    execute(full_cases, "full")

    # Deduplicate by key, preserving the latest record.
    unique = {}
    for record in all_runs:
        key = run_key(
            record["queue"], record["capacity"], record["load"],
            record["length_mode"], record["traffic"], record["seed"],
        )
        unique[key] = record
    runs = list(unique.values())
    runs.sort(
        key=lambda r: (
            r["queue"], r["capacity"], r["load"], r["length_mode"],
            r["traffic"], r["seed"],
        )
    )

    payload = {"config": config, "runs": runs}
    raw_path = os.path.join(args.outdir, "raw_runs.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    summary = analyze_phase2.build_summary(runs, config)
    analyze_phase2.write_outputs(summary, args.outdir)
    print("\n" + analyze_phase2.core_table(summary))
    print()
    print(json.dumps(summary["coverage"], ensure_ascii=False, indent=2))
    overall = summary["effects"]["overall"]
    print(
        "FIFO/VOQ effect over {strata} strata: voq_util_better={voq_util_better_strata} "
        "fifo_util_better={fifo_util_better_strata} tie={util_tie_strata} "
        "mean_delta_util={delta_utilization_mean:.4f}".format(**overall)
    )
    for row in summary["equal_buffer"]["by_pair"]:
        print(
            f"equal-buffer total={row['total_flits']}: "
            f"FIFO{row['fifo_capacity']} vs VOQ{row['voq_capacity']} "
            f"mean_delta_util={row['delta_utilization_mean']:.4f} "
            f"(voq better in {row['voq_util_better_strata']}/{row['strata']})"
        )
    print(f"wrote {raw_path}")
    return 0 if summary["coverage"]["mismatch_runs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
