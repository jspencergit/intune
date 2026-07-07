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
fun StaffTraceCanvas(
    samples: List<PitchSample>,
    displayNowMs: Float,
    windowSec: Float,
    inTuneThreshold: Float,
    instrument: StaffPitch.Instrument = StaffPitch.Instrument.Viola,
    paused: Boolean = false,
    scrubOffsetMs: Float = 0f,
    modifier: Modifier = Modifier,
) {
    Canvas(modifier = modifier.fillMaxSize()) {
        val w = size.width
        val h = size.height
        val plotLeft = StaffChartGeometry.plotLeft()
        val plotRight = StaffChartGeometry.plotRight(w)
        val plotTop = StaffChartGeometry.PLOT_TOP
        val plotBottom = StaffChartGeometry.plotBottom(h)
        val windowMs = windowSec * 1000f

        fun pitchToY(pitchY: Float): Float =
            StaffPitch.pitchToScreenY(pitchY, plotTop, plotBottom, instrument)

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

        val clefPaint = android.graphics.Paint().apply {
            color = android.graphics.Color.argb(210, 58, 68, 80)
            isAntiAlias = true
        }
        val clefAnchorY = pitchToY(instrument.clefAnchor)
        val nativeCanvas = drawContext.canvas.nativeCanvas
        if (instrument.clefSymbol != null) {
            clefPaint.textSize = 34.sp.toPx()
            nativeCanvas.drawText(
                instrument.clefSymbol,
                6f,
                clefAnchorY + clefPaint.textSize * 0.32f,
                clefPaint,
            )
        } else {
            clefPaint.textSize = 11.sp.toPx()
            clefPaint.typeface = android.graphics.Typeface.create(
                android.graphics.Typeface.DEFAULT,
                android.graphics.Typeface.BOLD,
            )
            drawVerticalClefLabel(
                canvas = nativeCanvas,
                text = "alto",
                centerX = StaffChartGeometry.GUTTER * 0.42f,
                centerY = clefAnchorY,
                paint = clefPaint,
            )
        }

        val labelPaint = android.graphics.Paint().apply {
            color = android.graphics.Color.argb(140, 90, 100, 112)
            textSize = 10.sp.toPx()
            isAntiAlias = true
        }
        drawContext.canvas.nativeCanvas.drawText(
            instrument.label,
            6f,
            plotTop - 6f,
            labelPaint,
        )

        for (ledger in StaffPitch.ledgerLines(instrument)) {
            val y = pitchToY(ledger)
            drawLine(
                IntuneColors.TextDim.copy(alpha = 0.22f),
                Offset(plotLeft, y),
                Offset(plotRight, y),
                strokeWidth = 1f,
            )
        }

        for (line in instrument.staffLines) {
            val y = pitchToY(line)
            drawLine(
                IntuneColors.TextPrimary.copy(alpha = 0.55f),
                Offset(plotLeft, y),
                Offset(plotRight, y),
                strokeWidth = 1.6f,
            )
        }

        var lastPitchY = StaffPitch.Y_REST
        val points = mutableListOf<Triple<Float, Float, androidx.compose.ui.graphics.Color>>()

        if (samples.isNotEmpty()) {
            for (sample in samples) {
                val age = displayNowMs - sample.hostTsMs
                if (age < 0f || age > windowMs + 400f) continue
                val x = ageToX(age)
                val pitchY = if (sample.isRest) {
                    lastPitchY
                } else {
                    StaffPitch.pitchYWithCents(sample.note, sample.cents).also { lastPitchY = it }
                }
                val y = pitchToY(pitchY)
                val col = if (sample.isRest) {
                    IntuneColors.Rest.copy(alpha = 0.45f)
                } else {
                    val alpha = 0.45f + sample.confidence.coerceIn(0f, 1f) * 0.55f
                    IntuneColors.centsColor(sample.cents, inTuneThreshold).copy(alpha = alpha)
                }
                points.add(Triple(x, y, col))
            }

            for (i in 1 until points.size) {
                val (x0, y0, _) = points[i - 1]
                val (x1, y1, c1) = points[i]
                drawLine(
                    color = c1.copy(alpha = c1.alpha * 0.25f),
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
                    val pitchY = if (inspect.isRest) {
                        lastPitchY
                    } else {
                        StaffPitch.pitchYWithCents(inspect.note, inspect.cents)
                    }
                    val dotY = pitchToY(pitchY)
                    val dotCol = if (inspect.isRest) {
                        IntuneColors.Rest
                    } else {
                        IntuneColors.centsColor(inspect.cents, inTuneThreshold)
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

/** Stacked letters in the gutter — readable alto clef substitute on Android. */
private fun drawVerticalClefLabel(
    canvas: android.graphics.Canvas,
    text: String,
    centerX: Float,
    centerY: Float,
    paint: android.graphics.Paint,
) {
    val lineHeight = paint.textSize * 1.15f
    val totalHeight = text.length * lineHeight
    var y = centerY - totalHeight * 0.5f + paint.textSize * 0.85f
    for (ch in text) {
        val glyph = ch.toString()
        val x = centerX - paint.measureText(glyph) * 0.5f
        canvas.drawText(glyph, x, y, paint)
        y += lineHeight
    }
}