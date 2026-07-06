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
import kotlin.math.abs

private const val CENTS_SCALE_MAX = 50f
private const val GOOD_ZONE_CENTS = 10f

@Composable
fun CentsTraceCanvas(
    samples: List<PitchSample>,
    displayNowMs: Float,
    windowSec: Float,
    inTuneThreshold: Float,
    modifier: Modifier = Modifier,
) {
    Canvas(modifier = modifier.fillMaxSize()) {
        val w = size.width
        val h = size.height
        val gutter = 44f
        val plotLeft = gutter + 8f
        val plotRight = w - 12f
        val plotTop = 28f
        val plotBottom = h - 16f
        val midY = (plotTop + plotBottom) * 0.5f
        val scaleY = (plotBottom - plotTop) * 0.5f / CENTS_SCALE_MAX
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

        // Good zone ±10¢
        val goodOff = GOOD_ZONE_CENTS * scaleY
        drawRect(
            color = IntuneColors.GoodZone.copy(alpha = 0.12f),
            topLeft = Offset(plotLeft, midY - goodOff),
            size = androidx.compose.ui.geometry.Size(plotRight - plotLeft, goodOff * 2f),
        )
        drawLine(
            IntuneColors.GoodZone.copy(alpha = 0.4f),
            Offset(plotLeft, midY - goodOff),
            Offset(plotRight, midY - goodOff),
            strokeWidth = 1.2f,
        )
        drawLine(
            IntuneColors.GoodZone.copy(alpha = 0.4f),
            Offset(plotLeft, midY + goodOff),
            Offset(plotRight, midY + goodOff),
            strokeWidth = 1.2f,
        )

        // In-tune threshold band
        val tuneOff = inTuneThreshold * scaleY
        drawRect(
            color = IntuneColors.TuneMarker.copy(alpha = 0.14f),
            topLeft = Offset(plotLeft, midY - tuneOff),
            size = androidx.compose.ui.geometry.Size(plotRight - plotLeft, tuneOff * 2f),
        )

        // Zero line
        drawLine(
            IntuneColors.TextDim.copy(alpha = 0.35f),
            Offset(plotLeft, midY),
            Offset(plotRight, midY),
            strokeWidth = 1.4f,
        )

        // Scale ticks (left)
        val labels = listOf("+50", "+25", "+10", "0", "-10", "-25", "-50")
        val values = listOf(50f, 25f, 10f, 0f, -10f, -25f, -50f)
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

        // Trace
        if (samples.isNotEmpty()) {
            var lastCents = 0f
            val points = mutableListOf<Triple<Float, Float, androidx.compose.ui.graphics.Color>>()

            for (sample in samples) {
                val age = displayNowMs - sample.hostTsMs
                if (age < 0f || age > windowMs + 400f) continue
                val x = ageToX(age)
                val cents = if (sample.isRest) lastCents else sample.cents.also { lastCents = it }
                val y = centsToY(cents)
                val col = if (sample.isRest) {
                    IntuneColors.Rest.copy(alpha = 0.45f)
                } else {
                    IntuneColors.centsColor(cents, inTuneThreshold)
                }
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

            // Playhead (now)
            drawLine(
                IntuneColors.Playhead.copy(alpha = 0.85f),
                Offset(plotRight, plotTop),
                Offset(plotRight, plotBottom),
                strokeWidth = 2.5f,
            )
        }
    }
}