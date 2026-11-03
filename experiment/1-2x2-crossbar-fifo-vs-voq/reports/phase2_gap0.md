# Phase 2（修正口径）— 容量作为正交变量

> 日期：2026-11-03
> 本报告取代 `reports/phase2.md` 中的吞吐/HOL 数字。旧报告使用
> `SOURCE_GAP=1` + 包完成吞吐，不能与新结果混用。
> 数据：[../results/phase2_gap0/](../results/phase2_gap0/)

## 1. 结论

- FIFO/VOQ 全因子矩阵（1152 runs，3 seeds）全部 exact；修正口径后 VOQ
  在 **163/192** 个 strata 更好，FIFO 更好 10，持平 19，平均 **+6.22pp**
  （旧口径 +2.69pp）。
- 5-seed core（uniform1-8 + uniform，cap 4/8/16/32 × load 0.5/0.8/0.95/1.0）
  与 3-seed 全矩阵方向一致；容量越大增益越明显。
- 等总 buffer（5-seed core）：
  - 16 flits：+4.85 / +6.05 / +6.10pp（load 0.8/0.95/1.0）
  - 32 flits：+8.85 / +12.99 / +12.83pp
  - 64 flits：+9.08 / +18.08 / +18.33pp
- 低负载 load 0.5 两者无差异（约 −0.03pp），符合“低负载不是瓶颈”。
- 包长与 traffic 的结论沿用 3-seed 全矩阵：fixed1 基本持平，bimodal1-8/
  uniform1-8 增益更大；hotspot 下增益受目标输出瓶颈限制。

## 2. 矩阵与口径

- queue type：FIFO / VOQ
- capacity per queue：4 / 8 / 16 / 32 flits
- load：0.5 / 0.8 / 0.95 / 1.0
- packet length：fixed1 / fixed8 / uniform1-8 / bimodal1-8
- traffic：uniform / hotspot / bursty
- seeds：1/2/3（全矩阵）；1–5（core）
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

## 4. 全矩阵（3 seeds，1152 runs）

- 1152/1152 exact；384 cells、192 strata。
- VOQ 更好 163/192；FIFO 10/192；持平 19/192；平均 +6.22pp。
- 等总 buffer 全矩阵：16/32/64 flits 为 +3.46/+5.71/+7.35pp
  （旧口径 +0.19/+2.25/+3.55pp）。
- 按 load：0.5 基本持平；0.8/0.95/1.0 增益随负载上升。
- 按包长：fixed1 基本持平；fixed8 中等；uniform1-8/bimodal1-8 更大。
- 按 traffic：uniform 增益最大；hotspot 受目标输出瓶颈限制；bursty 介于两者。
- 这些 3-seed 分层结论用于方向判断；强结论以 5-seed core 为准。

## 5. 限制

- 全矩阵 5-seed 仍在运行；本报告的全矩阵数字是 3 seeds，core 是 5 seeds。
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
  --seeds 1,2,3 --workdir /tmp/phase2 --outdir /tmp/phase2_out
python3 scripts/ci_from_raw.py /tmp/phase2_out/raw_runs.json \
  --pair fifo:voq --by capacity load
```
