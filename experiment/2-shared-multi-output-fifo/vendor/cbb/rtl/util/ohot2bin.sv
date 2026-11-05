`default_nettype none
//==============================================================================
// Module : ohot2bin
// Description : 独热到二进制编码器，带有效标志，纯组合
// Features :
//   - 全零输入返回 bin=0、vld=0
//   - 多热输入取最高位索引，不报错
//   - bin 位宽为 $clog2(IN_W)，IN_W=1 时为 1 bit
// Parameters :
//   IN_W - 独热输入位宽，默认 4，必须 >= 1
// Limitations :
//   - 不校验独热合法性，多热语义由调用方按需检查
//==============================================================================
module ohot2bin #(
    parameter   int IN_W    =   4
) (
    input   logic [IN_W                      -1:0]  ohot    ,
    output  logic [((IN_W>1)?$clog2(IN_W) :1)-1:0]  bin     ,
    output  logic                                   vld
);

localparam int OUT_W = (IN_W > 1) ? $clog2(IN_W) : 1;

always_comb begin
    bin = '0;
    vld = 1'b0;
    for (int i = 0; i < IN_W; i++) begin
        if (ohot[i]) begin
            bin = OUT_W'(i);
            vld = 1'b1;
        end
    end
end

`ifdef SVA_ON
`include "ohot2bin.sva"
`endif

endmodule

`default_nettype wire
