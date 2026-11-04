# E1 计划 — 共享缓冲多输出 FIFO 的 cycle model 与对比

> 状态：E1 模型 + 对比报告完成；RTL 未开始。
> 范围：模型 + 对比报告；本阶段不写 RTL。
> 上游决策：2026-11-04 与用户确认。

## 1. 目标

回答一个问题：在完整 2x2 交换机、相同总 buffer、相同每输入读带宽的前提下，
用“每输入一个 1W2R 共享 cell 池”替代“每输入每目的一个独立 VOQ 队列”，
吞吐/延迟/公平性会怎样变化；VC 与目的地解耦后，VC 内 HOL 的代价有多大。

## 2. 拓扑与口径

- 2 个输入、2 个输出。
- 每个输入一个 `mo_fifo_top` 实例：1 个写口、2 个读口、`CELL_NUM` 个共享 cell、
  `VC_NUM` 条 VC 链。
- 两个实例的读口接到每输出 2:1 仲裁；包粒度锁定到 EOP。
- **读口口径**：共享 FIFO 每输入最多 2 个读 flit/拍（完整 1W2R）；VOQ 基线
  每输入 1 个读 flit/拍。因此吞吐差异同时包含端口数优势，报告必须标注，
  不能单独归因于 cell 池共享。
- 基线：实验 1 `model_v2.py` 的 `voq` 模式，完整 2x2、每输入每目的一个队列。
- 等总 buffer：
  - 共享：每输入 `CELL_NUM`，整机 `2 × CELL_NUM`。
  - VOQ：每队列 `CELL_NUM / 2`，整机 `2 输入 × 2 目的 × CELL_NUM/2 = 2 × CELL_NUM`。
  - 首轮 `CELL_NUM = 16/32/64`，对应 VOQ 队列深度 `8/16/32`。

## 3. VC 配置

- `per_dst`：`VC_NUM=2`，`vc = dst`。每个 VC 只承载一个目的地，无 VC 内 HOL。
  这是与 VOQ 最干净的 apples-to-apples 对比。
- `multi2`：`VC_NUM=2`，`vc` 与 `dst` 独立随机。一个 VC 可承载多个目的地，
  会出现 VC 内 HOL；用于量化“VC 与目的解耦”的代价。
- 扩展（首轮结果稳定后再跑）：`multi4`（`VC_NUM=4`，vc 随机），观察更多 VC
  是否能缓解 VC 内 HOL。

## 4. 流量与矩阵

- 包长：`uniform1-8`；流量：`uniform`。
- 到达：每输入 Bernoulli，目标 flit 速率 `load`；`load = 0.8/0.95/1.0`。
- seeds：1–5，配对比较。
- 4000 cycles，warmup 500；`SOURCE_GAP=0`；输出 `out_rdy=1`。
- 首轮共 `3 capacity × 3 load × 5 seeds × (per_dst + multi2 + VOQ)` = 135 runs。
- 扩展（如首轮方向稳定）：`multi4`、输出周期性反压、fixed1/fixed8、hotspot/bursty。

## 5. 模型语义（cycle-exact 约定）

- 源：每输入最多 1 个 outstanding packet；包在 `arrival` 拍载入，下一拍开始写；
  背靠背包在最后一个 flit 的边沿载入下一个已到达包（gap=0）。
- 写侧：`in_rdy` 在拍首看共享池是否有空 cell；本拍读释放的 cell 不用于本拍写
  （与实验 1 的 `fifo_sync` 起始占用口径一致）。同拍 alloc/free 作为后续扩展单独测。
- 读侧：每拍拍首看到的 head 参与仲裁；写在本拍末尾提交，下一拍可见。
- 共享 FIFO 内：每输出在“head.dst==o 且未被其他输出锁定”的 VC 中做 RR；
  输出锁定到 (input, vc) 后只服务该 VC，直到 EOP。
- 每输入每拍最多 2 个读 flit（每个输出一个读口）；两个输出可同时读同一输入的
  不同 VC；同一 VC 不能被两个输出同时读。VOQ 基线仍限每输入 1 读/拍。
- 单 flit 包不进入多拍锁定；多 flit 包 SOP 后锁定，EOP 释放。
- 不丢包：池满只反压写侧；任何 cell 只在读握手后释放。

## 6. 指标

- 吞吐：逐 flit `out_vld && out_rdy` 握手；`utilization = delivered_flits / (2 × cycles)`。
- 延迟：admission latency = `end - accepted`（主指标）；arrival latency 仅作参考。
- 占用：每输入 cell 池平均/最大占用、池利用率。
- 反压/阻塞：源端 stall、输出反压、输出仲裁失败、VC 内 HOL 代理计数。
- 公平性：每输入/每输出 flit 的 Jain 指数。
- 正确性：每拍不变量检查；运行结束 `lifetime_alloc - lifetime_free == 占用`。

## 7. 不变量

- 每输入：`free + Σ|VC 链| == CELL_NUM`；cell ID 不重复、不泄漏。
- 每个 VC 链内 flit 序号连续，包边界不交错；cell 的 `vc/dst` 与所在链一致。
- 输出锁定的 VC 属于该输入，且同一 VC 不同时被两个输出锁定。
- 输出传输的 flit 序号连续；非 SOP 只能出现在锁定输出上；EOP 必须等于包长-1。
- 无 cell 重复释放；无未读释放；运行结束无泄漏。

## 8. 验收与交付

- 模型通过定向测试与随机 trace 的每拍不变量检查。
- 135 runs 全部无断言失败；5 seeds 配对 95% t CI。
- `reports/e1_shared_fifo.md`：口径、结果、VC HOL 代价、限制与下一步。
- 原始数据：`results/e1/raw_runs.json`、`summary.csv`、`paired.csv`。

## 9. 明确不做

- 不写 RTL、不做 RTL/model 逐 cycle 联仿（E2 阶段）。
- 不做 quota（v1 只留钩子）。
- 不做 wormhole 跨包 flit 交织。
- 不做多写口、CDC、ECC、动态 cell 大小。
