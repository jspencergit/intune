package com.analogintuition.intune

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class IntuneViewModel(application: Application) : AndroidViewModel(application) {

    val bleClient = (application as IntuneApplication).bleClient

    var paused by mutableStateOf(false)
    var pausedAtMs by mutableFloatStateOf(0f)
    var scrubOffsetMs by mutableFloatStateOf(0f)
    var windowSec by mutableFloatStateOf(8f)
    var inTuneThreshold by mutableFloatStateOf(5f)
    /**
     * Vertical half-range of the cents chart (±this many cents).
     * Default ±50 for beginners who can be far off pitch; ±25 for a tighter view.
     */
    var centsScaleMax by mutableFloatStateOf(50f)
    var displayNowMs by mutableFloatStateOf(0f)
    var traceViewMode by mutableStateOf(TraceViewMode.Cents)
    var staffInstrument by mutableStateOf(StaffPitch.Instrument.Viola)

    /**
     * Samples frozen at Pause. Live BLE keeps appending and would otherwise drop
     * history from the ring buffer (~20s), making the trace vanish while paused.
     */
    var frozenSamples by mutableStateOf<List<PitchSample>?>(null)
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
            pausedAtMs = currentDisplayMs
            scrubOffsetMs = 0f
            // Snapshot so live stream cannot age the review window off the chart.
            frozenSamples = bleClient.state.value.samples.toList()
            paused = true
        } else {
            frozenSamples = null
            paused = false
            // Jump clock to live so Play does not scrub through a gap.
            if (bleClient.state.value.connected) {
                displayNowMs = bleClient.hostNowMs()
            }
        }
    }

    /** Samples for chart + inspect: frozen snapshot while paused, else live BLE. */
    fun displaySamples(live: List<PitchSample>): List<PitchSample> =
        if (paused) frozenSamples ?: live else live

    fun setScrubOffset(offsetMs: Float) {
        if (!paused) return
        scrubOffsetMs = offsetMs.coerceIn(0f, windowSec * 1000f)
    }

    fun scrollSlower() {
        windowSec = (windowSec + 0.5f).coerceAtMost(24f)
        clampScrub()
    }

    fun scrollFaster() {
        windowSec = (windowSec - 0.5f).coerceAtLeast(2f)
        clampScrub()
    }

    private fun clampScrub() {
        scrubOffsetMs = scrubOffsetMs.coerceIn(0f, windowSec * 1000f)
    }

    fun widenTuneZone() {
        inTuneThreshold = (inTuneThreshold + 0.5f).coerceAtMost(25f)
    }

    fun narrowTuneZone() {
        inTuneThreshold = (inTuneThreshold - 0.5f).coerceAtLeast(2f)
    }

    /** Zoom out the cents chart vertical range (±25 → ±50). */
    fun centsRangeWider() {
        centsScaleMax = 50f
    }

    /** Zoom in the cents chart vertical range (±50 → ±25). */
    fun centsRangeTighter() {
        centsScaleMax = 25f
    }

}