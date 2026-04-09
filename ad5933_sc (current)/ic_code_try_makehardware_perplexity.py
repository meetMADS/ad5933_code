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

CAL_SWEEPS = 6      # internal: how many repeated readings to average
_MEAS_SWEEPS = 6

# ── I2C ───────────────────────────────────────────────────────────────────
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
# ── HARDWARE SWEEP HELPERS ────────────────────────────────────────────────

def _prog_sweep(start_freq, freq_step, num_points):
    """
    Program AD5933 for a true hardware sweep:
      start_freq  : Hz (float/int)
      freq_step   : Hz between points (float/int)
      num_points  : total number of measurement points (1..512)
                    num_increments = num_points - 1  (max 511 per datasheet)
    """
    num_inc = num_points - 1          # datasheet: num increments = points - 1
    if num_inc < 0:   num_inc = 0
    if num_inc > 511: num_inc = 511   # hardware limit

    sf = _freq_code(start_freq)
    fi = _freq_code(freq_step) if freq_step > 0 else 0
    sc = min(SETTLING_CYCLES, 511)

    # Start frequency
    _wr(0x82, (sf >> 16) & 0xFF)
    _wr(0x83, (sf >>  8) & 0xFF)
    _wr(0x84,  sf        & 0xFF)

    # Frequency increment
    _wr(0x85, (fi >> 16) & 0xFF)
    _wr(0x86, (fi >>  8) & 0xFF)
    _wr(0x87,  fi        & 0xFF)

    # Number of increments  (9-bit: hi byte is bit8 only)
    _wr(0x88, (num_inc >> 8) & 0x01)
    _wr(0x89,  num_inc       & 0xFF)

    # Settling time cycles
    _wr(0x8A, (sc >> 8) & 0x01)
    _wr(0x8B,  sc        & 0xFF)


def _hw_sweep_raw(start_freq, freq_step, num_points, timeout_ms=3000):
    """
    Execute a hardware frequency sweep and return raw (R, Im) pairs.

    Returns:
        list of (freq_hz, r, im)  — length == num_points
        Points that time out are stored as (freq_hz, None, None).

    The chip is left in power-down after the sweep.
    """
    num_points = min(num_points, 512)   # 511 increments → 512 points max

    _prog_sweep(start_freq, freq_step, num_points)

    _cmd(CMD_STANDBY)
    _wr(REG_CTRL_LO, 0x00)
    time.sleep_ms(20)

    _cmd(CMD_INIT_START_FREQ)
    time.sleep_ms(15)

    _cmd(CMD_START_SWEEP)             # chip now measures point 0

    results = []
    freq = start_freq

    for i in range(num_points):
        # Poll for data-ready on this point
        if not _poll(STATUS_DATA_READY, timeout_ms):
            results.append((freq, None, None))
        else:
            r  = _rd16s(REG_REAL_HI, REG_REAL_LO)
            im = _rd16s(REG_IMAG_HI, REG_IMAG_LO)
            results.append((freq, r, im))
        if _rd(REG_STATUS) & STATUS_SWEEP_DONE:
            for j in range(i + 1, num_points):
                freq += freq_step
                results.append((freq, None, None))
            break

        # Advance to next point (skip on last iteration)
        if i < num_points - 1:
            _cmd(CMD_INCREMENT_FREQ)
            # No extra sleep needed — poll above handles timing

        freq += freq_step

    _wr(REG_CTRL_HI, CMD_POWER_DOWN)
    return results

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
    _prog_single(freq)

    # _wr(REG_CTRL_HI, CMD_POWER_DOWN)
    # _wr(REG_CTRL_LO, 0x00)
    # time.sleep_ms(5)

    _cmd(CMD_STANDBY)
    _wr(REG_CTRL_LO, 0x00)
    time.sleep_ms(20)

    _cmd(CMD_INIT_START_FREQ)
    time.sleep_ms(15)

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
        result = _read_one_point(freq)
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

