import machine
import time

# I2C setup (same as your code)
# scl = machine.Pin(3)
# sda = machine.Pin(2)
# scl = machine.Pin(5, machine.Pin.IN, machine.Pin.PULL_UP)
# sda = machine.Pin(4, machine.Pin.IN, machine.Pin.PULL_UP)
# i2c = machine.I2C(1, sda=sda, scl=scl, freq=400000)
i2c = machine.I2C(0, sda=machine.Pin(4), scl=machine.Pin(5), freq=400000)

AD5933_ADDR = 0x0D   # default I2C address

print("Scanning I2C...")
print(i2c.scan())

# ---------- FUNCTION TO READ TEMPERATURE ----------

def read_temp():

    # 1. send "measure temperature" command
    # control register: 0x80,0x81
    i2c.writeto_mem(AD5933_ADDR, 0x80, bytes([0x90]))
    i2c.writeto_mem(AD5933_ADDR, 0x81, bytes([0x00]))

    # wait for conversion (~800us)
    time.sleep_ms(1)

    # 2. read temperature registers
    msb = i2c.readfrom_mem(AD5933_ADDR, 0x92, 1)[0]
    lsb = i2c.readfrom_mem(AD5933_ADDR, 0x93, 1)[0]

    raw = (msb << 8) | lsb

    # temperature calculation
    if raw & 0x2000:  # negative temperature
        temp = (raw - 16384) / 32
    else:
        temp = raw / 32

    return temp


# ---------- MAIN LOOP ----------

while True:
    t = read_temp()
    print("AD5933 Temperature:", t, "C")
    time.sleep(0.2)