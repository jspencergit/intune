package com.analogintuition.intune

import android.Manifest
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.core.content.ContextCompat
import kotlin.math.abs

/** Human label for visible time span (oscilloscope horizontal scale). */
private fun formatSpanLabel(sec: Float): String =
    if (sec >= 10f - 1e-3f) "%.0fs".format(sec) else "%.1fs".format(sec)

class MainActivity : ComponentActivity() {

    private val viewModel: IntuneViewModel by viewModels()

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        if (grants.values.all { it }) {
            viewModel.bleClient.toggleConnection()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        setContent {
            MaterialTheme(
                colorScheme = MaterialTheme.colorScheme.copy(
                    background = IntuneColors.Background,
                    surface = IntuneColors.Panel,
                    primary = IntuneColors.Accent,
                ),
            ) {
                Surface(modifier = Modifier.fillMaxSize(), color = IntuneColors.Background) {
                    val bleState by viewModel.bleClient.state.collectAsState()
                    IntuneScreen(
                        viewModel = viewModel,
                        bleState = bleState,
                        onConnectClick = { ensurePermissionsAndConnect() },
                    )
                }
            }
        }
    }

    private fun ensurePermissionsAndConnect() {
        val needed = requiredPermissions().filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (needed.isEmpty()) {
            viewModel.bleClient.toggleConnection()
        } else {
            permissionLauncher.launch(needed.toTypedArray())
        }
    }

    private fun requiredPermissions(): List<String> {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            listOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_CONNECT,
            )
        } else {
            listOf(
                Manifest.permission.BLUETOOTH,
                Manifest.permission.BLUETOOTH_ADMIN,
                Manifest.permission.ACCESS_FINE_LOCATION,
            )
        }
    }
}

