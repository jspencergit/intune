#!/usr/bin/env python3
"""
Intune - Real-time Viola Pitch Visualizer (pyqtgraph version)
===========================================================

Switched to PyQt5 + pyqtgraph for significantly smoother real-time scrolling,
inspired by efficient serial plotters like https://github.com/iskandarputra/Real-Time-Py-Serial-Plotter .

Key techniques borrowed/adapted for smoothness:
- pyqtgraph PlotWidget + PlotDataItem with fast setData (much lighter than Matplotlib FuncAnimation + LineCollection rebuilds).
- Event/timer driven updates (only when data arrives or regular poll).
- Circular-buffer style history (deque with maxlen).
- Direct curve updates instead of per-frame full artist reconstruction.
- Qt native widgets and event loop.

The musical features (alto clef staff, cents deviation view, BPM-timed "visible beats" window,
color-coded intonation, rests, confidence alpha, crosshair inspection, rich export, simulator)
are preserved as much as possible.

Run:
  python visualizer.py --simulate
  python visualizer.py --port COM3

Install deps:
  pip install -r requirements.txt
  (PyQt5, pyqtgraph, pyserial, numpy)
"""

import argparse
import logging
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Deque, List, Tuple

import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QGridLayout, QFileDialog
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont, QColor

import pyqtgraph as pg

# Optional: keep matplotlib only for the debug export dialog if tkinter is missing, but we use Qt now.
try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

# =============================================================================
# CONFIGURATION & CONSTANTS (preserved from original for compatibility)
# =============================================================================

DEFAULT_PORT = "COM3" if sys.platform.startswith("win") else "/dev/ttyACM0"
DEFAULT_BAUD = 115200
DEFAULT_HISTORY_SEC = 6.0
POINTS_PER_SECOND = 60
MIN_HISTORY_POINTS = 150

# First position viola notes only (C3 open C string up to E5 on A string in first position)
# Trimmed to avoid clutter from higher positions.
STAFF_Y_MAIN = [2.8, 3.6, 4.4, 5.2, 6.0]  # Core around G3-A4
STAFF_Y_LEDGER = [
    1.2, 1.6,           # C3, D3 low
    2.4, 3.2,
    4.0, 4.8, 5.6, 6.4, 7.2, 8.0,
]

NOTE_LABELS = [
    ("C3", 1.2), ("D3", 1.6), ("E3", 2.0), ("F3", 2.4), ("G3", 2.8),
    ("A3", 3.2), ("B3", 3.6),
    ("C4", 4.0), ("D4", 4.4), ("E4", 4.8), ("F4", 5.2), ("G4", 5.6),
    ("A4", 6.0), ("B4", 6.4),
    ("C5", 6.8), ("D5", 7.2), ("E5", 7.6),
]

# Color scheme - sheet music style (white background, black staff lines like printed music)
COLOR_BG = "w"                  # white paper
COLOR_STAFF = "#000000"         # solid black staff lines
COLOR_LEDGER = "#444444"        # dark gray for ledgers
COLOR_LABEL = "#000000"         # black note names
COLOR_ALTO = "#000000"          # black "ALTO CLEF" text

# Intonation trace colors - vivid but not neon, so they read well over black staff lines
# and give clear feedback (green=in-tune, red=sharp, blue=flat)
COLOR_IN_TUNE = "#2E8B57"       # sea green
COLOR_SHARP = "#DC143C"         # crimson
COLOR_FLAT = "#4169E1"          # royal blue

# Interaction / secondary elements (still high contrast on white)
COLOR_TEXT = "#000000"
COLOR_TEXT_DIM = "#333333"
COLOR_CROSSHAIR = "#8B0000"     # dark red for crosshairs (easy to see)
COLOR_HOVER = "#006400"         # dark green for hover readout

IN_TUNE_THRESHOLD_CENTS = 5
GOOD_THRESHOLD_CENTS = 15

UPDATE_INTERVAL_MS = 25  # ~40 fps poll / update target (pyqtgraph is fast)

