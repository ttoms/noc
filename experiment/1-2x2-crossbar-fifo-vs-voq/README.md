# 2x2 Crossbar: FIFO vs VOQ

一个 cycle-accurate 的 2x2 packet crossbar 实验：比较共享输入 FIFO 与 per-destination VOQ 在 no-drop / backpressure 下的吞吐、延迟和 HOL blocking。

> 当前是 **Phase 1**：模型与 RTL 已逐包、逐 cycle 对齐；结论见 [REPORT.md](REPORT.md)。

## 结论速览

- load 0.5：FIFO 与 VOQ 都能跟上，利用率约 0.489
- load ≥0.8：FIFO 被 HOL 卡在约 0.716–0.718；VOQ 约 0.789–0.813
- FIFO 的 HOL rate 约 46–47%；VOQ 为 0
- 等总 buffer 64 flits 下比较，不是靠增加存储赢

## 实验设定

- 2 输入 / 2 输出，1 flit/input/cycle，1 flit/output/cycle
- 包长 uniform random 1–8 flits
- 包粒度仲裁，整包锁定到 EOP
- 不丢包：队列满拉低 `rdy`，源端 stall
- 总 buffer 64 flits：
  - FIFO：2 × 32
  - VOQ：4 × 16
- 输出 RR 仲裁；uniform destination；load 0.5 / 0.8 / 0.95 / 1.0

## 快速开始

依赖：Python 3.10+、iverilog 11+。

```bash
python3 gen_trace.py --out /tmp/trace.jsonl --csv-out /tmp/trace.csv \
  --load 0.8 --cycles 4000 --seed 1

python3 run_cosim.py \
  --trace-jsonl /tmp/trace.jsonl --trace-csv /tmp/trace.csv \
  --cycles 4000 --warmup 500 \
  --dut fifo --mode fifo --total-buffer 64 --compile \
  --outdir /tmp/cosim_fifo
```

把 `--dut fifo --mode fifo` 换成 `--dut voq --mode voq` 即可跑 VOQ。

批量 sweep：

```bash
python3 run_sweep.py \
  --loads 0.5,0.8,0.95,1.0 --seeds 1,2,3 \
  --cycles 4000 --warmup 500 \
  --mode fifo --dut fifo \
  --outdir /tmp/sweep_fifo \
  --json-out results/phase1/fifo_summary.json
```

## 目录

- `model_v2.py`：flit 粒度 cycle model
- `gen_trace.py`：模型/RTL 共用 trace
- `gen_directed.py`：27 个定向验证 case
- `run_cosim.py`：逐包 + 逐 cycle 精确对比
- `run_sweep.py`：load/seed sweep
- `rtl/`：FIFO 和 VOQ 两套 RTL
- `tb/`：trace replay + 调试 CSV
- `vendor/cbb/`：复用的 CBB（fifo_sync、arbiter_rr、dff 等）
- `docs/architecture/2x2-crossbar.md`：架构、接口、时序契约
- `REPORT.md`：Phase 1 完整报告
- `results/phase1/`：sweep 汇总

## 验证标准

模型和 RTL 使用同一份 trace；`run_cosim.py` 按输出端口完成顺序比较 `(src, len, start, end)`，并可逐 cycle 比较 occupancy、head、grant、lock、source stall。任何差异直接报错，不使用统计容差。

## License

新代码使用 MIT；`vendor/cbb/` 复用 `ttoms/cbb_proj` 的 CBB，归属和说明见 `vendor/cbb/NOTICE.md`。
