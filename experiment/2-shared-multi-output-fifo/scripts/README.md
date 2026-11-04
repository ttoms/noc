# E1 scripts

- `model_e1.py` — cycle model: 2x2, two per-input 1W/2R shared FIFOs,
  VC-linked cell pools, output locks, per-cycle invariants.
- `run_e1.py` — matrix runner; generates base traces with Experiment 1's
  `gen_trace.py`, derives VC traces, runs shared + VOQ, writes `raw_runs.json`.
- `derive_vc_trace.py` — add `vc` to an Experiment 1 trace without changing
  packet timing (`per_dst` or `multi`).
- `analyze_e1.py` — 5-seed means and paired 95% t CIs; writes `summary.csv` and
  `paired.csv`.
- `test_model_e1.py` — directed + randomized tests (single/multi-flit, pool full,
  dual read, VC HOL, output backpressure, invariants).
- `render_e1_figure.py` — renders `docs/figures/e1-2x2-topology.png`.

Quick check:

```bash
python3 scripts/test_model_e1.py
```
