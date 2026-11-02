# Phase 2 results

Phase 2 turns per-queue capacity into an orthogonal variable and sweeps the
full factorial matrix.  All metrics below come from the same Python cycle
model that is compared exactly against RTL for every run.

## Files

- `raw_runs.json` — one compact record per run (configuration, exact-match
  status, model metrics). No per-packet or per-cycle CSV is stored.
- `core_capacity.csv` — capacity x load x queue type, with `uniform1-8`
  packet length and `uniform` traffic (3 seeds averaged).
- `matrix_cells.csv` — all 384 cells of
  type x capacity x load x length x traffic, averaged over 3 seeds.
- `effect_strata.csv` — FIFO vs VOQ deltas for all 192
  capacity x load x length x traffic strata, paired by seed.
- `effect_groups.csv` — the same effect aggregated per capacity, per load,
  per packet-length mode, and per traffic pattern.
- `equal_buffer.csv` — equal-total-buffer extraction at the common points:
  FIFO C vs VOQ C/2 (both total 2C).
- `summary.json` — machine-readable aggregate used by the report.

## RTL capacity parameterization

- FIFO: `xbar_2x2_fifo #(.DEPTH(C))`, TB top parameter `DEPTH`.
- VOQ: `xbar_2x2_voq #(.VOQ_DEPTH(C))`, TB top parameter `DEPTH`.
- One binary per `(queue type, capacity)`:
  `build/phase2/{fifo,voq}_c{4,8,16,32}`. The binary is reused for every
  load / packet length / traffic / seed.

## Exactness

Every run is compared with `scripts/run_cosim.py`:

- delivered packets: per output port, completion order, `(src, len, start, end)`
- every cycle debug row: occupancy, head, source write/stall, grant, lock

Any mismatch is reported; no tolerance is used.  `raw_runs.json` keeps the
`exact` flag and the first mismatch messages for every run.

## Reproduction

From the experiment directory:

```bash
python3 scripts/run_matrix.py --workdir ~/Temp/phase2 --outdir results/phase2
```

Smoke test on a reduced grid:

```bash
python3 scripts/run_matrix.py \
  --capacities 4,8 --loads 0.8 --length-modes fixed1,uniform1-8 \
  --traffics uniform,hotspot --seeds 1 --cycles 1000 --warmup 200 \
  --workdir ~/Temp/phase2_smoke --outdir ~/Temp/phase2_smoke_results
```
