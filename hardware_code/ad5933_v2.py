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
OUTPUT_RANGE = 1  # 1=~2Vpp, 2=~1Vpp, 3=~0.4Vpp, 4=~0.2Vpp
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


def _prog_sweep(start_freq, freq_inc, num_inc):
    """
    Program AD5933 registers for a continuous frequency sweep.
    """
    sf = _freq_code(start_freq)
    fi = _freq_code(freq_inc)
    ni = min(num_inc, 511) # AD5933 hardware limit is 511 increments
    sc = min(SETTLING_CYCLES, 511)

    # Start frequency
    _wr(0x82, (sf >> 16) & 0xFF)
    _wr(0x83, (sf >> 8) & 0xFF)
    _wr(0x84, sf & 0xFF)

    # Frequency increment
    _wr(0x85, (fi >> 16) & 0xFF)
    _wr(0x86, (fi >> 8) & 0xFF)
    _wr(0x87, fi & 0xFF)

    # Number of increments
    _wr(0x88, (ni >> 8) & 0xFF)
    _wr(0x89, ni & 0xFF)

    # Settling cycles
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
def _execute_hardware_sweep(num_inc):
    """
    Executes the AD5933 hardware sweep state machine.
    Returns a list of (real, imag) tuples for each frequency point.
    """
    _wr(REG_CTRL_HI, CMD_POWER_DOWN)   # clean reset first
    _wr(REG_CTRL_LO, 0x00)
    time.sleep_ms(5)

    _cmd(CMD_STANDBY)                  # uses _cmd → preserves PGA/range
    _wr(REG_CTRL_LO, 0x00)
    time.sleep_ms(5)

    _cmd(CMD_INIT_START_FREQ)
    time.sleep_ms(100)

    _cmd(CMD_START_SWEEP)

    sweep_results = []
    
    n_points = num_inc + 1   # pass this in, or read from registers
    for i in range(n_points):
        if not _poll(STATUS_DATA_READY):
            sweep_results.append(None)
        else:
            r = _rd16s(REG_REAL_HI, REG_REAL_LO)
            im = _rd16s(REG_IMAG_HI, REG_IMAG_LO)
            sweep_results.append((r, im))
        if i < n_points - 1:
            _cmd(CMD_INCREMENT_FREQ)

    # Power down after sweep completes
    _wr(REG_CTRL_HI, CMD_POWER_DOWN)
    
    return sweep_results

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
#     # 1e3, 4.9e3,
#     # 48e3,
#     # 51.9e3,
#     98.4e3,
#     145.4e3,
#     218e3
#     # 315.4e3,
#     # 392e3,
# ]
# # , 426.4e3, 484e3, 531e3, 701e3, 812e3, 875e3]

# # (asl1, asl0, bsl1, bsl0) → (GP2, GP1, GP7, GP6)
# r_select_lines = [
#     # (0, 0, 0, 0, 1),   # 1     kΩ
#     # (0, 1, 0, 0, 1),   # 4.9   kΩ
#     # (0, 0, 0, 0, 0),  # 48    kΩ
#     # (0, 1, 0, 0, 0),  # 51.9  kΩ
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


# def calibration_table_maker( START_FREQ, STOP_FREQ, NO_READINGS):
#     # swicth the gp28 to rcal
#     # then we need to transverse the whole freq range & all the resistance values and then take the
#     # gain factor at those points

#     _ASL1.value(1)  # GP2
#     _ASL0.value(0)  # GP1
#     _BSL1.value(0)  # GP7
#     _BSL0.value(0)  # GP6
#     _SHRT.value(1)
#     if NO_READINGS <= 1:
#         freq_array = [START_FREQ]
#     else:
#         step = (STOP_FREQ - START_FREQ) / (NO_READINGS - 1)
#         freq_array = [START_FREQ + i * step for i in range(NO_READINGS)]
#     # this will result in a huge 2d matrix with x cooordinate as rcal values and
#     # the y coordinate as the freq values which user has suggested

#     _SW_DUT_RCAL.value(0)
#     time.sleep_ms(2)

#     # global gain_factor_matrix
#     gain_factor_matrix = [
#         [(None, None) for _ in range(len(freq_array))] for _ in range(len(r_known))
#     ]

#     for i, res in enumerate(r_known):
#         switching_logic_rcal_rfb(res)
#         for j, freq in enumerate(freq_array):
#             # print(f"{res}, {freq}")
#             gain_factor_matrix[i][j] = gain_factor_cal(res, freq)

#     return gain_factor_matrix


def reading_bare(gain_factor_matrix, rcal, freq, freq_array):
    # first switch to the dut using the gp28
    _SW_DUT_RCAL.value(1)
    # switch to the required rcal
    switching_logic_rcal_rfb(rcal)
    # see the code measure_save_pico_auto.py file to see how readings are made
    # based on the above code and gain factor matrix now make the single freq reading and return the value of

    # Look up indices
    freq_idx = freq_array.index(freq)
    rcal_idx = r_known.index(rcal)

    # Use the indices to get the matrix data
    gf, sp = gain_factor_matrix[rcal_idx][freq_idx]

    # Use the imported engine to do the actual read
    measured_val = measure_single_freq(freq, gf, sp)

    return measured_val




# # def main():
# def sweep(gain_factor_matrix, START_FREQ, STOP_FREQ, NO_READINGS, mode):

