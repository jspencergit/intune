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
    centsScaleMax: Float = 50f,
    paused: Boolean = false,
    scrubOffsetMs: Float = 0f,
    modifier: Modifier = Modifier,
) {
    val scaleMax = centsScaleMax.coerceIn(25f, 50f)
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

        fun centsToY(cents: Float) = midY - cents * scaleY
        fun ageToX(ageMs: Float): Float {
            val t = (ageMs / windowMs).coerceIn(0f, 1f)
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
            scaleMax >= 45f -> listOf(50f, 25f, 0f, -25f, -50f)
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

        val points = mutableListOf<Triple<Float, Float, androidx.compose.ui.graphics.Color>>()
        val smoother = CentsDisplaySmoother()

        if (samples.isNotEmpty()) {
            val ordered = samples.sortedBy { it.hostTsMs }
            for (sample in ordered) {
                val age = displayNowMs - sample.hostTsMs
                if (age < 0f) continue

                val smoothCents = smoother.next(sample)
                if (age > windowMs + 400f || smoothCents == null) continue

                val x = ageToX(age)
                val cents = smoothCents.coerceIn(-scaleMax, scaleMax)
                val y = centsToY(cents)
                val col = IntuneColors.centsColor(cents, inTuneThreshold)
                points.add(Triple(x, y, col))
            }

            for (i in 1 until points.size) {
                val (x0, y0, _) = points[i - 1]
                val (x1, y1, c1) = points[i]
                drawLine(
                    color = c1.copy(alpha = 0.25f),
                    start = Offset(x0, y0),
                    end = Offset(x1, y1),
                    strokeWidth = 7f,
                    cap = StrokeCap.Round,
                )
                drawLine(
                    color = c1,
                    start = Offset(x0, y0),
                    end = Offset(x1, y1),
                    strokeWidth = 3f,
                    cap = StrokeCap.Round,
                )
            }
        }

        val cursorX = if (paused) {
            ChartScrubGeometry.scrubOffsetToX(
                scrubOffsetMs, w, windowMs, plotLeft, plotRight,
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
            if (inspect != null) {
                val inspectAge = displayNowMs - inspect.hostTsMs
                if (inspectAge in 0f..windowMs + 400f) {
                    val replay = CentsDisplaySmoother()
                    var inspectCents = 0f
                    for (sample in samples.sortedBy { it.hostTsMs }) {
                        if (sample.hostTsMs > inspect.hostTsMs) break
                        replay.next(sample)?.let { inspectCents = it }
                    }
                    val dotY = centsToY(inspectCents.coerceIn(-scaleMax, scaleMax))
                    val dotCol = if (inspect.isRest) {
                        IntuneColors.Rest
                    } else {
                        IntuneColors.centsColor(inspectCents, inTuneThreshold)
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