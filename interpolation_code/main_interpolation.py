
import math
import machine
from machine import Pin
import time
# import matplotlib as plt

from ic_code import sweep
from ic_code import calibration_table_maker
from ic_code import reading_bare
from ic_code import r_known


# r_select_lines = [
#     (0, 0, 0, 0),   # 48    kΩ
#     (1, 0, 0, 0),   # 145.4 kΩ
#     (0, 0, 0, 1),   # 218   kΩ
#     (1, 0, 0, 1),   # 315.4 kΩ
#     (0, 0, 1, 1)   # 392   kΩ


#     # (1, 0, 1, 0),   # 426.4 kΩ
#     # (1, 0, 1, 1),   # 484   kΩ
#     # (1, 1, 0, 0),   # 531   kΩ
#     # (1, 1, 0, 1),   # 701   kΩ
#     # (1, 1, 1, 0),   # 812   kΩ
#     # (1, 1, 1, 1)   # 875    kΩ
# ]

start = 30_000
stop = 30_500
num =  5
def main():
    gf_mat = calibration_table_maker(start,stop, num)

    if num <= 1:
        freq_array = [start]
    else:
        step = (stop - start) / (num - 1)
        freq_array = [start + i * step for i in range(num)]

    while True:
        print(f"please change to DUT")
        cin = input().strip().lower()

        if cin == 'd':
            results = sweep(gf_mat, start, stop, num, 2)
            print("{:<12} {:<14} {:<14} {:<12} {:<12}".format("Freq (Hz)", "Z_real (kΩ)", "Z_imag (kΩ)", "|Z| (kΩ)", "R_cal (kΩ)"))
            print("-" * 55)
            for i in range(0, num):
                freq, zr, zi, rcal = results[i]
                if zr is None or zi is None:
                    print("{:<12.1f}  [measurement failed]".format(freq))
                    continue
                z_mag = (zr**2 + zi**2) ** 0.5
                print("{:<12.1f} {:<14.2f} {:<14.2f} {:<12.2f} {:<12.2f}".format(freq, zr/1000, zi/1000, z_mag/1000, rcal/1000))
                time.sleep_ms(5)
            print("=" * 55)

        elif cin=='m':
            freq_new = 30_313
            print("{:<12} {:<14} {:<14} {:<12}".format("Freq (Hz)", "Z_real (kΩ)", "Z_imag (kΩ)", "|Z| (kΩ)"))
            print("-" * 50)
            for i in range(50):
                rcal = r_known[0]
                [real, imag] = reading_bare(gf_mat, rcal, freq_new, freq_array)
                z_mag = (real**2 + imag**2) ** 0.5
                print("{:<12.1f} {:<14.2f} {:<14.2f} {:<12.2f}".format(freq_new, real, imag, z_mag))
            print(f"{"=" * 20} END {"=" * 20}")

        elif cin == 'e':
            print("THANK YOU FOR USING")
            break
        else:
            print("Invalid input. Use 'h' or 'l'.")
        time.sleep_ms(2)

if __name__ == "__main__":
    main()