@Composable
private fun IntuneScreen(
    viewModel: IntuneViewModel,
    bleState: BleStreamClient.UiState,
    onConnectClick: () -> Unit,
) {
    val isLandscape =
        LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE
    val displayNow = if (viewModel.paused) viewModel.pausedAtMs else viewModel.displayNowMs
    // While paused, use the freeze snapshot so live BLE cannot purge the trace.
    val chartSamples = viewModel.displaySamples(bleState.samples)
    val latest = chartSamples.lastOrNull { !it.isRest } ?: chartSamples.lastOrNull()
    val focusSample = if (viewModel.paused) {
        chartSamples.nearestTo(displayNow - viewModel.scrubOffsetMs) ?: latest
    } else {
        latest
    }
    var showSettings by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding(),
    ) {
        TopBar(
            status = bleState.status,
            connected = bleState.connected,
            concertAHz = viewModel.concertAHz,
            onConnectClick = onConnectClick,
            onSettingsClick = { showSettings = true },
        )

        if (showSettings) {
            SettingsDialog(
                concertAHz = viewModel.concertAHz,
                onConcertAChange = viewModel::updateConcertAHz,
                onNudgeConcertA = viewModel::nudgeConcertA,
                onDismiss = { showSettings = false },
            )
        }

        if (!bleState.connected) {
            ConnectHelpCard(modifier = Modifier.padding(16.dp))
        } else if (isLandscape) {
            LandscapePracticeLayout(
                focusSample = focusSample,
                samples = chartSamples,
                displayNowMs = displayNow,
                windowSec = viewModel.windowSec,
                inTuneThreshold = viewModel.inTuneThreshold,
                centsScaleMax = viewModel.centsScaleMax,
                traceViewMode = viewModel.traceViewMode,
                staffInstrument = viewModel.staffInstrument,
                responseMode = viewModel.responseMode,
                paused = viewModel.paused,
                scrubOffsetMs = viewModel.scrubOffsetMs,
                viewEndAgeMs = viewModel.viewEndAgeMs,
                pauseHistoryLabel = viewModel.pauseHistoryLabel(),
                onScrubFromPlotX = viewModel::setScrubFromPlotX,
                onPanView = viewModel::panView,
                onPauseToggle = { viewModel.togglePause(viewModel.displayNowMs) },
                onSpanWider = viewModel::spanWider,
                onSpanTighter = viewModel::spanTighter,
                onPanOlder = viewModel::panOlder,
                onPanNewer = viewModel::panNewer,
                onTuneWider = viewModel::widenTuneZone,
                onTuneNarrower = viewModel::narrowTuneZone,
                onCentsRangeWider = viewModel::centsRangeWider,
                onCentsRangeTighter = viewModel::centsRangeTighter,
                onToggleTraceView = viewModel::toggleTraceView,
                onCycleInstrument = viewModel::cycleStaffInstrument,
                onCycleResponseMode = viewModel::cycleResponseMode,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
            )
        } else {
            PortraitPracticeLayout(
                focusSample = focusSample,
                samples = chartSamples,
                displayNowMs = displayNow,
                windowSec = viewModel.windowSec,
                inTuneThreshold = viewModel.inTuneThreshold,
                centsScaleMax = viewModel.centsScaleMax,
                traceViewMode = viewModel.traceViewMode,
                staffInstrument = viewModel.staffInstrument,
                responseMode = viewModel.responseMode,
                paused = viewModel.paused,
                scrubOffsetMs = viewModel.scrubOffsetMs,
                viewEndAgeMs = viewModel.viewEndAgeMs,
                pauseHistoryLabel = viewModel.pauseHistoryLabel(),
                onScrubFromPlotX = viewModel::setScrubFromPlotX,
                onPanView = viewModel::panView,
                onPauseToggle = { viewModel.togglePause(viewModel.displayNowMs) },
                onSpanWider = viewModel::spanWider,
                onSpanTighter = viewModel::spanTighter,
                onPanOlder = viewModel::panOlder,
                onPanNewer = viewModel::panNewer,
                onTuneWider = viewModel::widenTuneZone,
                onTuneNarrower = viewModel::narrowTuneZone,
                onCentsRangeWider = viewModel::centsRangeWider,
                onCentsRangeTighter = viewModel::centsRangeTighter,
                onToggleTraceView = viewModel::toggleTraceView,
                onCycleInstrument = viewModel::cycleStaffInstrument,
                onCycleResponseMode = viewModel::cycleResponseMode,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun PortraitPracticeLayout(
    focusSample: PitchSample?,
    samples: List<PitchSample>,
    displayNowMs: Float,
    windowSec: Float,
    inTuneThreshold: Float,
    centsScaleMax: Float,
    traceViewMode: TraceViewMode,
    staffInstrument: StaffPitch.Instrument,
    responseMode: ResponseMode,
    paused: Boolean,
    scrubOffsetMs: Float,
    viewEndAgeMs: Float,
    pauseHistoryLabel: String,
    onScrubFromPlotX: (Float, Float, Float, Float) -> Unit,
    onPanView: (Float) -> Unit,
    onPauseToggle: () -> Unit,
    onSpanWider: () -> Unit,
    onSpanTighter: () -> Unit,
    onPanOlder: () -> Unit,
    onPanNewer: () -> Unit,
    onTuneWider: () -> Unit,
    onTuneNarrower: () -> Unit,
    onCentsRangeWider: () -> Unit,
    onCentsRangeTighter: () -> Unit,
    onToggleTraceView: () -> Unit,
    onCycleInstrument: () -> Unit,
    onCycleResponseMode: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxSize()) {
        LiveNoteCard(
            sample = focusSample,
            inTuneThreshold = inTuneThreshold,
            layout = NoteCardLayout.Portrait,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp),
        )
        Spacer(modifier = Modifier.height(4.dp))
        // Chart gets most of the remaining space; controls hug content at bottom.
        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .padding(horizontal = 12.dp),
        ) {
            TraceChartPanel(
                traceViewMode = traceViewMode,
                staffInstrument = staffInstrument,
                samples = samples,
                displayNowMs = displayNowMs,
                windowSec = windowSec,
                inTuneThreshold = inTuneThreshold,
                centsScaleMax = centsScaleMax,
                paused = paused,
                scrubOffsetMs = scrubOffsetMs,
                viewEndAgeMs = viewEndAgeMs,
                onScrubFromPlotX = onScrubFromPlotX,
                onPanView = onPanView,
                modifier = Modifier.fillMaxSize(),
            )
        }
        ControlPanel(
            paused = paused,
            windowSec = windowSec,
            inTuneThreshold = inTuneThreshold,
            centsScaleMax = centsScaleMax,
            traceViewMode = traceViewMode,
            staffInstrument = staffInstrument,
            responseMode = responseMode,
            pauseHistoryLabel = pauseHistoryLabel,
            onPauseToggle = onPauseToggle,
            onSpanWider = onSpanWider,
            onSpanTighter = onSpanTighter,
            onPanOlder = onPanOlder,
            onPanNewer = onPanNewer,
            onTuneWider = onTuneWider,
            onTuneNarrower = onTuneNarrower,
            onCentsRangeWider = onCentsRangeWider,
            onCentsRangeTighter = onCentsRangeTighter,
            onToggleTraceView = onToggleTraceView,
            onCycleInstrument = onCycleInstrument,
            onCycleResponseMode = onCycleResponseMode,
            compact = true,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 4.dp),
        )
    }
}

