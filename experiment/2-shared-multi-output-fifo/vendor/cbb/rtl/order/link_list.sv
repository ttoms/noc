`default_nettype none
//==============================================================================
// Module : link_list
// Description : 多队列链式 FIFO，节点为外部 ID；每队列 head/tail + next 指针
// Features :
//   - 1 个 push 端口 + N 个 pop 端口；不同队列可同拍 push/pop
//   - 每队列每拍最多 1 次 pop；调用方保证同一队列不被两个 pop 端口选中
//   - 同队列同拍 push+pop：单节点时直接替换，多节点时读 next 并写旧 tail
//   - 每节点附带 DST_W 位 sideband（供 mo_fifo_top 的头目的查询）
//   - 不分配/释放 ID；ID 生命周期由上层 idpool 管理
// Parameters :
//   ID_NUM  - 节点 ID 数量，默认 16，必须是 2 的幂且 >= 2
//   QID_NUM - 队列数，默认 4，必须是 2 的幂且 >= 2
//   N       - pop 端口数，默认 2，必须 >= 1
//   ID_W    - ID 位宽，默认 $clog2(ID_NUM)
//   QID_W   - 队列号位宽，默认 $clog2(QID_NUM)
//   DST_W   - sideband 位宽，默认 1
// Limitations :
//   - 不做 ID 分配/释放，也不检查 push ID 是否已被占用
//   - 同一队列同拍被两个 pop 端口选中为非法用法，SVA 报错
//   - next_ram/dst_ram 不复位；只保证已 push 的节点可读
//   - 每队列无深度限制；full 恒 0，由上层 idpool 反压
//==============================================================================
module link_list #(
    parameter   int ID_NUM  =   16              ,
    parameter   int QID_NUM =   4               ,
    parameter   int N       =   2               ,
    parameter   int ID_W    =   $clog2(ID_NUM)  ,
    parameter   int QID_W   =   $clog2(QID_NUM) ,
    parameter   int DST_W   =   1
) (
    input   logic                       clk         ,
    input   logic                       rst_n       ,
    input   logic                       push_vld    ,
    input   logic [QID_W         -1:0]  push_qid    ,
    input   logic [ID_W          -1:0]  push_id     ,
    input   logic [DST_W         -1:0]  push_dst    ,
    output  logic                       push_rdy    ,
    input   logic [N             -1:0]  pop_vld     ,
    input   logic [N*QID_W       -1:0]  pop_qid     ,
    output  logic [N*ID_W        -1:0]  pop_id      ,
    output  logic [N             -1:0]  pop_rdy     ,
    output  logic [QID_NUM*ID_W  -1:0]  head_id     ,
    output  logic [QID_NUM*DST_W -1:0]  head_dst    ,
    output  logic [QID_NUM       -1:0]  empty       ,
    output  logic [QID_NUM       -1:0]  full
);

logic [ID_W    -1:0]    head_q          [QID_NUM];
logic [ID_W    -1:0]    tail_q          [QID_NUM];
logic [QID_NUM -1:0]    ne_q            ;
logic [ID_W    -1:0]    head_d          [QID_NUM];
logic [ID_W    -1:0]    tail_d          [QID_NUM];
logic [QID_NUM -1:0]    ne_d            ;
logic [QID_NUM -1:0]    push_hit        ;
logic [QID_NUM -1:0]    pop_req         ;
logic [QID_NUM -1:0]    pop_hit         ;
logic [QID_NUM -1:0]    q_one           ;
logic                   next_write_en   ;
logic [ID_W    -1:0]    next_ram        [ID_NUM];
logic [DST_W   -1:0]    dst_ram         [ID_NUM];

assign push_rdy = 1'b1;

generate
    for (genvar q = 0; q < QID_NUM; q++) begin : g_state
        logic q_en;

        assign q_en = push_hit[q] | pop_hit[q];

        dffr #(
            .W          (ID_W   ),
            .RESET_VAL  ('0     )
        ) U_HEAD (
            .clk    (clk        ),
            .rst_n  (rst_n      ),
            .en     (q_en       ),
            .d      (head_d[q]  ),
            .q      (head_q[q]  )
        );

        dffr #(
            .W          (ID_W   ),
            .RESET_VAL  ('0     )
        ) U_TAIL (
            .clk    (clk        ),
            .rst_n  (rst_n      ),
            .en     (q_en       ),
            .d      (tail_d[q]  ),
            .q      (tail_q[q]  )
        );

        dffr #(
            .W          (1  ),
            .RESET_VAL  ('0 )
        ) U_NE (
            .clk    (clk        ),
            .rst_n  (rst_n      ),
            .en     (q_en       ),
            .d      (ne_d[q]    ),
            .q      (ne_q[q]    )
        );

        assign head_id[q*ID_W +: ID_W]     = head_q[q];
        assign head_dst[q*DST_W +: DST_W]  = ne_q[q] ? dst_ram[head_q[q]] : '0;
        assign empty[q]                    = ~ne_q[q];
        assign full[q]                     = 1'b0;
    end

    for (genvar p = 0; p < N; p++) begin : g_pop
        assign pop_id[p*ID_W +: ID_W] = head_q[pop_qid[p*QID_W +: QID_W]];
        assign pop_rdy[p]             = ne_q[pop_qid[p*QID_W +: QID_W]];
    end
endgenerate

function automatic logic [QID_NUM-1:0] collect_pop_req(
    input logic [N-1:0] vld,
    input logic [N*QID_W-1:0] qid
);
    logic [QID_NUM-1:0] req;
    req = '0;
    for (int p = 0; p < N; p++) begin
        if (vld[p]) begin
            req[qid[p*QID_W +: QID_W]] = 1'b1;
        end
    end
    return req;
endfunction

assign pop_req = collect_pop_req(pop_vld, pop_qid);
assign pop_hit = pop_req & ne_q;

always_comb begin
    for (int q = 0; q < QID_NUM; q++) begin
        push_hit[q] = push_vld && (push_qid == QID_W'(q));
        q_one[q]    = ne_q[q] && (head_q[q] == tail_q[q]);
    end
end

always_comb begin
    for (int q = 0; q < QID_NUM; q++) begin
        head_d[q] = head_q[q];
        tail_d[q] = tail_q[q];
        ne_d[q]   = ne_q[q];
        if (pop_hit[q]) begin
            if (push_hit[q] && q_one[q]) begin
                head_d[q] = push_id;
                tail_d[q] = push_id;
                ne_d[q]   = 1'b1;
            end else if (q_one[q]) begin
                head_d[q] = '0;
                tail_d[q] = '0;
                ne_d[q]   = 1'b0;
            end else begin
                head_d[q] = next_ram[head_q[q]];
                if (push_hit[q]) begin
                    tail_d[q] = push_id;
                end
                ne_d[q] = 1'b1;
            end
        end else if (push_hit[q]) begin
            if (!ne_q[q]) begin
                head_d[q] = push_id;
            end
            tail_d[q] = push_id;
            ne_d[q]   = 1'b1;
        end
    end
end

assign next_write_en = push_vld
                     && ne_q[push_qid]
                     && !(pop_hit[push_qid] && q_one[push_qid]);

always_ff @(posedge clk) begin
    if (push_vld) begin
        dst_ram[push_id] <= push_dst;
        if (next_write_en) begin
            next_ram[tail_q[push_qid]] <= push_id;
        end
    end
end

`ifdef SVA_ON
`include "link_list.sva"
`endif

endmodule

`default_nettype wire
