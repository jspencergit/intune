package com.analogintuition.intune

import androidx.compose.ui.graphics.Color

/** Light Grey palette — aligned with visualizer_raylib default theme. */
object IntuneColors {
    val Background = Color(0xFFEEF0F2)
    val Panel = Color(0xFFE4E8EC)
    val PanelBorder = Color(0xFFA8B0B8)
    val TextPrimary = Color(0xFF181E24)
    val TextDim = Color(0xFF5A6470)
    val InTune = Color(0xFF188A44)
    val Sharp = Color(0xFFC8342C)
    val Flat = Color(0xFF1A78B8)
    val Rest = Color(0xFFB0B8C0)
    val GoodZone = Color(0xFF78B890)
    val TuneMarker = Color(0xFF389860)
    val Playhead = Color(0xFF2A70B8)
    val Accent = Color(0xFF2A70B8)
    /** Text/icons on solid Accent buttons */
    val OnAccent = Color(0xFFFFFFFF)

    // Manuscript-style staff (warmer than UI chrome)
    val StaffPaper = Color(0xFFF7F1E4)
    val StaffPaperEdge = Color(0xFFD8CFC0)
    val StaffLine = Color(0xFF2C3340)
    val StaffLedger = Color(0xFF6A7380)
    val StaffGutter = Color(0xFFEDE6D8)

    fun centsColor(cents: Float, inTuneThreshold: Float): Color {
        if (kotlin.math.abs(cents) < inTuneThreshold) return InTune
        return if (cents > 0f) Sharp else Flat
    }
}