`default_nettype none
//==============================================================================
// Module : fifo_sync
// Description : 同步 FIFO，单时钟域，每拍 1 项吞吐
// Features :
//   - 参数化位宽/深度，DEPTH 必须为 2 的幂且 >= 2
//   - valid-ready 接口，show-ahead 组合读
//   - 控制状态用 dffr，存储体用 dff（无复位）
//   - full/empty 由状态寄存器输出，不在输出端做组合译码
// Parameters :
//   DATA_W - 数据位宽，默认 32
//   DEPTH  - 深度，默认 16（2 的幂且 >= 2）
// Limitations :
//   - 单时钟域；跨时钟域请用异步 FIFO
//   - 组合读数据，rd_data 仅在 rd_vld 有效时可信
//   - 满时同拍读出的空位不能用于当拍写入
//==============================================================================
module fifo_sync #(
    parameter   int DATA_W  =   32  ,
    parameter   int DEPTH   =   16
) (
    input   logic               clk     ,
    input   logic               rst_n   ,
    input   logic               wr_vld  ,
    output  logic               wr_rdy  ,
    input   logic [DATA_W -1:0] wr_data ,
    output  logic               rd_vld  ,
    input   logic               rd_rdy  ,
    output  logic [DATA_W -1:0] rd_data ,
    output  logic               empty   ,
    output  logic               full
);

localparam int PTR_W = $clog2(DEPTH);

// 寄存器阵列用 packed 二维数组（不是 unpacked 数组）
logic [DEPTH-1:0][DATA_W-1:0] mem;

logic [DEPTH -1:0]  entry_vld       ;
logic [DEPTH -1:0]  nxt_entry_vld   ;
logic [DEPTH -1:0]  wr_oh           ;
logic [DEPTH -1:0]  rd_oh           ;
logic [PTR_W -1:0]  wr_ptr          ;
logic [PTR_W -1:0]  rd_ptr          ;
logic [PTR_W -1:0]  nxt_wr_ptr      ;
logic [PTR_W -1:0]  nxt_rd_ptr      ;
logic               wr_en           ;
logic               rd_en           ;
logic               entry_vld_en    ;
logic               empty_q         ;
logic               full_q          ;
logic               nxt_empty       ;
logic               nxt_full        ;

assign wr_en        = wr_vld && wr_rdy;
assign rd_en        = rd_vld && rd_rdy;
assign wr_rdy       = ~full_q;
assign rd_vld       = ~empty_q;
assign empty        = empty_q;
assign full         = full_q;
assign nxt_wr_ptr   = wr_ptr + 1'b1;
assign nxt_rd_ptr   = rd_ptr + 1'b1;
assign entry_vld_en = wr_en | rd_en;

// 指针 → 独热：用 CBB bin2ohot，不手写移位
bin2ohot #(
    .N  (DEPTH  )
) U_WR_OH (
    .bin    (wr_ptr ),
    .ohot   (wr_oh  )
);

bin2ohot #(
    .N  (DEPTH  )
) U_RD_OH (
    .bin    (rd_ptr ),
    .ohot   (rd_oh  )
);

// 独热掩码：一个解码器代替每项一个比较器；写优先于同拍读同一项
assign nxt_entry_vld = (entry_vld & ~(rd_en ? rd_oh : '0))
                     | (wr_en ? wr_oh : '0);

// full/empty 由寄存器输出，且与 entry_vld 同一拍更新
assign nxt_empty = ~|nxt_entry_vld;
assign nxt_full  = &nxt_entry_vld;

always_comb begin
    rd_data = mem[rd_ptr];
end

dffr #(
    .W          (PTR_W  ),
    .RESET_VAL  ('0     )
) U_WR_PTR (
    .clk    (clk        ),
    .rst_n  (rst_n      ),
    .en     (wr_en      ),
    .d      (nxt_wr_ptr ),
    .q      (wr_ptr     )
);

dffr #(
    .W          (PTR_W  ),
    .RESET_VAL  ('0     )
) U_RD_PTR (
    .clk    (clk        ),
    .rst_n  (rst_n      ),
    .en     (rd_en      ),
    .d      (nxt_rd_ptr ),
    .q      (rd_ptr     )
);

dffr #(
    .W          (DEPTH  ),
    .RESET_VAL  ('0     )
) U_ENTRY_VLD (
    .clk    (clk            ),
    .rst_n  (rst_n          ),
    .en     (entry_vld_en   ),
    .d      (nxt_entry_vld  ),
    .q      (entry_vld      )
);

dffr #(
    .W          (1      ),
    .RESET_VAL  (1'b1   )
) U_EMPTY (
    .clk    (clk            ),
    .rst_n  (rst_n          ),
    .en     (entry_vld_en   ),
    .d      (nxt_empty      ),
    .q      (empty_q        )
);

dffr #(
    .W          (1      ),
    .RESET_VAL  (1'b0   )
) U_FULL (
    .clk    (clk            ),
    .rst_n  (rst_n          ),
    .en     (entry_vld_en   ),
    .d      (nxt_full       ),
    .q      (full_q         )
);

generate
    for (genvar i = 0; i < DEPTH; i++) begin : gen_mem
        logic entry_wr_en;

        assign entry_wr_en = wr_en && wr_oh[i];

        dff #(
            .W  (DATA_W )
        ) U_MEM (
            .clk    (clk            ),
            .en     (entry_wr_en    ),
            .d      (wr_data        ),
            .q      (mem[i]         )
        );
    end
endgenerate

`ifdef SVA_ON
`include "fifo_sync.sva"
`endif

endmodule

`default_nettype wire
