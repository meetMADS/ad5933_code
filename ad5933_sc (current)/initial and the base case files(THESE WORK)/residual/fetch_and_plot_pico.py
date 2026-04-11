"""
AD5933 — Pair A, Code 2: Fetch result.csv from Pico and plot 4 charts.
=======================================================================
Run this on your LAPTOP after measure_save_pico.py has finished on the Pico.

Requirements (install once):
  pip install mpremote matplotlib

Usage:
  python fetch_and_plot_pico.py
"""

import subprocess, sys, csv
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

PICO_FILE  = "result.csv"          # filename on Pico flash
LOCAL_FILE = "result_fetched.csv"  # where to save it on laptop

# ── FETCH FROM PICO ───────────────────────────────────────────────────────────
print("  Fetching \'{}\' from Pico via mpremote...".format(PICO_FILE))
ret = subprocess.run(
    ["python3", "-m", "mpremote", "cp", ":{}".format(PICO_FILE), LOCAL_FILE],
    capture_output=True, text=True
)

if ret.returncode != 0:
    print("  [ERROR] mpremote failed:")
    print(ret.stderr)
    print("  Make sure the Pico is connected and mpremote is installed:")
    print("    pip install mpremote")
    sys.exit(1)

print("  Saved locally to \'{}\'.".format(LOCAL_FILE))

# ── READ CSV ──────────────────────────────────────────────────────────────────
freq    = []
z_mag   = []
z_phase = []
z_real  = []
z_imag  = []

with open(LOCAL_FILE, "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        freq.append(float(row["freq_hz"]))
        z_mag.append(float(row["z_mag_ohm"]))
        z_phase.append(float(row["z_phase_deg"]))
        z_real.append(float(row["z_real_ohm"]))
        z_imag.append(float(row["z_imag_ohm"]))

if not freq:
    print("  [ERROR] CSV is empty. Check that the Pico sweep completed.")
    sys.exit(1)

print("  Loaded {} data points. Plotting...".format(len(freq)))

# ── 4-PANEL PLOT ──────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(14, 10))
fig.suptitle("AD5933 Impedance Sweep", fontsize=14, fontweight="bold")
gs = gridspec.GridSpec(3, 2, hspace=0.42, wspace=0.35)

# Panel 1: |Z| vs Frequency
ax1 = fig.add_subplot(gs[0, 0])
ax1.plot(freq, z_mag, "b-o", ms=3)
ax1.set_title("|Z| vs Frequency")
ax1.set_xlabel("Frequency (Hz)")
ax1.set_ylabel("|Z| (\u03a9)")
ax1.grid(True, alpha=0.3)

# Panel 2: Phase vs Frequency
ax2 = fig.add_subplot(gs[0, 1])
ax2.plot(freq, z_phase, "r-o", ms=3)
ax2.set_title("Phase vs Frequency")
ax2.set_xlabel("Frequency (Hz)")
ax2.set_ylabel("Phase (\u00b0)")
ax2.grid(True, alpha=0.3)

# Panel 3: Z_real vs Frequency
ax3 = fig.add_subplot(gs[1, 0])
ax3.plot(freq, z_real, "g-o", ms=3)
ax3.set_title("Z_real vs Frequency")
ax3.set_xlabel("Frequency (Hz)")
ax3.set_ylabel("Z_real (\u03a9)")
ax3.grid(True, alpha=0.3)

# Panel 4: Z_imag vs Frequency
ax4 = fig.add_subplot(gs[1, 1])
ax4.plot(freq, z_imag, "g-o", ms=3)
ax4.set_title("Z_imag vs Frequency")
ax4.set_xlabel("Frequency (Hz)")
ax4.set_ylabel("Z_imag (\u03a9)")
ax4.grid(True, alpha=0.3)

# Panel 5: Nyquist plot — Z_real vs Z_imag (Y-axis inverted per convention)
ax5 = fig.add_subplot(gs[2, 0])
ax5.plot(z_real, z_imag, "m-o", ms=3)
ax5.set_title("Nyquist Plot")
ax5.set_xlabel("Z_real (\u03a9)")
ax5.set_ylabel("\u2212Z_imag (\u03a9)")
ax5.invert_yaxis()   # convention: −Im(Z) on Y-axis so capacitive arcs curve upward
ax5.grid(True, alpha=0.3)

PLOT_FILE = "impedance_plot.png"
plt.savefig(PLOT_FILE, dpi=150, bbox_inches="tight")
print("  Plot saved to \'{}\'.".format(PLOT_FILE))
plt.show()
