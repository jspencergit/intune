#include <Arduino.h>

#include "ble_uart.h"

// Teensy UART → BLE bridge for Intune Stream (Android).
//
// Wiring (one-way): Teensy pin 17 (Serial4 TX) → ESP32 UART RX. Common GND required.
//
// ESP32 RX pin options (DO NOT use RX0 — that is GPIO3 / USB-serial):
//   GPIO16  — best (hardware UART2 RX, no boot quirks)
//   GPIO13  — ok (D13 on most dev boards)
//
// CSV format from Teensy: timestamp_ms,Note,Cents,probability,level

constexpr uint32_t TEENSY_BAUD = 115200;  // must match Teensy Serial4 baud
constexpr int TEENSY_RX_PIN = 13;         // D13 / GPIO13 (or use 16 = UART2 RX if you rewire)
constexpr int TEENSY_TX_PIN = 17;         // unused TX — keeps UART driver fully initialized
constexpr size_t LINE_BUF_LEN = 96;

static char line_buf[LINE_BUF_LEN];
static size_t line_len = 0;
static uint32_t lines_received = 0;
static uint32_t lines_forwarded = 0;
static uint32_t last_stats_ms = 0;
static char last_line[LINE_BUF_LEN];

static void reset_line_buf() {
    line_len = 0;
    line_buf[0] = '\0';
}

static void forward_line() {
    if (line_len == 0) return;
    lines_received++;
    strncpy(last_line, line_buf, sizeof(last_line) - 1);
    last_line[sizeof(last_line) - 1] = '\0';
    // Android parser splits on '\n' — must include it (scale simulator did).
    line_buf[line_len++] = '\n';
    ble_uart_notify_line(line_buf, line_len);
    if (ble_uart_has_client()) lines_forwarded++;
    reset_line_buf();
}

static void handle_rx_char(char c) {
    if (c == '\r') return;
    if (c == '\n') {
        forward_line();
        return;
    }
    if (line_len < LINE_BUF_LEN - 1) {
        line_buf[line_len++] = c;
        line_buf[line_len] = '\0';
    } else {
        reset_line_buf();
    }
}

static void drain_teensy_uart() {
    while (Serial2.available() > 0) {
        handle_rx_char(static_cast<char>(Serial2.read()));
    }
}

void setup() {
    Serial.begin(115200);
    delay(800);

    Serial2.setRxBufferSize(2048);
    Serial2.begin(TEENSY_BAUD, SERIAL_8N1, TEENSY_RX_PIN, TEENSY_TX_PIN);
    ble_uart_begin("Intune");

    Serial.println();
    Serial.println("=== Intune ESP32 UART -> BLE bridge ===");
    Serial.printf("Teensy UART: GPIO%d RX @ %lu baud (TX GPIO%d unused)\n",
                  TEENSY_RX_PIN, (unsigned long)TEENSY_BAUD, TEENSY_TX_PIN);
    Serial.println("BLE name: Intune  (Nordic UART Service)");
    Serial.println("Do NOT wire to RX0 (GPIO3) — that is the USB-serial pin.");
}

void loop() {
    drain_teensy_uart();

    const uint32_t now_ms = millis();
    if (now_ms - last_stats_ms >= 5000) {
        last_stats_ms = now_ms;
        Serial.printf("[bridge] uart_lines=%lu ble_fwd=%lu ble_client=%s",
                      (unsigned long)lines_received,
                      (unsigned long)lines_forwarded,
                      ble_uart_has_client() ? "yes" : "no");
        if (last_line[0] != '\0') {
            Serial.printf(" last=\"%s\"", last_line);
        }
        Serial.println();
    }
}