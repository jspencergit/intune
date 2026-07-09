#!/usr/bin/env python3
import time
import numpy as np
import serial
import sounddevice as sd
import librosa

AUDIO = r"C:\Code\gitRepos\intune\test_audio\synthetic_C_major_scale_updown_viola_perfect.mp3"
y, sr = librosa.load(AUDIO, sr=44100, mono=True)
y = (y[: int(3 * sr)] * 1.0).astype(np.float32)

candidates = [5, 6, 7, 14, 15, 16, 26, 33, 34]
ser = serial.Serial("COM3", 230400, timeout=0.05)
time.sleep(0.2)


def max_level(duration=2.5):
    ser.reset_input_buffer()
    t_end = time.time() + duration
    mx = 0.0
    notes = set()
    buf = ""
    while time.time() < t_end:
        raw = ser.read(1024)
        if not raw:
            continue
        buf += raw.decode("utf-8", "ignore")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            parts = line.strip().split(",")
            if len(parts) < 5:
                continue
            try:
                mx = max(mx, float(parts[4]))
                notes.add(parts[1])
            except ValueError:
                pass
    return mx, notes


print("silence max", max_level(1.0))

for dev in candidates:
    try:
        info = sd.query_devices(dev)
        if info["max_output_channels"] < 1:
            continue
        print(f"\n=== device {dev}: {info['name']} ===")
        sd.play(y, sr, device=dev)
        mx, notes = max_level(3.2)
        sd.stop()
        print("max level", mx, "notes sample", list(notes)[:10])
        if mx > 0.001:
            print("HIT — use this device")
            break
    except Exception as e:
        print("dev", dev, "err", e)

ser.close()
