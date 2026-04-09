# AD5933 communication

import math
import machine
from machine import Pin
import time



LED = machine.Pin("LED", machine.Pin.OUT)
LED.value(0)

# ── HARDWARE CONFIG (edit once) ────────────────────────────────────────────
MCLK_HZ = 16.776e6
SETTLING_CYCLES = 50
OUTPUT_RANGE = 2  # 1=~2Vpp, 2=~1Vpp, 3=~0.4Vpp, 4=~0.2Vpp
PGA_GAIN_x1 = True

CAL_SWEEPS = 3  # internal: how many repeated readings to average
_MEAS_SWEEPS = 3

# ── I2C ───────────────────────────────────────────────────────────────────
# scl = machine.Pin(3)
# sda = machine.Pin(2)
# i2c = machine.I2C(1, sda=sda, scl=scl, freq=400_000)
i2c = machine.I2C(0, sda=machine.Pin(4), scl=machine.Pin(5), freq=400000)
AD5933_ADDR = 0x0D

# ── REGISTER ADDRESSES ────────────────────────────────────────────────────
REG_CTRL_HI = 0x80
REG_CTRL_LO = 0x81
REG_STATUS = 0x8F
REG_TEMP_HI = 0x92
REG_TEMP_LO = 0x93
REG_REAL_HI = 0x94
REG_REAL_LO = 0x95
REG_IMAG_HI = 0x96
REG_IMAG_LO = 0x97

# some extra values
REG_SETTLE_HI = 0x8A
REG_SETTLE_LO = 0x8B

# ── COMMANDS ──────────────────────────────────────────────────────────────
CMD_INIT_START_FREQ = 0x10
CMD_START_SWEEP = 0x20
CMD_POWER_DOWN = 0xA0
CMD_STANDBY = 0xB0
CMD_MEASURE_TEMP = 0x90

STATUS_TEMP_READY = 0x01
STATUS_DATA_READY = 0x02

# some extra values
CMD_INCREMENT_FREQ = 0x30
STATUS_SWEEP_DONE = 0x04

# ── LOW-LEVEL I2C HELPERS ─────────────────────────────────────────────────


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
    rb = {1: 0b00, 2: 0b11, 3: 0b10, 4: 0b01}.get(OUTPUT_RANGE, 0)
    pga = 1 if PGA_GAIN_x1 else 0
    return ((rb >> 1) & 1) << 2 | ((rb & 1) << 1) | pga


def _cmd(c):
    _wr(REG_CTRL_HI, c | _ctrl_lo())


def _poll(mask, timeout_ms=3000):
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while True:
        if _rd(REG_STATUS) & mask:
            return True
        if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            # print("[WARN] poll timeout for mask 0x{:02X}".format(mask))
            return False
        time.sleep_ms(1)


# ── SINGLE-POINT PROGRAMMING ──────────────────────────────────────────────


def _prog_single(freq):
    """
    Program AD5933 registers for a single measurement at `freq` Hz.
    Uses 0 increments — only the start frequency point is measured.
    """
    """
    Program the AD5933 with:
      - start_freq  = freq_hz
      - freq_inc    = 0        (we never increment; only one point)
      - num_inc     = 0
      - settling    = SETTLING_CYCLES
    """

    sf = _freq_code(freq)
    fi = _freq_code(1000)  # dummy increment (never executed)

    sc = min(SETTLING_CYCLES, 511)

    _wr(0x82, (sf >> 16) & 0xFF)
    _wr(0x83, (sf >> 8) & 0xFF)
    _wr(0x84, sf & 0xFF)

    _wr(0x85, (fi >> 16) & 0xFF)  # freq increment — unused but required
    _wr(0x86, (fi >> 8) & 0xFF)
    _wr(0x87, fi & 0xFF)

    _wr(0x88, 0x00)  # num increments Hi = 0
    _wr(0x89, 0x00)  # num increments Lo = 0  → single point

    _wr(0x8A, (sc >> 8) & 0x01)
    _wr(0x8B, sc & 0xFF)


