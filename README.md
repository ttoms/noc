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

## Layout

- `experiment/` — numbered, self-contained experiments
- future `rtl/`, `docs/`, `vendor/` — shared NOC modules and infrastructure

Experiment directories are named `<number>-<topic>`, and each one keeps its
own README, report, code, tests, and result summaries.