@Composable
private fun LandscapePracticeLayout(
    focusSample: PitchSample?,
    samples: List<PitchSample>,
    displayNowMs: Float,
    windowSec: Float,
    inTuneThreshold: Float,
    centsScaleMax: Float,
    traceViewMode: TraceViewMode,
    staffInstrument: StaffPitch.Instrument,
    responseMode: ResponseMode,
    paused: Boolean,
    scrubOffsetMs: Float,
    viewEndAgeMs: Float,
    pauseHistoryLabel: String,
    onScrubFromPlotX: (Float, Float, Float, Float) -> Unit,
    onPanView: (Float) -> Unit,
    onPauseToggle: () -> Unit,
    onSpanWider: () -> Unit,
    onSpanTighter: () -> Unit,
    onPanOlder: () -> Unit,
    onPanNewer: () -> Unit,
    onTuneWider: () -> Unit,
    onTuneNarrower: () -> Unit,
    onCentsRangeWider: () -> Unit,
    onCentsRangeTighter: () -> Unit,
    onToggleTraceView: () -> Unit,
    onCycleInstrument: () -> Unit,
    onCycleResponseMode: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 10.dp, vertical = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // Scrollable rail: note card + controls (Range must not be clipped off-screen).
        Column(
            modifier = Modifier
                .width(252.dp)
                .fillMaxHeight()
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            LiveNoteCard(
                sample = focusSample,
                inTuneThreshold = inTuneThreshold,
                layout = NoteCardLayout.Compact,
                modifier = Modifier.fillMaxWidth(),
            )
            ControlPanel(
                paused = paused,
                windowSec = windowSec,
                inTuneThreshold = inTuneThreshold,
                centsScaleMax = centsScaleMax,
                traceViewMode = traceViewMode,
                staffInstrument = staffInstrument,
                responseMode = responseMode,
                pauseHistoryLabel = pauseHistoryLabel,
                onPauseToggle = onPauseToggle,
                onSpanWider = onSpanWider,
                onSpanTighter = onSpanTighter,
                onPanOlder = onPanOlder,
                onPanNewer = onPanNewer,
                onTuneWider = onTuneWider,
                onTuneNarrower = onTuneNarrower,
                onCentsRangeWider = onCentsRangeWider,
                onCentsRangeTighter = onCentsRangeTighter,
                onToggleTraceView = onToggleTraceView,
                onCycleInstrument = onCycleInstrument,
                onCycleResponseMode = onCycleResponseMode,
                compact = true,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 8.dp),
            )
        }
        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxHeight(),
        ) {
            TraceChartPanel(
                traceViewMode = traceViewMode,
                staffInstrument = staffInstrument,
                samples = samples,
                displayNowMs = displayNowMs,
                windowSec = windowSec,
                inTuneThreshold = inTuneThreshold,
                centsScaleMax = centsScaleMax,
                paused = paused,
                scrubOffsetMs = scrubOffsetMs,
                viewEndAgeMs = viewEndAgeMs,
                onScrubFromPlotX = onScrubFromPlotX,
                onPanView = onPanView,
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}

@Composable
private fun TraceChartPanel(
    traceViewMode: TraceViewMode,
    staffInstrument: StaffPitch.Instrument,
    samples: List<PitchSample>,
    displayNowMs: Float,
    windowSec: Float,
    inTuneThreshold: Float,
    centsScaleMax: Float,
    paused: Boolean,
    scrubOffsetMs: Float,
    viewEndAgeMs: Float,
    onScrubFromPlotX: (Float, Float, Float, Float) -> Unit,
    onPanView: (Float) -> Unit,
    modifier: Modifier = Modifier,
) {
    val plotLeft = when (traceViewMode) {
        TraceViewMode.Cents -> CentsChartGeometry.plotLeft()
        TraceViewMode.Staff -> StaffChartGeometry.plotLeft()
    }

    Box(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(IntuneColors.Panel),
    ) {
        when (traceViewMode) {
            TraceViewMode.Cents -> CentsTraceCanvas(
                samples = samples,
                displayNowMs = displayNowMs,
                windowSec = windowSec,
                inTuneThreshold = inTuneThreshold,
                centsScaleMax = centsScaleMax,
                paused = paused,
                scrubOffsetMs = scrubOffsetMs,
                viewEndAgeMs = viewEndAgeMs,
                modifier = Modifier.fillMaxSize(),
            )
            TraceViewMode.Staff -> StaffTraceCanvas(
                samples = samples,
                displayNowMs = displayNowMs,
                windowSec = windowSec,
                inTuneThreshold = inTuneThreshold,
                instrument = staffInstrument,
                paused = paused,
                scrubOffsetMs = scrubOffsetMs,
                viewEndAgeMs = viewEndAgeMs,
                modifier = Modifier.fillMaxSize(),
            )
        }
        // Gesture layer ON TOP of the canvas. (pointerInput on the parent Box loses
        // hits to the Canvas child.) Do not key on viewEndAgeMs — that restarted the
        // detector mid-pan and cancelled two-finger drags.
        if (paused) {
            Box(
                Modifier
                    .fillMaxSize()
                    // Keys: only geometry/span — never viewEndAgeMs (that cancelled mid-pan).
                    .pointerInput(windowSec, plotLeft) {
                        val windowMs = windowSec * 1000f
                        awaitEachGesture {
                            awaitFirstDown(requireUnconsumed = false)
                            // Once a second finger joins, this gesture is pan-only.
                            var multiTouch = false
                            while (true) {
                                val event = awaitPointerEvent(PointerEventPass.Main)
                                val pressed = event.changes.filter { it.pressed }
                                if (pressed.isEmpty()) break
                                if (pressed.size >= 2) multiTouch = true

                                val width = size.width.toFloat()
                                if (width <= 1f) {
                                    pressed.forEach { it.consume() }
                                    continue
                                }
                                val pRight = width - CentsChartGeometry.PLOT_RIGHT_PAD
                                val pWidth = (pRight - plotLeft).coerceAtLeast(1f)
                                val agePerPx = windowMs / pWidth

                                if (multiTouch) {
                                    if (pressed.size >= 2) {
                                        // Centroid motion via positionChange (stable with multi-touch).
                                        val dx = pressed
                                            .map { it.positionChange().x }
                                            .average()
                                            .toFloat()
                                        // Finger right → pull older history into view.
                                        if (dx != 0f) onPanView(dx * agePerPx)
                                    }
                                    pressed.forEach { it.consume() }
                                } else {
                                    // Single finger: vertical marker only.
                                    val x = pressed[0].position.x
                                    onScrubFromPlotX(x, width, plotLeft, pRight)
                                    pressed.forEach { it.consume() }
                                }
                            }
                        }
                    },
            )
        }
    }
}

@Composable
private fun TopBar(
    status: String,
    connected: Boolean,
    concertAHz: Float,
    onConnectClick: () -> Unit,
    onSettingsClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(CircleShape)
                .background(
                    when {
                        connected && status.contains("Streaming") -> IntuneColors.InTune
                        connected -> IntuneColors.Accent
                        else -> IntuneColors.Rest
                    },
                ),
        )
        Spacer(modifier = Modifier.width(8.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text("Intune", fontWeight = FontWeight.SemiBold, fontSize = 16.sp, color = IntuneColors.TextPrimary)
            Text(
                "$status · A=${"%.0f".format(concertAHz)}",
                fontSize = 12.sp,
                color = IntuneColors.TextDim,
                maxLines = 1,
            )
        }
        FilledTonalButton(
            onClick = onSettingsClick,
            contentPadding = PaddingValues(0.dp),
            modifier = Modifier.size(36.dp),
        ) {
            Text("⚙", fontSize = 16.sp)
        }
        Spacer(modifier = Modifier.width(6.dp))
        FilledTonalButton(
            onClick = onConnectClick,
            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
            modifier = Modifier.height(36.dp),
        ) {
            Text(if (connected) "Disconnect" else "Connect", fontSize = 13.sp)
        }
    }
}

