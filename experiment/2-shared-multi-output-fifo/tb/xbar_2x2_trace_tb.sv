`timescale 1ns/1ps

module xbar_2x2_trace_tb;

    localparam int FLIT_W   = 32;
    localparam int N        = 2;
`ifdef TB_VC_NUM
    localparam int VC_NUM   = `TB_VC_NUM;
`else
    localparam int VC_NUM   = 2;
`endif
`ifdef TB_CELL_NUM
    localparam int CELL_NUM = `TB_CELL_NUM;
`else
    localparam int CELL_NUM = 16;
`endif
    localparam int DST_W    = $clog2(N);
    localparam int VC_W     = $clog2(VC_NUM);
    localparam int MAX_PKTS = 4096;

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

    integer trace_fd;
    integer out_fd;
    reg [1023:0] trace_path;
    reg [1023:0] out_path;
    reg [1023:0] line_buf;
    integer sim_cycles;
    integer cycle;
    integer rdy_period;
    integer rdy_high;
    logic done;

    integer n0;
    integer n1;
    integer p0;
    integer p1;

    integer src0_seq [0:MAX_PKTS-1];
    integer src0_dst [0:MAX_PKTS-1];
    integer src0_len [0:MAX_PKTS-1];
    integer src0_arr [0:MAX_PKTS-1];
    integer src0_vc  [0:MAX_PKTS-1];
    integer src1_seq [0:MAX_PKTS-1];
    integer src1_dst [0:MAX_PKTS-1];
    integer src1_len [0:MAX_PKTS-1];
    integer src1_arr [0:MAX_PKTS-1];
    integer src1_vc  [0:MAX_PKTS-1];

    integer pkt_src [0:MAX_PKTS-1];
    integer pkt_dst [0:MAX_PKTS-1];
    integer pkt_len [0:MAX_PKTS-1];
    integer pkt_vc  [0:MAX_PKTS-1];

    logic [1:0] cur_vld         ;
    integer     cur_len  [0:1];
    integer     cur_flit [0:1];
    integer     cur_seq  [0:1];
    integer     cur_dst  [0:1];
    integer     cur_vc   [0:1];

    logic       out_active [0:N-1];
    integer     out_start  [0:N-1];
    integer     out_seq    [0:N-1];
    integer     out_flit   [0:N-1];
    integer     data_errors;
    integer     protocol_errors;

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

    always_comb begin
        for (int o = 0; o < N; o++) begin
            if (rdy_period <= 0) begin
                out_rdy[o] = 1'b1;
            end else begin
                out_rdy[o] = ((cycle + 2*o) % rdy_period) < rdy_high;
            end
        end
    end

    assign in_vld = {cur_vld[1], cur_vld[0]};
    assign in_data = {cur_seq[1][15:0], cur_flit[1][15:0],
                      cur_seq[0][15:0], cur_flit[0][15:0]};
    assign in_sop = {cur_vld[1] && (cur_flit[1] == 0),
                     cur_vld[0] && (cur_flit[0] == 0)};
    assign in_eop = {cur_vld[1] && (cur_flit[1] == cur_len[1] - 1),
                     cur_vld[0] && (cur_flit[0] == cur_len[0] - 1)};
    assign in_vc = {VC_W'(cur_vc[1]), VC_W'(cur_vc[0])};
    assign in_dst = {DST_W'(cur_dst[1]), DST_W'(cur_dst[0])};

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        rst_n = 1'b0;
        cycle = 0;
        done  = 1'b0;
        n0 = 0;
        n1 = 0;
        p0 = 0;
        p1 = 0;
        data_errors = 0;
        protocol_errors = 0;
        for (int i = 0; i < 2; i++) begin
            cur_vld[i]  = 1'b0;
            cur_len[i]  = 1;
            cur_flit[i] = 0;
            cur_seq[i]  = 0;
            cur_dst[i]  = 0;
            cur_vc[i]   = 0;
        end
        for (int o = 0; o < N; o++) begin
            out_active[o] = 1'b0;
            out_start[o]  = 0;
            out_seq[o]    = 0;
            out_flit[o]   = 0;
        end

        if (!$value$plusargs("TRACE=%s", trace_path)) begin
            $display("ERROR: +TRACE=<csv> required");
            $finish;
        end
        if (!$value$plusargs("OUT=%s", out_path)) begin
            $display("ERROR: +OUT=<csv> required");
            $finish;
        end
        sim_cycles = 4000;
        $value$plusargs("CYCLES=%d", sim_cycles);
        rdy_period = 0;
        rdy_high = 0;
        $value$plusargs("RDY_PERIOD=%d", rdy_period);
        $value$plusargs("RDY_HIGH=%d", rdy_high);

        trace_fd = $fopen(trace_path, "r");
        if (trace_fd == 0) begin
            $display("ERROR: cannot open trace %s", trace_path);
            $finish;
        end
        out_fd = $fopen(out_path, "w");
        if (out_fd == 0) begin
            $display("ERROR: cannot open output %s", out_path);
            $finish;
        end
        $fwrite(out_fd, "port,seq,src,dst,len,start,end\n");

        line_buf = 0;
        begin
            integer hdr_code;
            hdr_code = $fgets(line_buf, trace_fd);
        end
        begin : read_trace
            integer seq;
            integer src;
            integer dst;
            integer len;
            integer arrival;
            integer vc;
            integer code;
            forever begin
                code = $fscanf(trace_fd, "%d,%d,%d,%d,%d,%d\n",
                               seq, src, dst, len, arrival, vc);
                if (code != 6) disable read_trace;
                pkt_src[seq] = src;
                pkt_dst[seq] = dst;
                pkt_len[seq] = len;
                pkt_vc[seq]  = vc;
                if (src == 0) begin
                    src0_seq[n0] = seq;
                    src0_dst[n0] = dst;
                    src0_len[n0] = len;
                    src0_arr[n0] = arrival;
                    src0_vc[n0]  = vc;
                    n0 = n0 + 1;
                end else begin
                    src1_seq[n1] = seq;
                    src1_dst[n1] = dst;
                    src1_len[n1] = len;
                    src1_arr[n1] = arrival;
                    src1_vc[n1]  = vc;
                    n1 = n1 + 1;
                end
            end
        end
        $fclose(trace_fd);

        rst_n = 1'b0;
        repeat (5) @(posedge clk);
        rst_n = 1'b1;
        repeat (sim_cycles) @(posedge clk);
        done = 1'b1;
        $fclose(out_fd);
        $display("DONE cycle=%0d n0=%0d n1=%0d data_errors=%0d protocol_errors=%0d",
                 cycle, n0, n1, data_errors, protocol_errors);
        if (data_errors != 0 || protocol_errors != 0) begin
            $fatal(1, "data=%0d protocol=%0d",
                   data_errors, protocol_errors);
        end
        $finish;
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            cycle <= 0;
            for (int i = 0; i < 2; i++) begin
                cur_vld[i]  <= 1'b0;
                cur_len[i]  <= 1;
                cur_flit[i] <= 0;
                cur_seq[i]  <= 0;
                cur_dst[i]  <= 0;
                cur_vc[i]   <= 0;
            end
            p0 <= 0;
            p1 <= 0;
        end else begin
            cycle <= cycle + 1;

            if (!cur_vld[0] && p0 < n0 && src0_arr[p0] <= cycle) begin
                cur_vld[0]  <= 1'b1;
                cur_len[0]  <= src0_len[p0];
                cur_flit[0] <= 0;
                cur_seq[0]  <= src0_seq[p0];
                cur_dst[0]  <= src0_dst[p0];
                cur_vc[0]   <= src0_vc[p0];
                p0 <= p0 + 1;
            end else if (cur_vld[0] && in_rdy[0]) begin
                if (cur_flit[0] == cur_len[0] - 1) begin
                    if (p0 < n0 && src0_arr[p0] <= cycle) begin
                        cur_vld[0]  <= 1'b1;
                        cur_len[0]  <= src0_len[p0];
                        cur_flit[0] <= 0;
                        cur_seq[0]  <= src0_seq[p0];
                        cur_dst[0]  <= src0_dst[p0];
                        cur_vc[0]   <= src0_vc[p0];
                        p0 <= p0 + 1;
                    end else begin
                        cur_vld[0] <= 1'b0;
                    end
                end else begin
                    cur_flit[0] <= cur_flit[0] + 1;
                end
            end

            if (!cur_vld[1] && p1 < n1 && src1_arr[p1] <= cycle) begin
                cur_vld[1]  <= 1'b1;
                cur_len[1]  <= src1_len[p1];
                cur_flit[1] <= 0;
                cur_seq[1]  <= src1_seq[p1];
                cur_dst[1]  <= src1_dst[p1];
                cur_vc[1]   <= src1_vc[p1];
                p1 <= p1 + 1;
            end else if (cur_vld[1] && in_rdy[1]) begin
                if (cur_flit[1] == cur_len[1] - 1) begin
                    if (p1 < n1 && src1_arr[p1] <= cycle) begin
                        cur_vld[1]  <= 1'b1;
                        cur_len[1]  <= src1_len[p1];
                        cur_flit[1] <= 0;
                        cur_seq[1]  <= src1_seq[p1];
                        cur_dst[1]  <= src1_dst[p1];
                        cur_vc[1]   <= src1_vc[p1];
                        p1 <= p1 + 1;
                    end else begin
                        cur_vld[1] <= 1'b0;
                    end
                end else begin
                    cur_flit[1] <= cur_flit[1] + 1;
                end
            end
        end
    end

    always @(negedge clk) begin
        if (rst_n && !done) begin
            for (int o = 0; o < N; o++) begin
                if (out_vld[o] && out_rdy[o]) begin
                    int seq;
                    int flit;
                    seq  = out_data[o*FLIT_W + 16 +: 16];
                    flit = out_data[o*FLIT_W + 0  +: 16];
                    if (out_sop[o] && out_active[o]) begin
                        $display("ERROR nested SOP port=%0d cycle=%0d", o, cycle);
                        protocol_errors++;
                    end
                    if (!out_sop[o] && !out_active[o]) begin
                        $display("ERROR flit without SOP port=%0d cycle=%0d", o, cycle);
                        protocol_errors++;
                    end
                    if (out_sop[o]) begin
                        out_active[o] = 1'b1;
                        out_start[o]  = cycle - 1;
                        out_seq[o]    = seq;
                        out_flit[o]   = 0;
                    end
                    if (out_active[o]) begin
                        if (seq != out_seq[o]) begin
                            $display("ERROR seq mismatch port=%0d cycle=%0d seq=%0d exp=%0d",
                                     o, cycle, seq, out_seq[o]);
                            data_errors++;
                        end
                        if (flit != out_flit[o]) begin
                            $display("ERROR flit mismatch port=%0d cycle=%0d flit=%0d exp=%0d",
                                     o, cycle, flit, out_flit[o]);
                            data_errors++;
                        end
                        if (out_vc[o*VC_W +: VC_W] != VC_W'(pkt_vc[seq])) begin
                            $display("ERROR vc mismatch port=%0d cycle=%0d", o, cycle);
                            data_errors++;
                        end
                        out_flit[o] = out_flit[o] + 1;
                        if (out_eop[o]) begin
                            if (flit != pkt_len[seq] - 1) begin
                                $display("ERROR eop flit port=%0d cycle=%0d", o, cycle);
                                data_errors++;
                            end
                            $fwrite(out_fd, "%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",
                                    o, seq, pkt_src[seq], pkt_dst[seq],
                                    pkt_len[seq], out_start[o], cycle - 1);
                            out_active[o] = 1'b0;
                        end
                    end
                end
            end
        end
    end

endmodule
