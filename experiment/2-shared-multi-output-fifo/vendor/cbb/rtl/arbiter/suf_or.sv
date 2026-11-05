`default_nettype none
//==============================================================================
// Module : suf_or
// Description : 后缀 OR 树，out[i] = |v[i:N-1]，O(log N) 组合深度
// Features :
//   - 递归二分，LEVELS 级后得到后缀 OR
//   - 输出用于生成"低于指针"的独热掩码
// Parameters :
//   N      - 向量位宽，默认 8，必须 >= 1
//   LEVELS - 级数，默认 3，应取 $clog2(N)（N=1 时为 1）
// Limitations :
//   - 纯组合；面积 O(N log N)
//   - 仲裁器内部复用，不单独作为 CBB 发布
//==============================================================================
module suf_or #(
    parameter   int N       =   8   ,
    parameter   int LEVELS  =   3
) (
    input   logic [N -1:0]  v   ,
    output  logic [N -1:0]  out
);

generate
    if (LEVELS == 0) begin : g_end
        assign out = v;
    end else begin : g_stage
        logic [N-1:0] nxt;
        genvar i;

        for (i = 0; i < N; i++) begin : g_bit
            if (i + (1 << (LEVELS-1)) < N) begin : g_comb
                assign nxt[i] = v[i] | v[i + (1 << (LEVELS-1))];
            end else begin : g_hold
                assign nxt[i] = v[i];
            end
        end

        suf_or #(
            .N      (N          ),
            .LEVELS (LEVELS - 1 )
        ) U_NEXT (
            .v      (nxt    ),
            .out    (out    )
        );
    end
endgenerate

endmodule

`default_nettype wire
