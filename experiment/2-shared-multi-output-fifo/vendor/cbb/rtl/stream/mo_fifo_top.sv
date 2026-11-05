`default_nettype none
//==============================================================================
// Module : mo_fifo_top
// Description : 1 write / N read 共享缓冲 FIFO 顶层，cell 池 + per-VC 链
// Features :
//   - idpool + shared_buffer + link_list + 每输出 RR 仲裁
//   - 包粒度 cut-through；输出选中的 VC 由 vc_locked 锁定到 EOP
//   - 每输出一个读口；多个输出可同拍读同一输入的不同 VC
//   - 同拍 alloc + N free；本拍释放的 cell 可被本拍写入复用
//   - v1 不做 quota；quota 端口保留，当前忽略
// Parameters :
//   FLIT_W   - payload 位宽，默认 32
//   N        - 输出/读端口数，默认 2，必须 >= 1
//   VC_NUM   - VC 数，默认 2，必须是 2 的幂且 >= 2
//   CELL_NUM - 共享 cell 数，默认 16，必须是 2 的幂且 >= 2
//   DST_W    - 目的编号位宽，默认 $clog2(N)
//   VC_W     - VC 编号位宽，默认 $clog2(VC_NUM)
//   QUOTA_W  - quota 位宽，默认 8（v1 忽略）
// Limitations :
//   - v1 无 quota/wormhole/多写口/CDC/ECC
//   - 输出仲裁为寄存选择：选中后下一拍才可能输出，比组合仲裁多 1 拍
//   - 每个输出每拍最多读 1 个 cell；同一 VC 不会被两个输出同时选中
//   - 同拍写和读同一 cell 依赖 shared_buffer 的 read-old-data 语义
//==============================================================================
module mo_fifo_top #(
    parameter   int FLIT_W      =   32                                  ,
    parameter   int N           =   2                                   ,
    parameter   int VC_NUM      =   2                                   ,
    parameter   int CELL_NUM    =   16                                  ,
    parameter   int DST_W       =   (N > 1) ? $clog2(N) : 1             ,
    parameter   int VC_W        =   (VC_NUM > 1) ? $clog2(VC_NUM) : 1   ,
    parameter   int QUOTA_W     =   8
) (
    input   logic                       clk         ,
    input   logic                       rst_n       ,
    input   logic                       in_vld      ,
    output  logic                       in_rdy      ,
    input   logic [FLIT_W         -1:0] in_data     ,
    input   logic                       in_sop      ,
    input   logic                       in_eop      ,
    input   logic [VC_W           -1:0] in_vc       ,
    input   logic [DST_W          -1:0] in_dst      ,
    output  logic [N              -1:0] out_vld     ,
    input   logic [N              -1:0] out_rdy     ,
    output  logic [N*FLIT_W       -1:0] out_data    ,
    output  logic [N              -1:0] out_sop     ,
    output  logic [N              -1:0] out_eop     ,
    output  logic [N*VC_W         -1:0] out_vc      ,
    input   logic                       quota_en    ,
    input   logic [VC_NUM*QUOTA_W -1:0] quota
);

localparam int ID_W   = $clog2(CELL_NUM);
localparam int ADDR_W = ID_W;
localparam int CELL_W = FLIT_W + 2;

logic [ID_W         -1:0]   alloc_id    ;
logic                       alloc_rdy   ;
logic [N            -1:0]   free_err    ;
logic [VC_NUM*ID_W  -1:0]   head_id     ;
logic [VC_NUM*DST_W -1:0]   head_dst    ;
logic [VC_NUM       -1:0]   empty       ;
logic [VC_NUM       -1:0]   full        ;
logic [N            -1:0]   pop_vld     ;
logic [N*VC_W       -1:0]   pop_qid     ;
logic [N*ID_W       -1:0]   pop_id      ;
logic [N            -1:0]   pop_rdy     ;
logic [N*CELL_W     -1:0]   rd_data     ;
logic [N*ADDR_W     -1:0]   rd_addr     ;
logic [N            -1:0]   rd_vld      ;
logic [N            -1:0]   rd_rdy      ;
logic [VC_NUM       -1:0]   vc_locked   ;
logic [N            -1:0]   sel_vld     ;
logic [N*VC_W       -1:0]   sel_vc      ;
logic [N            -1:0]   gnt_vld     ;
logic [N*VC_NUM     -1:0]   gnt         ;
logic [N*VC_NUM     -1:0]   req         ;
logic [N*VC_W       -1:0]   gnt_idx     ;
logic [N*ID_W       -1:0]   free_id     ;
logic [N            -1:0]   free_req    ;
logic                       in_wr       ;
logic                       push_rdy    ;
logic [CELL_W       -1:0]   wr_data     ;
logic                       unused_nc   ;

assign in_wr     = in_vld && in_rdy;
assign in_rdy    = alloc_rdy && push_rdy;
assign wr_data   = {in_sop, in_eop, in_data};
assign unused_nc = &{1'b0, quota_en, quota};


generate
    for (genvar o = 0; o < N; o++) begin : g_out
        assign out_vld[o] = sel_vld[o]
                         && !empty[sel_vc[o*VC_W +: VC_W]];
        assign out_vc[o*VC_W +: VC_W] =
            sel_vc[o*VC_W +: VC_W];
        assign out_data[o*FLIT_W +: FLIT_W] =
            rd_data[o*CELL_W +: FLIT_W];
        assign out_sop[o] = rd_data[o*CELL_W + FLIT_W + 1];
        assign out_eop[o] = rd_data[o*CELL_W + FLIT_W];
        assign rd_vld[o]  = out_vld[o];
        assign rd_addr[o*ADDR_W +: ADDR_W] =
            head_id[sel_vc[o*VC_W +: VC_W]*ID_W +: ID_W];
        assign pop_vld[o] = out_vld[o] && out_rdy[o];
        assign pop_qid[o*VC_W +: VC_W] =
            sel_vc[o*VC_W +: VC_W];
        assign free_req[o] = pop_vld[o];
        assign free_id[o*ID_W +: ID_W] =
            head_id[sel_vc[o*VC_W +: VC_W]*ID_W +: ID_W];
    end

    for (genvar o = 0; o < N; o++) begin : g_arb
        arbiter_rr #(
            .N  (VC_NUM )
        ) U_RR (
            .clk        (clk                        ),
            .rst_n      (rst_n                      ),
            .upd        (gnt_vld[o]                 ),
            .req        (req[o*VC_NUM +: VC_NUM]    ),
            .gnt        (gnt[o*VC_NUM +: VC_NUM]    ),
            .gnt_vld    (gnt_vld[o]                 )
        );

        ohot2bin #(
            .IN_W   (VC_NUM )
        ) U_GNT_IDX (
            .ohot   (gnt[o*VC_NUM +: VC_NUM]    ),
            .bin    (gnt_idx[o*VC_W +: VC_W]    ),
            .vld    (                           )
        );
    end
endgenerate

idpool #(
    .ID_NUM (CELL_NUM   ),
    .N_FREE (N          )
) U_IDPOOL (
    .clk        (clk        ),
    .rst_n      (rst_n      ),
    .alloc_req  (in_vld     ),
    .alloc_rdy  (alloc_rdy  ),
    .alloc_id   (alloc_id   ),
    .free_req   (free_req   ),
    .free_id    (free_id    ),
    .free_err   (free_err   ),
    .empty      (           ),
    .full       (           ),
    .count      (           )
);

shared_buffer #(
    .DATA_W     (CELL_W     ),
    .CELL_NUM   (CELL_NUM   ),
    .N          (N          )
) U_BUFFER (
    .clk        (clk        ),
    .rst_n      (rst_n      ),
    .wr_vld     (in_wr      ),
    .wr_rdy     (           ),
    .wr_addr    (alloc_id   ),
    .wr_data    (wr_data    ),
    .rd_vld     (rd_vld     ),
    .rd_rdy     (rd_rdy     ),
    .rd_addr    (rd_addr    ),
    .rd_data    (rd_data    )
);

link_list #(
    .ID_NUM     (CELL_NUM   ),
    .QID_NUM    (VC_NUM     ),
    .N          (N          ),
    .ID_W       (ID_W       ),
    .QID_W      (VC_W       ),
    .DST_W      (DST_W      )
) U_LINK (
    .clk        (clk        ),
    .rst_n      (rst_n      ),
    .push_vld   (in_wr      ),
    .push_qid   (in_vc      ),
    .push_id    (alloc_id   ),
    .push_dst   (in_dst     ),
    .push_rdy   (push_rdy   ),
    .pop_vld    (pop_vld    ),
    .pop_qid    (pop_qid    ),
    .pop_id     (pop_id     ),
    .pop_rdy    (pop_rdy    ),
    .head_id    (head_id    ),
    .head_dst   (head_dst   ),
    .empty      (empty      ),
    .full       (full       )
);



always_comb begin
    req = '0;
    for (int o_i = 0; o_i < N; o_i++) begin
        for (int vc_i = 0; vc_i < VC_NUM; vc_i++) begin
            req[o_i*VC_NUM + vc_i] =
                !sel_vld[o_i]
                && !empty[vc_i]
                && (head_dst[vc_i*DST_W +: DST_W] == DST_W'(o_i))
                && !vc_locked[vc_i];
        end
    end
end

// Selection registers.  These are control state; kept as one explicit
// always_ff because the dffr d/en combination created a simulator loop in
// the integration testbench.  Refactor to dffr once the loop is root-caused.
always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        sel_vld   <= '0;
        sel_vc    <= '0;
        vc_locked <= '0;
    end else begin
        for (int o_i = 0; o_i < N; o_i++) begin
            if (!sel_vld[o_i]) begin
                if (gnt_vld[o_i]) begin
                    sel_vld[o_i] <= 1'b1;
                    sel_vc[o_i*VC_W +: VC_W] <= gnt_idx[o_i*VC_W +: VC_W];
                    vc_locked[gnt_idx[o_i*VC_W +: VC_W]] <= 1'b1;
                end
            end else if (out_vld[o_i] && out_rdy[o_i] && out_eop[o_i]) begin
                sel_vld[o_i] <= 1'b0;
                vc_locked[sel_vc[o_i*VC_W +: VC_W]] <= 1'b0;
            end
        end
    end
end

`ifdef SVA_ON
`include "mo_fifo_top.sva"
`endif

endmodule

`default_nettype wire
