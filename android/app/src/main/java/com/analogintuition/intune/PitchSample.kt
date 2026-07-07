package com.analogintuition.intune

data class PitchSample(
    val hostTsMs: Float,
    val deviceTsMs: Long,
    val note: String,
    val cents: Float,
    val confidence: Float,
    val level: Float,
    /** Continuous filtered pitch for display smoothing (NaN if unknown). */
    val pitchMidi: Float = Float.NaN,
) {
    val isRest: Boolean get() = note == "---" || note == "REST"
    val displayNote: String get() = if (isRest) "REST" else note
}

fun List<PitchSample>.nearestTo(targetMs: Float): PitchSample? =
    minByOrNull { kotlin.math.abs(it.hostTsMs - targetMs) }

object PitchCsvParser {
    private const val SAMPLE_INTERVAL_MS = 1000f / 120f

    fun parse(line: String): PitchSample? {
        val parts = line.split(',')
        if (parts.size < 3) return null
        val note = parts[1].trim()
        if (note.isEmpty()) return null
        val cents = parts[2].trim().toFloatOrNull() ?: return null
        val deviceTs = parts[0].trim().toLongOrNull() ?: 0L
        val conf = parts.getOrNull(3)?.trim()?.toFloatOrNull()?.let {
            if (it > 1f) it / 100f else it
        } ?: 0f
        val level = parts.getOrNull(4)?.trim()?.toFloatOrNull() ?: 0f
        return PitchSample(
            hostTsMs = 0f,
            deviceTsMs = deviceTs,
            note = note,
            cents = cents,
            confidence = conf.coerceIn(0f, 1f),
            level = level.coerceIn(0f, 1f),
        )
    }

    fun assignHostTimestamps(
        incoming: List<PitchSample>,
        hostNowMs: Float,
    ): List<PitchSample> {
        if (incoming.isEmpty()) return emptyList()
        return incoming.mapIndexed { idx, sample ->
            val offset = (incoming.size - 1 - idx) * SAMPLE_INTERVAL_MS
            sample.copy(hostTsMs = hostNowMs - offset)
        }
    }
}