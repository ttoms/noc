`default_nettype none
//==============================================================================
// Module : arbiter_rr
// Description : 轮询仲裁，one-hot 指针 + 双 pri_tree，O(log N) 组合深度
// Features :
//   - 输出独热 gnt，gnt_vld=OR(req)
//   - 无请求时 gnt=0、gnt_vld=0，指针保持
//   - 仅当 upd=1（当前 gnt 被使用）时指针指向被授权索引的下一路
//   - 指针为 one-hot，后缀 OR 生成"低于指针"掩码，不使用取模
// Parameters :
//   N - 请求路数，默认 4，必须 >= 1
// Limitations :
//   - gnt 为组合输出，授权方需保证请求在握手周期内有效
//   - upd 必须与当前 gnt 的消费拍对齐；upd 恒 1 等价于逐拍推进
//   - 指针寄存器为 N 位 one-hot，面积随 N 线性增长
//==============================================================================
module arbiter_rr #(
    parameter   int N   =   4
) (
    input   logic           clk     ,
    input   logic           rst_n   ,
    input   logic           upd     ,
    input   logic [N -1:0]  req     ,
    output  logic [N -1:0]  gnt     ,
    output  logic           gnt_vld
);

    localparam int LOGN = (N > 1) ? $clog2(N) : 1;
    localparam logic [N-1:0] PTR_RESET = N'(1);

    logic [N -1:0]  ptr         ;   // one-hot
    logic [N -1:0]  lower_mask  ;   // 低于 ptr 的通道
    logic [N -1:0]  req_hi      ;
    logic [N -1:0]  req_lo      ;
    logic [N -1:0]  gnt_hi      ;
    logic [N -1:0]  gnt_lo      ;
    logic [N -1:0]  nxt_ptr     ;
    logic           ptr_en      ;
    logic [N -1:0]  suf         ;   // 后缀 OR：suf[i] = |ptr[i:N-1]

    // 低于 ptr 的通道；ptr 的下一路及其后由 req_hi 覆盖
    suf_or #(
        .N      (N      ),
        .LEVELS (LOGN   )
    ) U_SUF (
        .v      (ptr    ),
        .out    (suf    )
    );

    assign lower_mask = suf >> 1;
    assign req_hi     = req & ~lower_mask;
    assign req_lo     = req & lower_mask;

    pri_tree #(
        .N  (N  )
    ) U_HI (
        .req    (req_hi ),
        .gnt    (gnt_hi )
    );

    pri_tree #(
        .N  (N  )
    ) U_LO (
        .req    (req_lo ),
        .gnt    (gnt_lo )
    );

    assign gnt     = (|gnt_hi) ? gnt_hi : gnt_lo;
    assign gnt_vld = |req;
    assign ptr_en  = gnt_vld & upd;
    assign nxt_ptr = (gnt << 1) | (gnt >> (N-1));

    dffr #(
        .W          (N          ),
        .RESET_VAL  (PTR_RESET  )
    ) U_PTR (
        .clk    (clk        ),
        .rst_n  (rst_n      ),
        .en     (ptr_en     ),
        .d      (nxt_ptr    ),
        .q      (ptr        )
    );

`ifdef SVA_ON
`include "arbiter_rr.sva"
`endif

endmodule

`default_nettype wire