# ── SINGLE RAW MEASUREMENT ────────────────────────────────────────────────


def _read_one_point(freq):
    """
    Take one raw measurement at `freq` Hz.
    Returns (real, imag) 16-bit signed integers, or None on timeout.
    """
    """
    Wake the chip, fire a single-point sweep, capture (R, Im) and power down.
    Returns (r, im) as signed 16-bit integers, or None on timeout.
    """
    # UNCOMMENT
    # _prog_single(freq)

    _wr(REG_CTRL_HI, CMD_POWER_DOWN)
    _wr(REG_CTRL_LO, 0x00)
    time.sleep_ms(5)

    _cmd(CMD_STANDBY)
    _wr(REG_CTRL_LO, 0x00)
    time.sleep_ms(5)

    _cmd(CMD_INIT_START_FREQ)
    time.sleep_ms(100)

    _cmd(CMD_START_SWEEP)

    if not _poll(STATUS_DATA_READY):
        _wr(REG_CTRL_HI, CMD_POWER_DOWN)
        return None

    r = _rd16s(REG_REAL_HI, REG_REAL_LO)
    im = _rd16s(REG_IMAG_HI, REG_IMAG_LO)

    _wr(REG_CTRL_HI, CMD_POWER_DOWN)
    return (r, im)


# ── TEMPORAL AVERAGE (multi-read) ─────────────────────────────────────────


def _average_raw(freq, num_reads):
    """
    Repeat the measurement `num_reads` times at `freq` Hz.
    Accumulate and average R/Im before returning.
    Returns (r_avg, im_avg) or None if all reads failed.
    """
    _prog_single(freq)

    sum_r = 0.0
    sum_im = 0.0
    cnt = 0

    for i in range(num_reads):
        result = _read_one_point(freq)
        if result is None:
            # print("[WARN] read {}/{} failed at {} Hz".format(i + 1, num_reads, freq))
            continue
        sum_r += result[0]
        sum_im += result[1]
        cnt += 1

    if cnt == 0:
        return None
    return sum_r / cnt, sum_im / cnt


# ── PUBLIC API ────────────────────────────────────────────────────────────

# reading_bare


def measure_single_freq(freq, gain_factor, system_phase_rad, num_sweeps=None):
    """
    Take `num_sweeps` readings at `freq`, average R/Im, apply calibration,
    and return [z_real_ohm, z_imag_ohm].

    Parameters
    ----------
    freq          : int/float  — target frequency in Hz
    gain_factor      : float      — from gain_factor_matrix for this frequency
    system_phase_rad : float      — from gain_factor_matrix for this frequency
    num_sweeps       : int        — readings to average (default: _MEAS_SWEEPS)

    Returns
    -------
    [z_real_ohm, z_imag_ohm]  as a 2-element list, or None on failure.
    """
    if num_sweeps is None:
        num_sweeps = _MEAS_SWEEPS

    _prog_single(freq)

    sum_r = 0.0
    sum_im = 0.0
    count = 0

    for i in range(num_sweeps):
        print(f"measuring mode: repeated calling, freq={freq}")
        result = _read_one_point(freq)
        print(f" reading result real, imaginary {result[0]}, {result[1]}")
        if result is None:
            # print("  [WARN] sweep {} failed at {} Hz".format(i + 1, freq))
            continue
        sum_r += result[0]
        sum_im += result[1]
        count += 1

    if count == 0:
        # print("  [ERROR] all sweeps failed at {} Hz".format(freq))
        return None

    r_avg = sum_r / count
    im_avg = sum_im / count

    mag = math.sqrt(r_avg * r_avg + im_avg * im_avg)
    if mag == 0:
        # print("  [ERROR] zero magnitude at {} Hz".format(freq))
        return None

    z_mag = 1.0 / (gain_factor * mag)
    z_phase_rad = math.atan2(im_avg, r_avg) - system_phase_rad

    z_real = z_mag * math.cos(z_phase_rad)
    z_imag = z_mag * math.sin(z_phase_rad)

    return [z_real, z_imag]


