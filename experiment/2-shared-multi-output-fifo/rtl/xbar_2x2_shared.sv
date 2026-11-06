`default_nettype none
//==============================================================================
// Module : xbar_2x2_shared
// Description : 2x2 switch with one 1W/NR shared FIFO per input
// Features :
//   - Two mo_fifo_top instances; each input's N outputs feed every output port
//   - Per-output 2:1 RR arbitration across the two input FIFOs
//   - Output locks to the selected input from SOP to EOP; holds under backpressure
//   - Both outputs may read the same input in the same cycle (mo_fifo has N read ports)
// Parameters :
//   FLIT_W, N, VC_NUM, CELL_NUM, DST_W, VC_W, QUOTA_W
// Limitations :
//   - Fixed two inputs; N outputs parameterized (2x2 uses N=2)
//   - v1 no quota; quota ports are tied off
//   - Output arbiter is registered; one cycle selection latency
//   - Output lock uses dffr; next-state/enable are continuous logic
//==============================================================================
module xbar_2x2_shared #(
    parameter   int FLIT_W      =   32                                  ,
    parameter   int N           =   2                                   ,
    parameter   int VC_NUM      =   2                                   ,
    parameter   int CELL_NUM    =   16                                  ,
    parameter   int DST_W       =   (N > 1) ? $clog2(N) : 1             ,
    parameter   int VC_W        =   (VC_NUM > 1) ? $clog2(VC_NUM) : 1   ,
    parameter   int QUOTA_W     =   8
) (
    input   logic                   clk         ,
    input   logic                   rst_n       ,
    input   logic [1          :0]   in_vld      ,
    output  logic [1          :0]   in_rdy      ,
    input   logic [2*FLIT_W -1:0]   in_data     ,
    input   logic [1          :0]   in_sop      ,
    input   logic [1          :0]   in_eop      ,
    input   logic [2*VC_W   -1:0]   in_vc       ,
    input   logic [2*DST_W  -1:0]   in_dst      ,
    output  logic [N        -1:0]   out_vld     ,
    input   logic [N        -1:0]   out_rdy     ,
    output  logic [N*FLIT_W -1:0]   out_data    ,
    output  logic [N        -1:0]   out_sop     ,
    output  logic [N        -1:0]   out_eop     ,
    output  logic [N*VC_W   -1:0]   out_vc
);

logic [2*N            -1:0] f_vld       ;
logic [2*N            -1:0] f_rdy       ;
logic [2*N*FLIT_W     -1:0] f_data      ;
logic [2*N            -1:0] f_sop       ;
logic [2*N            -1:0] f_eop       ;
logic [2*N*VC_W       -1:0] f_vc        ;
logic [N*2            -1:0] req         ;
logic [N*2            -1:0] gnt         ;
logic [N              -1:0] gnt_vld     ;
logic [N              -1:0] gnt_idx     ;
logic [N              -1:0] locked      ;
logic [N              -1:0] locked_in   ;
logic [N              -1:0] sel_in      ;
logic [VC_NUM*QUOTA_W -1:0] quota_zero  ;

genvar i;
genvar o;

generate
    for (genvar o_i = 0; o_i < N; o_i++) begin : g_req
        for (genvar i_i = 0; i_i < 2; i_i++) begin : g_req_in
            assign req[o_i*2 + i_i] = !locked[o_i] && f_vld[i_i*N + o_i];
        end
    end
endgenerate

assign quota_zero = '0;

generate
    for (i = 0; i < 2; i++) begin : g_fifo
        mo_fifo_top #(
            .FLIT_W     (FLIT_W     ),
            .N          (N          ),
            .VC_NUM     (VC_NUM     ),
            .CELL_NUM   (CELL_NUM   ),
            .DST_W      (DST_W      ),
            .VC_W       (VC_W       ),
            .QUOTA_W    (QUOTA_W    )
        ) U_FIFO (
            .clk        (clk                            ),
            .rst_n      (rst_n                          ),
            .in_vld     (in_vld[i]                      ),
            .in_rdy     (in_rdy[i]                      ),
            .in_data    (in_data[i*FLIT_W +: FLIT_W]    ),
            .in_sop     (in_sop[i]                      ),
            .in_eop     (in_eop[i]                      ),
            .in_vc      (in_vc[i*VC_W +: VC_W]          ),
            .in_dst     (in_dst[i*DST_W +: DST_W]       ),
            .out_vld    (f_vld[i*N +: N]                ),
            .out_rdy    (f_rdy[i*N +: N]                ),
            .out_data   (f_data[i*N*FLIT_W +: N*FLIT_W] ),
            .out_sop    (f_sop[i*N +: N]                ),
            .out_eop    (f_eop[i*N +: N]                ),
            .out_vc     (f_vc[i*N*VC_W +: N*VC_W]       ),
            .quota_en   (1'b0                           ),
            .quota      (quota_zero                     )
        );
    end

    for (o = 0; o < N; o++) begin : g_out
        arbiter_rr #(
            .N  (2  )
        ) U_RR (
            .clk        (clk            ),
            .rst_n      (rst_n          ),
            .upd        (gnt_vld[o]     ),
            .req        (req[o*2 +: 2]  ),
            .gnt        (gnt[o*2 +: 2]  ),
            .gnt_vld    (gnt_vld[o]     )
        );

        ohot2bin #(
            .IN_W   (2  )
        ) U_GNT_IDX (
            .ohot   (gnt[o*2 +: 2]  ),
            .bin    (gnt_idx[o]     ),
            .vld    (               )
        );

        assign sel_in[o] = locked[o] ? locked_in[o] : gnt_idx[o];
        assign out_vld[o] = locked[o]
                          ? f_vld[locked_in[o]*N + o]
                          : (gnt_vld[o] ? f_vld[gnt_idx[o]*N + o] : 1'b0);

        assign f_rdy[0*N + o] = out_rdy[o]
                              && ((locked[o] && (locked_in[o] == 1'b0))
                                  || (!locked[o] && gnt_vld[o] && (gnt_idx[o] == 1'b0)));
        assign f_rdy[1*N + o] = out_rdy[o]
                              && ((locked[o] && (locked_in[o] == 1'b1))
                                  || (!locked[o] && gnt_vld[o] && (gnt_idx[o] == 1'b1)));

        assign out_data[o*FLIT_W +: FLIT_W] = out_vld[o]
            ? (sel_in[o]
               ? f_data[1*N*FLIT_W + o*FLIT_W +: FLIT_W]
               : f_data[0*N*FLIT_W + o*FLIT_W +: FLIT_W])
            : '0;
        assign out_sop[o] = out_vld[o]
            ? (sel_in[o] ? f_sop[1*N + o] : f_sop[0*N + o])
            : 1'b0;
        assign out_eop[o] = out_vld[o]
            ? (sel_in[o] ? f_eop[1*N + o] : f_eop[0*N + o])
            : 1'b0;
        assign out_vc[o*VC_W +: VC_W] = out_vld[o]
            ? (sel_in[o]
               ? f_vc[1*N*VC_W + o*VC_W +: VC_W]
               : f_vc[0*N*VC_W + o*VC_W +: VC_W])
            : '0;
    end
endgenerate

// Output lock state: dffr + continuous next-state/enable.  A grant that
// already completes (EOP with out_rdy) must not enter the locked state.
logic [N -1:0]  lock_set            ;
logic [N -1:0]  lock_clr            ;
logic [N -1:0]  lock_en             ;
logic [N -1:0]  lock_d              ;
logic [N -1:0]  locked_in_en        ;
logic [N -1:0]  locked_in_d         ;
logic           lock_en_any         ;
logic           locked_in_en_any    ;

generate
    for (genvar o_i = 0; o_i < N; o_i++) begin : g_lock
        assign lock_set[o_i] = !locked[o_i] && gnt_vld[o_i]
                             && !(out_rdy[o_i]
                                  && f_eop[gnt_idx[o_i]*N + o_i]);
        assign lock_clr[o_i] = locked[o_i]
                             && f_vld[locked_in[o_i]*N + o_i]
                             && out_rdy[o_i]
                             && f_eop[locked_in[o_i]*N + o_i];
        assign lock_en[o_i]  = lock_set[o_i] | lock_clr[o_i];
        assign lock_d[o_i]   = lock_set[o_i] ? 1'b1
                             : lock_clr[o_i] ? 1'b0
                             : locked[o_i];
        assign locked_in_en[o_i] = lock_set[o_i];
        assign locked_in_d[o_i]  = lock_set[o_i] ? gnt_idx[o_i] : locked_in[o_i];
    end
endgenerate

assign lock_en_any      = |lock_en;
assign locked_in_en_any = |locked_in_en;

dffr #(
    .W          (N  ),
    .RESET_VAL  ('0 )
) U_LOCKED (
    .clk    (clk            ),
    .rst_n  (rst_n          ),
    .en     (lock_en_any    ),
    .d      (lock_d         ),
    .q      (locked         )
);

dffr #(
    .W          (N  ),
    .RESET_VAL  ('0 )
) U_LOCKED_IN (
    .clk    (clk                ),
    .rst_n  (rst_n              ),
    .en     (locked_in_en_any   ),
    .d      (locked_in_d        ),
    .q      (locked_in          )
);

endmodule

`default_nettype wire
