package com.analogintuition.intune

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.sign

/**
 * Bandwidth-limited cents for the scroll trace.
 *
 * Pitch detectors often put short overshoot/undershoot spikes on note attacks
 * (high-frequency content on top of the intended “square” detune steps). This
 * pipeline kills that HF junk while keeping intentional plateaus readable:
 *
 *  1. Short **median** — rejects 1–2 sample impulses
 *  2. **Slew limit** — caps ¢/sample so a spike cannot jump the full height
 *  3. **1-pole low-pass** — rolls off remaining HF (bandwidth limit)
 *
 * Causal and deterministic when replayed oldest→newest (pause scrub uses the same path).
 */
class CentsDisplaySmoother(
    /** Odd window for impulse rejection. 3 ≈ 25 ms at 120 Hz — light spike kill only. */
    private val medianWindow: Int = 3,
    /**
     * Low-pass time constant in milliseconds (at nominal 120 Hz).
     * Lower = more HF through / snappier edges. ~55–70 ms is mild roll-off.
     */
    private val tauMs: Float = 60f,
    /** Max cents change per sample after median (~120 Hz). Higher = less slew clamping. */
    private val maxStepCents: Float = 8f,
    private val sampleHz: Float = 120f,
) {
    private val ring = FloatArray(medianWindow.coerceAtLeast(1)) { Float.NaN }
    private var ringCount = 0
    private var ema: Float? = null

    private val alpha: Float = run {
        val dt = 1000f / sampleHz
        val a = 1f - exp(-dt / tauMs.coerceAtLeast(1f))
        a.coerceIn(0.02f, 0.5f)
    }

    fun reset() {
        ring.fill(Float.NaN)
        ringCount = 0
        ema = null
    }

    fun next(sample: PitchSample): Float? {
        if (sample.isRest) {
            reset()
            return null
        }
        return nextCents(sample.cents)
    }

    fun nextCents(rawCents: Float): Float {
        push(rawCents)
        val med = medianOr(rawCents)

        val prev = ema
        if (prev == null) {
            ema = med
            return med
        }

        // Slew-limit the input to the LPF so single-frame spikes never fully enter.
        val delta = (med - prev).let { d ->
            if (abs(d) > maxStepCents) sign(d) * maxStepCents else d
        }
        val limited = prev + delta
        val smoothed = prev + alpha * (limited - prev)
        ema = smoothed
        return smoothed
    }

    private fun push(value: Float) {
        if (ringCount < ring.size) {
            ring[ringCount++] = value
        } else {
            for (i in 0 until ring.size - 1) ring[i] = ring[i + 1]
            ring[ring.size - 1] = value
        }
    }

    private fun medianOr(fallback: Float): Float {
        if (ringCount == 0) return fallback
        val sorted = ring.copyOfRange(0, ringCount).apply { sort() }
        return sorted[sorted.size / 2]
    }
}
