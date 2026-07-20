package com.analogintuition.intune

import android.app.Application
import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.math.max

class IntuneViewModel(application: Application) : AndroidViewModel(application) {

    val bleClient = (application as IntuneApplication).bleClient

    private val prefs =
        application.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var paused by mutableStateOf(false)
    var pausedAtMs by mutableFloatStateOf(0f)
    /**
     * Absolute age (ms) of the inspect crosshair relative to [pausedAtMs] / live edge.
     * 0 = newest (right when view is not panned). Larger = older history.
     */
    var scrubOffsetMs by mutableFloatStateOf(0f)
    /**
     * Age (ms) at the **right edge** of the visible window. 0 = window ends at freeze/live.
     * Increase to pan left into older history (paused only).
     */
    var viewEndAgeMs by mutableFloatStateOf(0f)
    /**
     * Visible time span (seconds) — oscilloscope horizontal scale.
     * **+** widens (zoom out), **−** tightens (zoom in).
     */
    var windowSec by mutableFloatStateOf(DEFAULT_SPAN_SEC)
    var inTuneThreshold by mutableFloatStateOf(10f)
    /**
     * Vertical half-range of the cents chart (±this many cents).
     * Steps: ±25 / ±50 / ±100. Default ±100 so early practice is on-scale.
     */
    var centsScaleMax by mutableFloatStateOf(100f)
    /**
     * Concert A in Hz for note/cents display. Stream is labeled at 440 Hz;
     * the app remaps for the selected reference (default 441).
     */
    var concertAHz by mutableFloatStateOf(
        prefs.getFloat(KEY_CONCERT_A, ConcertPitch.DEFAULT_A_HZ)
            .coerceIn(ConcertPitch.MIN_A_HZ, ConcertPitch.MAX_A_HZ),
    )
        private set
    var displayNowMs by mutableFloatStateOf(0f)
    var traceViewMode by mutableStateOf(TraceViewMode.Cents)
    var staffInstrument by mutableStateOf(StaffPitch.Instrument.Viola)
    /**
     * Steady (default) softens bow attacks for slow intonation practice.
     * Live shows pitch promptly including attack wiggles.
     */
    var responseMode by mutableStateOf(
        ResponseMode.fromStorage(prefs.getString(KEY_RESPONSE_MODE, ResponseMode.Steady.name)),
    )
        private set

    /**
     * Samples frozen at Pause. Live BLE keeps appending and would otherwise drop
     * history from the ring buffer, making the trace vanish while paused.
     */
    var frozenSamples by mutableStateOf<List<PitchSample>?>(null)
        private set

    /** Wall-clock span of [frozenSamples] at pause (ms). 0 when live. */
    var freezeHistoryMs by mutableFloatStateOf(0f)
        private set

    /** Sample count captured at pause. */
    var freezeSampleCount by mutableStateOf(0)
        private set

    fun toggleTraceView() {
        traceViewMode = when (traceViewMode) {
            TraceViewMode.Cents -> TraceViewMode.Staff
            TraceViewMode.Staff -> TraceViewMode.Cents
        }
    }

    fun cycleStaffInstrument() {
        val values = StaffPitch.Instrument.entries
        val idx = values.indexOf(staffInstrument)
        staffInstrument = values[(idx + 1) % values.size]
    }

    fun cycleResponseMode() {
        responseMode = when (responseMode) {
            ResponseMode.Steady -> ResponseMode.Live
            ResponseMode.Live -> ResponseMode.Steady
        }
        prefs.edit().putString(KEY_RESPONSE_MODE, responseMode.name).apply()
    }

    init {
        viewModelScope.launch {
            while (isActive) {
                if (bleClient.state.value.connected && !paused) {
                    displayNowMs = bleClient.hostNowMs()
                }
                delay(16L)
            }
        }
    }

