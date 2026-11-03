#!/usr/bin/env bash
# Build the three crossbar TBs with SVA_ON runtime assertions.
# Icarus 11 does not support concurrent `assert property`; the .sva files are
# immediate assertions executed at posedge.
set -euo pipefail
cd "$(dirname "$0")/.."

CBB_RTL="${CBB_RTL:-vendor/cbb/rtl}"
OUT="${OUT:-build/sva}"
mkdir -p "$OUT"

for dut in fifo voq xp; do
    iverilog -g2012 -DSVA_ON -I sva -I "$CBB_RTL" \
        -o "$OUT/${dut}_tb" \
        "rtl/xbar_2x2_${dut}.sv" \
        "tb/xbar_2x2_${dut}_tb.sv" \
        "$CBB_RTL/memory/fifo_sync.sv" \
        "$CBB_RTL/arbiter/arbiter_rr.sv" \
        "$CBB_RTL/arbiter/pri_tree.sv" \
        "$CBB_RTL/arbiter/suf_or.sv" \
        "$CBB_RTL/util/bin2ohot.sv" \
        "$CBB_RTL/basic/dff.sv" \
        "$CBB_RTL/basic/dffr.sv"
    echo "built $OUT/${dut}_tb"
done
