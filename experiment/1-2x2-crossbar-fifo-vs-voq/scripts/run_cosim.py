#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run one model/RTL co-simulation and compare at packet and cycle level.

The comparison is exact: no statistical tolerance.  Packet rows are compared
per output port in completion order; the optional per-cycle debug CSVs are
compared cell by cell.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_CBB_RTL = os.environ.get(
    "CBB_RTL", os.path.join(ROOT, "vendor", "cbb", "rtl")
)

CBB_SOURCES = [
    "memory/fifo_sync.sv",
    "arbiter/arbiter_rr.sv",
    "arbiter/pri_tree.sv",
    "arbiter/suf_or.sv",
    "util/bin2ohot.sv",
    "basic/dff.sv",
    "basic/dffr.sv",
]


DUT_FILES = {
    "fifo": ("rtl/xbar_2x2_fifo.sv", "tb/xbar_2x2_fifo_tb.sv"),
    "voq": ("rtl/xbar_2x2_voq.sv", "tb/xbar_2x2_voq_tb.sv"),
    "xp": ("rtl/xbar_2x2_xp.sv", "tb/xbar_2x2_xp_tb.sv"),
}

TB_TOP = {
    "fifo": "xbar_2x2_fifo_tb",
    "voq": "xbar_2x2_voq_tb",
    "xp": "xbar_2x2_xp_tb",
}


def compile_rtl(
    binary: str,
    cbb_rtl: str,
    dut: str = "fifo",
    depth: int | None = None,
) -> None:
    if dut not in DUT_FILES:
        raise SystemExit(f"unknown dut {dut}")
    os.makedirs(os.path.dirname(os.path.abspath(binary)), exist_ok=True)
    rtl_file, tb_file = DUT_FILES[dut]
    cmd = [
        "iverilog",
        "-g2012",
        "-I",
        cbb_rtl,
        "-o",
        binary,
    ]
    if depth is not None:
        # Compile-time per-queue capacity: FIFO DEPTH, VOQ/XP per-queue depth.
        cmd += ["-P", f"{TB_TOP[dut]}.DEPTH={depth}"]
    cmd += [
        os.path.join(ROOT, rtl_file),
        os.path.join(ROOT, tb_file),
    ] + [os.path.join(cbb_rtl, src) for src in CBB_SOURCES]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"iverilog failed ({proc.returncode})")


