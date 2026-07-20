package com.analogintuition.intune

/**
 * Display-only rewrite of the pitch stream for [ResponseMode].
 *
 * Does not change BLE ingest or the Teensy detector. Walks samples in time order so
 * pause scrub and live header share the same Steady/Live behavior.
 *
 * **Steady**
 * - After rest→note or note change, mark ~[SETTLE_MS] as [PitchSample.isSettling]
 * - Stronger cents smoother (median + slew + LPF)
 * - During settle, hold last non-settling display cents so the cents chart does not spike
 *
 * **Live**
 * - Light smoother only (same character as the original cents chart pipeline)
 */
object ResponseDisplayMapper {

    /** How long after a note change Steady treats the pitch as “settling”. */
    const val STEADY_SETTLE_MS = 100f

    fun map(samples: List<PitchSample>, mode: ResponseMode): List<PitchSample> {
        if (samples.isEmpty()) return samples
        return when (mode) {
            ResponseMode.Live -> mapWithSmoother(samples, liveSmoother(), settleMs = 0f)
            ResponseMode.Steady -> mapWithSmoother(samples, steadySmoother(), settleMs = STEADY_SETTLE_MS)
        }
    }

    fun liveSmoother(): CentsDisplaySmoother = CentsDisplaySmoother(
        medianWindow = 3,
        tauMs = 60f,
        maxStepCents = 8f,
    )

    fun steadySmoother(): CentsDisplaySmoother = CentsDisplaySmoother(
        medianWindow = 5,
        tauMs = 120f,
        maxStepCents = 4f,
    )

    private fun mapWithSmoother(
        samples: List<PitchSample>,
        smoother: CentsDisplaySmoother,
        settleMs: Float,
    ): List<PitchSample> {
        smoother.reset()
        val ordered = samples.sortedBy { it.hostTsMs }
        var lastNote = ""
        var settleUntilMs = Float.NEGATIVE_INFINITY
        var lastDisplayCents: Float? = null
        val out = ArrayList<PitchSample>(ordered.size)

        for (sample in ordered) {
            if (sample.isRest) {
                smoother.reset()
                lastNote = ""
                settleUntilMs = Float.NEGATIVE_INFINITY
                lastDisplayCents = null
                out.add(sample.copy(isSettling = false))
                continue
            }

            if (sample.note != lastNote) {
                lastNote = sample.note
                if (settleMs > 0f) {
                    settleUntilMs = sample.hostTsMs + settleMs
                    // Fresh note body after settle — don't drag prior note's LPF state.
                    smoother.reset()
                }
            }

            val settling = settleMs > 0f && sample.hostTsMs < settleUntilMs
            if (settling) {
                // Hold last good cents for continuous charts; header uses isSettling.
                val held = lastDisplayCents ?: sample.cents
                out.add(
                    sample.copy(
                        cents = held,
                        isSettling = true,
                    ),
                )
                continue
            }

            val smooth = smoother.nextCents(sample.cents)
            lastDisplayCents = smooth
            out.add(
                sample.copy(
                    cents = smooth,
                    isSettling = false,
                ),
            )
        }
        return out
    }
}
