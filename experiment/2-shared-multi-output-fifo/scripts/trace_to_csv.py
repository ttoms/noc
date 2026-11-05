#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert the E1 JSONL trace (with vc) to the flat CSV used by the RTL TB."""
from __future__ import annotations

import argparse
import csv
import json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arrival-offset", type=int, default=0)
    args = ap.parse_args()
    rows = []
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rows.append(
                (
                    int(r["seq"]),
                    int(r["src"]),
                    int(r["dst"]),
                    int(r["len"]),
                    int(r["arrival"]) + args.arrival_offset,
                    int(r.get("vc", 0)),
                )
            )
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["seq", "src", "dst", "len", "arrival", "vc"])
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
