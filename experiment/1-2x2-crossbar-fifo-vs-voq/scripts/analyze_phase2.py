#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aggregate Phase 2 raw runs into summary JSON and plotting CSVs.

Input is `raw_runs.json` produced by run_matrix.py.  The script writes:

  results/phase2/core_capacity.csv   capacity x load x queue type
  results/phase2/matrix_cells.csv    every (type, cap, load, len, traffic)
  results/phase2/effect_strata.csv   FIFO vs VOQ delta for all 192 strata
  results/phase2/effect_groups.csv   effect summarized per variable level
  results/phase2/equal_buffer.csv    FIFO 2xC vs VOQ 4x(C/2), common points
  results/phase2/summary.json        machine-readable summary

No raw per-cycle or per-packet CSV is stored here; those are compared exactly
inside run_matrix.py and discarded after the comparison.
"""

from __future__ import annotations

import argparse
import csv
import json
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
    "max_single_voq_occupancy",
    "jain",
    "jain_dst",
    "output_idle_rate",
    "delivered_pkts",
    "delivered_flits",
    "trace_offered_flits",
]

# FIFO per-queue C is compared with VOQ per-queue C/2, so both have 2*C flits.
EQUAL_BUFFER_PAIRS = [(8, 4), (16, 8), (32, 16)]

UNCOVERED_EQUAL_BUFFER = [
    {
        "fifo_capacity": 4,
        "voq_capacity": 2,
        "total_flits": 8,
        "reason": "VOQ capacity 2 is outside the measured grid {4,8,16,32}",
    },
    {
        "fifo_capacity": 64,
        "voq_capacity": 32,
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
        return f"{value:.8g}"
    return value


def write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fnum(row.get(k, "")) for k in fields})


def run_metrics(run):
    return run["metrics"]


def aggregate_cells(runs):
    """Group by (queue, capacity, load, length, traffic) and average seeds."""
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
        metrics = {}
        for name in METRICS:
            values = [float(run_metrics(r)[name]) for r in group]
            metrics[name] = mean(values)
            metrics[name + "_std"] = pstdev(values)
        cells[key] = {
            "queue": key[0],
            "capacity": key[1],
            "load": key[2],
            "length_mode": key[3],
            "traffic": key[4],
            "seeds": len(group),
            "exact_all": all(bool(r["exact"]) for r in group),
            "mismatch_runs": sum(1 for r in group if not r["exact"]),
            **metrics,
        }
    return cells


def core_rows(cells):
    rows = []
    for key in sorted(
        cells,
        key=lambda k: (k[0], k[1], k[2], k[3], k[4]),
    ):
        queue, cap, load, length, traffic = key
        if length != "uniform1-8" or traffic != "uniform":
            continue
        cell = cells[key]
        rows.append(cell)
    return rows


def paired_strata(runs, seeds):
    """FIFO vs VOQ deltas for every (cap, load, length, traffic) stratum."""
    by_key_seed = {}
    for run in runs:
        key = (
            int(run["capacity"]),
            float(run["load"]),
            run["length_mode"],
            run["traffic"],
            int(run["seed"]),
        )
        by_key_seed[(run["queue"],) + key] = run

    deltas = [
        "utilization",
        "avg_pkt_latency",
        "p99_pkt_latency",
        "source_stall_rate",
        "hol_rate",
        "jain",
        "jain_dst",
    ]
    strata = []
    strata_seeds = sorted({
        (
            int(r["capacity"]),
            float(r["load"]),
            r["length_mode"],
            r["traffic"],
        )
        for r in runs
    })
    for cap, load, length, traffic in strata_seeds:
        seed_deltas = defaultdict(list)
        seed_pairs = 0
        for seed in seeds:
            fifo = by_key_seed.get(("fifo", cap, load, length, traffic, seed))
            voq = by_key_seed.get(("voq", cap, load, length, traffic, seed))
            if fifo is None or voq is None:
                continue
            seed_pairs += 1
            for name in deltas:
                seed_deltas[name].append(
                    float(run_metrics(voq)[name]) - float(run_metrics(fifo)[name])
                )
        row = {
            "capacity": cap,
            "load": load,
            "length_mode": length,
            "traffic": traffic,
            "seed_pairs": seed_pairs,
        }
        for name in deltas:
            values = seed_deltas[name]
            row["delta_" + name + "_mean"] = mean(values)
            row["delta_" + name + "_std"] = pstdev(values)
            row["delta_" + name + "_min"] = min(values) if values else 0.0
            row["delta_" + name + "_max"] = max(values) if values else 0.0
            row["voq_wins_" + name] = sum(1 for v in values if v > 1e-9)
            row["fifo_wins_" + name] = sum(1 for v in values if v < -1e-9)
        strata.append(row)
    return strata


def summarize_effect_rows(rows, label_key=None):
    """Summarize utility deltas over a set of strata rows."""
    util = [r["delta_utilization_mean"] for r in rows]
    lat = [r["delta_avg_pkt_latency_mean"] for r in rows]
    p99 = [r["delta_p99_pkt_latency_mean"] for r in rows]
    out = {
        "strata": len(rows),
        "seed_observations": sum(r["seed_pairs"] for r in rows),
        "voq_util_better_strata": sum(1 for v in util if v > 1e-9),
        "fifo_util_better_strata": sum(1 for v in util if v < -1e-9),
        "util_tie_strata": sum(1 for v in util if abs(v) <= 1e-9),
        "delta_utilization_mean": mean(util),
        "delta_utilization_median": median(util),
        "delta_utilization_min": min(util) if util else 0.0,
        "delta_utilization_max": max(util) if util else 0.0,
        "delta_avg_pkt_latency_mean": mean(lat),
        "delta_p99_pkt_latency_mean": mean(p99),
        "voq_lower_latency_strata": sum(1 for v in lat if v < -1e-9),
        "fifo_lower_latency_strata": sum(1 for v in lat if v > 1e-9),
        # A stricter count: VOQ better in all measured seeds of that stratum.
        "strata_voq_util_better_all_seeds": sum(
            1
            for r in rows
            if r["seed_pairs"] > 0
            and r["voq_wins_utilization"] == r["seed_pairs"]
        ),
    }
    if label_key:
        out[label_key] = rows[0][label_key]
    return out


def effect_groups(strata):
    groups = []
    for dim in ("capacity", "load", "length_mode", "traffic"):
        values = sorted({r[dim] for r in strata})
        for value in values:
            subset = [r for r in strata if r[dim] == value]
            groups.append(summarize_effect_rows(subset, dim))
    return groups


def equal_buffer_rows(cells):
    rows = []
    for fifo_cap, voq_cap in EQUAL_BUFFER_PAIRS:
        keys = sorted(
            {
                (cell["load"], cell["length_mode"], cell["traffic"])
                for cell in cells.values()
                if cell["queue"] == "fifo" and cell["capacity"] == fifo_cap
            }
        )
        for load, length, traffic in keys:
            fifo = cells.get(("fifo", fifo_cap, load, length, traffic))
            voq = cells.get(("voq", voq_cap, load, length, traffic))
            if fifo is None or voq is None:
                continue
            row = {
                "total_flits": 2 * fifo_cap,
                "fifo_capacity": fifo_cap,
                "voq_capacity": voq_cap,
                "load": load,
                "length_mode": length,
                "traffic": traffic,
                "fifo_utilization": fifo["utilization"],
                "voq_utilization": voq["utilization"],
                "delta_utilization": voq["utilization"] - fifo["utilization"],
                "fifo_avg_pkt_latency": fifo["avg_pkt_latency"],
                "voq_avg_pkt_latency": voq["avg_pkt_latency"],
                "delta_avg_pkt_latency": (
                    voq["avg_pkt_latency"] - fifo["avg_pkt_latency"]
                ),
                "fifo_p99_pkt_latency": fifo["p99_pkt_latency"],
                "voq_p99_pkt_latency": voq["p99_pkt_latency"],
                "delta_p99_pkt_latency": (
                    voq["p99_pkt_latency"] - fifo["p99_pkt_latency"]
                ),
                "fifo_source_stall_rate": fifo["source_stall_rate"],
                "voq_source_stall_rate": voq["source_stall_rate"],
                "fifo_hol_rate": fifo["hol_rate"],
                "voq_hol_rate": voq["hol_rate"],
                "fifo_max_total_queue_occupancy": fifo[
                    "max_total_queue_occupancy"
                ],
                "voq_max_total_queue_occupancy": voq[
                    "max_total_queue_occupancy"
                ],
                "exact_all": fifo["exact_all"] and voq["exact_all"],
            }
            rows.append(row)
    return rows


def equal_buffer_summary(rows):
    out = []
    for fifo_cap, voq_cap in EQUAL_BUFFER_PAIRS:
        subset = [
            r
            for r in rows
            if r["fifo_capacity"] == fifo_cap and r["voq_capacity"] == voq_cap
        ]
        util = [r["delta_utilization"] for r in subset]
        lat = [r["delta_avg_pkt_latency"] for r in subset]
        out.append(
            {
                "total_flits": 2 * fifo_cap,
                "fifo_capacity": fifo_cap,
                "voq_capacity": voq_cap,
                "strata": len(subset),
                "delta_utilization_mean": mean(util),
                "delta_utilization_min": min(util) if util else 0.0,
                "delta_utilization_max": max(util) if util else 0.0,
                "voq_util_better_strata": sum(1 for v in util if v > 1e-9),
                "fifo_util_better_strata": sum(1 for v in util if v < -1e-9),
                "delta_avg_pkt_latency_mean": mean(lat),
                "voq_lower_latency_strata": sum(1 for v in lat if v < -1e-9),
                "fifo_lower_latency_strata": sum(1 for v in lat if v > 1e-9),
            }
        )
    return out


def coverage(runs, cells, config):
    exact = sum(1 for r in runs if r["exact"])
    by_status = defaultdict(int)
    for run in runs:
        if not run["exact"]:
            if run.get("packet_errors"):
                by_status["packet_mismatch"] += 1
            if run.get("cycle_errors"):
                by_status["cycle_mismatch"] += 1
    return {
        "planned_runs": (
            len(config["queues"])
            * len(config["capacities"])
            * len(config["loads"])
            * len(config["length_modes"])
            * len(config["traffics"])
            * len(config["seeds"])
        ),
        "completed_runs": len(runs),
        "exact_runs": exact,
        "mismatch_runs": len(runs) - exact,
        "mismatch_detail": dict(by_status),
        "cells": len(cells),
        "core_cells": len(
            [
                c
                for c in cells.values()
                if c["length_mode"] == "uniform1-8" and c["traffic"] == "uniform"
            ]
        ),
    }


def build_summary(runs, config):
    cells = aggregate_cells(runs)
    core = core_rows(cells)
    strata = paired_strata(runs, config["seeds"])
    groups = effect_groups(strata)
    eq_rows = equal_buffer_rows(cells)
    eq_summary = equal_buffer_summary(eq_rows)

    matrix_rows = [
        cells[key] for key in sorted(cells, key=lambda k: (k[0], k[1], k[2], k[3], k[4]))
    ]
    summary = {
        "experiment": "1-2x2-crossbar-fifo-vs-voq",
        "phase": 2,
        "config": config,
        "coverage": coverage(runs, cells, config),
        "core_capacity": core,
        "matrix_cells": matrix_rows,
        "effects": {
            "overall": summarize_effect_rows(strata),
            "by_capacity": [g for g in groups if "capacity" in g],
            "by_load": [g for g in groups if "load" in g],
            "by_length_mode": [g for g in groups if "length_mode" in g],
            "by_traffic": [g for g in groups if "traffic" in g],
            "strata": strata,
        },
        "equal_buffer": {
            "formula": "FIFO total = 2*C, VOQ total = 4*(C/2) = 2*C",
            "pairs": [
                {"fifo_capacity": f, "voq_capacity": v, "total_flits": 2 * f}
                for f, v in EQUAL_BUFFER_PAIRS
            ],
            "uncovered": UNCOVERED_EQUAL_BUFFER,
            "by_pair": eq_summary,
            "rows": eq_rows,
        },
    }
    return summary


def write_outputs(summary, outdir):
    os.makedirs(outdir, exist_ok=True)

    core_fields = [
        "queue", "capacity", "load", "length_mode", "traffic", "seeds",
        "exact_all", "mismatch_runs", "utilization", "utilization_std",
        "avg_pkt_latency", "avg_pkt_latency_std", "p99_pkt_latency",
        "p99_pkt_latency_std", "source_stall_rate", "hol_rate",
        "avg_queue_occupancy", "max_total_queue_occupancy",
        "max_input_queue_occupancy", "max_single_voq_occupancy",
        "jain", "jain_dst", "output_idle_rate",
    ]
    write_csv(os.path.join(outdir, "core_capacity.csv"),
              summary["core_capacity"], core_fields)

    matrix_fields = core_fields + [
        "delivered_pkts", "delivered_flits", "trace_offered_flits",
    ]
    write_csv(os.path.join(outdir, "matrix_cells.csv"),
              summary["matrix_cells"], matrix_fields)

    strata = summary["effects"]["strata"]
    strata_fields = ["capacity", "load", "length_mode", "traffic", "seed_pairs"]
    for name in (
        "utilization", "avg_pkt_latency", "p99_pkt_latency",
        "source_stall_rate", "hol_rate", "jain", "jain_dst",
    ):
        strata_fields += [
            f"delta_{name}_mean", f"delta_{name}_std",
            f"delta_{name}_min", f"delta_{name}_max",
            f"voq_wins_{name}", f"fifo_wins_{name}",
        ]
    write_csv(os.path.join(outdir, "effect_strata.csv"), strata, strata_fields)

    group_rows = []
    for key in ("by_capacity", "by_load", "by_length_mode", "by_traffic"):
        for row in summary["effects"][key]:
            group_rows.append({"group_by": key, **row})
    group_fields = [
        "group_by", "capacity", "load", "length_mode", "traffic", "strata",
        "seed_observations", "voq_util_better_strata", "fifo_util_better_strata",
        "util_tie_strata", "delta_utilization_mean", "delta_utilization_median",
        "delta_utilization_min", "delta_utilization_max",
        "delta_avg_pkt_latency_mean", "delta_p99_pkt_latency_mean",
        "voq_lower_latency_strata", "fifo_lower_latency_strata",
        "strata_voq_util_better_all_seeds",
    ]
    write_csv(os.path.join(outdir, "effect_groups.csv"), group_rows, group_fields)

    eq_fields = [
        "total_flits", "fifo_capacity", "voq_capacity", "load", "length_mode",
        "traffic", "fifo_utilization", "voq_utilization", "delta_utilization",
        "fifo_avg_pkt_latency", "voq_avg_pkt_latency", "delta_avg_pkt_latency",
        "fifo_p99_pkt_latency", "voq_p99_pkt_latency", "delta_p99_pkt_latency",
        "fifo_source_stall_rate", "voq_source_stall_rate",
        "fifo_hol_rate", "voq_hol_rate",
        "fifo_max_total_queue_occupancy", "voq_max_total_queue_occupancy",
        "exact_all",
    ]
    write_csv(os.path.join(outdir, "equal_buffer.csv"),
              summary["equal_buffer"]["rows"], eq_fields)

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
    parser = argparse.ArgumentParser(description="analyze Phase 2 raw runs")
    parser.add_argument("--runs", required=True, help="raw_runs.json from run_matrix.py")
    parser.add_argument("--outdir", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "phase2"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    with open(args.runs, encoding="utf-8") as f:
        payload = json.load(f)
    runs = payload["runs"]
    config = payload["config"]
    summary = build_summary(runs, config)
    write_outputs(summary, args.outdir)
    if not args.quiet:
        print(core_table(summary))
        print()
        overall = summary["effects"]["overall"]
        print(
            "effect strata={strata} seed_obs={seed_observations} "
            "voq_util_better={voq_util_better_strata} "
            "fifo_util_better={fifo_util_better_strata} "
            "tie={util_tie_strata} mean_delta_util={delta_utilization_mean:.4f}".format(
                **overall
            )
        )
        for row in summary["equal_buffer"]["by_pair"]:
            print(
                f"equal-buffer total={row['total_flits']} "
                f"fifo{row['fifo_capacity']} vs voq{row['voq_capacity']}: "
                f"mean_delta_util={row['delta_utilization_mean']:.4f}, "
                f"voq_better={row['voq_util_better_strata']}/{row['strata']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
