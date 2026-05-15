import serial
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
from collections import deque

# ================== CONFIG ==================
SERIAL_PORT = "COM3"
BAUD_RATE = 115200
MAX_POINTS = 700
BPM = 80
# ===========================================

ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.05)
print(f"✅ Connected to Teensy!  BPM = {BPM}")

pitches = deque(maxlen=MAX_POINTS)
cents_data = deque(maxlen=MAX_POINTS)

fig, ax = plt.subplots(figsize=(15, 8))

plot_line, = ax.plot([], [], lw=3, color='#1f77b4', alpha=0.9)
scatter = ax.scatter([], [], c=[], cmap='RdYlGn_r', s=50, vmin=-40, vmax=40, zorder=5)

ax.set_ylim(1.0, 8.0)                    # More room above for higher notes
ax.set_xlim(0, MAX_POINTS)

ax.set_title(f"Intune — Real-time Viola Pitch Trace (Alto Clef)  |  {BPM} BPM  |  4/4", fontsize=18, pad=20)
ax.set_xlabel("Time (Measures • Beats)")
ax.set_ylabel("")

# Hide y-axis numbers
ax.yaxis.set_visible(False)

# === CORRECT ALTO CLEF STAFF (Viola) ===
# Lines: F3, A3, C4, E4, G4
alto_clef_lines = [2.0, 2.8, 3.6, 4.4, 5.2]
for y in alto_clef_lines:
    ax.axhline(y=y, color='black', lw=1.4, alpha=0.75)   # Thin, elegant lines

# Alto Clef label
ax.text(-22, 3.6, "Alto Clef", fontsize=13, va='center', ha='center', 
        color='black', fontweight='bold', style='italic')

# Static note names (Viola range)
labels = [
    ("C3", 1.2), ("D3", 1.6), ("E3", 2.0), ("F3", 2.4), ("G3", 2.8),
    ("A3", 3.2), ("B3", 3.6), ("C4", 4.0), ("D4", 4.4), ("E4", 4.8),
    ("F4", 5.2), ("G4", 5.6), ("A4", 6.0), ("B4", 6.4), ("C5", 6.8),
    ("D5", 7.2), ("E5", 7.6)
]

for note, y in labels:
    ax.text(-11, y, note, fontsize=12, va='center', ha='right', 
            color='black', fontweight='medium')

ax.grid(True, alpha=0.15, axis='y')

# Vertical dashed lines for measures
for i in range(0, MAX_POINTS + 1, 120):
    ax.axvline(x=i, color='gray', linestyle='--', lw=1.2, alpha=0.5)

def pitch_to_y(note_str):
    try:
        note = note_str[0].upper()
        octave = int(note_str[-1])
        base = {'C':0, 'D':1, 'E':2, 'F':3, 'G':4, 'A':5, 'B':6}
        steps = base.get(note, 3) + (octave - 3) * 7
        return 1.2 + steps * 0.4
    except:
        return 4.0

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
        plot_line.set_data(x, pitches)
        scatter.set_offsets(np.column_stack((x, pitches)))
        
        colors = ['green' if abs(c) < 10 else 'red' if c > 0 else 'blue' for c in cents_data]
        scatter.set_color(colors)

    return plot_line, scatter

ani = animation.FuncAnimation(fig, update, interval=25, blit=False, cache_frame_data=False)

plt.tight_layout()
plt.show()