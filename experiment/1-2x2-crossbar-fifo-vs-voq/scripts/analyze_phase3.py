#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aggregate Phase 3 FIFO / VOQ / XP runs into summary JSON and CSVs.

Input is `raw_runs.json` produced by run_phase3.py.  Outputs:

  core_capacity.csv          queue x capacity x load (core matrix)
  matrix_cells.csv           every queue x capacity x load cell
  effect_strata.csv          paired deltas for XP/FIFO, VOQ/FIFO, XP/VOQ
  effect_groups.csv          the same deltas grouped by capacity and load
  equal_buffer.csv           FIFO vs 4-queue at equal total flits, plus XP vs VOQ
  xp_voq_equivalence.csv     per-cell metric equality check for XP and VOQ
  summary.json               machine-readable aggregate

No raw per-cycle or per-packet CSV is stored here.  Those are compared exactly
inside run_phase3.py and discarded after the comparison.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
from collections import defaultdict

METRICS = [
    "utilization",
    "avg_pkt_latency",
    "p99_pkt_latency",
    "source_stall_rate",
    "hol_rate",
    "avg_queue_occupancy",
    "max_total_queue_occupancy",
    "max_input_queue_occupancy",
    "max_single_dst_queue_occupancy",
    "jain",
    "jain_dst",
    "output_idle_rate",
    "delivered_pkts",
    "delivered_flits",
    "trace_offered_flits",
]

PAIRS = [("xp", "fifo"), ("voq", "fifo"), ("xp", "voq")]
PAIR_LABELS = {
    ("xp", "fifo"): "XP vs FIFO",
    ("voq", "fifo"): "VOQ vs FIFO",
    ("xp", "voq"): "XP vs VOQ",
}

# FIFO has 2 queues, VOQ/XP have 4.  Equal total requires C_4q = C_fifo / 2.
EQUAL_TOTAL_FIFO_CAPS = [8, 16, 32]
UNCOVERED_EQUAL_BUFFER = [
    {
        "comparison": "fifo_vs_4q_equal_total",
        "fifo_capacity": 4,
        "fourq_capacity": 2,
        "total_flits": 8,
        "reason": "4-queue capacity 2 is outside the measured grid {4,8,16,32}",
    },
    {
        "comparison": "fifo_vs_4q_equal_total",
        "fifo_capacity": 64,
        "fourq_capacity": 32,
        "total_flits": 128,
        "reason": "FIFO capacity 64 is outside the measured grid {4,8,16,32}",
    },
]


def mean(values):
    return statistics.fmean(values) if values else 0.0


def pstdev(values):
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def median(values):
    return statistics.median(values) if values else 0.0


def fnum(value):
    if isinstance(value, float):
        return f"{value:.10g}"
    return value


def write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fnum(row.get(k, "")) for k in fields})


def metric(run, name):
    metrics = run["metrics"]
    if name in metrics:
        return float(metrics[name])
    if name == "max_single_dst_queue_occupancy":
        return float(metrics.get("max_single_voq_occupancy", 0.0))
    return 0.0


def aggregate_cells(runs):
    groups = defaultdict(list)
    for run in runs:
        key = (
            run["queue"],
            int(run["capacity"]),
            float(run["load"]),
            run["length_mode"],
            run["traffic"],
        )
        groups[key].append(run)

    cells = {}
    for key, group in groups.items():
        values = {}
        for name in METRICS:
            samples = [metric(run, name) for run in group]
            values[name] = mean(samples)
            values[name + "_std"] = pstdev(samples)
        cells[key] = {
            "queue": key[0],
            "capacity": key[1],
            "load": key[2],
            "length_mode": key[3],
            "traffic": key[4],
            "seeds": len(group),
            "exact_all": all(bool(run["exact"]) for run in group),
            "mismatch_runs": sum(1 for run in group if not run["exact"]),
            **values,
        }
    return cells


def core_rows(cells):
    rows = [
        cells[key]
        for key in sorted(cells, key=lambda k: (k[0], k[1], k[2], k[3], k[4]))
        if key[3] == "uniform1-8" and key[4] == "uniform"
    ]
    return rows


