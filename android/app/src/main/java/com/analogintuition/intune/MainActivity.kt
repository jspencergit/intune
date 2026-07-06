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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.ui.unit.Dp
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
                paused = viewModel.paused,
                scrubOffsetMs = viewModel.scrubOffsetMs,
                onScrub = viewModel::setScrubOffset,
                onPauseToggle = { viewModel.togglePause(viewModel.displayNowMs) },
                onScrollSlower = viewModel::scrollSlower,
                onScrollFaster = viewModel::scrollFaster,
                onTuneWider = viewModel::widenTuneZone,
                onTuneNarrower = viewModel::narrowTuneZone,
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
                paused = viewModel.paused,
                scrubOffsetMs = viewModel.scrubOffsetMs,
                onScrub = viewModel::setScrubOffset,
                onPauseToggle = { viewModel.togglePause(viewModel.displayNowMs) },
                onScrollSlower = viewModel::scrollSlower,
                onScrollFaster = viewModel::scrollFaster,
                onTuneWider = viewModel::widenTuneZone,
                onTuneNarrower = viewModel::narrowTuneZone,
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
    paused: Boolean,
    scrubOffsetMs: Float,
    onScrub: (Float) -> Unit,
    onPauseToggle: () -> Unit,
    onScrollSlower: () -> Unit,
    onScrollFaster: () -> Unit,
    onTuneWider: () -> Unit,
    onTuneNarrower: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxSize()) {
        LiveNoteCard(
            sample = focusSample,
            inTuneThreshold = inTuneThreshold,
            layout = NoteCardLayout.Portrait,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp),
        )
        Spacer(modifier = Modifier.height(6.dp))
        Box(
            modifier = Modifier
                .weight(0.38f)
                .fillMaxWidth()
                .padding(horizontal = 16.dp),
        ) {
            CentsChartPanel(
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
        Box(
            modifier = Modifier
                .weight(0.34f)
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 4.dp),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState()),
            ) {
                ControlPanel(
                    paused = paused,
                    windowSec = windowSec,
                    inTuneThreshold = inTuneThreshold,
                    onPauseToggle = onPauseToggle,
                    onScrollSlower = onScrollSlower,
                    onScrollFaster = onScrollFaster,
                    onTuneWider = onTuneWider,
                    onTuneNarrower = onTuneNarrower,
                    compact = false,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

@Composable
private fun LandscapePracticeLayout(
    focusSample: PitchSample?,
    samples: List<PitchSample>,
    displayNowMs: Float,
    windowSec: Float,
    inTuneThreshold: Float,
    paused: Boolean,
    scrubOffsetMs: Float,
    onScrub: (Float) -> Unit,
    onPauseToggle: () -> Unit,
    onScrollSlower: () -> Unit,
    onScrollFaster: () -> Unit,
    onTuneWider: () -> Unit,
    onTuneNarrower: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 12.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(
            modifier = Modifier
                .width(280.dp)
                .fillMaxHeight(),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
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
                    onPauseToggle = onPauseToggle,
                    onScrollSlower = onScrollSlower,
                    onScrollFaster = onScrollFaster,
                    onTuneWider = onTuneWider,
                    onTuneNarrower = onTuneNarrower,
                    compact = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxHeight(),
        ) {
            CentsChartPanel(
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
private fun CentsChartPanel(
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

    fun updateScrub(x: Float) {
        if (chartWidthPx > 0f) {
            onScrub(CentsChartGeometry.xToScrubOffsetMs(x, chartWidthPx, windowMs))
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
        CentsTraceCanvas(
            samples = samples,
            displayNowMs = displayNowMs,
            windowSec = windowSec,
            inTuneThreshold = inTuneThreshold,
            paused = paused,
            scrubOffsetMs = scrubOffsetMs,
            modifier = Modifier.fillMaxSize(),
        )
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
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(10.dp)
                .clip(CircleShape)
                .background(
                    when {
                        connected && status.contains("Streaming") -> IntuneColors.InTune
                        connected -> IntuneColors.Accent
                        else -> IntuneColors.Rest
                    },
                ),
        )
        Spacer(modifier = Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text("Intune", fontWeight = FontWeight.SemiBold, color = IntuneColors.TextPrimary)
            Text(status, fontSize = 13.sp, color = IntuneColors.TextDim)
        }
        FilledTonalButton(onClick = onConnectClick) {
            Text(if (connected) "Disconnect" else "Connect")
        }
    }
}

private enum class NoteCardLayout { Portrait, Compact }

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
        isRest -> "waiting for pitch"
        abs(cents) < inTuneThreshold -> "in tune"
        cents > 0f -> "sharp"
        else -> "flat"
    }
    val noteSize = when (layout) {
        NoteCardLayout.Portrait -> 48.sp
        NoteCardLayout.Compact -> 44.sp
    }
    val centsSize = when (layout) {
        NoteCardLayout.Portrait -> 26.sp
        NoteCardLayout.Compact -> 22.sp
    }
    val verticalPad = when (layout) {
        NoteCardLayout.Portrait -> 10.dp
        NoteCardLayout.Compact -> 12.dp
    }

    Column(
        modifier = modifier
            .clip(RoundedCornerShape(16.dp))
            .background(IntuneColors.Panel)
            .padding(horizontal = 16.dp, vertical = verticalPad),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("CENTS FOCUS", fontSize = 11.sp, color = IntuneColors.TextDim, letterSpacing = 1.5.sp)
        Spacer(modifier = Modifier.height(4.dp))
        if (layout == NoteCardLayout.Portrait) {
            Row(
                verticalAlignment = Alignment.Bottom,
                horizontalArrangement = Arrangement.Center,
            ) {
                Text(
                    text = note,
                    fontSize = noteSize,
                    fontWeight = FontWeight.Bold,
                    color = col,
                )
                if (!isRest && sample != null) {
                    Spacer(modifier = Modifier.width(10.dp))
                    Text(
                        text = "%+.1f ¢".format(cents),
                        fontSize = centsSize,
                        fontWeight = FontWeight.Medium,
                        color = col.copy(alpha = 0.9f),
                    )
                }
            }
        } else {
            Text(
                text = note,
                fontSize = noteSize,
                fontWeight = FontWeight.Bold,
                color = col,
            )
            if (!isRest && sample != null) {
                Text(
                    text = "%+.1f ¢".format(cents),
                    fontSize = centsSize,
                    fontWeight = FontWeight.Medium,
                    color = col.copy(alpha = 0.9f),
                )
            }
        }
        Text(qual, fontSize = 13.sp, color = IntuneColors.TextDim)
        Text(
            "in-tune zone ±%.0f¢".format(inTuneThreshold),
            fontSize = 11.sp,
            color = IntuneColors.TuneMarker.copy(alpha = 0.85f),
        )
    }
}

@Composable
private fun ControlPanel(
    paused: Boolean,
    windowSec: Float,
    inTuneThreshold: Float,
    onPauseToggle: () -> Unit,
    onScrollSlower: () -> Unit,
    onScrollFaster: () -> Unit,
    onTuneWider: () -> Unit,
    onTuneNarrower: () -> Unit,
    compact: Boolean,
    modifier: Modifier = Modifier,
) {
    val rowSpacing = if (compact) 6.dp else 8.dp
    val rowPadding = if (compact) 8.dp else 12.dp
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(rowSpacing),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Button(
                onClick = onPauseToggle,
                colors = ButtonDefaults.buttonColors(containerColor = IntuneColors.Accent),
                modifier = Modifier.weight(1f),
            ) {
                Text(if (paused) "Play" else "Pause")
            }
        }
        if (paused) {
            Text(
                "Drag chart to review",
                fontSize = 11.sp,
                color = IntuneColors.TextDim,
                modifier = Modifier.fillMaxWidth(),
                textAlign = TextAlign.Center,
            )
        }
        ControlRow(
            label = "Scroll speed",
            hint = "%.1fs visible window".format(windowSec),
            decreaseLabel = "Slower",
            increaseLabel = "Faster",
            onDecrease = onScrollSlower,
            onIncrease = onScrollFaster,
            valueLabel = "%.1fs".format(windowSec),
            compact = compact,
            contentPadding = rowPadding,
        )
        ControlRow(
            label = "In-tune zone",
            hint = "±%.0f¢ from perfect pitch".format(inTuneThreshold),
            decreaseLabel = "Narrow",
            increaseLabel = "Widen",
            onDecrease = onTuneNarrower,
            onIncrease = onTuneWider,
            valueLabel = "±%.0f¢".format(inTuneThreshold),
            compact = compact,
            contentPadding = rowPadding,
        )
    }
}

@Composable
private fun ControlRow(
    label: String,
    hint: String,
    decreaseLabel: String,
    increaseLabel: String,
    onDecrease: () -> Unit,
    onIncrease: () -> Unit,
    valueLabel: String,
    compact: Boolean,
    contentPadding: Dp,
) {
    val labelSize = if (compact) 11.sp else 12.sp
    val hintSize = if (compact) 10.sp else 11.sp
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(IntuneColors.Panel)
            .padding(contentPadding),
    ) {
        Text(label, fontSize = labelSize, fontWeight = FontWeight.SemiBold, color = IntuneColors.TextPrimary)
        Text(hint, fontSize = hintSize, color = IntuneColors.TextDim, modifier = Modifier.padding(top = 2.dp))
        Spacer(modifier = Modifier.height(if (compact) 6.dp else 8.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            FilledTonalButton(onClick = onDecrease, modifier = Modifier.weight(1f)) {
                Text(decreaseLabel)
            }
            Text(
                valueLabel,
                modifier = Modifier.width(80.dp),
                textAlign = TextAlign.Center,
                fontWeight = FontWeight.Medium,
                color = IntuneColors.TextPrimary,
            )
            FilledTonalButton(onClick = onIncrease, modifier = Modifier.weight(1f)) {
                Text(increaseLabel)
            }
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