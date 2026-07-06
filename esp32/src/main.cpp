#include <Arduino.h>
#include <math.h>

// Teensy-compatible CSV stream for visualizer bring-up (USB serial monitor / PC viz).
//   timestamp_ms,Note,Cents,probability,level
//
// Plays C major up + down with the same per-note detune map as generate_test_scale.py.

constexpr uint32_t OUTPUT_INTERVAL_US = 8333;  // 120 Hz — matches Teensy + visualizer
constexpr uint32_t NOTE_HOLD_MS = 1000;
constexpr uint32_t REST_MS = 180;

struct ScaleEntry {
    const char* note;
    float detune_cents;
};

// C major viola range, slightly detuned (c-major preset from generate_test_scale.py).
static const ScaleEntry kScaleUp[] = {
    {"C3", +7.0f},  {"D3", -5.0f},  {"E3", +10.0f}, {"F3", -6.0f},  {"G3", +8.0f},
    {"A3", -9.0f},  {"B3", +4.0f},  {"C4", -7.0f},  {"D4", +11.0f}, {"E4", -5.0f},
    {"F4", +6.0f},  {"G4", -8.0f},  {"A4", +9.0f},  {"B4", -4.0f},  {"C5", +7.0f},
    {"D5", -10.0f}, {"E5", +5.0f},
};
static const size_t kScaleUpLen = sizeof(kScaleUp) / sizeof(kScaleUp[0]);

static const ScaleEntry kScaleDown[] = {
    {"D5", -10.0f}, {"C5", +7.0f},  {"B4", -4.0f},  {"A4", +9.0f},  {"G4", -8.0f},
    {"F4", +6.0f},  {"E4", -5.0f},  {"D4", +11.0f}, {"C4", -7.0f},  {"B3", +4.0f},
    {"A3", -9.0f},  {"G3", +8.0f},  {"F3", -6.0f},  {"E3", +10.0f}, {"D3", -5.0f},
    {"C3", +7.0f},
};
static const size_t kScaleDownLen = sizeof(kScaleDown) / sizeof(kScaleDown[0]);

enum class Phase { Note, Rest };

static const ScaleEntry* phase_note_ = nullptr;
static float phase_cents_ = 0.0f;
static Phase phase_ = Phase::Rest;
static uint32_t phase_elapsed_ms_ = 0;
static uint32_t phase_duration_ms_ = REST_MS;
static size_t scale_idx_ = 0;
static bool scale_ascending_ = true;
static float vibrato_phase_ = 0.0f;

static void begin_note(const ScaleEntry& entry) {
    phase_note_ = &entry;
    phase_cents_ = entry.detune_cents;
    phase_ = Phase::Note;
    phase_elapsed_ms_ = 0;
    phase_duration_ms_ = NOTE_HOLD_MS;
}

static void begin_rest() {
    phase_note_ = nullptr;
    phase_ = Phase::Rest;
    phase_elapsed_ms_ = 0;
    phase_duration_ms_ = REST_MS;
}

static void advance_scale() {
    if (scale_ascending_) {
        if (scale_idx_ < kScaleUpLen) {
            begin_note(kScaleUp[scale_idx_++]);
            if (scale_idx_ >= kScaleUpLen) {
                scale_ascending_ = false;
                scale_idx_ = 0;
            }
            return;
        }
    } else {
        if (scale_idx_ < kScaleDownLen) {
            begin_note(kScaleDown[scale_idx_++]);
            if (scale_idx_ >= kScaleDownLen) {
                scale_ascending_ = true;
                scale_idx_ = 0;
            }
            return;
        }
    }
    begin_rest();
}

static void tick_phase(uint32_t dt_ms) {
    phase_elapsed_ms_ += dt_ms;
    if (phase_elapsed_ms_ < phase_duration_ms_) return;

    if (phase_ == Phase::Note) {
        begin_rest();
    } else {
        advance_scale();
    }
}

static void emit_sample(uint32_t ts_ms) {
    vibrato_phase_ += 0.11f;
    const float vibrato = sinf(vibrato_phase_) * 1.5f;  // subtle motion on top of detune

    if (phase_ == Phase::Note && phase_note_ != nullptr) {
        const float cents = phase_cents_ + vibrato;
        const float prob = 0.90f;
        const float level = 0.022f;
        Serial.printf("%lu,%s,%+.1f,%.2f,%.3f\n",
                      (unsigned long)ts_ms, phase_note_->note, cents, prob, level);
    } else {
        Serial.printf("%lu,---,0,0.00,%.3f\n", (unsigned long)ts_ms, 0.0003f);
    }
}

void setup() {
    Serial.begin(115200);
    delay(800);
    Serial.println();
    Serial.println("=== Intune ESP32 scale simulator ===");
    Serial.println("C major up/down, slightly detuned @ 120 Hz");
    Serial.println("Format: timestamp_ms,Note,Cents,probability,level");
    begin_rest();
}

void loop() {
    static uint32_t next_output_us = 0;
    static uint32_t last_tick_ms = 0;

    const uint32_t now_us = micros();
    if (next_output_us == 0) {
        next_output_us = now_us;
        last_tick_ms = millis();
    }

    const uint32_t now_ms = millis();
    const uint32_t dt_ms = now_ms - last_tick_ms;
    if (dt_ms > 0) {
        tick_phase(dt_ms);
        last_tick_ms = now_ms;
    }

    if ((int32_t)(now_us - next_output_us) >= (int32_t)OUTPUT_INTERVAL_US) {
        next_output_us += OUTPUT_INTERVAL_US;
        if ((int32_t)(now_us - next_output_us) > (int32_t)OUTPUT_INTERVAL_US) {
            next_output_us = now_us;
        }
        emit_sample(next_output_us / 1000);
    }
}