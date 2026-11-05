#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare E1 model packet CSV with E2 RTL packet CSV."""
from __future__ import annotations

import argparse
import csv
import statistics


def load(path):
    return {int(r["seq"]): r for r in csv.DictReader(open(path, encoding="utf-8"))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("rtl")
    args = ap.parse_args()
    m = load(args.model)
    r = load(args.rtl)
    common = set(m) & set(r)
    print(f"model={len(m)} rtl={len(r)} common={len(common)}")
    print(f"rtl_only={len(set(r) - set(m))} model_only={len(set(m) - set(r))}")
    for key in ("start", "end"):
        ds = [int(r[s][key]) - int(m[s][key]) for s in common]
        if ds:
            print(
                f"{key}_delta mean={statistics.mean(ds):+.2f} "
                f"min={min(ds):+d} max={max(ds):+d} "
                f"stdev={statistics.pstdev(ds):.2f}"
            )
    bad_port = [s for s, x in r.items() if int(x["port"]) != int(x["dst"])]
    print(f"rtl_port_mismatch={len(bad_port)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