def paired_strata(runs, seeds):
    by_key = {}
    for run in runs:
        key = (
            run["queue"],
            int(run["capacity"]),
            float(run["load"]),
            run["length_mode"],
            run["traffic"],
            int(run["seed"]),
        )
        by_key[key] = run

    strata_keys = sorted({
        (
            int(run["capacity"]),
            float(run["load"]),
            run["length_mode"],
            run["traffic"],
        )
        for run in runs
    })
    delta_metrics = [
        "utilization",
        "avg_pkt_latency",
        "p99_pkt_latency",
        "source_stall_rate",
        "hol_rate",
        "jain",
        "jain_dst",
        "max_single_dst_queue_occupancy",
    ]
    rows = []
    for left, right in PAIRS:
        for cap, load, length_mode, traffic in strata_keys:
            seed_deltas = defaultdict(list)
            seed_pairs = 0
            for seed in seeds:
                left_run = by_key.get((left, cap, load, length_mode, traffic, seed))
                right_run = by_key.get((right, cap, load, length_mode, traffic, seed))
                if left_run is None or right_run is None:
                    continue
                seed_pairs += 1
                for name in delta_metrics:
                    seed_deltas[name].append(
                        metric(left_run, name) - metric(right_run, name)
                    )
            if seed_pairs == 0:
                continue
            row = {
                "pair": f"{left}_vs_{right}",
                "left_queue": left,
                "right_queue": right,
                "capacity": cap,
                "load": load,
                "length_mode": length_mode,
                "traffic": traffic,
                "seed_pairs": seed_pairs,
            }
            for name in delta_metrics:
                samples = seed_deltas[name]
                row["delta_" + name + "_mean"] = mean(samples)
                row["delta_" + name + "_std"] = pstdev(samples)
                row["delta_" + name + "_min"] = min(samples)
                row["delta_" + name + "_max"] = max(samples)
                row["left_wins_" + name] = sum(1 for v in samples if v > 1e-12)
                row["right_wins_" + name] = sum(1 for v in samples if v < -1e-12)
            rows.append(row)
    return rows


def summarize_effect_rows(rows, label_key=None):
    util = [r["delta_utilization_mean"] for r in rows]
    lat = [r["delta_avg_pkt_latency_mean"] for r in rows]
    p99 = [r["delta_p99_pkt_latency_mean"] for r in rows]
    out = {
        "strata": len(rows),
        "seed_observations": sum(r["seed_pairs"] for r in rows),
        "left_util_better_strata": sum(1 for v in util if v > 1e-12),
        "right_util_better_strata": sum(1 for v in util if v < -1e-12),
        "util_tie_strata": sum(1 for v in util if abs(v) <= 1e-12),
        "delta_utilization_mean": mean(util),
        "delta_utilization_median": median(util),
        "delta_utilization_min": min(util) if util else 0.0,
        "delta_utilization_max": max(util) if util else 0.0,
        "delta_avg_pkt_latency_mean": mean(lat),
        "delta_p99_pkt_latency_mean": mean(p99),
        "left_lower_latency_strata": sum(1 for v in lat if v < -1e-12),
        "right_lower_latency_strata": sum(1 for v in lat if v > 1e-12),
        "left_latency_better_all_seeds": sum(
            1
            for r in rows
            if r["seed_pairs"] > 0
            and r["left_wins_avg_pkt_latency"] == 0
            and r["right_wins_avg_pkt_latency"] == r["seed_pairs"]
        ),
    }
    if label_key:
        out[label_key] = rows[0][label_key]
    return out


def effect_groups(strata):
    groups = []
    for pair in PAIRS:
        pair_rows = [r for r in strata if r["pair"] == f"{pair[0]}_vs_{pair[1]}"]
        if not pair_rows:
            continue
        overall = summarize_effect_rows(pair_rows)
        overall["pair"] = f"{pair[0]}_vs_{pair[1]}"
        overall["group_by"] = "overall"
        groups.append(overall)
        for dim in ("capacity", "load"):
            values = sorted({r[dim] for r in pair_rows})
            for value in values:
                subset = [r for r in pair_rows if r[dim] == value]
                row = summarize_effect_rows(subset)
                row["pair"] = f"{pair[0]}_vs_{pair[1]}"
                row["group_by"] = dim
                row[dim] = value
                groups.append(row)
    return groups


def get_cell(cells, queue, capacity, load, length_mode, traffic):
    return cells.get((queue, capacity, load, length_mode, traffic))


