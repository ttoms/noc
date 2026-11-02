# Experiments

每个实验一个编号目录，命名格式：`<序号>-<主题>`。

- [1-2x2-crossbar-fifo-vs-voq](1-2x2-crossbar-fifo-vs-voq/README.md)
  - 2x2 packet crossbar：共享输入 FIFO vs per-destination VOQ
  - Phase 1：cycle-exact 模型 + RTL + 逐包/逐 cycle 验证
  - 报告：[REPORT.md](1-2x2-crossbar-fifo-vs-voq/REPORT.md)

每个实验目录自包含：README、REPORT、RTL、TB、模型、复现脚本、结果汇总。
