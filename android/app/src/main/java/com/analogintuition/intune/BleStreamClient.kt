package com.analogintuition.intune

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.UUID

/** Connects to ESP32 Nordic UART Service (same UUIDs as esp32/src/ble_uart.cpp). */
class BleStreamClient(context: Context) {

    companion object {
        private val SERVICE_UUID = UUID.fromString("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
        private val TX_UUID = UUID.fromString("6E400003-B5A3-F393-E0A9-E50E24DCCA9E")
        private val CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        private const val TARGET_NAME = "Intune"
        private const val MAX_SAMPLES = 2400
        private const val SCAN_TIMEOUT_MS = 15_000L
    }

    data class UiState(
        val status: String = "Idle",
        val samples: List<PitchSample> = emptyList(),
        val scanning: Boolean = false,
        val connected: Boolean = false,
    )

    private val appContext = context.applicationContext
    private val bluetoothManager =
        appContext.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val adapter: BluetoothAdapter? = bluetoothManager.adapter
    private val handler = Handler(Looper.getMainLooper())

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    private var gatt: BluetoothGatt? = null
    private var lineBuffer = StringBuilder()
    private var streamAnchorMs = 0L
    private var scanTimeoutRunnable: Runnable? = null

    fun hostNowMs(): Float {
        if (streamAnchorMs == 0L) streamAnchorMs = SystemClock.elapsedRealtime()
        return (SystemClock.elapsedRealtime() - streamAnchorMs).toFloat()
    }

    fun resetStreamClock() {
        streamAnchorMs = SystemClock.elapsedRealtime()
    }

    private fun deviceLabel(result: ScanResult): String {
        val name = result.device.name ?: result.scanRecord?.deviceName
        return name?.takeIf { it.isNotBlank() } ?: TARGET_NAME
    }

    private fun matchesIntune(result: ScanResult): Boolean {
        val name = (result.device.name ?: result.scanRecord?.deviceName ?: "").trim()
        if (name.equals(TARGET_NAME, ignoreCase = true)) return true
        if (name.contains("intune", ignoreCase = true)) return true
        val serviceUuids = result.scanRecord?.serviceUuids?.map { it.uuid } ?: emptyList()
        return serviceUuids.contains(SERVICE_UUID)
    }

    private val scanCallback = object : ScanCallback() {
        @SuppressLint("MissingPermission")
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            if (!matchesIntune(result)) return
            stopScanInternal()

            val device = result.device ?: return
            val label = deviceLabel(result)
            _state.value = _state.value.copy(
                scanning = false,
                status = "Connecting to $label…",
            )

            gatt?.close()
            gatt = device.connectGatt(appContext, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
        }

        @SuppressLint("MissingPermission")
        override fun onScanFailed(errorCode: Int) {
            stopScanInternal()
            _state.value = _state.value.copy(
                scanning = false,
                status = "Scan failed ($errorCode)",
            )
        }
    }

    private val gattCallback = object : BluetoothGattCallback() {
        @SuppressLint("MissingPermission")
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    if (status != BluetoothGatt.GATT_SUCCESS) {
                        cleanupGatt("Connect failed ($status)")
                        return
                    }
                    this@BleStreamClient.gatt = gatt
                    _state.value = _state.value.copy(connected = true, status = "Negotiating link…")
                    if (!gatt.requestMtu(247)) {
                        gatt.discoverServices()
                    }
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    val msg = if (status == BluetoothGatt.GATT_SUCCESS) {
                        "Disconnected"
                    } else {
                        "Connection lost ($status)"
                    }
                    cleanupGatt(msg)
                }
            }
        }

        @SuppressLint("MissingPermission")
        override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
            gatt.discoverServices()
        }

        @SuppressLint("MissingPermission")
        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                _state.value = _state.value.copy(status = "Service discovery failed ($status)")
                cleanupGatt("Service discovery failed")
                return
            }
            val service = gatt.getService(SERVICE_UUID)
            val tx = service?.getCharacteristic(TX_UUID)
            if (tx == null) {
                _state.value = _state.value.copy(status = "Nordic UART TX not found")
                cleanupGatt("UART service missing")
                return
            }
            gatt.setCharacteristicNotification(tx, true)
            val cccd = tx.getDescriptor(CCCD_UUID)
            if (cccd == null) {
                _state.value = _state.value.copy(status = "Notify descriptor missing")
                return
            }
            _state.value = _state.value.copy(status = "Enabling notifications…")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                val result = gatt.writeDescriptor(
                    cccd,
                    BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE,
                )
                if (result != BluetoothGatt.GATT_SUCCESS) {
                    _state.value = _state.value.copy(status = "writeDescriptor failed ($result)")
                }
            } else {
                @Suppress("DEPRECATION")
                cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                @Suppress("DEPRECATION")
                val queued = gatt.writeDescriptor(cccd)
                if (!queued) {
                    _state.value = _state.value.copy(status = "writeDescriptor failed to queue")
                }
            }
        }

        override fun onDescriptorWrite(
            gatt: BluetoothGatt,
            descriptor: BluetoothGattDescriptor,
            status: Int
        ) {
            if (descriptor.uuid != CCCD_UUID) return
            if (status == BluetoothGatt.GATT_SUCCESS) {
                resetStreamClock()
                lineBuffer = StringBuilder()
                _state.value = _state.value.copy(status = "Streaming…", samples = emptyList())
            } else {
                _state.value = _state.value.copy(status = "Enable notify failed ($status)")
            }
        }

        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray
        ) {
            handleIncoming(String(value, Charsets.UTF_8))
        }

        @Deprecated("Deprecated in API 33")
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic
        ) {
            @Suppress("DEPRECATION")
            val value = characteristic.value ?: return
            handleIncoming(String(value, Charsets.UTF_8))
        }
    }

    private fun handleIncoming(chunk: String) {
        if (chunk.isEmpty()) return
        lineBuffer.append(chunk)
        val text = lineBuffer.toString()
        val parts = text.split('\n')
        lineBuffer = StringBuilder(parts.last())
        val complete = parts.dropLast(1).map { it.trim() }.filter { it.isNotEmpty() }.toMutableList()
        val pending = parts.last().trim()
        if (pending.isNotEmpty() && PitchCsvParser.parse(pending) != null) {
            complete.add(pending)
            lineBuffer = StringBuilder()
        }
        if (complete.isEmpty()) return
        val parsed = complete.mapNotNull { PitchCsvParser.parse(it) }
        if (parsed.isEmpty()) return
        val stamped = PitchCsvParser.assignHostTimestamps(parsed, hostNowMs())
        val merged = (_state.value.samples + stamped).takeLast(MAX_SAMPLES)
        _state.value = _state.value.copy(samples = merged)
    }

    @SuppressLint("MissingPermission")
    fun toggleConnection() {
        if (_state.value.connected || _state.value.scanning) {
            disconnect()
            return
        }
        if (adapter == null || !adapter.isEnabled) {
            _state.value = _state.value.copy(status = "Turn on Bluetooth")
            return
        }
        cleanupGatt(clearStatus = false)
        lineBuffer = StringBuilder()
        _state.value = UiState(status = "Scanning for Intune…", scanning = true)

        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()
        adapter.bluetoothLeScanner.startScan(null, settings, scanCallback)

        scanTimeoutRunnable?.let { handler.removeCallbacks(it) }
        scanTimeoutRunnable = Runnable {
            if (_state.value.scanning) {
                stopScanInternal()
                _state.value = _state.value.copy(
                    scanning = false,
                    status = "Intune not found — power-cycle ESP32 and retry",
                )
            }
        }
        handler.postDelayed(scanTimeoutRunnable!!, SCAN_TIMEOUT_MS)
    }

    @SuppressLint("MissingPermission")
    private fun stopScanInternal() {
        scanTimeoutRunnable?.let { handler.removeCallbacks(it) }
        scanTimeoutRunnable = null
        adapter?.bluetoothLeScanner?.stopScan(scanCallback)
    }

    @SuppressLint("MissingPermission")
    fun disconnect() {
        stopScanInternal()
        val activeGatt = gatt
        if (activeGatt == null) {
            _state.value = _state.value.copy(
                connected = false,
                scanning = false,
                status = "Disconnected",
                samples = emptyList(),
            )
            return
        }
        _state.value = _state.value.copy(
            connected = false,
            scanning = false,
            status = "Disconnecting…",
        )
        activeGatt.disconnect()
    }

    @SuppressLint("MissingPermission")
    private fun cleanupGatt(status: String? = null, clearStatus: Boolean = true) {
        stopScanInternal()
        gatt?.close()
        gatt = null
        streamAnchorMs = 0L
        if (clearStatus && status != null) {
            _state.value = _state.value.copy(
                connected = false,
                scanning = false,
                status = status,
                samples = emptyList(),
            )
        } else if (clearStatus) {
            _state.value = _state.value.copy(
                connected = false,
                scanning = false,
                samples = emptyList(),
            )
        }
    }
}