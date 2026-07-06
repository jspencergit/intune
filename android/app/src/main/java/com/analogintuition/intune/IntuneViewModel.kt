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
    var displayNowMs by mutableFloatStateOf(0f)

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
        }
        paused = !paused
    }

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

}