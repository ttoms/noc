# Phase 2 gap 0 重跑（5 seeds）

- 日期：2026-11-03
- 配置：1920 runs，FIFO/VOQ × capacity 4/8/16/32 × load 0.5/0.8/0.95/1.0
  × length fixed1/fixed8/uniform1-8/bimodal1-8 × traffic uniform/hotspot/bursty
  × seeds 1–5；4000 cycles，warmup 500
- 口径：`SOURCE_GAP=0`、逐 flit 握手吞吐
- 1920/1920 exact
- 旧 `results/phase2/` 为 gap 1 / 包完成口径
