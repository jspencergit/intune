#!/usr/bin/env python3
"""
Intune - Real-time Viola Pitch Visualizer
==========================================

A high-quality, robust tool for visualizing intonation on the viola (Alto Clef).

Features:
- Threaded serial reader with automatic reconnection
- Simulation mode for development without hardware (--simulate)
- Large, clear current note + cents display with color
- Live statistics (time in tune, average deviation, etc.)
- Pause / Clear / History controls + crosshair inspection (pause then hover over trace)
- Keyboard shortcuts (E = export debug log)
- Cross-platform serial port handling
- Proper error handling and status feedback
- Clean, beautiful dark theme with musical staff

Expected serial data format (one line per reading):
    <anything>,Note,Cents
    Example: 1234,G3,12.7
"""

import argparse
import logging
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Deque

import numpy as np
import serial
from serial.tools import list_ports
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.collections import LineCollection
from matplotlib.widgets import Slider, Button

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_PORT = "COM3" if sys.platform.startswith("win") else "/dev/ttyACM0"
DEFAULT_BAUD = 115200
DEFAULT_HISTORY_SEC = 6.0
POINTS_PER_SECOND = 60
MIN_HISTORY_POINTS = 150
UPDATE_INTERVAL_MS = 20  # ~50 fps target

# Musical constants (Alto Clef / Viola)
# Expanded range to cover full practical viola: C3 (open C) → ~F6 (high on A string)
STAFF_Y_MAIN = [2.0, 2.8, 3.6, 4.4, 5.2]          # Core 5 staff lines (G3–E4 area)

# Extended ledger lines for full viola range
STAFF_Y_LEDGER = [
    1.2, 1.6,           # C3, D3 (low end)
    2.4, 3.2,           # E3/F3 area
    4.0, 4.8, 5.6, 6.4, 7.2, 8.0, 8.8,   # mid to high
    9.6, 10.4,          # C6 / E6 area
]

NOTE_LABELS = [
    # Full practical viola range: C3 (open C string) up to F6 (high positions on A string)
    ("C3", 1.2), ("D3", 1.6), ("E3", 2.0), ("F3", 2.4), ("G3", 2.8),
    ("A3", 3.2), ("B3", 3.6),
    ("C4", 4.0), ("D4", 4.4), ("E4", 4.8), ("F4", 5.2), ("G4", 5.6),
    ("A4", 6.0), ("B4", 6.4),
    ("C5", 6.8), ("D5", 7.2), ("E5", 7.6), ("F5", 8.0), ("G5", 8.4),
    ("A5", 8.8),
    ("C6", 9.6), ("D6", 10.0), ("E6", 10.4), ("F6", 10.8),
]

# Color scheme (dark elegant theme)
COLOR_BG = "#0a0a1f"
COLOR_IN_TUNE = "#7dff9f"
COLOR_SHARP = "#ff6b6b"   # red for sharp
COLOR_FLAT = "#6b9cff"    # blue for flat
COLOR_TEXT = "#e0e0ff"
COLOR_TEXT_DIM = "#aaaaaa"
COLOR_STAFF = "#eeeeee"
COLOR_LEDGER = "#aaaaaa"

IN_TUNE_THRESHOLD_CENTS = 5
GOOD_THRESHOLD_CENTS = 15

# =============================================================================
# DATA MODELS
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
    confidence: Optional[float] = None   # From 4th field (YIN probability, etc.)
    level: Optional[float] = None        # From 5th field (0-1 mic peak level) when available


@dataclass
class Stats:
    """Live session statistics."""
    start_time: float = field(default_factory=time.time)
    total_samples: int = 0
    in_tune_samples: int = 0
    sum_abs_cents: float = 0.0
    max_deviation: float = 0.0
    last_update: float = field(default_factory=time.time)

    def reset(self):
        self.start_time = time.time()
        self.total_samples = 0
        self.in_tune_samples = 0
        self.sum_abs_cents = 0.0
        self.max_deviation = 0.0
        self.last_update = time.time()

    @property
    def duration(self) -> float:
        return max(0.1, time.time() - self.start_time)

    @property
    def pct_in_tune(self) -> float:
        if self.total_samples == 0:
            return 0.0
        return (self.in_tune_samples / self.total_samples) * 100

    @property
    def mean_abs_cents(self) -> float:
        if self.total_samples == 0:
            return 0.0
        return self.sum_abs_cents / self.total_samples