# gain_factor_cal


def gain_factor_cal(r_cal_ohms, freq):
    """
    Compute and return the gain factor of the AD5933 at `freq` Hz,
    using `r_cal_ohms` as the known calibration resistor value.

    Internally runs CAL_SWEEPS repeated measurements and averages
    R/Im BEFORE computing GF (preserves linearity of the average).

    Parameters
    ----------
    freq        : float  — measurement frequency in Hz
    r_cal_ohms  : float  — calibration resistor value in Ohms (e.g. 10000.0)

    Returns
    -------
    float  — gain factor at `freq`, or None on hardware failure
    """
    result = _average_raw(freq, CAL_SWEEPS)
    if result is None:
        # print("[ERROR] gain_factor_cal: all reads failed at {} Hz".format(freq))
        return None, None

    r_avg, im_avg = result
    mag = math.sqrt(r_avg * r_avg + im_avg * im_avg)

    if mag == 0.0:
        # print("[ERROR] gain_factor_cal: zero magnitude at {} Hz".format(freq))
        return None, None

    gain_factor = 1.0 / (r_cal_ohms * mag)
    system_phase = math.atan2(im_avg, r_avg)
    return gain_factor, system_phase


# ── OPTIONAL: read chip temperature ───────────────────────────────────────


def read_temp():
    """Returns AD5933 die temperature in °C, or None on failure."""
    _wr(REG_CTRL_HI, CMD_MEASURE_TEMP)
    _wr(REG_CTRL_LO, 0x00)
    time.sleep_ms(1)
    if not _poll(STATUS_TEMP_READY, 50):
        return None
    raw = (_rd(REG_TEMP_HI) << 8) | _rd(REG_TEMP_LO)
    return ((raw - 16384) / 32.0) if (raw & 0x2000) else (raw / 32.0)


_ASL1 = Pin(2, Pin.OUT)  # MUX A sel1
_ASL0 = Pin(1, Pin.OUT)  # MUX A sel0
_BSL1 = Pin(7, Pin.OUT)  # MUX B sel1
_BSL0 = Pin(6, Pin.OUT)  # MUX B sel0
_SHRT = Pin(0, Pin.OUT)

_SW_DUT_RCAL = Pin(28, Pin.OUT)

# these are the rfb and rcal values in kΩ
# r_known = [1, 4.9, 48, 51.9, 98.4, 145.4, 218, 315.4, 392, 426.4, 484, 531, 701, 812, 875]
# r_known = [
#     # 1e3, 9.9e3,
#     # 48e3,
#     51.9e3,
#     98.4e3,
#     145.4e3,
#     218e3
#     # 315.4e3,
#     # 392e3,
# ]
# # , 426.4e3, 484e3, 531e3, 701e3, 812e3, 875e3]

r_known =  [
    48e3,
    145.4e3,
    218e3,
    315.4e3,
    392e3
    # 426.4,
    # 489.4e3,
    # 531e3,
    # 701e3,
    # 812e3,
    # 875
]

r_select_lines = [
    (0, 0, 0, 0),   # 48    kΩ
    (1, 0, 0, 0),   # 145.4 kΩ
    (0, 0, 0, 1),   # 218   kΩ
    (1, 0, 0, 1),   # 315.4 kΩ
    (0, 0, 1, 1)   # 392   kΩ
    # (1, 0, 1, 0),   # 426.4 kΩ
    # (1, 0, 1, 1),   # 484   kΩ
    # (1, 1, 0, 0),   # 531   kΩ
    # (1, 1, 0, 1),   # 701   kΩ
    # (1, 1, 1, 0),   # 812   kΩ
    # (1, 1, 1, 1)   # 875    kΩ
]


# r_select_lines is an array which has the required select lines which need to be made in order to achieve
# the above resistance values.
# the select lines order is as follows muxa(sel1, sel0), muxb(sel1, sel0)
# the gpio pins in the above order are asl1 asl0 bsl1 bsl0 are gp2 gp1 gp7 gp6


