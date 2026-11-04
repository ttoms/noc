# E1 results

- `raw_runs.json` — 135 runs: 45 VOQ + 45 shared `per_dst` + 45 shared `multi2`.
  - 5 seeds, capacities 16/32/64, loads 0.8/0.95/1.0, uniform1-8, uniform traffic.
- `summary.csv` — per-architecture/capacity/load means and 95% t CIs.
- `paired.csv` — paired deltas (shared − VOQ, per_dst − multi2).

Extensions live in sibling directories:

- `../e1_multi4/` — VC_NUM=4, loads 0.95/1.0.
- `../e1_scf/` — same-cycle alloc/free, per_dst, loads 0.95/1.0.
- `../e1_backpressure/` — 75% output ready, cap32/load1.0.
- `../e1_hotspot/` — 80% traffic to output 0, cap32/load0.95.

Report: [`../../reports/e1_shared_fifo.md`](../../reports/e1_shared_fifo.md).