#     _ASL1.value(1)  # GP2
#     _ASL0.value(0)  # GP1
#     _BSL1.value(0)  # GP7
#     _BSL0.value(0)  # GP6
#     _SHRT.value(1)

#     temp = read_temp()
#     if temp is not None:
#         # print("Chip temperature : {:.1f} °C".format(temp))
#         pass
#     else:
#         return []
#         # print("[WARN] Temperature read failed — check I2C wiring")

#     # ── 2. Build frequency array ───────────────────────────────────────────
#     if NO_READINGS <= 1:
#         freq_array = [START_FREQ]
#     else:
#         step = (STOP_FREQ - START_FREQ) / (NO_READINGS - 1)
#         freq_array = [START_FREQ + i * step for i in range(NO_READINGS)]
    
    
#     print(f"startign to take the readings")
#     freq_inc = (STOP_FREQ - START_FREQ) / (NO_READINGS - 1)
#     _prog_sweep(START_FREQ, freq_inc, NO_READINGS - 1)
#     raw_data_array = _execute_hardware_sweep()
#     results = []
#     for freq in freq_array:
#         # val, rcal = reading_with_logic(gain_factor_matrix, freq, freq_array)
#         val, rcal = reading_with_logic(gain_factor_matrix, freq, freq_array)
#         if val is None:
#             # print("{:<12.1f}  [measurement failed]".format(freq))
#             results.append((freq, None, None, None))
#             continue
#         zr, zi = val[0], val[1]
#         # z_mag = (zr**2 + zi**2) ** 0.5
#         # print("{:<12.1f} {:<14.2f} {:<14.2f} {:<12.2f} {:<12.2f}".format(freq, zr, zi, z_mag, rcal))
#         results.append((freq, zr, zi, rcal))
#         # time.sleep_ms(5)
#     # print("=" * 55)
#     # print("Sweep complete. {} / {} points succeeded.".format(sum(1 for _, zr, _ in results if zr is not None), len(results)))
#     return results















def calibration_table_maker(START_FREQ, STOP_FREQ, NO_READINGS, fixed_rcal):
    """
    Measures and stores the gain factor and system phase for a fixed calibration
    resistor across the specified frequency sweep points.
    """
    _ASL1.value(1)  # GP2
    _ASL0.value(0)  # GP1
    _BSL1.value(0)  # GP7
    _BSL0.value(0)  # GP6
    _SHRT.value(1)
    
    # Switch to RCAL (0 for calibration)
    _SW_DUT_RCAL.value(0)
    time.sleep_ms(10)

    if NO_READINGS <= 1:
        freq_array = [START_FREQ]
    else:
        step = (STOP_FREQ - START_FREQ) / (NO_READINGS - 1)
        freq_array = [START_FREQ + i * step for i in range(NO_READINGS)]

    # 1D Array to store (gain_factor, system_phase) for each frequency
    gain_factor_array = []

    for freq in freq_array:
        # gain_factor_cal handles the temporal averaging automatically
        gf, sp = gain_factor_cal(fixed_rcal, freq)
        gain_factor_array.append((gf, sp))

    return gain_factor_array


def sweep(gain_factor_array, START_FREQ, STOP_FREQ, NO_READINGS, fixed_rcal):
    """
    Executes a continuous hardware sweep and post-processes the raw DFT data
    using the pre-calculated 1D gain factor array.
    """
    _ASL1.value(1)  # GP2
    _ASL0.value(0)  # GP1
    _BSL1.value(0)  # GP7
    _BSL0.value(0)  # GP6
    _SHRT.value(1)

    # Switch to DUT (1 for measurement)
    _SW_DUT_RCAL.value(1)
    time.sleep_ms(10)

    if NO_READINGS <= 1:
        freq_array = [START_FREQ]
        freq_inc = 0
    else:
        step = (STOP_FREQ - START_FREQ) / (NO_READINGS - 1)
        freq_array = [START_FREQ + i * step for i in range(NO_READINGS)]
        freq_inc = step

    # 1. Program the sweep parameters
    _prog_sweep(START_FREQ, freq_inc, NO_READINGS - 1)
    
    # 2. Execute the state machine and retrieve raw (R, I) tuples
    raw_data_array = _execute_hardware_sweep(NO_READINGS)
    
    results = []
    
    # Ensure we only iterate up to the available data points in case of early termination
    valid_points = min(len(freq_array), len(raw_data_array), len(gain_factor_array))

    # 3. Reconstruct impedance using the raw data and calibration array
    for i in range(valid_points):
        freq = freq_array[i]
        r_raw, im_raw = raw_data_array[i]
        gf, sp = gain_factor_array[i]

        if gf is None or r_raw is None:
            results.append((freq, None, None, fixed_rcal))
            continue

        mag_raw = math.sqrt(r_raw**2 + im_raw**2)
        if mag_raw == 0:
            results.append((freq, None, None, fixed_rcal))
            continue

        # Apply calibration math
        z_mag = 1.0 / (gf * mag_raw)
        z_phase_rad = math.atan2(im_raw, r_raw) - sp

        # Convert back to Cartesian impedance coordinates
        z_real = z_mag * math.cos(z_phase_rad)
        z_imag = z_mag * math.sin(z_phase_rad)

        results.append((freq, z_real, z_imag, fixed_rcal))

    return results