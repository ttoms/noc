`default_nettype none
//==============================================================================
// Module : shared_buffer
// Description : cell-based 共享存储，1 写端口 + N 个独立组合读端口
// Features :
//   - 写地址由上层（idpool）分配；写只在 wr_vld 时生效
//   - 读为组合读，rd_data[i] 与 rd_addr[i] 同拍有效
//   - 同拍 1 写 + N 读允许；同地址读写为 read-old-data 语义
// Parameters :
//   DATA_W   - 每个 cell 的数据位宽，默认 32
//   CELL_NUM - cell 数量，默认 64，必须是 2 的幂且 >= 2
//   N        - 读端口数，默认 2，必须 >= 1
// Limitations :
//   - 不做读写冲突检测；上层必须保证地址生命周期正确
//   - 存储体不复位；未写过的 cell 读出为 X（仿真）或未定义（综合）
//   - 组合读的 N 选一 mux 会随时延随 N 增长，大 N 需上层加流水
//==============================================================================
module shared_buffer #(
    parameter   int DATA_W      =   32                  ,
    parameter   int CELL_NUM    =   64                  ,
    parameter   int N           =   2                   ,
    parameter   int ADDR_W      =   $clog2(CELL_NUM)
) (
    input   logic                   clk     ,
    input   logic                   rst_n   ,
    input   logic                   wr_vld  ,
    output  logic                   wr_rdy  ,
    input   logic [ADDR_W   -1:0]   wr_addr ,
    input   logic [DATA_W   -1:0]   wr_data ,
    input   logic [N        -1:0]   rd_vld  ,
    output  logic [N        -1:0]   rd_rdy  ,
    input   logic [N*ADDR_W -1:0]   rd_addr ,
    output  logic [N*DATA_W -1:0]   rd_data
);

logic [DATA_W-1:0] mem [CELL_NUM];
logic              unused_nc;

assign wr_rdy   = 1'b1;
assign rd_rdy   = {N{1'b1}};
assign unused_nc = &{1'b0, rst_n};

always_ff @(posedge clk) begin
    if (wr_vld) begin
        mem[wr_addr] <= wr_data;
    end
end

generate
    for (genvar i = 0; i < N; i++) begin : g_rd
        assign rd_data[i*DATA_W +: DATA_W] =
            rd_vld[i] ? mem[rd_addr[i*ADDR_W +: ADDR_W]] : '0;
    end
endgenerate

`ifdef SVA_ON
`include "shared_buffer.sva"
`endif

endmodule

`default_nettype wire
