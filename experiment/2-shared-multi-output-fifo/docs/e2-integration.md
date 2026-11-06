# E2 — 2x2 集成 RTL（定向 TB）

> 状态：集成 RTL + 定向 TB + trace TB + 逐包逐 cycle co-sim 完成（185/185 exact；cell16/32/64、VC2/4、100%/75% ready、uniform/hotspot/bursty、fixed1/fixed8）。
> CBB pin：`cbb_proj` `1fd7337`，见 `vendor/cbb/README.md`。

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
- CBB：`vendor/cbb/rtl/...`（只读副本，pin `1fd7337`）
- 参数：`FLIT_W`、`N`、`VC_NUM`、`CELL_NUM`、`DST_W`、`VC_W`、`QUOTA_W`。
- v1 无 quota；`quota_en`/`quota` 在集成层 tied off。

## 3. 输出仲裁语义

- 每个输出维护 `locked/locked_in`：
  - 未锁定时，对两个输入 FIFO 的 `out_vld` 做 RR；选中即锁存输入。
  - 下游未 ready 时也锁存，保证 `out_vld/data` 稳定。
  - 锁定后只把 `out_rdy` 回给该输入；输入 FIFO 自身再锁到 (vc) 到 EOP。
  - 收到 EOP 握手后解锁。
- 选中输入的 `out_sop/eop/data/vc` 直接 mux 到输出；未选中输入 `out_rdy=0`。
- 输出锁 `locked/locked_in` 使用 `dffr` + 连续 next-state/enable；`req` 也改为
  连续赋值。`mo_fifo_top` 的 selection 同样使用 `dffr` + 连续逻辑。
  不要把 next-state 放回单个 `always_comb`：iverilog 11 下 `always_comb` +
  `dffr` 会形成零延迟环（`always @*` 可绕过但违反规范）。

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

- 逐 cycle co-sim 已覆盖 cell16/32/64、VC2/4、100%/75% ready、
  uniform/hotspot/bursty、fixed1/fixed8。
- **明确不在 E2 v1 范围**：quota（只留钩子，端口 tied off）；过载 >1.0
  （写侧只有 1 个写口，物理上不能注入 >1 flit/cycle；要测需多源/多写口）；
  多 outstanding source（当前源模型每输入 1 个未完成包，是激励模型限制，
  不是 RTL 限制）。
- 顶层 SVA 未运行：依赖子 CBB 并发 SVA，iverilog 11 不支持整体 `-DSVA_ON` 编译；
  定向 TB 和 trace TB 已做协议检查。
- 结果与复现见 [`../reports/e2_cosim.md`](../reports/e2_cosim.md)。
