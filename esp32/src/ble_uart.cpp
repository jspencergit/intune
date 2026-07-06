#include "ble_uart.h"

#include <NimBLEDevice.h>

// Nordic UART Service UUIDs
static const NimBLEUUID kServiceUuid("6E400001-B5A3-F393-E0A9-E50E24DCCA9E");
static const NimBLEUUID kRxUuid("6E400002-B5A3-F393-E0A9-E50E24DCCA9E");
static const NimBLEUUID kTxUuid("6E400003-B5A3-F393-E0A9-E50E24DCCA9E");

static NimBLECharacteristic* g_tx = nullptr;

class IntuneServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* server, NimBLEConnInfo& conn_info) override {
        // Ask for a faster connection interval (7.5–15 ms) when the central allows it.
        server->updateConnParams(conn_info.getConnHandle(), 6, 12, 0, 400);
    }
};

void ble_uart_begin(const char* device_name) {
    NimBLEDevice::init(device_name);
    NimBLEDevice::setPower(ESP_PWR_LVL_P9);

    NimBLEServer* server = NimBLEDevice::createServer();
    server->setCallbacks(new IntuneServerCallbacks());

    NimBLEService* service = server->createService(kServiceUuid);
    service->createCharacteristic(kRxUuid, NIMBLE_PROPERTY::WRITE_NR);
    g_tx = service->createCharacteristic(kTxUuid, NIMBLE_PROPERTY::NOTIFY);

    // Explicit advert + scan response helps Android/iOS find "Intune" reliably.
    NimBLEAdvertisementData advertisementData;
    advertisementData.setName(device_name);
    advertisementData.setCompleteServices({kServiceUuid});

    NimBLEAdvertisementData scanResponseData;
    scanResponseData.setName(device_name);
    scanResponseData.setCompleteServices({kServiceUuid});

    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    adv->setAdvertisementData(advertisementData);
    adv->setScanResponseData(scanResponseData);
    adv->start();
}

void ble_uart_notify_line(const char* line, size_t len) {
    if (!g_tx || !ble_uart_has_client() || len == 0) return;
    // Chunk to negotiated MTU (default 23 → 20 bytes payload) so lines aren't truncated.
    const uint16_t mtu = NimBLEDevice::getMTU();
    const size_t chunk_max = (mtu > 3) ? (mtu - 3) : 20;
    size_t offset = 0;
    while (offset < len) {
        size_t chunk = len - offset;
        if (chunk > chunk_max) chunk = chunk_max;
        g_tx->setValue(reinterpret_cast<const uint8_t*>(line + offset), chunk);
        g_tx->notify();
        offset += chunk;
    }
}

bool ble_uart_has_client() {
    NimBLEServer* server = NimBLEDevice::getServer();
    return server && server->getConnectedCount() > 0;
}