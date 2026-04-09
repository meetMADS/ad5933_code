import machine
LED = machine.Pin("LED", machine.Pin.OUT)
import time
temp = 1

time.sleep_ms(100)
while True:
    LED.toggle()
    time.sleep_ms(500)