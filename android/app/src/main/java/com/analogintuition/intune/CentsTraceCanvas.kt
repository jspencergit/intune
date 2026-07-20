package com.analogintuition.intune

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.unit.sp

@Composable
fun CentsTraceCanvas(
    samples: List<PitchSample>,
    displayNowMs: Float,
    windowSec: Float,
    inTuneThreshold: Float,
    /** Vertical half-range in cents (e.g. 50 → ±50). */
    centsScaleMax: Float = 100f,
    paused: Boolean = false,
    /** Absolute age of crosshair from live/pause edge (0 = newest). */
    scrubOffsetMs: Float = 0f,
    /** Age at the right edge of the view (pan into history when paused). */
    viewEndAgeMs: Float = 0f,
    modifier: Modifier = Modifier,
) {
    val scaleMax = centsScaleMax.coerceIn(25f, 100f)
    Canvas(modifier = modifier.fillMaxSize()) {
        val w = size.width
        val h = size.height
        val plotLeft = CentsChartGeometry.plotLeft()
        val plotRight = CentsChartGeometry.plotRight(w)
        val plotTop = CentsChartGeometry.PLOT_TOP
        val plotBottom = CentsChartGeometry.plotBottom(h)
        val midY = (plotTop + plotBottom) * 0.5f
        val scaleY = (plotBottom - plotTop) * 0.5f / scaleMax
        val windowMs = windowSec * 1000f
        val viewEnd = viewEndAgeMs.coerceAtLeast(0f)

        fun centsToY(cents: Float) = midY - cents * scaleY
        /** [relAgeMs] = 0 at right edge of view, windowMs at left. */
        fun relAgeToX(relAgeMs: Float): Float {
            val t = (relAgeMs / windowMs).coerceIn(0f, 1f)
            return plotRight - t * (plotRight - plotLeft)
        }

        drawRect(IntuneColors.Panel, topLeft = Offset(0f, 0f), size = size)
        drawRect(
            IntuneColors.PanelBorder.copy(alpha = 0.35f),
            topLeft = Offset(0f, 0f),
            size = size,
            style = Stroke(width = 1.5f),
        )

        // Clip in-tune band drawing to plot so a wide zone still looks OK.
        val tuneOff = (inTuneThreshold * scaleY).coerceAtMost((plotBottom - plotTop) * 0.5f)
        drawRect(
            color = IntuneColors.TuneMarker.copy(alpha = 0.16f),
            topLeft = Offset(plotLeft, midY - tuneOff),
            size = androidx.compose.ui.geometry.Size(plotRight - plotLeft, tuneOff * 2f),
        )
        drawLine(
            IntuneColors.TuneMarker.copy(alpha = 0.55f),
            Offset(plotLeft, midY - tuneOff),
            Offset(plotRight, midY - tuneOff),
            strokeWidth = 1.4f,
        )
        drawLine(
            IntuneColors.TuneMarker.copy(alpha = 0.55f),
            Offset(plotLeft, midY + tuneOff),
            Offset(plotRight, midY + tuneOff),
            strokeWidth = 1.4f,
        )

        drawLine(
            IntuneColors.TextDim.copy(alpha = 0.35f),
            Offset(plotLeft, midY),
            Offset(plotRight, midY),
            strokeWidth = 1.4f,
        )

        val values = when {
            scaleMax >= 75f -> listOf(100f, 50f, 0f, -50f, -100f)
            scaleMax >= 40f -> listOf(50f, 25f, 0f, -25f, -50f)
            else -> listOf(25f, 10f, 0f, -10f, -25f)
        }
        val labels = values.map { c ->
            when {
                c > 0f -> "+${c.toInt()}"
                c < 0f -> "${c.toInt()}"
                else -> "0"
            }
        }
        val paint = android.graphics.Paint().apply {
            color = android.graphics.Color.argb(160, 90, 100, 112)
            textSize = 11.sp.toPx()
            isAntiAlias = true
        }
        values.zip(labels).forEach { (cents, label) ->
            val y = centsToY(cents)
            drawLine(
                IntuneColors.TextDim.copy(alpha = 0.3f),
                Offset(plotLeft - 8f, y),
                Offset(plotLeft, y),
                strokeWidth = 1f,
            )
            drawContext.canvas.nativeCanvas.drawText(label, 4f, y + 4f, paint)
        }

        // Cents already shaped by ResponseDisplayMapper (Steady/Live). Skip settling
        // samples so bow attacks leave a short gap instead of a red spike.
        data class Pt(val x: Float, val y: Float, val col: androidx.compose.ui.graphics.Color, val seg: Int)
        val points = mutableListOf<Pt>()
        var segment = 0

        if (samples.isNotEmpty()) {
            val ordered = samples.sortedBy { it.hostTsMs }
            var prevWasDrawn = false
            for (sample in ordered) {
                val age = displayNowMs - sample.hostTsMs
                val rel = age - viewEnd
                if (rel < -50f || rel > windowMs + 50f) continue
                if (sample.isRest || sample.isSettling) {
                    if (prevWasDrawn) {
                        segment++
                        prevWasDrawn = false
                    }
                    continue
                }
                val x = relAgeToX(rel)
                val cents = sample.cents.coerceIn(-scaleMax, scaleMax)
                val y = centsToY(cents)
                val col = IntuneColors.centsColor(cents, inTuneThreshold)
                points.add(Pt(x, y, col, segment))
                prevWasDrawn = true
            }

            for (i in 1 until points.size) {
                val a = points[i - 1]
                val b = points[i]
                if (a.seg != b.seg) continue
                drawLine(
                    color = b.col.copy(alpha = 0.25f),
                    start = Offset(a.x, a.y),
                    end = Offset(b.x, b.y),
                    strokeWidth = 7f,
                    cap = StrokeCap.Round,
                )
                drawLine(
                    color = b.col,
                    start = Offset(a.x, a.y),
                    end = Offset(b.x, b.y),
                    strokeWidth = 3f,
                    cap = StrokeCap.Round,
                )
            }
        }

        val cursorX = if (paused) {
            ChartScrubGeometry.scrubOffsetToX(
                (scrubOffsetMs - viewEnd).coerceIn(0f, windowMs),
                w, windowMs, plotLeft, plotRight,
            )
        } else {
            plotRight
        }

        drawLine(
            IntuneColors.Playhead.copy(alpha = if (paused) 0.95f else 0.85f),
            Offset(cursorX, plotTop),
            Offset(cursorX, plotBottom),
            strokeWidth = if (paused) 3f else 2.5f,
        )
        if (paused) {
            drawLine(
                IntuneColors.Playhead.copy(alpha = 0.15f),
                Offset(cursorX, plotTop),
                Offset(cursorX, plotBottom),
                strokeWidth = 10f,
            )
        }

        if (paused && samples.isNotEmpty()) {
            val inspectMs = displayNowMs - scrubOffsetMs
            val inspect = samples.nearestTo(inspectMs)
            if (inspect != null && !inspect.isRest) {
                val inspectRel = (displayNowMs - inspect.hostTsMs) - viewEnd
                if (inspectRel in -20f..windowMs + 20f) {
                    val inspectCents = inspect.cents
                    val dotY = centsToY(inspectCents.coerceIn(-scaleMax, scaleMax))
                    val dotCol = when {
                        inspect.isSettling -> IntuneColors.TextDim
                        else -> IntuneColors.centsColor(inspectCents, inTuneThreshold)
                    }
                    drawCircle(
                        color = dotCol.copy(alpha = 0.22f),
                        radius = 11f,
                        center = Offset(cursorX, dotY),
                    )
                    drawCircle(
                        color = dotCol,
                        radius = 6f,
                        center = Offset(cursorX, dotY),
                    )
                }
            }
        }
    }
}