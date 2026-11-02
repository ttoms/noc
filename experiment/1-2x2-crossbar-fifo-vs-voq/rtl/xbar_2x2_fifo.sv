`default_nettype none
//==============================================================================
// Module : xbar_2x2_fifo
// Description : 2x2 packet crossbar, one shared input FIFO per input.
// Features :
//   - vld/rdy, sop/eop, packet-granular output arbitration
//   - one shared input FIFO per input (HOL baseline)
//   - no drop: full FIFO deasserts in_rdy; source holds vld
//   - packet-granular lock: output stays on the selected input until eop
// Parameters :
//   FLIT_W - flit payload width
//   DEPTH  - input FIFO depth in flits (must be >= 2)
// Limitations :
//   - registered only for arbiter lock; output mux is combinational
//   - output ready assumed to be driven by downstream; TB may stall it
//   - no output queue / VOQ in this variant
//==============================================================================
module xbar_2x2_fifo #(
    parameter int FLIT_W = 32,
    parameter int DEPTH  = 32
) (
    input  logic                 clk,
    input  logic                 rst_n,

    input  logic [1:0]           in_vld,
    output logic [1:0]           in_rdy,
    input  logic [1:0][FLIT_W-1:0] in_data,
    input  logic [1:0]           in_sop,
    input  logic [1:0]           in_eop,
    input  logic [1:0]           in_dst,

    output logic [1:0]           out_vld,
    input  logic [1:0]           out_rdy,
    output logic [1:0][FLIT_W-1:0] out_data,
    output logic [1:0]           out_sop,
    output logic [1:0]           out_eop,
    output logic [1:0]           out_src_dbg
);

    localparam int FIFO_W = FLIT_W + 3;

    logic [1:0]             fifo_wr_rdy;
    logic [1:0]             fifo_rd_vld;
    logic [1:0]             fifo_rd_rdy;
    logic [1:0][FIFO_W-1:0] fifo_rd_data;

    logic [1:0]             head_dst;
    logic [1:0]             head_sop;
    logic [1:0]             head_eop;
    logic [1:0][FLIT_W-1:0] head_data;

    logic [1:0]             req0;
    logic [1:0]             req1;
    logic [1:0]             gnt0;
    logic [1:0]             gnt1;
    logic                   gnt0_vld;
    logic                   gnt1_vld;

    logic [1:0]             locked;
    logic [1:0]             locked_src;

    logic [1:0]             sel;
    logic [1:0]             sel_vld;
    logic [1:0]             sel_src;

    genvar i;
    generate
        for (i = 0; i < 2; i++) begin : g_input_fifo
            fifo_sync #(
                .DATA_W (FIFO_W),
                .DEPTH  (DEPTH )
            ) U_FIFO (
                .clk     (clk),
                .rst_n   (rst_n),
                .wr_vld  (in_vld[i]),
                .wr_rdy  (fifo_wr_rdy[i]),
                .wr_data ({in_dst[i], in_sop[i], in_eop[i], in_data[i]}),
                .rd_vld  (fifo_rd_vld[i]),
                .rd_rdy  (fifo_rd_rdy[i]),
                .rd_data (fifo_rd_data[i]),
                .empty   (),
                .full    ()
            );

            assign in_rdy[i] = fifo_wr_rdy[i];
            assign head_dst[i] = fifo_rd_data[i][FIFO_W-1];
            assign head_sop[i] = fifo_rd_data[i][FLIT_W+1];
            assign head_eop[i] = fifo_rd_data[i][FLIT_W];
            assign head_data[i] = fifo_rd_data[i][FLIT_W-1:0];
        end
    endgenerate

    // Requests. Output 0 has priority when both outputs want the same input.
    // A locked output masks its selected input from the other output.
    assign req0[0] = fifo_rd_vld[0] && (head_dst[0] == 1'b0) &&
                     !locked[0] &&
                     !(locked[1] && (locked_src[1] == 1'b0));
    assign req0[1] = fifo_rd_vld[1] && (head_dst[1] == 1'b0) &&
                     !locked[0] &&
                     !(locked[1] && (locked_src[1] == 1'b1));

    assign req1[0] = fifo_rd_vld[0] && (head_dst[0] == 1'b1) &&
                     !locked[1] &&
                     !(locked[0] && (locked_src[0] == 1'b0)) &&
                     !gnt0[0];
    assign req1[1] = fifo_rd_vld[1] && (head_dst[1] == 1'b1) &&
                     !locked[1] &&
                     !(locked[0] && (locked_src[0] == 1'b1)) &&
                     !gnt0[1];

    arbiter_rr #(
        .N (2)
    ) U_ARB0 (
        .clk     (clk),
        .rst_n   (rst_n),
        .upd     (gnt0_vld),
        .req     (req0),
        .gnt     (gnt0),
        .gnt_vld (gnt0_vld)
    );

    arbiter_rr #(
        .N (2)
    ) U_ARB1 (
        .clk     (clk),
        .rst_n   (rst_n),
        .upd     (gnt1_vld),
        .req     (req1),
        .gnt     (gnt1),
        .gnt_vld (gnt1_vld)
    );

    assign sel[0] = locked[0] ? locked_src[0] : gnt0[1];
    assign sel[1] = locked[1] ? locked_src[1] : gnt1[1];
    assign sel_vld[0] = locked[0] | gnt0_vld;
    assign sel_vld[1] = locked[1] | gnt1_vld;

    assign out_vld[0] = sel_vld[0] & fifo_rd_vld[sel[0]];
    assign out_vld[1] = sel_vld[1] & fifo_rd_vld[sel[1]];

    assign out_data[0] = head_data[sel[0]];
    assign out_data[1] = head_data[sel[1]];
    assign out_sop[0]  = head_sop[sel[0]];
    assign out_sop[1]  = head_sop[sel[1]];
    assign out_eop[0]  = head_eop[sel[0]];
    assign out_eop[1]  = head_eop[sel[1]];
    assign out_src_dbg[0] = sel[0];
    assign out_src_dbg[1] = sel[1];

    // Read enables: an input FIFO is read by the output that selected it and
    // only when that output's flit is accepted.
    assign fifo_rd_rdy[0] =
        (out_vld[0] && out_rdy[0] && (sel[0] == 1'b0)) ||
        (out_vld[1] && out_rdy[1] && (sel[1] == 1'b0));
    assign fifo_rd_rdy[1] =
        (out_vld[0] && out_rdy[0] && (sel[0] == 1'b1)) ||
        (out_vld[1] && out_rdy[1] && (sel[1] == 1'b1));

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            locked     <= 2'b00;
            locked_src <= 2'b00;
        end else begin
            // output 0
            if (!locked[0] && gnt0_vld) begin
                if (!(out_vld[0] && out_rdy[0] && out_eop[0])) begin
                    locked[0]     <= 1'b1;
                    locked_src[0] <= gnt0[1]; // one-hot: 0 -> src0, 1 -> src1
                end
            end else if (locked[0] && out_vld[0] && out_rdy[0] && out_eop[0]) begin
                locked[0] <= 1'b0;
            end

            // output 1
            if (!locked[1] && gnt1_vld) begin
                if (!(out_vld[1] && out_rdy[1] && out_eop[1])) begin
                    locked[1]     <= 1'b1;
                    locked_src[1] <= gnt1[1];
                end
            end else if (locked[1] && out_vld[1] && out_rdy[1] && out_eop[1]) begin
                locked[1] <= 1'b0;
            end
        end
    end

endmodule

`default_nettype wire
