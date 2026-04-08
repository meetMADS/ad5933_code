import math
from ic_code import calibration_table_maker, sweep

start = 20000
stop = 80000
num = 80

def main():
    print("Calibrating...")
    gf_mat, freqs = calibration_table_maker(start, stop, num)

    while True:
        cmd = input("d = measure, e = exit: ")

        if cmd == 'd':
            results = sweep(gf_mat, freqs)

            print("Freq     Zreal     Zimag     |Z|      Phase")

            for f, zr, zi, rcal in results:
                mag = math.sqrt(zr*zr + zi*zi)
                ph = math.degrees(math.atan2(zi, zr))

                print(f"{f:7.1f} {zr:9.2f} {zi:9.2f} {mag:9.2f} {ph:7.2f}")

        elif cmd == 'e':
            break

if __name__ == "__main__":
    main()