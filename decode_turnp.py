import serial
import time

ser = serial.Serial("/dev/ttyACM0", 115200, timeout=0.1)

print("Waiting 3 seconds...")
time.sleep(3)
ser.reset_input_buffer()

last = {}

print("Ready.")

while True:
    data = ser.read(64)
    if not data:
        continue

    i = 0
    while i < len(data) - 5:
        if data[i] == 0xFF and data[i+1] == 0xFE and data[i+2] == 0x03:
            channel = data[i+3]
            value = (data[i+4] << 8) | data[i+5]

            old = last.get(channel)
            if old is not None and value != old:
                direction = "UP" if value > old else "DOWN"
                percent = round((value / 1023) * 100)
                print(f"channel={channel} {direction} value={value} percent={percent}%")

            last[channel] = value
            i += 6
        else:
            i += 1