@Composable
private fun SettingsDialog(
    concertAHz: Float,
    onConcertAChange: (Float) -> Unit,
    onNudgeConcertA: (Float) -> Unit,
    onDismiss: () -> Unit,
) {
    // Custom Dialog (not AlertDialog): Material AlertDialog often clips its body
    // in landscape, leaving only title/Done — so A4 controls vanish.
    val landscape =
        LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE

    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = IntuneColors.Panel,
            modifier = Modifier.fillMaxWidth(if (landscape) 0.72f else 0.92f),
        ) {
            Column(
                modifier = Modifier
                    .padding(
                        horizontal = 16.dp,
                        vertical = if (landscape) 12.dp else 16.dp,
                    )
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(if (landscape) 8.dp else 12.dp),
            ) {
                Text(
                    "Settings",
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 18.sp,
                    color = IntuneColors.TextPrimary,
                )
                Text(
                    "Concert A — reference for note names and cents only",
                    fontSize = 12.sp,
                    color = IntuneColors.TextDim,
                    maxLines = if (landscape) 1 else 2,
                )
                CompactStepperRow(
                    label = "A4",
                    valueLabel = "%.0f Hz".format(concertAHz),
                    decreaseLabel = "−",
                    increaseLabel = "+",
                    onDecrease = { onNudgeConcertA(-1f) },
                    onIncrease = { onNudgeConcertA(1f) },
                    dense = landscape,
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    listOf(440f, 441f, 442f).forEach { preset ->
                        val selected = abs(concertAHz - preset) < 0.5f
                        val mod = Modifier
                            .weight(1f)
                            .height(if (landscape) 34.dp else 36.dp)
                        if (selected) {
                            Button(
                                onClick = { onConcertAChange(preset) },
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp),
                                modifier = mod,
                            ) {
                                Text("%.0f".format(preset), fontSize = 13.sp, maxLines = 1)
                            }
                        } else {
                            FilledTonalButton(
                                onClick = { onConcertAChange(preset) },
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp),
                                modifier = mod,
                            ) {
                                Text("%.0f".format(preset), fontSize = 13.sp, maxLines = 1)
                            }
                        }
                    }
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                ) {
                    TextButton(onClick = onDismiss) {
                        Text("Done")
                    }
                }
            }
        }
    }
}

