# Phase 1（修正口径）— 2x2 Crossbar: FIFO vs VOQ

> 日期：2026-11-03
> 本报告取代 `REPORT.md` 中的吞吐/HOL/延迟数字；旧报告使用 `SOURCE_GAP=1`
> 和包完成吞吐，不能与新结果混用。
> 数据：[../results/phase1_gap0/](../results/phase1_gap0/)

## 1. 结论

- 在 2x2、包粒度仲裁、no-drop 只反压、总 buffer 64 flits 下，FIFO 在高负载
  被 HOL 卡在 **0.711–0.713**；VOQ 达到 **0.894**（load 0.95/1.0）。
- load 0.8 的 VOQ 增益 **+9.08pp**（95% CI ±2.87pp）；load 0.95/1.0 为
  **+18.08 / +18.33pp**（CI ±2.28 / ±2.20pp）。
- load 0.5 两者无差异（delta −0.03pp，CI ±0.06pp），符合“低负载不是瓶颈”。
- FIFO 的 HOL rate 在高负载约 **0.56**，其中 output_busy 约 0.48、arb_loss
  约 0.08；VOQ 的 HOL 恒为 0。
- **latency 只引用 admission 口径**（`end - accepted`）：FIFO 约 47 cycles，
  VOQ 约 19–20 cycles（load 0.95/1.0，5 seeds，4000 cycles）。
  arrival 口径在 load ≥0.8 时不收敛，不能用于比较。

## 2. 口径修正

旧结果有三处偏差：

1. 源端每包最后 flit 后固定空 1 拍，VOQ 在高负载被 source ceiling 压住。
2. 吞吐在包完成时一次性加整包长度，warmup 边界会把整包计入。
3. HOL 只看 locked 输出，漏掉同拍仲裁竞争，单 flit 包尤其明显。

本报告使用：

- `SOURCE_GAP=0`：最后一个 flit 握手的同一 edge 装载下一包，下一拍发首 flit。
- 逐 flit `out_vld && out_rdy` 握手计数；`utilization = 握手数 / (2 × 窗口)`。
- FIFO HOL 拆成 `hol_output_busy` / `hol_arb_loss`；另报 `arb_loss_events`。
- admission latency：只统计 warmup 后接受（`accepted >= warmup`）的包。

## 3. 实验设定

- 2 输入 / 2 输出，1 flit/input/cycle，1 flit/output/cycle
- 包长 uniform 1–8 flits
- 包粒度仲裁，整包锁定到 EOP
- 不丢包：目标队列满时拉低 `in_rdy`，源端 stall
- 总 buffer 64 flits：FIFO 每输入 32；VOQ 每 (src,dst) 16
- load 0.5 / 0.8 / 0.95 / 1.0；5 seeds（1–5）
- 4000 cycles，warmup 500；模型与 RTL 共用 trace，逐包、逐 cycle 精确比较

## 4. 结果

| load | FIFO util | VOQ util | Δ (VOQ−FIFO) | FIFO HOL | VOQ HOL | FIFO admit lat | VOQ admit lat |
|---|---|---|---|---|---|---|---|
| 0.5 | 0.4887 ±0.0112 | 0.4885 ±0.0108 | −0.0003 ±0.0006 | 0.041 | 0 | 6.66 | 5.76 |
| 0.8 | 0.7128 ±0.0077 | 0.8036 ±0.0156 | +0.0908 ±0.0287 | 0.558 | 0 | 46.08 | 13.89 |
| 0.95 | 0.7131 ±0.0097 | 0.8938 ±0.0137 | +0.1808 ±0.0228 | 0.562 | 0 | 47.22 | 19.27 |
| 1.0 | 0.7109 ±0.0067 | 0.8942 ±0.0120 | +0.1833 ±0.0220 | 0.565 | 0 | 47.42 | 19.74 |

注：util 与 Δ 为 5 seeds 的均值 ± 95% t 置信区间；HOL 为 per-cycle 比例；
admit lat 单位为 cycles。

### 4.1 HOL 拆分（FIFO）

| load | output_busy | arb_loss | arb_loss_events/4000cycles |
|---|---|---|---|
| 0.5 | 0.037 | 0.004 | 85.8 |
| 0.8 | 0.476 | 0.083 | 299.6 |
| 0.95 | 0.477 | 0.084 | 301.8 |
| 1.0 | 0.482 | 0.083 | 297.4 |

单 flit 同拍竞争由 `arb_loss_events` 覆盖；`hol_cycles` 仍要求后面有可用的
替代目的地包，因此不会把纯竞争算成 HOL。

### 4.2 与旧结果对比

旧报告 load 0.95/1.0 的 VOQ 约 0.813、FIFO 约 0.716，增益约 +9.7pp。
修正后 VOQ 约 0.894，FIFO 约 0.711，增益约 +18pp。差异主要来自旧口径的
source turnaround，而不是仲裁器或容量变化。方向不变。

## 5. 限制

- **arrival latency 不收敛**：源端外是隐式无界到达队列；FIFO 在 load 0.8 时
  offered 0.8 > served 0.71，队列持续增长。4k/500 到 8k/1000，FIFO arrival
  avg 从 235 涨到 542，admission 从 45.2 到 47.3；因此只引用 admission 口径。
- **输出反压单独测**：本报告 `out_rdy=1`；60% ready 的反压实验见
  `docs/progress.md` §9.4，不混入本表。
- **5 seeds 仍不是强统计**：大增益（≥9pp）CI 明显不为 0；小差异（load 0.5）
  已经落在噪声内。
- SVA 使用 iverilog 可执行的立即断言，不是并发 SVA 形式化；见 §9.5。
- 只覆盖 2x2、单 outstanding source、uniform traffic；不外推到更大 crossbar。

## 6. 复现

```bash
cd experiment/1-2x2-crossbar-fifo-vs-voq
python3 scripts/run_sweep.py \
  --loads 0.5,0.8,0.95,1.0 --seeds 1,2,3,4,5 \
  --cycles 4000 --warmup 500 \
  --mode fifo --dut fifo \
  --binary /tmp/fifo_tb --outdir /tmp/p1_fifo \
  --source-gap 0 --json-out /tmp/p1_fifo.json
```

VOQ 把 `--mode/--dut` 换成 `voq`，binary 换成 `xbar_voq_tb`。
