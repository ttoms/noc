# Phase 3 gap 0 重跑

- 日期：2026-11-03
- 配置：144 runs，FIFO/VOQ/XP × capacity 4/8/16/32 × load 0.5/0.8/0.95/1.0
  × 3 seeds；uniform1-8，4000 cycles，warmup 500
- 口径：`SOURCE_GAP=0`、逐 flit 握手吞吐
- 144/144 exact；XP/VOQ 在 16 cells / 48 seed-pairs 上完全等价
- 旧 `results/phase3/` 为 gap 1 / 包完成口径