    fun togglePause(currentDisplayMs: Float) {
        if (!paused) {
            // Snapshot first so depth uses the same list we freeze.
            val snap = bleClient.state.value.samples.toList()
            frozenSamples = snap
            freezeSampleCount = snap.size
            freezeHistoryMs = PitchCsvParser.historySpanMs(snap).let { span ->
                // Also measure against pause clock in case host stamps lag wall time.
                if (snap.isEmpty()) {
                    0f
                } else {
                    val oldest = snap.minOf { it.hostTsMs }
                    val newest = snap.maxOf { it.hostTsMs }
                    val end = max(currentDisplayMs, newest)
                    max(span, end - oldest)
                }
            }
            // Anchor pause clock to newest sample so ages start at ~0 on the right.
            pausedAtMs = if (snap.isNotEmpty()) {
                max(currentDisplayMs, snap.maxOf { it.hostTsMs })
            } else {
                currentDisplayMs
            }
            scrubOffsetMs = 0f
            viewEndAgeMs = 0f
            paused = true
        } else {
            frozenSamples = null
            freezeHistoryMs = 0f
            freezeSampleCount = 0
            viewEndAgeMs = 0f
            scrubOffsetMs = 0f
            paused = false
            // Jump clock to live so Play does not scrub through a gap.
            if (bleClient.state.value.connected) {
                displayNowMs = bleClient.hostNowMs()
            }
        }
    }

    /** How far (ms) the view can pan into older history for the current Span. */
    fun maxPanMs(): Float = max(0f, historyDepthMs() - windowMs())

    /** True when two-finger / Pan can actually move the window. */
    fun canPanHistory(): Boolean = paused && maxPanMs() > 50f

    /** One-line status for the pause review UI. */
    fun pauseHistoryLabel(): String {
        if (!paused) return ""
        val histSec = freezeHistoryMs / 1000f
        val spanSec = windowSec
        val panSec = maxPanMs() / 1000f
        val n = freezeSampleCount
        return if (panSec > 0.05f) {
            "history %.1fs (%d) · pan up to %.1fs".format(histSec, n, panSec)
        } else if (histSec > 0.2f) {
            "history %.1fs (%d) · Span− to pan".format(histSec, n)
        } else {
            "history thin (%d samples) · play longer".format(n)
        }
    }

    /**
     * Samples for chart + inspect: frozen snapshot while paused, else live BLE.
     * Remapped to [concertAHz], then Steady/Live display shaping.
     */
    fun displaySamples(live: List<PitchSample>): List<PitchSample> {
        val base = if (paused) frozenSamples ?: live else live
        val remapped = ConcertPitch.remapSamples(base, concertAHz)
        return ResponseDisplayMapper.map(remapped, responseMode)
    }

    fun updateConcertAHz(hz: Float) {
        val v = hz.coerceIn(ConcertPitch.MIN_A_HZ, ConcertPitch.MAX_A_HZ)
        concertAHz = v
        prefs.edit().putFloat(KEY_CONCERT_A, v).apply()
    }

    fun nudgeConcertA(delta: Float) {
        updateConcertAHz(concertAHz + delta)
    }

    /** Place crosshair by absolute age from live/pause edge (0 = newest). */
    fun setScrubOffset(offsetMs: Float) {
        if (!paused) return
        scrubOffsetMs = offsetMs.coerceIn(viewEndAgeMs, viewEndAgeMs + windowMs())
    }

    /**
     * Place crosshair from a plot X while paused. Age is absolute (not view-relative)
     * so panning later keeps the same sample under the marker until it leaves the view.
     */
    fun setScrubFromPlotX(x: Float, chartWidthPx: Float, plotLeft: Float, plotRight: Float) {
        if (!paused || chartWidthPx <= 0f) return
        val rel = ChartScrubGeometry.xToScrubOffsetMs(
            x, chartWidthPx, windowMs(), plotLeft, plotRight,
        )
        setScrubOffset(viewEndAgeMs + rel)
    }

    /** Pan the viewport; crosshair keeps absolute age (clamped into view). */
    fun panView(deltaAgeMs: Float) {
        if (!paused) return
        val maxEnd = maxViewEndAgeMs()
        if (maxEnd <= 0f) return // no history beyond current Span
        viewEndAgeMs = (viewEndAgeMs + deltaAgeMs).coerceIn(0f, maxEnd)
        clampCursorIntoView()
    }

