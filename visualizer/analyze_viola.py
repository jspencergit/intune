#!/usr/bin/env python3
"""
Viola Pitch Analysis Tool
=========================

PC-first pitch detection development script.

This script:
- Loads a clean viola reference recording
- Runs high-quality pitch detection using librosa.pyin
- Plays the audio on your speakers
- Generates rich visualizations (waveform, pitch, cents deviation, confidence)
- Automatically saves the plot as a PNG (with timestamp) in the 'plots/' folder

Usage:
    python analyze_viola.py

Requirements:
    pip install librosa sounddevice soundfile matplotlib numpy
"""

import os
import time
import threading
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import librosa
import sounddevice as sd
import soundfile as sf

# =============================================================================
# CONFIGURATION
# =============================================================================

# === Choose your audio file here ===
# For clean algorithm development, prefer non-vibrato files when possible.

AUDIO_PATH = Path(r"C:\Code\reference_audio\viola\viola_A4_1_piano_arco-glissando.mp3")

# Other interesting files you can quickly switch to:
# AUDIO_PATH = Path(r"C:\Code\reference_audio\viola\viola_A4_1_pianissimo_arco-normal.mp3")
# AUDIO_PATH = Path(r"C:\Code\reference_audio\viola\viola_C4_1_mezzo-piano_non-vibrato.mp3")
# AUDIO_PATH = Path(r"C:\Code\reference_audio\viola\viola_G4_1_mezzo-piano_non-vibrato.mp3")

# Recommended non-vibrato files (good for early testing - all ~1 second long)
NON_VIBRATO_FILES = [
    Path(r"C:\Code\reference_audio\viola\viola_C4_1_mezzo-piano_non-vibrato.mp3"),
    Path(r"C:\Code\reference_audio\viola\viola_G4_1_mezzo-piano_non-vibrato.mp3"),
    Path(r"C:\Code\reference_audio\viola\viola_D5_1_mezzo-piano_non-vibrato.mp3"),
    Path(r"C:\Code\reference_audio\viola\viola_A4_1_mezzo-piano_non-vibrato.mp3"),
    Path(r"C:\Code\reference_audio\viola\viola_C3_1_mezzo-piano_non-vibrato.mp3"),
]

# Analysis parameters
SR = 22050                    # Sample rate for analysis (good balance of quality vs speed)
HOP_LENGTH = 512              # Hop length for pitch tracking (~23ms frames at 22kHz)
FRAME_LENGTH = 2048

# Output folder for saved plots (will be created automatically)
OUTPUT_DIR = Path("plots")

# For plotting
PLOT_DPI = 140

# Set to True only when running in an environment without speakers or a display.
# On your normal Windows machine, leave this as False.
HEADLESS = False


# =============================================================================
# AUDIO LOADING & PITCH ANALYSIS
# =============================================================================

def load_and_analyze(audio_path: Path):
    print(f"Loading: {audio_path.name}")
    print(f"Full path: {audio_path}")

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Load audio
    y, sr = librosa.load(str(audio_path), sr=SR, mono=True)
    duration = len(y) / sr
    print(f"Duration: {duration:.2f} seconds | Sample rate: {sr} Hz")

    # Run probabilistic YIN (very good for monophonic instruments)
    print("Running pitch detection (librosa.pyin)...")
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y,
        fmin=librosa.note_to_hz('C2'),
        fmax=librosa.note_to_hz('C7'),
        sr=sr,
        hop_length=HOP_LENGTH,
        frame_length=FRAME_LENGTH,
    )

    # Create time axis for the pitch data
    times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=HOP_LENGTH)

    # Convert frequency to note + cents
    notes = []
    cents = []
    for freq in f0:
        if np.isnan(freq) or freq <= 0:
            notes.append(None)
            cents.append(np.nan)
            continue

        midi = librosa.hz_to_midi(freq)
        midi_rounded = int(round(midi))
        note_name = librosa.midi_to_note(midi_rounded, octave=True)
        cents_dev = (midi - midi_rounded) * 100

        notes.append(note_name)
        cents.append(cents_dev)

    cents = np.array(cents)

    print("Analysis complete.")
    return {
        "y": y,
        "sr": sr,
        "duration": duration,
        "times": times,
        "f0": f0,
        "cents": cents,
        "voiced_probs": voiced_probs,
        "voiced_flag": voiced_flag,
        "notes": notes,
    }


# =============================================================================
# AUDIO PLAYBACK
# =============================================================================

