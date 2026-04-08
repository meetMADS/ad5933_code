import math
import machine
from machine import Pin
import time

# ================= CONFIG =================
MCLK_HZ = 16.776e6
SETTLING_CYCLES = 400
NUM_AVG = 4

OUTPUT_RANGE = 2
PGA_GAIN_x1 = True

# ================= I2C =================
i2c = machine.I2C(0, sda=machine.Pin(4), scl=machine.Pin(5), freq=400000)
AD5933_ADDR = 0x0D

# ================= REGISTERS =================
REG_CTRL_HI = 0x80
REG_STATUS = 0x8F
REG_REAL_HI = 0x94
REG_REAL_LO = 0x95
REG_IMAG_HI = 0x96
REG_IMAG_LO = 0x97

# ================= COMMANDS =================
CMD_INIT_START_FREQ = 0x10
CMD_START_SWEEP = 0x20
CMD_REPEAT_FREQ = 0x40
CMD_STANDBY = 0xB0

STATUS_DATA_READY = 0x02

# ================= GPIO (YOUR MUX) =================
_ASL1 = Pin(2, Pin.OUT)
_ASL0 = Pin(1, Pin.OUT)
_BSL1 = Pin(7, Pin.OUT)
_BSL0 = Pin(6, Pin.OUT)
_SHRT = Pin(0, Pin.OUT)

_SW_DUT_RCAL = Pin(28, Pin.OUT)

r_known = [1e3, 10e3, 48e3, 100e3, 201e3]

r_select_lines = [
    (0,0,0,0,1),
    (1,0,0,0,1),
    (0,0,0,0,0),
    (0,1,0,0,1),
    (0,0,1,0,0)
]

# ================= LOW LEVEL =================
def _wr(reg, val):
    i2c.writeto_mem(AD5933_ADDR, reg, bytes([val & 0xFF]))

def _rd(reg):
    return i2c.readfrom_mem(AD5933_ADDR, reg, 1)[0]

def _rd16s(rh, rl):
    raw = (_rd(rh) << 8) | _rd(rl)
    return raw - 65536 if raw & 0x8000 else raw

def _freq_code(f):
    return int((f * 4 / MCLK_HZ) * (2**27)) & 0xFFFFFF

def _ctrl_lo():
    rb = {1:0b00,2:0b11,3:0b10,4:0b01}[OUTPUT_RANGE]
    pga = 1 if PGA_GAIN_x1 else 0
    return ((rb >> 1)&1)<<2 | ((rb&1)<<1) | pga

def _cmd(c):
    _wr(REG_CTRL_HI, c | _ctrl_lo())

def _poll():
    while not (_rd(REG_STATUS) & STATUS_DATA_READY):
        pass

# ================= MUX SWITCH =================
def switching_logic_rcal_rfb(res):
    idx = r_known.index(res)
    asl1, asl0, bsl1, bsl0, shrt = r_select_lines[idx]

    _ASL1.value(asl1)
    _ASL0.value(asl0)
    _BSL1.value(bsl1)
    _BSL0.value(bsl0)
    _SHRT.value(shrt)

    time.sleep_ms(5)

# ================= CORE FIX =================
def stable_read(freq):
    """Proper AD5933 measurement (NO re-init per read)"""

    # program once
    sf = _freq_code(freq)

    _wr(0x82, (sf >> 16) & 0xFF)
    _wr(0x83, (sf >> 8) & 0xFF)
    _wr(0x84, sf & 0xFF)

    _wr(0x88, 0x00)
    _wr(0x89, 0x00)

    _wr(0x8A, (SETTLING_CYCLES >> 8) & 0x01)
    _wr(0x8B, SETTLING_CYCLES & 0xFF)

    _cmd(CMD_STANDBY)
    _cmd(CMD_INIT_START_FREQ)
    _cmd(CMD_START_SWEEP)

    _poll()

    sum_r = 0
    sum_i = 0

    for _ in range(NUM_AVG):
        r = _rd16s(REG_REAL_HI, REG_REAL_LO)
        im = _rd16s(REG_IMAG_HI, REG_IMAG_LO)

        sum_r += r
        sum_i += im

        _cmd(CMD_REPEAT_FREQ)
        _poll()

    return sum_r/NUM_AVG, sum_i/NUM_AVG

# ================= CALIBRATION =================
def gain_factor_cal(rcal, freq):
    _SW_DUT_RCAL.value(0)
    switching_logic_rcal_rfb(rcal)

    r, im = stable_read(freq)

    mag = math.sqrt(r*r + im*im)

    gf = 1/(rcal * mag)
    phase = math.atan2(im, r)

    return gf, phase

# ================= MEASURE =================
def measure_single(freq, gf, phase, rcal):
    _SW_DUT_RCAL.value(1)
    switching_logic_rcal_rfb(rcal)

    r, im = stable_read(freq)

    mag = math.sqrt(r*r + im*im)

    z_mag = 1/(gf * mag)
    z_phase = math.atan2(im, r) - phase

    zr = z_mag * math.cos(z_phase)
    zi = z_mag * math.sin(z_phase)

    return zr, zi

# ================= CAL TABLE =================
def calibration_table_maker(start, stop, n):
    freqs = [start + i*(stop-start)/(n-1) for i in range(n)]

    gf_mat = [[None]*n for _ in r_known]

    for i, rcal in enumerate(r_known):
        for j, f in enumerate(freqs):
            gf_mat[i][j] = gain_factor_cal(rcal, f)

    return gf_mat, freqs

# ================= SWEEP =================
def sweep(gf_mat, freqs):
    results = []

    for j, f in enumerate(freqs):
        rcal = r_known[len(r_known)//2]  # start mid

        gf, ph = gf_mat[r_known.index(rcal)][j]

        zr, zi = measure_single(f, gf, ph, rcal)

        results.append((f, zr, zi, rcal))

    return results