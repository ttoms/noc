# 2x2 Crossbar — Progress

> 日期：2026-11-02
> 范围：IQ-FIFO 基线 cycle 级对齐、load sweep、IQ-VOQ RTL 与 co-sim。
> 约束：只改本实验目录；未动 CC/memory、日历、cron、vault 其他内容。
> 结构：Python 工具已归到 `scripts/`；RTL 按 `rtl-developer` 规范；结构图在
> `docs/figures/`（SVG + PNG）。

## 1. 结论

- 模型与 RTL 现在在已测配置下 **cycle 级完全一致**，没有使用统计容差。
- 原 2000-cycle、load=0.5 的 trace：双方均交付 434 包 / 1933 flits；逐包 start/end 0 处不一致；逐 cycle 调试字段 0 处不一致（2020 cycles × 27 列）。
- 定向 trace：27/27 个 case 在 FIFO 和 VOQ 下均 exact match。
- load sweep：4 个 load × 3 个 seed，共 12 组，FIFO 与 VOQ 全部 exact match。
- 过载检查：load=1.2 / 1.5，FIFO 与 VOQ 均 exact match，只反压、不丢包。
- IQ-VOQ RTL 已完成并与模型 VOQ 模式逐 cycle 对齐；XP per-crosspoint 未做。

这里“exact”指：按输出端口完成顺序比较 `(src, len, start, end)` 完全相等，且逐 cycle 的队列占用、head、grant、lock、source write/stall 全部相等。

## 2. 原 250/434 不一致的根因

原模型是 **包粒度原子入队**：

- `InputQueue.can_accept(packet)` 要求整包一次放下；`Source` 在包入队的同一 cycle 就释放，可以立刻加载下一个包。
- RTL 的源端是 **flit 粒度**：一个包每 cycle 写 1 个 flit，源端占用 L 个 cycle；最后一个 flit 写完后还有 1 个 cycle 的 turnaround，才能加载下一个包。
- RTL `fifo_sync` 是 show-ahead：cycle t 写进 FIFO 的 flit 在 t+1 才对仲裁可见；TB 在 negedge 采样并打印 `cycle-1`，所以“写 flit 的 cycle”和“包 start/end 标签”恰好对齐。
- 原模型把“入队、仲裁、传输”都放在同一 cycle，且整包瞬间入队，导致同一输入的下一个包最多提前 L-1 个 cycle 开始，队列占用和反压也在突发/冲突处走偏。表现就是部分包差 1 拍、部分包跨端口顺序不同，但总数和总 flits 仍相同。

修复方式是让模型复刻 RTL 的逐 edge 时序，而不是调容差或改仲裁优先级：

1. Source 每 cycle 最多写 1 个 flit；加载包后下一 cycle 才能写第一个 flit；写完最后一个 flit 后空 1 cycle。
2. 写接纳只看 **cycle 开始** 的队列占用；同 cycle 的读出不能给写腾位置（对应 `fifo_sync` 的 “满时同拍读出的空位不能用于当拍写入”）。
3. 仲裁只看 **cycle 开始** 的 head；本 cycle 的写要等 edge 结束才可见。
4. 输出的 flit 在 edge 结束被消费；TB 标签为 `physical_cycle - 1`，模型输出同样的标签。
5. 多 flit 包锁定 output/input 到 EOP；锁在 edge 结束更新，下一 cycle 生效。
6. FIFO 与 VOQ 都改成 flit 粒度存储；VOQ 每个 `(src, dst)` 独立反压。

另外发现并修复了一个 VOQ 模型 bug：VOQ 请求原先用了 `head()`（只对 FIFO 有意义，VOQ 返回 None），导致 VOQ 包永远不被仲裁；改为 `head_for(dst)`。

## 3. 改动清单

- `scripts/model_v2.py`
  - 重写时序内核：flit 粒度 Source / InputQueue，逐 edge 的 write → arbitrate → transfer → apply 顺序。
  - `fifo` 与 `voq` 共用同一套 cycle 语义；VOQ 按 `(src,dst)` 独立队列和深度。
  - `--cycles-csv`：输出逐 cycle 调试 CSV（FIFO 和 VOQ 两种表头）。
  - `all_delivered`：CSV 保留整段运行的交付包，`--warmup` 只影响统计窗口，不影响与 RTL 的逐包比较。
