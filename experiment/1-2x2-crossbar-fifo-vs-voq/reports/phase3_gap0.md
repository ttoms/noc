# Phase 3（修正口径）— Per-crosspoint FIFO (XP) vs FIFO/VOQ

> 日期：2026-11-03
> 本报告取代 `reports/phase3.md` 中的吞吐/HOL 数字；旧报告使用
> `SOURCE_GAP=1` + 包完成吞吐。
> 数据：[../results/phase3_gap0/](../results/phase3_gap0/)

## 1. 结论

- 240/240 runs exact（FIFO/VOQ/XP × cap 4/8/16/32 × load 0.5/0.8/0.95/1.0
  × 5 seeds，uniform1-8）。
- XP 与 VOQ 在 **16 cells / 80 seed-pairs** 上所有指标完全相等，CI 为 0。
  这是“在此测试包络内可观测等价”，不是对所有 crossbar 的形式化等价。
- XP/VOQ 相对 FIFO 的增益随容量和负载上升；等总 buffer 64 flits、
  load 0.95/1.0 为 **+18.08 / +18.33pp**（95% CI ±2.28 / ±2.20pp）。
- FIFO 的吞吐与容量几乎无关（HOL 饱和在 0.711–0.713）；VOQ/XP 随容量增加
  接近输出瓶颈（cap32、load 1.0 为 0.9344）。
- 单 flit 包同拍竞争、输出反压、payload 完整性均已单独覆盖；见
  `docs/progress.md` §9。

## 2. 配置

- 2x2；每队列容量 4/8/16/32 flits
- load 0.5/0.8/0.95/1.0；seeds 1–5
- uniform1-8 包长；uniform destination
- 4000 cycles，warmup 500
- `SOURCE_GAP=0`；逐 flit `out_vld && out_rdy` 吞吐；`out_rdy=1`
- 容量口径：FIFO 总 buffer = 2×C；VOQ/XP 总 buffer = 4×C

## 3. 核心结果

| queue | cap | load 0.5 | 0.8 | 0.95 | 1.0 |
|---|---|---|---|---|---|
| FIFO | 4/8/16/32 | 0.4887 | 0.7128 | 0.7131 | 0.7109 |
| VOQ  | 4 | 0.4885 | 0.7612 | 0.7735 | 0.7719 |
| VOQ  | 8 | 0.4885 | 0.8013 | 0.8429 | 0.8392 |
| VOQ  | 16 | 0.4885 | 0.8036 | 0.8938 | 0.8942 |
| VOQ  | 32 | 0.4885 | 0.8041 | 0.9276 | 0.9344 |
| XP   | 4/8/16/32 | 与 VOQ 逐项相同 | 同左 | 同左 | 同左 |

XP/VOQ vs FIFO 的 Δ（等每队列容量；95% t CI）：

| cap | load 0.8 | load 0.95 | load 1.0 |
|---|---|---|---|
| 4 | +4.85 ±1.57pp | +6.05 ±1.54pp | +6.10 ±1.49pp |
| 8 | +8.85 ±2.91pp | +12.99 ±2.32pp | +12.83 ±1.54pp |
| 16 | +9.08 ±2.87pp | +18.08 ±2.28pp | +18.33 ±2.20pp |
| 32 | +9.13 ±2.91pp | +21.45 ±2.03pp | +22.35 ±1.83pp |

等总 buffer（FIFO C 对 XP/VOQ C/2；5 seeds）：

| total flits | load 0.8 | load 0.95 | load 1.0 |
|---|---|---|---|
| 16 | +4.85 ±1.57pp | +6.05 ±1.54pp | +6.10 ±1.49pp |
| 32 | +8.85 ±2.91pp | +12.99 ±2.32pp | +12.83 ±1.54pp |
| 64 | +9.08 ±2.87pp | +18.08 ±2.28pp | +18.33 ±2.20pp |

注：等总 buffer 的数值与 cap 8/16/32 的“等每队列”行相同，因为 FIFO 的
吞吐在测点内不随深度变化；报告时必须说明这是等总 buffer 口径，不是 XP
额外容量带来的收益。

## 4. XP/VOQ 等价边界

- 只在 2x2、单 outstanding source、uniform、无输出反压、cap 4–32、
  load ≤1.0 下验证。
- 模型 voq/xp 共用 `InputQueue`，RTL 共用 `arbiter_rr` + 手写 lock；
  “exact” 是行为一致性，不是独立形式化证明。
- 加入 XP+VOQ、多 outstanding、input scheduling、非 uniform、输出反压后，
  等价性需要重新验证。
- XP 是 per-crosspoint 的物理放置，不是新的吞吐机制；等总 buffer 下收益
  来自消除输入侧 HOL，而不是更多存储。

## 5. 限制

- latency 不引用 arrival 口径；admission latency 见 Phase 1 修正报告。
- 输出反压单独测，不混入本矩阵。
- 全矩阵只覆盖 uniform1-8 + uniform；hotspot/bursty 在 Phase 2 中覆盖。
- 5 seeds 对大增益足够，但对小差异仍需看 CI；load 0.5 的 −0.03pp 已在噪声内。

## 6. 复现

```bash
cd experiment/1-2x2-crossbar-fifo-vs-voq
python3 scripts/run_phase3.py --seeds 1,2,3,4,5 \
  --source-gap 0 --workdir /tmp/phase3 --outdir /tmp/phase3_out
python3 scripts/ci_from_raw.py /tmp/phase3_out/raw_runs.json \
  --pair fifo:voq --by capacity load --equal-buffer
```
