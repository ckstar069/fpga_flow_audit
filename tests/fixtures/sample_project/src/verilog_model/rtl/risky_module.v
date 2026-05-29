module risky_module(
    input wire clk
);
    // real type — synthesis incompatible
    real pi_val;
    // $display — synthesis incompatible
    always @(posedge clk) begin
        $display("debug: %f", pi_val);
    end
    // #delay — synthesis incompatible
    initial begin
        #10 pi_val = 3.14;
    end
    // $fatal — synthesis incompatible
    always @(posedge clk) begin
        if (pi_val < 0) $fatal(1, "negative");
    end
endmodule