# (asl1, asl0, bsl1, bsl0) → (GP2, GP1, GP7, GP6)
# r_select_lines = [
#     # (0, 0, 0, 0, 1),   # 1     kΩ
#     # (0, 1, 0, 0, 1),   # 4.9   kΩ
#     # (0, 0, 0, 0, 0),  # 48    kΩ
#     (0, 1, 0, 0, 0),  # 51.9  kΩ
#     (1, 0, 0, 0, 1),  # 98.4  kΩ
#     (1, 0, 0, 0, 0),  # 145.4 kΩ
#     (0, 0, 0, 1, 0)  # 218   kΩ
#     # (1, 0, 0, 1, 0),  # 315.4 kΩ
#     # (0, 0, 1, 1, 0),  # 392   kΩ
#     # (1, 0, 1, 0, 0),   # 426.4 kΩ
#     # (1, 1, 0, 0, 1),   # 484   kΩ
#     # (1, 1, 0, 0, 0),   # 531   kΩ
#     # (1, 1, 0, 1, 0),   # 701   kΩ
#     # (1, 1, 1, 0, 0),   # 812   kΩ
#     # (1, 1, 1, 1, 0)    # 875   kΩ
# ]



# our user gives the start stop and no of readings only and the dut is connected on the output
# rcal and rfb have same logic lines and hence when one is changed other is changed as well

# we have a single switch which switches between the dut and rcal ---- this is present on the gp28

# need a cal function and readings function


def switching_logic_rcal_rfb(resistance_value):
    """
    Switch MUX A and MUX B select lines to connect
    the resistor matching resistance_value (Ω).
    resistance_value MUST be a value present in r_known.
    """
    idx = r_known.index(resistance_value)  # direct lookup, O(n) but n=11
    # asl1, asl0, bsl1, bsl0, shrt = r_select_lines[idx]
    asl1, asl0, bsl1, bsl0 = r_select_lines[idx]

    _ASL1.value(asl1)  # GP2
    _ASL0.value(asl0)  # GP1
    _BSL1.value(bsl1)  # GP7
    _BSL0.value(bsl0)  # GP6
    # _SHRT.value(shrt)

    time.sleep_ms(10)  # MUX settling time


# def gain_factor_cal(res, freq):
#     # take the help from the cal_extract_savesafile_auto.py to get the logic of how to find the gain factor
#     # this fucntion returns the gain factor at the required frequency
#     return gain_factor

# gain_factor_matrix = []

def calibration_table_maker( START_FREQ, STOP_FREQ, NO_READINGS):
    # swicth the gp28 to rcal
    # then we need to transverse the whole freq range & all the resistance values and then take the
    # gain factor at those points
    if NO_READINGS <= 1:
        freq_array = [START_FREQ]
    else:
        step = (STOP_FREQ - START_FREQ) / (NO_READINGS - 1)
        freq_array = [START_FREQ + i * step for i in range(NO_READINGS)]
    # this will result in a huge 2d matrix with x cooordinate as rcal values and
    # the y coordinate as the freq values which user has suggested

    _SW_DUT_RCAL.value(0)
    time.sleep_ms(2)

    # global gain_factor_matrix
    gain_factor_matrix = [
        [(None, None) for _ in range(len(freq_array))] for _ in range(len(r_known))
    ]

    for i, res in enumerate(r_known):
        switching_logic_rcal_rfb(res)
        for j, freq in enumerate(freq_array):
            gain_factor_matrix[i][j] = gain_factor_cal(res, freq)
            print(f"{res}, {freq} value reading is {gain_factor_matrix[i][j]}")

    return gain_factor_matrix

####################################################################################################
####################################################################################################
####################################################################################################
####################################################################################################
####################################################################################################


