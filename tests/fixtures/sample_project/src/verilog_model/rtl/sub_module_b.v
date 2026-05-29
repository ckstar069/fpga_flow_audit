module sub_module_b(
    input  wire clk,
    input  wire rst_n,
    output reg [7:0] metric
);
    // Runtime division — this is a BLOCKER
    always @(posedge clk) begin
        metric <= metric / 2;
    end
endmodule