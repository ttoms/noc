#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the E1 comparison matrix: shared 1W2R per input vs Experiment 1 VOQ.

Main comparison (per user decision):
  * shared: full 1W2R shared FIFO, both read ports usable in the same cycle
  * VOQ: Experiment 1 VOQ baseline, one input read per cycle

The difference therefore includes the extra read port; the report must say so.

Usage:
  python3 scripts/run_e1.py --seeds 1,2,3,4,5 \
      --cell-nums 16,32,64 --loads 0.8,0.95,1.0 \
      --workdir /root/Temp/e1 --outdir results/e1
"""

from __future__ import annotations

import argparse
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

import model_v2  # noqa: E402
from model_e1 import run as shared_run  # noqa: E402
from derive_vc_trace import main as derive_main  # noqa: E402


def parse_list(text: str, cast):
    return [cast(x) for x in text.split(",") if x.strip()]


def gen_base_trace(
    out: Path,
    load: float,
    seed: int,
    cycles: int,
    length_mode: str,
    traffic: str,
) -> None:
    cmd = [
        sys.executable,
        str(EXP1 / "scripts" / "gen_trace.py"),
        "--out",
        str(out),
        "--load",
        str(load),
        "--cycles",
        str(cycles),
        "--seed",
        str(seed),
        "--length-mode",
        length_mode,
        "--traffic",
        traffic,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def derive_trace(base: Path, out: Path, vc_mode: str, vc_num: int, seed: int) -> None:
    argv = [
        "derive_vc_trace.py",
        "--in",
        str(base),
        "--out",
        str(out),
        "--vc-mode",
        vc_mode,
        "--vc-num",
        str(vc_num),
        "--seed",
        str(seed),
    ]
    old = sys.argv
    try:
        sys.argv = argv
        rc = derive_main()
    finally:
        sys.argv = old
    if rc != 0:
        raise RuntimeError(f"derive_vc_trace failed for {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1,2,3,4,5")
    ap.add_argument("--cell-nums", default="16,32,64")
    ap.add_argument("--loads", default="0.8,0.95,1.0")
    ap.add_argument("--cycles", type=int, default=4000)
    ap.add_argument("--warmup", type=int, default=500)
    ap.add_argument("--length-mode", default="uniform1-8")
    ap.add_argument("--traffic", default="uniform")
    ap.add_argument("--vc-modes", default="per_dst,multi2")
    ap.add_argument("--workdir", default="/root/Temp/e1")
    ap.add_argument("--outdir", default="results/e1")
    ap.add_argument("--rdy-period", type=int, default=0)
    ap.add_argument("--rdy-high", type=int, default=0)
    ap.add_argument("--check-every", type=int, default=1)
    ap.add_argument("--same-cycle-free", action="store_true")
    args = ap.parse_args()

    seeds = parse_list(args.seeds, int)
    cell_nums = parse_list(args.cell_nums, int)
    loads = parse_list(args.loads, float)
    vc_modes = [x.strip() for x in args.vc_modes.split(",") if x.strip()]
    if any(c % 2 for c in cell_nums):
        print("ERROR: cell-nums must be even for equal-buffer VOQ pairing", file=sys.stderr)
        return 2
    for mode in vc_modes:
        if mode not in ("per_dst", "multi2", "multi4"):
            print(f"ERROR: unknown vc mode {mode}", file=sys.stderr)
            return 2

    workdir = Path(args.workdir)
    outdir = Path(args.outdir)
    workdir.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    runs: list[dict] = []
    total = len(seeds) * len(loads) * len(cell_nums) * (1 + len(vc_modes))
    done = 0
    for seed in seeds:
        for load in loads:
            stem = f"base_l{load:g}_s{seed}"
            base = workdir / f"{stem}.jsonl"
            if not base.exists():
                gen_base_trace(
                    base,
                    load,
                    seed,
                    args.cycles,
                    args.length_mode,
                    args.traffic,
                )
            trace_by_mode: dict[str, Path] = {}
            for mode in vc_modes:
                vc_num = 4 if mode == "multi4" else 2
                vc_mode_arg = "per_dst" if mode == "per_dst" else "multi"
                out = workdir / f"{stem}_{mode}.jsonl"
                derive_trace(base, out, vc_mode_arg, vc_num, seed)
                trace_by_mode[mode] = out

            for cell_num in cell_nums:
                common = {
                    "load": load,
                    "seed": seed,
                    "capacity": cell_num,
                    "length_mode": args.length_mode,
                    "traffic": args.traffic,
                    "cycles": args.cycles,
                    "warmup": args.warmup,
                    "rdy_period": args.rdy_period,
                    "rdy_high": args.rdy_high,
                }

                voq = model_v2.run(
                    str(base),
                    "voq",
                    total_buffer=2 * cell_num,
                    cycles=args.cycles,
                    warmup=args.warmup,
                    csv_path=None,
                    per_queue_depth=cell_num // 2,
                    source_gap=0,
                    rdy_period=args.rdy_period,
                    rdy_high=args.rdy_high,
                )
                runs.append(
                    {
                        "arch": "voq",
                        "vc_mode": "none",
                        "vc_num": 0,
                        "queue_depth": cell_num // 2,
                        **common,
                        "metrics": voq,
                    }
                )
                done += 1
                print(
                    f"[{done}/{total}] voq  cap={cell_num} load={load} seed={seed} "
                    f"util={voq['utilization']:.4f}",
                    flush=True,
                )

                for mode in vc_modes:
                    vc_num = 4 if mode == "multi4" else 2
                    res = shared_run(
                        str(trace_by_mode[mode]),
                        cell_num=cell_num,
                        vc_num=vc_num,
                        vc_mode=mode,
                        cycles=args.cycles,
                        warmup=args.warmup,
                        rdy_period=args.rdy_period,
                        rdy_high=args.rdy_high,
                        same_cycle_free=args.same_cycle_free,
                        check_every=args.check_every,
                    )
                    runs.append(
                        {
                            "arch": "shared",
                            "vc_mode": mode,
                            "vc_num": vc_num,
                            "queue_depth": None,
                            **common,
                            "metrics": res,
                        }
                    )
                    done += 1
                    print(
                        f"[{done}/{total}] shared {mode:8s} cap={cell_num} "
                        f"load={load} seed={seed} util={res['utilization']:.4f} "
                        f"admit={res['avg_admit_latency']:.2f} "
                        f"hol={res['vc_hol_cycles']}",
                        flush=True,
                    )

    payload = {
        "meta": {
            "seeds": seeds,
            "cell_nums": cell_nums,
            "loads": loads,
            "vc_modes": vc_modes,
            "cycles": args.cycles,
            "warmup": args.warmup,
            "length_mode": args.length_mode,
            "traffic": args.traffic,
            "rdy_period": args.rdy_period,
            "rdy_high": args.rdy_high,
            "same_cycle_free": args.same_cycle_free,
            "read_ports": "shared=2 per input, voq=1 per input",
        },
        "runs": runs,
    }
    out = outdir / "raw_runs.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"wrote {len(runs)} runs to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