def play_audio(y, sr):
    """Play audio in a separate thread so we can do other things."""
    if HEADLESS:
        print("\n[HEADLESS MODE] Skipping audio playback.")
        return
    print("\n▶ Playing audio...")
    sd.play(y, sr)
    # Wait until playback finishes
    sd.wait()
    print("Playback finished.")


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_analysis(data: dict, audio_path: Path):
    y = data["y"]
    sr = data["sr"]
    times = data["times"]
    f0 = data["f0"]
    cents = data["cents"]
    voiced_probs = data["voiced_probs"]

    # Create time axis for the raw waveform
    wave_times = np.linspace(0, len(y) / sr, num=len(y))

    fig, axes = plt.subplots(4, 1, figsize=(14, 10), sharex=True)
    fig.suptitle(f"Viola Pitch Analysis: {audio_path.name}", fontsize=16, fontweight="bold")

    # 1. Waveform
    ax = axes[0]
    ax.plot(wave_times, y, color="#1f77b4", linewidth=0.6)
    ax.set_ylabel("Amplitude")
    ax.set_title("Waveform")
    ax.grid(True, alpha=0.3)

    # 2. Pitch (Frequency in Hz)
    ax = axes[1]
    ax.plot(times, f0, color="#2ca02c", linewidth=1.5, label="Detected Pitch (pyin)")
    ax.set_ylabel("Frequency (Hz)")
    ax.set_title("Detected Fundamental Frequency")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)

    # 3. Cents deviation
    ax = axes[2]
    ax.plot(times, cents, color="#d62728", linewidth=1.2)
    ax.axhline(0, color="black", linestyle="--", linewidth=0.8, alpha=0.7)
    ax.axhline(9, color="green", linestyle=":", linewidth=0.8, alpha=0.6, label="±9 cents (in tune)")
    ax.axhline(-9, color="green", linestyle=":", linewidth=0.8, alpha=0.6)
    ax.fill_between(times, -9, 9, color="green", alpha=0.08)
    ax.set_ylabel("Cents Deviation")
    ax.set_title("Cents from Nearest Semitone (0 = perfectly in tune)")
    ax.set_ylim(-50, 50)
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)

    # 4. Voiced probability
    ax = axes[3]
    ax.plot(times, voiced_probs, color="#9467bd", linewidth=1.2)
    ax.fill_between(times, 0, voiced_probs, color="#9467bd", alpha=0.2)
    ax.set_ylabel("Voiced Probability")
    ax.set_xlabel("Time (seconds)")
    ax.set_title("Confidence that a note is sounding (pyin)")
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    # === Auto-save the plot ===
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    safe_name = audio_path.stem.replace(" ", "_")
    save_path = OUTPUT_DIR / f"{safe_name}_{timestamp}.png"

    plt.savefig(save_path, dpi=PLOT_DPI, bbox_inches="tight")
    print(f"\n[SAVED] Plot automatically saved to: {save_path.resolve()}")

    if not HEADLESS:
        plt.show()
    else:
        plt.close()  # Close the figure so we don't leak memory in headless mode


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("  VIOLA PITCH ANALYSIS TOOL  (PC-first development)")
    print("=" * 60)
    print(f"Analyzing: {AUDIO_PATH.name}\n")

    data = load_and_analyze(AUDIO_PATH)

    # Play audio in background thread (skipped in HEADLESS mode)
    playback_thread = threading.Thread(target=play_audio, args=(data["y"], data["sr"]), daemon=True)
    playback_thread.start()

    # Give the audio a moment to start (only relevant when not headless)
    if not HEADLESS:
        time.sleep(0.3)

    # Show the plots + auto-save
    plot_analysis(data, AUDIO_PATH)

    # Wait for playback to finish if it's still going
    if not HEADLESS:
        playback_thread.join(timeout=2)

    print("\n" + "=" * 60)
    print("Done.")
    print("- Edit AUDIO_PATH at the top of this file to analyze a different recording.")
    print("- All plots are automatically saved in the 'plots/' folder.")
    print("=" * 60)


def run_batch(files):
    """Process multiple files one after another.
    For each file: plays audio + pops up the plot window.
    Waits for you to close the plot before moving to the next file.
    """
    print("\n" + "=" * 60)
    print(f"  BATCH MODE - Processing {len(files)} files")
    print("=" * 60)

    for i, filepath in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] Processing: {filepath.name}")
        print("-" * 40)

        # Temporarily override AUDIO_PATH for this file
        global AUDIO_PATH
        AUDIO_PATH = filepath

        main()

        if i < len(files):
            input("\nPress Enter to continue to the next file...")

    print("\nBatch complete. All plots saved in the 'plots/' folder.")


if __name__ == "__main__":
    # === Easy ways to run ===

    # Default: Analyze whatever is set in AUDIO_PATH above
    # (Currently set to the A4 pianissimo file you asked for)
    main()

    # Alternative: Run the batch of non-vibrato files one after another
    # (Uncomment the line below if you want to process several files in a row)
    # run_batch(NON_VIBRATO_FILES)
