package com.analogintuition.intune

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.delay
import kotlin.math.abs

class MainActivity : ComponentActivity() {

    private lateinit var bleClient: BleStreamClient

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        if (grants.values.all { it }) {
            bleClient.toggleConnection()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        bleClient = BleStreamClient(this)

        setContent {
            MaterialTheme(
                colorScheme = MaterialTheme.colorScheme.copy(
                    background = IntuneColors.Background,
                    surface = IntuneColors.Panel,
                    primary = IntuneColors.Accent,
                ),
            ) {
                Surface(modifier = Modifier.fillMaxSize(), color = IntuneColors.Background) {
                    val bleState by bleClient.state.collectAsState()
                    IntuneScreen(
                        bleState = bleState,
                        hostNowMs = { bleClient.hostNowMs() },
                        onConnectClick = { ensurePermissionsAndConnect() },
                    )
                }
            }
        }
    }

    override fun onDestroy() {
        bleClient.disconnect()
        super.onDestroy()
    }

    private fun ensurePermissionsAndConnect() {
        val needed = requiredPermissions().filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (needed.isEmpty()) {
            bleClient.toggleConnection()
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
    bleState: BleStreamClient.UiState,
    hostNowMs: () -> Float,
    onConnectClick: () -> Unit,
) {
    var paused by remember { mutableStateOf(false) }
    var pausedAtMs by remember { mutableFloatStateOf(0f) }
    var windowSec by remember { mutableFloatStateOf(8f) }
    var displayNowMs by remember { mutableFloatStateOf(0f) }
    val inTuneThreshold = 5f

    LaunchedEffect(paused, bleState.connected) {
        while (bleState.connected) {
            if (!paused) {
                displayNowMs = hostNowMs()
            }
            delay(16L)
        }
    }

    val latest = bleState.samples.lastOrNull { !it.isRest } ?: bleState.samples.lastOrNull()

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
        } else {
            LiveNoteCard(
                sample = latest,
                inTuneThreshold = inTuneThreshold,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp),
            )
            Spacer(modifier = Modifier.height(8.dp))
            Box(
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 16.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(IntuneColors.Panel),
            ) {
                CentsTraceCanvas(
                    samples = bleState.samples,
                    displayNowMs = if (paused) pausedAtMs else displayNowMs,
                    windowSec = windowSec,
                    inTuneThreshold = inTuneThreshold,
                )
            }
            Spacer(modifier = Modifier.height(8.dp))
            ControlBar(
                paused = paused,
                windowSec = windowSec,
                onPauseToggle = {
                    if (!paused) {
                        pausedAtMs = displayNowMs
                    }
                    paused = !paused
                },
                onSlower = { windowSec = (windowSec + 1f).coerceAtMost(20f) },
                onFaster = { windowSec = (windowSec - 1f).coerceAtLeast(3f) },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
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
            .padding(horizontal = 16.dp, vertical = 12.dp),
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

@Composable
private fun LiveNoteCard(
    sample: PitchSample?,
    inTuneThreshold: Float,
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

    Column(
        modifier = modifier
            .clip(RoundedCornerShape(16.dp))
            .background(IntuneColors.Panel)
            .padding(horizontal = 20.dp, vertical = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("CENTS FOCUS", fontSize = 12.sp, color = IntuneColors.TextDim, letterSpacing = 1.5.sp)
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = note,
            fontSize = 56.sp,
            fontWeight = FontWeight.Bold,
            color = col,
        )
        if (!isRest && sample != null) {
            Text(
                text = "%+.1f ¢".format(cents),
                fontSize = 28.sp,
                fontWeight = FontWeight.Medium,
                color = col.copy(alpha = 0.9f),
            )
        }
        Text(qual, fontSize = 14.sp, color = IntuneColors.TextDim)
    }
}

@Composable
private fun ControlBar(
    paused: Boolean,
    windowSec: Float,
    onPauseToggle: () -> Unit,
    onSlower: () -> Unit,
    onFaster: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Button(
            onClick = onPauseToggle,
            colors = ButtonDefaults.buttonColors(containerColor = IntuneColors.Accent),
        ) {
            Text(if (paused) "Play" else "Pause")
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Scroll", color = IntuneColors.TextDim, fontSize = 13.sp)
            FilledTonalButton(onClick = onSlower) { Text("Slower") }
            Text(
                "%.0fs".format(windowSec),
                color = IntuneColors.TextPrimary,
                fontWeight = FontWeight.Medium,
                modifier = Modifier.width(36.dp),
            )
            FilledTonalButton(onClick = onFaster) { Text("Faster") }
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