def _find_bracket(freq_array, freq):
    """
    Find the bracketing indices for `freq` in `freq_array`.

    Returns:
        (lo_idx, hi_idx, t)   — where t in [0,1] is the interpolation weight
        None                  — if freq is outside [freq_array[0], freq_array[-1]]
    """
    f_min = freq_array[0]
    f_max = freq_array[-1]

    # Out-of-range check (with a tiny epsilon for floating-point edge cases)
    eps = (f_max - f_min) * 1e-9 if f_max != f_min else 1e-3
    if freq < f_min - eps or freq > f_max + eps:
        return None

    # Clamp edge touches caused by float rounding
    if freq <= f_min:
        return (0, 0, 0.0)
    if freq >= f_max:
        n = len(freq_array) - 1
        return (n, n, 0.0)

    # Linear scan for bracket  (freq_array is short, so O(n) is fine)
    for i in range(len(freq_array) - 1):
        if freq_array[i] <= freq <= freq_array[i + 1]:
            span = freq_array[i + 1] - freq_array[i]
            t = (freq - freq_array[i]) / span if span != 0.0 else 0.0
            return (i, i + 1, t)

    # Should never reach here
    n = len(freq_array) - 1
    return (n, n, 0.0)



def _interp_gf_sp(gain_factor_matrix, rcal_idx, freq, freq_array):
    """
    Return (gf, sp) for `freq` using linear interpolation between
    the two nearest calibrated points.

    Returns (None, None) if freq is outside the calibrated range
    (caller must recalibrate on-the-fly).
    """
    bracket = _find_bracket(freq_array, freq)
    if bracket is None:
        print(f"out of range value we have got")
        return None, None                     # out-of-range → trigger recal

    lo, hi, t = bracket
    print(f"  Interpolating GF/SP for {freq} Hz between indices {lo} and {hi} with t={t:.3f}")
    gf_lo, sp_lo = gain_factor_matrix[rcal_idx][lo]
    gf_hi, sp_hi = gain_factor_matrix[rcal_idx][hi]

    # Handle missing calibration data at either neighbour
    if gf_lo is None and gf_hi is None:
        return None, None
    if gf_lo is None:
        return gf_hi, sp_hi
    if gf_hi is None:
        return gf_lo, sp_lo

    # Exact match or true interpolation
    gf = gf_lo + t * (gf_hi - gf_lo)
    sp = sp_lo + t * (sp_hi - sp_lo)   # small Δφ → no wrap issue
    return gf, sp

def reading_bare(gain_factor_matrix, rcal, freq, freq_array):
    """
    Measure DUT impedance at `freq` Hz using calibration resistor `rcal`.

    • If freq is inside the calibrated range  → interpolate GF/SP.
    • If freq is outside the calibrated range → recalibrate at that exact
      frequency on-the-fly, then measure.
    """
    # ── 1. Find rcal index (safe: rcal always comes from r_known directly) ──
    rcal_idx = r_known.index(rcal)

    # ── 2. Get GF / SP (interpolated or None if out-of-range) ───────────────
    gf, sp = _interp_gf_sp(gain_factor_matrix, rcal_idx, freq, freq_array)

    # ── 3. Out-of-range → recalibrate at this exact frequency ───────────────
    if gf is None:
        # Switch circuit to RCAL path
        print(f"recalibrating")
        _SW_DUT_RCAL.value(0)
        time.sleep_ms(2)
        switching_logic_rcal_rfb(rcal)

        gf, sp = gain_factor_cal(rcal, freq)   # live single-point cal

        # Restore DUT path before measuring
        _SW_DUT_RCAL.value(1)
        time.sleep_ms(2)
        switching_logic_rcal_rfb(rcal)

        if gf is None:
            # print("[ERROR] reading_bare: on-the-fly recal failed at {} Hz".format(freq))
            return None

    # ── 4. Switch to DUT and measure ────────────────────────────────────────
    _SW_DUT_RCAL.value(1)
    switching_logic_rcal_rfb(rcal)

    return measure_single_freq(freq, gf, sp)


