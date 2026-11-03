# Phase 3 gap 0 重跑（5 seeds）

- 日期：2026-11-03
- 配置：240 runs，FIFO/VOQ/XP × capacity 4/8/16/32 × load 0.5/0.8/0.95/1.0
  × seeds 1–5；uniform1-8，4000 cycles，warmup 500
- 口径：`SOURCE_GAP=0`、逐 flit 握手吞吐
- 240/240 exact；XP 与 VOQ 在 16 cells / 80 seed-pairs 上完全等价
- 旧 `results/phase3/` 为 gap 1 / 包完成口径
