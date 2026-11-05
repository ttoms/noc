`default_nettype none
//==============================================================================
// Module : ohot_pri_enc
// Description : 优先编码器，输出最低索引有效位的二进制索引与有效标志，纯组合
// Features :
//   - req 全零时 idx=0、vld=0
//   - 多请求时索引最小者优先，与 arbiter_pri 优先级方向一致
//   - idx 位宽为 $clog2(IN_W)，IN_W=1 时为 1 bit
// Parameters :
//   IN_W - 请求位宽，默认 4，必须 >= 1
// Limitations :
//   - 高索引持续请求会被低索引饿死，固定优先级语义如此
//   - idx 只在 vld=1 时有意义，调用方必须用 vld 判定
//==============================================================================
module ohot_pri_enc #(
    parameter   int IN_W    =   4
) (
    input   logic [IN_W                      -1:0]  req ,
    output  logic [((IN_W>1)?$clog2(IN_W) :1)-1:0]  idx ,
    output  logic                                   vld
);

localparam int IDX_W = (IN_W > 1) ? $clog2(IN_W) : 1;

always_comb begin
    idx = '0;
    vld = 1'b0;
    for (int i = 0; i < IN_W; i++) begin
        if (req[i] && !vld) begin
            idx = IDX_W'(i);
            vld = 1'b1;
        end
    end
end

`ifdef SVA_ON
`include "ohot_pri_enc.sva"
`endif

endmodule

`default_nettype wire