####################################################################################################
####################################################################################################
####################################################################################################
####################################################################################################
####################################################################################################
####################################################################################################
####################################################################################################
####################################################################################################
####################################################################################################

# def reading_bare(gain_factor_matrix, rcal, freq, freq_array):
#     # first switch to the dut using the gp28
#     _SW_DUT_RCAL.value(1)
#     # switch to the required rcal
#     switching_logic_rcal_rfb(rcal)
#     # see the code measure_save_pico_auto.py file to see how readings are made
#     # based on the above code and gain factor matrix now make the single freq reading and return the value of

#     # Look up indices
#     freq_idx = freq_array.index(freq)
#     rcal_idx = r_known.index(rcal)

#     # Use the indices to get the matrix data
#     gf, sp = gain_factor_matrix[rcal_idx][freq_idx]

#     # Use the imported engine to do the actual read
#     measured_val = measure_single_freq(freq, gf, sp)

#     return measured_val


def floor_cal(measured_val):
    # UNCOMMENT
    # this code finds the value of the resistance just smaller than the measured impedance magnitude
    if measured_val is None:
        return 0  # Or handle the error appropriately
    # measured_val = (z_real, z_imag)
    z_mag = math.sqrt(measured_val[0] ** 2 + measured_val[1] ** 2)

    floor_idx = 0
    for i, res in enumerate(r_known):
        if res <= z_mag:
            floor_idx = i
        else:
            break

    return floor_idx


def reading_with_logic(gain_factor_matrix, freq, freq_array):
    # THIS IS THE MAIN CODE WHERE WE NEED TO MAKE THE CHNAGES AS MENTIONED IN THE PSEUDOCODE
    # you can suggest some better logic if you have
    _SW_DUT_RCAL.value(1)
    rcal_visited = [False] * len(r_known)
    master_measured = 0

    rcal = r_known[0]
    measured_val = reading_bare(gain_factor_matrix, rcal, freq, freq_array)
    # if measured_val is None:
    #     return None # Abort gracefully if hardware fails
    rcal_visited[0] = True

    while True:
        idx_a = floor_cal(measured_val)
        rcal_flr_a = r_known[idx_a]
        if rcal_visited[idx_a] == True:

            return measured_val, rcal_flr_a
            # return measured_val

        measured_at_ra = reading_bare(gain_factor_matrix, rcal_flr_a, freq, freq_array)
        rcal_visited[idx_a] = True
        rcal_flr_b = r_known[floor_cal(measured_at_ra)]

        if rcal_flr_b == rcal_flr_a:

            # only ceil calculation
            ceil_ind = floor_cal(measured_at_ra)
            if ceil_ind >= len(r_known) - 1:
                ceil_ind = ceil_ind
            else:
                ceil_ind += 1

            rcal_ceil = r_known[ceil_ind]
            measured_ceil = reading_bare(
                gain_factor_matrix, rcal_ceil, freq, freq_array
            )
            rcal_visited[ceil_ind] = True

            if (measured_ceil[0] ** 2 + measured_ceil[1] ** 2) ** 0.5 < rcal_ceil:
                return measured_at_ra, rcal_flr_a
                # return measured_at_ra
            else:
                measured_val = measured_ceil

        elif rcal_flr_a > rcal_flr_b:
            measured_val = reading_bare(
                gain_factor_matrix, rcal_flr_b, freq, freq_array
            )
            rcal_visited[floor_cal(measured_at_ra)] = True
        else:
            measured_val = measured_at_ra

    return measured_val


# START_FREQ    = 10_000    # Hz
# STOP_FREQ     = 30_000    # Hz
# NO_READINGS   = 20


