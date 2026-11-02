`default_nettype none
//==============================================================================
// Module : xbar_2x2_xp
// Description : 2x2 packet crossbar with one FIFO per crosspoint.
// Features :
//   - 4 crosspoint FIFOs: xp[src][dst], one per (input, output) pair
//   - input demux writes each flit into the FIFO selected by in_dst
//   - each output arbitrates among the two FIFOs in its column at packet
//     granularity and locks the grant until EOP
//   - no drop: a full target FIFO deasserts in_rdy and the source holds vld
//   - no input-side queue: the source holds one outstanding packet at a time
// Parameters :
//   FLIT_W   - flit payload width
//   XP_DEPTH - depth of each crosspoint FIFO in flits (power of two, >= 2)
// Limitations :
//   - in_dst must remain stable for every flit of a packet (TB holds it)
//   - registered only for arbiter lock; output mux is combinational
//   - XP-only variant; no input VOQ or output queue is included
//==============================================================================
module xbar_2x2_xp #(
    parameter   int FLIT_W      =   32  ,
    parameter   int XP_DEPTH    =   16
) (
    input   logic                       clk         ,
    input   logic                       rst_n       ,

    input   logic [1 :0]                in_vld      ,
    output  logic [1 :0]                in_rdy      ,
    input   logic [1 :0] [FLIT_W -1:0]  in_data     ,
    input   logic [1 :0]                in_sop      ,
    input   logic [1 :0]                in_eop      ,
    input   logic [1 :0]                in_dst      ,

    output  logic [1 :0]                out_vld     ,
    input   logic [1 :0]                out_rdy     ,
    output  logic [1 :0] [FLIT_W -1:0]  out_data    ,
    output  logic [1 :0]                out_sop     ,
    output  logic [1 :0]                out_eop     ,
    output  logic [1 :0]                out_src_dbg
);

    // The destination is implicit in the XP FIFO index, so only sop/eop and
    // payload are stored.
    localparam int FIFO_W = FLIT_W + 2;

    // Port inputs are sampled into local names before any logic or instance
    // connection, so the datapath and port list stay independent.
    logic [1 :0]                in_vld_int  ;
    logic [1 :0] [FLIT_W -1:0]  in_data_int ;
    logic [1 :0]                in_sop_int  ;
    logic [1 :0]                in_eop_int  ;
    logic [1 :0]                in_dst_int  ;
    logic [1 :0]                out_rdy_int ;
    logic [1 :0]                in_rdy_int  ;

    logic [1 :0] [1 :0]                 xp_wr_rdy   ;
    logic [1 :0] [1 :0]                 xp_wr_vld   ;
    logic [1 :0] [1 :0]                 xp_rd_vld   ;
    logic [1 :0] [1 :0]                 xp_rd_rdy   ;
    logic [1 :0] [1 :0] [FIFO_W -1:0]   xp_wr_data  ;
    logic [1 :0] [1 :0] [FIFO_W -1:0]   xp_rd_data  ;

    logic [1 :0]                sel_rd_vld  ;
    logic [1 :0]                head_sop    ;
    logic [1 :0]                head_eop    ;
    logic [1 :0] [FLIT_W -1:0]  head_data   ;

    logic [1 :0]    req0        ;
    logic [1 :0]    req1        ;
    logic [1 :0]    gnt0        ;
    logic [1 :0]    gnt1        ;
    logic           gnt0_vld    ;
    logic           gnt1_vld    ;
    logic [1 :0]    gnt_vld     ;
    logic [1 :0]    gnt_src     ;

    logic [1 :0]    locked          ;
    logic [1 :0]    locked_src      ;
    logic [1 :0]    nxt_locked      ;
    logic [1 :0]    nxt_locked_src  ;
    logic           lock_en         ;

    logic [1 :0]    sel         ;
    logic [1 :0]    sel_vld     ;

    assign in_vld_int  = in_vld;
    assign in_data_int = in_data;
    assign in_sop_int  = in_sop;
    assign in_eop_int  = in_eop;
    assign in_dst_int  = in_dst;
    assign out_rdy_int = out_rdy;

    genvar s;
    genvar d;
    generate
        for (s = 0; s < 2; s++) begin : g_input
            for (d = 0; d < 2; d++) begin : g_xp
                assign xp_wr_vld[s][d] = in_vld_int[s] && (in_dst_int[s] == d);
                assign xp_wr_data[s][d] = {
                    in_sop_int[s],
                    in_eop_int[s],
                    in_data_int[s]
                };

                fifo_sync #(
                    .DATA_W (FIFO_W     ),
                    .DEPTH  (XP_DEPTH   )
                ) U_FIFO (
                    .clk        (clk                ),
                    .rst_n      (rst_n              ),
                    .wr_vld     (xp_wr_vld[s][d]    ),
                    .wr_rdy     (xp_wr_rdy[s][d]    ),
                    .wr_data    (xp_wr_data[s][d]   ),
                    .rd_vld     (xp_rd_vld[s][d]    ),
                    .rd_rdy     (xp_rd_rdy[s][d]    ),
                    .rd_data    (xp_rd_data[s][d]   ),
                    .empty      (                   ),
                    .full       (                   )
                );
            end
            // A source is backpressured only by the XP FIFO selected by dst.
            assign in_rdy_int[s] = in_dst_int[s] ? xp_wr_rdy[s][1]
                                                 : xp_wr_rdy[s][0];
        end
    endgenerate

    assign in_rdy = in_rdy_int;

    // Requests.  Output 0 has priority when both outputs want the same input.
    // A locked output masks its selected input from the other output.
    assign req0[0] = xp_rd_vld[0][0] && !locked[0] &&
                     !(locked[1] && (locked_src[1] == 1'b0));
    assign req0[1] = xp_rd_vld[1][0] && !locked[0] &&
                     !(locked[1] && (locked_src[1] == 1'b1));

    assign req1[0] = xp_rd_vld[0][1] && !locked[1] &&
                     !(locked[0] && (locked_src[0] == 1'b0)) &&
                     !gnt0[0];
    assign req1[1] = xp_rd_vld[1][1] && !locked[1] &&
                     !(locked[0] && (locked_src[0] == 1'b1)) &&
                     !gnt0[1];

    arbiter_rr #(
        .N  (2  )
    ) U_ARB0 (
        .clk        (clk        ),
        .rst_n      (rst_n      ),
        .upd        (gnt0_vld   ),
        .req        (req0       ),
        .gnt        (gnt0       ),
        .gnt_vld    (gnt0_vld   )
    );

    arbiter_rr #(
        .N  (2  )
    ) U_ARB1 (
        .clk        (clk        ),
        .rst_n      (rst_n      ),
        .upd        (gnt1_vld   ),
        .req        (req1       ),
        .gnt        (gnt1       ),
        .gnt_vld    (gnt1_vld   )
    );

    assign gnt_vld[0] = gnt0_vld;
    assign gnt_vld[1] = gnt1_vld;
    assign gnt_src[0] = gnt0[1];
    assign gnt_src[1] = gnt1[1];

    assign sel[0] = locked[0] ? locked_src[0] : gnt0[1];
    assign sel[1] = locked[1] ? locked_src[1] : gnt1[1];
    assign sel_vld[0] = locked[0] | gnt0_vld;
    assign sel_vld[1] = locked[1] | gnt1_vld;

    // Output muxes.  iverilog does not allow a variable index on the first
    // packed dimension, so spell out the 2:1 selects for each column.
    assign sel_rd_vld[0] = sel[0] ? xp_rd_vld[1][0] : xp_rd_vld[0][0];
    assign sel_rd_vld[1] = sel[1] ? xp_rd_vld[1][1] : xp_rd_vld[0][1];
    assign out_vld[0] = sel_vld[0] & sel_rd_vld[0];
    assign out_vld[1] = sel_vld[1] & sel_rd_vld[1];

    assign head_sop[0] = sel[0] ? xp_rd_data[1][0][FLIT_W+1]
                                : xp_rd_data[0][0][FLIT_W+1];
    assign head_sop[1] = sel[1] ? xp_rd_data[1][1][FLIT_W+1]
                                : xp_rd_data[0][1][FLIT_W+1];
    assign head_eop[0] = sel[0] ? xp_rd_data[1][0][FLIT_W]
                                : xp_rd_data[0][0][FLIT_W];
    assign head_eop[1] = sel[1] ? xp_rd_data[1][1][FLIT_W]
                                : xp_rd_data[0][1][FLIT_W];
    assign head_data[0] = sel[0] ? xp_rd_data[1][0][FLIT_W-1:0]
                                 : xp_rd_data[0][0][FLIT_W-1:0];
    assign head_data[1] = sel[1] ? xp_rd_data[1][1][FLIT_W-1:0]
                                 : xp_rd_data[0][1][FLIT_W-1:0];

    assign out_data[0] = head_data[0];
    assign out_data[1] = head_data[1];
    assign out_sop[0]  = head_sop[0];
    assign out_sop[1]  = head_sop[1];
    assign out_eop[0]  = head_eop[0];
    assign out_eop[1]  = head_eop[1];
    assign out_src_dbg[0] = sel[0];
    assign out_src_dbg[1] = sel[1];

    // Each output reads only the XP FIFO in its own column.
    assign xp_rd_rdy[0][0] =
        out_vld[0] && out_rdy_int[0] && (sel[0] == 1'b0);
    assign xp_rd_rdy[1][0] =
        out_vld[0] && out_rdy_int[0] && (sel[0] == 1'b1);
    assign xp_rd_rdy[0][1] =
        out_vld[1] && out_rdy_int[1] && (sel[1] == 1'b0);
    assign xp_rd_rdy[1][1] =
        out_vld[1] && out_rdy_int[1] && (sel[1] == 1'b1);

    always_comb begin
        nxt_locked     = locked;
        nxt_locked_src = locked_src;
        for (int o = 0; o < 2; o++) begin
            if (!locked[o] && gnt_vld[o]) begin
                if (!(out_vld[o] && out_rdy_int[o] && out_eop[o])) begin
                    nxt_locked[o]     = 1'b1;
                    nxt_locked_src[o] = gnt_src[o];
                end
            end else if (locked[o] && out_vld[o] && out_rdy_int[o] &&
                         out_eop[o]) begin
                nxt_locked[o] = 1'b0;
            end
        end
    end

    assign lock_en = (nxt_locked != locked) || (nxt_locked_src != locked_src);

    dffr #(
        .W          (2      ),
        .RESET_VAL  (2'b00  )
    ) U_LOCKED (
        .clk    (clk        ),
        .rst_n  (rst_n      ),
        .en     (lock_en    ),
        .d      (nxt_locked ),
        .q      (locked     )
    );

    dffr #(
        .W          (2      ),
        .RESET_VAL  (2'b00  )
    ) U_LOCKED_SRC (
        .clk    (clk            ),
        .rst_n  (rst_n          ),
        .en     (lock_en        ),
        .d      (nxt_locked_src ),
        .q      (locked_src     )
    );

`ifdef SVA_ON
`include "xbar_2x2_xp.sva"
`endif

endmodule

`default_nettype wire