def equal_buffer_rows(cells, config):
    rows = []
    lengths = config["length_modes"]
    traffics = config["traffics"]
    loads = config["loads"]

    for fifo_cap in EQUAL_TOTAL_FIFO_CAPS:
        fourq_cap = fifo_cap // 2
        for right_queue in ("xp", "voq"):
            for load in loads:
                for length_mode in lengths:
                    for traffic in traffics:
                        fifo = get_cell(cells, "fifo", fifo_cap, load,
                                        length_mode, traffic)
                        right = get_cell(cells, right_queue, fourq_cap, load,
                                         length_mode, traffic)
                        if fifo is None or right is None:
                            continue
                        rows.append({
                            "comparison": f"fifo_vs_{right_queue}_equal_total",
                            "total_flits": 2 * fifo_cap,
                            "left_queue": "fifo",
                            "left_capacity": fifo_cap,
                            "right_queue": right_queue,
                            "right_capacity": fourq_cap,
                            "load": load,
                            "length_mode": length_mode,
                            "traffic": traffic,
                            "left_utilization": fifo["utilization"],
                            "right_utilization": right["utilization"],
                            "delta_utilization": right["utilization"] - fifo["utilization"],
                            "left_avg_pkt_latency": fifo["avg_pkt_latency"],
                            "right_avg_pkt_latency": right["avg_pkt_latency"],
                            "delta_avg_pkt_latency": (
                                right["avg_pkt_latency"] - fifo["avg_pkt_latency"]
                            ),
                            "left_p99_pkt_latency": fifo["p99_pkt_latency"],
                            "right_p99_pkt_latency": right["p99_pkt_latency"],
                            "delta_p99_pkt_latency": (
                                right["p99_pkt_latency"] - fifo["p99_pkt_latency"]
                            ),
                            "left_hol_rate": fifo["hol_rate"],
                            "right_hol_rate": right["hol_rate"],
                            "exact_all": fifo["exact_all"] and right["exact_all"],
                        })

    for cap in config["capacities"]:
        for load in loads:
            for length_mode in lengths:
                for traffic in traffics:
                    xp = get_cell(cells, "xp", cap, load, length_mode, traffic)
                    voq = get_cell(cells, "voq", cap, load, length_mode, traffic)
                    if xp is None or voq is None:
                        continue
                    rows.append({
                        "comparison": "xp_vs_voq_equal_queue",
                        "total_flits": 4 * cap,
                        "left_queue": "xp",
                        "left_capacity": cap,
                        "right_queue": "voq",
                        "right_capacity": cap,
                        "load": load,
                        "length_mode": length_mode,
                        "traffic": traffic,
                        "left_utilization": xp["utilization"],
                        "right_utilization": voq["utilization"],
                        "delta_utilization": voq["utilization"] - xp["utilization"],
                        "left_avg_pkt_latency": xp["avg_pkt_latency"],
                        "right_avg_pkt_latency": voq["avg_pkt_latency"],
                        "delta_avg_pkt_latency": (
                            voq["avg_pkt_latency"] - xp["avg_pkt_latency"]
                        ),
                        "left_p99_pkt_latency": xp["p99_pkt_latency"],
                        "right_p99_pkt_latency": voq["p99_pkt_latency"],
                        "delta_p99_pkt_latency": (
                            voq["p99_pkt_latency"] - xp["p99_pkt_latency"]
                        ),
                        "left_hol_rate": xp["hol_rate"],
                        "right_hol_rate": voq["hol_rate"],
                        "exact_all": xp["exact_all"] and voq["exact_all"],
                    })
    return rows


def equal_buffer_summary(rows):
    groups = defaultdict(list)
    for row in rows:
        key = (
            row["comparison"],
            row["total_flits"],
            row["left_queue"],
            row["left_capacity"],
            row["right_queue"],
            row["right_capacity"],
        )
        groups[key].append(row)
    out = []
    for key in sorted(groups):
        subset = groups[key]
        util = [r["delta_utilization"] for r in subset]
        lat = [r["delta_avg_pkt_latency"] for r in subset]
        out.append({
            "comparison": key[0],
            "total_flits": key[1],
            "left_queue": key[2],
            "left_capacity": key[3],
            "right_queue": key[4],
            "right_capacity": key[5],
            "strata": len(subset),
            "delta_utilization_mean": mean(util),
            "delta_utilization_min": min(util) if util else 0.0,
            "delta_utilization_max": max(util) if util else 0.0,
            "right_util_better_strata": sum(1 for v in util if v > 1e-12),
            "left_util_better_strata": sum(1 for v in util if v < -1e-12),
            "util_tie_strata": sum(1 for v in util if abs(v) <= 1e-12),
            "delta_avg_pkt_latency_mean": mean(lat),
            "right_lower_latency_strata": sum(1 for v in lat if v < -1e-12),
            "left_lower_latency_strata": sum(1 for v in lat if v > 1e-12),
            "exact_all": all(r["exact_all"] for r in subset),
        })
    return out