# =============================================================================
# NOTE MAPPING
# =============================================================================

def pitch_to_y(note_str: str) -> float:
    """Convert note name (e.g. 'G3', 'A4') to y-position on Alto Clef staff."""
    if not note_str:
        return 4.0
    try:
        note = note_str[0].upper()
        # Handle possible trailing garbage
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
    """Return color based on intonation accuracy."""
    abs_cents = abs(cents)
    if abs_cents < IN_TUNE_THRESHOLD_CENTS:
        return COLOR_IN_TUNE
    elif cents > 0:
        return COLOR_SHARP
    else:
        return COLOR_FLAT


def get_color_with_alpha(cents: float, alpha: float = 1.0) -> tuple:
    """Return (color, alpha) tuple for more nuanced rendering."""
    return get_color(cents), alpha


# =============================================================================
# SERIAL READER (THREADED)
# =============================================================================

class SerialReader:
    """Threaded serial reader with automatic reconnection."""

    def __init__(self, port: str, baud: int, out_queue: queue.Queue, stop_event: threading.Event):
        self.port = port
        self.baud = baud
        self.out_queue = out_queue
        self.stop_event = stop_event
        self.ser: Optional[serial.Serial] = None
        self.running = False
        self.last_success = 0.0

    def _connect(self) -> bool:
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            logging.info(f"Connected to {self.port} @ {self.baud} baud")
            return True
        except serial.SerialException as e:
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
                    # Timeout or no data
                    if time.time() - self.last_success > 2.0:
                        # Consider connection stale
                        self._disconnect()
                    continue

                line = raw.decode("utf-8", errors="ignore").strip()
                logging.debug(f"Raw serial line: {line!r}")

                if not line or "," not in line:
                    logging.debug("  → Skipped (no comma or empty)")
                    continue

                parts = [p.strip() for p in line.split(",") if p.strip()]

                note = None
                cents = None

                # === Robust parsing for common formats ===
                # Format A (your Teensy):   timestamp,Note,Cents,amplitude
                # Format B (original):      ...,Note,Cents
                # Format C:                 Note,Cents
                if len(parts) >= 3:
                    # Try the classic "second and third fields" pattern first (very common)
                    try:
                        candidate_note = parts[1]
                        candidate_cents = float(parts[2])
                        if candidate_note and len(candidate_note) >= 2 and candidate_note[0].upper() in "ABCDEFG":
                            note = candidate_note
                            cents = candidate_cents
                    except (ValueError, IndexError):
                        pass

                if note is None and len(parts) >= 2:
                    # Fallback: last two fields (Note,Cents at the end)
                    try:
                        candidate_cents = float(parts[-1])
                        candidate_note = parts[-2]
                        if candidate_note and len(candidate_note) >= 2 and candidate_note[0].upper() in "ABCDEFG":
                            note = candidate_note
                            cents = candidate_cents
                    except (ValueError, IndexError):
                        pass

                if note is not None and cents is not None:
                    logging.debug(f"  → Parsed successfully: note={note}, cents={cents}")

                    # Try to parse optional 4th field as confidence/probability
                    confidence = None
                    if len(parts) >= 4:
                        try:
                            c4 = float(parts[3])
                            confidence = c4 / 100.0 if c4 > 1.0 else c4
                            confidence = max(0.0, min(1.0, confidence))
                        except (ValueError, IndexError):
                            pass

                    # Optional 5th field = level (0-1)
                    level = None
                    if len(parts) >= 5:
                        try:
                            level = float(parts[4])
                            level = max(0.0, min(1.0, level))
                        except (ValueError, IndexError):
                            pass

                    # For real acoustic input, skip very low-confidence readings
                    if confidence is None or confidence > 0.25:
                        sample = PitchSample(
                            timestamp=time.time(),
                            note=note,
                            cents=cents,
                            y_pos=pitch_to_y(note),
                            confidence=confidence,
                            level=level,
                        )
                        try:
                            self.out_queue.put_nowait(sample)
                            self.last_success = time.time()
                        except queue.Full:
                            pass
                else:
                    logging.debug(f"  → Failed to parse note+cents from parts={parts}")

            except serial.SerialException as e:
                logging.warning(f"Serial error: {e}")
                self._disconnect()
                time.sleep(0.5)
            except Exception as e:
                logging.debug(f"Unexpected read error: {e}")

        self._disconnect()
        self.running = False
        logging.info("Serial reader stopped")


