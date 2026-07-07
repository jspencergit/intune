package com.analogintuition.intune

/**
 * Staff pitch mapping — aligned with visualizer_raylib (Y_STEP diatonic spaces).
 */
object StaffPitch {
    const val Y_STEP = 0.4f
    const val Y_REST = 0.8f
    const val Y_C3 = 1.2f

    enum class Instrument(
        val label: String,
        val pitchMin: Float,
        val pitchMax: Float,
        val staffLines: FloatArray,
        val clefSymbol: String,
    ) {
        Viola(
            label = "Viola",
            pitchMin = 1.2f,
            pitchMax = 7.6f,
            staffLines = floatArrayOf(2.4f, 3.2f, 4.0f, 4.8f, 5.6f),
            clefSymbol = "\uD834\uDD1F", // 𝄡 alto clef
        ),
        Cello(
            label = "Cello",
            pitchMin = -1.6f,
            pitchMax = 4.0f,
            staffLines = floatArrayOf(0.0f, 0.4f, 1.6f, 2.4f, 3.2f),
            clefSymbol = "\uD834\uDD22", // 𝄢 bass clef
        ),
        Violin(
            label = "Violin",
            pitchMin = 4.0f,
            pitchMax = 8.4f,
            staffLines = floatArrayOf(4.8f, 5.6f, 6.4f, 7.2f, 8.0f),
            clefSymbol = "\uD834\uDD1E", // 𝄞 treble clef
        ),
    }

    fun pitchY(note: String): Float {
        if (note.isEmpty() || note == "---" || note == "REST") return Y_REST
        val s = note.trim()
        val letter = s[0].uppercaseChar()
        var accidental = 0
        var i = 1
        if (i < s.length && s[i] == '#') {
            accidental = 1
            i++
        } else if (i < s.length && (s[i] == 'b' || s[i] == 'B')) {
            accidental = -1
            i++
        }

        var octave = 3
        for (j in s.indices.reversed()) {
            if (s[j].isDigit()) {
                octave = s[j].digitToInt()
                break
            }
        }

        val step = when (letter) {
            'C' -> 0
            'D' -> 1
            'E' -> 2
            'F' -> 3
            'G' -> 4
            'A' -> 5
            'B' -> 6
            else -> return 4.0f
        }

        var y = Y_C3 + (step + (octave - 3) * 7) * Y_STEP
        y += accidental * (Y_STEP * 0.5f)
        return y
    }

    /** Note height plus cents offset (100¢ = half a diatonic step on the staff). */
    fun pitchYWithCents(note: String, cents: Float): Float {
        if (note == "---" || note == "REST" || note.isEmpty()) return Y_REST
        return pitchY(note) + (cents / 100f) * (Y_STEP * 0.5f)
    }

    fun ledgerLines(instrument: Instrument): List<Float> {
        val lines = mutableListOf<Float>()
        var y = instrument.pitchMin
        while (y <= instrument.pitchMax + 0.001f) {
            val onStaff = instrument.staffLines.any { kotlin.math.abs(it - y) < 0.01f }
            if (!onStaff) lines.add(y)
            y += Y_STEP
        }
        return lines
    }

    fun pitchToScreenY(
        pitchY: Float,
        plotTop: Float,
        plotBottom: Float,
        instrument: Instrument,
    ): Float {
        val flipped = instrument.pitchMin + instrument.pitchMax - pitchY
        val yScale = (plotBottom - plotTop) / (instrument.pitchMax - instrument.pitchMin)
        return plotTop + (flipped - instrument.pitchMin) * yScale
    }
}