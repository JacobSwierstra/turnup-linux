import serial

ser = serial.Serial("/dev/ttyACM0", 115200, timeout=0.1)

print("Listening...")
print("Turn knobs and press buttons")

while True:
    data = ser.read(64)
    if data:
        print(data)