private enum class NoteCardLayout { Portrait, Compact }

private val CompactBtnPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp)
private val CompactBtnHeight = 32.dp
private val PrimaryBtnHeight = 42.dp

@Composable
private fun LiveNoteCard(
    sample: PitchSample?,
    inTuneThreshold: Float,
    layout: NoteCardLayout,
    modifier: Modifier = Modifier,
) {
    val note = sample?.displayNote ?: "—"
    val cents = sample?.cents ?: 0f
    val isRest = sample == null || sample.isRest
    val isSettling = sample?.isSettling == true
    val col = when {
        sample == null -> IntuneColors.TextDim
        isRest -> IntuneColors.Rest
        isSettling -> IntuneColors.TextDim
        else -> IntuneColors.centsColor(cents, inTuneThreshold)
    }
    val qual = when {
        isRest -> "waiting"
        isSettling -> "settling"
        abs(cents) < inTuneThreshold -> "in tune"
        cents > 0f -> "sharp"
        else -> "flat"
    }
    val showCents = !isRest && !isSettling

    when (layout) {
        NoteCardLayout.Compact -> {
            Column(
                modifier = modifier
                    .clip(RoundedCornerShape(10.dp))
                    .background(IntuneColors.Panel)
                    .padding(horizontal = 8.dp, vertical = 6.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center,
                ) {
                    Text(
                        text = note,
                        fontSize = 24.sp,
                        fontWeight = FontWeight.Bold,
                        color = col,
                        maxLines = 1,
                    )
                    if (showCents) {
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = "%+.1f¢".format(cents),
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Medium,
                            color = col.copy(alpha = 0.9f),
                            maxLines = 1,
                        )
                    }
                }
                Text(
                    "$qual · zone ±%.0f¢".format(inTuneThreshold),
                    fontSize = 10.sp,
                    color = IntuneColors.TextDim,
                    maxLines = 1,
                )
            }
        }
        NoteCardLayout.Portrait -> {
            Column(
                modifier = modifier
                    .clip(RoundedCornerShape(12.dp))
                    .background(IntuneColors.Panel)
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center,
                ) {
                    Text(
                        text = note,
                        fontSize = 36.sp,
                        fontWeight = FontWeight.Bold,
                        color = col,
                        maxLines = 1,
                    )
                    if (showCents) {
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "%+.1f ¢".format(cents),
                            fontSize = 20.sp,
                            fontWeight = FontWeight.Medium,
                            color = col.copy(alpha = 0.9f),
                        )
                    }
                }
                Text(
                    "$qual · zone ±%.0f¢".format(inTuneThreshold),
                    fontSize = 12.sp,
                    color = IntuneColors.TextDim,
                )
            }
        }
    }
}

