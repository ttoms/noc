# Phase 3 results

Phase 3 adds the XP-only per-crosspoint FIFO and compares it with IQ-FIFO and
IQ-VOQ on the same traces and arbitration policy.  All metrics come from the
Python cycle model; every run is checked exactly against RTL before its record
is accepted.

## Files

- `raw_runs.json` — one compact record per run (configuration, exact-match
  status, model metrics). No per-packet or per-cycle CSV is stored.
- `core_capacity.csv` — queue type x capacity x load, averaged over 3 seeds.
- `matrix_cells.csv` — all 48 measured cells.
- `effect_strata.csv` — paired deltas for XP/FIFO, VOQ/FIFO, XP/VOQ at every
  capacity x load stratum (16 per pair).
- `effect_groups.csv` — deltas grouped by capacity and load.
- `equal_buffer.csv` — equal-total-buffer rows (FIFO 8/16/32 vs XP/VOQ
  4/8/16) and XP-vs-VOQ equal-per-queue rows.
- `xp_voq_equivalence.csv` — per-cell model-metric equality check for XP and
  VOQ.
- `xp_voq_rtl_equivalence.json` — RTL-vs-RTL packet/cycle CSV equality check
  from `scripts/compare_xp_voq.py`.
- `summary.json` — machine-readable aggregate used by the report.

## Core matrix

- queue type: `fifo` / `voq` / `xp`
- capacity per queue: 4 / 8 / 16 / 32 flits
- load: 0.5 / 0.8 / 0.95 / 1.0
- packet length: `uniform1-8`
- traffic: `uniform`
- seeds: 1 / 2 / 3

`3 x 4 x 4 x 3 = 144` runs; 144/144 exact, 0 mismatches, 48 cells.

## Capacity accounting

- FIFO total = `2 * C_fifo`
- VOQ / XP total = `4 * C_4q`
- Equal total buffer uses `C_4q = C_fifo / 2`:
  FIFO 8/16/32 vs VOQ/XP 4/8/16 (total 16/32/64 flits).
- XP and VOQ are both 4-queue structures, so equal per-queue depth is also
  equal total buffer.

The common equal-total grid does not include FIFO 4 vs 4-queue 2 (total 8) or
FIFO 64 vs 4-queue 32 (total 128); see `summary.json`
`equal_buffer.uncovered`.

## Exactness

Every run is compared with `scripts/run_cosim.py`:

- delivered packets: per output port, completion order, `(src, len, start, end)`
- every cycle debug row: occupancy, head, source write/stall, grant, lock

No tolerance is used.  `raw_runs.json` keeps the exact flag and first mismatch
messages for every run.  `xp_voq_rtl_equivalence.json` additionally compares
the XP and VOQ RTL CSVs directly on the directed and random traces:

- 31 traces x depth 4/8/16/32 = 124 RTL pair checks
- XP exact vs model: 124/124
- VOQ exact vs model: 124/124
- XP packets CSV == VOQ packets CSV: 124/124
- XP cycles CSV == VOQ cycles CSV: 124/124

The 16/16 model cells and 48/48 seed pairs are also metric-identical in
`xp_voq_equivalence.csv` (all max absolute deltas are zero).

## Reproduction

From the experiment directory:

```bash
python3 scripts/run_phase3.py --workdir ~/Temp/phase3 --outdir results/phase3
python3 scripts/compare_xp_voq.py --traces-dir ~/Temp/phase3_directed \
  --depths 4,8,16,32 --cycles 2200 --workdir ~/Temp/phase3_equiv \
  --out results/phase3/xp_voq_rtl_equivalence.json
```

Smoke test on a reduced grid:

```bash
python3 scripts/run_phase3.py \
  --queues fifo,voq,xp --capacities 4 --loads 0.8 --seeds 1 \
  --cycles 600 --warmup 100 \
  --workdir ~/Temp/phase3_smoke --outdir ~/Temp/phase3_smoke_results
```
