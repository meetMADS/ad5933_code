"""
AD5933 — Pair A, Code 1: Measure + Save to Pico Flash  (Averaged)
==================================================================
Loads calibration from cal_data.txt (written by cal_extract_savesafile.py).
Runs NUM_AVERAGES sweep iterations, averages raw (R, Im) per frequency point,
then computes impedance from the averaged values. Saves results to result.csv.
On laptop run: python fetch_and_plot_pico.py

FIXES applied vs previous version:
1. _freq_code() uses (f * 4 / MCLK_HZ) * 2^27 — correct datasheet formula.
2. Phase calculation uses math.atan2() directly — faulty quadrant
   correction block removed (wrong for reactive loads like capacitors).
"""

import machine, time, math

# ── I2C ───────────────────────────────────────────────────────────────────────
# scl = machine.Pin(3)
# sda = machine.Pin(2)
# i2c = machine.I2C(1, sda=sda, scl=scl, freq=400_000)
i2c = machine.I2C(0, sda=machine.Pin(4), scl=machine.Pin(5), freq=400000)

AD5933_ADDR = 0x0D

# ── USER CONFIG ───────────────────────────────────────────────────────────────
MCLK_HZ        = 16.776e6
START_FREQ_HZ  = 10_000
FREQ_INC_HZ    = 1_000
NUM_INCREMENTS = 89
SETTLING_CYCLES = 15
OUTPUT_RANGE   = 2        # 1=~2Vpp, 2=~1Vpp, 3=~0.4Vpp, 4=~0.2Vpp
PGA_GAIN_x1    = True     # True = PGA x1, False = PGA x5

NUM_AVERAGES   = 4        # ← number of sweep iterations to average over

CAL_FILE    = "cal_data.txt"   # written by cal_extract_savesafile.py
RESULT_FILE = "result_179.csv"     # output saved to Pico flash

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
CMD_MEASURE_TEMP=0x90; CMD_POWER_DOWN=0xA0; CMD_STANDBY=0xB0
STATUS_TEMP_READY=0x01; STATUS_DATA_READY=0x02; STATUS_SWEEP_DONE=0x04

# ── LOW-LEVEL HELPERS ─────────────────────────────────────────────────────────
def _wr(reg, val): i2c.writeto_mem(AD5933_ADDR, reg, bytes([val & 0xFF]))
def _rd(reg): return i2c.readfrom_mem(AD5933_ADDR, reg, 1)[0]
def _rd16s(rh, rl):
    raw = (_rd(rh) << 8) | _rd(rl)
    return raw - 65536 if raw & 0x8000 else raw

def _freq_code(f): return int((f * 4 / MCLK_HZ) * (2**27)) & 0xFFFFFF

def _ctrl_lo():
    rb = {1:0b00, 2:0b11, 3:0b10, 4:0b01}.get(OUTPUT_RANGE, 0)
    pga = 1 if PGA_GAIN_x1 else 0
    return ((rb>>1)&1)<<2 | ((rb&1)<<1) | pga

def _cmd(c): _wr(REG_CTRL_HI, c | _ctrl_lo())

def _poll(mask, timeout_ms=3000):
    dl = time.ticks_add(time.ticks_ms(), timeout_ms)
    while True:
        if _rd(REG_STATUS) & mask: return True
        if time.ticks_diff(dl, time.ticks_ms()) <= 0:
            print(" [WARN] timeout 0x{:02X}".format(mask)); return False
        time.sleep_ms(1)

def _prog():
    sf = _freq_code(START_FREQ_HZ); fi = _freq_code(FREQ_INC_HZ)
    n = min(NUM_INCREMENTS, 511); sc = min(SETTLING_CYCLES, 511)
    _wr(0x82,(sf>>16)&0xFF); _wr(0x83,(sf>>8)&0xFF); _wr(0x84,sf&0xFF)
    _wr(0x85,(fi>>16)&0xFF); _wr(0x86,(fi>>8)&0xFF); _wr(0x87,fi&0xFF)
    _wr(0x88,(n>>8)&0x01);   _wr(0x89,n&0xFF)
    _wr(0x8A,(sc>>8)&0x01);  _wr(0x8B,sc&0xFF)