- `tb/xbar_2x2_fifo_tb.sv`
  - 新增 `+DBG=<csv>`：逐 cycle 输出 source 状态、FIFO occupancy/head、wr/stall、req/grant、locked、out_vld/sop/eop。
  - 原有 trace replay、packets CSV、时序行为不变。
- `rtl/xbar_2x2_voq.sv`（新增）
  - 4 个 VOQ（2 input × 2 output），每 VOQ 深度 16（总 buffer 64，与 FIFO 32+32 等总容量）。
  - 输入按 `dst` demux；目标 VOQ 满时拉低 `in_rdy`。
  - 每输出 packet-granular RR 仲裁，锁到 EOP；output 0 优先，output 1 的请求被 output 0 本 cycle 的 grant 屏蔽。
  - 复用 `fifo_sync` / `arbiter_rr`，无新 CBB 依赖。
- `tb/xbar_2x2_voq_tb.sv`（新增）
  - 同一套 trace replay 和 packets CSV；`+DBG` 输出每个 VOQ 的 occupancy/valid、grant、lock。
- `scripts/gen_directed.py`（新增）
  - 27 个定向 trace：单包四组合 × len 1/8、晚到包、独立双输出、同目的冲突（1/1、8/1、1/8、8/8、dst0/dst1）、错拍冲突、最大包长、FIFO/VOQ 打满、混合长度、HOL、RR 压力、同输入背靠背到达。
- `scripts/run_cosim.py`（新增）
  - 一次运行模型 + RTL，逐包（按输出端口的完成顺序）和逐 cycle（cell-by-cell）精确比较；不一致直接打印第一个差异。
- `scripts/run_sweep.py`（新增）
  - 生成 trace、跑 co-sim、聚合 3 个 seed 的指标并输出 Markdown 表；任何一组不 exact 就返回非 0。
- `docs/progress.md`（本文件）
- `results/matrix_v2/fifo_summary.json`、`results/matrix_v2/voq_summary.json`
  - 本轮 sweep 的原始指标和逐 run exact 结果。

## 4. 验证结果

### 4.1 原 trace（2000 cycles，load=0.5，seed=1）

- FIFO depth：每输入 32 flits（总 64）。
- 模型 / RTL：434 包、1933 flits。
- 逐包：0 处不一致。
- 逐 cycle：2020 cycles × 27 列，0 处不一致。

命令：

```bash
cd .
python3 scripts/run_cosim.py \
  --trace-jsonl results/rtl_trace.jsonl \
  --trace-csv results/rtl_trace.csv \
  --cycles 2020 --warmup 500 \
  --dut fifo --mode fifo --total-buffer 64 \
  --binary build/xbar_fifo_tb \
  --outdir /tmp/cosim_orig
```

### 4.2 定向 trace

- FIFO：27/27 exact match。
- VOQ：27/27 exact match。
- 覆盖到的边界：
  - 单包所有 `src/dst` 组合，len=1 和 len=8。
  - 同目的冲突：len 1/1、8/1、1/8、8/8，dst0 和 dst1。
  - 两输入同 cycle 到达、错 1/2/7 cycle 到达。
  - FIFO 真打满：`full_d0_l8_x12` 中 FIFO occupancy 达到 32，出现 38 个 source stall cycle；VOQ occupancy 达到 16，出现 102 个 stall cycle。
  - 混合包长打满、HOL、RR 连续授权、同输入背靠背到达、双输出独立服务。
- 逐 cycle 比较包含每个队列的 occupancy、head/valid、source write/stall、grant、lock，因此不是只比包级完成时间。

命令：

```bash
python3 scripts/gen_directed.py --outdir /tmp/directed --cycles 1200

for f in /tmp/directed/*.jsonl; do
  b=${f%.jsonl}
  python3 scripts/run_cosim.py \
    --trace-jsonl "$f" --trace-csv "$b.csv" \
    --cycles 1200 --warmup 0 \
    --dut fifo --mode fifo --total-buffer 64 \
    --binary build/xbar_fifo_tb \
    --outdir /tmp/cosim_directed
done

# VOQ 用同样的 trace，只换 DUT/mode/binary：
#   --dut voq --mode voq --binary build/xbar_voq_tb
```

