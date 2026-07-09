package com.analogintuition.intune

object StaffChartGeometry {
    const val GUTTER = 56f
    const val PLOT_LEFT_PAD = 4f
    /** Extra top inset so instrument name sits fully inside the panel (not clipped). */
    const val PLOT_TOP = 36f
    const val PLOT_BOTTOM_PAD = 16f

    fun plotLeft(): Float = GUTTER + PLOT_LEFT_PAD

    fun plotRight(width: Float): Float = width - CentsChartGeometry.PLOT_RIGHT_PAD

    fun plotBottom(height: Float): Float = height - PLOT_BOTTOM_PAD
}