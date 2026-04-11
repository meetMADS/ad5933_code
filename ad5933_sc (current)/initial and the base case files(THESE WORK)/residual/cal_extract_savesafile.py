"""
AD5933 — Code 1: Calibration Extractor (file-saving version)
==============================================================
Runs a calibration sweep with R_CAL connected between VOUT (Pin6) and VIN (Pin5).
Computes per-frequency gain factor and system phase, saves to cal_data.txt on Pico flash.
File format per line:  freq_hz,gain_factor,system_phase_rad

FIX applied vs previous version:
  _freq_code() now uses (f * 4 / MCLK_HZ) * 2^27 — the correct datasheet formula.
"""

import machine, time, math

# ── I2C ───────────────────────────────────────────────────────────────────────
# scl = machine.Pin(3)
# sda = machine.Pin(2)
# i2c = machine.I2C(1, sda=sda, scl=scl, freq=400_000)
i2c = machine.I2C(0, sda=machine.Pin(4), scl=machine.Pin(5), freq=400000)

AD5933_ADDR = 0x0D

# ── USER CONFIG ───────────────────────────────────────────────────────────────
MCLK_HZ         = 16.776e6
START_FREQ_HZ   = 10_000
FREQ_INC_HZ     = 1_000
NUM_INCREMENTS  = 89
SETTLING_CYCLES = 15
R_CAL_OHMS      = 100_000.0   # <-- measured value of your calibration resistor (Ohms)
R_FB_OHMS       = 100_000.0   # <-- measured value of your feedback resistor (Ohms)
OUTPUT_RANGE    = 2          # 1=~2Vpp, 2=~1Vpp, 3=~0.4Vpp, 4=~0.2Vpp
PGA_GAIN_x1     = True       # True = PGA x1, False = PGA x5

CAL_FILE = "cal_data.txt"    # saved to Pico flash (/)

# ── REGISTERS ─────────────────────────────────────────────────────────────────
REG_CTRL_HI=0x80; REG_CTRL_LO=0x81
REG_FREQ_HI=0x82; REG_FREQ_MID=0x83; REG_FREQ_LO=0x84
REG_INC_HI =0x85; REG_INC_MID =0x86; REG_INC_LO =0x87
REG_NINC_HI=0x88; REG_NINC_LO =0x89
REG_SETTLE_HI=0x8A; REG_SETTLE_LO=0x8B
REG_STATUS=0x8F
REG_TEMP_HI=0x92; REG_TEMP_LO=0x93
REG_REAL_HI=0x94; REG_REAL_LO=0x95
REG_IMAG_HI=0x96; REG_IMAG_LO=0x97

CMD_INIT_START_FREQ=0x10; CMD_START_SWEEP=0x20; CMD_INCREMENT_FREQ=0x30
CMD_MEASURE_TEMP=0x90;    CMD_POWER_DOWN=0xA0;  CMD_STANDBY=0xB0
STATUS_TEMP_READY=0x01;   STATUS_DATA_READY=0x02; STATUS_SWEEP_DONE=0x04

# ── LOW-LEVEL HELPERS ─────────────────────────────────────────────────────────
def _wr(reg, val):  i2c.writeto_mem(AD5933_ADDR, reg, bytes([val & 0xFF]))
def _rd(reg):       return i2c.readfrom_mem(AD5933_ADDR, reg, 1)[0]
def _rd16s(rh, rl):
    raw = (_rd(rh) << 8) | _rd(rl)
    return raw - 65536 if raw & 0x8000 else raw

# FIX: multiply by 4 — datasheet formula: Code = (f_out / (MCLK/4)) * 2^27
def _freq_code(f): return int((f * 4 / MCLK_HZ) * (2**27)) & 0xFFFFFF

def _ctrl_lo():
    rb  = {1:0b00, 2:0b11, 3:0b10, 4:0b01}.get(OUTPUT_RANGE, 0)
    pga = 1 if PGA_GAIN_x1 else 0
    return ((rb>>1)&1)<<2 | ((rb&1)<<1) | pga

def _cmd(c): _wr(REG_CTRL_HI, c | _ctrl_lo())

