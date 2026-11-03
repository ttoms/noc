#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FIFO load sweep: generate traces, co-simulate model + RTL, exact compare.

Every (load, seed) run is compared packet-by-packet and cycle-by-cycle.  The
markdown table reports mean model metrics over seeds; the `exact` column is
only yes when every seed matches with no tolerance.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import subprocess
import sys

from run_cosim import DEFAULT_CBB_RTL, compile_rtl, run_one

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def percentile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return float(ordered[idx])


def p99_latency(model_csv: str, warmup: int) -> float:
    latencies: list[int] = []
    with open(model_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            end = int(row["end"])
            if end >= warmup:
                latencies.append(end - int(row["arrival"]))
    return percentile(latencies, 0.99)


def main() -> int:
    parser = argparse.ArgumentParser(description="FIFO load sweep with exact co-sim")
    parser.add_argument("--loads", default="0.5,0.8,0.95,1.0")
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--cycles", type=int, default=4000)
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--mode", choices=["fifo", "voq"], default="fifo")
    parser.add_argument("--dut", choices=["fifo", "voq"], default="fifo")
    parser.add_argument("--total-buffer", type=int, default=64)
    parser.add_argument("--outdir", default=os.path.join(ROOT, "out", "sweep"))
    parser.add_argument("--binary", default=os.path.join(ROOT, "build", "xbar_fifo_tb"))
    parser.add_argument("--cbb-rtl", default=DEFAULT_CBB_RTL)
    parser.add_argument("--source-gap", type=int, choices=[0, 1], default=0)
    parser.add_argument("--rdy-period", type=int, default=0)
    parser.add_argument("--rdy-high", type=int, default=0)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--markdown-out", default=None)
    args = parser.parse_args()

    loads = [float(x) for x in args.loads.split(",") if x]
    seeds = [int(x) for x in args.seeds.split(",") if x]
    os.makedirs(args.outdir, exist_ok=True)
    compile_rtl(args.binary, args.cbb_rtl, args.dut)

    runs: list[dict] = []
    for load in loads:
        for seed in seeds:
            base = f"{args.mode}_l{load:g}_s{seed}"
            jsonl = os.path.join(args.outdir, base + ".jsonl")
            csv_path = os.path.join(args.outdir, base + ".csv")
            trace_cmd = [
                sys.executable,
                os.path.join(HERE, "gen_trace.py"),
                "--out",
                jsonl,
                "--csv-out",
                csv_path,
                "--load",
                str(load),
                "--cycles",
                str(args.cycles),
                "--seed",
                str(seed),
            ]
            subprocess.run(trace_cmd, check=True, capture_output=True, text=True)
            result = run_one(
                jsonl,
                csv_path,
                args.cycles,
                os.path.join(args.outdir, "cosim"),
                args.binary,
                args.mode,
                args.total_buffer,
                args.warmup,
                False,
                args.cbb_rtl,
                True,
                args.dut,
                None,
                args.source_gap,
                args.rdy_period,
                args.rdy_high,
            )
            model_csv = os.path.join(
                args.outdir, "cosim", base + ".model_packets.csv"
            )
            with open(
                os.path.join(args.outdir, "cosim", base + ".model.json"),
                encoding="utf-8",
            ) as f:
                metrics = json.load(f)
            result.update(
                {
                    "load": load,
                    "seed": seed,
                    **{
                        k: metrics[k]
                        for k in (
                            "delivered_pkts",
                            "delivered_flits",
                            "utilization",
                            "avg_pkt_latency",
                            "avg_admit_latency",
                            "p99_admit_latency",
                            "avg_queue_latency",
                            "avg_queue_occupancy",
                            "source_stall_rate",
                            "output_idle_rate",
                            "hol_rate",
                            "hol_output_busy_rate",
                            "hol_arb_loss_rate",
                            "arb_loss_rate",
                            "arb_loss_events",
                            "out_flits",
                            "jain",
                            "jain_out",
                            "trace_offered_flits",
                        )
                    },
                    "p99_pkt_latency": p99_latency(model_csv, args.warmup),
                }
            )
            runs.append(result)
            status = "MATCH" if result["match"] else "MISMATCH"
            print(
                f"{status} load={load:g} seed={seed} "
                f"rtl_rows={result['rtl_packets']} "
                f"delivered_pkts={result['delivered_pkts']} "
                f"delivered_flits={result['delivered_flits']}",
                file=sys.stderr,
            )

    summary = {}
    for load in loads:
        rows = [r for r in runs if r["load"] == load]
        summary[load] = {
            "exact": all(r["match"] for r in rows),
            "seeds": len(rows),
            "delivered_pkts": mean([r["delivered_pkts"] for r in rows]),
            "delivered_flits": mean([r["delivered_flits"] for r in rows]),
            "offered_flits": mean([r["trace_offered_flits"] for r in rows]),
            "utilization": mean([r["utilization"] for r in rows]),
            "avg_pkt_latency": mean([r["avg_pkt_latency"] for r in rows]),
            "p99_pkt_latency": mean([r["p99_pkt_latency"] for r in rows]),
            "avg_admit_latency": mean([r["avg_admit_latency"] for r in rows]),
            "p99_admit_latency": mean([r["p99_admit_latency"] for r in rows]),
            "avg_queue_latency": mean([r["avg_queue_latency"] for r in rows]),
            "avg_queue_occupancy": mean([r["avg_queue_occupancy"] for r in rows]),
            "source_stall_rate": mean([r["source_stall_rate"] for r in rows]),
            "output_idle_rate": mean([r["output_idle_rate"] for r in rows]),
            "hol_rate": mean([r["hol_rate"] for r in rows]),
            "hol_output_busy_rate": mean(
                [r["hol_output_busy_rate"] for r in rows]
            ),
            "hol_arb_loss_rate": mean([r["hol_arb_loss_rate"] for r in rows]),
            "arb_loss_rate": mean([r["arb_loss_rate"] for r in rows]),
            "arb_loss_events": mean([r["arb_loss_events"] for r in rows]),
            "jain": mean([r["jain"] for r in rows]),
            "jain_out": mean([r["jain_out"] for r in rows]),
        }

    header = (
        "| load | seeds | exact | delivered pkts | delivered flits | "
        "utilization | avg pkt lat | p99 pkt lat | avg queue lat | "
        "avg queue occ | source stall | output idle | HOL rate | Jain |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    lines = [header]
    for load in loads:
        s = summary[load]
        lines.append(
            f"| {load:g} | {s['seeds']} | {'yes' if s['exact'] else 'NO'} | "
            f"{s['delivered_pkts']:.1f} | {s['delivered_flits']:.0f} | "
            f"{s['utilization']:.3f} | {s['avg_pkt_latency']:.2f} | "
            f"{s['p99_pkt_latency']:.1f} | {s['avg_queue_latency']:.2f} | "
            f"{s['avg_queue_occupancy']:.2f} | "
            f"{s['source_stall_rate']:.4f} | {s['output_idle_rate']:.3f} | "
            f"{s['hol_rate']:.4f} | {s['jain']:.4f} |\n"
        )
    table = "".join(lines)
    print(table)

    payload = {
        "mode": args.mode,
        "dut": args.dut,
        "cycles": args.cycles,
        "warmup": args.warmup,
        "total_buffer": args.total_buffer,
        "source_gap": args.source_gap,
        "rdy_period": args.rdy_period,
        "rdy_high": args.rdy_high,
        "summary": {str(k): v for k, v in summary.items()},
        "runs": runs,
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    if args.markdown_out:
        with open(args.markdown_out, "w", encoding="utf-8") as f:
            f.write(table)
    return 0 if all(r["match"] for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
