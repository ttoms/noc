`default_nettype none
//==============================================================================
// Module : pri_tree
// Description : 固定优先级树，最低索引优先，O(log N) 组合深度
// Features :
//   - req 非零时 gnt 恰好一位有效
//   - 递归二分，深度 ceil(log2(N))
// Parameters :
//   N - 输入/输出位宽，默认 8，必须 >= 1
// Limitations :
//   - 纯组合；面积 O(N)
//   - 仲裁器内部复用，不单独作为 CBB 发布
//==============================================================================
module pri_tree #(
    parameter   int N   =   8
) (
    input   logic [N -1:0]  req ,
    output  logic [N -1:0]  gnt
);

generate
    if (N == 1) begin : g_one
        assign gnt = req;
    end else begin : g_split
        localparam int NL = N / 2;
        localparam int NR = N - NL;

        logic [NL-1:0] gnt_l;
        logic [NR-1:0] gnt_r;

        pri_tree #(
            .N  (NL )
        ) U_L (
            .req    (req[NL-1:0]    ),
            .gnt    (gnt_l          )
        );

        pri_tree #(
            .N  (NR )
        ) U_R (
            .req    (req[N-1:NL]    ),
            .gnt    (gnt_r          )
        );

        assign gnt = (|gnt_l) ? {{(NR){1'b0}}, gnt_l}
                              : {gnt_r, {(NL){1'b0}}};
    end
endgenerate

endmodule

`default_nettype wire