### 4.3 IQ-FIFO load sweep（模型 / RTL 对比表）

条件：4000 cycles，500 cycles warmup，3 seeds，total buffer 64（FIFO 每输入 32 flits），uniform dst，包长 1–8。

- `delivered pkts/flits` 是 warmup 后的模型统计均值；RTL 在每一组里逐包、逐 cycle 完全一致（比较覆盖全部 4000 cycles 和全部交付包，包括 warmup 内交付的包）。
- `utilization` = delivered flits / (2 × 3500)，即两个输出合计的归一化利用率。
- 延迟指标与 CSV 的 `start/end` 同一口径：`physical transfer cycle - 1`；p99 取同一口径下 `end - arrival` 的 99 分位。
- `exact=yes` 表示 3 个 seed 全部无差异。

| load | seeds | exact | delivered pkts | delivered flits | utilization | avg pkt lat | p99 pkt lat | avg queue lat | avg queue occ | source stall | output idle | HOL rate | Jain |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.5 | 3 | yes | 771.3 | 3422 | 0.489 | 10.77 | 39.7 | 2.39 | 1.66 | 0.0000 | 0.511 | 0.0243 | 0.9993 |
| 0.8 | 3 | yes | 1127.7 | 5010 | 0.716 | 240.26 | 526.7 | 38.68 | 28.18 | 0.1154 | 0.285 | 0.4655 | 0.9997 |
| 0.95 | 3 | yes | 1127.7 | 5026 | 0.718 | 498.27 | 980.7 | 39.60 | 28.88 | 0.1204 | 0.282 | 0.4655 | 0.9994 |
| 1.0 | 3 | yes | 1122.3 | 5015 | 0.716 | 586.47 | 1132.3 | 39.94 | 29.07 | 0.1242 | 0.284 | 0.4694 | 0.9999 |

命令：

```bash
python3 scripts/run_sweep.py \
  --loads 0.5,0.8,0.95,1.0 --seeds 1,2,3 \
  --cycles 4000 --warmup 500 \
  --mode fifo --dut fifo \
  --outdir /tmp/sweep_fifo \
  --json-out results/matrix_v2/fifo_summary.json
```

### 4.4 IQ-VOQ load sweep（对照）

条件同上；总 buffer 仍为 64，VOQ 为 4 × 16 flits。所有组同样 exact match。

| load | seeds | exact | delivered pkts | delivered flits | utilization | avg pkt lat | p99 pkt lat | avg queue lat | avg queue occ | source stall | output idle | HOL rate | Jain |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.5 | 3 | yes | 771.0 | 3420 | 0.489 | 10.32 | 37.7 | 1.93 | 1.38 | 0.0000 | 0.511 | 0.0000 | 0.9992 |
| 0.8 | 3 | yes | 1235.0 | 5522 | 0.789 | 78.31 | 217.7 | 7.00 | 6.14 | 0.0067 | 0.211 | 0.0000 | 0.9989 |
| 0.95 | 3 | yes | 1276.7 | 5694 | 0.813 | 308.65 | 624.3 | 7.35 | 6.61 | 0.0049 | 0.187 | 0.0000 | 1.0000 |
| 1.0 | 3 | yes | 1271.3 | 5689 | 0.813 | 400.55 | 777.0 | 7.63 | 6.78 | 0.0065 | 0.187 | 0.0000 | 1.0000 |

命令：

```bash
python3 scripts/run_sweep.py \
  --loads 0.5,0.8,0.95,1.0 --seeds 1,2,3 \
  --cycles 4000 --warmup 500 \
  --mode voq --dut voq --binary build/xbar_voq_tb \
  --outdir /tmp/sweep_voq \
  --json-out results/matrix_v2/voq_summary.json
```

### 4.5 过载检查

条件：2000 cycles，seed=7，load=1.2 / 1.5。FIFO 与 VOQ 均 exact match：

- FIFO：load 1.2 交付 612 包，load 1.5 交付 627 包。
- VOQ：load 1.2 交付 706 包，load 1.5 交付 704 包。
- 行为是 source stall + 队列满反压，没有丢包；模型和 RTL 的 stall/full 逐 cycle 一致。

命令示例：