# =============================================================================
# DATA MODELS (mostly unchanged)
# =============================================================================

@dataclass
class Config:
    port: str = DEFAULT_PORT
    baud: int = DEFAULT_BAUD
    history_sec: float = DEFAULT_HISTORY_SEC
    simulate: bool = False
    debug: bool = False
    list_ports: bool = False

@dataclass
class PitchSample:
    """A single pitch measurement."""
    timestamp: float
    note: str
    cents: float
    y_pos: float
    confidence: Optional[float] = None
    level: Optional[float] = None
    teensy_ts: Optional[float] = None

# (Stats class removed - statistics panel no longer shown)

# =============================================================================
# NOTE MAPPING & COLORS (unchanged)
# =============================================================================

def pitch_to_y(note_str: str) -> float:
    if not note_str:
        return 4.0
    if note_str.strip() == "---":
        return 0.8
    try:
        note = note_str[0].upper()
        octave_str = ''.join(c for c in note_str[1:] if c.isdigit())
        if not octave_str:
            octave_str = "3"
        octave = int(octave_str)
        base = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
        steps = base.get(note, 3) + (octave - 3) * 7
        return 1.2 + steps * 0.4
    except Exception:
        return 4.0

def get_color(cents: float) -> str:
    abs_cents = abs(cents)
    if abs_cents < IN_TUNE_THRESHOLD_CENTS:
        return COLOR_IN_TUNE
    elif cents > 0:
        return COLOR_SHARP
    else:
        return COLOR_FLAT

# =============================================================================
# SERIAL READER & SIMULATOR (reused with minimal changes)
# =============================================================================

class SerialReader:
    """Threaded serial reader with automatic reconnection (same as before)."""

    def __init__(self, port: str, baud: int, out_queue: queue.Queue, stop_event: threading.Event):
        self.port = port
        self.baud = baud
        self.out_queue = out_queue
        self.stop_event = stop_event
        self.ser: Optional["serial.Serial"] = None
        self.running = False
        self.last_success = 0.0

    def _connect(self) -> bool:
        if serial is None:
            return False
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            logging.info(f"Connected to {self.port} @ {self.baud} baud")
            return True
        except Exception as e:
            logging.warning(f"Failed to open {self.port}: {e}")
            return False

    def _disconnect(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def run(self):
        self.running = True
        reconnect_delay = 1.0

        while not self.stop_event.is_set():
            if self.ser is None:
                if not self._connect():
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 1.5, 5.0)
                    continue
                reconnect_delay = 1.0
                self.last_success = time.time()

            try:
                raw = self.ser.readline()
                if not raw:
                    if time.time() - self.last_success > 2.0:
                        self._disconnect()
                    continue

                line = raw.decode("utf-8", errors="ignore").strip()
                if not line or "," not in line:
                    continue

                parts = [p.strip() for p in line.split(",") if p.strip()]

                note = None
                cents = None

                if len(parts) >= 3:
                    try:
                        candidate_note = parts[1]
                        candidate_cents = float(parts[2])
                        if candidate_note and (candidate_note.strip() == "---" or
                                               (len(candidate_note) >= 2 and candidate_note[0].upper() in "ABCDEFG")):
                            note = candidate_note
                            cents = candidate_cents
                    except (ValueError, IndexError):
                        pass

                if note is None and len(parts) >= 2:
                    try:
                        candidate_cents = float(parts[-1])
                        candidate_note = parts[-2]
                        if candidate_note and (candidate_note.strip() == "---" or
                                               (len(candidate_note) >= 2 and candidate_note[0].upper() in "ABCDEFG")):
                            note = candidate_note
                            cents = candidate_cents
                    except (ValueError, IndexError):
                        pass

                if note is not None and cents is not None:
                    teensy_ts = None
                    try:
                        teensy_ts = float(parts[0])
                    except (ValueError, IndexError):
                        pass

                    confidence = None
                    if len(parts) >= 4:
                        try:
                            c4 = float(parts[3])
                            confidence = c4 / 100.0 if c4 > 1.0 else c4
                            confidence = max(0.0, min(1.0, confidence))
                        except (ValueError, IndexError):
                            pass

                    level = None
                    if len(parts) >= 5:
                        try:
                            level = float(parts[4])
                            level = max(0.0, min(1.0, level))
                        except (ValueError, IndexError):
                            pass

                    is_silence = (note and note.strip() == "---")
                    if is_silence or confidence is None or confidence > 0.02 or (level is not None and level > 0.001):
                        sample = PitchSample(
                            timestamp=time.time(),
                            note=note,
                            cents=cents,
                            y_pos=pitch_to_y(note),
                            confidence=confidence,
                            level=level,
                            teensy_ts=teensy_ts,
                        )
                        try:
                            self.out_queue.put_nowait(sample)
                            self.last_success = time.time()
                        except queue.Full:
                            pass
            except Exception as e:
                logging.debug(f"Serial read error: {e}")
                self._disconnect()
                time.sleep(0.5)

        self._disconnect()
        self.running = False