# =============================================================================
# SIMULATOR (for development without hardware)
# =============================================================================

class Simulator:
    """Generates realistic drifting pitch data for testing."""

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
            # Simulate a player: slow drift + small jitter + occasional correction
            self.phase += 0.035
            self.drift += np.random.normal(0, 0.08)  # slow random walk
            self.drift = np.clip(self.drift, -35, 35)

            # Add some "effort" oscillation
            effort = 6.0 * np.sin(self.phase * 0.6) + 3.0 * np.sin(self.phase * 1.7)
            jitter = np.random.normal(0, 1.8)

            cents = self.drift + effort + jitter

            # Occasionally "nail" a note or have a bad moment
            if np.random.random() < 0.012:
                cents = np.random.choice([-18, -12, 0, 0, 0, 7, 14, 22])

            self.current_cents = float(np.clip(cents, -45, 45))

            sample = PitchSample(
                timestamp=time.time(),
                note=self.base_note,
                cents=self.current_cents,
                y_pos=self.base_y + (self.current_cents * 0.012),  # small visual movement
                confidence=None,   # Simulation doesn't have real detector confidence
            )
            try:
                self.out_queue.put_nowait(sample)
            except queue.Full:
                pass

            time.sleep(max(0.001, interval - 0.001))

        self.running = False
        logging.info("Simulator stopped")


# =============================================================================
# MAIN VISUALIZER
# =============================================================================