def equivalence_rows(runs, seeds):
    by_key = {}
    for run in runs:
        key = (
            run["queue"],
            int(run["capacity"]),
            float(run["load"]),
            run["length_mode"],
            run["traffic"],
            int(run["seed"]),
        )
        by_key[key] = run

    strata = sorted({
        (
            int(run["capacity"]),
            float(run["load"]),
            run["length_mode"],
            run["traffic"],
        )
        for run in runs
    })
    rows = []
    for cap, load, length_mode, traffic in strata:
        max_abs = {name: 0.0 for name in METRICS}
        identical_seeds = 0
        seed_pairs = 0
        for seed in seeds:
            xp = by_key.get(("xp", cap, load, length_mode, traffic, seed))
            voq = by_key.get(("voq", cap, load, length_mode, traffic, seed))
            if xp is None or voq is None:
                continue
            seed_pairs += 1
            all_equal = True
            for name in METRICS:
                delta = abs(metric(xp, name) - metric(voq, name))
                max_abs[name] = max(max_abs[name], delta)
                if delta != 0.0:
                    all_equal = False
            if all_equal:
                identical_seeds += 1
        row = {
            "capacity": cap,
            "load": load,
            "length_mode": length_mode,
            "traffic": traffic,
            "seed_pairs": seed_pairs,
            "identical_seeds": identical_seeds,
            "identical_all": identical_seeds == seed_pairs and seed_pairs > 0,
        }
        for name in METRICS:
            row["max_abs_delta_" + name] = max_abs[name]
        rows.append(row)
    return rows


def coverage(runs, cells, config, strata, equivalence):
    exact = sum(1 for run in runs if run["exact"])
    mismatch_detail = defaultdict(int)
    for run in runs:
        if not run["exact"]:
            if run.get("packet_errors"):
                mismatch_detail["packet_mismatch"] += 1
            if run.get("cycle_errors"):
                mismatch_detail["cycle_mismatch"] += 1
    planned = (
        len(config["queues"])
        * len(config["capacities"])
        * len(config["loads"])
        * len(config["length_modes"])
        * len(config["traffics"])
        * len(config["seeds"])
    )
    return {
        "planned_runs": planned,
        "completed_runs": len(runs),
        "exact_runs": exact,
        "mismatch_runs": len(runs) - exact,
        "mismatch_detail": dict(mismatch_detail),
        "cells": len(cells),
        "strata_per_pair": len(strata) // max(1, len(PAIRS)),
        "paired_strata_rows": len(strata),
        "xp_voq_equivalence_cells": len(equivalence),
        "xp_voq_identical_cells": sum(1 for r in equivalence if r["identical_all"]),
        "xp_voq_identical_seed_pairs": sum(r["identical_seeds"] for r in equivalence),
        "xp_voq_seed_pairs": sum(r["seed_pairs"] for r in equivalence),
    }


def build_summary(runs, config):
    cells = aggregate_cells(runs)
    core = core_rows(cells)
    strata = paired_strata(runs, config["seeds"])
    groups = effect_groups(strata)
    eq_rows = equal_buffer_rows(cells, config)
    eq_summary = equal_buffer_summary(eq_rows)
    equiv = equivalence_rows(runs, config["seeds"])
    overall = [
        row for row in groups
        if row["group_by"] == "overall"
    ]
    return {
        "experiment": "1-2x2-crossbar-fifo-vs-voq",
        "phase": 3,
        "config": config,
        "coverage": coverage(runs, cells, config, strata, equiv),
        "core_capacity": core,
        "matrix_cells": [
            cells[key] for key in sorted(
                cells, key=lambda k: (k[0], k[1], k[2], k[3], k[4])
            )
        ],
        "effects": {
            "overall": overall,
            "groups": groups,
            "strata": strata,
        },
        "equal_buffer": {
            "formula": (
                "FIFO total = 2*C_fifo; VOQ/XP total = 4*C_4q. "
                "Equal total uses C_4q = C_fifo/2."
            ),
            "xp_vs_voq_note": (
                "XP and VOQ are both 4-queue structures; equal per-queue depth "
                "is also equal total buffer."
            ),
            "uncovered": UNCOVERED_EQUAL_BUFFER,
            "summary": eq_summary,
            "rows": eq_rows,
        },
        "xp_voq_equivalence": {
            "note": (
                "XP-only and the current IQ-VOQ reference both expose four "
                "per-(src,dst) queues and one-outstanding-packet sources. "
                "This table checks whether their model metrics are identical "
                "for the same trace; the RTL check is separate."
            ),
            "cells": equiv,
        },
    }


