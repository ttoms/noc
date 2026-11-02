`default_nettype none
//==============================================================================
// Module : dff
// Description : 无复位数据通路寄存器，显式 en 便于插入 ICG
// Features :
//   - 无复位，避免数据通路复位树
//   - 显式 en，综合可识别时钟门控
// Parameters :
//   W - 数据位宽，默认 32
// Limitations :
//   - 仅用于数据通路；控制/状态寄存器请用 dffr
//==============================================================================
module dff #(
    parameter   int W   =   32
) (
    input   logic           clk ,
    input   logic           en  ,
    input   logic [W -1:0]  d   ,
    output  logic [W -1:0]  q
);

always_ff @(posedge clk) begin
    if (en) begin
        q <= d;
    end
end

endmodule

`default_nettype wire
