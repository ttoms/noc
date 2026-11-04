# Experiments

每个实验一个编号目录，命名格式：`<序号>-<主题>`。

- [1-2x2-crossbar-fifo-vs-voq](1-2x2-crossbar-fifo-vs-voq/README.md)
  - 2x2 packet crossbar：共享输入 FIFO vs per-destination VOQ
  - Phase 1：cycle-exact 模型 + RTL + 逐包/逐 cycle 验证
    （[REPORT.md](1-2x2-crossbar-fifo-vs-voq/REPORT.md)）
  - Phase 2：per-queue capacity 正交化，capacity × load × type × packet length ×
    traffic 全因子矩阵（[reports/phase2.md](1-2x2-crossbar-fifo-vs-voq/reports/phase2.md)）

每个实验目录自包含：README、REPORT、RTL、TB、模型、复现脚本、结果汇总。

- [2-shared-multi-output-fifo](2-shared-multi-output-fifo/README.md)
  - 1 write / N read 共享缓冲 FIFO；架构（C0/E0）+ E1 cycle model，暂无 RTL
  - 组件：`idpool`、`link_list`、`shared_buffer`、`mo_fifo_top`
  - E1 对比报告：[reports/e1_shared_fifo.md](2-shared-multi-output-fifo/reports/e1_shared_fifo.md)
