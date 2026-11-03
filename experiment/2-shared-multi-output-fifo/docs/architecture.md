# Shared-buffer Multi-output FIFO — 架构（C0/E0）

> 状态：架构评审稿；没有 RTL、没有时序/面积数据。
> 约束：1 write / N read；flit 级；cut-through；no-drop；v1 无 quota。

## 1. 参数

| 参数 | 含义 | v1 约束 |
|---|---|---|
| `FLIT_W` | flit payload 位宽 | ≥1 |
| `N` | 输出端口数 / 读端口数 | ≥1 |
| `VC_NUM` | VC 数 | ≥1，独立于 `N` |
| `CELL_NUM` | 共享缓冲 cell 数 | 2 的幂，≥2 |
| `DST_W` | 输出编号位宽 | `$clog2(N)` |
| `VC_W` | VC 编号位宽 | `$clog2(VC_NUM)` |

元数据随 cell 存储：`sop/eop/vc/dst`；payload 单独字段。cell 宽度由顶层
`shared_buffer` 的 `DATA_W` 承载，避免 metadata RAM 与 payload RAM 两套读口。

## 2. 模块划分

| 模块 | 职责 | 状态 |
|---|---|---|
| `idpool` | 分配/回收 cell ID；维护 free count；空/满 | 待架构（CBB-ORDER-002） |
| `link_list` | 每 VC 的 FIFO 链；push/pop/advance；head/tail/next | 待架构（CBB-ORDER-001） |
| `shared_buffer` | 1W N R cell RAM；每读口独立地址/数据 | 新增 CBB-MEM-003 |
| `mo_fifo_top` | 集成、反压、每输出 VC 仲裁、EOP 释放、quota 钩子 | 新增 CBB-STREAM-007 |

每输出 VC 仲裁使用 `arbiter_wrapper`（默认 `ARB_RR`）+ head-address mux，
**不是 `strmux`**：1W N R 的每个输出只有一个读口，无法同时把 N 个 VC 的
payload 都送到 `strmux` 的 N 路输入；`strmux` 适合外部链路层多流汇聚。

## 3. 接口

### 3.1 写侧（单口）

| 信号 | 方向 | 说明 |
|---|---|---|
| `in_vld` | in | flit 有效 |
| `in_rdy` | out | cell 可分配且目标 VC 可入队 |
| `in_data` | in | `FLIT_W` payload |
| `in_sop/eop` | in | 包边界；同一包的 flit 连续 |
| `in_vc` | in | VC 编号 |
| `in_dst` | in | 目标输出编号 |

### 3.2 读侧（每输出一套）

| 信号 | 方向 | 说明 |
|---|---|---|
| `out_vld[o]` | out | 本输出有可读 head |
| `out_rdy[o]` | in | 下游 ready |
| `out_data[o]` | out | payload |
| `out_sop/eop[o]` | out | 包边界 |
| `out_vc[o]` | out | 当前服务的 VC |

### 3.3 cell 生命周期

1. 写侧握手：`idpool.alloc` 得到 `cell_id`；`shared_buffer` 写入 payload+metadata；
   `link_list.push(vc, cell_id)`。
2. 读侧：每输出从“head.dst == o”的 VC 中仲裁；用 head cell ID 读
   `shared_buffer`；握手后 `link_list.advance(vc)`。
3. EOP 握手：释放当前 cell；该 VC 的包结束，输出解除锁定。
4. 非 EOP：当前 cell 在读握手后即可释放；下一 cell 成为 head。
5. 任一步失败（池空/队列满/读口冲突）只反压，不丢 cell。

## 4. 仲裁与锁定

- 每输出一个 `arbiter_wrapper`，请求位为“该 VC 非空且 head.dst==o”。
- 已锁定输出只向当前 VC 发请求；其他 VC 被屏蔽。
- SOP 选中 VC 后锁定到 EOP；单 flit 包（SOP=EOP）不进入锁定态。
- 同一 VC 不能被两个输出同时服务；输出锁定时，其 VC 从其他输出请求中移除。
- 读口仲裁只看 head 元数据，不需要预读 payload；payload 在选中后从
  `shared_buffer` 读出。

## 5. Quota（v1 不做，只留钩子）

- v1：`quota_en=0`，一个 VC 可以占满整个 `CELL_NUM`。
- 后续：每 VC 一个 cell 计数；入队前检查 `used[vc] < quota[vc]`，超限只反压
  该 VC 的写侧。
- quota **只按 VC**，不按 output；输出仲裁不感知 quota，避免把“VC 限流”变成
  “输出带宽分配”。
- 需要额外考虑：单 VC 多目的地时的 head 阻塞；quota 不解决 HOL，属于后续
  VOQ/多队列扩展。

## 6. 时序与反压

- `shared_buffer` 读数据同拍有效（组合读）或固定 1 拍（寄存读），二选一；
  v1 建议组合读，先保证 cycle-exact 简单。
- `idpool` 分配/回收各 1 次/拍；同拍 alloc+free 必须支持，否则回收气泡会
  直接掉吞吐。
- `link_list` 每 VC 每拍最多 1 次 push / 1 次 pop；跨 VC 并行。
- 写侧 `in_rdy = idpool_not_empty && target_vc_can_push && quota_ok`；
  读侧 `out_vld = vc_not_empty && head.dst==o`。
- 输出 stall 时 head 不动，cell 不释放；输入可继续写入其他 VC，直到 cell 池满。

## 7. 验证计划

- 定向：单 VC/多 VC、单 flit/多 flit、同 VC 多目的地、N=1/2/4、池满、队列空、
  同拍 alloc/free、EOP 释放、输出反压、单 VC 占满池。
- 随机：1W N R 随机流量 + 随机 `out_rdy`，模型/RTL 逐包逐 cycle 比较。
- 断言：cell 不重复分配/释放、链不丢节点、head.dst 合法、输出锁到 EOP、
  池计数守恒、无 cell 泄漏。
- 性能：吞吐/延迟 vs `CELL_NUM`、`VC_NUM`、N、包长、输出 ready duty；
  quota 开启后单 VC 限流对总吞吐的影响。

## 8. 未决问题

- VC 是否允许一个 VC 内多目的地（当前按 `dst` 逐包判断，会产生 VC 内 HOL）。
- head metadata 放 `link_list` 还是 `shared_buffer`；前者读口小，后者省一次查表。
- 非 EOP cell 是否立即释放，还是包结束统一释放；前者省容量，后者简化链表。
- 读口组合读的 N 选一 mux 时序；大 N 时是否需要分级/寄存。
- quota 计数放 `idpool` 还是 `mo_fifo_top`；建议顶层，保持 idpool 通用。
