"""
AD5933 Impedance Measurement - MicroPython Driver
Target: Raspberry Pi Pico (or any MicroPython board)
I2C: SDA=Pin(2), SCL=Pin(3) [change as needed]

CALIBRATION:
- Connect R_CAL between VOUT (Pin6) and VIN (Pin5).
- RFB is already wired between RFB (Pin4) and VIN (Pin5) permanently.
- Set R_CAL and R_FB values below.
- Code does calibration sweep, computes gain factor, then waits 5 seconds
  for you to swap in the unknown impedance, then runs the measurement sweep.
"""

import machine
import time
import math

# ─────────────────────────────────────────────
# I2C SETUP – change pins / bus if needed
# ─────────────────────────────────────────────
scl = machine.Pin(3)
sda = machine.Pin(2)
i2c = machine.I2C(1, sda=sda, scl=scl, freq=400000)

AD5933_ADDR = 0x0D

# ═════════════════════════════════════════════
# >>> USER CONFIGURATION <<< EDIT THESE
# ═════════════════════════════════════════════

MCLK_HZ          = 16.776e6   # internal oscillator (~16.776 MHz)
START_FREQ_HZ    = 1_000       # sweep start frequency (Hz)
FREQ_INC_HZ      = 1_000       # frequency step size (Hz)
NUM_INCREMENTS   = 99          # number of frequency points (max 511)
SETTLING_CYCLES  = 15          # ADC settling cycles per point

# --- RESISTOR VALUES (ENTER YOUR ACTUAL VALUES HERE) ---
R_CAL_OHMS = 21_000   # <-- Known calibration resistor between VOUT and VIN (Ohms)
R_FB_OHMS  = 20_500   # <-- Feedback resistor between RFB (Pin4) and VIN (Pin5) (Ohms)

# --- OUTPUT EXCITATION ---
OUTPUT_RANGE = 1        # 1=~2Vpp, 2=~1Vpp, 3=~0.4Vpp, 4=~0.2Vpp
PGA_GAIN_x1  = True     # True = PGA x1, False = PGA x5

# ═════════════════════════════════════════════

# ─────────────────────────────────────────────
# REGISTER ADDRESSES
# ─────────────────────────────────────────────
REG_CTRL_HI  = 0x80
REG_CTRL_LO  = 0x81
REG_FREQ_HI  = 0x82
REG_FREQ_MID = 0x83
REG_FREQ_LO  = 0x84
REG_INC_HI   = 0x85
REG_INC_MID  = 0x86
REG_INC_LO   = 0x87
REG_NINC_HI  = 0x88
REG_NINC_LO  = 0x89
REG_SETTLE_HI = 0x8A
REG_SETTLE_LO = 0x8B
REG_STATUS   = 0x8F
REG_TEMP_HI  = 0x92
REG_TEMP_LO  = 0x93
REG_REAL_HI  = 0x94
REG_REAL_LO  = 0x95
REG_IMAG_HI  = 0x96
REG_IMAG_LO  = 0x97

# Control register command codes (D15-D12)
CMD_INIT_START_FREQ = 0x10
CMD_START_SWEEP     = 0x20
CMD_INCREMENT_FREQ  = 0x30
CMD_REPEAT_FREQ     = 0x40
CMD_MEASURE_TEMP    = 0x90
CMD_POWER_DOWN      = 0xA0
CMD_STANDBY         = 0xB0

# Status register bits
STATUS_TEMP_READY = 0x01
STATUS_DATA_READY = 0x02
STATUS_SWEEP_DONE = 0x04

# ─────────────────────────────────────────────
# LOW-LEVEL HELPERS
# ─────────────────────────────────────────────
def _write_reg(reg, value):
    i2c.writeto_mem(AD5933_ADDR, reg, bytes([value & 0xFF]))

def _read_reg(reg):
    return i2c.readfrom_mem(AD5933_ADDR, reg, 1)[0]

def _read_reg16_signed(reg_hi, reg_lo):
    hi  = _read_reg(reg_hi)
    lo  = _read_reg(reg_lo)
    raw = (hi << 8) | lo
    if raw & 0x8000:
        raw -= 65536
    return raw

