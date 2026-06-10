import serial
import subprocess
import time

ser = serial.Serial("/dev/ttyACM0", 115200, timeout=0.1)

time.sleep(3)
ser.reset_input_buffer()

last_percent = None

print("Channel 0 controls master volume.")

while True:
    data = ser.read(64)
    if not data:
        continue

    i = 0
    while i < len(data) - 5:
        if data[i] == 0xFF and data[i+1] == 0xFE and data[i+2] == 0x03:
            channel = data[i+3]
            value = (data[i+4] << 8) | data[i+5]
            percent = round((value / 1023) * 100)

            if channel == 0 and percent != last_percent:
                print(f"Master volume: {percent}%")
                subprocess.run([
                    "wpctl", "set-volume",
                    "@DEFAULT_AUDIO_SINK@",
                    f"{percent}%"
                ])
                last_percent = percent

            i += 6
        else:
            i += 1