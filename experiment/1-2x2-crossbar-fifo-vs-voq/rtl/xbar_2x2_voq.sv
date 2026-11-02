`default_nettype none
//==============================================================================
// Module : xbar_2x2_voq
// Description : 2x2 packet crossbar, one VOQ per (input, output) pair.
// Features :
//   - vld/rdy, sop/eop, packet-granular output arbitration
//   - 4 VOQs (2 inputs x 2 outputs), flit-level capacity per VOQ
//   - input demux writes flit `dst` into voq[src][dst]
//   - no HOL: a packet waiting for output 0 does not block input's output 1
//   - no drop: full target VOQ deasserts in_rdy; source holds vld
//   - packet-granular lock: output stays on selected input until eop
// Parameters :
//   FLIT_W - flit payload width
//   VOQ_DEPTH - per-VOQ depth in flits (must be >= 2)
// Limitations :
//   - in_dst must remain stable for every flit of a packet (TB holds it)
//   - registered only for arbiter lock; output mux is combinational
//   - no output queue / XP in this variant
//==============================================================================
module xbar_2x2_voq #(
    parameter   int FLIT_W      =   32  ,
    parameter   int VOQ_DEPTH   =   16
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

    // dst is implicit in the VOQ index, so only sop/eop are stored.
    localparam int FIFO_W = FLIT_W + 2;

    logic [1 :0] [1 :0]                 voq_wr_rdy  ;
    logic [1 :0] [1 :0]                 voq_wr_vld  ;
    logic [1 :0] [1 :0]                 voq_rd_vld  ;
    logic [1 :0] [1 :0]                 voq_rd_rdy  ;
    logic [1 :0] [1 :0] [FIFO_W -1:0]   voq_wr_data ;
    logic [1 :0] [1 :0] [FIFO_W -1:0]   voq_rd_data ;

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

    logic [1:0]             sel;
    logic [1:0]             sel_vld;

    genvar s;
    genvar d;
    generate
        for (s = 0; s < 2; s++) begin : g_input
            for (d = 0; d < 2; d++) begin : g_voq
                assign voq_wr_vld[s][d] = in_vld[s] && (in_dst[s] == d);
                assign voq_wr_data[s][d] = {in_sop[s], in_eop[s], in_data[s]};

                fifo_sync #(
                    .DATA_W (FIFO_W     ),
                    .DEPTH  (VOQ_DEPTH  )
                ) U_FIFO (
                    .clk        (clk                ),
                    .rst_n      (rst_n              ),
                    .wr_vld     (voq_wr_vld[s][d]   ),
                    .wr_rdy     (voq_wr_rdy[s][d]   ),
                    .wr_data    (voq_wr_data[s][d]  ),
                    .rd_vld     (voq_rd_vld[s][d]   ),
                    .rd_rdy     (voq_rd_rdy[s][d]   ),
                    .rd_data    (voq_rd_data[s][d]  ),
                    .empty      (                   ),
                    .full       (                   )
                );
            end
            // The source sees backpressure from the VOQ selected by dst.
            assign in_rdy[s] = in_dst[s] ? voq_wr_rdy[s][1]
                                         : voq_wr_rdy[s][0];
        end
    endgenerate

    // Output 0 priority when both outputs want the same input.  A locked
    // output masks its selected input from the other output.
    assign req0[0] = voq_rd_vld[0][0] && !locked[0] &&
                     !(locked[1] && (locked_src[1] == 1'b0));
    assign req0[1] = voq_rd_vld[1][0] && !locked[0] &&
                     !(locked[1] && (locked_src[1] == 1'b1));

    assign req1[0] = voq_rd_vld[0][1] && !locked[1] &&
                     !(locked[0] && (locked_src[0] == 1'b0)) &&
                     !gnt0[0];
    assign req1[1] = voq_rd_vld[1][1] && !locked[1] &&
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
    // packed dimension, so spell out the 2:1 selects for each output.
    assign sel_rd_vld[0] = sel[0] ? voq_rd_vld[1][0] : voq_rd_vld[0][0];
    assign sel_rd_vld[1] = sel[1] ? voq_rd_vld[1][1] : voq_rd_vld[0][1];
    assign out_vld[0] = sel_vld[0] & sel_rd_vld[0];
    assign out_vld[1] = sel_vld[1] & sel_rd_vld[1];

    assign head_sop[0] = sel[0] ? voq_rd_data[1][0][FLIT_W+1]
                                : voq_rd_data[0][0][FLIT_W+1];
    assign head_sop[1] = sel[1] ? voq_rd_data[1][1][FLIT_W+1]
                                : voq_rd_data[0][1][FLIT_W+1];
    assign head_eop[0] = sel[0] ? voq_rd_data[1][0][FLIT_W]
                                : voq_rd_data[0][0][FLIT_W];
    assign head_eop[1] = sel[1] ? voq_rd_data[1][1][FLIT_W]
                                : voq_rd_data[0][1][FLIT_W];
    assign head_data[0] = sel[0] ? voq_rd_data[1][0][FLIT_W-1:0]
                                 : voq_rd_data[0][0][FLIT_W-1:0];
    assign head_data[1] = sel[1] ? voq_rd_data[1][1][FLIT_W-1:0]
                                 : voq_rd_data[0][1][FLIT_W-1:0];

    assign out_data[0] = head_data[0];
    assign out_data[1] = head_data[1];
    assign out_sop[0]  = head_sop[0];
    assign out_sop[1]  = head_sop[1];
    assign out_eop[0]  = head_eop[0];
    assign out_eop[1]  = head_eop[1];
    assign out_src_dbg[0] = sel[0];
    assign out_src_dbg[1] = sel[1];

    // Each output reads only its own VOQ of the selected input.
    assign voq_rd_rdy[0][0] =
        out_vld[0] && out_rdy[0] && (sel[0] == 1'b0);
    assign voq_rd_rdy[1][0] =
        out_vld[0] && out_rdy[0] && (sel[0] == 1'b1);
    assign voq_rd_rdy[0][1] =
        out_vld[1] && out_rdy[1] && (sel[1] == 1'b0);
    assign voq_rd_rdy[1][1] =
        out_vld[1] && out_rdy[1] && (sel[1] == 1'b1);

    always_comb begin
        nxt_locked     = locked;
        nxt_locked_src = locked_src;
        for (int o = 0; o < 2; o++) begin
            if (!locked[o] && gnt_vld[o]) begin
                if (!(out_vld[o] && out_rdy[o] && out_eop[o])) begin
                    nxt_locked[o]     = 1'b1;
                    nxt_locked_src[o] = gnt_src[o];
                end
            end else if (locked[o] && out_vld[o] && out_rdy[o] && out_eop[o]) begin
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
`include "xbar_2x2_voq.sva"
`endif

endmodule

`default_nettype wire