_SW_DUT_RCAL = Pin(28, Pin.OUT) # Low = Rcal, High = DUT

# these are the rfb and rcal values in kΩ
# r_known = [1, 4.9, 48, 51.9, 98.4, 145.4, 218, 315.4, 392, 426.4, 484, 531, 701, 812, 875]
r_known = [
    # 1e3, 
    # 10e3
    # 48e3
    100e3
    # 201e3,
    # 301e3,
    # 401e3,
    # 510e3,
    # 560e3,
    # 710e3,
    # 810e3,
    # 910e3
]

r_select_lines = [
    # (0, 0, 0, 0, 1),   # 1     kΩ
    # (1, 0, 0, 0, 1)   # 10    kΩ
    # (0, 0, 0, 0, 0)   # 48    kΩ
    (0, 1, 0, 0, 1)   # 100   kΩ
    # (0, 0, 1, 0, 0),   # 201   kΩ
    # (0, 0, 0, 1, 0),   # 301   kΩ
    # (0, 0, 1, 1, 0),   # 401   kΩ
    # (1, 1, 0, 0, 1),   # 510   kΩ
    # (1, 1, 0, 0, 0),   # 560   kΩ
    # (1, 1, 1, 0, 0),   # 710   kΩ
    # (1, 1, 0, 1, 0),   # 810   kΩ
    # (1, 1, 1, 1, 0)    # 910   kΩ
]





########################################################################################
########################################################################################
########################################################################################
########################################################################################
########################################################################################


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
    # print(f"  Interpolating GF/SP for {freq} Hz between indices {lo} and {hi} with t={t:.3f}")
    gf_lo, sp_lo = gain_factor_matrix[rcal_idx][lo]
    gf_hi, sp_hi = gain_factor_matrix[rcal_idx][hi]

    # Handle missing calibration data at either neighbour
    if gf_lo is None and gf_hi is None:
        return None, None
    if gf_lo is None:
        return gf_hi, sp_hi
    if gf_hi is None:
        return gf_lo, sp_lo

    # GF interpolation — unchanged, linear is correct
    gf = gf_lo + t * (gf_hi - gf_lo)

    # Phase interpolation — wrap-safe
    delta = sp_hi - sp_lo
    if delta > math.pi:
        delta -= 2 * math.pi
    elif delta < -math.pi:
        delta += 2 * math.pi
    sp = sp_lo + t * delta

    return gf, sp


def reading_bare(gain_factor_matrix, rcal, freq, freq_array):
    rcal_idx = r_known.index(rcal)
    gf, sp = _interp_gf_sp(gain_factor_matrix, rcal_idx, freq, freq_array)

    if gf is None:
        # On-the-fly recal
        _SW_DUT_RCAL.value(0)
        time.sleep_ms(2)
        switching_logic_rcal_rfb(rcal)
        gf, sp = gain_factor_cal(rcal, freq)
        if gf is None:
            return None

    # Always arrive here with correct gf/sp; now switch to DUT
    _SW_DUT_RCAL.value(1)
    time.sleep_ms(2)          # ← add this, was missing in normal path
    switching_logic_rcal_rfb(rcal)
    return measure_single_freq(freq, gf, sp)


########################################################################################
########################################################################################
########################################################################################
########################################################################################
########################################################################################
########################################################################################

def switching_logic_rcal_rfb(resistance_value):
    idx = r_known.index(resistance_value)
    asl1, asl0, bsl1, bsl0, shrt = r_select_lines[idx]

    _ASL1.value(asl1)  # GP2
    _ASL0.value(asl0)  # GP1
    _BSL1.value(bsl1)  # GP7
    _BSL0.value(bsl0)  # GP6
    _SHRT.value(shrt)  # GP0

    time.sleep_ms(5)  # MUX settling time

