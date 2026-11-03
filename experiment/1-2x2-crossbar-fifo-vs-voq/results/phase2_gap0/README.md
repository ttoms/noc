# Phase 2 gap 0 重跑

- 日期：2026-11-03
- 配置：1152 runs，FIFO/VOQ × capacity 4/8/16/32 × load 0.5/0.8/0.95/1.0
  × length fixed1/fixed8/uniform1-8/bimodal1-8 × traffic uniform/hotspot/bursty
  × 3 seeds；4000 cycles，warmup 500
- 口径：`SOURCE_GAP=0`、逐 flit 握手吞吐
- 1152/1152 exact
- 旧 `results/phase2/` 为 gap 1 / 包完成口径

- `core_5seed.json`：uniform1-8 + uniform 的 5-seed core（160 runs）
