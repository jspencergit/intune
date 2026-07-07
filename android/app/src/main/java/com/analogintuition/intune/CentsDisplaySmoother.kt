package com.analogintuition.intune

/**
 * Causal moving average on the cents stream for the scroll trace.
 * Note changes are ignored — +10 wobbling into a new note at -10 just ramps through the average.
 */
class CentsDisplaySmoother(
    private val windowSize: Int = 8,
) {
    private val ring = FloatArray(windowSize) { Float.NaN }
    private var count = 0

    fun reset() {
        ring.fill(Float.NaN)
        count = 0
    }

    fun next(sample: PitchSample): Float? {
        if (sample.isRest) {
            reset()
            return null
        }

        if (count < windowSize) {
            ring[count++] = sample.cents
        } else {
            for (i in 0 until windowSize - 1) ring[i] = ring[i + 1]
            ring[windowSize - 1] = sample.cents
        }

        var sum = 0f
        var n = 0
        for (i in 0 until count) {
            if (!ring[i].isNaN()) {
                sum += ring[i]
                n++
            }
        }
        return if (n == 0) sample.cents else sum / n
    }
}