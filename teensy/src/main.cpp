#include <Arduino.h>
#include <Audio.h>
#include <math.h>
#include <string.h>

#include "pitch_detector.h"

/*
 * Intune Teensy Pitch Detection v3
 *
 * Custom overlapping-window YIN (pitch_detector.*) for viola/violin.
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

  Serial.println("=== Intune pitch v3: overlapping YIN (viola/violin) ===");
  Serial.println("=== USB 230400 + Serial4 115200 pin17 | 120 Hz CSV ===");
}

void loop() {
  static uint32_t nextOutputUs = 0;
  constexpr uint32_t OUTPUT_INTERVAL_US = 8333;  // 120 Hz

  static float last_freq = 0.0f;
  static float last_prob = 0.0f;
  static float last_cents = 0.0f;
  static char last_note[12] = {0};
  static int last_midi = -1;
  static uint32_t last_good_us = 0;

  while (pitch1.process()) {
  }

  while (pitch1.available()) {
    float f = pitch1.read();
    float p = pitch1.probability();
    if (!(f > FMIN_HZ * 0.95f && f < FMAX_HZ * 1.05f && p > 0.40f)) {
      continue;
    }

    float midiFloat = 12.0f * log2f(f / 440.0f) + 69.0f;
    int midiNote = (int)lroundf(midiFloat);
    float cents = (midiFloat - (float)midiNote) * 100.0f;

    // Snap exact ±1 octave jumps to previous stable MIDI
    if (last_midi > 0) {
      int d = midiNote - last_midi;
      if (d == 12 || d == -12) {
        midiNote = last_midi;
        float target = 440.0f * powf(2.0f, ((float)last_midi - 69.0f) / 12.0f);
        float f_adj = f;
        while (f_adj > target * 1.5f) f_adj *= 0.5f;
        while (f_adj < target * 0.67f) f_adj *= 2.0f;
        float mf = 12.0f * log2f(f_adj / 440.0f) + 69.0f;
        cents = (mf - (float)midiNote) * 100.0f;
        f = f_adj;
      }
    }

    last_freq = f;
    last_prob = p;
    last_cents = cents;
    last_midi = midiNote;
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

  const float REST_THRESHOLD = 0.0015f;
  const float TRUST_FRESH_LOCK = 0.0040f;
  const uint32_t HOLD_MAX_US = 180000;

  bool hold_ok = (last_note[0] != '\0') &&
                 ((uint32_t)(nowUs - last_good_us) < HOLD_MAX_US);

  if (level > REST_THRESHOLD) {
    if (hold_ok) {
      emitSampleLine(nextOutputUs / 1000, last_note, last_cents, last_prob, level);
    } else {
      emitSampleLine(nextOutputUs / 1000, "---", 0.0f, 0.0f, level);
    }
  } else {
    last_freq = 0.0f;
    last_prob = 0.0f;
    last_cents = 0.0f;
    last_midi = -1;
    last_note[0] = '\0';
    emitSampleLine(nextOutputUs / 1000, "---", 0.0f, 0.0f, level);
  }

  (void)TRUST_FRESH_LOCK;
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
