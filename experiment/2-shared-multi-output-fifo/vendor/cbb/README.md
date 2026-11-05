# Vendored CBB

本实验只引用 `ttoms/cbb_proj` 的 CBB；`vendor/` 是固定 commit 的只读副本，
不在 NOC 内修改 CBB 源码。

- 上游仓库：`git@github.com:ttoms/cbb_proj.git`
- 固定 commit：`af593e9`（feat(stream): add mo_fifo_top shared multi-output FIFO RTL）
- 复制日期：2026-11-05

包含：

- `rtl/order/idpool.sv`（CBB-ORDER-002）：1 alloc + N free。
- `rtl/order/link_list.sv`（CBB-ORDER-001）：1 push + N pop，per-VC 链 + dst sideband。
- `rtl/memory/shared_buffer.sv`（CBB-MEM-003）：1W N R 组合读。
- `rtl/stream/mo_fifo_top.sv`（CBB-STREAM-007）：1W N R 共享 FIFO 顶层。
- 依赖：`arbiter_rr`、`pri_tree`、`suf_or`、`ohot2bin`、`ohot_pri_enc`、`dffr`。
- `sva/`：对应模块的即时断言文件。

注意：`mo_fifo_top` 的 selection 寄存器暂用显式 `always_ff`，是 CBB 规范例外；
等上游 root-cause 后改回 `dffr`，届时更新 pin。
