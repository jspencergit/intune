package com.analogintuition.intune

object CentsChartGeometry {
    const val GUTTER = 44f
    const val PLOT_LEFT_PAD = 8f
    const val PLOT_RIGHT_PAD = 12f
    const val PLOT_TOP = 28f
    const val PLOT_BOTTOM_PAD = 16f

    fun plotLeft(): Float = GUTTER + PLOT_LEFT_PAD

    fun plotRight(width: Float): Float = width - PLOT_RIGHT_PAD

    fun plotBottom(height: Float): Float = height - PLOT_BOTTOM_PAD

    fun xToScrubOffsetMs(x: Float, width: Float, windowMs: Float): Float =
        ChartScrubGeometry.xToScrubOffsetMs(x, width, windowMs, plotLeft(), plotRight(width))

    fun scrubOffsetToX(offsetMs: Float, width: Float, windowMs: Float): Float =
        ChartScrubGeometry.scrubOffsetToX(offsetMs, width, windowMs, plotLeft(), plotRight(width))
}

object ChartScrubGeometry {
    fun xToScrubOffsetMs(
        x: Float,
        width: Float,
        windowMs: Float,
        plotLeft: Float,
        plotRight: Float,
    ): Float {
        if (plotRight <= plotLeft) return 0f
        val t = ((plotRight - x) / (plotRight - plotLeft)).coerceIn(0f, 1f)
        return t * windowMs
    }

    fun scrubOffsetToX(
        offsetMs: Float,
        width: Float,
        windowMs: Float,
        plotLeft: Float,
        plotRight: Float,
    ): Float {
        if (plotRight <= plotLeft || windowMs <= 0f) return plotRight
        val t = (offsetMs / windowMs).coerceIn(0f, 1f)
        return plotRight - t * (plotRight - plotLeft)
    }
}