def write_outputs(summary, outdir):
    os.makedirs(outdir, exist_ok=True)

    core_fields = [
        "queue", "capacity", "load", "length_mode", "traffic", "seeds",
        "exact_all", "mismatch_runs", "utilization", "utilization_std",
        "avg_pkt_latency", "avg_pkt_latency_std", "p99_pkt_latency",
        "p99_pkt_latency_std", "source_stall_rate", "hol_rate",
        "avg_queue_occupancy", "max_total_queue_occupancy",
        "max_input_queue_occupancy", "max_single_dst_queue_occupancy",
        "jain", "jain_dst", "output_idle_rate", "delivered_pkts",
        "delivered_flits", "trace_offered_flits",
    ]
    write_csv(os.path.join(outdir, "core_capacity.csv"),
              summary["core_capacity"], core_fields)
    write_csv(os.path.join(outdir, "matrix_cells.csv"),
              summary["matrix_cells"], core_fields)

    strata_fields = [
        "pair", "left_queue", "right_queue", "capacity", "load",
        "length_mode", "traffic", "seed_pairs",
    ]
    delta_metrics = [
        "utilization", "avg_pkt_latency", "p99_pkt_latency",
        "source_stall_rate", "hol_rate", "jain", "jain_dst",
        "max_single_dst_queue_occupancy",
    ]
    for name in delta_metrics:
        strata_fields += [
            f"delta_{name}_mean", f"delta_{name}_std",
            f"delta_{name}_min", f"delta_{name}_max",
            f"left_wins_{name}", f"right_wins_{name}",
        ]
    write_csv(os.path.join(outdir, "effect_strata.csv"),
              summary["effects"]["strata"], strata_fields)

    group_rows = summary["effects"]["groups"]
    group_fields = [
        "pair", "group_by", "capacity", "load", "strata",
        "seed_observations", "left_util_better_strata",
        "right_util_better_strata", "util_tie_strata",
        "delta_utilization_mean", "delta_utilization_median",
        "delta_utilization_min", "delta_utilization_max",
        "delta_avg_pkt_latency_mean", "delta_p99_pkt_latency_mean",
        "left_lower_latency_strata", "right_lower_latency_strata",
        "left_latency_better_all_seeds",
    ]
    write_csv(os.path.join(outdir, "effect_groups.csv"),
              group_rows, group_fields)

    eq_fields = [
        "comparison", "total_flits", "left_queue", "left_capacity",
        "right_queue", "right_capacity", "load", "length_mode", "traffic",
        "left_utilization", "right_utilization", "delta_utilization",
        "left_avg_pkt_latency", "right_avg_pkt_latency",
        "delta_avg_pkt_latency", "left_p99_pkt_latency",
        "right_p99_pkt_latency", "delta_p99_pkt_latency",
        "left_hol_rate", "right_hol_rate", "exact_all",
    ]
    write_csv(os.path.join(outdir, "equal_buffer.csv"),
              summary["equal_buffer"]["rows"], eq_fields)

    equiv = summary["xp_voq_equivalence"]["cells"]
    equiv_fields = [
        "capacity", "load", "length_mode", "traffic", "seed_pairs",
        "identical_seeds", "identical_all",
    ] + ["max_abs_delta_" + name for name in METRICS]
    write_csv(os.path.join(outdir, "xp_voq_equivalence.csv"),
              equiv, equiv_fields)

    with open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def core_table(summary):
    lines = [
        "| queue | cap | load | util | avg lat | p99 lat | stall | HOL | "
        "max occ | Jain | exact |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in summary["core_capacity"]:
        lines.append(
            f"| {row['queue']} | {row['capacity']} | {row['load']:g} | "
            f"{row['utilization']:.4f} | {row['avg_pkt_latency']:.2f} | "
            f"{row['p99_pkt_latency']:.1f} | {row['source_stall_rate']:.4f} | "
            f"{row['hol_rate']:.4f} | {row['max_total_queue_occupancy']:.1f} | "
            f"{row['jain']:.4f} | {'yes' if row['exact_all'] else 'NO'} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="analyze Phase 3 raw runs")
    parser.add_argument("--runs", required=True,
                        help="raw_runs.json from run_phase3.py")
    parser.add_argument("--outdir", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "results", "phase3"))
    args = parser.parse_args()

    with open(args.runs, encoding="utf-8") as f:
        payload = json.load(f)
    summary = build_summary(payload["runs"], payload["config"])
    write_outputs(summary, args.outdir)
    print(core_table(summary))
    print()
    print(json.dumps(summary["coverage"], ensure_ascii=False, indent=2))
    return 0 if summary["coverage"]["mismatch_runs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
