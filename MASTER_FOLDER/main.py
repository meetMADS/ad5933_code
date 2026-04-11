# SPDX-License-Identifier: GPL-3.0-or-later
# Main controller
# Copyright (C) 2026 Arnav Bhate

import os
import ic_code
import display

# Constants
limits = (1e3, 1e5)
max_size = 1000000

# State
start = limits[0]
stop = limits[1]
number = 100


# @rp2.asm_pio()
# def debounce_button():
#     wait(0, pin, 0)
#     set(x, 31)
#     label("debounce")
#     nop()[31]
#     jmp(x_dec, "debounce")
#     jmp(pin, "restart")
#     irq(0)
#     wait(1, pin, 0)
#     label("restart")
#     wrap()


def get_dir_size(path):
    total = 0
    for entry in os.listdir(path):
        full_path = path + "/" + entry
        try:
            stat = os.stat(full_path)
            total += stat[6]
        except OSError:
            total += get_dir_size(full_path)
    return total


def exists(path: str) -> bool:
    try:
        os.stat(path)
        return True
    except:
        return False


def main() -> None:
    global limits, start, stop, number
    freq_array = None
    gf_mat = None

    i = 0

    try:
        os.stat("Sweep")
    except:
        os.mkdir("Sweep")

    while True:
        command = input().lower().split()
        if command[0] == "limits":
            print(limits[0], limits[1], sep=",")
        elif command[0] == "start":
            try:
                start = float(command[1])
                if start < limits[0]:
                    start = limits[0]
                if start > stop:
                    start = stop
            except:
                pass
            print(start)
        elif command[0] == "stop":
            try:
                stop = float(command[1])
                if stop > limits[1]:
                    stop = limits[1]
                if stop < start:
                    stop = start
            except:
                pass
            print(stop)
        elif command[0] == "number":
            try:
                n = int(command[1])
                number = n if n > 1 else number
            except:
                pass
            print(number)
        elif command[0] == "sweep":
            if get_dir_size("Sweep") > max_size:
                print("0")
            if (
                not freq_array
                or not gf_mat
                or not (
                    freq_array[0] == start
                    and freq_array[-1] == stop
                    and len(freq_array) == number
                )
            ):
                gf_mat, freq_array = ic_code.calibration_table_maker(
                    start, stop, number
                )
            readings = ic_code.sweep(gf_mat, freq_array)
            files = os.listdir("Sweep")
            while i < 10000:
                name = f"{i:04}.csv"
                if name not in files:
                    with open("Sweep/" + name, "w") as f:
                        for reading in readings:
                            f.write(
                                f"{reading[0]},{reading[1]},{reading[2]}\n"
                            )
                    print(name)
                    break
                i += 1
            else:
                i = 0
        elif command[0] == "size":
            print(get_dir_size("Sweep") / max_size)
        elif command[0] == "list":
            files = os.listdir("Sweep")
            names = []
            for name in files:
                if name.endswith(".csv"):
                    names.append(name)
            print(len(names))
            for name in names:
                print(name)
        elif command[0] == "get":
            try:
                if not command[1].endswith(".csv"):
                    raise Exception
                f = open("Sweep/" + command[1], "r")
                lines = f.readlines()
                print(len(lines))
                for line in lines:
                    print(line[:-1])
                f.close()
            except:
                print(0)
        elif command[0] == "delete":
            try:
                if not command[1].endswith(".csv"):
                    raise Exception
                os.remove("Sweep/" + command[1])
                print(1)
            except:
                print(0)
        elif command[0] == "rename":
            try:
                if (not command[1].endswith(".csv")) or (
                    not exists("Sweep/" + command[1])
                ):
                    raise Exception
                if (not command[2].endswith(".csv")) or exists("Sweep/" + command[2]):
                    raise Exception
                os.rename("Sweep/" + command[1], "Sweep/" + command[2])
                print(1)
            except:
                print(0)


if __name__ == "__main__":
    while True:
        try:
            main()
        except:
            pass
