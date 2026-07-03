#!/usr/bin/env python3
"""
Generate synthetic C-major scales for intonation testing.

Pure sine tones (A4=440), 1 second per note, first-position viola range C3–E5.
Lower notes are boosted (and highs slightly reduced) so speaker playback is more
even — helps the INMP441 pick up weak fundamentals on C3/D3.

Files (default --all):
  test_audio/synthetic_C_major_scale_perfect.mp3          up only, pure sine
  test_audio/synthetic_C_major_scale_updown_perfect.mp3   up + down, pure sine
  test_audio/synthetic_C_major_scale_updown_detuned.mp3   up + down, pure sine, detuned

Viola-like harmonic scales (--rich-scales):
  test_audio/synthetic_C_major_scale_updown_viola_perfect.mp3
  test_audio/synthetic_C_major_scale_updown_viola_detuned.mp3

Usage:
    python generate_test_scale.py --all
    python generate_test_scale.py --rich-scales
    python generate_test_scale.py --mode updown --tone viola --detune
    python generate_test_scale.py --output ../test_audio/custom.mp3 --mode updown
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

NOTES = [
    "C3", "D3", "E3", "F3", "G3", "A3", "B3",
    "C4", "D4", "E4", "F4", "G4", "A4", "B4",
    "C5", "D5", "E5",
]

# Reproducible small intonation errors (cents) for the detuned variant.
# Alternating sharp/flat, ±3..±12¢ — enough to see on the visualizer, not huge leaps.
DETUNE_CENTS_BY_NOTE = {
    "C3": +7.0,  "D3": -5.0,  "E3": +10.0, "F3": -6.0,  "G3": +8.0,
    "A3": -9.0,  "B3": +4.0,  "C4": -7.0,  "D4": +11.0, "E4": -5.0,
    "F4": +6.0,  "G4": -8.0,  "A4": +9.0,  "B4": -4.0,  "C5": +7.0,
    "D5": -10.0, "E5": +5.0,
}

NOTE_TO_MIDI = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_AUDIO = REPO_ROOT / "test_audio"

SR = 44100
NOTE_SEC = 1.0
FADE_SEC = 0.008
GAIN = 0.82

# Per-note level compensation: speakers/mics favor highs; boost lows relative to A4.
LEVEL_REF_HZ = 440.0
LEVEL_COMP_EXP = 0.55
MAX_LEVEL_BOOST_DB = 10.0

# Harmonic weights (1st–8th partial). Normalized in render; approximates bowed string brightness.
VIOLA_PARTIALS: list[tuple[int, float]] = [
    (1, 1.00),
    (2, 0.58),
    (3, 0.36),
    (4, 0.23),
    (5, 0.15),
    (6, 0.10),
    (7, 0.06),
    (8, 0.04),
]

VIOLA_ATTACK_SEC = 0.040
VIOLA_RELEASE_SEC = 0.070


def note_name_to_midi(name: str) -> int:
    letter = name[:-1]
    octave = int(name[-1])
    return (octave + 1) * 12 + NOTE_TO_MIDI[letter]


def midi_to_freq(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def freq_with_cents(base_freq: float, cents: float) -> float:
    return base_freq * (2.0 ** (cents / 1200.0))


def gain_for_freq(freq: float) -> float:
    """Boost low fundamentals; trim highs. Capped so C3 isn't excessive."""
    ratio = LEVEL_REF_HZ / freq
    gain = ratio ** LEVEL_COMP_EXP
    max_gain = 10.0 ** (MAX_LEVEL_BOOST_DB / 20.0)
    min_gain = 1.0 / max_gain
    return float(np.clip(gain, min_gain, max_gain))


def note_sequence(mode: str) -> list[str]:
    if mode == "up":
        return list(NOTES)
    if mode == "updown":
        return list(NOTES) + NOTES[-2::-1]  # C3..E5, then D5..C3
    raise ValueError(f"unknown mode: {mode}")