```bash
python3 scripts/gen_trace.py \
  --out /tmp/ov_fifo_l1.2.jsonl \
  --csv-out /tmp/ov_fifo_l1.2.csv \
  --load 1.2 --cycles 2000 --seed 7

python3 scripts/run_cosim.py \
  --trace-jsonl /tmp/ov_fifo_l1.2.jsonl \
  --trace-csv /tmp/ov_fifo_l1.2.csv \
  --cycles 2000 --warmup 300 \
  --dut fifo --mode fifo --total-buffer 64 \
  --binary build/xbar_fifo_tb \
  --outdir /tmp/cosim_ov
```

## 5. 当前差异与限制

- **当前模型/RTL 差异：无**（在上述已测配置和 trace 范围内，逐包和逐 cycle 均为 0 差异）。
- 尚未覆盖：下游 `out_rdy` 反压。当前 TB 固定 `out_rdy=2'b11`，所以“输出端 stall 后 FIFO/XP 反压”的路径没有进入本轮 co-sim。
- 流量只有 uniform destination + 包长 1–8；还没有 bursty / correlated / 固定包长矩阵。旧 `sim.py` 的 bursty 流量没有接到 `model_v2` 的逐 cycle 契约里。
- RTL packets CSV 只有 `port,src,len,start,end`，没有 `seq/dst`。目前包身份由“每输入保序 + 每个输出端口的完成顺序 + 逐 cycle head/grant 比较”确定，不是显式 seq tag；后续可以在 TB 里加 sideband seq 做更强的身份校验。
- RTL 侧没有统计 p99/队列最大占用；表里的延迟和占用来自模型，但前提是模型与 RTL 已逐 cycle 完全一致。
- RTL TB 的缓冲深度是编译期常量：FIFO 2 × 32、VOQ 4 × 16（总 64）。`scripts/run_cosim.py` 对 `--total-buffer != 64` 直接报错，避免模型和 RTL 静默使用不同容量。
- XP per-crosspoint、OQ、CIOQ 未实现，按计划留到后续阶段。
- 环境：iverilog 11.0，Python 3.10；只使用 iverilog/python，没有安装重型依赖，没有重型编译。中间文件都在 `/tmp/`，不在 vault 内。

## 6. 下一步

1. 在 TB 和模型里加入可配置的下游 `out_rdy` stall 序列（例如 `+RDY_PATTERN`），验证输出反压路径仍然逐 cycle 一致。
2. 给 RTL packets CSV 增加显式 `seq`/`dst`（TB sideband 编码或单独 monitor），把包身份校验从“按端口顺序”升级为“按 seq”。
3. 增加 bursty / 固定包长 / 双峰包长矩阵，复用同一 co-sim 契约和 `scripts/run_sweep.py`。
4. 增加 RTL 侧或模型侧的 max queue occupancy、p99、每输入/输出吞吐对比。
5. 视需要实现 IQ-VOQ 的更多参数化（每 VOQ 深度、等每队列深度 vs 等总 buffer 两组结果）。
6. XP per-crosspoint 和 OQ/CIOQ 留到后续阶段；不在本轮引入。

## 7. 构建命令（不依赖 Makefile）

CBB 源默认在 `vendor/cbb/rtl`，可用 `CBB_RTL` 环境变量覆盖。FIFO：

```bash
CBB_RTL=${CBB_RTL:-vendor/cbb/rtl}
iverilog -g2012 -I "$CBB_RTL" -o build/xbar_fifo_tb \
  rtl/xbar_2x2_fifo.sv tb/xbar_2x2_fifo_tb.sv \
  "$CBB_RTL"/memory/fifo_sync.sv \
  "$CBB_RTL"/arbiter/arbiter_rr.sv \
  "$CBB_RTL"/arbiter/pri_tree.sv \
  "$CBB_RTL"/arbiter/suf_or.sv \
  "$CBB_RTL"/util/bin2ohot.sv \
  "$CBB_RTL"/basic/dff.sv \
  "$CBB_RTL"/basic/dffr.sv
```

VOQ：把 `rtl/xbar_2x2_fifo.sv tb/xbar_2x2_fifo_tb.sv` 换成 `rtl/xbar_2x2_voq.sv tb/xbar_2x2_voq_tb.sv`，输出改成 `build/xbar_voq_tb`。也可以用 `scripts/run_cosim.py --compile` / `scripts/run_sweep.py`（内部调用同一组命令）。
