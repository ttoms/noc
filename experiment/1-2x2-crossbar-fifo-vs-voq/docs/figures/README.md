# Figures

这些图是手写 SVG，再用 headless Chrome 渲染成 PNG；不使用 ASCII / Mermaid。

- `fifo-architecture.svg/png`：IQ-FIFO 结构
- `voq-architecture.svg/png`：IQ-VOQ 结构
- `xp-architecture.svg/png`：per-crosspoint FIFO（Phase 3 planned）
- `verification-flow.svg/png`：模型/RTL 共用 trace 的逐包/逐 cycle 验证流程

重新渲染：

```bash
bash scripts/render_figures.sh
```

依赖：`google-chrome` 或 `chromium`。PNG 是提交产物；SVG 是可编辑源文件。
