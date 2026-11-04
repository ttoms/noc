#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Directed and randomized tests for the E1 shared-FIFO cycle model."""

from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))

from model_e1 import run  # noqa: E402


def write_trace(path: Path, rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: (r["arrival"], r["seq"]))
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_single_flit(tmp: Path) -> None:
    p = tmp / "single.jsonl"
    write_trace(p, [{"seq": 0, "src": 0, "dst": 0, "len": 1, "arrival": 0, "vc": 0}])
    r = run(str(p), 8, 2, "per_dst", 20, 0, check_every=1)
    assert r["delivered_pkts"] == 1, r
    assert r["delivered_flits"] == 1, r
    assert r["avg_admit_latency"] == 0.0, r


def test_multi_flit(tmp: Path) -> None:
    p = tmp / "multi.jsonl"
    write_trace(p, [{"seq": 0, "src": 0, "dst": 0, "len": 8, "arrival": 0, "vc": 0}])
    r = run(str(p), 8, 2, "per_dst", 30, 0, check_every=1)
    assert r["delivered_pkts"] == 1, r
    assert r["delivered_flits"] == 8, r
    assert r["avg_admit_latency"] == 7.0, r


def test_pool_full(tmp: Path) -> None:
    p = tmp / "full.jsonl"
    rows = [
        {"seq": i, "src": 0, "dst": 0, "len": 1, "arrival": i, "vc": 0}
        for i in range(20)
    ]
    write_trace(p, rows)
    r = run(
        str(p), 4, 2, "per_dst", 30, 0,
        rdy_period=100, rdy_high=0, check_every=1,
    )
    assert r["accepted_flits"] == 4, r
    assert r["delivered_flits"] == 0, r
    assert r["max_pool_occupancy"] == 4, r


def test_dual_read(tmp: Path) -> None:
    p = tmp / "dual.jsonl"
    rows = [
        {"seq": 0, "src": 0, "dst": 0, "len": 8, "arrival": 0, "vc": 0},
        {"seq": 1, "src": 0, "dst": 1, "len": 8, "arrival": 1, "vc": 1},
        {"seq": 2, "src": 0, "dst": 0, "len": 8, "arrival": 2, "vc": 0},
        {"seq": 3, "src": 0, "dst": 1, "len": 8, "arrival": 3, "vc": 1},
    ]
    write_trace(p, rows)
    r = run(
        str(p), 16, 2, "per_dst", 80, 0,
        rdy_period=8, rdy_high=6, check_every=1,
    )
    assert r["delivered_pkts"] == 4, r
    assert r["dual_read_cycles"] > 0, r


def test_vc_hol(tmp: Path) -> None:
    p = tmp / "hol.jsonl"
    rows = [
        {"seq": 0, "src": 0, "dst": 0, "len": 8, "arrival": 0, "vc": 0},
        {"seq": 1, "src": 0, "dst": 1, "len": 1, "arrival": 0, "vc": 0},
    ]
    write_trace(p, rows)
    r = run(
        str(p), 16, 1, "multi", 80, 0,
        rdy_period=16, rdy_high=4, check_every=1,
    )
    assert r["delivered_pkts"] == 2, r
    assert r["vc_hol_cycles"] > 0, r


def test_random_invariants(tmp: Path) -> None:
    rng = random.Random(7)
    rows = [
        {
            "seq": i,
            "src": rng.randrange(2),
            "dst": rng.randrange(2),
            "len": rng.randint(1, 8),
            "arrival": rng.randrange(400),
            "vc": rng.randrange(2),
        }
        for i in range(400)
    ]
    p = tmp / "random.jsonl"
    write_trace(p, rows)
    for mode in ("per_dst", "multi"):
        for scf in (False, True):
            r = run(
                str(p), 16, 2, mode, 600, 50,
                rdy_period=8, rdy_high=5,
                same_cycle_free=scf, check_every=1,
            )
            assert r["invariant_checks"] == 601, r
            assert r["delivered_pkts"] > 0, r


def test_backpressure(tmp: Path) -> None:
    p = tmp / "bp.jsonl"
    rows = [
        {
            "seq": i,
            "src": i % 2,
            "dst": i % 2,
            "len": 4,
            "arrival": i * 2,
            "vc": i % 2,
        }
        for i in range(50)
    ]
    write_trace(p, rows)
    r = run(
        str(p), 16, 2, "per_dst", 300, 20,
        rdy_period=8, rdy_high=6, check_every=1,
    )
    assert r["delivered_flits"] > 0, r
    assert r["output_backpressure_cycles"] > 0, r


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="e1_model_test_") as td:
        tmp = Path(td)
        test_single_flit(tmp)
        test_multi_flit(tmp)
        test_pool_full(tmp)
        test_dual_read(tmp)
        test_vc_hol(tmp)
        test_random_invariants(tmp)
        test_backpressure(tmp)
    print("PASS: E1 model directed + randomized tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
