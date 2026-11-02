#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RTL-vs-RTL equivalence check for XP and VOQ on the same traces.

Both DUTs are first co-simulated against their cycle model; then the XP and
VOQ RTL packet CSVs and per-cycle debug CSVs are compared cell by cell.  This
is separate from the model-vs-RTL check: it answers whether the two physical
implementations expose the same observable behavior in the XP-only 2x2 setup.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys

from run_cosim import DEFAULT_CBB_RTL, compile_rtl, read_packets, run_one

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_WORKDIR = os.path.expanduser("~/Temp/phase3_equiv")


def compare_csv(path_a: str, path_b: str) -> list[str]:
    a = read_packets(path_a)
    b = read_packets(path_b)
    errors = []
    if len(a) != len(b):
        errors.append(f"row count {len(a)} vs {len(b)}")
    if a and b and list(a[0].keys()) != list(b[0].keys()):
        errors.append("header mismatch")
        return errors
    for idx, (row_a, row_b) in enumerate(zip(a, b)):
        for key in row_a:
            if row_a[key] != row_b[key]:
                errors.append(
                    f"row {idx} column {key}: {row_a[key]} vs {row_b[key]}"
                )
                if len(errors) >= 12:
                    return errors
    return errors


def split_list(text):
    return [x.strip() for x in text.split(",") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="exact RTL equivalence: XP vs VOQ"
    )
    parser.add_argument("--traces-dir", required=True,
                        help="directory with matching .jsonl/.csv trace pairs")
    parser.add_argument("--depths", default="4,8,16,32")
    parser.add_argument("--cycles", type=int, default=1200)
    parser.add_argument("--warmup", type=int, default=0)
    parser.add_argument("--workdir", default=DEFAULT_WORKDIR)
    parser.add_argument("--out",
                        default=os.path.join(ROOT, "results", "phase3",
                                             "xp_voq_rtl_equivalence.json"))
    parser.add_argument("--cbb-rtl", default=DEFAULT_CBB_RTL)
    args = parser.parse_args()

    depths = [int(x) for x in split_list(args.depths)]
    trace_jsonl = sorted(glob.glob(os.path.join(args.traces_dir, "*.jsonl")))
    if not trace_jsonl:
        raise SystemExit(f"no .jsonl traces in {args.traces_dir}")

    os.makedirs(args.workdir, exist_ok=True)
    binaries = {}
    for depth in depths:
        for queue in ("xp", "voq"):
            binary = os.path.join(args.workdir, "build", f"{queue}_c{depth}")
            compile_rtl(binary, args.cbb_rtl, queue, depth)
            binaries[(queue, depth)] = binary

    results = []
    for depth in depths:
        for jsonl in trace_jsonl:
            base = os.path.splitext(os.path.basename(jsonl))[0]
            csv_path = os.path.join(args.traces_dir, base + ".csv")
            if not os.path.exists(csv_path):
                print(f"skip {base}: no CSV", file=sys.stderr)
                continue
            runs = {}
            for queue in ("xp", "voq"):
                outdir = os.path.join(args.workdir, f"c{depth}", queue)
                runs[queue] = run_one(
                    jsonl,
                    csv_path,
                    args.cycles,
                    outdir,
                    binaries[(queue, depth)],
                    queue,
                    4 * depth,
                    args.warmup,
                    False,
                    args.cbb_rtl,
                    True,
                    queue,
                    depth,
                )
            xp_dir = os.path.join(args.workdir, f"c{depth}", "xp")
            voq_dir = os.path.join(args.workdir, f"c{depth}", "voq")
            packet_errors = compare_csv(
                os.path.join(xp_dir, base + ".rtl_packets.csv"),
                os.path.join(voq_dir, base + ".rtl_packets.csv"),
            )
            cycle_errors = compare_csv(
                os.path.join(xp_dir, base + ".rtl_cycles.csv"),
                os.path.join(voq_dir, base + ".rtl_cycles.csv"),
            )
            record = {
                "depth": depth,
                "trace": base,
                "xp_model_exact": runs["xp"]["match"],
                "voq_model_exact": runs["voq"]["match"],
                "rtl_packets_equal": not packet_errors,
                "rtl_cycles_equal": not cycle_errors,
                "packet_errors": packet_errors[:12],
                "cycle_errors": cycle_errors[:12],
            }
            results.append(record)
            status = (
                "MATCH"
                if record["rtl_packets_equal"] and record["rtl_cycles_equal"]
                else "MISMATCH"
            )
            print(
                f"{status} c={depth} {base} "
                f"(xp_exact={record['xp_model_exact']} "
                f"voq_exact={record['voq_model_exact']})",
                file=sys.stderr,
            )

    summary = {
        "traces": len(trace_jsonl),
        "depths": depths,
        "runs": len(results),
        "all_xp_model_exact": all(r["xp_model_exact"] for r in results),
        "all_voq_model_exact": all(r["voq_model_exact"] for r in results),
        "all_packet_files_equal": all(r["rtl_packets_equal"] for r in results),
        "all_cycle_files_equal": all(r["rtl_cycles_equal"] for r in results),
        "all_equivalent": all(
            r["xp_model_exact"]
            and r["voq_model_exact"]
            and r["rtl_packets_equal"]
            and r["rtl_cycles_equal"]
            for r in results
        ),
        "cases": results,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps({
        "traces": summary["traces"],
        "depths": summary["depths"],
        "runs": summary["runs"],
        "all_equivalent": summary["all_equivalent"],
        "out": args.out,
    }, ensure_ascii=False, indent=2))
    return 0 if summary["all_equivalent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
