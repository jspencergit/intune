import serial
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
from collections import deque
from matplotlib.collections import LineCollection

# ================== CONFIG ==================
SERIAL_PORT = "COM3"
BAUD_RATE = 115200
MAX_POINTS = 700
BPM = 80
# ===========================================

ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.05)
print(f"✅ Connected! BPM = {BPM}")

pitches = deque(maxlen=MAX_POINTS)
cents_data = deque(maxlen=MAX_POINTS)

plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(15, 8), facecolor='#0a0a1f')

# We'll use LineCollection for multicolored trace
lc = LineCollection([], linewidth=4.2, alpha=0.95)
ax.add_collection(lc)

glow_lc = LineCollection([], linewidth=10, alpha=0.16)
ax.add_collection(glow_lc)

ax.set_ylim(0.7, 7.5)
ax.set_xlim(0, MAX_POINTS)

ax.set_title(f"Intune — Viola Pitch Trace (Alto Clef)   |   {BPM} BPM   |   4/4", 
             fontsize=19, pad=25, color='#e0e0ff')
ax.set_xlabel("Time (Measures • Beats)", fontsize=12, color='#aaaaaa')

# Elegant staff
for y in [2.0, 2.8, 3.6, 4.4, 5.2]:
    ax.axhline(y=y, color='#ffffff', lw=1.1, alpha=0.65)

ax.text(-23, 4.0, "𝄞", fontsize=82, va='center', ha='center', color='#a0c4ff', alpha=0.85)

# Note labels
labels = [
    ("C3", 1.2), ("D3", 1.6), ("E3", 2.0), ("F3", 2.4), ("G3", 2.8),
    ("A3", 3.2), ("B3", 3.6), ("C4", 4.0), ("D4", 4.4), ("E4", 4.8),
    ("F4", 5.2), ("G4", 5.6), ("A4", 6.0), ("B4", 6.4), ("C5", 6.8)
]

for note, y in labels:
    ax.text(-11, y, note, fontsize=13, va='center', ha='right', 
            color='#dddddd', fontweight='medium')

ax.grid(True, alpha=0.08, linestyle='--', color='#334455')

def pitch_to_y(note_str):
    try:
        note = note_str[0].upper()
        octave = int(note_str[-1])
        base = {'C':0, 'D':1, 'E':2, 'F':3, 'G':4, 'A':5, 'B':6}
        steps = base.get(note, 3) + (octave - 3) * 7
        return 1.2 + steps * 0.4
    except:
        return 4.0

def get_color(cents):
    if abs(cents) < 9:
        return '#7dff9f'      # In tune - beautiful green
    elif cents > 0:
        return '#ff9d7d'      # Sharp - warm orange
    else:
        return '#9d9dff'      # Flat - cool blue

def update(frame):
    try:
        raw = ser.readline().decode('utf-8', errors='ignore').strip()
        if raw and ',' in raw:
            parts = raw.split(',')
            if len(parts) >= 3:
                note = parts[1]
                cent = float(parts[2])
                y_pos = pitch_to_y(note)
                
                pitches.append(y_pos)
                cents_data.append(cent)
    except:
        pass

    if len(pitches) > 3:
        x = np.arange(len(pitches))
        y = np.array(pitches)
        
        # Create segments for multicolored line
        points = np.column_stack((x, y)).reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        
        colors = [get_color(c) for c in cents_data]
        
        lc.set_segments(segments)
        lc.set_color(colors)
        
        glow_lc.set_segments(segments)
        glow_lc.set_color(colors)

    return lc, glow_lc

ani = animation.FuncAnimation(fig, update, interval=25, blit=False, cache_frame_data=False)

plt.tight_layout()
plt.show()