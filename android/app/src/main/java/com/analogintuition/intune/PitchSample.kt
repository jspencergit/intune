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
    /**
     * Display-only: true during Steady-mode attack/transition window.
     * Not set by BLE parse — applied by [ResponseDisplayMapper].
     */
    val isSettling: Boolean = false,
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

    /**
     * Stamp [hostTsMs] so the newest sample lands at [hostNowMs].
     * Prefer Teensy device-time deltas within the batch (real ms gaps); fall back
     * to 120 Hz index spacing if device clocks are missing or non-monotonic.
     */
    fun assignHostTimestamps(
        incoming: List<PitchSample>,
        hostNowMs: Float,
    ): List<PitchSample> {
        if (incoming.isEmpty()) return emptyList()
        val last = incoming.last()
        val lastDev = last.deviceTsMs
        val deviceOk = incoming.all { it.deviceTsMs > 0L } &&
            incoming.zipWithNext().all { (a, b) ->
                b.deviceTsMs >= a.deviceTsMs && (b.deviceTsMs - a.deviceTsMs) <= 500L
            }
        return if (deviceOk) {
            incoming.map { sample ->
                val ageMs = (lastDev - sample.deviceTsMs).toFloat().coerceIn(0f, 10_000f)
                sample.copy(hostTsMs = hostNowMs - ageMs)
            }
        } else {
            incoming.mapIndexed { idx, sample ->
                val offset = (incoming.size - 1 - idx) * SAMPLE_INTERVAL_MS
                sample.copy(hostTsMs = hostNowMs - offset)
            }
        }
    }

    /** Wall-clock span covered by samples (ms), using host and device clocks. */
    fun historySpanMs(samples: List<PitchSample>): Float {
        if (samples.isEmpty()) return 0f
        val hostSpan = samples.maxOf { it.hostTsMs } - samples.minOf { it.hostTsMs }
        val devSpan = if (samples.any { it.deviceTsMs > 0L }) {
            (samples.maxOf { it.deviceTsMs } - samples.minOf { it.deviceTsMs }).toFloat()
        } else {
            0f
        }
        // Host is primary (aligned to app clock); device is a floor if host collapsed.
        return maxOf(hostSpan, devSpan, 0f)
    }
}