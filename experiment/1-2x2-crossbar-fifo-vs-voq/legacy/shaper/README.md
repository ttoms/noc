# Legacy: shaper negative result

这里保留早期“flow shaper 是否提高 crossbar 总吞吐”的探索代码。

结论：在 work-conserving、无丢包、冲突排队的 crossbar 里，限流没有提高总吞吐；FIFO 的瓶颈是 HOL，正确方向是 VOQ/输出队列，而不是限流。代码仅作过程记录，不属于 Phase 1 主线。
