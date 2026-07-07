package com.analogintuition.intune

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke

/**
 * Vector clef glyphs — Android system fonts often misrender Unicode SMuFL clefs
 * (e.g. viola shows treble + 8 instead of alto).
 */
object ClefDrawer {
    fun draw(
        scope: DrawScope,
        instrument: StaffPitch.Instrument,
        center: Offset,
        staffSpacePx: Float,
        color: Color,
    ) {
        when (instrument) {
            StaffPitch.Instrument.Viola -> scope.drawAltoClef(center, staffSpacePx, color)
            StaffPitch.Instrument.Cello -> scope.drawBassClef(center, staffSpacePx, color)
            StaffPitch.Instrument.Violin -> scope.drawTrebleClef(center, staffSpacePx, color)
        }
    }

    /** Alto (C) clef — centered on the middle staff line (C4 on viola). */
    private fun DrawScope.drawAltoClef(center: Offset, sp: Float, color: Color) {
        val stroke = Stroke(width = 2.4f, cap = StrokeCap.Round, join = StrokeJoin.Round)
        val cx = center.x
        val cy = center.y

        val path = Path().apply {
            moveTo(cx + sp * 0.2f, cy - sp * 2.4f)
            cubicTo(
                cx - sp * 1.35f, cy - sp * 1.6f,
                cx - sp * 1.35f, cy - sp * 0.35f,
                cx + sp * 0.05f, cy,
            )
            cubicTo(
                cx - sp * 1.35f, cy + sp * 0.35f,
                cx - sp * 1.35f, cy + sp * 1.6f,
                cx + sp * 0.2f, cy + sp * 2.4f,
            )
        }
        drawPath(path, color, style = stroke)

        val curl = Path().apply {
            moveTo(cx + sp * 0.55f, cy - sp * 0.55f)
            cubicTo(
                cx + sp * 0.05f, cy - sp * 0.15f,
                cx + sp * 0.05f, cy + sp * 0.15f,
                cx + sp * 0.55f, cy + sp * 0.55f,
            )
        }
        drawPath(curl, color, style = stroke)
    }

    /** Bass (F) clef — dots bracket the F line (second line from top). */
    private fun DrawScope.drawBassClef(center: Offset, sp: Float, color: Color) {
        val stroke = Stroke(width = 2.4f, cap = StrokeCap.Round, join = StrokeJoin.Round)
        val cx = center.x
        val cy = center.y

        val path = Path().apply {
            moveTo(cx + sp * 0.35f, cy - sp * 1.1f)
            cubicTo(
                cx - sp * 0.9f, cy - sp * 1.8f,
                cx - sp * 1.1f, cy,
                cx - sp * 0.2f, cy + sp * 1.9f,
            )
            cubicTo(
                cx + sp * 0.5f, cy + sp * 0.8f,
                cx + sp * 0.9f, cy - sp * 0.2f,
                cx + sp * 0.35f, cy - sp * 1.1f,
            )
        }
        drawPath(path, color, style = stroke)

        val dotR = sp * 0.17f
        drawCircle(color, dotR, Offset(cx + sp * 0.55f, cy - sp * 0.55f))
        drawCircle(color, dotR, Offset(cx + sp * 0.55f, cy + sp * 0.55f))
    }

    /** Treble (G) clef — curl around the G line (second line from bottom). */
    private fun DrawScope.drawTrebleClef(center: Offset, sp: Float, color: Color) {
        val stroke = Stroke(width = 2.4f, cap = StrokeCap.Round, join = StrokeJoin.Round)
        val cx = center.x
        val cy = center.y

        val path = Path().apply {
            moveTo(cx - sp * 0.15f, cy + sp * 2.0f)
            cubicTo(
                cx - sp * 1.3f, cy + sp * 1.0f,
                cx - sp * 0.9f, cy - sp * 1.6f,
                cx + sp * 0.35f, cy - sp * 1.0f,
            )
            cubicTo(
                cx + sp * 1.0f, cy - sp * 0.55f,
                cx + sp * 0.55f, cy + sp * 0.9f,
                cx - sp * 0.05f, cy + sp * 1.2f,
            )
            cubicTo(
                cx - sp * 0.55f, cy + sp * 1.45f,
                cx - sp * 0.35f, cy + sp * 2.0f,
                cx - sp * 0.15f, cy + sp * 2.0f,
            )
        }
        drawPath(path, color, style = stroke)
    }
}