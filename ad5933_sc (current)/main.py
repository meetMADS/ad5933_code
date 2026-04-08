
import math
import machine
from machine import Pin
import time
# import matplotlib as plt

from ic_code import sweep
from ic_code import calibration_table_maker


start = 20_000
stop = 40_000
num =  11
def main():
    gf_mat, cal_freq_array = calibration_table_maker(start,stop, num)

    while True:
        print(f"please change to DUT")
        cin = input().strip().lower()

        if cin == 'd':
            results = sweep(gf_mat, start, stop, num, 2, cal_freq_array)
            print("{:<12} {:<14} {:<14} {:<12} {:<12}".format("Freq (Hz)", "Z_real (Ω)", "Z_imag (Ω)", "|Z| (Ω)", "R_cal (Ω)"))
            print("-" * 55)
            for i in range(0, num):
                freq, zr, zi, rcal = results[i]
                if zr is None or zi is None:
                    print("{:<12.1f}  [measurement failed]".format(freq))
                    continue
                z_mag = (zr**2 + zi**2) ** 0.5
                phase = math.atan2(zi, zr) * (180 / math.pi)
                print("{:<12.1f} {:<14.2f} {:<14.2f} {:<12.2f} {:<12.2f} {:<12.2f}".format(freq, zr, zi, z_mag, rcal, phase))
                time.sleep_ms(5)
            print("=" * 55)

        elif cin == 'e':
            print("THANK YOU FOR USING")
            break
        else:
            print("Invalid input. Use 'h' or 'l'.")
        time.sleep_ms(2)

if __name__ == "__main__":
    main()