class Simulator:
    """Generates realistic drifting pitch data (reused)."""

    def __init__(self, out_queue: queue.Queue, stop_event: threading.Event, base_note: str = "G3"):
        self.out_queue = out_queue
        self.stop_event = stop_event
        self.base_note = base_note
        self.base_y = pitch_to_y(base_note)
        self.phase = 0.0
        self.drift = 0.0
        self.current_cents = 0.0
        self.running = False

    def run(self):
        self.running = True
        interval = 1.0 / POINTS_PER_SECOND

        while not self.stop_event.is_set():
            self.phase += 0.035
            self.drift += np.random.normal(0, 0.08)
            self.drift = np.clip(self.drift, -35, 35)

            effort = 6.0 * np.sin(self.phase * 0.6) + 3.0 * np.sin(self.phase * 1.7)
            jitter = np.random.normal(0, 1.8)

            cents = self.drift + effort + jitter
            if np.random.random() < 0.012:
                cents = np.random.choice([-18, -12, 0, 0, 0, 7, 14, 22])

            self.current_cents = float(np.clip(cents, -45, 45))

            sample = PitchSample(
                timestamp=time.time(),
                note=self.base_note,
                cents=self.current_cents,
                y_pos=self.base_y + (self.current_cents * 0.012),
                confidence=None,
                teensy_ts=time.time() * 1000,
            )
            try:
                self.out_queue.put_nowait(sample)
            except queue.Full:
                pass

            time.sleep(max(0.001, interval - 0.001))

        self.running = False

# =============================================================================
# MAIN PYQTGRAPH VISUALIZER WINDOW
# =============================================================================

