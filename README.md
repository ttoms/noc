# noc

NOC / on-chip interconnect modules and experiments.

## Experiments

- [1-2x2-crossbar-fifo-vs-voq](experiment/1-2x2-crossbar-fifo-vs-voq/REPORT.md)
  - 2x2 packet crossbar: shared input FIFO vs per-destination VOQ
  - Phase 1: cycle-exact Python model + RTL + directed/load-sweep verification

## Layout

- `experiment/` — numbered, self-contained experiments
- future `rtl/`, `docs/`, `vendor/` — shared NOC modules and infrastructure

Experiment directories are named `<number>-<topic>`, and each one keeps its
own README, report, code, tests, and result summaries.