def note_envelope(n: int, sr: int, attack_sec: float, release_sec: float) -> np.ndarray:
    env = np.ones(n, dtype=np.float64)
    attack_n = max(1, int(attack_sec * sr))
    release_n = max(1, int(release_sec * sr))
    if attack_n + release_n >= n:
        attack_n = max(1, n // 4)
        release_n = max(1, n // 4)
    env[:attack_n] = np.linspace(0.0, 1.0, attack_n) ** 0.75
    env[-release_n:] = np.linspace(1.0, 0.0, release_n) ** 1.1

    fade_n = max(1, int(FADE_SEC * sr))
    ramp = np.ones(n, dtype=np.float64)
    ramp[:fade_n] = np.linspace(0.0, 1.0, fade_n)
    ramp[-fade_n:] = np.linspace(1.0, 0.0, fade_n)
    return env * ramp


def render_note_sine(freq: float, duration_sec: float, sr: int) -> np.ndarray:
    n = int(duration_sec * sr)
    t = np.arange(n, dtype=np.float64) / sr
    tone = np.sin(2.0 * np.pi * freq * t)
    env = note_envelope(n, sr, FADE_SEC, FADE_SEC)
    level = GAIN * gain_for_freq(freq)
    return (tone * env * level).astype(np.float32)


def render_note_viola(freq: float, duration_sec: float, sr: int) -> np.ndarray:
    n = int(duration_sec * sr)
    t = np.arange(n, dtype=np.float64) / sr
    partial_sum = sum(amp for _, amp in VIOLA_PARTIALS)

    tone = np.zeros(n, dtype=np.float64)
    for harmonic, amp in VIOLA_PARTIALS:
        tone += amp * np.sin(2.0 * np.pi * freq * harmonic * t)
    tone /= partial_sum

    env = note_envelope(n, sr, VIOLA_ATTACK_SEC, VIOLA_RELEASE_SEC)
    level = GAIN * gain_for_freq(freq)
    return (tone * env * level).astype(np.float32)


def render_note(freq: float, duration_sec: float, sr: int, tone: str = "sine") -> np.ndarray:
    if tone == "viola":
        return render_note_viola(freq, duration_sec, sr)
    if tone == "sine":
        return render_note_sine(freq, duration_sec, sr)
    raise ValueError(f"unknown tone: {tone}")


def write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    pcm = np.clip(audio, -1.0, 1.0)
    pcm_i16 = (pcm * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm_i16.tobytes())


def wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError(
            "MP3 export needs imageio-ffmpeg. Install with: pip install imageio-ffmpeg"
        ) from exc

    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(wav_path),
        "-codec:a", "libmp3lame", "-q:a", "2",
        str(mp3_path),
    ]
    subprocess.run(cmd, check=True)


def build_scale(
    mode: str = "up",
    note_sec: float = NOTE_SEC,
    detune: bool = False,
    tone: str = "sine",
) -> tuple[np.ndarray, list[tuple[str, float, float, float]]]:
    """Returns audio and metadata: (name, ideal_hz, actual_hz, start_sec)."""
    sequence = note_sequence(mode)
    segments: list[np.ndarray] = []
    meta: list[tuple[str, float, float, float]] = []
    t0 = 0.0

    for name in sequence:
        midi = note_name_to_midi(name)
        ideal = midi_to_freq(midi)
        cents = DETUNE_CENTS_BY_NOTE.get(name, 0.0) if detune else 0.0
        actual = freq_with_cents(ideal, cents)
        segments.append(render_note(actual, note_sec, SR, tone=tone))
        meta.append((name, ideal, actual, t0))
        t0 += note_sec

    audio = np.concatenate(segments)
    peak = float(np.max(np.abs(audio)))
    if peak > 0.0:
        audio = audio * (0.95 / peak)
    return audio, meta


def save_mp3(audio: np.ndarray, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "scale.wav"
        write_wav(wav_path, audio, SR)
        wav_to_mp3(wav_path, output)


def print_meta(title: str, meta: list, note_sec: float, detune: bool) -> None:
    print(title)
    print(f"  Notes: {len(meta)}  ({meta[0][0]} .. {meta[-1][0]})")
    print(f"  Duration: {len(meta) * note_sec:.1f}s  ({note_sec:.1f}s per note)")
    for name, ideal, actual, start in meta:
        level_db = 20.0 * np.log10(gain_for_freq(actual))
        if detune:
            cents = 1200.0 * np.log2(actual / ideal)
            print(
                f"    {start:5.1f}s  {name:3s}  {actual:8.3f} Hz  "
                f"({cents:+.1f}¢)  level {level_db:+.1f} dB rel A4"
            )
        else:
            print(
                f"    {start:5.1f}s  {name:3s}  {actual:8.3f} Hz  "
                f"level {level_db:+.1f} dB rel A4"
            )


def generate_one(
    output: Path,
    mode: str,
    note_sec: float,
    detune: bool,
    wav_only: bool,
    tone: str = "sine",
) -> None:
    audio, meta = build_scale(mode=mode, note_sec=note_sec, detune=detune, tone=tone)
    tone_label = "viola-like" if tone == "viola" else "sine"
    label = (
        f"Synthetic C-major ({mode}, {tone_label}"
        + (", detuned" if detune else ", perfect")
        + ")"
    )
    print_meta(label, meta, note_sec, detune)

    if wav_only or output.suffix.lower() == ".wav":
        out = output if output.suffix else output.with_suffix(".wav")
        write_wav(out, audio, SR)
        print(f"  [SAVED] {out}\n")
        return

    save_mp3(audio, output)
    print(f"  [SAVED] {output}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic C-major test scales")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--mode", choices=("up", "updown"), default="up")
    parser.add_argument("--note-sec", type=float, default=NOTE_SEC)
    parser.add_argument("--detune", action="store_true", help="Apply small per-note pitch errors")
    parser.add_argument("--tone", choices=("sine", "viola"), default="sine")
    parser.add_argument("--wav-only", action="store_true")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate all standard sine test_audio files",
    )
    parser.add_argument(
        "--rich-scales",
        action="store_true",
        help="Generate viola-like updown perfect + detuned scales",
    )
    args = parser.parse_args()

    if args.all:
        jobs = [
            (TEST_AUDIO / "synthetic_C_major_scale_perfect.mp3", "up", False),
            (TEST_AUDIO / "synthetic_C_major_scale_updown_perfect.mp3", "updown", False),
            (TEST_AUDIO / "synthetic_C_major_scale_updown_detuned.mp3", "updown", True),
        ]
        for path, mode, detune in jobs:
            generate_one(path, mode, args.note_sec, detune, args.wav_only, tone="sine")
        return

    if args.rich_scales:
        jobs = [
            (TEST_AUDIO / "synthetic_C_major_scale_updown_viola_perfect.mp3", "updown", False),
            (TEST_AUDIO / "synthetic_C_major_scale_updown_viola_detuned.mp3", "updown", True),
        ]
        for path, mode, detune in jobs:
            generate_one(path, mode, args.note_sec, detune, args.wav_only, tone="viola")
        return

    if args.output is None:
        if args.tone == "viola":
            suffix = "updown_viola_detuned" if args.detune else (
                "updown_viola_perfect" if args.mode == "updown" else "viola_perfect"
            )
        else:
            suffix = "updown_detuned" if args.detune else (
                "updown_perfect" if args.mode == "updown" else "perfect"
            )
        args.output = TEST_AUDIO / f"synthetic_C_major_scale_{suffix}.mp3"

    generate_one(args.output, args.mode, args.note_sec, args.detune, args.wav_only, tone=args.tone)


if __name__ == "__main__":
    main()