package com.analogintuition.intune

/**
 * Staff pitch mapping — diatonic Y_STEP model shared with visualizer_raylib.
 *
 * Screen layout uses **fixed staff geometry**: five lines always the same pixel
 * spacing; only clef / note→line mapping changes per instrument.
 */
object StaffPitch {
    const val Y_STEP = 0.4f
    /** Pitch span of one staff space (line to line) = two letter steps. */
    const val STAFF_SPACE = 2f * Y_STEP // 0.8f
    const val Y_REST = 0.8f
    const val Y_C3 = 1.2f

    enum class Instrument(
        val label: String,
        val pitchMin: Float,
        val pitchMax: Float,
        /** Five staff lines, low→high pitch (even spacing of STAFF_SPACE). */
        val staffLines: FloatArray,
        /** Pitch Y of the line the clef sits on. */
        val clefAnchor: Float,
        /** SMuFL clef glyph — null for viola (vertical "alto" label). */
        val clefSymbol: String? = null,
    ) {
        Viola(
            label = "Viola",
            pitchMin = 1.2f,
            pitchMax = 7.6f,
            staffLines = floatArrayOf(2.4f, 3.2f, 4.0f, 4.8f, 5.6f),
            clefAnchor = 4.0f,
            clefSymbol = null,
        ),
        Cello(
            label = "Cello",
            pitchMin = -1.6f,
            pitchMax = 4.0f,
            // Bass lines G2–A3 (was buggy 0.4 instead of 0.8)
            staffLines = floatArrayOf(0.0f, 0.8f, 1.6f, 2.4f, 3.2f),
            clefAnchor = 2.4f,
            clefSymbol = "\uD834\uDD22", // 𝄢 bass
        ),
        Violin(
            label = "Violin",
            pitchMin = 4.0f,
            pitchMax = 8.4f,
            staffLines = floatArrayOf(4.8f, 5.6f, 6.4f, 7.2f, 8.0f),
            clefAnchor = 5.6f,
            clefSymbol = "\uD834\uDD1E", // 𝄞 treble
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

    fun pitchYWithCents(note: String, cents: Float): Float {
        if (note == "---" || note == "REST" || note.isEmpty()) return Y_REST
        return pitchY(note) + (cents / 100f) * (Y_STEP * 0.5f)
    }

    /**
     * Fixed five-line staff layout in plot coordinates.
     * Line spacing is constant in pixels across instruments.
     */
    data class FixedStaff(
        val linesLowToHigh: FloatArray,
        val lineGapPx: Float,
        /** Screen Y of the lowest staff line (highest Y value). */
        val staffBottomY: Float,
        /** Screen Y of the highest staff line. */
        val staffTopY: Float,
        val bottomPitch: Float,
        val topPitch: Float,
    ) {
        fun pitchToScreenY(pitchY: Float): Float {
            // Higher pitch → toward top of screen (smaller Y)
            return staffBottomY - (pitchY - bottomPitch) / STAFF_SPACE * lineGapPx
        }

        /** Ledger pitches (line positions only) needed to support [pitchY]. */
        fun ledgerPitchesFor(pitchY: Float): List<Float> {
            val out = mutableListOf<Float>()
            if (pitchY > topPitch + 0.01f) {
                var y = topPitch + STAFF_SPACE
                while (y <= pitchY + 0.01f) {
                    out.add(y)
                    y += STAFF_SPACE
                }
            } else if (pitchY < bottomPitch - 0.01f) {
                var y = bottomPitch - STAFF_SPACE
                while (y >= pitchY - 0.01f) {
                    out.add(y)
                    y -= STAFF_SPACE
                }
            }
            return out
        }
    }

    /**
     * Build a staff with the same pixel line spacing for every instrument.
     * Staff block is vertically centered in [plotTop, plotBottom] with margin for ledgers.
     */
    fun fixedStaff(
        plotTop: Float,
        plotBottom: Float,
        instrument: Instrument,
    ): FixedStaff {
        val lines = instrument.staffLines.sortedArray()
        val avail = (plotBottom - plotTop).coerceAtLeast(40f)
        // Fill most of the chart: 4 line-gaps + ~0.4 space margin each side for ledgers.
        // No tight max — landscape has plenty of height; let line spacing scale with the panel.
        val lineGap = (avail / 4.8f).coerceIn(18f, 96f)
        val staffBlockH = 4f * lineGap
        val mid = (plotTop + plotBottom) * 0.5f
        val staffBottomY = mid + staffBlockH * 0.5f
        val staffTopY = mid - staffBlockH * 0.5f
        return FixedStaff(
            linesLowToHigh = lines,
            lineGapPx = lineGap,
            staffBottomY = staffBottomY,
            staffTopY = staffTopY,
            bottomPitch = lines.first(),
            topPitch = lines.last(),
        )
    }

    @Deprecated("Use fixedStaff().pitchToScreenY", ReplaceWith("fixedStaff(plotTop, plotBottom, instrument).pitchToScreenY(pitchY)"))
    fun pitchToScreenY(
        pitchY: Float,
        plotTop: Float,
        plotBottom: Float,
        instrument: Instrument,
    ): Float = fixedStaff(plotTop, plotBottom, instrument).pitchToScreenY(pitchY)
}