def read_packets(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def compare_packets(rtl_rows: list[dict], model_rows: list[dict]) -> list[str]:
    errors: list[str] = []
    for port in ("0", "1"):
        rtl = [r for r in rtl_rows if r["port"] == port]
        model = [r for r in model_rows if r["dst"] == port]
        if len(rtl) != len(model):
            errors.append(
                f"port {port}: delivered count RTL={len(rtl)} model={len(model)}"
            )
        for idx, (r, m) in enumerate(zip(rtl, model)):
            got = (r["src"], r["len"], r["start"], r["end"])
            exp = (m["src"], m["len"], m["start"], m["end"])
            if got != exp:
                errors.append(
                    f"port {port} row {idx}: RTL={got} model={exp} "
                    f"(model seq={m['seq']} arrival={m['arrival']})"
                )
                if len(errors) >= 12:
                    return errors
    return errors


def compare_cycles(rtl_path: str, model_path: str) -> list[str]:
    rtl = read_packets(rtl_path)
    model = read_packets(model_path)
    errors: list[str] = []
    if len(rtl) != len(model):
        errors.append(f"cycle rows: RTL={len(rtl)} model={len(model)}")
    if rtl and model and list(rtl[0].keys()) != list(model[0].keys()):
        errors.append("cycle CSV headers differ")
        return errors
    for i, (r, m) in enumerate(zip(rtl, model)):
        for key in r:
            if r[key] != m[key]:
                errors.append(
                    f"cycle {r.get('cycle', i)} column {key}: "
                    f"RTL={r[key]} model={m[key]}"
                )
                if len(errors) >= 12:
                    return errors
    return errors


def run_one(
    trace_jsonl: str,
    trace_csv: str,
    cycles: int,
    outdir: str,
    binary: str,
    mode: str,
    total_buffer: int,
    warmup: int,
    compile: bool,
    cbb_rtl: str,
    check_cycles: bool,
    dut: str = "fifo",
    depth: int | None = None,
) -> dict:
    if depth is None:
        # Backward-compatible total-buffer interpretation:
        # FIFO total/2 per input; VOQ/XP total/4 per crosspoint queue.
        depth = total_buffer // 2 if mode == "fifo" else total_buffer // 4
    if depth < 2:
        raise SystemExit(f"per-queue depth must be >= 2, got {depth}")
    if depth & (depth - 1):
        raise SystemExit(
            f"per-queue depth must be a power of two (fifo_sync), got {depth}"
        )
    os.makedirs(outdir, exist_ok=True)
    if compile:
        compile_rtl(binary, cbb_rtl, dut, depth)

    base = os.path.splitext(os.path.basename(trace_jsonl))[0]
    rtl_out = os.path.join(outdir, base + ".rtl_packets.csv")
    rtl_cycles = os.path.join(outdir, base + ".rtl_cycles.csv")
    model_out = os.path.join(outdir, base + ".model_packets.csv")
    model_cycles = os.path.join(outdir, base + ".model_cycles.csv")
    model_json = os.path.join(outdir, base + ".model.json")

    model_cmd = [
        sys.executable,
        os.path.join(HERE, "model_v2.py"),
        "--trace",
        trace_jsonl,
        "--mode",
        mode,
        "--per-queue-depth",
        str(depth),
        "--cycles",
        str(cycles),
        "--warmup",
        str(warmup),
        "--csv",
        model_out,
        "--json",
    ]
    if check_cycles:
        model_cmd += ["--cycles-csv", model_cycles]
    proc = subprocess.run(model_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"model failed ({proc.returncode})")
    with open(model_json, "w", encoding="utf-8") as f:
        f.write(proc.stdout)

    vvp_cmd = [
        "vvp",
        binary,
        f"+TRACE={trace_csv}",
        f"+OUT={rtl_out}",
        f"+CYCLES={cycles}",
    ]
    if check_cycles:
        vvp_cmd.append(f"+DBG={rtl_cycles}")
    proc = subprocess.run(vvp_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"vvp failed ({proc.returncode})")

    packet_errors = compare_packets(
        read_packets(rtl_out), read_packets(model_out)
    )
    cycle_errors = (
        compare_cycles(rtl_cycles, model_cycles) if check_cycles else []
    )
    result = {
        "trace": base,
        "cycles": cycles,
        "per_queue_depth": depth,
        "rtl_packets": len(read_packets(rtl_out)),
        "model_packets": len(read_packets(model_out)),
        "packet_errors": packet_errors,
        "cycle_errors": cycle_errors[:12],
        "match": not packet_errors and not cycle_errors,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="exact model/RTL co-simulation")
    parser.add_argument("--trace-jsonl", required=True)
    parser.add_argument("--trace-csv", required=True)
    parser.add_argument("--cycles", type=int, required=True)
    parser.add_argument("--outdir", default=os.path.join(ROOT, "out", "cosim"))
    parser.add_argument("--binary", default=os.path.join(ROOT, "build", "xbar_fifo_tb"))
    parser.add_argument("--dut", choices=["fifo", "voq", "xp"], default="fifo")
    parser.add_argument("--mode", choices=["fifo", "voq", "xp"], default="fifo")
    parser.add_argument("--total-buffer", type=int, default=64)
    parser.add_argument("--depth", type=int, default=None,
                        help="per-queue depth (overrides --total-buffer)")
    parser.add_argument("--warmup", type=int, default=0)
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--cbb-rtl", default=DEFAULT_CBB_RTL)
    parser.add_argument("--no-cycles", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_one(
        args.trace_jsonl,
        args.trace_csv,
        args.cycles,
        args.outdir,
        args.binary,
        args.mode,
        args.total_buffer,
        args.warmup,
        args.compile,
        args.cbb_rtl,
        not args.no_cycles,
        args.dut,
        args.depth,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "MATCH" if result["match"] else "MISMATCH"
        print(
            f"{result['trace']}: {status} "
            f"(packets RTL={result['rtl_packets']} model={result['model_packets']}, "
            f"cycles={result['cycles']})"
        )
        for err in result["packet_errors"]:
            print("  packet:", err)
        for err in result["cycle_errors"]:
            print("  cycle :", err)
    return 0 if result["match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
