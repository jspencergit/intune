import serial
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
from collections import deque
from matplotlib.collections import LineCollection
from matplotlib.widgets import Slider
import time

# ================== CONFIG ==================
SERIAL_PORT = "COM3"
BAUD_RATE = 115200
INITIAL_HISTORY_SEC = 6.0
POINTS_PER_SECOND = 60        # Increased for smoother scrolling
# ===========================================

ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.05)
print(f"✅ Connected! Initial history = {INITIAL_HISTORY_SEC} seconds")

current_max = int(INITIAL_HISTORY_SEC * POINTS_PER_SECOND)
pitches = deque(maxlen=current_max)
cents_data = deque(maxlen=current_max)

plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(15, 8), facecolor='#0a0a1f')
plt.subplots_adjust(bottom=0.18, left=0.12)

lc = LineCollection([], linewidth=4.2, alpha=0.95)
ax.add_collection(lc)
glow_lc = LineCollection([], linewidth=10, alpha=0.16)
ax.add_collection(glow_lc)

ax.set_ylim(0.8, 7.6)
ax.set_xlim(0, current_max)

title = ax.set_title(f"Intune — Viola Pitch Trace (Alto Clef)   |   History: {INITIAL_HISTORY_SEC:.1f} sec", 
                     fontsize=19, pad=25, color='#e0e0ff')
ax.set_xlabel("Time (recent → past)", fontsize=12, color='#aaaaaa')
ax.yaxis.set_visible(False)

# Staff and labels (same as before)
for y in [2.0, 2.8, 3.6, 4.4, 5.2]:
    ax.axhline(y=y, color='#eeeeee', lw=1.4, alpha=0.75)
for y in [1.2, 1.6, 2.4, 3.2, 4.0, 4.8, 5.6, 6.4, 7.2]:
    ax.axhline(y=y, color='#aaaaaa', lw=0.9, linestyle='--', alpha=0.4)

ax.text(-0.085, 0.48, "Alto Clef", fontsize=14, va='center', ha='center', 
        color='#a0c4ff', alpha=0.9, transform=ax.transAxes)

note_labels = [
    ("C3", 1.2), ("D3", 1.6), ("E3", 2.0), ("F3", 2.4), ("G3", 2.8),
    ("A3", 3.2), ("B3", 3.6), ("C4", 4.0), ("D4", 4.4), ("E4", 4.8),
    ("F4", 5.2), ("G4", 5.6), ("A4", 6.0), ("B4", 6.4), ("C5", 6.8)
]
for note, y in note_labels:
    ax.text(-0.085, (y-0.8)/6.8, note, fontsize=13, va='center', ha='right', 
            color='#dddddd', fontweight='medium', transform=ax.transAxes)

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
    if abs(cents) < 9:   return '#7dff9f'
    elif cents > 0:      return '#ff9d7d'
    else:                return '#9d9dff'

def update_history_length(seconds):
    global pitches, cents_data
    new_max = max(150, int(seconds * POINTS_PER_SECOND))
    
    old_p = list(pitches)
    old_c = list(cents_data)
    
    pitches = deque(old_p[-new_max:], maxlen=new_max)
    cents_data = deque(old_c[-new_max:], maxlen=new_max)
    
    ax.set_xlim(0, new_max)

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
        points = np.column_stack((x, y)).reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        
        colors = [get_color(c) for c in cents_data]
        
        lc.set_segments(segments)
        lc.set_color(colors)
        glow_lc.set_segments(segments)
        glow_lc.set_color(colors)

    return lc, glow_lc

ani = animation.FuncAnimation(fig, update, interval=20, blit=False, cache_frame_data=False)  # Faster update

# Slider
ax_slider = plt.axes([0.2, 0.05, 0.6, 0.03])
history_slider = Slider(ax_slider, 'History (seconds)', 1.0, 15.0, valinit=INITIAL_HISTORY_SEC, valstep=0.5)

def on_slider_change(val):
    update_history_length(val)
    title.set_text(f"Intune — Viola Pitch Trace (Alto Clef)   |   History: {val:.1f} sec")

history_slider.on_changed(on_slider_change)

plt.tight_layout()
plt.show()