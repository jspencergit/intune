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
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlin.math.abs

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
    val latest = bleState.samples.lastOrNull { !it.isRest } ?: bleState.samples.lastOrNull()
    val focusSample = if (viewModel.paused) {
        bleState.samples.nearestTo(displayNow - viewModel.scrubOffsetMs) ?: latest
    } else {
        latest
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding(),
    ) {
        TopBar(
            status = bleState.status,
            connected = bleState.connected,
            onConnectClick = onConnectClick,
        )

        if (!bleState.connected) {
            ConnectHelpCard(modifier = Modifier.padding(16.dp))
        } else if (isLandscape) {
            LandscapePracticeLayout(
                focusSample = focusSample,
                samples = bleState.samples,
                displayNowMs = displayNow,
                windowSec = viewModel.windowSec,
                inTuneThreshold = viewModel.inTuneThreshold,
                traceViewMode = viewModel.traceViewMode,
                staffInstrument = viewModel.staffInstrument,
                paused = viewModel.paused,
                scrubOffsetMs = viewModel.scrubOffsetMs,
                onScrub = viewModel::setScrubOffset,
                onPauseToggle = { viewModel.togglePause(viewModel.displayNowMs) },
                onScrollSlower = viewModel::scrollSlower,
                onScrollFaster = viewModel::scrollFaster,
                onTuneWider = viewModel::widenTuneZone,
                onTuneNarrower = viewModel::narrowTuneZone,
                onToggleTraceView = viewModel::toggleTraceView,
                onCycleInstrument = viewModel::cycleStaffInstrument,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
            )
        } else {
            PortraitPracticeLayout(
                focusSample = focusSample,
                samples = bleState.samples,
                displayNowMs = displayNow,
                windowSec = viewModel.windowSec,
                inTuneThreshold = viewModel.inTuneThreshold,
                traceViewMode = viewModel.traceViewMode,
                staffInstrument = viewModel.staffInstrument,
                paused = viewModel.paused,
                scrubOffsetMs = viewModel.scrubOffsetMs,
                onScrub = viewModel::setScrubOffset,
                onPauseToggle = { viewModel.togglePause(viewModel.displayNowMs) },
                onScrollSlower = viewModel::scrollSlower,
                onScrollFaster = viewModel::scrollFaster,
                onTuneWider = viewModel::widenTuneZone,
                onTuneNarrower = viewModel::narrowTuneZone,
                onToggleTraceView = viewModel::toggleTraceView,
                onCycleInstrument = viewModel::cycleStaffInstrument,
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
    traceViewMode: TraceViewMode,
    staffInstrument: StaffPitch.Instrument,
    paused: Boolean,
    scrubOffsetMs: Float,
    onScrub: (Float) -> Unit,
    onPauseToggle: () -> Unit,
    onScrollSlower: () -> Unit,
    onScrollFaster: () -> Unit,
    onTuneWider: () -> Unit,
    onTuneNarrower: () -> Unit,
    onToggleTraceView: () -> Unit,
    onCycleInstrument: () -> Unit,
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
                paused = paused,
                scrubOffsetMs = scrubOffsetMs,
                onScrub = onScrub,
                modifier = Modifier.fillMaxSize(),
            )
        }
        ControlPanel(
            paused = paused,
            windowSec = windowSec,
            inTuneThreshold = inTuneThreshold,
            traceViewMode = traceViewMode,
            staffInstrument = staffInstrument,
            onPauseToggle = onPauseToggle,
            onScrollSlower = onScrollSlower,
            onScrollFaster = onScrollFaster,
            onTuneWider = onTuneWider,
            onTuneNarrower = onTuneNarrower,
            onToggleTraceView = onToggleTraceView,
            onCycleInstrument = onCycleInstrument,
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
    traceViewMode: TraceViewMode,
    staffInstrument: StaffPitch.Instrument,
    paused: Boolean,
    scrubOffsetMs: Float,
    onScrub: (Float) -> Unit,
    onPauseToggle: () -> Unit,
    onScrollSlower: () -> Unit,
    onScrollFaster: () -> Unit,
    onTuneWider: () -> Unit,
    onTuneNarrower: () -> Unit,
    onToggleTraceView: () -> Unit,
    onCycleInstrument: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 10.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // Pin note card at top so it never clips when controls need a tiny scroll.
        Column(
            modifier = Modifier
                .width(252.dp)
                .fillMaxHeight(),
            verticalArrangement = Arrangement.spacedBy(6.dp),
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
                traceViewMode = traceViewMode,
                staffInstrument = staffInstrument,
                onPauseToggle = onPauseToggle,
                onScrollSlower = onScrollSlower,
                onScrollFaster = onScrollFaster,
                onTuneWider = onTuneWider,
                onTuneNarrower = onTuneNarrower,
                onToggleTraceView = onToggleTraceView,
                onCycleInstrument = onCycleInstrument,
                compact = true,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 10.dp),
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
                paused = paused,
                scrubOffsetMs = scrubOffsetMs,
                onScrub = onScrub,
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
    paused: Boolean,
    scrubOffsetMs: Float,
    onScrub: (Float) -> Unit,
    modifier: Modifier = Modifier,
) {
    var chartWidthPx by remember { mutableFloatStateOf(0f) }
    val windowMs = windowSec * 1000f
    val plotLeft = when (traceViewMode) {
        TraceViewMode.Cents -> CentsChartGeometry.plotLeft()
        TraceViewMode.Staff -> StaffChartGeometry.plotLeft()
    }
    val plotRight = chartWidthPx - CentsChartGeometry.PLOT_RIGHT_PAD

    fun updateScrub(x: Float) {
        if (chartWidthPx > 0f) {
            onScrub(
                ChartScrubGeometry.xToScrubOffsetMs(
                    x, chartWidthPx, windowMs, plotLeft, plotRight,
                ),
            )
        }
    }

    Box(
        modifier = modifier
            .onSizeChanged { chartWidthPx = it.width.toFloat() }
            .clip(RoundedCornerShape(12.dp))
            .background(IntuneColors.Panel)
            .then(
                if (paused) {
                    Modifier
                        .pointerInput(windowSec, chartWidthPx) {
                            detectTapGestures { offset -> updateScrub(offset.x) }
                        }
                        .pointerInput(windowSec, chartWidthPx) {
                            detectHorizontalDragGestures(
                                onDragStart = { offset -> updateScrub(offset.x) },
                                onHorizontalDrag = { change, _ ->
                                    updateScrub(change.position.x)
                                    change.consume()
                                },
                            )
                        }
                } else {
                    Modifier
                },
            ),
    ) {
        when (traceViewMode) {
            TraceViewMode.Cents -> CentsTraceCanvas(
                samples = samples,
                displayNowMs = displayNowMs,
                windowSec = windowSec,
                inTuneThreshold = inTuneThreshold,
                paused = paused,
                scrubOffsetMs = scrubOffsetMs,
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
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}

@Composable
private fun TopBar(
    status: String,
    connected: Boolean,
    onConnectClick: () -> Unit,
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
            Text(status, fontSize = 12.sp, color = IntuneColors.TextDim)
        }
        FilledTonalButton(
            onClick = onConnectClick,
            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
            modifier = Modifier.height(36.dp),
        ) {
            Text(if (connected) "Disconnect" else "Connect", fontSize = 13.sp)
        }
    }
}

private enum class NoteCardLayout { Portrait, Compact }

private val CompactBtnPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp)
private val CompactBtnHeight = 34.dp

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
    val col = when {
        sample == null -> IntuneColors.TextDim
        isRest -> IntuneColors.Rest
        else -> IntuneColors.centsColor(cents, inTuneThreshold)
    }
    val qual = when {
        isRest -> "waiting"
        abs(cents) < inTuneThreshold -> "in tune"
        cents > 0f -> "sharp"
        else -> "flat"
    }

    when (layout) {
        NoteCardLayout.Compact -> {
            // Dense side-rail card: note + cents on one row, status on one line.
            // Extra top pad so tall glyphs (e.g. REST) are not clipped by rounded clip.
            Column(
                modifier = modifier
                    .clip(RoundedCornerShape(12.dp))
                    .background(IntuneColors.Panel)
                    .padding(horizontal = 10.dp, vertical = 10.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center,
                ) {
                    Text(
                        text = note,
                        fontSize = 28.sp,
                        fontWeight = FontWeight.Bold,
                        color = col,
                        maxLines = 1,
                    )
                    if (!isRest && sample != null) {
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "%+.1f¢".format(cents),
                            fontSize = 15.sp,
                            fontWeight = FontWeight.Medium,
                            color = col.copy(alpha = 0.9f),
                            maxLines = 1,
                        )
                    }
                }
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    "$qual · zone ±%.0f¢".format(inTuneThreshold),
                    fontSize = 11.sp,
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
                    if (!isRest && sample != null) {
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
    traceViewMode: TraceViewMode,
    staffInstrument: StaffPitch.Instrument,
    onPauseToggle: () -> Unit,
    onScrollSlower: () -> Unit,
    onScrollFaster: () -> Unit,
    onTuneWider: () -> Unit,
    onTuneNarrower: () -> Unit,
    onToggleTraceView: () -> Unit,
    onCycleInstrument: () -> Unit,
    compact: Boolean,
    modifier: Modifier = Modifier,
) {
    val gap = if (compact) 4.dp else 6.dp
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(gap),
    ) {
        // Primary: large Pause. Secondary: Staff/Cents toggle.
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Button(
                onClick = onPauseToggle,
                colors = ButtonDefaults.buttonColors(containerColor = IntuneColors.Accent),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 10.dp),
                modifier = Modifier
                    .weight(1.35f)
                    .height(48.dp),
            ) {
                Text(
                    if (paused) "Play" else "Pause",
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                )
            }
            FilledTonalButton(
                onClick = onToggleTraceView,
                contentPadding = CompactBtnPadding,
                modifier = Modifier
                    .weight(1f)
                    .height(48.dp),
            ) {
                Text(
                    if (traceViewMode == TraceViewMode.Cents) "Staff" else "Cents",
                    fontSize = 13.sp,
                    maxLines = 1,
                )
            }
        }
        if (traceViewMode == TraceViewMode.Staff) {
            // Smaller “change instrument” control — label shows current + affordance
            FilledTonalButton(
                onClick = onCycleInstrument,
                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(32.dp),
            ) {
                Text(
                    text = "Instrument · ${staffInstrument.label}  ›",
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                    softWrap = false,
                )
            }
        }
        if (paused) {
            Text(
                "Drag chart to review",
                fontSize = 10.sp,
                color = IntuneColors.TextDim,
                modifier = Modifier.fillMaxWidth(),
                textAlign = TextAlign.Center,
            )
        }
        CompactStepperRow(
            label = "Scroll",
            valueLabel = "%.1fs".format(windowSec),
            decreaseLabel = "−",
            increaseLabel = "+",
            onDecrease = onScrollSlower,
            onIncrease = onScrollFaster,
        )
        CompactStepperRow(
            label = "Zone",
            valueLabel = "±%.0f¢".format(inTuneThreshold),
            decreaseLabel = "−",
            increaseLabel = "+",
            onDecrease = onTuneNarrower,
            onIncrease = onTuneWider,
        )
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
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(IntuneColors.Panel)
            .padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(
            label,
            fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold,
            color = IntuneColors.TextPrimary,
            modifier = Modifier.width(52.dp),
            maxLines = 1,
        )
        FilledTonalButton(
            onClick = onDecrease,
            contentPadding = PaddingValues(0.dp),
            modifier = Modifier.size(CompactBtnHeight),
        ) {
            Text(decreaseLabel, fontSize = 16.sp, fontWeight = FontWeight.Bold)
        }
        Text(
            valueLabel,
            modifier = Modifier.weight(1f),
            textAlign = TextAlign.Center,
            fontSize = 13.sp,
            fontWeight = FontWeight.Medium,
            color = IntuneColors.TextPrimary,
        )
        FilledTonalButton(
            onClick = onIncrease,
            contentPadding = PaddingValues(0.dp),
            modifier = Modifier.size(CompactBtnHeight),
        ) {
            Text(increaseLabel, fontSize = 16.sp, fontWeight = FontWeight.Bold)
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