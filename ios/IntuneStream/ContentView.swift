import SwiftUI

struct ContentView: View {
    @StateObject private var ble = BLEManager()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                HStack {
                    Circle()
                        .fill(ble.isConnected ? Color.green : Color.orange)
                        .frame(width: 10, height: 10)
                    Text(ble.status)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                    Spacer()
                    Button(ble.isConnected ? "Disconnect" : "Connect") {
                        ble.toggleScan()
                    }
                    .buttonStyle(.borderedProminent)
                }
                .padding()

                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 4) {
                            if ble.lines.isEmpty {
                                Text("No data yet.\n\n1. Flash the ESP32 (Intune BLE firmware)\n2. Tap Connect\n3. CSV lines appear here")
                                    .font(.body)
                                    .foregroundStyle(.secondary)
                                    .padding(.top, 8)
                            } else {
                                ForEach(Array(ble.lines.enumerated()), id: \.offset) { idx, line in
                                    Text(line)
                                        .font(.system(.caption, design: .monospaced))
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .id(idx)
                                }
                            }
                        }
                        .padding(.horizontal)
                    }
                    .onChange(of: ble.lines.count) { _, _ in
                        if let last = ble.lines.indices.last {
                            withAnimation {
                                proxy.scrollTo(last, anchor: .bottom)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Intune Stream")
        }
    }
}

#Preview {
    ContentView()
}