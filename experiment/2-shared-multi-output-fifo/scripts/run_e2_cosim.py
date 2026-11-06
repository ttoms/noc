#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run E2 RTL vs cycle-model co-simulation on generated traces.

The RTL trace TB and model use the same trace, with arrival offset 5 so
packets do not fall into the reset window.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
EXP2 = HERE.parents[1]
EXP_ROOT = HERE.parents[2]
EXP1 = EXP_ROOT / "1-2x2-crossbar-fifo-vs-voq"
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(EXP1 / "scripts"))

import model_e2  # noqa: E402
from derive_vc_trace import main as derive_main  # noqa: E402

VENDOR = EXP2 / "vendor" / "cbb" / "rtl"
RTL = EXP2 / "rtl" / "xbar_2x2_shared.sv"
TB = EXP2 / "tb" / "xbar_2x2_trace_tb.sv"
CBB = [
    VENDOR / "stream" / "mo_fifo_top.sv",
    VENDOR / "order" / "idpool.sv",
    VENDOR / "order" / "link_list.sv",
    VENDOR / "memory" / "shared_buffer.sv",
    VENDOR / "arbiter" / "arbiter_rr.sv",
    VENDOR / "arbiter" / "pri_tree.sv",
    VENDOR / "arbiter" / "suf_or.sv",
    VENDOR / "util" / "ohot2bin.sv",
    VENDOR / "util" / "ohot_pri_enc.sv",
    VENDOR / "basic" / "dffr.sv",
]


def derive(base: Path, out: Path, vc_num: int, seed: int) -> None:
    old = sys.argv
    try:
        sys.argv = [
            "derive_vc_trace.py", "--in", str(base), "--out", str(out),
            "--vc-mode", "multi", "--vc-num", str(vc_num), "--seed", str(seed),
        ]
        rc = derive_main()
    finally:
        sys.argv = old
    if rc != 0:
        raise RuntimeError(f"derive_vc_trace failed: {out}")


def offset_trace(src: Path, dst: Path, offset: int) -> None:
    with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8") as g:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            r["arrival"] = int(r["arrival"]) + offset
            g.write(json.dumps(r) + "\n")


def load_csv(path: Path) -> dict[int, dict]:
    return {int(r["seq"]): r for r in csv.DictReader(open(path, encoding="utf-8"))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1,2,3,4,5")
    ap.add_argument("--loads", default="0.8,0.9,1.0")
    ap.add_argument("--cell-nums", default="16")
    ap.add_argument("--vc-nums", default="2")
    ap.add_argument("--trace-cycles", type=int, default=2500)
    ap.add_argument("--sim-cycles", type=int, default=2600)
    ap.add_argument("--rdy-period", type=int, default=0)
    ap.add_argument("--rdy-high", type=int, default=0)
    ap.add_argument("--workdir", default="/root/Temp/e2_cosim")
    ap.add_argument("--outdir", default="results/e2_cosim")
    args = ap.parse_args()

    work = Path(args.workdir)
    outdir = Path(args.outdir)
    work.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    seeds = [int(x) for x in args.seeds.split(",")]
    loads = [float(x) for x in args.loads.split(",")]
    cell_nums = [int(x) for x in args.cell_nums.split(",")]
    vc_nums = [int(x) for x in args.vc_nums.split(",")]
    rows = []
    for cell_num in cell_nums:
      for vc_num in vc_nums:
        simv = work / f"xbar_trace_tb_c{cell_num}_v{vc_num}"
        compile_cmd = [
            "iverilog", "-g2012",
            f"-DTB_CELL_NUM={cell_num}", f"-DTB_VC_NUM={vc_num}",
            "-o", str(simv),
            str(RTL), *[str(p) for p in CBB], str(TB),
        ]
        subprocess.run(compile_cmd, check=True)
        for seed in seeds:
          for load in loads:
            stem = f"c{cell_num}_v{vc_num}_l{load:g}_s{seed}"
            base = work / f"{stem}_base.jsonl"
            vc = work / f"{stem}_vc.jsonl"
            vc_off = work / f"{stem}_vc_off.jsonl"
            trace_csv = work / f"{stem}_trace.csv"
            rtl_csv = work / f"{stem}_rtl.csv"
            model_csv = work / f"{stem}_model.csv"
            subprocess.run(
                [
                    sys.executable, str(EXP1 / "scripts" / "gen_trace.py"),
                    "--out", str(base), "--load", str(load),
                    "--cycles", str(args.trace_cycles), "--seed", str(seed),
                    "--length-mode", "uniform1-8", "--traffic", "uniform",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            derive(base, vc, vc_num, seed)
            offset_trace(vc, vc_off, 5)
            subprocess.run(
                [
                    sys.executable, str(HERE.parent / "trace_to_csv.py"),
                    "--in", str(vc_off), "--out", str(trace_csv),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    "vvp", str(simv), f"+TRACE={trace_csv}", f"+OUT={rtl_csv}",
                    f"+CYCLES={args.sim_cycles}",
                    f"+RDY_PERIOD={args.rdy_period}",
                    f"+RDY_HIGH={args.rdy_high}",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            model_e2.run(
                str(vc_off), cell_num, vc_num, 2,
                args.sim_cycles, 0, str(model_csv),
                args.rdy_period, args.rdy_high,
            )
            m = load_csv(model_csv)
            r = load_csv(rtl_csv)
            common = set(m) & set(r)
            d_start = [
                int(r[s]["start"]) - int(m[s]["start"]) for s in common
            ]
            d_end = [
                int(r[s]["end"]) - int(m[s]["end"]) for s in common
            ]
            ok = (
                set(m) == set(r)
                and all(d == 0 for d in d_start)
                and all(d == 0 for d in d_end)
            )
            rows.append(
                {
                    "cell_num": cell_num,
                    "vc_num": vc_num,
                    "load": load,
                    "seed": seed,
                    "model_pkts": len(m),
                    "rtl_pkts": len(r),
                    "common": len(common),
                    "start_delta_max": max(map(abs, d_start), default=0),
                    "end_delta_max": max(map(abs, d_end), default=0),
                    "exact": int(ok),
                }
            )
            print(
                f"cell={cell_num} vc={vc_num} load={load:g} seed={seed} model={len(m)} rtl={len(r)} "
                f"common={len(common)} exact={ok}",
                flush=True,
            )
            if not ok:
                raise SystemExit(1)

    with open(outdir / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {outdir / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
