# Phase 1 gap 0 重跑

- 日期：2026-11-03
- 配置：2x2、总 buffer 64、load 0.5/0.8/0.95/1.0、3 seeds、4000 cycles、warmup 500
- 口径：`SOURCE_GAP=0`、逐 flit `out_vld && out_rdy` 吞吐、HOL 拆分
- `fifo.json` / `voq.json`：完整 summary + 逐 run 指标
- 旧 `results/phase1/` 为 gap 1 / 包完成口径，不能与新数据混用
