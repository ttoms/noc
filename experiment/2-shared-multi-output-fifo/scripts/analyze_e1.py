#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aggregate E1 raw runs into 5-seed means and paired 95% t CIs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def tcrit(n: int) -> float:
    table = {
        2: 12.706,
        3: 4.303,
        4: 3.182,
        5: 2.776,
        6: 2.571,
        7: 2.447,
        8: 2.365,
        9: 2.306,
        10: 2.262,
    }
    return table.get(n, 1.96)


def mean_ci(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], 0.0
    return (
        statistics.mean(values),
        tcrit(len(values)) * statistics.stdev(values) / math.sqrt(len(values)),
    )


def key(run: dict) -> tuple:
    return (run["capacity"], run["load"], run["seed"])


def arch_key(run: dict) -> tuple:
    return (run["arch"], run["vc_mode"])


def metric(run: dict, name: str) -> float:
    m = run["metrics"]
    if name == "jain_input" and run["arch"] == "voq":
        # Experiment 1's VOQ summary names per-source fairness "jain".
        return float(m.get("jain", 0.0))
    return float(m.get(name, 0.0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", nargs="?", default="results/e1/raw_runs.json")
    ap.add_argument("--outdir", default="results/e1")
    args = ap.parse_args()
    payload = json.load(open(args.raw, encoding="utf-8"))
    runs = payload["runs"]
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    by_arch: dict[tuple, dict[tuple, dict]] = defaultdict(dict)
    for r in runs:
        by_arch[arch_key(r)][key(r)] = r

    # Summary per architecture/stratum.
    summary_rows = []
    for (arch, vc_mode), strata in sorted(by_arch.items()):
        for (cap, load), _ in sorted(
            {(k[0], k[1]): None for k in strata}.items()
        ):
            selected = [r for k, r in strata.items() if k[0] == cap and k[1] == load]
            if not selected:
                continue
            util_m, util_ci = mean_ci([metric(r, "utilization") for r in selected])
            admit_m, admit_ci = mean_ci(
                [metric(r, "avg_admit_latency") for r in selected]
            )
            p99_m, p99_ci = mean_ci(
                [metric(r, "p99_admit_latency") for r in selected]
            )
            summary_rows.append(
                {
                    "arch": arch,
                    "vc_mode": vc_mode,
                    "capacity": cap,
                    "load": load,
                    "n": len(selected),
                    "util_mean": util_m,
                    "util_ci95": util_ci,
                    "admit_mean": admit_m,
                    "admit_ci95": admit_ci,
                    "p99_admit_mean": p99_m,
                    "p99_admit_ci95": p99_ci,
                    "vc_hol_rate_mean": statistics.mean(
                        metric(r, "vc_hol_rate") for r in selected
                    ),
                    "dual_read_rate_mean": statistics.mean(
                        metric(r, "dual_read_rate") for r in selected
                    ),
                    "pool_util_mean": statistics.mean(
                        metric(r, "pool_utilization") for r in selected
                    ),
                    "source_stall_rate_mean": statistics.mean(
                        metric(r, "source_stall_rate") for r in selected
                    ),
                    "jain_input_mean": statistics.mean(
                        metric(r, "jain_input") for r in selected
                    ),
                    "jain_out_mean": statistics.mean(
                        metric(r, "jain_out") for r in selected
                    ),
                }
            )

    with open(outdir / "summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(summary_rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    # Paired deltas: shared - voq, per_dst - multi2.
    pairs = [
        ("shared_per_dst_vs_voq", ("shared", "per_dst"), ("voq", "none")),
        ("shared_multi2_vs_voq", ("shared", "multi2"), ("voq", "none")),
        ("shared_multi4_vs_voq", ("shared", "multi4"), ("voq", "none")),
        ("per_dst_vs_multi2", ("shared", "per_dst"), ("shared", "multi2")),
    ]
    paired_rows = []
    for name, left_key, right_key in pairs:
        left = by_arch.get(left_key, {})
        right = by_arch.get(right_key, {})
        groups: dict[tuple[int, float], list[dict]] = defaultdict(list)
        for k, lr in left.items():
            rr = right.get(k)
            if rr is None:
                continue
            groups[(k[0], k[1])].append(
                {
                    "d_util": metric(lr, "utilization") - metric(rr, "utilization"),
                    "d_admit": metric(lr, "avg_admit_latency")
                    - metric(rr, "avg_admit_latency"),
                    "d_p99": metric(lr, "p99_admit_latency")
                    - metric(rr, "p99_admit_latency"),
                    "d_hol": metric(lr, "vc_hol_rate") - metric(rr, "vc_hol_rate"),
                    "d_dual": metric(lr, "dual_read_rate")
                    - metric(rr, "dual_read_rate"),
                }
            )
        for (cap, load), ds in sorted(groups.items()):
            util_m, util_ci = mean_ci([d["d_util"] for d in ds])
            admit_m, admit_ci = mean_ci([d["d_admit"] for d in ds])
            p99_m, p99_ci = mean_ci([d["d_p99"] for d in ds])
            paired_rows.append(
                {
                    "pair": name,
                    "capacity": cap,
                    "load": load,
                    "n": len(ds),
                    "d_util_mean_pp": util_m * 100,
                    "d_util_ci95_pp": util_ci * 100,
                    "d_admit_mean": admit_m,
                    "d_admit_ci95": admit_ci,
                    "d_p99_admit_mean": p99_m,
                    "d_p99_admit_ci95": p99_ci,
                    "d_vc_hol_rate_mean": statistics.mean(d["d_hol"] for d in ds),
                    "d_dual_read_rate_mean": statistics.mean(
                        d["d_dual"] for d in ds
                    ),
                }
            )

    with open(outdir / "paired.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(paired_rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(paired_rows)

    # Console summary.
    print("== summary (utilization, mean ± 95% CI, 5 seeds) ==")
    for row in summary_rows:
        print(
            f"{row['arch']:7s} {row['vc_mode']:8s} cap={row['capacity']:2d} "
            f"load={row['load']:.2f} "
            f"util={row['util_mean']:.4f}±{row['util_ci95']:.4f} "
            f"admit={row['admit_mean']:.2f}±{row['admit_ci95']:.2f} "
            f"hol={row['vc_hol_rate_mean']:.3f} "
            f"dual={row['dual_read_rate_mean']:.3f}"
        )
    print("== paired deltas ==")
    for row in paired_rows:
        print(
            f"{row['pair']:28s} cap={row['capacity']:2d} load={row['load']:.2f} "
            f"d_util={row['d_util_mean_pp']:+.2f}±{row['d_util_ci95_pp']:.2f}pp "
            f"d_admit={row['d_admit_mean']:+.2f}±{row['d_admit_ci95']:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
