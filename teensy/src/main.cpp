#include <Arduino.h>
#include <Audio.h>
#include <math.h>
#include <string.h>

#include "pitch_detector.h"

/*
 * Intune Teensy Pitch Detection v6
 *
 * Custom overlapping-window YIN + Goertzel harmonic referee (k=1/2,2,3)
 * for viola/violin open-string octave / partial locks.
 * Constant 120 Hz CSV on USB Serial + Serial4 (ESP32 BLE bridge).
 *
 * Format: timestamp_ms,Note,Cents,probability,level
 *
 * Hardware (INMP441):
 *   VDD→3.3V  GND→GND  SCK→21  WS→20  SD→8  L/R→pin0 LOW
 *   Serial4 TX pin 17 @ 115200 → ESP32 UART RX
 */

AudioInputI2S        i2s1;
AudioAnalyzePitchYin pitch1;
AudioAnalyzePeak     peak1;

AudioConnection patchCord1(i2s1, 0, pitch1, 0);
AudioConnection patchCord2(i2s1, 0, peak1, 0);

const char* noteToName(int midi);

constexpr uint8_t MIC_LR_SELECT_PIN = 0;
constexpr uint32_t USB_BAUD = 230400;
constexpr uint32_t ESP32_BAUD = 115200;

// Viola + violin practical range with margin
constexpr float FMIN_HZ = 120.0f;
constexpr float FMAX_HZ = 2800.0f;

static void emitSampleLine(uint32_t ts_ms, const char* note, float cents, float prob, float level) {
  char line[96];
  snprintf(line, sizeof(line), "%lu,%s,%+.1f,%.2f,%.3f\n",
           (unsigned long)ts_ms, note, cents, prob, level);
  Serial.print(line);
  Serial4.print(line);
}

void setup() {
  Serial.begin(USB_BAUD);
  Serial4.begin(ESP32_BAUD);
  delay(800);

  pinMode(MIC_LR_SELECT_PIN, OUTPUT);
  digitalWrite(MIC_LR_SELECT_PIN, LOW);

  AudioMemory(60);

  pitch1.setRange(FMIN_HZ, FMAX_HZ);
  pitch1.begin(0.12f);

  Serial.println("=== Intune pitch v6: YIN + harmonic referee (x2/x3) ===");
  Serial.println("=== USB 230400 + Serial4 115200 pin17 | 120 Hz CSV ===");
}

void loop() {
  static uint32_t nextOutputUs = 0;
  constexpr uint32_t OUTPUT_INTERVAL_US = 8333;  // 120 Hz

  static float last_prob = 0.0f;
  static float last_cents = 0.0f;
  static char last_note[12] = {0};
  static uint32_t last_good_us = 0;

  while (pitch1.process()) {
  }

  // Short median on frequency suppresses 1–2 frame freckles (C3→G4 partial spikes)
  // without freezing real string changes (new note fills the ring in ~5 hops).
  static float freq_ring[5] = {0};
  static int freq_ring_n = 0;
  static int freq_ring_i = 0;

  while (pitch1.available()) {
    float f = pitch1.read();
    float p = pitch1.probability();
    if (!(f > FMIN_HZ * 0.95f && f < FMAX_HZ * 1.05f && p > 0.40f)) {
      continue;
    }

    freq_ring[freq_ring_i] = f;
    freq_ring_i = (freq_ring_i + 1) % 5;
    if (freq_ring_n < 5) freq_ring_n++;

    float fs[5];
    int n = freq_ring_n;
    for (int i = 0; i < n; i++) fs[i] = freq_ring[i];
    // insertion sort
    for (int i = 1; i < n; i++) {
      float key = fs[i];
      int j = i - 1;
      while (j >= 0 && fs[j] > key) {
        fs[j + 1] = fs[j];
        j--;
      }
      fs[j + 1] = key;
    }
    float f_med = fs[n / 2];
    // Use median freq; keep latest probability for display.
    float midiFloat = 12.0f * log2f(f_med / 440.0f) + 69.0f;
    int midiNote = (int)lroundf(midiFloat);
    float cents = (midiFloat - (float)midiNote) * 100.0f;

    last_prob = p;
    last_cents = cents;
    const char* nm = noteToName(midiNote);
    strncpy(last_note, nm, sizeof(last_note) - 1);
    last_note[sizeof(last_note) - 1] = '\0';
    last_good_us = micros();
  }

  uint32_t nowUs = micros();
  if (nextOutputUs == 0) nextOutputUs = nowUs;
  if ((int32_t)(nowUs - nextOutputUs) < (int32_t)OUTPUT_INTERVAL_US) {
    return;
  }
  nextOutputUs += OUTPUT_INTERVAL_US;
  if ((int32_t)(nowUs - nextOutputUs) > (int32_t)OUTPUT_INTERVAL_US) {
    nextOutputUs = nowUs;
  }

  float level = peak1.read();
  float yin_lvl = pitch1.level();
  if (yin_lvl > level) level = yin_lvl;

  // Hold last good pitch only briefly when YIN misses a hop (attack/noise).
  // Keep this short so a failed lock cannot "stick" on the previous string.
  const float REST_THRESHOLD = 0.0015f;
  const uint32_t HOLD_MAX_US = 80000;  // ~80 ms (was 180 ms)

  bool hold_ok = (last_note[0] != '\0') &&
                 ((uint32_t)(nowUs - last_good_us) < HOLD_MAX_US);

  if (level > REST_THRESHOLD) {
    if (hold_ok) {
      emitSampleLine(nextOutputUs / 1000, last_note, last_cents, last_prob, level);
    } else {
      // Stale lock: clear so UI cannot keep showing the previous note.
      last_prob = 0.0f;
      last_cents = 0.0f;
      last_note[0] = '\0';
      freq_ring_n = 0;
      freq_ring_i = 0;
      emitSampleLine(nextOutputUs / 1000, "---", 0.0f, 0.0f, level);
    }
  } else {
    last_prob = 0.0f;
    last_cents = 0.0f;
    last_note[0] = '\0';
    freq_ring_n = 0;
    freq_ring_i = 0;
    // Drop octave continuity so the next string is not biased by the previous one.
    pitch1.clearContinuity();
    emitSampleLine(nextOutputUs / 1000, "---", 0.0f, 0.0f, level);
  }
}

const char* noteToName(int midi) {
  static const char* names[12] = {"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"};
  static char buf[12];
  if (midi < 0) midi = 0;
  if (midi > 127) midi = 127;
  int octave = (midi / 12) - 1;
  snprintf(buf, sizeof(buf), "%s%d", names[midi % 12], octave);
  return buf;
}
