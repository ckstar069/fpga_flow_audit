module unsized_shift(
    input wire clk
);
    parameter int WIDTH = 32;
    // Unsized shift: 1 << (WIDTH-1) where WIDTH >= 32
    wire [63:0] mask = 1 << (WIDTH - 1);
endmodule