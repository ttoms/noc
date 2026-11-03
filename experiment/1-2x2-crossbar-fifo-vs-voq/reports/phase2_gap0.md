# Phase 2（修正口径）— 容量作为正交变量

> 日期：2026-11-03
> 本报告取代 `reports/phase2.md` 中的吞吐/HOL 数字。旧报告使用
> `SOURCE_GAP=1` + 包完成吞吐，不能与新结果混用。
> 数据：[../results/phase2_gap0/](../results/phase2_gap0/)

## 1. 结论

- FIFO/VOQ 全因子矩阵（1920 runs，5 seeds）全部 exact；修正口径后 VOQ
  在 **159/192** 个 strata 更好，FIFO 更好 21，持平 12，平均 **+6.27pp**
  （旧口径 +2.69pp）。
- 5-seed core（uniform1-8 + uniform，cap 4/8/16/32 × load 0.5/0.8/0.95/1.0）
  与全矩阵方向一致；容量越大增益越明显。
- 等总 buffer（全矩阵 5 seeds）：16/32/64 flits 为
  **+3.50 / +5.79 / +7.40pp**。
- 低负载 load 0.5 两者无差异（约 0），符合“低负载不是瓶颈”。
- 包长：fixed1 / fixed8 / uniform1-8 / bimodal1-8 为
  +7.96 / +3.62 / +6.63 / +6.89pp；fixed1 不再持平。单 flit 包没有队头阻塞，
  但 FIFO 的固定顺序仍会在输出竞争时损失吞吐；VOQ 可以按目的选择。
- traffic：uniform / bursty / hotspot 为 +9.19 / +8.81 / +0.83pp；
  hotspot 受目标输出瓶颈限制。

## 2. 矩阵与口径

- queue type：FIFO / VOQ
- capacity per queue：4 / 8 / 16 / 32 flits
- load：0.5 / 0.8 / 0.95 / 1.0
- packet length：fixed1 / fixed8 / uniform1-8 / bimodal1-8
- traffic：uniform / hotspot / bursty
- seeds：1–5（全矩阵）
- 4000 cycles，warmup 500
- `SOURCE_GAP=0`；吞吐按逐 flit `out_vld && out_rdy` 握手；`out_rdy=1`

容量口径：

- FIFO 总 buffer = `2 × C_fifo`
- VOQ 总 buffer = `4 × C_voq`
- 等总 buffer 比较：FIFO 8/16/32 对 VOQ 4/8/16（FIFO 4 的等总点未覆盖）

## 3. 5-seed core 结果

FIFO utilization 在各 capacity 下相同（HOL 饱和，深度不影响稳态吞吐）：

| load | FIFO util | VOQ cap4 | VOQ cap8 | VOQ cap16 | VOQ cap32 |
|---|---|---|---|---|---|
| 0.5 | 0.4887 | 0.4885 | 0.4885 | 0.4885 | 0.4885 |
| 0.8 | 0.7128 | 0.7612 | 0.8013 | 0.8036 | 0.8041 |
| 0.95 | 0.7131 | 0.7735 | 0.8429 | 0.8938 | 0.9276 |
| 1.0 | 0.7109 | 0.7719 | 0.8392 | 0.8942 | 0.9344 |

Δ（VOQ−FIFO，5 seeds，95% t CI）：

| capacity | load 0.8 | load 0.95 | load 1.0 |
|---|---|---|---|
| 4 | +4.85 ±1.57pp | +6.05 ±1.54pp | +6.10 ±1.49pp |
| 8 | +8.85 ±2.91pp | +12.99 ±2.32pp | +12.83 ±1.54pp |
| 16 | +9.08 ±2.87pp | +18.08 ±2.28pp | +18.33 ±2.20pp |
| 32 | +9.13 ±2.91pp | +21.45 ±2.03pp | +22.35 ±1.83pp |

## 4. 全矩阵（5 seeds，1920 runs）

- 1920/1920 exact；384 cells、192 strata。
- VOQ 更好 159/192；FIFO 21/192；持平 12/192；平均 +6.27pp。
- 等总 buffer：16/32/64 flits 为 +3.50/+5.79/+7.40pp
  （旧口径 +0.19/+2.25/+3.55pp）。
- 按容量：4/8/16/32 为 +3.50/+5.79/+7.40/+8.41pp。
- 按 load：0.5 约 0；0.8/0.95/1.0 为 +4.94/+9.86/+10.31pp。
- 按包长：fixed1/fixed8/uniform1-8/bimodal1-8 = +7.96/+3.62/+6.63/+6.89pp。
- 按 traffic：uniform/bursty/hotspot = +9.19/+8.81/+0.83pp。
- fixed1 的旧结论“持平”在新口径下不成立；单 flit 包没有 HOL，但 FIFO 的
  固定顺序仍会在输出竞争时损失吞吐。hotspot 的增益小是因为输出瓶颈，不是
  队列位置无效。

## 5. 限制

- latency 不能引用 arrival 口径；本报告不比较 latency。admission latency 见
  Phase 1 修正报告。
- `out_rdy=1`；输出反压实验单独做，不混入本矩阵。
- `gen_trace.py` 的 packet rate 上限为 1/cycle，`fixed1` 下 load>1.0 实际仍是
  1.0；本矩阵最高 load 1.0，不受影响。
- 只覆盖 2x2、单 outstanding source、uniform destination（除 hotspot/bursty）。

## 6. 复现

```bash
cd experiment/1-2x2-crossbar-fifo-vs-voq
python3 scripts/run_matrix.py --source-gap 0 \
  --seeds 1,2,3,4,5 --workdir /tmp/phase2 --outdir /tmp/phase2_out
python3 scripts/ci_from_raw.py /tmp/phase2_out/raw_runs.json \
  --pair fifo:voq --by capacity load
```