def _sweep():
    _wr(REG_CTRL_HI, CMD_POWER_DOWN); _wr(REG_CTRL_LO, 0x00); time.sleep_ms(5)
    _cmd(CMD_STANDBY); _wr(REG_CTRL_LO, 0x00); time.sleep_ms(5)
    _cmd(CMD_INIT_START_FREQ); time.sleep_ms(100)
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

# ── LOAD CALIBRATION FILE ─────────────────────────────────────────────────────
print("\n AD5933 — Measure + Save to Pico Flash  [Averaging: {} sweeps]".format(NUM_AVERAGES))
print(" I2C:", i2c.scan())

gain_factors = []
system_phases = []

try:
    with open(CAL_FILE, "r") as f:
        for line in f:
            p = line.strip().split(",")
            if len(p) < 3: continue
            gain_factors.append(float(p[1]))
            system_phases.append(float(p[2]))
except OSError:
    print(" [ERROR] \'{}\' not found. Run cal_extract_savesafile.py first.".format(CAL_FILE))
    raise SystemExit

if not gain_factors:
    print(" [ERROR] Cal file empty."); raise SystemExit

print(" Loaded {} cal points. Avg GF: {:.6e}".format(
    len(gain_factors), sum(gain_factors) / len(gain_factors)))
temp = read_temp()
if temp: print(" Temp: {:.2f} C".format(temp))

print("\n Connect UNKNOWN IMPEDANCE between VOUT (Pin6) and VIN (Pin5).")
print(" Starting in 1 second...\n")

# ── MULTI-SWEEP AVERAGE ───────────────────────────────────────────────────────
# acc[idx] = [freq, sum_r, sum_im, count]
_prog()
acc = {}   # keyed by frequency index

for iteration in range(NUM_AVERAGES):
    print(" Sweep {}/{}...".format(iteration + 1, NUM_AVERAGES))
    raw = _sweep()
    for idx, (freq, r, im) in enumerate(raw):
        if idx not in acc:
            acc[idx] = [freq, 0.0, 0.0, 0]
        acc[idx][1] += r
        acc[idx][2] += im
        acc[idx][3] += 1

print(" All sweeps done. Computing averages...\n")

# ── COMPUTE IMPEDANCE FROM AVERAGED R/Im AND SAVE ────────────────────────────
if not acc:
    print(" [ERROR] No sweep data.")
else:
    count = 0
    with open(RESULT_FILE, "w") as out:
        out.write("freq_hz,z_mag_ohm,z_phase_deg,z_real_ohm,z_imag_ohm\n")
        print(f" freq,   zmag(ohm), zphase(deg), zreal(ohm), zimag(ohm)")
        for idx in sorted(acc.keys()):
            freq, sum_r, sum_im, n = acc[idx]
            if n == 0: continue
            r_avg  = sum_r  / n
            im_avg = sum_im / n

            mag = math.sqrt(r_avg*r_avg + im_avg*im_avg)
            if mag == 0: continue

            gf = gain_factors[idx] if idx < len(gain_factors) else gain_factors[0]
            sp = system_phases[idx] if idx < len(system_phases) else system_phases[0]

            z_mag = 1.0 / (gf * mag)

            z_phase_rad = math.atan2(im_avg, r_avg) - sp
            z_phase_deg = math.degrees(z_phase_rad)

            z_real = z_mag * math.cos(z_phase_rad)
            z_imag = z_mag * math.sin(z_phase_rad)

            out.write("{},{:.4f},{:.4f},{:.4f},{:.4f}\n".format(
                freq, z_mag, z_phase_deg, z_real, z_imag))
            print("  {:>8d} {:>12.2f} {:>10.3f} {:>12.2f} {:>12.2f}".format(
                freq, z_mag, z_phase_deg, z_real, z_imag))
            count += 1

    print("\n Saved {} points (avg of {} sweeps) to \'{}\'." .format(count, NUM_AVERAGES, RESULT_FILE))
    print(" On laptop run: python fetch_and_plot_pico.py")
