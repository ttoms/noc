`default_nettype none
//==============================================================================
// Module : bin2ohot
// Description : 二进制到独热译码器，输出路数 N 任意（不要求 2 的幂）
// Features :
//   - bin < N 时输出恰好一位有效
//   - bin >= N（越界编码）时输出全 0
//   - 输入位宽为 $clog2(N)，N=1 时为 1 bit
// Parameters :
//   N - 独热输出路数，默认 16，必须 >= 1；不要求 2 的幂
// Limitations :
//   - 纯组合译码器，面积随 N 线性增长
//   - 越界编码输出全 0，调用方需自行判断（或保证输入范围）
//==============================================================================
module bin2ohot #(
    parameter   int N   =   16
) (
    input   logic [((N>1)?$clog2(N) :1)-1:0]    bin     ,
    output  logic [N                   -1:0]    ohot
);

localparam int SEL_W = (N > 1) ? $clog2(N) : 1;
localparam logic [SEL_W:0] N_LIMIT = (SEL_W+1)'(N);

always_comb begin
    ohot = '0;
    if ({1'b0, bin} < N_LIMIT) begin
        ohot[bin] = 1'b1;
    end
end

`ifdef SVA_ON
`include "bin2ohot.sva"
`endif

endmodule

`default_nettype wire