# FIX 1: Added missing ×4 factor per datasheet formula:
#         Code = (f_out / (MCLK/4)) × 2^27  =  (f_out × 4 / MCLK) × 2^27
def _freq_to_code(freq_hz):
    code = int((freq_hz * 4 / MCLK_HZ) * (2 ** 27))
    return code & 0xFFFFFF

def _build_ctrl_lo_bits():
    """
    Returns the lower bits of ctrl_hi byte (range + PGA).
    D10-D9 = output range bits, D8 = PGA gain.
    In the byte at 0x80: bit2=D10, bit1=D9, bit0=D8.
    """
    range_map = {1: 0b00, 2: 0b11, 3: 0b10, 4: 0b01}
    rb  = range_map.get(OUTPUT_RANGE, 0b00)
    pga = 1 if PGA_GAIN_x1 else 0
    return ((rb >> 1) & 1) << 2 | ((rb & 1) << 1) | pga

def _send_command(cmd_byte):
    """Write a control command; merges range+PGA bits. Never uses block write."""
    _write_reg(REG_CTRL_HI, cmd_byte | _build_ctrl_lo_bits())

def _poll_status(bit_mask, timeout_ms=3000):
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while True:
        if _read_reg(REG_STATUS) & bit_mask:
            return True
        if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            print("  [WARN] Status poll timeout! mask=0x{:02X}".format(bit_mask))
            return False
        time.sleep_ms(1)

# ─────────────────────────────────────────────
# SWEEP REGISTER PROGRAMMING
# ─────────────────────────────────────────────
def _program_sweep_registers():
    sf = _freq_to_code(START_FREQ_HZ)
    fi = _freq_to_code(FREQ_INC_HZ)
    n  = min(NUM_INCREMENTS, 511)
    sc = min(SETTLING_CYCLES, 511)

    _write_reg(REG_FREQ_HI,  (sf >> 16) & 0xFF)
    _write_reg(REG_FREQ_MID, (sf >>  8) & 0xFF)
    _write_reg(REG_FREQ_LO,   sf        & 0xFF)

    _write_reg(REG_INC_HI,  (fi >> 16) & 0xFF)
    _write_reg(REG_INC_MID, (fi >>  8) & 0xFF)
    _write_reg(REG_INC_LO,   fi        & 0xFF)

    _write_reg(REG_NINC_HI, (n >> 8) & 0x01)
    _write_reg(REG_NINC_LO,  n       & 0xFF)

    _write_reg(REG_SETTLE_HI, (sc >> 8) & 0x01)  # multiplier x1 (D10-D9 = 00)
    _write_reg(REG_SETTLE_LO,  sc       & 0xFF)

# ─────────────────────────────────────────────
# CORE SWEEP ENGINE
# ─────────────────────────────────────────────
def _acquire_sweep():
    """
    Execute the full frequency sweep sequence:
    Power-down → Standby → Init → Start sweep → poll/read each point → Power-down
    Returns list of (freq_hz, real, imag).
    """
    results = []

    # Step 1: Power down
    _write_reg(REG_CTRL_HI, CMD_POWER_DOWN)
    _write_reg(REG_CTRL_LO, 0x00)
    time.sleep_ms(5)

    # Step 2: Standby (disconnects VOUT/VIN from GND bias)
    _send_command(CMD_STANDBY)
    _write_reg(REG_CTRL_LO, 0x00)
    time.sleep_ms(5)

    # Step 3: Initialize with start frequency (DDS runs, no measurement yet)
    _send_command(CMD_INIT_START_FREQ)
    time.sleep_ms(100)  # wait for circuit to reach steady state

    # Step 4: Start frequency sweep (ADC fires after settling cycles)
    _send_command(CMD_START_SWEEP)

    current_freq = START_FREQ_HZ

    for point in range(NUM_INCREMENTS + 1):

        # Wait for D1 (data ready) in status register 0x8F
        if not _poll_status(STATUS_DATA_READY, timeout_ms=3000):
            print("  Timeout at point {} ({} Hz)".format(point, current_freq))
            break

        # Read 16-bit signed real and imaginary from registers 0x94-0x97
        real = _read_reg16_signed(REG_REAL_HI, REG_REAL_LO)
        imag = _read_reg16_signed(REG_IMAG_HI, REG_IMAG_LO)
        results.append((current_freq, real, imag))

        # Check D2 (sweep complete) in status register
        if _read_reg(REG_STATUS) & STATUS_SWEEP_DONE:
            print("  Sweep complete at point {} / {} ({} Hz).".format(
                point + 1, NUM_INCREMENTS + 1, current_freq))
            break

        # Increment to next frequency point
        _send_command(CMD_INCREMENT_FREQ)
        current_freq += FREQ_INC_HZ

    # Power down after sweep
    _write_reg(REG_CTRL_HI, CMD_POWER_DOWN)
    return results

