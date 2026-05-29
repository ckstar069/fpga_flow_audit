module top_module(
    input  wire clk,
    input  wire rst_n,
    output wire [7:0] data_out
);
    sub_module_a u_a (
        .clk(clk),
        .rst_n(rst_n),
        .result(data_out)
    );
    sub_module_b u_b (
        .clk(clk),
        .rst_n(rst_n),
        .metric()
    );
endmodule