def _poll(mask, timeout_ms=3000):
    dl = time.ticks_add(time.ticks_ms(), timeout_ms)
    while True:
        if _rd(REG_STATUS) & mask: return True
        if time.ticks_diff(dl, time.ticks_ms()) <= 0:
            print("  [WARN] timeout 0x{:02X}".format(mask)); return False
        time.sleep_ms(1)

# ── SWEEP PROGRAMMING & ENGINE ────────────────────────────────────────────────
def _prog():
    sf = _freq_code(START_FREQ_HZ); fi = _freq_code(FREQ_INC_HZ)
    n  = min(NUM_INCREMENTS, 511);  sc = min(SETTLING_CYCLES, 511)
    _wr(0x82,(sf>>16)&0xFF); _wr(0x83,(sf>>8)&0xFF); _wr(0x84,sf&0xFF)
    _wr(0x85,(fi>>16)&0xFF); _wr(0x86,(fi>>8)&0xFF); _wr(0x87,fi&0xFF)
    _wr(0x88,(n>>8)&0x01);   _wr(0x89,n&0xFF)
    _wr(0x8A,(sc>>8)&0x01);  _wr(0x8B,sc&0xFF)

def _sweep():
    _wr(REG_CTRL_HI, CMD_POWER_DOWN); _wr(REG_CTRL_LO, 0x00); time.sleep_ms(5)
    _cmd(CMD_STANDBY);                _wr(REG_CTRL_LO, 0x00); time.sleep_ms(5)
    _cmd(CMD_INIT_START_FREQ);        time.sleep_ms(100)
    _cmd(CMD_START_SWEEP)
    pts = []; freq = START_FREQ_HZ
    for _ in range(NUM_INCREMENTS + 1):
        if not _poll(STATUS_DATA_READY): break
        r  = _rd16s(REG_REAL_HI, REG_REAL_LO)
        im = _rd16s(REG_IMAG_HI, REG_IMAG_LO)
        pts.append((freq, r, im))
        if _rd(REG_STATUS) & STATUS_SWEEP_DONE: break
        _cmd(CMD_INCREMENT_FREQ); freq += FREQ_INC_HZ
    _wr(REG_CTRL_HI, CMD_POWER_DOWN)
    return pts

def read_temp():
    _wr(REG_CTRL_HI, CMD_MEASURE_TEMP); _wr(REG_CTRL_LO, 0x00); time.sleep_ms(1)
    if not _poll(STATUS_TEMP_READY, 50): return None
    raw = (_rd(REG_TEMP_HI) << 8) | _rd(REG_TEMP_LO)
    return ((raw - 16384) / 32.0) if (raw & 0x2000) else (raw / 32.0)

# ── MAIN ──────────────────────────────────────────────────────────────────────
print("\n AD5933 — Calibration Extractor")
print("  I2C:", i2c.scan())
temp = read_temp()
if temp: print("  Temp: {:.2f} C".format(temp))
print("  R_CAL={}\u03a9  R_FB={}\u03a9  -> sweep starting...\n".format(int(R_CAL_OHMS), int(R_FB_OHMS)))

_prog()
raw = _sweep()

if not raw:
    print("  [ERROR] No sweep data. Check wiring.")
else:
    print("  {:>8s} {:>8s} {:>8s} {:>14s} {:>14s}".format(
        "Freq(Hz)", "Real", "Imag", "GainFactor", "SysPhase(rad)"))
    print("  " + "-"*60)

    with open(CAL_FILE, "w") as f:
        for (freq, r, im) in raw:
            mag = math.sqrt(r*r + im*im)
            if mag == 0:
                print("  {:>8d} -- zero mag, skipped --".format(freq))
                continue
            # Gain Factor = 1 / (Z_CAL * |DFT|)
            gf = 1.0 / (R_CAL_OHMS * mag)
            # System phase: atan2 handles all quadrants correctly
            sp = math.atan2(im, r)
            # Format: freq,gain_factor,system_phase_rad
            f.write("{},{:.9e},{:.9f}\n".format(freq, gf, sp))
            print("  {:>8d} {:>8d} {:>8d} {:>14.6e} {:>14.9f}".format(
                freq, r, im, gf, sp))

    print("\n  Saved {} points to \'{}\'. Calibration done.".format(len(raw), CAL_FILE))
