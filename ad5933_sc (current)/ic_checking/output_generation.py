"""
AD5933 — Sinusoidal Output Generator
=====================================
Continuously excites VOUT (Pin 6) with a sinusoid at EXCITE_FREQ_HZ.
Set EXCITE_FREQ_HZ below (or pass as the single config arg at top).
"""

import machine, time

# ── ARGUMENT: set your desired output frequency here ─────────────────────────
EXCITE_FREQ_HZ = 20_000        # <--- CHANGE THIS to your desired frequency (Hz)

# ── I2C ───────────────────────────────────────────────────────────────────────
# scl = machine.Pin(3)
# sda = machine.Pin(2)
# i2c = machine.I2C(1, sda=sda, scl=scl, freq=400_000)
i2c = machine.I2C(0, sda=machine.Pin(4), scl=machine.Pin(5), freq=400000)
AD5933_ADDR = 0x0D

# ── CONFIG ────────────────────────────────────────────────────────────────────
MCLK_HZ      = 16.776e6
OUTPUT_RANGE = 1        # 1=~2Vpp, 2=~1Vpp, 3=~0.4Vpp, 4=~0.2Vpp
PGA_GAIN_x1  = True     # True = PGA x1, False = PGA x5
SETTLING_CYCLES = 10

# ── REGISTERS ─────────────────────────────────────────────────────────────────
REG_CTRL_HI   = 0x80; REG_CTRL_LO   = 0x81
REG_FREQ_HI   = 0x82; REG_FREQ_MID  = 0x83; REG_FREQ_LO  = 0x84
REG_INC_HI    = 0x85; REG_INC_MID   = 0x86; REG_INC_LO   = 0x87
REG_NINC_HI   = 0x88; REG_NINC_LO   = 0x89
REG_SETTLE_HI = 0x8A; REG_SETTLE_LO = 0x8B

CMD_INIT_START_FREQ = 0x10
CMD_POWER_DOWN      = 0xA0
CMD_STANDBY         = 0xB0

# ── HELPERS ───────────────────────────────────────────────────────────────────
def _wr(reg, val):
    i2c.writeto_mem(AD5933_ADDR, reg, bytes([val & 0xFF]))

def _freq_code(f):
    return int((f * 4 / MCLK_HZ) * (2**27)) & 0xFFFFFF

def _ctrl_lo():
    rb  = {1: 0b00, 2: 0b11, 3: 0b10, 4: 0b01}.get(OUTPUT_RANGE, 0)
    pga = 1 if PGA_GAIN_x1 else 0
    return ((rb >> 1) & 1) << 2 | ((rb & 1) << 1) | pga

def _cmd(c):
    _wr(REG_CTRL_HI, c | _ctrl_lo())

def _program_freq(f):
    fc = _freq_code(f)
    _wr(REG_FREQ_HI,  (fc >> 16) & 0xFF)
    _wr(REG_FREQ_MID, (fc >>  8) & 0xFF)
    _wr(REG_FREQ_LO,   fc        & 0xFF)
    # increment = 0, num_increments = 0 (single tone, no sweep)
    _wr(REG_INC_HI, 0x00); _wr(REG_INC_MID, 0x00); _wr(REG_INC_LO, 0x00)
    _wr(REG_NINC_HI, 0x00); _wr(REG_NINC_LO, 0x00)
    sc = min(SETTLING_CYCLES, 511)
    _wr(REG_SETTLE_HI, (sc >> 8) & 0x01)
    _wr(REG_SETTLE_LO,  sc       & 0xFF)

# ── MAIN: start tone, loop forever ───────────────────────────────────────────
print("AD5933 — Excite VOUT at {} Hz".format(EXCITE_FREQ_HZ))
print("I2C devices:", i2c.scan())

# Power-down → Standby → Init → tone ON
_wr(REG_CTRL_HI, CMD_POWER_DOWN); _wr(REG_CTRL_LO, 0x00); time.sleep_ms(5)
_program_freq(EXCITE_FREQ_HZ)
_cmd(CMD_STANDBY);         _wr(REG_CTRL_LO, 0x00); time.sleep_ms(5)
_cmd(CMD_INIT_START_FREQ); time.sleep_ms(100)   # tone now active on VOUT

print("Sinusoid active on VOUT. Looping forever (Ctrl+C to stop)...")

while True:
    # The AD5933 keeps outputting the tone autonomously once CMD_INIT_START_FREQ
    # is issued. This loop just keeps the Pico alive and can re-arm if needed.
    time.sleep_ms(500)
