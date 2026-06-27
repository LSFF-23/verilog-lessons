// example for dmm
module leds_dmm (
    clk,
    rst,
    button,
    switches,
    leds,
    avalon_address,
    avalon_read,
    avalon_readdata,
    avalon_write,
    avalon_writedata
);

input logic clk;
input logic rst;
input logic button;
input logic [7:0] switches;
output logic [7:0] leds;
// Avalon-MM Slave Interface
input logic avalon_address;
input logic avalon_read;
output logic [31:0] avalon_readdata;
input logic avalon_write;
input logic [31:0] avalon_writedata;

logic [7:0] switches_reg;
logic button_sync1, button_sync2;
logic reset_sync1, reset_sync2;

always_ff @(posedge clk, posedge rst) begin
    if (rst) begin
        reset_sync1 <= 1'b1;
        reset_sync2 <= 1'b1;
    end else begin
        reset_sync1 <= 1'b0;
        reset_sync2 <= reset_sync1;
    end
end

always_ff @(posedge clk) begin
    button_sync1 <= button;
    button_sync2 <= button_sync1;
end

always_ff @(posedge clk)
    if (reset_sync2)
        switches_reg <= '0;
    else if (button_sync2)
        switches_reg <= switches;

wire set_leds = avalon_write && avalon_address == 1'b0;
always_ff @(posedge clk)
    if (reset_sync2)
        leds <= '0;
    else if (set_leds)
        leds <= avalon_writedata[7:0];

wire get_leds = avalon_read && avalon_address == 1'b0;
wire get_switches = avalon_read && avalon_address == 1'b1;
always_comb
    if (get_leds)
        avalon_readdata = {24'b0, leds};
    else if (get_switches)
        avalon_readdata = {24'b0, switches_reg};
    else
        avalon_readdata = 32'b0;

endmodule