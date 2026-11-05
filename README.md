# noc

NOC / on-chip interconnect modules and experiments.

## Experiments

- [1-2x2-crossbar-fifo-vs-voq](experiment/1-2x2-crossbar-fifo-vs-voq/README.md)
  - 2x2 packet crossbar: shared input FIFO vs per-destination VOQ
  - Phase 1: cycle-exact Python model + RTL + directed/load-sweep verification
    ([report](experiment/1-2x2-crossbar-fifo-vs-voq/REPORT.md))
  - Phase 2: per-queue capacity as an orthogonal variable, full 1152-run matrix
    ([report](experiment/1-2x2-crossbar-fifo-vs-voq/reports/phase2.md))
  - Phase 3: per-crosspoint FIFO (XP), exact 144-run core matrix against
    FIFO/VOQ, plus equal-total-buffer analysis
    ([report](experiment/1-2x2-crossbar-fifo-vs-voq/reports/phase3.md))
  - 2026-11-03 corrected measurement: `SOURCE_GAP=0`, flit-handshake throughput,
    split HOL, output backpressure, 5-seed reruns
    ([Phase 1](experiment/1-2x2-crossbar-fifo-vs-voq/reports/phase1_gap0.md),
    [Phase 2](experiment/1-2x2-crossbar-fifo-vs-voq/reports/phase2_gap0.md),
    [Phase 3](experiment/1-2x2-crossbar-fifo-vs-voq/reports/phase3_gap0.md))
- [2-shared-multi-output-fifo](experiment/2-shared-multi-output-fifo/README.md)
  - 1-write / N-read shared-buffer FIFO for NoC; architecture (C0/E0) + E1
    cycle model + E2 integration RTL (directed TB)
  - CBB dependencies: `idpool`, `link_list`, `shared_buffer`, `mo_fifo_top`
  - E1 2x2 comparison (5 seeds, paired CIs):
    ([report](experiment/2-shared-multi-output-fifo/reports/e1_shared_fifo.md))
  - E2 integration RTL + directed TB:
    ([docs](experiment/2-shared-multi-output-fifo/docs/e2-integration.md))

## Layout

- `experiment/` — numbered, self-contained experiments
- future `rtl/`, `docs/`, `vendor/` — shared NOC modules and infrastructure

Experiment directories are named `<number>-<topic>`, and each one keeps its
own README, report, code, tests, and result summaries.