@Composable
private fun ControlPanel(
    paused: Boolean,
    windowSec: Float,
    inTuneThreshold: Float,
    centsScaleMax: Float,
    traceViewMode: TraceViewMode,
    staffInstrument: StaffPitch.Instrument,
    responseMode: ResponseMode,
    pauseHistoryLabel: String = "",
    onPauseToggle: () -> Unit,
    onSpanWider: () -> Unit,
    onSpanTighter: () -> Unit,
    onPanOlder: () -> Unit,
    onPanNewer: () -> Unit,
    onTuneWider: () -> Unit,
    onTuneNarrower: () -> Unit,
    onCentsRangeWider: () -> Unit,
    onCentsRangeTighter: () -> Unit,
    onToggleTraceView: () -> Unit,
    onCycleInstrument: () -> Unit,
    onCycleResponseMode: () -> Unit,
    compact: Boolean,
    modifier: Modifier = Modifier,
) {
    val gap = if (compact) 2.dp else 6.dp
    val primaryH = if (compact) 38.dp else 48.dp
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(gap),
    ) {
        // Primary: larger Pause. Secondary: Staff/Cents.
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Button(
                onClick = onPauseToggle,
                colors = ButtonDefaults.buttonColors(containerColor = IntuneColors.Accent),
                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp),
                modifier = Modifier
                    .weight(1.4f)
                    .height(primaryH),
            ) {
                Text(
                    if (paused) "Play" else "Pause",
                    fontSize = if (compact) 14.sp else 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                )
            }
            FilledTonalButton(
                onClick = onToggleTraceView,
                contentPadding = CompactBtnPadding,
                modifier = Modifier
                    .weight(1f)
                    .height(primaryH),
            ) {
                Text(
                    if (traceViewMode == TraceViewMode.Cents) "Staff" else "Cents",
                    fontSize = 13.sp,
                    maxLines = 1,
                )
            }
        }
        if (traceViewMode == TraceViewMode.Staff) {
            FilledTonalButton(
                onClick = onCycleInstrument,
                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(28.dp),
            ) {
                Text(
                    text = "Instrument · ${staffInstrument.label}  ›",
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                    softWrap = false,
                )
            }
        }
        FilledTonalButton(
            onClick = onCycleResponseMode,
            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp),
            modifier = Modifier
                .fillMaxWidth()
                .height(if (compact) 28.dp else 32.dp),
        ) {
            Text(
                text = "Response · ${responseMode.label}  ›",
                fontSize = 11.sp,
                fontWeight = FontWeight.Medium,
                maxLines = 1,
                softWrap = false,
            )
        }
        if (paused) {
            Text(
                "1 finger = marker · 2 fingers = pan",
                fontSize = 10.sp,
                color = IntuneColors.TextDim,
                modifier = Modifier.fillMaxWidth(),
                textAlign = TextAlign.Center,
            )
            if (pauseHistoryLabel.isNotEmpty()) {
                Text(
                    pauseHistoryLabel,
                    fontSize = 10.sp,
                    color = IntuneColors.TextDim,
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                )
            }
        }
        // Span = how much time is on screen (+ zooms out / more history visible).
        CompactStepperRow(
            label = "Span",
            valueLabel = formatSpanLabel(windowSec),
            decreaseLabel = "−",
            increaseLabel = "+",
            onDecrease = onSpanTighter,
            onIncrease = onSpanWider,
            dense = compact,
        )
        if (paused) {
            // Pan history under the fixed window; crosshair keeps absolute time.
            CompactStepperRow(
                label = "Pan",
                valueLabel = "history",
                decreaseLabel = "«",
                increaseLabel = "»",
                onDecrease = onPanOlder,
                onIncrease = onPanNewer,
                dense = compact,
            )
        }
        CompactStepperRow(
            label = "Zone",
            valueLabel = "±%.0f¢".format(inTuneThreshold),
            decreaseLabel = "−",
            increaseLabel = "+",
            onDecrease = onTuneNarrower,
            onIncrease = onTuneWider,
            dense = compact,
        )
        if (traceViewMode == TraceViewMode.Cents) {
            CompactStepperRow(
                label = "Range",
                valueLabel = "±%.0f¢".format(centsScaleMax),
                decreaseLabel = "−",
                increaseLabel = "+",
                onDecrease = onCentsRangeTighter,
                onIncrease = onCentsRangeWider,
                dense = compact,
            )
        }
    }
}

