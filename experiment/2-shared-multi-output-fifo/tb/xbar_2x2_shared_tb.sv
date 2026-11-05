`timescale 1ns/1ps

module xbar_2x2_shared_tb;

    localparam int FLIT_W   = 16;
    localparam int N        = 2;
    localparam int VC_NUM   = 2;
    localparam int CELL_NUM = 16;
    localparam int DST_W    = $clog2(N);
    localparam int VC_W     = $clog2(VC_NUM);

    logic                 clk         ;
    logic                 rst_n       ;
    logic [1:0]           in_vld      ;
    logic [1:0]           in_rdy      ;
    logic [2*FLIT_W-1:0]  in_data     ;
    logic [1:0]           in_sop      ;
    logic [1:0]           in_eop      ;
    logic [2*VC_W-1:0]    in_vc       ;
    logic [2*DST_W-1:0]   in_dst      ;
    logic [N-1:0]         out_vld     ;
    logic [N-1:0]         out_rdy     ;
    logic [N*FLIT_W-1:0]  out_data    ;
    logic [N-1:0]         out_sop     ;
    logic [N-1:0]         out_eop     ;
    logic [N*VC_W-1:0]    out_vc      ;

    int pkt_len [256];
    int pkt_vc  [256];
    int pkt_dst [256];
    int active_seq [N];
    int active_idx [N];
    int delivered_pkts;
    int delivered_by_out [N];
    int sent_pkts;
    int errors;

    xbar_2x2_shared #(
        .FLIT_W   (FLIT_W   ),
        .N        (N        ),
        .VC_NUM   (VC_NUM   ),
        .CELL_NUM (CELL_NUM ),
        .DST_W    (DST_W    ),
        .VC_W     (VC_W     )
    ) U_DUT (
        .clk        (clk        ),
        .rst_n      (rst_n      ),
        .in_vld     (in_vld     ),
        .in_rdy     (in_rdy     ),
        .in_data    (in_data    ),
        .in_sop     (in_sop     ),
        .in_eop     (in_eop     ),
        .in_vc      (in_vc      ),
        .in_dst     (in_dst     ),
        .out_vld    (out_vld    ),
        .out_rdy    (out_rdy    ),
        .out_data   (out_data   ),
        .out_sop    (out_sop    ),
        .out_eop    (out_eop    ),
        .out_vc     (out_vc     )
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    task automatic err(input string msg);
        errors++;
        $display("[%m] FAIL: %s", msg);
    endtask

    task automatic send_flit(
        input int inp,
        input int seq,
        input int idx,
        input int len,
        input int vc,
        input int dst
    );
        @(negedge clk);
        in_vld[inp] = 1'b1;
        in_data[inp*FLIT_W +: FLIT_W] = {seq[7:0], idx[7:0]};
        in_sop[inp] = (idx == 0);
        in_eop[inp] = (idx == len - 1);
        in_vc[inp*VC_W +: VC_W] = VC_W'(vc);
        in_dst[inp*DST_W +: DST_W] = DST_W'(dst);
        #1;
        while (!in_rdy[inp]) begin
            @(negedge clk);
            #1;
        end
        @(posedge clk);
    endtask

    task automatic send_packet(
        input int inp,
        input int seq,
        input int len,
        input int vc,
        input int dst
    );
        pkt_len[seq] = len;
        pkt_vc[seq]  = vc;
        pkt_dst[seq] = dst;
        for (int i = 0; i < len; i++) begin
            send_flit(inp, seq, i, len, vc, dst);
        end
        @(negedge clk);
        in_vld[inp] = 1'b0;
    endtask

    task automatic wait_pkts(input int target, input int timeout);
        int cycles;
        cycles = 0;
        while (delivered_pkts < target && cycles < timeout) begin
            @(posedge clk);
            cycles++;
        end
        if (delivered_pkts < target) begin
            err($sformatf("timeout: delivered=%0d target=%0d",
                delivered_pkts, target));
        end
    endtask

    always @(posedge clk) begin
        if (rst_n) begin
            for (int o = 0; o < N; o++) begin
                if (out_vld[o] && out_rdy[o]) begin
                    int seq;
                    int idx;
                    int got_vc;
                    logic [FLIT_W-1:0] data;
                    data  = out_data[o*FLIT_W +: FLIT_W];
                    seq   = data[15:8];
                    idx   = data[7:0];
                    got_vc = out_vc[o*VC_W +: VC_W];
                    if (pkt_len[seq] == 0) begin
                        err($sformatf("unknown seq %0d on out%0d", seq, o));
                    end
                    if (pkt_dst[seq] != o) begin
                        err($sformatf("seq%0d dst%0d appeared on out%0d",
                            seq, pkt_dst[seq], o));
                    end
                    if (got_vc != pkt_vc[seq]) begin
                        err($sformatf("seq%0d vc%0d exp%0d",
                            seq, got_vc, pkt_vc[seq]));
                    end
                    if (out_sop[o]) begin
                        if (idx != 0) begin
                            err($sformatf("seq%0d sop idx%0d", seq, idx));
                        end
                        if (active_seq[o] >= 0) begin
                            err($sformatf("out%0d new sop before eop", o));
                        end
                        active_seq[o] = seq;
                        active_idx[o] = 0;
                    end else begin
                        if (active_seq[o] != seq) begin
                            err($sformatf("out%0d seq%0d expected active%0d",
                                o, seq, active_seq[o]));
                        end
                        if (idx != active_idx[o] + 1) begin
                            err($sformatf("out%0d seq%0d idx%0d exp%0d",
                                o, seq, idx, active_idx[o] + 1));
                        end
                        active_idx[o] = idx;
                    end
                    if (out_eop[o]) begin
                        if (idx != pkt_len[seq] - 1) begin
                            err($sformatf("seq%0d eop idx%0d len%0d",
                                seq, idx, pkt_len[seq]));
                        end
                        active_seq[o] = -1;
                        active_idx[o] = -1;
                        delivered_pkts++;
                        delivered_by_out[o]++;
                    end
                end
            end
        end
    end

    initial begin
        rst_n    = 1'b0;
        in_vld   = '0;
        in_data  = '0;
        in_sop   = '0;
        in_eop   = '0;
        in_vc    = '0;
        in_dst   = '0;
        out_rdy  = 2'b11;
        sent_pkts = 0;
        delivered_pkts = 0;
        errors = 0;
        for (int o = 0; o < N; o++) begin
            active_seq[o] = -1;
            active_idx[o] = -1;
            delivered_by_out[o] = 0;
        end
        for (int i = 0; i < 256; i++) begin
            pkt_len[i] = 0;
            pkt_vc[i] = 0;
            pkt_dst[i] = 0;
        end

        repeat (3) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        #1;

        // 1) One packet per input, different outputs.
        sent_pkts += 2;
        fork
            send_packet(0, 0, 4, 0, 0);
            send_packet(1, 1, 4, 1, 1);
        join
        wait_pkts(2, 200);

        // 2) Both inputs target output 0; output arbitration + packet lock.
        sent_pkts += 2;
        fork
            send_packet(0, 2, 4, 0, 0);
            send_packet(1, 3, 4, 1, 0);
        join
        wait_pkts(4, 300);
        if (delivered_by_out[0] != 3) begin
            err($sformatf("out0 delivered=%0d exp=3", delivered_by_out[0]));
        end

        // 3) One input feeds both outputs (two read ports).
        sent_pkts += 2;
        send_packet(0, 4, 4, 0, 0);
        send_packet(0, 5, 4, 1, 1);
        wait_pkts(6, 300);

        // 4) Same input, same VC, different destinations (VC HOL, sequential).
        sent_pkts += 2;
        send_packet(0, 6, 3, 0, 0);
        send_packet(0, 7, 3, 0, 1);
        wait_pkts(8, 300);

        // 5) Backpressure on output 0.
        @(negedge clk);
        out_rdy[0] = 1'b0;
        sent_pkts += 1;
        send_packet(1, 8, 4, 1, 0);
        repeat (10) @(posedge clk);
        if (delivered_pkts != 8) err("packet delivered under backpressure");
        @(negedge clk);
        out_rdy[0] = 1'b1;
        wait_pkts(9, 300);

        repeat (20) @(posedge clk);
        if (sent_pkts != delivered_pkts) begin
            err($sformatf("sent=%0d delivered=%0d", sent_pkts, delivered_pkts));
        end

        if (errors == 0) begin
            $display("[%m] PASS (%0d packets)", delivered_pkts);
        end else begin
            $display("[%m] FAIL: %0d errors", errors);
        end
        $finish;
    end

endmodule