class IntuneVisualizer(QMainWindow):
    """PyQtGraph-based real-time visualizer (smooth scrolling via efficient setData)."""

    def __init__(self, config: Config):
        super().__init__()
        self.config = config

        # Data
        self.history: Deque[PitchSample] = deque(maxlen=2500)
        self.paused = False
        self.latest_teensy_ts = 0.0
        self.last_data_time = 0.0

        # Musical time (for x-axis in beats)
        self.bpm = 80.0
        self.beats_visible = 4.0

        # Threading / data source
        self.data_queue: queue.Queue = queue.Queue(maxsize=500)
        self.stop_event = threading.Event()
        self.reader_thread: Optional[threading.Thread] = None
        self.reader: Optional[SerialReader | Simulator] = None

        # For smooth creep even between packets (display time advances independently)
        self.display_now = 0.0
        self.last_poll_wall = time.time()

        # Defensive init for items that _update_plots touches early
        self.staff_segment_items: List[pg.PlotDataItem] = []
        self.cents_segment_items: List[pg.PlotDataItem] = []
        self.staff_note_labels: List[Tuple[pg.TextItem, float]] = []
        self.alto_clef_item = None

        self._setup_logging()
        self._setup_ui()
        self._start_reader()

        # Regular poll + update (cheap in pyqtgraph)
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_and_update)
        self.poll_timer.start(UPDATE_INTERVAL_MS)

    def _setup_logging(self):
        level = logging.DEBUG if self.config.debug else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )

    def _setup_ui(self):
        self.setWindowTitle("Intune — Viola Intonation Visualizer (pyqtgraph)")
        self.resize(1400, 900)

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # --- Top bar: big current reading (stats removed per user request) ---
        top_bar = QHBoxLayout()
        self.current_label = QLabel("—")
        self.current_label.setFont(QFont("Consolas", 42, QFont.Bold))
        self.current_label.setAlignment(Qt.AlignCenter)
        self.current_label.setMinimumHeight(80)
        self.current_label.setStyleSheet("color: #aaaaaa;")

        top_bar.addWidget(self.current_label)
        main_layout.addLayout(top_bar)

        # --- Staff plot (Alto Clef) ---
        self.staff_plot = pg.PlotWidget()
        self.staff_plot.setBackground(COLOR_BG)  # white sheet music background
        self.staff_plot.setYRange(0.8, 8.2, padding=0)  # Trimmed to first position (C3-E5)
        self.staff_plot.setMouseEnabled(x=True, y=False)
        self.staff_plot.setClipToView(True)
        self.staff_plot.showGrid(x=False, y=False)
        self.staff_plot.setLabel("bottom", "Beats (newest → right)")

        # Hide numeric y-axis ticks completely (we draw our own note names on the chart area)
        self.staff_plot.hideAxis('left')

        # Staff and ledger lines (horizontal) - black like printed sheet music
        for y in STAFF_Y_MAIN:
            line = pg.InfiniteLine(pos=y, angle=0, pen=pg.mkPen(COLOR_STAFF, width=1.5))
            self.staff_plot.addItem(line)
        for y in STAFF_Y_LEDGER:
            line = pg.InfiniteLine(pos=y, angle=0, pen=pg.mkPen(COLOR_LEDGER, width=0.8, style=Qt.DashLine))
            self.staff_plot.addItem(line)

        # Note labels placed directly on the chart area (like the original Matplotlib version).
        # These will be repositioned dynamically in _update_plots so they stay just inside
        # the left edge of the current "visible beats" window.
        self.staff_note_labels: List[Tuple[pg.TextItem, float]] = []
        for note, y in NOTE_LABELS[::2]:  # thin them out a bit
            txt = pg.TextItem(note, color=COLOR_LABEL, anchor=(1.0, 0.5))
            txt.setFont(QFont("Consolas", 9))
            self.staff_plot.addItem(txt)
            self.staff_note_labels.append((txt, y))

        # ALTO CLEF label (positioned on the chart area, like the original)
        if self.alto_clef_item is None:
            self.alto_clef_item = pg.TextItem("ALTO\nCLEF", color=COLOR_ALTO, anchor=(0.5, 0.5))
            self.alto_clef_item.setFont(QFont("Consolas", 8))
            self.staff_plot.addItem(self.alto_clef_item)

        self.staff_segment_items: List[pg.PlotDataItem] = []
        main_layout.addWidget(self.staff_plot, stretch=3)

        # --- Cents deviation plot ---
        self.cents_plot = pg.PlotWidget()
        self.cents_plot.setBackground(COLOR_BG)  # white sheet music background
        self.cents_plot.setYRange(-25, 25, padding=0)
        self.cents_plot.setMouseEnabled(x=True, y=False)
        self.cents_plot.setClipToView(True)
        self.cents_plot.showGrid(x=False, y=True)
        self.cents_plot.setLabel("left", "Cents Deviation")
        self.cents_plot.setLabel("bottom", "Beats")

        # Reference lines + in-tune band hint (sheet music style)
        self.cents_plot.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(COLOR_STAFF, width=1.2)))  # black
        self.cents_plot.addItem(pg.InfiniteLine(pos=+IN_TUNE_THRESHOLD_CENTS, angle=0,
                                                pen=pg.mkPen(COLOR_IN_TUNE, width=0.8, style=Qt.DashLine)))
        self.cents_plot.addItem(pg.InfiniteLine(pos=-IN_TUNE_THRESHOLD_CENTS, angle=0,
                                                pen=pg.mkPen(COLOR_IN_TUNE, width=0.8, style=Qt.DashLine)))

        self.cents_segment_items: List[pg.PlotDataItem] = []
        main_layout.addWidget(self.cents_plot, stretch=2)

        # Link X axes so they scroll together
        self.cents_plot.setXLink(self.staff_plot)

        # Make axis lines black to match sheet music look (ticks/labels default to dark on white bg)
        self.staff_plot.getAxis('bottom').setPen(pg.mkPen(COLOR_STAFF, width=0.6))
        self.cents_plot.getAxis('bottom').setPen(pg.mkPen(COLOR_STAFF, width=0.6))
        self.cents_plot.getAxis('left').setPen(pg.mkPen(COLOR_STAFF, width=0.6))

        # Set initial X ranges so labels are positioned correctly from the start
        # (must happen after both plots are created)
        self.staff_plot.setXRange(-self.beats_visible, 0.3)
        self.cents_plot.setXRange(-self.beats_visible, 0.3)

        # Initial positioning of note labels and ALTO label (before the update timer kicks in)
        if hasattr(self, 'staff_note_labels') and self.staff_note_labels:
            left = -self.beats_visible
            label_x = left + 0.12
            for txt, y in self.staff_note_labels:
                txt.setPos(label_x, y)
        if getattr(self, 'alto_clef_item', None) is not None:
            left = -self.beats_visible
            self.alto_clef_item.setPos(left + 0.45, 5.0)

        # --- Controls ---
        ctrl_layout = QHBoxLayout()

        ctrl_layout.addWidget(QLabel("BPM"))
        self.bpm_slider = QSlider(Qt.Horizontal)
        self.bpm_slider.setRange(40, 200)
        self.bpm_slider.setValue(int(self.bpm))
        self.bpm_slider.setTickInterval(20)
        self.bpm_slider.setTickPosition(QSlider.TicksBelow)
        self.bpm_slider.valueChanged.connect(self._on_bpm_change)
        ctrl_layout.addWidget(self.bpm_slider, 2)

        ctrl_layout.addWidget(QLabel("Visible beats"))
        self.beats_slider = QSlider(Qt.Horizontal)
        self.beats_slider.setRange(10, 160)  # 1.0 - 16.0
        self.beats_slider.setValue(int(self.beats_visible * 10))
        self.beats_slider.setTickInterval(10)
        self.beats_slider.setTickPosition(QSlider.TicksBelow)
        self.beats_slider.valueChanged.connect(self._on_beats_change)
        ctrl_layout.addWidget(self.beats_slider, 3)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self._toggle_pause)
        ctrl_layout.addWidget(self.pause_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_history)
        ctrl_layout.addWidget(clear_btn)

        export_btn = QPushButton("Export Log")
        export_btn.clicked.connect(self._export_debug_log)
        ctrl_layout.addWidget(export_btn)

        main_layout.addLayout(ctrl_layout)

        self.setCentralWidget(central)

        # Crosshair support (simple version for now)
        self.crosshair_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(COLOR_CROSSHAIR, width=0.9, style=Qt.DashLine))
        self.crosshair_h = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(COLOR_CROSSHAIR, width=0.9, style=Qt.DashLine))
        self.hover_label = pg.TextItem("", color=COLOR_HOVER, anchor=(0, 1))
        self.staff_plot.addItem(self.crosshair_v, ignoreBounds=True)
        self.staff_plot.addItem(self.crosshair_h, ignoreBounds=True)
        self.staff_plot.addItem(self.hover_label)
        self.crosshair_v.setVisible(False)
        self.crosshair_h.setVisible(False)
        self.hover_label.setVisible(False)

        # Connect mouse for inspection when paused
        self.staff_plot.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # Keyboard shortcuts (basic)
        self.setFocusPolicy(Qt.StrongFocus)

    def _on_bpm_change(self, val: int):
        self.bpm = float(val)
        self._update_plots()  # refresh range immediately

    def _on_beats_change(self, val: int):
        self.beats_visible = val / 10.0
        self._update_plots()

    def _start_reader(self):
        if self.config.simulate:
            self.reader = Simulator(self.data_queue, self.stop_event)
            name = "Simulator"
        else:
            if serial is None:
                logging.error("pyserial not available")
                return
            self.reader = SerialReader(
                self.config.port, self.config.baud, self.data_queue, self.stop_event
            )
            name = f"SerialReader({self.config.port})"

        self.reader_thread = threading.Thread(target=self.reader.run, name=name, daemon=True)
        self.reader_thread.start()
        logging.info(f"Started {name}")

    def _poll_and_update(self):
        if self.paused:
            return

        # Advance display time for smooth creep of existing points
        now_wall = time.time()
        dt = now_wall - self.last_poll_wall
        self.last_poll_wall = now_wall
        self.display_now += dt * 1000.0

        ingested = 0
        while True:
            try:
                sample = self.data_queue.get_nowait()
            except queue.Empty:
                break

            self.history.append(sample)
            if sample.teensy_ts:
                self.latest_teensy_ts = max(self.latest_teensy_ts, sample.teensy_ts)
            ingested += 1

        if ingested:
            self.last_data_time = time.time()

        # Always update plots (cheap) so the trace creeps smoothly via display_now
        self._update_plots()
        self._update_current_display()

    def _update_plots(self):
        # Clear any previous colored segments
        for item in self.staff_segment_items:
            try:
                self.staff_plot.removeItem(item)
            except Exception:
                pass
        self.staff_segment_items.clear()

        for item in self.cents_segment_items:
            try:
                self.cents_plot.removeItem(item)
            except Exception:
                pass
        self.cents_segment_items.clear()

        # Always keep note labels positioned on the left of the current view
        if hasattr(self, 'staff_note_labels') and self.staff_note_labels:
            left = -self.beats_visible
            label_x = left + 0.12  # small inset so labels are inside the plot area
            for txt, y in self.staff_note_labels:
                txt.setPos(label_x, y)

        if getattr(self, 'alto_clef_item', None) is not None:
            left = -self.beats_visible
            self.alto_clef_item.setPos(left + 0.45, 5.0)  # roughly middle of staff

        if len(self.history) < 2:
            return

        visible_sec = self.beats_visible / (self.bpm / 60.0) if self.bpm > 0 else 4.0

        # Use display_now (smoothly advancing) as the reference "now"
        now_ts = self.display_now
        if self.latest_teensy_ts > now_ts:
            # gently catch up to device if it is ahead
            now_ts = self.latest_teensy_ts

        # Build list of visible points with color/alpha info (restores original per-point coloring)
        points: List[dict] = []
        last_sound_y = None
        last_sound_cents = None
        for s in self.history:
            if s.teensy_ts is None:
                continue
            age = (now_ts - s.teensy_ts) / 1000.0
            if age < 0 or age > visible_sec + 0.5:
                continue
            beat_age = age * (self.bpm / 60.0)
            x = -beat_age

            if s.note and s.note.strip() == "---":
                color = "#8888aa"
                alpha = 0.35
                # Hold last played pitch during rest for continuous trace (avoids big vertical jumps)
                # Gray color + lower alpha makes it clear this is a rest/silence period.
                y_staff = last_sound_y if last_sound_y is not None else s.y_pos
                y_cents = last_sound_cents if last_sound_cents is not None else s.cents
            else:
                color = get_color(s.cents)
                alpha = 0.92 if s.confidence is None else max(0.15, s.confidence * 0.9)
                y_staff = s.y_pos
                y_cents = s.cents
                last_sound_y = y_staff
                last_sound_cents = y_cents

            points.append({
                "x": x,
                "y_staff": y_staff,
                "y_cents": y_cents,
                "color": color,
                "alpha": alpha,
            })

        if len(points) < 2:
            return

        # Group into consecutive same-color segments for colored lines (like original)
        def make_pen(color: str, alpha: float, width: float):
            qcolor = QColor(color)
            qcolor.setAlphaF(alpha)
            return pg.mkPen(qcolor, width=width)

        # Staff trace segments
        i = 0
        while i < len(points):
            j = i
            curr_color = points[i]["color"]
            curr_alpha = points[i]["alpha"]
            xs_seg = []
            ys_seg = []
            while j < len(points) and points[j]["color"] == curr_color:
                xs_seg.append(points[j]["x"])
                ys_seg.append(points[j]["y_staff"])
                j += 1

            if len(xs_seg) >= 2:
                pen = make_pen(curr_color, curr_alpha, 3.5)
                seg = pg.PlotDataItem(xs_seg, ys_seg, pen=pen)
                self.staff_plot.addItem(seg)
                self.staff_segment_items.append(seg)
            i = j

        # Cents trace segments (same grouping, thinner)
        i = 0
        while i < len(points):
            j = i
            curr_color = points[i]["color"]
            curr_alpha = points[i]["alpha"]
            xs_seg = []
            ys_seg = []
            while j < len(points) and points[j]["color"] == curr_color:
                xs_seg.append(points[j]["x"])
                ys_seg.append(points[j]["y_cents"])
                j += 1

            if len(xs_seg) >= 2:
                pen = make_pen(curr_color, curr_alpha, 2.8)
                seg = pg.PlotDataItem(xs_seg, ys_seg, pen=pen)
                self.cents_plot.addItem(seg)
                self.cents_segment_items.append(seg)
            i = j

        # Musical x window
        self.staff_plot.setXRange(-self.beats_visible, 0.3)
        self.cents_plot.setXRange(-self.beats_visible, 0.3)

    def _update_current_display(self):
        if not self.history:
            self.current_label.setText("—")
            self.current_label.setStyleSheet("color: #aaaaaa;")
            return

        sample = self.history[-1]
        note = sample.note.upper() if sample.note else "---"
        cents = sample.cents

        if note.strip() == "---":
            text = "REST"
            color = "#8888aa"
        else:
            text = note
            if sample.level is not None:
                text += f"   lvl={sample.level:.2f}"
            color = get_color(cents)

        self.current_label.setText(text)
        self.current_label.setStyleSheet(f"color: {color};")

    # _update_stats and _update_stats_display removed (statistics not helpful)

    def _toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.setText("Resume" if self.paused else "Pause")
        if not self.paused:
            self.last_poll_wall = time.time()
            # give the display time a little kick so it doesn't jump
            if self.latest_teensy_ts > 0:
                self.display_now = max(self.display_now, self.latest_teensy_ts)

    def _clear_history(self):
        self.history.clear()
        # Clear colored segments
        for item in self.staff_segment_items:
            try:
                self.staff_plot.removeItem(item)
            except Exception:
                pass
        self.staff_segment_items.clear()
        for item in self.cents_segment_items:
            try:
                self.cents_plot.removeItem(item)
            except Exception:
                pass
        self.cents_segment_items.clear()

        # (colored segments cleared above)
        self.display_now = 0.0
        self.latest_teensy_ts = 0.0
        self._update_current_display()
        logging.info("History cleared")

    def _export_debug_log(self):
        if not self.history:
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Intune Debug Log", "intune_debug.csv", "CSV Files (*.csv)"
        )
        if not filepath:
            return
        try:
            with open(filepath, "w", encoding="utf-8", newline="") as f:
                f.write("# Intune Debug Export (pyqtgraph version)\n")
                f.write(f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Mode: {'SIMULATION' if self.config.simulate else 'REAL'}\n")
                f.write("# Columns: wall_time_iso, note, cents, confidence, y_pos\n\n")
                f.write("wall_time_iso,note,cents,confidence,y_pos\n")
                for sample in self.history:
                    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(sample.timestamp))
                    conf_str = f"{sample.confidence:.4f}" if sample.confidence is not None else ""
                    f.write(f"{iso},{sample.note},{sample.cents:.2f},{conf_str},{sample.y_pos:.4f}\n")
            logging.info(f"Exported to {filepath}")
        except Exception as e:
            logging.error(f"Export failed: {e}")

    def _on_mouse_moved(self, pos):
        """Simple crosshair + value when paused (like original hover inspection)."""
        if not self.paused or len(self.history) < 2:
            self.crosshair_v.setVisible(False)
            self.crosshair_h.setVisible(False)
            self.hover_label.setVisible(False)
            return

        # Map scene pos to data coordinates in the staff plot
        mouse_point = self.staff_plot.getViewBox().mapSceneToView(pos)
        x = mouse_point.x()

        # Find closest point in current plotted data
        best_dist = float("inf")
        best_sample = None
        best_x = 0
        best_y = 0

        visible_sec = self.beats_visible / (self.bpm / 60.0) if self.bpm > 0 else 4.0
        now_ts = self.display_now or self.latest_teensy_ts

        for s in self.history:
            if s.teensy_ts is None:
                continue
            age = (now_ts - s.teensy_ts) / 1000.0
            if age < 0 or age > visible_sec:
                continue
            beat_age = age * (self.bpm / 60.0)
            px = -beat_age
            dist = abs(px - x)
            if dist < best_dist:
                best_dist = dist
                best_sample = s
                best_x = px
                best_y = s.y_pos

        if best_sample is None:
            return

        self.crosshair_v.setPos(best_x)
        self.crosshair_h.setPos(best_y)
        self.crosshair_v.setVisible(True)
        self.crosshair_h.setVisible(True)

        conf_str = f"{best_sample.confidence:.2f}" if best_sample.confidence is not None else "—"
        sign = "+" if best_sample.cents >= 0 else ""
        text = f"t≈{- (now_ts - best_sample.teensy_ts)/1000:.2f}s  |  {best_sample.note}  {sign}{best_sample.cents:.1f}¢  |  conf={conf_str}"
        self.hover_label.setText(text)
        self.hover_label.setPos(x + 0.2, best_y + 0.6)
        self.hover_label.setVisible(True)

    def closeEvent(self, event):
        logging.info("Shutting down...")
        self.stop_event.set()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=1.0)
        event.accept()

