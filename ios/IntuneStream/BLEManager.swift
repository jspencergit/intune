import CoreBluetooth
import Foundation

/// Connects to the ESP32 Nordic UART Service and streams CSV lines.
final class BLEManager: NSObject, ObservableObject {
    // Nordic UART Service (same UUIDs as esp32/src/ble_uart.cpp)
    private let serviceUUID = CBUUID(string: "6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
    private let txUUID = CBUUID(string: "6E400003-B5A3-F393-E0A9-E50E24DCCA9E")
    private let targetName = "Intune"

    @Published var status = "Idle"
    @Published var lines: [String] = []
    @Published var isScanning = false
    @Published var isConnected = false

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var txCharacteristic: CBCharacteristic?
    private var lineBuffer = ""

    private let maxLines = 400

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: .main)
    }

    func toggleScan() {
        if isConnected {
            disconnect()
            return
        }
        if isScanning {
            central.stopScan()
            isScanning = false
            status = "Scan stopped"
        } else {
            guard central.state == .poweredOn else {
                status = "Bluetooth off or unavailable"
                return
            }
            lines.removeAll()
            lineBuffer = ""
            isScanning = true
            status = "Scanning for Intune…"
            central.scanForPeripherals(
                withServices: [serviceUUID],
                options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
            )
        }
    }

    func disconnect() {
        if let peripheral {
            central.cancelPeripheralConnection(peripheral)
        }
        resetConnection()
        status = "Disconnected"
    }

    private func resetConnection() {
        peripheral = nil
        txCharacteristic = nil
        isConnected = false
        isScanning = false
    }

    private func appendLine(_ line: String) {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        lines.append(trimmed)
        if lines.count > maxLines {
            lines.removeFirst(lines.count - maxLines)
        }
    }

    private func handleIncoming(_ data: Data) {
        guard let chunk = String(data: data, encoding: .utf8) else { return }
        lineBuffer += chunk
        while let newline = lineBuffer.firstIndex(of: "\n") {
            let line = String(lineBuffer[..<newline])
            lineBuffer = String(lineBuffer[lineBuffer.index(after: newline)...])
            appendLine(line)
        }
    }
}

extension BLEManager: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            status = "Bluetooth ready — tap Connect"
        case .poweredOff:
            status = "Turn on Bluetooth"
            resetConnection()
        case .unauthorized:
            status = "Bluetooth permission denied — check Settings"
        default:
            status = "Bluetooth state: \(central.state.rawValue)"
        }
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String) ?? ""
        guard name == targetName || name.isEmpty else { return }

        central.stopScan()
        isScanning = false
        self.peripheral = peripheral
        peripheral.delegate = self
        status = "Connecting to \(name.isEmpty ? "Intune" : name)…"
        central.connect(peripheral, options: nil)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        isConnected = true
        status = "Connected — discovering services"
        peripheral.discoverServices([serviceUUID])
    }

    func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: Error?
    ) {
        resetConnection()
        status = "Connect failed: \(error?.localizedDescription ?? "unknown")"
    }

    func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: Error?
    ) {
        resetConnection()
        status = error == nil ? "Disconnected" : "Lost: \(error!.localizedDescription)"
    }
}

extension BLEManager: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error {
            status = "Service error: \(error.localizedDescription)"
            return
        }
        guard let service = peripheral.services?.first(where: { $0.uuid == serviceUUID }) else {
            status = "Nordic UART service not found"
            return
        }
        peripheral.discoverCharacteristics([txUUID], for: service)
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverCharacteristicsFor service: CBService,
        error: Error?
    ) {
        if let error {
            status = "Characteristic error: \(error.localizedDescription)"
            return
        }
        guard let tx = service.characteristics?.first(where: { $0.uuid == txUUID }) else {
            status = "TX characteristic not found"
            return
        }
        txCharacteristic = tx
        peripheral.setNotifyValue(true, for: tx)
        status = "Streaming…"
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error {
            status = "Read error: \(error.localizedDescription)"
            return
        }
        guard characteristic.uuid == txUUID, let data = characteristic.value else { return }
        handleIncoming(data)
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateNotificationStateFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error {
            status = "Notify error: \(error.localizedDescription)"
        }
    }
}