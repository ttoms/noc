`default_nettype none
//==============================================================================
// Module : dffr
// Description : 带异步复位与显式 en 的寄存器单元
// Features :
//   - 异步复位、同步释放（复位释放由 rst_sync 保证）
//   - 显式 en，综合可识别时钟门控
// Parameters :
//   W         - 数据位宽，默认 32
//   RESET_VAL - 复位值，默认 0
// Limitations :
//   - 复位值必须是常量
//==============================================================================
module dffr #(
    parameter   int             W           =   32  ,
    parameter   logic [W-1:0]   RESET_VAL   =   '0
) (
    input   logic           clk     ,
    input   logic           rst_n   ,
    input   logic           en      ,
    input   logic [W -1:0]  d       ,
    output  logic [W -1:0]  q
);

always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        q <= RESET_VAL;
    end else if (en) begin
        q <= d;
    end
end

endmodule

`default_nettype wire
