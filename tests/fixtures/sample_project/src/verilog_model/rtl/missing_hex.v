module missing_hex(
    input wire clk
);
    reg [7:0] data [0:15];
    initial begin
        $readmemh("nonexistent.hex", data);
    end
endmodule