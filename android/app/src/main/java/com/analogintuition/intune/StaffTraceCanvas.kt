package com.analogintuition.intune

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.unit.sp

/**
 * Staff + pitch trace — “manuscript paper” look: warm paper field, even dark staff
 * lines, ledger marks, gutter for clef, soft inset edge.
 */
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
        val gutterRight = plotLeft - 4f

        fun pitchToY(pitchY: Float): Float =
            StaffPitch.pitchToScreenY(pitchY, plotTop, plotBottom, instrument)

        fun ageToX(ageMs: Float): Float {
            val t = (ageMs / windowMs).coerceIn(0f, 1f)
            return plotRight - t * (plotRight - plotLeft)
        }

        // Outer panel chrome (matches app chrome)
        drawRoundRect(
            color = IntuneColors.Panel,
            topLeft = Offset(0f, 0f),
            size = size,
            cornerRadius = CornerRadius(12f, 12f),
        )

        // Paper field for the staff + gutter (inset from chrome)
        val paperPad = 3f
        drawRoundRect(
            color = IntuneColors.StaffPaper,
            topLeft = Offset(paperPad, paperPad),
            size = Size(w - paperPad * 2f, h - paperPad * 2f),
            cornerRadius = CornerRadius(10f, 10f),
        )
        // Soft paper edge
        drawRoundRect(
            color = IntuneColors.StaffPaperEdge,
            topLeft = Offset(paperPad, paperPad),
            size = Size(w - paperPad * 2f, h - paperPad * 2f),
            cornerRadius = CornerRadius(10f, 10f),
            style = Stroke(width = 1.2f),
        )

        // Clef gutter (slightly warmer/darker strip — like a printed margin)
        drawRect(
            color = IntuneColors.StaffGutter,
            topLeft = Offset(paperPad, paperPad),
            size = Size(gutterRight - paperPad, h - paperPad * 2f),
        )
        // Gutter / system divider
        drawLine(
            color = IntuneColors.StaffPaperEdge,
            start = Offset(gutterRight, plotTop - 4f),
            end = Offset(gutterRight, plotBottom + 4f),
            strokeWidth = 1.4f,
        )

        // In-tune bands on each staff line (very soft green wash on paper)
        val bandHalf = (plotBottom - plotTop) / 40f
        for (line in instrument.staffLines) {
            val y = pitchToY(line)
            drawRect(
                color = IntuneColors.InTune.copy(alpha = 0.06f),
                topLeft = Offset(plotLeft, y - bandHalf),
                size = Size(plotRight - plotLeft, bandHalf * 2f),
            )
        }

        // Ledger lines — short traditional marks, only in the plot area
        for (ledger in StaffPitch.ledgerLines(instrument)) {
            val y = pitchToY(ledger)
            drawLine(
                color = IntuneColors.StaffLedger.copy(alpha = 0.55f),
                start = Offset(plotLeft + 6f, y),
                end = Offset(plotRight - 6f, y),
                strokeWidth = 1.15f,
                cap = StrokeCap.Butt,
            )
        }

        // Five staff lines — even weight, dark, full system width (trace region only)
        val staffStroke = 1.85f
        for (line in instrument.staffLines) {
            val y = pitchToY(line)
            drawLine(
                color = IntuneColors.StaffLine.copy(alpha = 0.88f),
                start = Offset(plotLeft, y),
                end = Offset(plotRight, y),
                strokeWidth = staffStroke,
                cap = StrokeCap.Butt,
            )
        }

        // Subtle inner shadow under top staff line (depth)
        val topStaffY = pitchToY(instrument.staffLines.first())
        drawLine(
            color = IntuneColors.StaffLine.copy(alpha = 0.06f),
            start = Offset(plotLeft, topStaffY + 2.5f),
            end = Offset(plotRight, topStaffY + 2.5f),
            strokeWidth = 3f,
        )

        val clefPaint = android.graphics.Paint().apply {
            color = android.graphics.Color.argb(230, 44, 51, 64)
            isAntiAlias = true
        }
        val clefAnchorY = pitchToY(instrument.clefAnchor)
        val nativeCanvas = drawContext.canvas.nativeCanvas
        if (instrument.clefSymbol != null) {
            clefPaint.textSize = 38.sp.toPx()
            nativeCanvas.drawText(
                instrument.clefSymbol,
                8f,
                clefAnchorY + clefPaint.textSize * 0.32f,
                clefPaint,
            )
        } else {
            clefPaint.textSize = 12.sp.toPx()
            clefPaint.typeface = android.graphics.Typeface.create(
                android.graphics.Typeface.SERIF,
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

        // Instrument name — top of paper, clear of clip
        val labelPaint = android.graphics.Paint().apply {
            color = android.graphics.Color.argb(200, 42, 112, 184)
            textSize = 12.sp.toPx()
            isAntiAlias = true
            typeface = android.graphics.Typeface.create(
                android.graphics.Typeface.SANS_SERIF,
                android.graphics.Typeface.BOLD,
            )
        }
        nativeCanvas.drawText(
            instrument.label,
            8f,
            6f + labelPaint.textSize,
            labelPaint,
        )

        // Pitch trace on top of staff
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
                // Soft under-glow so the line reads on paper
                drawLine(
                    color = c1.copy(alpha = c1.alpha * 0.22f),
                    start = Offset(x0, y0),
                    end = Offset(x1, y1),
                    strokeWidth = 8f,
                    cap = StrokeCap.Round,
                )
                drawLine(
                    color = c1,
                    start = Offset(x0, y0),
                    end = Offset(x1, y1),
                    strokeWidth = 3.2f,
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
                IntuneColors.Playhead.copy(alpha = 0.12f),
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
