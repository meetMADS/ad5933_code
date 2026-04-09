
# import math
# import machine
# from machine import Pin
# import time
# # import matplotlib as plt

# from ad5933_v2 import sweep
# from ad5933_v2 import calibration_table_maker


# start = 20_000
# stop = 40_000
# num = 5 
# def main():
#     gf_mat = calibration_table_maker(start,stop, num)

#     while True:
#         print(f"please change to DUT")
#         cin = input().strip().lower()

#         if cin == 'd':
#             results = sweep(gf_mat, start, stop, num, 2)
#             print("{:<12} {:<14} {:<14} {:<12} {:<12}".format("Freq (Hz)", "Z_real (Ω)", "Z_imag (Ω)", "|Z| (Ω)", "R_cal (Ω)"))
#             print("-" * 55)
#             for i in range(0, num):
#                 freq, zr, zi, rcal = results[i]
#                 if zr is None or zi is None:
#                     print("{:<12.1f}  [measurement failed]".format(freq))
#                     continue
#                 z_mag = (zr**2 + zi**2) ** 0.5
#                 print("{:<12.1f} {:<14.2f} {:<14.2f} {:<12.2f} {:<12.2f}".format(freq, zr, zi, z_mag, rcal))
#                 time.sleep_ms(5)
#             print("=" * 55)

#         elif cin == 'e':
#             print("THANK YOU FOR USING")
#             break
#         else:
#             print("Invalid input. Use 'h' or 'l'.")
#         time.sleep_ms(2)

# if __name__ == "__main__":
#     main()

import math
import machine
from machine import Pin
import time

from ad5933_v2 import sweep
from ad5933_v2 import calibration_table_maker

# Define sweep parameters
start = 20_000
stop = 40_000
num = 5 

# Hardcode your calibration resistor value here (in Ohms)
FIXED_RCAL = 98400  # Example: 98.4 kΩ

def main():
    print("Generating calibration array...")
    # Pass FIXED_RCAL to create a 1D array
    gf_array = calibration_table_maker(start, stop, num, FIXED_RCAL)

    while True:
        print(f"Please change to DUT and press 'd' to measure, or 'e' to exit:")
        cin = input().strip().lower()

        if cin == 'd':
            # Pass the 1D array and the FIXED_RCAL value
            results = sweep(gf_array, start, stop, num, FIXED_RCAL)
            
            print("{:<12} {:<14} {:<14} {:<12} {:<12}".format("Freq (Hz)", "Z_real (Ω)", "Z_imag (Ω)", "|Z| (Ω)", "R_cal (Ω)"))
            print("-" * 65)
            
            for i in range(len(results)):
                freq, zr, zi, rcal = results[i]
                if zr is None or zi is None:
                    print("{:<12.1f}  [measurement failed]".format(freq))
                    continue
                z_mag = (zr**2 + zi**2) ** 0.5
                print("{:<12.1f} {:<14.2f} {:<14.2f} {:<12.2f} {:<12.2f}".format(freq, zr, zi, z_mag, rcal))
                time.sleep_ms(5)
            print("=" * 65)

        elif cin == 'e':
            print("THANK YOU FOR USING")
            break
        else:
            print("Invalid input. Use 'd' or 'e'.")
        time.sleep_ms(2)

if __name__ == "__main__":
    main()