def calibration_table_maker( START_FREQ, STOP_FREQ, NO_READINGS):
    if NO_READINGS <= 1:
        freq_array = [START_FREQ]
    else:
        step = (STOP_FREQ - START_FREQ) / (NO_READINGS - 1)
        freq_array = [START_FREQ + i * step for i in range(NO_READINGS)]

    _SW_DUT_RCAL.value(0)
    time.sleep_ms(2)

    gain_factor_matrix = [
        [(None, None) for _ in range(len(freq_array))] for _ in range(len(r_known))
    ]

    for i, res in enumerate(r_known):
        switching_logic_rcal_rfb(res)
        line = [str(res)+" Ω"]
        print(f"calibrating for {res} Ω")
        print(f" freq(hz) | gain factor (1/Ω) | system phase (°)")
        for j, freq in enumerate(freq_array):
            line.append(str(freq))
            gain_factor_matrix[i][j] = gain_factor_cal(res, freq)
            print(f"{freq}   {gain_factor_matrix[i][j][0]:.3e}   {math.degrees(gain_factor_matrix[i][j][1]):.2f}°")
        print(", ".join(line))
        # want to save calib matric to the local pico

    return gain_factor_matrix, freq_array



def save_matrix_csv(filename, r_values, freq_array, matrix):
    with open(filename, "w") as f:
        # Header row
        header = "R/F," + ",".join(str(freq) for freq in freq_array)
        f.write(header + "\n")

        # Data rows
        for i, r in enumerate(r_values):
            row = [str(r)] + [str(matrix[i][j]) for j in range(len(freq_array))]
            f.write(",".join(row) + "\n")

    print(f"{filename} saved to Pico!")

# def calibration_table_maker(START_FREQ, STOP_FREQ, NO_READINGS):
#     if NO_READINGS <= 1:
#         freq_array = [START_FREQ]
#     else:
#         step = (STOP_FREQ - START_FREQ) / (NO_READINGS - 1)
#         freq_array = [START_FREQ + i * step for i in range(NO_READINGS)]

#     _SW_DUT_RCAL.value(0)
#     time.sleep_ms(2)

#     gain_matrix = []
#     phase_matrix = []

#     for i, res in enumerate(r_known):
#         switching_logic_rcal_rfb(res)
#         print(f"calibrating for {res} Ω")
#         print(f" freq(hz) | gain factor (1/Ω) | system phase (°)")

#         gain_row = []
#         phase_row = []

#         for j, freq in enumerate(freq_array):
#             gain, phase = gain_factor_cal(res, freq)

#             gain_row.append(gain)
#             phase_row.append(phase)

#             print(f"{freq}   {gain:.3e}   {math.degrees(phase):.2f}°")

#         gain_matrix.append(gain_row)
#         phase_matrix.append(phase_row)

#     # ✅ SAVE FILES
#     save_matrix_csv("gain.csv", r_known, freq_array, gain_matrix)
#     save_matrix_csv("phase.csv", r_known, freq_array, phase_matrix)

#     return gain_matrix, phase_matrix, freq_array




####### THIS IS FOR EXTERNAL CAILBRATION AND THEN CHECKING
# def calibration_table_maker( START_FREQ, STOP_FREQ, NO_READINGS):
#     if NO_READINGS <= 1:
#         freq_array = [START_FREQ]
#     else:
#         step = (STOP_FREQ - START_FREQ) / (NO_READINGS - 1)
#         freq_array = [START_FREQ + i * step for i in range(NO_READINGS)]

#     _SW_DUT_RCAL.value(1)
#     time.sleep_ms(2)

#     gain_factor_matrix = [
#         [(None, None) for _ in range(len(freq_array))] for _ in range(len(r_known))
#     ]

#     for i, res in enumerate(r_known):
#         switching_logic_rcal_rfb(res)
#         line = [str(res)+" Ω"]
#         for j, freq in enumerate(freq_array):
#             line.append(str(freq))
#             gain_factor_matrix[i][j] = gain_factor_cal(res, freq)
#         print(", ".join(line))

#     return gain_factor_matrix, freq_array