    fun panOlder() = panView(panStepMs())
    fun panNewer() = panView(-panStepMs())

    /** Zoom out: more seconds on screen (+ on Span control). */
    fun spanWider() {
        windowSec = (windowSec + spanStep(windowSec)).coerceAtMost(MAX_SPAN_SEC)
        onSpanChanged()
    }

    /** Zoom in: fewer seconds on screen (− on Span control). */
    fun spanTighter() {
        windowSec = (windowSec - spanStep(windowSec)).coerceAtLeast(MIN_SPAN_SEC)
        onSpanChanged()
    }

    private fun onSpanChanged() {
        if (!paused) {
            viewEndAgeMs = 0f
            scrubOffsetMs = 0f
            return
        }
        // Keep the right edge fixed when zooming so history expands/contracts to the left.
        viewEndAgeMs = viewEndAgeMs.coerceIn(0f, maxViewEndAgeMs())
        // If the crosshair left the view, re-center the window on it.
        if (scrubOffsetMs < viewEndAgeMs || scrubOffsetMs > viewEndAgeMs + windowMs()) {
            val w = windowMs()
            viewEndAgeMs = (scrubOffsetMs - w * 0.5f).coerceIn(0f, maxViewEndAgeMs())
        }
        clampCursorIntoView()
    }

    private fun clampCursorIntoView() {
        scrubOffsetMs = scrubOffsetMs.coerceIn(viewEndAgeMs, viewEndAgeMs + windowMs())
    }

    fun windowMs(): Float = windowSec * 1000f

    /**
     * Deepest absolute age available (ms from right edge / pause).
     * Does **not** floor to the Span — if history is shorter than Span, pan range is 0
     * (you already see everything; use Span− or play longer).
     */
    fun historyDepthMs(): Float {
        if (paused && freezeHistoryMs > 0f) return freezeHistoryMs
        val samples = if (paused) frozenSamples.orEmpty() else bleClient.state.value.samples
        if (samples.isEmpty()) return 0f
        val now = if (paused) pausedAtMs else displayNowMs
        val oldest = samples.minOf { it.hostTsMs }
        val newest = samples.maxOf { it.hostTsMs }
        val end = max(now, newest)
        return max(PitchCsvParser.historySpanMs(samples), end - oldest)
    }

    private fun maxViewEndAgeMs(): Float = max(0f, historyDepthMs() - windowMs())

    private fun panStepMs(): Float = (windowMs() * 0.25f).coerceIn(250f, 4000f)

    private fun spanStep(span: Float): Float = when {
        span < 4f -> 0.5f
        span < 12f -> 1f
        span < 30f -> 2f
        else -> 5f
    }

    fun widenTuneZone() {
        inTuneThreshold = (inTuneThreshold + 0.5f).coerceAtMost(25f)
    }

    fun narrowTuneZone() {
        inTuneThreshold = (inTuneThreshold - 0.5f).coerceAtLeast(2f)
    }

    /** Zoom out the cents chart vertical range: ±25 → ±50 → ±100. */
    fun centsRangeWider() {
        centsScaleMax = when {
            centsScaleMax < 40f -> 50f
            centsScaleMax < 75f -> 100f
            else -> 100f
        }
    }

    /** Zoom in the cents chart vertical range: ±100 → ±50 → ±25. */
    fun centsRangeTighter() {
        centsScaleMax = when {
            centsScaleMax > 75f -> 50f
            centsScaleMax > 40f -> 25f
            else -> 25f
        }
    }

    companion object {
        private const val PREFS_NAME = "intune_prefs"
        private const val KEY_CONCERT_A = "concert_a_hz"
        private const val KEY_RESPONSE_MODE = "response_mode"
        const val MIN_SPAN_SEC = 2f
        const val MAX_SPAN_SEC = 60f
        const val DEFAULT_SPAN_SEC = 8f
    }
}