/** Single-line control: Label  [−]  value  [+]  — no nested cards. */
@Composable
private fun CompactStepperRow(
    label: String,
    valueLabel: String,
    decreaseLabel: String,
    increaseLabel: String,
    onDecrease: () -> Unit,
    onIncrease: () -> Unit,
    dense: Boolean = false,
) {
    val btn = if (dense) 30.dp else CompactBtnHeight
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(IntuneColors.Panel)
            .padding(horizontal = 6.dp, vertical = if (dense) 1.dp else 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(
            label,
            fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold,
            color = IntuneColors.TextPrimary,
            // Wide enough for "Span" / "Range" / "Zone" without clipping.
            modifier = Modifier.width(60.dp),
            maxLines = 1,
            softWrap = false,
        )
        FilledTonalButton(
            onClick = onDecrease,
            contentPadding = PaddingValues(0.dp),
            modifier = Modifier.size(btn),
        ) {
            Text(decreaseLabel, fontSize = 15.sp, fontWeight = FontWeight.Bold)
        }
        Text(
            valueLabel,
            modifier = Modifier.weight(1f),
            textAlign = TextAlign.Center,
            fontSize = 12.sp,
            fontWeight = FontWeight.Medium,
            color = IntuneColors.TextPrimary,
        )
        FilledTonalButton(
            onClick = onIncrease,
            contentPadding = PaddingValues(0.dp),
            modifier = Modifier.size(btn),
        ) {
            Text(increaseLabel, fontSize = 15.sp, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun ConnectHelpCard(modifier: Modifier = Modifier) {
    Column(modifier = modifier) {
        Text(
            "Connect to your ESP32 (BLE name: Intune).\n\n" +
                "• Bluetooth ON in Settings — no manual pairing\n" +
                "• ESP32 powered nearby\n" +
                "• Tap Connect above",
            color = IntuneColors.TextDim,
            lineHeight = 22.sp,
        )
    }
}