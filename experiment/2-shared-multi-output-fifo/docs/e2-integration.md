# E2 — 2x2 集成 RTL（定向 TB）

> 状态：集成 RTL + 定向 TB + trace TB + 逐包逐 cycle co-sim 完成（cell16/32/64、VC2/4、100%/75% ready 全部 exact）。
> CBB pin：`cbb_proj` `af593e9`，见 `vendor/cbb/README.md`。

## 1. 拓扑

- 2 个输入，每个输入一个 `mo_fifo_top`（1W / 2R，`CELL_NUM` 个共享 cell，
  `VC_NUM` 条 VC 链，multi-dst VC）。
- 每个 FIFO 的 2 个读口分别接到 output0 / output1。
- 每个输出一个 2:1 RR 仲裁（两个输入 FIFO），选中后锁定到 EOP；
  输出反压时保持 selection/data 不变。
- 两个输出可以在同一拍读同一个输入 FIFO 的不同 VC（1W/NR 的多读口能力）。

## 2. 接口与文件

- RTL：`rtl/xbar_2x2_shared.sv`
- TB：`tb/xbar_2x2_shared_tb.sv`（定向）、`tb/xbar_2x2_trace_tb.sv`（随机 trace）
- CBB：`vendor/cbb/rtl/...`（只读副本，pin `af593e9`）
- 参数：`FLIT_W`、`N`、`VC_NUM`、`CELL_NUM`、`DST_W`、`VC_W`、`QUOTA_W`。
- v1 无 quota；`quota_en`/`quota` 在集成层 tied off。

## 3. 输出仲裁语义

- 每个输出维护 `locked/locked_in`：
  - 未锁定时，对两个输入 FIFO 的 `out_vld` 做 RR；选中即锁存输入。
  - 下游未 ready 时也锁存，保证 `out_vld/data` 稳定。
  - 锁定后只把 `out_rdy` 回给该输入；输入 FIFO 自身再锁到 (vc) 到 EOP。
  - 收到 EOP 握手后解锁。
- 选中输入的 `out_sop/eop/data/vc` 直接 mux 到输出；未选中输入 `out_rdy=0`。
- 输出选择寄存器使用显式 `always_ff`（与 `mo_fifo_top` selection 相同的
  工具链例外），后续统一重构。

## 4. 定向 TB

`tb/xbar_2x2_shared_tb.sv` 覆盖：

1. 两个输入分别送不同输出，4-flit 包。
2. 两个输入同时打 output0：输出 2:1 仲裁 + 包锁，不能交错。
3. 同一输入送两个输出：验证同一 FIFO 的双读口并发。
4. 同一输入、同一 VC、不同目的地：验证 VC 内 HOL + 输出顺序。
5. output0 反压：保持数据、不丢包，释放后继续。

结果：`PASS (9 packets)`；scoreboard 检查 payload/seq、SOP/EOP、目的、VC。

### 4.1 随机 trace

- 971 个包、2500 cycles（`load=0.9`、uniform1-8、multi2 VC）输入 RTL。
- 2600 cycles 内输出 893 个包；`data_errors=0`、`protocol_errors=0`。
- 相同 trace 跑 E1 模型：930 个包；RTL 的 893 个与模型全部重合，无 RTL-only 包。
- 早期 E1 模型是组合选择/组合输出仲裁，与 RTL 时序不一致；新建
  `scripts/model_e2.py` 按 RTL 状态机重建后，主矩阵 90/90、反压 15/15
  runs 全部 exact（包集合一致，每包 start/end 差 0）。
- 复现脚本：`scripts/run_e2_cosim.py`、`scripts/trace_to_csv.py`、
  `scripts/compare_e2_model.py`；报告：[`../reports/e2_cosim.md`](../reports/e2_cosim.md)。

## 5. 限制 / 下一步

- 逐 cycle co-sim 已覆盖 cell16/32/64、VC2/4、100%/75% ready；尚未覆盖
  hotspot/bursty、quota、过载 >1.0。
- 未做随机压力、输出 backpressure 全矩阵、SVA 运行时。
- `mo_fifo_top` / 集成层的 selection 暂用显式 `always_ff`，CBB 规范待重构。
- 下一步：先做 trace-driven co-sim（payload/包序/时序对齐），再跑
  `CELL_NUM=16/32/64` 的集成对比，最后回写 E2 报告。
