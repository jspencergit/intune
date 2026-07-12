package com.analogintuition.intune

import kotlin.math.abs
import kotlin.math.ln
import kotlin.math.pow
import kotlin.math.roundToInt

/**
 * Concert-A reference for display labels.
 *
 * Teensy streams note/cents relative to A4 = [STREAM_A_HZ] (440).
 * The app remaps to the user's concert A without changing firmware.
 */
object ConcertPitch {
    /** Reference baked into Teensy / CSV labels today. */
    const val STREAM_A_HZ = 440f

    /** Default for practice (teacher preference over 440). */
    const val DEFAULT_A_HZ = 441f

    const val MIN_A_HZ = 415f
    const val MAX_A_HZ = 446f

    private val NOTE_TO_SEMITONE = mapOf(
        "C" to 0, "C#" to 1, "Db" to 1,
        "D" to 2, "D#" to 3, "Eb" to 3,
        "E" to 4,
        "F" to 5, "F#" to 6, "Gb" to 6,
        "G" to 7, "G#" to 8, "Ab" to 8,
        "A" to 9, "A#" to 10, "Bb" to 10,
        "B" to 11,
    )

    private val SEMITONE_TO_NAME = arrayOf(
        "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
    )

    /**
     * Re-label a stream sample (assumed relative to [STREAM_A_HZ]) for [displayAHz].
     * Rests pass through unchanged.
     */
    fun remapSample(sample: PitchSample, displayAHz: Float): PitchSample {
        if (sample.isRest) return sample
        if (abs(displayAHz - STREAM_A_HZ) < 0.05f) return sample

        val midi = parseNoteToMidi(sample.note) ?: return sample
        val midiFloatStream = midi + sample.cents / 100f
        val freqHz = STREAM_A_HZ *
            2.0.pow(((midiFloatStream - 69.0) / 12.0)).toFloat()

        val midiFloatDisplay =
            (12.0 * (ln((freqHz / displayAHz).toDouble()) / ln(2.0)) + 69.0).toFloat()
        val nearest = midiFloatDisplay.roundToInt().coerceIn(0, 127)
        val cents = (midiFloatDisplay - nearest) * 100f
        return sample.copy(
            note = midiToNoteName(nearest),
            cents = cents,
        )
    }

    fun remapSamples(samples: List<PitchSample>, displayAHz: Float): List<PitchSample> {
        if (abs(displayAHz - STREAM_A_HZ) < 0.05f) return samples
        return samples.map { remapSample(it, displayAHz) }
    }

    fun parseNoteToMidi(note: String): Int? {
        val s = note.trim()
        if (s.isEmpty() || s == "---" || s.equals("REST", ignoreCase = true)) return null
        val letter = s[0].uppercaseChar()
        var i = 1
        var accidental = ""
        if (i < s.length && s[i] == '#') {
            accidental = "#"
            i++
        } else if (i < s.length && (s[i] == 'b' || s[i] == 'B')) {
            accidental = "b"
            i++
        }
        val semitone = NOTE_TO_SEMITONE["$letter$accidental"] ?: return null
        var octave = 3
        for (j in s.indices.reversed()) {
            if (s[j].isDigit()) {
                octave = s[j].digitToInt()
                break
            }
        }
        return (octave + 1) * 12 + semitone
    }

    fun midiToNoteName(midi: Int): String {
        val m = midi.coerceIn(0, 127)
        val octave = m / 12 - 1
        val name = SEMITONE_TO_NAME[((m % 12) + 12) % 12]
        return "$name$octave"
    }
}
