`default_nettype none
//==============================================================================
// Module : idpool
// Description : 固定数量 ID 的分配/回收池，位图 + 优先编码
// Features :
//   - 1 个 alloc 端口 + N_FREE 个 free 端口
//   - 同拍 alloc + free 支持；本拍释放的 ID 可被本拍分配复用
//   - 最低空闲 ID 优先，分配结果确定
//   - 每个 free 端口独立报告“释放已空闲 ID”，不破坏池状态
//   - empty 表示本拍无可用 ID（含同拍释放），full 表示当前已全占用
// Parameters :
//   ID_NUM - ID 数量，默认 16，必须是 2 的幂且 >= 2
//   N_FREE - free 端口数，默认 1，必须 >= 1
//   ID_W   - ID 位宽，默认 $clog2(ID_NUM)
//   CNT_W  - 计数位宽，默认 $clog2(ID_NUM+1)
// Limitations :
//   - 位图 + 优先编码为 O(ID_NUM) 组合逻辑，适合中小规模 cell 池
//   - 同一 ID 被多个 free 端口同拍释放时只释放一次；调用方应避免重复释放
//   - full 是当前占用状态；同拍 free_req 时 alloc_rdy 仍可能为 1
//==============================================================================
module idpool #(
    parameter   int ID_NUM  =   16                                  ,
    parameter   int N_FREE  =   1                                   ,
    parameter   int ID_W    =   (ID_NUM > 1) ? $clog2(ID_NUM) : 1   ,
    parameter   int CNT_W   =   $clog2(ID_NUM + 1)
) (
    input   logic                       clk         ,
    input   logic                       rst_n       ,
    input   logic                       alloc_req   ,
    output  logic                       alloc_rdy   ,
    output  logic [ID_W        -1:0]    alloc_id    ,
    input   logic [N_FREE      -1:0]    free_req    ,
    input   logic [N_FREE*ID_W -1:0]    free_id     ,
    output  logic [N_FREE      -1:0]    free_err    ,
    output  logic                       empty       ,
    output  logic                       full        ,
    output  logic [CNT_W       -1:0]    count
);

localparam logic [ID_NUM -1:0] ONE        = 1'b1;
localparam logic [ID_NUM -1:0] ALL_FREE  = '1;

logic [ID_NUM -1:0] free_mask       ;
logic [ID_NUM -1:0] free_mask_eff   ;
logic [ID_NUM -1:0] free_bits_union ;
logic [ID_NUM -1:0] free_new_bits   ;
logic [ID_NUM -1:0] nxt_free_mask   ;
logic               alloc_vld       ;
logic               alloc_en        ;
logic               mask_en         ;
logic [CNT_W  -1:0] free_count      ;
logic [CNT_W  -1:0] nxt_count       ;

function automatic logic [CNT_W-1:0] popcount(
    input logic [ID_NUM-1:0] v
);
    logic [CNT_W-1:0] c;
    c = '0;
    for (int i = 0; i < ID_NUM; i++) begin
        c = c + CNT_W'(v[i]);
    end
    return c;
endfunction

function automatic logic [ID_NUM-1:0] collect_free_bits(
    input logic [N_FREE    -1:0] req,
    input logic [N_FREE*ID_W-1:0] id
);
    logic [ID_NUM-1:0] bits;
    bits = '0;
    for (int p = 0; p < N_FREE; p++) begin
        if (req[p]) begin
            bits[id[p*ID_W +: ID_W]] = 1'b1;
        end
    end
    return bits;
endfunction

generate
    for (genvar p = 0; p < N_FREE; p++) begin : g_free_err
        assign free_err[p] = free_req[p]
                           && free_mask[free_id[p*ID_W +: ID_W]];
    end
endgenerate

assign free_bits_union = collect_free_bits(free_req, free_id);
assign free_mask_eff   = free_mask | free_bits_union;
assign free_new_bits   = free_bits_union & ~free_mask;
assign free_count      = popcount(free_new_bits);
assign alloc_en        = alloc_req && alloc_rdy;
assign empty           = ~alloc_rdy;
assign full            = (count == CNT_W'(ID_NUM));

ohot_pri_enc #(
    .IN_W   (ID_NUM )
) U_ALLOC_ENC (
    .req    (free_mask_eff  ),
    .idx    (alloc_id       ),
    .vld    (alloc_vld      )
);

assign alloc_rdy = alloc_vld;

assign nxt_free_mask = (free_mask | free_bits_union)
                     & ~(alloc_en ? (ONE << alloc_id) : {ID_NUM{1'b0}});
assign nxt_count     = count + CNT_W'(alloc_en) - free_count;
assign mask_en       = (|free_new_bits) || alloc_en;

dffr #(
    .W          (ID_NUM     ),
    .RESET_VAL  (ALL_FREE   )
) U_FREE_MASK (
    .clk    (clk            ),
    .rst_n  (rst_n          ),
    .en     (mask_en        ),
    .d      (nxt_free_mask  ),
    .q      (free_mask      )
);

dffr #(
    .W          (CNT_W  ),
    .RESET_VAL  ('0     )
) U_COUNT (
    .clk    (clk        ),
    .rst_n  (rst_n      ),
    .en     (mask_en    ),
    .d      (nxt_count  ),
    .q      (count      )
);

`ifdef SVA_ON
`include "idpool.sva"
`endif

endmodule

`default_nettype wire
