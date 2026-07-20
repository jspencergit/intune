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

/**
 * Staff + pitch trace.
 *
 * Fixed staff geometry: five lines always the same pixel spacing for every
 * instrument; only clef and pitch→line mapping change. Short ledgers only
 * where a note needs them (not full-width graph paper).
 */
@Composable
fun StaffTraceCanvas(
    samples: List<PitchSample>,
    displayNowMs: Float,
    windowSec: Float,
    inTuneThreshold: Float,
    instrument: StaffPitch.Instrument = StaffPitch.Instrument.Viola,
    paused: Boolean = false,
    /** Absolute age of crosshair from live/pause edge (0 = newest). */
    scrubOffsetMs: Float = 0f,
    /** Age at the right edge of the view (pan into history when paused). */
    viewEndAgeMs: Float = 0f,
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
        val viewEnd = viewEndAgeMs.coerceAtLeast(0f)

        val staff = StaffPitch.fixedStaff(plotTop, plotBottom, instrument)

        fun pitchToY(pitchY: Float): Float = staff.pitchToScreenY(pitchY)

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

        // Soft in-tune wash on each staff line (same geometry for all instruments)
        val bandHalf = staff.lineGapPx * 0.22f
        for (linePitch in staff.linesLowToHigh) {
            val y = pitchToY(linePitch)
            drawRect(
                color = IntuneColors.InTune.copy(alpha = 0.07f),
                topLeft = Offset(plotLeft, y - bandHalf),
                size = androidx.compose.ui.geometry.Size(plotRight - plotLeft, bandHalf * 2f),
            )
        }

        // Five staff lines — constant pixel spacing
        val staffStroke = 1.75f
        for (linePitch in staff.linesLowToHigh) {
            val y = pitchToY(linePitch)
            drawLine(
                color = IntuneColors.TextPrimary.copy(alpha = 0.62f),
                start = Offset(plotLeft, y),
                end = Offset(plotRight, y),
                strokeWidth = staffStroke,
                cap = StrokeCap.Butt,
            )
        }

        val clefPaint = android.graphics.Paint().apply {
            color = android.graphics.Color.argb(210, 58, 68, 80)
            isAntiAlias = true
        }
        val clefAnchorY = pitchToY(instrument.clefAnchor)
        val nativeCanvas = drawContext.canvas.nativeCanvas
        val clef = instrument.clefSymbol
        if (clef != null) {
            // Scale + baseline per clef glyph (Unicode music symbols differ optically).
            // clefAnchor = staff line the clef sits on (C mid / F for bass / G for treble).
            val (sizeMul, baselineFrac) = when (instrument) {
                StaffPitch.Instrument.Viola -> 1.75f to 0.36f   // C clef centered on middle line
                // Bass: Unicode 𝄢 sits high on the baseline — large frac moves dots onto F line.
                StaffPitch.Instrument.Cello -> 2.05f to 1.02f
                // Treble: spiral should wrap the G line (2nd from bottom); was a bit low.
                StaffPitch.Instrument.Violin -> 2.0f to 0.42f
            }
            clefPaint.textSize = (staff.lineGapPx * sizeMul).coerceIn(40f, 88f)
            val baseline = clefAnchorY + clefPaint.textSize * baselineFrac
            nativeCanvas.drawText(clef, 4f, baseline, clefPaint)
        }

        val labelPaint = android.graphics.Paint().apply {
            color = android.graphics.Color.argb(200, 42, 112, 184)
            textSize = 12.sp.toPx()
            isAntiAlias = true
            typeface = android.graphics.Typeface.create(
                android.graphics.Typeface.DEFAULT,
                android.graphics.Typeface.BOLD,
            )
        }
        nativeCanvas.drawText(
            instrument.label,
            8f,
            6f + labelPaint.textSize,
            labelPaint,
        )

        // Collect pitch samples + draw short ledgers only where notes need them
        var lastPitchY = StaffPitch.Y_REST
        val points = mutableListOf<Triple<Float, Float, androidx.compose.ui.graphics.Color>>()
        val ledgerHalfW = 11f

        if (samples.isNotEmpty()) {
            for (sample in samples) {
                val age = displayNowMs - sample.hostTsMs
                val rel = age - viewEnd
                if (rel < -50f || rel > windowMs + 50f) continue
                val x = relAgeToX(rel)
                val pitchY = if (sample.isRest) {
                    lastPitchY
                } else {
                    StaffPitch.pitchYWithCents(sample.note, sample.cents).also { lastPitchY = it }
                }
                val y = pitchToY(pitchY)
                val col = when {
                    sample.isRest -> IntuneColors.Rest.copy(alpha = 0.45f)
                    sample.isSettling -> IntuneColors.TextDim.copy(alpha = 0.55f)
                    else -> {
                        val alpha = 0.45f + sample.confidence.coerceIn(0f, 1f) * 0.55f
                        IntuneColors.centsColor(sample.cents, inTuneThreshold).copy(alpha = alpha)
                    }
                }
                points.add(Triple(x, y, col))

                if (!sample.isRest) {
                    for (lp in staff.ledgerPitchesFor(pitchY)) {
                        val ly = pitchToY(lp)
                        drawLine(
                            color = IntuneColors.TextPrimary.copy(alpha = 0.5f),
                            start = Offset(x - ledgerHalfW, ly),
                            end = Offset(x + ledgerHalfW, ly),
                            strokeWidth = 1.5f,
                            cap = StrokeCap.Butt,
                        )
                    }
                }
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
                (scrubOffsetMs - viewEnd).coerceIn(0f, windowMs),
                w, windowMs, plotLeft, plotRight,
            )
        } else {
            plotRight
        }

        // Playhead spans the staff block (not full panel of empty ledger space)
        drawLine(
            IntuneColors.Playhead.copy(alpha = if (paused) 0.95f else 0.85f),
            Offset(cursorX, staff.staffTopY - staff.lineGapPx * 0.5f),
            Offset(cursorX, staff.staffBottomY + staff.lineGapPx * 0.5f),
            strokeWidth = if (paused) 3f else 2.5f,
        )
        if (paused) {
            drawLine(
                IntuneColors.Playhead.copy(alpha = 0.15f),
                Offset(cursorX, staff.staffTopY - staff.lineGapPx * 0.5f),
                Offset(cursorX, staff.staffBottomY + staff.lineGapPx * 0.5f),
                strokeWidth = 10f,
            )
        }

        if (paused && samples.isNotEmpty()) {
            val inspectMs = displayNowMs - scrubOffsetMs
            val inspect = samples.nearestTo(inspectMs)
            if (inspect != null) {
                val inspectRel = (displayNowMs - inspect.hostTsMs) - viewEnd
                if (inspectRel in -20f..windowMs + 20f) {
                    val pitchY = if (inspect.isRest) {
                        lastPitchY
                    } else {
                        StaffPitch.pitchYWithCents(inspect.note, inspect.cents)
                    }
                    val dotY = pitchToY(pitchY)
                    val dotCol = when {
                        inspect.isRest -> IntuneColors.Rest
                        inspect.isSettling -> IntuneColors.TextDim
                        else -> IntuneColors.centsColor(inspect.cents, inTuneThreshold)
                    }
                    if (!inspect.isRest) {
                        for (lp in staff.ledgerPitchesFor(pitchY)) {
                            val ly = pitchToY(lp)
                            drawLine(
                                color = IntuneColors.TextPrimary.copy(alpha = 0.55f),
                                start = Offset(cursorX - ledgerHalfW, ly),
                                end = Offset(cursorX + ledgerHalfW, ly),
                                strokeWidth = 1.6f,
                            )
                        }
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


