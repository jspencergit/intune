package com.analogintuition.intune

import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Ingest filter: median + EMA on MIDI for spike rejection and staff/header pitch.
 * Cents and note pass through from the detector — the cents trace does its own moving average.
 */
class PitchStreamFilter(
    private val windowSize: Int = 7,
    private val outlierSemitones: Float = 3.5f,
    private val emaAlpha: Float = 0.28f,
) {
    private val ring = FloatArray(windowSize) { Float.NaN }
    private var ringCount = 0
    private var emaMidi: Float? = null
    private var lastNote = ""
    private var lastCents = 0f

    fun reset() {
        ring.fill(Float.NaN)
        ringCount = 0
        emaMidi = null
        lastNote = ""
        lastCents = 0f
    }

    fun filter(samples: List<PitchSample>): List<PitchSample> =
        samples.map { filterOne(it) }

    private fun filterOne(sample: PitchSample): PitchSample {
        if (sample.isRest) {
            reset()
            return sample
        }

        val rawMidi = noteCentsToMidiFloat(sample.note, sample.cents) ?: return sample

        if (emaMidi != null && abs(rawMidi - emaMidi!!) > outlierSemitones) {
            return sample.copy(
                note = lastNote.ifEmpty { sample.note },
                cents = lastCents,
                pitchMidi = emaMidi!!,
            )
        }

        pushRing(rawMidi)
        val median = ringMedian() ?: rawMidi
        emaMidi = if (emaMidi == null) {
            median
        } else {
            emaMidi!! + emaAlpha * (median - emaMidi!!)
        }

        lastNote = sample.note
        lastCents = sample.cents
        return sample.copy(pitchMidi = emaMidi!!)
    }

    private fun pushRing(value: Float) {
        if (ringCount < windowSize) {
            ring[ringCount++] = value
        } else {
            for (i in 0 until windowSize - 1) ring[i] = ring[i + 1]
            ring[windowSize - 1] = value
        }
    }

    private fun ringMedian(): Float? {
        if (ringCount == 0) return null
        val slice = ring.copyOfRange(0, ringCount).sorted()
        return slice[slice.size / 2]
    }

    companion object {
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

        fun noteCentsToMidiFloat(note: String, cents: Float): Float? {
            val midi = parseNoteToMidi(note) ?: return null
            return midi + cents / 100f
        }

        fun midiFloatToNoteCents(midiFloat: Float): Pair<String, Float> {
            val nearest = midiFloat.roundToInt()
            val cents = (midiFloat - nearest) * 100f
            return midiToNoteName(nearest) to cents
        }

        private fun parseNoteToMidi(note: String): Int? {
            val s = note.trim()
            if (s.isEmpty()) return null
            val letter = s[0].uppercaseChar()
            var accidental = ""
            var i = 1
            if (i < s.length && s[i] == '#') {
                accidental = "#"
                i++
            } else if (i < s.length && (s[i] == 'b' || s[i] == 'B')) {
                accidental = "b"
                i++
            }
            val key = "$letter$accidental"
            val semitone = NOTE_TO_SEMITONE[key] ?: return null
            var octave = 3
            for (j in s.indices.reversed()) {
                if (s[j].isDigit()) {
                    octave = s[j].digitToInt()
                    break
                }
            }
            return (octave + 1) * 12 + semitone
        }

        private fun midiToNoteName(midi: Int): String {
            val octave = midi / 12 - 1
            val name = SEMITONE_TO_NAME[((midi % 12) + 12) % 12]
            return "$name$octave"
        }
    }
}