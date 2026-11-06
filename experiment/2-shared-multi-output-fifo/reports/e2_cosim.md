# E2 — RTL / cycle-model 逐包逐 cycle co-sim

> 日期：2026-11-06
> 状态：cell16、VC2、multi-dst VC、5 seeds × 3 loads 全部 exact。
> 数据：[../results/e2_cosim/summary.csv](../results/e2_cosim/summary.csv)

## 1. 口径

- RTL：`rtl/xbar_2x2_shared.sv` + vendor CBB pin `af593e9`。
- 模型：`scripts/model_e2.py`，显式建模 RTL 的寄存选择：
  - 每输入/每输出的 `sel_vld/sel_vc/vc_locked` 寄存；
  - 每输出外部 2:1 RR + 包锁；
  - source 在周期末写入；同拍读释放的 cell 可被写复用。
- trace：`gen_trace.py`（uniform1-8、uniform、load 0.8/0.9/1.0、5 seeds），
  `derive_vc_trace.py` 生成 multi VC（VC_NUM=2），arrival +5 避开 reset 窗口。
- 仿真：2600 cycles，trace 2500 cycles；`CELL_NUM=16`。
- 对比：同一 trace 分别跑 RTL 与模型，比较输出包 CSV 的
  `seq/src/dst/len/start/end`；要求包集合完全一致且 `start/end` 差为 0。

## 2. 结果

15/15 runs exact：

- 每 run 的模型包数 = RTL 包数（例如 load0.9/seed1：893 = 893）。
- 包集合完全一致：`rtl_only=0`、`model_only=0`。
- 每个包的 `start` 差 = 0，`end` 差 = 0。
- RTL trace TB 同时检查 payload/seq、SOP/EOP、目的、VC；无 data/protocol error。

## 3. 关键修正

- 早期 E1 模型是组合选择/组合输出仲裁，与 RTL 的寄存选择差 1–2 拍且
  调度不同；同 trace 下 RTL 893 包 vs E1 930 包，start/end 差均值 +50。
- 新 `model_e2.py` 按 RTL 状态机重建后，先校准输出标签（RTL TB 在
  negedge 打印 `physical_cycle-1`），然后 15/15 exact。
- 结论：RTL 的 1W/NR 共享 FIFO + 2x2 输出仲裁行为已被模型复现，
  不是只对齐包数/数据，而是包级 start/end 完全一致。

## 4. 限制

- 只覆盖 `CELL_NUM=16`、`VC_NUM=2`、`N=2`、`out_rdy=1`。
- 未覆盖 `CELL_NUM=32/64`、`VC_NUM=4`、输出周期性反压、hotspot/bursty、
  quota、过载 >1.0。
- RTL 的 selection 暂用显式 `always_ff`（CBB 规范例外），待重构。
- 顶层 SVA 未运行（依赖子 CBB 并发 SVA，iverilog 11 不支持整体编译）。

## 5. 复现

```bash
cd experiment/2-shared-multi-output-fifo
python3 scripts/run_e2_cosim.py \
  --seeds 1,2,3,4,5 --loads 0.8,0.9,1.0 --cell-num 16 \
  --workdir /root/Temp/e2_cosim --outdir results/e2_cosim
```
