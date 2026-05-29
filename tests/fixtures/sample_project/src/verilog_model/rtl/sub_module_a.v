module sub_module_a(
    input  wire clk,
    input  wire rst_n,
    output reg [7:0] result
);
    reg [15:0] mem [0:255];
    initial begin
        $readmemh("atan_lut.hex", mem);
    end
    always @(posedge clk) begin
        result <= mem[0][7:0];
    end
endmodule