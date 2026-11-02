#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate directed packet traces for model/RTL cycle-level co-simulation.

Each case is written twice: ``<name>.jsonl`` for model_v2.py and
``<name>.csv`` for tb/xbar_2x2_fifo_tb.sv.  Both contain the same packets.

Packet order inside a trace is (arrival, seq), which is what both readers
sort by per source.  All packets are listed even when several share arrival
0; the one-outstanding source serialises them.
"""

from __future__ import annotations

import argparse
import json
import os


def pkt(seq: int, src: int, dst: int, length: int, arrival: int) -> dict:
    return {"seq": seq, "src": src, "dst": dst, "len": length, "arrival": arrival}


def build_cases() -> dict[str, list[dict]]:
    cases: dict[str, list[dict]] = {}

    # All four src/dst combinations, min and max packet length.
    for src in (0, 1):
        for dst in (0, 1):
            for length in (1, 8):
                name = f"single_s{src}_d{dst}_l{length}"
                cases[name] = [pkt(0, src, dst, length, 0)]
    cases["single_late_s0_d1_l5_a10"] = [pkt(0, 0, 1, 5, 10)]

    # Independent grants: both outputs busy with different inputs.
    cases["cross_s0d0_l3_s1d1_l5"] = [
        pkt(0, 0, 0, 3, 0),
        pkt(1, 1, 1, 5, 0),
    ]
    cases["cross_s0d1_l4_s1d0_l2_a3"] = [
        pkt(0, 0, 1, 4, 3),
        pkt(1, 1, 0, 2, 3),
    ]

    # Same-destination contention, output 0 and output 1, all length pairs.
    for dst in (0, 1):
        for len0, len1 in ((1, 1), (8, 1), (1, 8), (8, 8)):
            name = f"conflict_d{dst}_l{len0}_l{len1}"
            cases[name] = [
                pkt(0, 0, dst, len0, 0),
                pkt(1, 1, dst, len1, 0),
            ]

    # Staggered arrivals: the second packet is already queued while the first
    # packet starts, exercising the RR pointer and lock release.
    for gap in (1, 2, 7):
        cases[f"conflict_d0_l8_l8_gap{gap}"] = [
            pkt(0, 0, 0, 8, 0),
            pkt(1, 1, 0, 8, gap),
        ]

    # Fill both input FIFOs (DEPTH=32) with max-length packets to one output.
    # Aggregate input is 2 flit/cycle against one drain port, so both FIFOs
    # reach full and the sources stall; no flit may be dropped.
    cases["full_d0_l8_x12"] = [
        pkt(i, 0, 0, 8, 0) for i in range(12)
    ] + [
        pkt(12 + i, 1, 0, 8, 0) for i in range(12)
    ]

    # Same, with mixed packet lengths so partial writes, full stalls and
    # packet boundaries interleave.
    mixed: list[dict] = []
    seq = 0
    for src in (0, 1):
        for i in range(18):
            mixed.append(pkt(seq, src, 0, 1 + (i % 8), 0))
            seq += 1
    cases["full_d0_mixed"] = mixed

    # Alternating destinations from one input (HOL), with the other input
    # competing for output 0.
    alt: list[dict] = []
    seq = 0
    for i in range(10):
        alt.append(pkt(seq, 0, i % 2, 2 + (i % 3), 0))
        seq += 1
    for i in range(6):
        alt.append(pkt(seq, 1, 0, 1 + (i % 8), 0))
        seq += 1
    cases["hol_alt_s0"] = alt

    # Back-to-back trace arrivals on one input: arrivals are much closer than
    # the one-outstanding source can drain, so the source serialises them.
    burst: list[dict] = []
    seq = 0
    for i in range(10):
        burst.append(pkt(seq, 0, i % 2, 1 + (i % 8), i))
        seq += 1
    cases["burst_s0_arrivals"] = burst

    # Round-robin stress: single-flit packets, both inputs always aimed at
    # output 0.  Every grant should advance the output-0 pointer.
    rr: list[dict] = []
    seq = 0
    for i in range(16):
        rr.append(pkt(seq, i % 2, 0, 1, 0))
        seq += 1
    cases["rr_d0_l1_x16"] = rr

    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="generate directed crossbar traces")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--cycles", type=int, default=1200)
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    cases = build_cases()
    manifest = []
    for name, rows in sorted(cases.items()):
        rows = sorted(rows, key=lambda r: (r["arrival"], r["seq"]))
        jsonl_path = os.path.join(args.outdir, name + ".jsonl")
        csv_path = os.path.join(args.outdir, name + ".csv")
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("seq,src,dst,len,arrival\n")
            for row in rows:
                f.write(
                    f"{row['seq']},{row['src']},{row['dst']},"
                    f"{row['len']},{row['arrival']}\n"
                )
        manifest.append(
            {
                "name": name,
                "packets": len(rows),
                "flits": sum(r["len"] for r in rows),
                "max_arrival": max(r["arrival"] for r in rows),
                "cycles": args.cycles,
            }
        )
    with open(os.path.join(args.outdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"wrote {len(manifest)} cases to {args.outdir} (cycles={args.cycles})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