class IntuneVisualizer:
    """Main application class."""

    def __init__(self, config: Config):
        self.config = config
        self.max_points = max(MIN_HISTORY_POINTS, int(config.history_sec * POINTS_PER_SECOND))

        # Data
        self.history: Deque[PitchSample] = deque(maxlen=self.max_points)
        self.stats = Stats()
        self.paused = False
        self.last_data_time = 0.0

        # Threading
        self.data_queue: queue.Queue = queue.Queue(maxsize=500)
        self.stop_event = threading.Event()
        self.reader_thread: Optional[threading.Thread] = None
        self.reader: Optional[SerialReader | Simulator] = None

        # Matplotlib objects
        self.fig = None
        self.ax_main = None
        self.ax_status = None
        self.lc = None
        self.glow_lc = None
        self.zoom_lc = None
        self.ax_zoom = None
        self.current_text = None
        self.stats_text = None
        self.status_text = None
        self.slider = None
        self.pause_button = None
        self.clear_button = None
        self.export_button = None

        # Crosshair / hover inspection (shown when paused)
        self.crosshair_v = None
        self.crosshair_h = None
        self.hover_text = None

        self._setup_logging()
        self._setup_figure()

    def _setup_logging(self):
        level = logging.DEBUG if self.config.debug else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )

    def _setup_figure(self):
        plt.style.use("dark_background")
        self.fig = plt.figure(figsize=(16, 9), facecolor=COLOR_BG)

        # Use GridSpec for flexible layout
        # Row 0: Top bar - left: big current note, right: stats
        # Row 1: Main Alto Clef staff with trace
        # Row 2: Zoomed cents deviation view
        # Row 3: Controls
        gs = self.fig.add_gridspec(
            4, 1,
            height_ratios=[1.0, 3.8, 2.5, 0.9],
            hspace=0.13,
            left=0.06, right=0.98, top=0.94, bottom=0.05
        )

        # Top row: split into big current reading (left) and stats (right)
        gs_top = gs[0].subgridspec(1, 2, width_ratios=[2.1, 1.0], wspace=0.04)

        # Left: Big current note + cents display
        self.ax_status = self.fig.add_subplot(gs_top[0, 0])
        self.ax_status.set_xlim(0, 1)
        self.ax_status.set_ylim(0, 1)
        self.ax_status.axis("off")
        self.ax_status.set_facecolor(COLOR_BG)

        # Big current reading
        self.current_text = self.ax_status.text(
            0.5, 0.55, "—",
            fontsize=42, fontweight="bold", ha="center", va="center",
            color=COLOR_TEXT_DIM, family="monospace"
        )
        self.status_text = self.ax_status.text(
            0.5, 0.12, "Waiting for data...",
            fontsize=11, ha="center", va="center", color=COLOR_TEXT_DIM, alpha=0.85
        )

        # Right: Live statistics (moved here so it doesn't cover the right edge of the trace)
        self.ax_top_stats = self.fig.add_subplot(gs_top[0, 1])
        self.ax_top_stats.set_xlim(0, 1)
        self.ax_top_stats.set_ylim(0, 1)
        self.ax_top_stats.axis("off")
        self.ax_top_stats.set_facecolor(COLOR_BG)

        # Stats text - now lives in the top-right panel (no longer overlaps the right side of the trace)
        self.stats_text = self.ax_top_stats.text(
            0.97, 0.92, "",
            transform=self.ax_top_stats.transAxes,
            fontsize=8.5, ha="right", va="top",
            color=COLOR_TEXT_DIM, alpha=0.95,
            family="monospace",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#12122a", edgecolor="#2a2a55", alpha=0.92)
        )

        # Main staff plot (Alto Clef) - cropped at bottom for better vertical resolution on viola range (B3 and above)
        self.ax_main = self.fig.add_subplot(gs[1])
        self.ax_main.set_facecolor(COLOR_BG)
        # Full viola range: C3 (open C) to ~F6 (high on A string)
        self.ax_main.set_ylim(0.6, 11.5)
        self.ax_main.set_xlim(0, self.max_points)

        # Staff lines (adjusted - fewer low ledgers since we no longer show down to C3)
        for y in STAFF_Y_MAIN:
            self.ax_main.axhline(y=y, color=COLOR_STAFF, lw=1.6, alpha=0.85)
        # Reduced low ledger lines (B3 and above focus)
        for y in STAFF_Y_LEDGER:
            self.ax_main.axhline(y=y, color=COLOR_LEDGER, lw=0.9, linestyle="--", alpha=0.45)

        # Note labels on left (now starts at B3)
        for note, y in NOTE_LABELS:
            self.ax_main.text(-0.018, y, note, fontsize=10.5, va="center", ha="right",
                              color="#cccccc", fontweight="medium",
                              transform=self.ax_main.get_yaxis_transform())

        self.ax_main.text(-0.055, 5.8, "ALTO\nCLEF", fontsize=11, va="center", ha="center",
                          color="#88aaff", alpha=0.85, transform=self.ax_main.get_yaxis_transform(),
                          linespacing=1.15)

        self.ax_main.yaxis.set_visible(False)
        self.ax_main.set_xlabel("Time  (older  ←――――――――――→  newer)", fontsize=10, color=COLOR_TEXT_DIM, labelpad=6)
        self.ax_main.grid(True, alpha=0.07, linestyle="--", color="#445566")

        # === Zoomed Cents Deviation View (bottom) ===
        self.ax_zoom = self.fig.add_subplot(gs[2])
        self.ax_zoom.set_facecolor(COLOR_BG)
        self.ax_zoom.set_ylim(-25, 25)          # Good resolution for ± few cents while catching bigger errors
        self.ax_zoom.set_xlim(0, self.max_points)

        # Reference lines for the new ±5 cent in-tune zone
        self.ax_zoom.axhline(0, color="#ffffff", lw=1.1, alpha=0.65)                    # Target pitch
        self.ax_zoom.axhline(+IN_TUNE_THRESHOLD_CENTS, color=COLOR_IN_TUNE, lw=0.8, linestyle="--", alpha=0.6)
        self.ax_zoom.axhline(-IN_TUNE_THRESHOLD_CENTS, color=COLOR_IN_TUNE, lw=0.8, linestyle="--", alpha=0.6)

        # Light green band for in-tune zone
        self.ax_zoom.axhspan(-IN_TUNE_THRESHOLD_CENTS, +IN_TUNE_THRESHOLD_CENTS,
                             color=COLOR_IN_TUNE, alpha=0.08)

        self.ax_zoom.set_ylabel("Cents Deviation", fontsize=10, color=COLOR_TEXT_DIM, labelpad=4)
        self.ax_zoom.tick_params(axis='y', labelsize=8, colors=COLOR_TEXT_DIM)
        self.ax_zoom.set_xlabel("Time  (older  ←――――――――――→  newer)", fontsize=9, color=COLOR_TEXT_DIM, labelpad=4)
        self.ax_zoom.grid(True, alpha=0.07, linestyle="--", color="#445566")
        self.ax_zoom.yaxis.set_major_locator(plt.MultipleLocator(10))
        self.ax_zoom.yaxis.set_minor_locator(plt.MultipleLocator(5))

        # Line collections
        self.lc = LineCollection([], linewidth=3.8, alpha=0.92)
        self.ax_main.add_collection(self.lc)
        self.glow_lc = LineCollection([], linewidth=9.5, alpha=0.13)
        self.ax_main.add_collection(self.glow_lc)

        # Zoomed cents deviation trace (colored the same way as main trace)
        self.zoom_lc = LineCollection([], linewidth=2.8, alpha=0.95)
        self.ax_zoom.add_collection(self.zoom_lc)

        # Crosshair lines + hover readout (for paused inspection of glitches)
        self.crosshair_v = self.ax_main.axvline(
            x=0, color="#88ddff", lw=0.9, alpha=0.75, linestyle="--", visible=False
        )
        self.crosshair_h = self.ax_main.axhline(
            y=0, color="#88ddff", lw=0.9, alpha=0.75, linestyle="--", visible=False
        )
        self.hover_text = self.ax_main.text(
            0.02, 0.96, "",
            transform=self.ax_main.transAxes,
            fontsize=9.0, family="monospace",
            color="#ccffaa",
            va="top",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#0f0f22", edgecolor="#334455", alpha=0.9),
            visible=False
        )

        # (Stats panel moved to top-right bar - see ax_top_stats below)

        # Title
        self.fig.suptitle("Intune — Viola Intonation Visualizer", fontsize=16, color=COLOR_TEXT, y=0.985)

        # Controls
        self._create_controls()

        # Event handlers
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.fig.canvas.mpl_connect("close_event", self._on_close)
        self.fig.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.fig.canvas.mpl_connect("axes_leave_event", self._on_axes_leave)

    def _create_controls(self):
        # History slider
        ax_slider = self.fig.add_axes([0.22, 0.025, 0.42, 0.028])
        self.slider = Slider(
            ax_slider, "History (sec)", 1.5, 18.0,
            valinit=self.config.history_sec, valstep=0.5,
            color="#556688", handle_style={"facecolor": "#88aaff"}
        )
        self.slider.on_changed(self._on_history_change)

        # Pause button
        ax_pause = self.fig.add_axes([0.68, 0.025, 0.09, 0.038])
        self.pause_button = Button(ax_pause, "Pause", color="#2a2a55", hovercolor="#3a3a70")
        self.pause_button.on_clicked(self._toggle_pause)

        # Clear button
        ax_clear = self.fig.add_axes([0.78, 0.025, 0.09, 0.038])
        self.clear_button = Button(ax_clear, "Clear", color="#2a2a55", hovercolor="#3a3a70")
        self.clear_button.on_clicked(self._clear_history)

        # Export Debug Log button (new)
        ax_export = self.fig.add_axes([0.88, 0.025, 0.10, 0.038])
        self.export_button = Button(ax_export, "Export Log", color="#2a2a55", hovercolor="#3a3a70")
        self.export_button.on_clicked(self._export_debug_log)

    # -------------------------------------------------------------------------
    # DATA INGESTION & STATS
    # -------------------------------------------------------------------------

    def _ingest_data(self):
        """Pull any available samples from the queue (non-blocking)."""
        ingested = 0
        while True:
            try:
                sample = self.data_queue.get_nowait()
            except queue.Empty:
                break

            if not self.paused:
                self.history.append(sample)
                self._update_stats(sample)
                ingested += 1

        if ingested:
            self.last_data_time = time.time()

    def _update_stats(self, sample: PitchSample):
        self.stats.total_samples += 1
        abs_c = abs(sample.cents)
        self.stats.sum_abs_cents += abs_c
        self.stats.max_deviation = max(self.stats.max_deviation, abs_c)
        if abs_c < IN_TUNE_THRESHOLD_CENTS:
            self.stats.in_tune_samples += 1
        self.stats.last_update = time.time()

    # -------------------------------------------------------------------------
    # RENDERING
    # -------------------------------------------------------------------------

    def _render(self):
        if len(self.history) < 2:
            self.lc.set_segments([])
            self.glow_lc.set_segments([])
            self.zoom_lc.set_segments([])
            self._update_current_display(None)
            self._update_stats_display()
            return

        # Right-align the trace (newest data at the right edge)
        n = len(self.history)
        x = np.arange(self.max_points - n, self.max_points)

        y = np.array([s.y_pos for s in self.history])
        cents = np.array([s.cents for s in self.history])

        # Build segments for LineCollection
        points = np.column_stack((x, y)).reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)

        # Build rgba colors so we can fade the trace on low confidence (very useful with real mic).
        colors = []
        glow_colors = []
        for i, c in enumerate(cents):
            base = get_color(c)
            conf = self.history[i].confidence
            alpha = 0.92 if conf is None else max(0.15, conf * 0.9)
            # Simple hex to rgb (assumes #rrggbb)
            r = int(base[1:3], 16) / 255.0
            g = int(base[3:5], 16) / 255.0
            b = int(base[5:7], 16) / 255.0
            colors.append((r, g, b, alpha))
            glow_colors.append((r, g, b, alpha * 0.15))

        self.lc.set_segments(segments)
        self.lc.set_color(colors)

        self.glow_lc.set_segments(segments)
        self.glow_lc.set_color(glow_colors)

        # Zoomed cents view (same x, y = cents deviation)
        zoom_points = np.column_stack((x, cents)).reshape(-1, 1, 2)
        zoom_segments = np.concatenate([zoom_points[:-1], zoom_points[1:]], axis=1)
        self.zoom_lc.set_segments(zoom_segments)
        self.zoom_lc.set_color(colors)

        self._update_current_display(self.history[-1])
        self._update_stats_display()

    def _update_current_display(self, sample: Optional[PitchSample]):
        if sample is None:
            self.current_text.set_text("—")
            self.current_text.set_color(COLOR_TEXT_DIM)
            self.status_text.set_text("Waiting for data..." if not self.paused else "PAUSED")
            return

        note = sample.note.upper()
        cents = sample.cents
        sign = "+" if cents >= 0 else ""
        text = f"{note}   {sign}{cents:.1f}¢"

        color = get_color(cents)
        self.current_text.set_text(text)
        self.current_text.set_color(color)

        # Status line
        age = time.time() - sample.timestamp
        if age > 1.5:
            status = f"Last reading: {age:.1f}s ago"
        else:
            status = "Receiving data ✓"

        if self.paused:
            status = "PAUSED — press SPACE or click Pause to resume"

        self.status_text.set_text(status)
        self.status_text.set_color("#ffcc66" if self.paused else COLOR_TEXT_DIM)

    def _update_stats_display(self):
        s = self.stats
        lines = [
            f"Session: {s.duration:.0f}s",
            f"Samples: {s.total_samples}",
            f"In tune (<{IN_TUNE_THRESHOLD_CENTS}¢): {s.pct_in_tune:.1f}%",
            f"Mean |dev|: {s.mean_abs_cents:.1f}¢",
            f"Max dev: {s.max_deviation:.1f}¢",
        ]
        self.stats_text.set_text("\n".join(lines))

    # -------------------------------------------------------------------------
    # CONTROLS & EVENTS
    # -------------------------------------------------------------------------

    def _on_history_change(self, val: float):
        new_max = max(MIN_HISTORY_POINTS, int(val * POINTS_PER_SECOND))
        if new_max == self.max_points:
            return

        # Resize history buffer
        old_data = list(self.history)
        self.max_points = new_max
        self.history = deque(old_data[-new_max:], maxlen=new_max)

        self.ax_main.set_xlim(0, new_max)
        if self.ax_zoom is not None:
            self.ax_zoom.set_xlim(0, new_max)
        self.slider.valtext.set_text(f"{val:.1f}")

    def _toggle_pause(self, event=None):
        self.paused = not self.paused
        label = "Resume" if self.paused else "Pause"
        self.pause_button.label.set_text(label)
        self._update_current_display(self.history[-1] if self.history else None)
        if not self.paused:
            self._hide_crosshair()

    def _clear_history(self, event=None):
        self.history.clear()
        self.stats.reset()
        self.lc.set_segments([])
        self.glow_lc.set_segments([])
        if self.zoom_lc is not None:
            self.zoom_lc.set_segments([])
        self._update_current_display(None)
        self._update_stats_display()
        self._hide_crosshair()
        logging.info("History cleared")

    def _export_debug_log(self, event=None):
        """Export current history + stats to a CSV file chosen by the user."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            from datetime import datetime
        except Exception as e:
            logging.error(f"Could not open file dialog: {e}")
            print("Export failed: tkinter file dialog not available.")
            return

        root = tk.Tk()
        root.withdraw()

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        mode = "SIM" if self.config.simulate else "HW"
        default_name = f"intune_debug_{mode}_{ts}.csv"

        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=default_name,
            title="Save Intune Debug Log",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        root.destroy()

        if not filepath:
            logging.info("Export cancelled by user")
            return

        try:
            with open(filepath, "w", encoding="utf-8", newline="") as f:
                # Header / metadata
                f.write("# Intune Debug Export\n")
                f.write(f"# Generated: {datetime.now().isoformat()}\n")
                f.write(f"# Mode: {'SIMULATION' if self.config.simulate else 'REAL HARDWARE'}\n")
                f.write(f"# Port: {self.config.port if not self.config.simulate else 'N/A'}\n")
                f.write(f"# History window at capture: {self.max_points / POINTS_PER_SECOND:.1f} seconds\n")
                f.write(f"# Samples in buffer: {len(self.history)}\n")
                f.write("#\n")
                f.write("# === Current Session Stats ===\n")
                s = self.stats
                f.write(f"# Duration: {s.duration:.1f}s\n")
                f.write(f"# Total samples: {s.total_samples}\n")
                f.write(f"# In tune (<{IN_TUNE_THRESHOLD_CENTS}¢): {s.pct_in_tune:.2f}%\n")
                f.write(f"# Mean |dev|: {s.mean_abs_cents:.2f}¢\n")
                f.write(f"# Max dev: {s.max_deviation:.2f}¢\n")
                f.write("#\n")
                f.write("# Columns: wall_time_iso, relative_time_s, note, cents, confidence, y_pos\n")
                f.write("# confidence: detector probability (0-1) when available, empty if unknown\n")
                f.write("\n")

                # CSV header
                f.write("wall_time_iso,relative_time_s,note,cents,confidence,y_pos\n")

                if len(self.history) == 0:
                    f.write("# (no data in history buffer at time of export)\n")
                else:
                    t0 = self.history[0].timestamp
                    for sample in self.history:
                        rel = sample.timestamp - t0
                        conf_str = f"{sample.confidence:.4f}" if sample.confidence is not None else ""
                        iso = datetime.fromtimestamp(sample.timestamp).isoformat()
                        f.write(f"{iso},{rel:.4f},{sample.note},{sample.cents:.2f},{conf_str},{sample.y_pos:.4f}\n")

            logging.info(f"Debug log exported to: {filepath}")
            print(f"\n[EXPORT] Debug log saved to: {filepath}")

        except Exception as e:
            logging.error(f"Failed to write debug log: {e}")
            print(f"Export failed: {e}")

    def _on_key(self, event):
        if event.key == " " or event.key == "p":
            self._toggle_pause()
        elif event.key == "c":
            self._clear_history()
        elif event.key == "e":
            self._export_debug_log()
        elif event.key == "q" or event.key == "escape":
            plt.close(self.fig)
        elif event.key == "r":
            self.stats.reset()
            self._update_stats_display()
            logging.info("Stats reset")

    def _on_close(self, event):
        logging.info("Window closed — shutting down...")
        self.stop_event.set()

    # -------------------------------------------------------------------------
    # CROSSHAIR / HOVER INSPECTION (mainly useful when paused)
    # -------------------------------------------------------------------------

    def _on_mouse_move(self, event):
        """Show crosshair + value readout when mouse is over the main plot (best when paused)."""
        if event.inaxes != self.ax_main:
            self._hide_crosshair()
            return

        # Only show helpful crosshair when paused (user's stated use case)
        if not self.paused or len(self.history) < 2:
            self._hide_crosshair()
            return

        x = event.xdata
        if x is None:
            self._hide_crosshair()
            return

        # Map mouse x back to index in history (right-aligned layout)
        n = len(self.history)
        x_start = self.max_points - n
        idx = int(round(x - x_start))
        idx = max(0, min(idx, n - 1))

        sample = list(self.history)[idx]   # deque -> list for indexing

        # Seconds ago (relative to newest sample in buffer)
        seconds_ago = (self.max_points - (x_start + idx)) / POINTS_PER_SECOND

        # Update crosshair lines
        self.crosshair_v.set_xdata([x_start + idx, x_start + idx])
        self.crosshair_v.set_visible(True)

        self.crosshair_h.set_ydata([sample.y_pos, sample.y_pos])
        self.crosshair_h.set_visible(True)

        # Build nice hover text
        conf_str = f"{sample.confidence:.2f}" if sample.confidence is not None else "—"
        sign = "+" if sample.cents >= 0 else ""
        text = (f"t=-{seconds_ago:.2f}s  |  {sample.note}  "
                f"{sign}{sample.cents:.1f}¢  |  conf={conf_str}")

        self.hover_text.set_text(text)
        self.hover_text.set_visible(True)

        # Redraw just the affected artists (cheap enough)
        self.fig.canvas.draw_idle()

    def _on_axes_leave(self, event):
        """Hide crosshair when mouse leaves the main plot area."""
        self._hide_crosshair()

    def _hide_crosshair(self):
        changed = False
        if self.crosshair_v and self.crosshair_v.get_visible():
            self.crosshair_v.set_visible(False)
            changed = True
        if self.crosshair_h and self.crosshair_h.get_visible():
            self.crosshair_h.set_visible(False)
            changed = True
        if self.hover_text and self.hover_text.get_visible():
            self.hover_text.set_visible(False)
            changed = True

        if changed:
            self.fig.canvas.draw_idle()

    # -------------------------------------------------------------------------
    # ANIMATION & LIFECYCLE
    # -------------------------------------------------------------------------

    def _start_reader(self):
        if self.config.simulate:
            self.reader = Simulator(self.data_queue, self.stop_event)
            name = "Simulator"
        else:
            self.reader = SerialReader(
                self.config.port, self.config.baud, self.data_queue, self.stop_event
            )
            name = f"SerialReader({self.config.port})"

        self.reader_thread = threading.Thread(target=self.reader.run, name=name, daemon=True)
        self.reader_thread.start()
        logging.info(f"Started {name}")

    def _animation_update(self, frame):
        """Called by FuncAnimation."""
        self._ingest_data()
        self._render()
        return self.lc, self.glow_lc

    def run(self):
        print("\n" + "=" * 60)
        print("  INTUNE — Viola Pitch Visualizer")
        print("=" * 60)
        if self.config.simulate:
            print("  Mode: SIMULATION (no hardware required)")
        else:
            print(f"  Serial: {self.config.port} @ {self.config.baud} baud")
        print(f"  History window: {self.config.history_sec:.1f} seconds")
        print("  Shortcuts: SPACE=pause/resume, C=clear, E=export, R=reset stats, Q=quit")
        print("  Layout: Top = Alto Clef staff (C3–F6) | Bottom = Zoomed ±25¢ view (green = ±5¢ in tune)")
        print("  Tip: With real mic, low-confidence readings are filtered. Pause + hover for crosshairs.")
        print("=" * 60 + "\n")

        self._start_reader()

        # Give the reader a moment to start
        time.sleep(0.15)

        ani = animation.FuncAnimation(
            self.fig,
            self._animation_update,
            interval=UPDATE_INTERVAL_MS,
            blit=False,
            cache_frame_data=False,
        )

        try:
            plt.show()
        finally:
            self.stop_event.set()
            if self.reader_thread and self.reader_thread.is_alive():
                self.reader_thread.join(timeout=1.5)
            logging.info("Shutdown complete.")


# =============================================================================
# ENTRY POINT
# =============================================================================

def parse_args() -> Config:
    parser = argparse.ArgumentParser(
        description="Intune — Real-time pitch visualization for viola",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--port", default=DEFAULT_PORT, help="Serial port (e.g. COM3 or /dev/ttyACM0)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baud rate")
    parser.add_argument("--history", type=float, default=DEFAULT_HISTORY_SEC,
                        help="Initial history window in seconds")
    parser.add_argument("--simulate", action="store_true",
                        help="Run with built-in pitch simulator (no hardware needed)")
    parser.add_argument("--list-ports", action="store_true",
                        help="List available serial ports and exit")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.list_ports:
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
        history_sec=args.history,
        simulate=args.simulate,
        debug=args.debug,
        list_ports=args.list_ports,
    )


def main():
    config = parse_args()
    visualizer = IntuneVisualizer(config)
    visualizer.run()


if __name__ == "__main__":
    main()