# def reading_bare(gain_factor_matrix, rcal, freq, freq_array):
#     # first switch to the dut using the gp28
#     _SW_DUT_RCAL.value(1)
#     time.sleep_ms(2)
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
    time.sleep_ms(2)
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


def sweep(gain_factor_matrix, START_FREQ, STOP_FREQ, NO_READINGS, mode, freq_array):
    temp = read_temp()
    if temp is not None:
        # print("Chip temperature : {:.1f} °C".format(temp))
        pass
    else:
        return []
    

    LED.value(1)
    time.sleep_ms(100)
    LED.value(0)
    
    results = []
    for freq in freq_array:
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


def sweep_hw(gain_factor_matrix, START_FREQ, STOP_FREQ, NO_READINGS,
             freq_array):
    """
    Hardware-sweep replacement for sweep().

    Uses the AD5933's internal frequency increment engine.
    Calibration (gain_factor_matrix) is still software-built — unchanged.

    Returns same format as sweep():
        list of (freq_hz, z_real, z_imag, rcal_used)
    """
    temp = read_temp()
    if temp is None:
        return []

    LED.value(1)
    time.sleep_ms(100)
    LED.value(0)

    if NO_READINGS <= 1:
        freq_step = 0.0
    else:
        freq_step = (STOP_FREQ - START_FREQ) / (NO_READINGS - 1)

    # ── Single Rcal pass (pick best Rcal for the sweep centre) ───────────
    # For a hardware sweep we pick one Rcal; reading_with_logic adaptive
    # logic doesn't apply here because we can't interrupt mid-sweep.
    # Use the middle frequency as a proxy to choose Rcal.
    mid_freq  = (START_FREQ + STOP_FREQ) / 2
    # Quick single-point probe with Rcal[0] to get a rough impedance
    _SW_DUT_RCAL.value(1)
    time.sleep_ms(2)
    probe_rcal = r_known[0]
    switching_logic_rcal_rfb(probe_rcal)
    probe_val = reading_bare(gain_factor_matrix, probe_rcal, mid_freq, freq_array)
    rcal_idx  = floor_cal(probe_val) if probe_val is not None else 0
    rcal      = r_known[rcal_idx]

    # ── Switch to selected Rcal/RFB, connect DUT ─────────────────────────
    _SW_DUT_RCAL.value(1)
    time.sleep_ms(2)
    switching_logic_rcal_rfb(rcal)

    # ── Look up (or interpolate) GF/SP for every point ───────────────────
    gf_sp = []
    for freq in freq_array:
        gf, sp = _interp_gf_sp(gain_factor_matrix, rcal_idx, freq, freq_array)
        if gf is None:                    # outside calibrated range — fallback
            _SW_DUT_RCAL.value(0)
            time.sleep_ms(2)
            switching_logic_rcal_rfb(rcal)
            gf, sp = gain_factor_cal(rcal, freq)
            _SW_DUT_RCAL.value(1)
            time.sleep_ms(2)
            switching_logic_rcal_rfb(rcal)
        gf_sp.append((gf, sp))

    # ── Fire hardware sweep ───────────────────────────────────────────────
    raw = _hw_sweep_raw(START_FREQ, freq_step, NO_READINGS)

    # ── Convert raw (R, Im) → calibrated impedance ───────────────────────
    results = []
    for i, (freq, r, im) in enumerate(raw):
        if r is None:
            results.append((freq, None, None, rcal))
            continue

        gf, sp = gf_sp[i]
        if gf is None:
            results.append((freq, None, None, rcal))
            continue

        mag = math.sqrt(r * r + im * im)
        if mag == 0:
            results.append((freq, None, None, rcal))
            continue

        z_mag   = 1.0 / (gf * mag)
        z_phase = math.atan2(im, r) - sp
        results.append((
            freq,
            z_mag * math.cos(z_phase),
            z_mag * math.sin(z_phase),
            rcal
        ))

    return results