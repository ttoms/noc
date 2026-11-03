# Vendored CBB

本实验只引用 `ttoms/cbb_proj` 的 CBB，不在 NOC 内修改 CBB 源码。

计划固定版本（架构阶段，尚未复制 RTL）：

- `idpool`：CBB-ORDER-002，待架构
- `link_list`：CBB-ORDER-001，待架构
- `shared_buffer`：CBB-MEM-003，待架构
- `mo_fifo_top`：CBB-STREAM-007，待架构
- `arbiter_wrapper`：CBB-ARB-006，已发布
- `dff` / `dffr`：CBB-BASIC，已发布

等 CBB 架构评审通过、RTL 落地后，再把对应源码复制到 `vendor/cbb/rtl/`
并记录 commit hash；当前目录只放依赖说明。