# =============================================================================
# ENTRY POINT (adapted)
# =============================================================================

def parse_args() -> Config:
    parser = argparse.ArgumentParser(
        description="Intune — Real-time pitch visualization for viola (pyqtgraph)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--port", default=DEFAULT_PORT, help="Serial port")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baud rate")
    parser.add_argument("--simulate", action="store_true", help="Use built-in simulator")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports and exit")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.list_ports:
        if list_ports is None:
            print("pyserial not installed")
        else:
            print("\nAvailable serial ports:")
            ports = list(list_ports.comports())
            if not ports:
                print("  (none found)")
            for p in ports:
                print(f"  {p.device}  —  {p.description}")
        sys.exit(0)

    return Config(
        port=args.port,
        baud=args.baud,
        simulate=args.simulate,
        debug=args.debug,
        list_ports=args.list_ports,
    )

def main():
    config = parse_args()

    app = QApplication(sys.argv)
    pg.setConfigOptions(antialias=True, useOpenGL=False)  # OpenGL can be tried for extra smoothness

    window = IntuneVisualizer(config)
    window.show()

    # Print helpful info
    print("\n" + "=" * 60)
    print("  INTUNE — Viola Pitch Visualizer (pyqtgraph edition)")
    print("=" * 60)
    if config.simulate:
        print("  Mode: SIMULATION")
    else:
        print(f"  Serial: {config.port} @ {config.baud}")
    print("  PyQtGraph + efficient setData updates for smooth scrolling")
    print("  Shortcuts: many Qt defaults + Pause button, mouse hover when paused")
    print("=" * 60 + "\n")

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()