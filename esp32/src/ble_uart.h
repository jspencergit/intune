#pragma once

#include <stddef.h>

// Nordic UART Service (NUS) — standard BLE serial profile used by many apps.
void ble_uart_begin(const char* device_name);
void ble_uart_notify_line(const char* line, size_t len);
bool ble_uart_has_client();