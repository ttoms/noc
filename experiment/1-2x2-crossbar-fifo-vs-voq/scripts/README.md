# Scripts

实验用 Python 工具；RTL/TB 在仓库根目录的 `rtl/`、`tb/`。

- `gen_trace.py`：生成模型/RTL 共用 trace（包长、traffic、负载、seed）
- `gen_directed.py`：生成定向验证 case
- `model_v2.py`：flit 粒度 cycle-accurate 模型（FIFO/VOQ/XP）
- `run_cosim.py`：编译 RTL、跑模型和 RTL、逐包/逐 cycle 精确比较
- `run_sweep.py`：Phase 1 的 load/seed sweep
- `run_matrix.py`：Phase 2 全因子 capacity/traffic 矩阵驱动
- `analyze_phase2.py`：Phase 2 汇总与等总 buffer 重提取
- `run_phase3.py`：Phase 3 FIFO/VOQ/XP core matrix 驱动
- `analyze_phase3.py`：Phase 3 配对 delta、等总 buffer、XP/VOQ 等价汇总
- `compare_xp_voq.py`：XP 与 VOQ 两套 RTL 的逐包/逐 cycle 等价检查

所有脚本从实验根目录运行，例如：

```bash
python3 scripts/gen_trace.py --out /tmp/t.jsonl --csv-out /tmp/t.csv
python3 scripts/run_cosim.py --trace-jsonl /tmp/t.jsonl --trace-csv /tmp/t.csv \
  --cycles 4000 --warmup 500 --dut fifo --mode fifo --total-buffer 64 --compile
```

`run_cosim.py` 默认使用 `vendor/cbb/rtl`，不依赖本机其他仓库。