# def main():
def sweep(gain_factor_matrix, START_FREQ, STOP_FREQ, NO_READINGS, mode):
    temp = read_temp()
    if temp is not None:
        # print("Chip temperature : {:.1f} °C".format(temp))
        pass
    else:
        return []
        # print("[WARN] Temperature read failed — check I2C wiring")

    # ── 2. Build frequency array ───────────────────────────────────────────
    if NO_READINGS <= 1:
        freq_array = [START_FREQ]
    else:
        step = (STOP_FREQ - START_FREQ) / (NO_READINGS - 1)
        freq_array = [START_FREQ + i * step for i in range(NO_READINGS)]
    # print("\nFrequency sweep  : {} Hz → {} Hz  ({} points)".format(START_FREQ, STOP_FREQ, len(freq_array)))

    # ── 3. Calibration ────────────────────────────────────────────────────
    # print(f"[STEP 1/3] Running calibration…")
    # calibration_table_maker(freq_array)
    # global gain_factor_matrix
    # print("Calibration done.")

    # # ── 4. Sweep at SAME RCAL ──────────────────────────────────────────────────────
    # print("[STEP 2/3] Measuring AT THE SAME VALUE RCAL …")
    # print("{:<12} {:<14} {:<14} {:<12} {:<12}".format("Freq (Hz)", "Z_real (Ω)", "Z_imag (Ω)", "|Z| (Ω)", "R_cal (Ω)"))
    # print("-" * 55)
    LED.value(1)
    # time.sleep_ms(10000)
    LED.value(0)
    results = []
    for freq in freq_array:
        # val, rcal = reading_with_logic(gain_factor_matrix, freq, freq_array)
        val, rcal = reading_with_logic(gain_factor_matrix, freq, freq_array)
        if val is None:
            # print("{:<12.1f}  [measurement failed]".format(freq))
            results.append((freq, None, None, None))
            continue
        zr, zi = val[0], val[1]
        # z_mag = (zr**2 + zi**2) ** 0.5
        # print("{:<12.1f} {:<14.2f} {:<14.2f} {:<12.2f} {:<12.2f}".format(freq, zr, zi, z_mag, rcal))
        results.append((freq, zr, zi, rcal))
        # time.sleep_ms(5)
    # print("=" * 55)
    # print("Sweep complete. {} / {} points succeeded.".format(sum(1 for _, zr, _ in results if zr is not None), len(results)))
    return results

    # while True:
    #     # print("Now you have measured gf now change the pins to measure the DUT or some other dut \n please PRESS D so that we know you have done the changes: \n and if you want to exit pls PRESS E")
    #     print(f" please press d when u have connected the 10kohm values")
    #     cin = input().strip().lower()

    #     if cin == 'd':
    #         # _adg_switch.value(1)   # IN=1 → D connected to S2

    #         # ── 4. Sweep DUT ──────────────────────────────────────────────────────
    #         print("[STEP 3/3] Measuring DUT …")
    #         print("{:<12} {:<14} {:<14} {:<12} {:<12}".format("Freq (Hz)", "Z_real (Ω)", "Z_imag (Ω)", "|Z| (Ω)", "R_cal (Ω)"))
    #         print("-" * 55)
    #         results = []
    #         for freq in freq_array:
    #             val, rcal = reading_with_logic(gain_factor_matrix, freq, freq_array)

    #             if val is None:
    #                 print("{:<12.1f}  [measurement failed]".format(freq))
    #                 results.append((freq, None, None, None))
    #                 continue

    #             zr, zi = val[0], val[1]
    #             z_mag = (zr**2 + zi**2) ** 0.5
    #             print("{:<12.1f} {:<14.2f} {:<14.2f} {:<12.2f} {:<12.2f}".format(freq, zr, zi, z_mag, rcal))
    #             results.append((freq, zr, zi, rcal))
    #             time.sleep_ms(50)

    #         print("=" * 55)
    #         # print("Sweep complete. {} / {} points succeeded.".format(sum(1 for _, zr, _ in results if zr is not None), len(results)))

    #     elif cin == 'e':
    #         print("THANK YOU FOR USING")
    #         break
    #     else:
    #         print("Invalid input. Use 'h' or 'l'.")
    #     time.sleep_ms(20)


# if __name__ == "__main__":
#     main()