# ─────────────────────────────────────────────
# TEMPERATURE READING
# ─────────────────────────────────────────────
def read_temperature():
    _write_reg(REG_CTRL_HI, CMD_MEASURE_TEMP)
    _write_reg(REG_CTRL_LO, 0x00)
    time.sleep_ms(1)
    if not _poll_status(STATUS_TEMP_READY, timeout_ms=50):
        return None
    msb = _read_reg(REG_TEMP_HI)
    lsb = _read_reg(REG_TEMP_LO)
    raw = (msb << 8) | lsb
    if raw & 0x2000:
        temp = (raw - 16384) / 32.0
    else:
        temp = raw / 32.0
    return temp

# ─────────────────────────────────────────────
# GAIN FACTOR CALCULATION (Datasheet Eq.)
#
# Magnitude_cal = sqrt(R_cal^2 + I_cal^2)
# GainFactor    = 1 / (Z_CAL * Magnitude_cal)
# SystemPhase   = atan2(I_cal, R_cal)
# ─────────────────────────────────────────────
def run_calibration():
    """
    Phase 1: Calibration sweep with R_CAL between VOUT and VIN.
    Computes per-frequency gain factor and system phase arrays.
    Returns (gain_factors[], system_phases[], cal_raw[]).
    """
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║           PHASE 1: CALIBRATION               ║")
    print("╠══════════════════════════════════════════════╣")
    print("║  R_CAL = {:>10.1f} Ohm                  ║".format(R_CAL_OHMS))
    print("║  R_FB  = {:>10.1f} Ohm                  ║".format(R_FB_OHMS))
    print("║  Range = {} | PGA = {}                      ║".format(
        OUTPUT_RANGE, "x1" if PGA_GAIN_x1 else "x5"))
    print("╚══════════════════════════════════════════════╝")
    print()
    print("  Make sure R_CAL ({} Ohm) is connected between".format(R_CAL_OHMS))
    print("  VOUT (Pin 6) and VIN (Pin 5).")
    print("  RFB ({} Ohm) must be between RFB (Pin 4) and VIN (Pin 5).".format(R_FB_OHMS))
    print("  Starting calibration sweep...")

    _program_sweep_registers()
    cal_raw = _acquire_sweep()

    if not cal_raw:
        print("  [ERROR] Calibration sweep returned no data!")
        return None, None, None

    gain_factors   = []
    system_phases  = []

    print()
    print("  {:>8s} | {:>8s} | {:>8s} | {:>12s} | {:>14s}".format(
        "Freq(Hz)", "Real", "Imag", "Magnitude", "GainFactor"))
    print("  " + "-"*65)

    for (freq, r, i_) in cal_raw:
        mag = math.sqrt(r * r + i_ * i_)
        if mag == 0:
            gain_factors.append(None)
            system_phases.append(0.0)
            continue

        # Gain Factor = Admittance / DFT_Magnitude = 1 / (Z_CAL * Magnitude)
        gf = 1.0 / (R_CAL_OHMS * mag)

        # System phase at this frequency point
        sp = math.atan2(i_, r)

        gain_factors.append(gf)
        system_phases.append(sp)

        print("  {:>8d} | {:>8d} | {:>8d} | {:>12.3f} | {:>14.6e}".format(
            freq, r, i_, mag, gf))

    avg_gf = sum(g for g in gain_factors if g is not None) / len(gain_factors)
    print()
    print("  Average Gain Factor across sweep: {:.6e}".format(avg_gf))
    print("  Calibration DONE.")
    return gain_factors, system_phases, cal_raw

