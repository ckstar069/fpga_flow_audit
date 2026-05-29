module DSP48E1_stub(
    input wire clk,
    input wire a,
    input wire b,
    output wire p
);
    // Simulation stub — not synthesizable
    assign p = a * b;
endmodule