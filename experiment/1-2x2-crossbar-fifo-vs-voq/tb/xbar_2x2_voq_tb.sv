`timescale 1ns/1ps
// Trace-replay testbench for xbar_2x2_voq.
// Trace CSV: seq,src,dst,len,arrival
// Output CSV: port,src,len,start,end
module xbar_2x2_voq_tb #(
    // Per-VOQ depth.  Override at compile time, e.g.
    //   iverilog -P xbar_2x2_voq_tb.DEPTH=4 ...
    parameter int DEPTH = 16
);

    localparam int FLIT_W     = 32;
    localparam int MAX_PKTS   = 100000;
    localparam int MAX_CYCLES = 200000;

    logic clk;
    logic rst_n;

    logic [1:0]             in_vld;
    logic [1:0]             in_rdy;
    logic [1:0][FLIT_W-1:0] in_data;
    logic [1:0]             in_sop;
    logic [1:0]             in_eop;
    logic [1:0]             in_dst;

    logic [1:0]             out_vld;
    logic [1:0]             out_rdy;
    logic [1:0][FLIT_W-1:0] out_data;
    logic [1:0]             out_sop;
    logic [1:0]             out_eop;
    logic [1:0]             out_src_dbg;

    xbar_2x2_voq #(
        .FLIT_W    (FLIT_W),
        .VOQ_DEPTH (DEPTH )
    ) dut (
        .clk         (clk),
        .rst_n       (rst_n),
        .in_vld      (in_vld),
        .in_rdy      (in_rdy),
        .in_data     (in_data),
        .in_sop      (in_sop),
        .in_eop      (in_eop),
        .in_dst      (in_dst),
        .out_vld     (out_vld),
        .out_rdy     (out_rdy),
        .out_data    (out_data),
        .out_sop     (out_sop),
        .out_eop     (out_eop),
        .out_src_dbg (out_src_dbg)
    );

    integer cycle;
    integer sim_cycles;
    integer source_gap;
    integer rdy_period;
    integer rdy_high;
    integer trace_fd;
    integer out_fd;
    integer dbg_fd;
    reg [1023:0] trace_path;
    reg [1023:0] out_path;
    reg [1023:0] dbg_path;
    reg [1023:0] line_buf;
    logic done;
    logic dbg_en;

    function automatic integer popcount(input logic [DEPTH-1:0] v);
        integer k;
        begin
            popcount = 0;
            for (k = 0; k < DEPTH; k++)
                popcount = popcount + v[k];
        end
    endfunction

    // per-input trace arrays
    integer n0;
    integer n1;
    integer src0_dst [0:MAX_PKTS-1];
    integer src0_len [0:MAX_PKTS-1];
    integer src0_arr [0:MAX_PKTS-1];
    integer src1_dst [0:MAX_PKTS-1];
    integer src1_len [0:MAX_PKTS-1];
    integer src1_arr [0:MAX_PKTS-1];

    integer p0;
    integer p1;

    logic       cur_valid [0:1];
    integer     cur_len   [0:1];
    integer     cur_flit  [0:1];
    logic       cur_dst   [0:1];

    // output monitor state
    logic       out_active [0:1];
    integer     out_start  [0:1];
    integer     out_len    [0:1];
    integer     out_src    [0:1];
    integer     o;
    integer     data_errors;
    integer     protocol_errors;

    // Downstream ready pattern: period 0 means always ready.  Both the model
    // and the TB use ((cycle + 2*out) % period) < high.
    always_comb begin
        if (rdy_period <= 0) begin
            out_rdy = 2'b11;
        end else begin
            out_rdy[0] = ((cycle + 0) % rdy_period) < rdy_high;
            out_rdy[1] = ((cycle + 2) % rdy_period) < rdy_high;
        end
    end

    initial clk = 1'b0;
    always #5 clk = ~clk;

    assign in_vld[0] = cur_valid[0];
    assign in_vld[1] = cur_valid[1];
    assign in_data[0] = 32'h0000_0000 + cur_flit[0];
    assign in_data[1] = 32'h1000_0000 + cur_flit[1];
    assign in_sop[0] = cur_valid[0] && (cur_flit[0] == 0);
    assign in_sop[1] = cur_valid[1] && (cur_flit[1] == 0);
    assign in_eop[0] = cur_valid[0] && (cur_flit[0] == cur_len[0] - 1);
    assign in_eop[1] = cur_valid[1] && (cur_flit[1] == cur_len[1] - 1);
    assign in_dst[0] = cur_dst[0];
    assign in_dst[1] = cur_dst[1];

    initial begin
        for (int i = 0; i < 2; i++) begin
            cur_valid[i] = 1'b0;
            cur_len[i]   = 1;
            cur_flit[i]  = 0;
            cur_dst[i]   = 0;
            out_active[i] = 1'b0;
            out_start[i]  = 0;
            out_len[i]    = 0;
            out_src[i]    = 0;
        end
        n0 = 0;
        n1 = 0;
        p0 = 0;
        p1 = 0;
        data_errors = 0;
        protocol_errors = 0;
        cycle = 0;
        done = 1'b0;
        dbg_en = 1'b0;
        sim_cycles = MAX_CYCLES;
        source_gap = 0;
        if (!$value$plusargs("SOURCE_GAP=%d", source_gap))
            source_gap = 0;
        rdy_period = 0;
        rdy_high = 0;
        if (!$value$plusargs("RDY_PERIOD=%d", rdy_period))
            rdy_period = 0;
        if (!$value$plusargs("RDY_HIGH=%d", rdy_high))
            rdy_high = 0;

        if (!$value$plusargs("TRACE=%s", trace_path)) begin
            $display("ERROR: +TRACE=<csv> required");
            $finish;
        end
        if (!$value$plusargs("OUT=%s", out_path)) begin
            $display("ERROR: +OUT=<csv> required");
            $finish;
        end
        begin
            integer cyc_code;
            cyc_code = $value$plusargs("CYCLES=%d", sim_cycles);
        end

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
        $fwrite(out_fd, "port,src,len,start,end\n");

        if ($value$plusargs("DBG=%s", dbg_path)) begin
            dbg_fd = $fopen(dbg_path, "w");
            if (dbg_fd == 0) begin
                $display("ERROR: cannot open debug %s", dbg_path);
                $finish;
            end
            dbg_en = 1'b1;
            $fwrite(dbg_fd, "cycle,in0_vld,in0_wr,in0_stall,in0_flit,in0_occ_d0,in0_occ_d1,in0_vld_d0,in0_vld_d1,in1_vld,in1_wr,in1_stall,in1_flit,in1_occ_d0,in1_occ_d1,in1_vld_d0,in1_vld_d1,out0_src,out0_vld,out0_sop,out0_eop,out0_grant,out0_locked,out0_locked_src,out1_src,out1_vld,out1_sop,out1_eop,out1_grant,out1_locked,out1_locked_src\n");
        end

        // skip header
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
            integer code;
            forever begin
                code = $fscanf(trace_fd, "%d,%d,%d,%d,%d\n", seq, src, dst, len, arrival);
                if (code != 5) disable read_trace;
                if (src == 0) begin
                    src0_dst[n0] = dst;
                    src0_len[n0] = len;
                    src0_arr[n0] = arrival;
                    n0 = n0 + 1;
                end else begin
                    src1_dst[n1] = dst;
                    src1_len[n1] = len;
                    src1_arr[n1] = arrival;
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
        if (dbg_en)
            $fclose(dbg_fd);
        $display("DONE cycle=%0d n0=%0d n1=%0d data_errors=%0d protocol_errors=%0d",
                 cycle, n0, n1, data_errors, protocol_errors);
        if (data_errors != 0 || protocol_errors != 0)
            $fatal(1, "data errors=%0d protocol errors=%0d",
                   data_errors, protocol_errors);
        $finish;
    end

    // Source state update at posedge.
    always @(posedge clk) begin
        if (!rst_n) begin
            cycle <= 0;
            for (int i = 0; i < 2; i++) begin
                cur_valid[i] <= 1'b0;
                cur_len[i]   <= 1;
                cur_flit[i]  <= 0;
                cur_dst[i]   <= 0;
            end
            p0 <= 0;
            p1 <= 0;
        end else begin
            cycle <= cycle + 1;

            if (!cur_valid[0] && p0 < n0 && src0_arr[p0] <= cycle) begin
                cur_valid[0] <= 1'b1;
                cur_len[0]   <= src0_len[p0];
                cur_flit[0]  <= 0;
                cur_dst[0]   <= src0_dst[p0];
                p0 <= p0 + 1;
            end else if (cur_valid[0] && in_rdy[0]) begin
                if (cur_flit[0] == cur_len[0] - 1) begin
                    if (source_gap == 0 && p0 < n0 && src0_arr[p0] <= cycle) begin
                        cur_valid[0] <= 1'b1;
                        cur_len[0]   <= src0_len[p0];
                        cur_flit[0]  <= 0;
                        cur_dst[0]   <= src0_dst[p0];
                        p0 <= p0 + 1;
                    end else begin
                        cur_valid[0] <= 1'b0;
                    end
                end else begin
                    cur_flit[0] <= cur_flit[0] + 1;
                end
            end

            if (!cur_valid[1] && p1 < n1 && src1_arr[p1] <= cycle) begin
                cur_valid[1] <= 1'b1;
                cur_len[1]   <= src1_len[p1];
                cur_flit[1]  <= 0;
                cur_dst[1]   <= src1_dst[p1];
                p1 <= p1 + 1;
            end else if (cur_valid[1] && in_rdy[1]) begin
                if (cur_flit[1] == cur_len[1] - 1) begin
                    if (source_gap == 0 && p1 < n1 && src1_arr[p1] <= cycle) begin
                        cur_valid[1] <= 1'b1;
                        cur_len[1]   <= src1_len[p1];
                        cur_flit[1]  <= 0;
                        cur_dst[1]   <= src1_dst[p1];
                        p1 <= p1 + 1;
                    end else begin
                        cur_valid[1] <= 1'b0;
                    end
                end else begin
                    cur_flit[1] <= cur_flit[1] + 1;
                end
            end
        end
    end

    // Output monitor at negedge, after DUT combinational outputs settle.
    always @(negedge clk) begin
        if (rst_n && !done) begin
            for (o = 0; o < 2; o++) begin
                if (out_vld[o] && out_rdy[o]) begin
                    if (out_sop[o] && out_active[o]) begin
                        $display("ERROR: nested SOP port=%0d cycle=%0d", o, cycle);
                        protocol_errors = protocol_errors + 1;
                    end
                    if (!out_sop[o] && !out_active[o]) begin
                        $display("ERROR: flit without SOP port=%0d cycle=%0d", o, cycle);
                        protocol_errors = protocol_errors + 1;
                    end
                    if (out_eop[o] && !out_active[o] && !out_sop[o]) begin
                        $display("ERROR: EOP without SOP port=%0d cycle=%0d", o, cycle);
                        protocol_errors = protocol_errors + 1;
                    end
                    if (out_sop[o]) begin
                        out_active[o] = 1'b1;
                        out_start[o]  = cycle - 1;
                        out_len[o]    = 0;
                        out_src[o]    = out_src_dbg[o];
                    end
                    if (out_active[o]) begin
                        if (out_data[o] !==
                            ((out_src[o] == 0) ? 32'h0000_0000 : 32'h1000_0000)
                            + out_len[o]) begin
                            $display("ERROR: data mismatch port=%0d cycle=%0d expected=%08x got=%08x",
                                     o, cycle,
                                     ((out_src[o] == 0) ? 32'h0000_0000 : 32'h1000_0000)
                                     + out_len[o], out_data[o]);
                            data_errors = data_errors + 1;
                        end
                        out_len[o] = out_len[o] + 1;
                        if (out_eop[o]) begin
                            $fwrite(out_fd, "%0d,%0d,%0d,%0d,%0d\n",
                                    o, out_src[o], out_len[o], out_start[o],
                                    cycle - 1);
                            out_active[o] = 1'b0;
                        end
                    end
                end
            end

            if (dbg_en) begin
                $fwrite(dbg_fd, "%0d", cycle);
                for (o = 0; o < 2; o++) begin
                    $fwrite(dbg_fd, ",%0d,%0d,%0d,",
                            cur_valid[o],
                            cur_valid[o] && in_rdy[o],
                            cur_valid[o] && !in_rdy[o]);
                    if (cur_valid[o])
                        $fwrite(dbg_fd, "%0d", cur_flit[o]);
                    else
                        $fwrite(dbg_fd, "-");
                    $fwrite(dbg_fd, ",%0d,%0d,%0d,%0d",
                            (o == 0) ? popcount(voq_entry_vld_dbg[0][0])
                                     : popcount(voq_entry_vld_dbg[1][0]),
                            (o == 0) ? popcount(voq_entry_vld_dbg[0][1])
                                     : popcount(voq_entry_vld_dbg[1][1]),
                            (o == 0) ? voq_rd_vld_dbg[0][0]
                                     : voq_rd_vld_dbg[1][0],
                            (o == 0) ? voq_rd_vld_dbg[0][1]
                                     : voq_rd_vld_dbg[1][1]);
                end
                for (o = 0; o < 2; o++) begin
                    if (out_vld[o])
                        $fwrite(dbg_fd, ",%0d", out_src_dbg[o]);
                    else
                        $fwrite(dbg_fd, ",-");
                    $fwrite(dbg_fd, ",%0d,%0d,%0d,%0d,%0d,%0d",
                            out_vld[o],
                            out_vld[o] && out_sop[o],
                            out_vld[o] && out_eop[o],
                            (o == 0) ? gnt0_vld_dbg : gnt1_vld_dbg,
                            locked_dbg[o],
                            locked_src_dbg[o]);
                end
                $fwrite(dbg_fd, "\n");
            end
        end
    end

    // Debug aliases (hierarchical references into the DUT).
    logic [1:0][1:0][DEPTH-1:0] voq_entry_vld_dbg;
    logic [1:0][1:0] voq_rd_vld_dbg;
    logic [1:0]      locked_dbg;
    logic [1:0]      locked_src_dbg;
    logic            gnt0_vld_dbg;
    logic            gnt1_vld_dbg;
    assign voq_entry_vld_dbg[0][0] = dut.g_input[0].g_voq[0].U_FIFO.entry_vld;
    assign voq_entry_vld_dbg[0][1] = dut.g_input[0].g_voq[1].U_FIFO.entry_vld;
    assign voq_entry_vld_dbg[1][0] = dut.g_input[1].g_voq[0].U_FIFO.entry_vld;
    assign voq_entry_vld_dbg[1][1] = dut.g_input[1].g_voq[1].U_FIFO.entry_vld;
    assign voq_rd_vld_dbg = dut.voq_rd_vld;
    assign locked_dbg      = dut.locked;
    assign locked_src_dbg  = dut.locked_src;
    assign gnt0_vld_dbg    = dut.gnt0_vld;
    assign gnt1_vld_dbg    = dut.gnt1_vld;

endmodule