# ─────────────────────────────────────────────
# IMPEDANCE SWEEP (Datasheet Eq.)
#
# Magnitude = sqrt(R^2 + I^2)
# |Z|       = 1 / (GainFactor * Magnitude)
# phi_Z     = atan2(I, R) - SystemPhase
# ─────────────────────────────────────────────
def run_measurement(gain_factors, system_phases):
    """
    Phase 2: Measurement sweep with unknown impedance between VOUT and VIN.
    Uses per-frequency gain_factors and system_phases from calibration.
    Returns list of (freq_hz, |Z|, phase_deg, Z_real, Z_imag).
    """
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║       PHASE 2: IMPEDANCE MEASUREMENT         ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("  Swap R_CAL for UNKNOWN IMPEDANCE between VOUT (Pin 6) and VIN (Pin 5).")
    print("  Waiting 5 seconds for you to make the change...")
    print()

    for countdown in range(5, 0, -1):
        print("  {} ...".format(countdown))
        time.sleep(1)

    print()
    print("  Starting measurement sweep...")
    _program_sweep_registers()
    meas_raw = _acquire_sweep()

    if not meas_raw:
        print("  [ERROR] Measurement sweep returned no data!")
        return []

    output = []
    print()
    print("  {:>8s} | {:>12s} | {:>10s} | {:>12s} | {:>12s}".format(
        "Freq(Hz)", "|Z| (Ohm)", "Phase(deg)", "Z_real(Ohm)", "Z_imag(Ohm)"))
    print("  " + "-"*72)

    for idx, (freq, r, i_) in enumerate(meas_raw):
        mag = math.sqrt(r * r + i_ * i_)
        if mag == 0:
            print("  {:>8d} | (zero DFT magnitude, skipping)".format(freq))
            continue

        # Use per-frequency gain factor (fall back to index-0 if mismatch)
        gf = gain_factors[idx] if idx < len(gain_factors) and gain_factors[idx] else gain_factors[0]
        sp = system_phases[idx] if idx < len(system_phases) else system_phases[0]

        # Impedance magnitude
        z_mag = 1.0 / (gf * mag)

        # FIX 2: atan2 already returns the correct angle for all four quadrants (−π, π].
        #         The previous manual quadrant correction was wrong for Q2/Q3 and
        #         produced incorrect phase values for reactive loads (capacitors/inductors).
        #         Simply subtract the system phase calibrated during the calibration sweep.
        z_phase_rad = math.atan2(i_, r) - sp
        z_phase_deg = math.degrees(z_phase_rad)

        # Rectangular components
        z_real = z_mag * math.cos(z_phase_rad)
        z_imag = z_mag * math.sin(z_phase_rad)

        output.append((freq, z_mag, z_phase_deg, z_real, z_imag))

        print("  {:>8d} | {:>12.2f} | {:>10.3f} | {:>12.2f} | {:>12.2f}".format(
            freq, z_mag, z_phase_deg, z_real, z_imag))

    print()
    print("  Measurement DONE. {} points collected.".format(len(output)))
    return output

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
print()
print("  AD5933 Impedance Analyser - MicroPython")
print("  I2C scan:", i2c.scan())
print()

temp = read_temperature()
if temp is not None:
    print("  On-chip temperature: {:.2f} C".format(temp))

# ── PHASE 1: Calibration with R_CAL ──
gain_factors, system_phases, _ = run_calibration()

if gain_factors is None:
    print("Aborting due to calibration failure.")
else:
    # ── PHASE 2: Measurement with unknown Z (5s swap window) ──
    results = run_measurement(gain_factors, system_phases)
    print()
    print("  All done. Results stored in `results` list.")
    print("  Access as: freq, z_mag, z_phase_deg, z_real, z_imag = results[i]")
