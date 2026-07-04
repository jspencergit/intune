// Intune — Raylib Visualizer (C++ edition)
// Fresh, smooth, vibrant, musical-staff aesthetic with light gamification.
// Designed to feel beautiful and non-fatiguing for long practice sessions.
//
// Same serial protocol as the Python visualizer (works with existing Teensy firmware).
// High-FPS GPU-accelerated rendering, multi-pass glowing trace, BPM-synced scrolling,
// pulsing beat grid, optional metronome, in-tune duration + accuracy HUD.
//
// Build with the provided CMakeLists.txt (vcpkg or MSYS2 recommended).
//
// Controls:
//   Space/P        Pause/Resume
//   [ ]            BPM down / up
//   ; '            Visible beats narrower / wider
//   M              Toggle metronome click
//   T              Cycle color theme preset
//   I              Cycle instrument (Viola / Cello / Violin)
//   - =            In-tune threshold down / up (¢)
//   C              Clear
//   Q / Esc        Quit
//   Mouse (paused) Hover trace to inspect pitch + cents
//
// Compile-time note: Raylib 4.5+ or 5.x preferred.

// Windows header conflict prevention (must come before BOTH windows.h and raylib.h)
#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#define NOGDI
#define NOUSER
#define NOMINMAX
#include <windows.h>
#endif

#include "raylib.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <deque>
#include <mutex>
#include <queue>
#include <random>
#include <string>
#include <thread>
#include <vector>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>

// =============================================================================
// CONFIG & CONSTANTS
// =============================================================================

constexpr int   DEFAULT_WIDTH   = 1600;
constexpr int   DEFAULT_HEIGHT  = 960;
constexpr float DEFAULT_BPM     = 80.0f;
constexpr float DEFAULT_BEATS   = 4.0f;
constexpr float RENDER_HZ         = 60.0f;
constexpr float RENDER_STEP_MS    = 1000.0f / RENDER_HZ;  // display vsync
constexpr float DEVICE_HZ         = 120.0f;
constexpr float SAMPLE_INTERVAL_MS = 1000.0f / DEVICE_HZ;
constexpr float GOOD_ZONE_CENTS   = 10.0f;  // visual guide on cents ribbon

struct Config {
    std::string port = "COM3";
    int baud = 230400;
    bool simulate = true;
    bool debug = false;
};

// Musical staff Y mapping (identical semantics to the Python version for compatibility)
constexpr float Y_REST     = 0.8f;
constexpr float Y_C3       = 1.2f;
constexpr float Y_STEP     = 0.4f;   // 0.4 per semitone step in our normalized space

enum class ClefKind { Alto, Bass, Treble };

struct InstrumentProfile {
    const char* name;
    float pitch_min;   // lowest labeled note (C-major range start)
    float pitch_max;   // highest labeled note
    std::vector<float> staff_main;
    ClefKind clef;
    float clef_anchor;   // pitch_y where clef is centered
};

// C-major practice ranges: viola C3–E5, cello C2–C4, violin C4–C6
static const InstrumentProfile INSTRUMENTS[] = {
    { "Viola", 1.2f, 7.6f, {2.4f, 3.2f, 4.0f, 4.8f, 5.6f}, ClefKind::Alto,   4.0f },
    { "Cello", -1.6f, 4.0f, {0.0f, 0.4f, 1.6f, 2.4f, 3.2f}, ClefKind::Bass,   2.4f },
    { "Violin", 4.0f, 8.4f, {4.8f, 5.6f, 6.4f, 7.2f, 8.0f}, ClefKind::Treble, 5.6f },
};

static int g_instrument_idx = 0;
static float g_staff_pitch_min = 1.2f;
static float g_staff_pitch_max = 7.6f;
static std::vector<std::pair<std::string, float>> g_note_labels;
static std::vector<float> g_staff_main;
static std::vector<float> g_staff_ledger;
static const InstrumentProfile* g_inst = &INSTRUMENTS[0];

static std::string pitch_y_to_note(float y) {
    int total = (int)std::lround((y - 1.2f) / Y_STEP);
    int octave = 3 + total / 7;
    int step = total % 7;
    if (step < 0) { step += 7; --octave; }
    static const char* names[] = {"C", "D", "E", "F", "G", "A", "B"};
    return std::string(names[step]) + std::to_string(octave);
}

static std::vector<float> build_ledger_lines(float pmin, float pmax, const std::vector<float>& main) {
    std::vector<float> ledgers;
    for (float y = pmin; y <= pmax + 0.001f; y += Y_STEP) {
        bool on_staff = false;
        for (float m : main) {
            if (std::fabs(y - m) < 0.01f) { on_staff = true; break; }
        }
        if (!on_staff) ledgers.push_back(y);
    }
    return ledgers;
}

static void apply_instrument(int idx) {
    g_instrument_idx = idx % (int)(sizeof(INSTRUMENTS) / sizeof(INSTRUMENTS[0]));
    g_inst = &INSTRUMENTS[g_instrument_idx];
    g_staff_pitch_min = g_inst->pitch_min;
    g_staff_pitch_max = g_inst->pitch_max;
    g_staff_main = g_inst->staff_main;
    g_staff_ledger = build_ledger_lines(g_staff_pitch_min, g_staff_pitch_max, g_staff_main);
    g_note_labels.clear();
    for (float y = g_staff_pitch_min; y <= g_staff_pitch_max + 0.001f; y += Y_STEP) {
        g_note_labels.push_back({pitch_y_to_note(y), y});
    }
}

struct VizPalette {
    const char* name;
    Color bg, header_top, header_bot, panel_bg, panel_border;
    Color staff_surface, staff_line, ledger_line, label_color;
    Color now_line, text_bright, text_dim, accent;
    Color col_in_tune, col_sharp, col_flat, col_rest;
    Color beat_grid, bar_grid;
    Color good_zone, tune_marker;
};

static VizPalette g_pal{};
static int g_theme_idx = 0;
static float g_in_tune_cents = 5.0f;

// Grey-scale palettes only (default: Light Grey). Press T to cycle darker.
static const VizPalette THEME_PRESETS[] = {
    // 0 — default
    { "Light Grey",
      {0xd8,0xdc,0xe0,0xff}, {0xcc,0xd0,0xd6,0xff}, {0xc0,0xc6,0xcc,0xff},
      {0xe4,0xe8,0xec,0xf8}, {0xa8,0xb0,0xb8,0xff},
      {0xee,0xf0,0xf2,0xff}, {0x4a,0x54,0x60,0xcc}, {0x8a,0x94,0xa0,0x99},
      {0x3a,0x44,0x50,0xff}, {0x18,0x1e,0x24,0xff}, {0x5a,0x64,0x70,0xff},
      {0x6a,0x74,0x80,0xff}, {0x2a,0x70,0xb8,0xff},
      {0x18,0x8a,0x44,0xff}, {0xc8,0x34,0x2c,0xff}, {0x1a,0x78,0xb8,0xff},
      {0xb0,0xb8,0xc0,0x88}, {0x98,0xa8,0xb8,0xff}, {0x78,0x88,0x98,0xff},
      {0x78,0xb8,0x90,0xff}, {0x38,0x98,0x60,0xff} },
    { "Silver",
      {0xe8,0xea,0xec,0xff}, {0xdc,0xe0,0xe4,0xff}, {0xd0,0xd4,0xd8,0xff},
      {0xf2,0xf4,0xf6,0xf8}, {0xb0,0xb8,0xc0,0xff},
      {0xf6,0xf8,0xfa,0xff}, {0x4a,0x54,0x60,0xcc}, {0x8a,0x94,0xa0,0x99},
      {0x3a,0x44,0x50,0xff}, {0x18,0x1e,0x24,0xff}, {0x5a,0x64,0x70,0xff},
      {0x6a,0x74,0x80,0xff}, {0x2a,0x70,0xb8,0xff},
      {0x18,0x8a,0x44,0xff}, {0xc8,0x34,0x2c,0xff}, {0x1a,0x78,0xb8,0xff},
      {0xc0,0xc8,0xd0,0x88}, {0xa0,0xb0,0xc0,0xff}, {0x80,0x90,0xa0,0xff},
      {0x78,0xb8,0x90,0xff}, {0x38,0x98,0x60,0xff} },
    { "Medium Grey",
      {0xb8,0xbc,0xc0,0xff}, {0xac,0xb0,0xb6,0xff}, {0xa0,0xa6,0xac,0xff},
      {0xc4,0xc8,0xcc,0xf8}, {0x90,0x98,0xa0,0xff},
      {0xcc,0xd0,0xd4,0xff}, {0x3a,0x44,0x50,0xcc}, {0x7a,0x84,0x90,0x99},
      {0x2a,0x34,0x40,0xff}, {0x14,0x18,0x1c,0xff}, {0x4a,0x54,0x60,0xff},
      {0x5a,0x64,0x70,0xff}, {0x2a,0x68,0xb0,0xff},
      {0x18,0x8a,0x44,0xff}, {0xc8,0x34,0x2c,0xff}, {0x1a,0x78,0xb8,0xff},
      {0x98,0xa0,0xa8,0x88}, {0x88,0x98,0xa8,0xff}, {0x68,0x78,0x88,0xff},
      {0x70,0xb0,0x88,0xff}, {0x30,0x90,0x58,0xff} },
    { "Slate Grey",
      {0x98,0x9c,0xa4,0xff}, {0x8c,0x90,0x98,0xff}, {0x80,0x86,0x8e,0xff},
      {0xa4,0xa8,0xb0,0xf8}, {0x70,0x78,0x82,0xff},
      {0xac,0xb0,0xb8,0xff}, {0x58,0x62,0x6e,0xcc}, {0x88,0x92,0x9c,0x99},
      {0xe8,0xec,0xf0,0xff}, {0xf4,0xf6,0xf8,0xff}, {0xc8,0xd0,0xd8,0xff},
      {0xb0,0xb8,0xc0,0xff}, {0x5a,0xa8,0xe0,0xff},
      {0x50,0xd8,0x78,0xff}, {0xf0,0x58,0x48,0xff}, {0x58,0xb8,0xf0,0xff},
      {0x78,0x80,0x88,0x88}, {0x90,0xa8,0xc0,0xff}, {0x70,0x88,0xa0,0xff},
      {0x88,0xd0,0xa0,0xff}, {0x58,0xb0,0x78,0xff} },
    { "Graphite",
      {0x6c,0x70,0x78,0xff}, {0x60,0x64,0x6c,0xff}, {0x54,0x5a,0x62,0xff},
      {0x78,0x7c,0x84,0xf8}, {0x48,0x50,0x58,0xff},
      {0x80,0x84,0x8c,0xff}, {0x68,0x72,0x7e,0xcc}, {0x98,0xa2,0xac,0x99},
      {0xe0,0xe4,0xe8,0xff}, {0xf0,0xf2,0xf4,0xff}, {0xb8,0xc0,0xc8,0xff},
      {0xa0,0xa8,0xb0,0xff}, {0x68,0xb0,0xe8,0xff},
      {0x58,0xe0,0x80,0xff}, {0xf0,0x60,0x50,0xff}, {0x60,0xc0,0xf8,0xff},
      {0x58,0x60,0x68,0x88}, {0x88,0xa0,0xb8,0xff}, {0x68,0x80,0x98,0xff},
      {0x80,0xd8,0xa0,0xff}, {0x50,0xb8,0x70,0xff} },
    { "Charcoal",
      {0x48,0x4c,0x54,0xff}, {0x3c,0x40,0x48,0xff}, {0x30,0x36,0x3e,0xff},
      {0x54,0x58,0x60,0xf8}, {0x28,0x30,0x38,0xff},
      {0x5c,0x60,0x68,0xff}, {0x78,0x82,0x8c,0xcc}, {0x88,0x92,0x9c,0x99},
      {0xe4,0xe8,0xec,0xff}, {0xf4,0xf6,0xf8,0xff}, {0xa8,0xb0,0xb8,0xff},
      {0x90,0x98,0xa0,0xff}, {0x78,0xc0,0xf8,0xff},
      {0x60,0xf0,0x88,0xff}, {0xff,0x68,0x58,0xff}, {0x70,0xd0,0xff,0xff},
      {0x38,0x40,0x48,0x88}, {0x90,0xa8,0xc0,0xff}, {0x70,0x88,0xa0,0xff},
      {0x90,0xe8,0xb0,0xff}, {0x60,0xc8,0x80,0xff} },
};

static Color BG, HEADER_TOP, HEADER_BOT, PANEL_BG, PANEL_BORDER;
static Color STAFF_SURFACE, STAFF_LINE, LEDGER_LINE, LABEL_COLOR;
static Color NOW_LINE, TEXT_BRIGHT, TEXT_DIM, ACCENT_BLUE;
static Color COL_IN_TUNE, COL_SHARP, COL_FLAT, COL_REST;
static Color BEAT_GRID_COL, BAR_GRID_COL;
static Color GOOD_ZONE_COL, TUNE_MARKER_COL;

static void apply_theme(int idx) {
    g_theme_idx = idx % (int)(sizeof(THEME_PRESETS) / sizeof(THEME_PRESETS[0]));
    g_pal = THEME_PRESETS[g_theme_idx];
    BG = g_pal.bg; HEADER_TOP = g_pal.header_top; HEADER_BOT = g_pal.header_bot;
    PANEL_BG = g_pal.panel_bg; PANEL_BORDER = g_pal.panel_border;
    STAFF_SURFACE = g_pal.staff_surface; STAFF_LINE = g_pal.staff_line;
    LEDGER_LINE = g_pal.ledger_line; LABEL_COLOR = g_pal.label_color;
    NOW_LINE = g_pal.now_line; TEXT_BRIGHT = g_pal.text_bright;
    TEXT_DIM = g_pal.text_dim; ACCENT_BLUE = g_pal.accent;
    COL_IN_TUNE = g_pal.col_in_tune; COL_SHARP = g_pal.col_sharp;
    COL_FLAT = g_pal.col_flat; COL_REST = g_pal.col_rest;
    BEAT_GRID_COL = g_pal.beat_grid; BAR_GRID_COL = g_pal.bar_grid;
    GOOD_ZONE_COL = g_pal.good_zone; TUNE_MARKER_COL = g_pal.tune_marker;
}

constexpr float TRACE_CORE_WIDTH = 2.4f;
constexpr int   HUD_HEIGHT       = 96;
constexpr float STAFF_GUTTER_W   = 88.0f;  // fixed left column for clef + labels
constexpr float CENTS_RIBBON_H   = 228.0f; // 50% taller than original 152

// Simple square-wave generator for the metronome (raylib 6+ does not provide GenWaveSquare in the public API).
static Wave GenWaveSquare(float frequency, float durationSeconds, int sampleRate)
{
    Wave wave = { 0 };
    wave.frameCount = (unsigned int)(durationSeconds * sampleRate);
    wave.sampleRate = sampleRate;
    wave.sampleSize = 32; // 32-bit float samples
    wave.channels   = 1;
    wave.data = malloc((size_t)wave.frameCount * sizeof(float));
    if (!wave.data) {
        wave.frameCount = 0;
        return wave;
    }
    float* samples = (float*)wave.data;
    float periodSamples = (float)sampleRate / frequency;
    for (unsigned int i = 0; i < wave.frameCount; ++i) {
        float t = (float)i / periodSamples;
        samples[i] = ((int)t % 2 == 0) ? 1.0f : -1.0f;
    }
    return wave;
}

// =============================================================================
// DATA
// =============================================================================

struct PitchSample {
    float   teensy_ts;   // host stream time (ms since scroll anchor) — set on drain
    std::string note;
    float   cents;
    float   y_pos;
    float   confidence;
    float   level;
};

// Thread-safe handoff queue (reader/sim -> main)
static std::deque<PitchSample> g_incoming;
static std::mutex g_incoming_mtx;

// Serial diagnostics (HW mode) — surfaced on HUD + --debug console
static std::atomic<bool>     g_serial_connected{false};
static std::atomic<uint32_t> g_serial_lines_parsed{0};
static std::atomic<uint32_t> g_serial_open_failures{0};
static std::atomic<DWORD>    g_serial_last_error{0};

// =============================================================================
// UTILITIES
// =============================================================================

// Screen Y grows downward; musical pitch grows upward — flip when drawing the staff.
inline float staff_pitch_to_screen_y(float pitch_y, float staff_top, float y_scale) {
    float flipped = g_staff_pitch_min + g_staff_pitch_max - pitch_y;
    return staff_top + (flipped - g_staff_pitch_min) * y_scale;
}

float pitch_to_y(const std::string& note_str) {
    if (note_str.empty()) return 4.0f;
    if (note_str == "---" || note_str == "REST") return Y_REST;

    char note = static_cast<char>(std::toupper(note_str[0]));
    int accidental = 0;  // +1 sharp, -1 flat (half step in staff Y)
    size_t acc_i = 1;
    if (acc_i < note_str.size()) {
        if (note_str[acc_i] == '#') {
            accidental = 1;
            ++acc_i;
        } else if (note_str[acc_i] == 'b' || note_str[acc_i] == 'B') {
            accidental = -1;
            ++acc_i;
        }
    }

    int octave = 3;
    for (int i = (int)note_str.size() - 1; i >= 0; --i) {
        if (std::isdigit(note_str[i])) {
            octave = note_str[i] - '0';
            break;
        }
    }

    // Diatonic staff space: C3=1.2, natural letter steps = 0.4
    int step = 0;
    switch (note) {
        case 'C': step = 0; break; case 'D': step = 1; break; case 'E': step = 2; break;
        case 'F': step = 3; break; case 'G': step = 4; break; case 'A': step = 5; break;
        case 'B': step = 6; break;
        default: return 4.0f;
    }

    float y = 1.2f + (step + (octave - 3) * 7) * Y_STEP;
    y += accidental * (Y_STEP * 0.5f);  // C# sits midway between C and D, etc.
    return y;
}

Color get_color(float cents) {
    if (std::fabs(cents) < g_in_tune_cents) return COL_IN_TUNE;
    return (cents > 0.0f) ? COL_SHARP : COL_FLAT;
}

Color with_alpha(Color c, float a) {
    c.a = (unsigned char)std::clamp((int)(a * 255.0f), 0, 255);
    return c;
}

// Simple musical time helpers
inline float beats_to_seconds(float beats, float bpm) { return (bpm > 1.0f) ? (beats * 60.0f / bpm) : 0.0f; }

// Locale-safe parse (std::stof can fail under some Windows locale settings)
static bool parse_float_c(const std::string& s, float& out) {
    if (s.empty()) return false;
    char* end = nullptr;
    out = std::strtof(s.c_str(), &end);
    return end != s.c_str();
}

static bool parse_ulong_c(const std::string& s, unsigned long& out) {
    if (s.empty()) return false;
    char* end = nullptr;
    out = std::strtoul(s.c_str(), &end, 10);
    return end != s.c_str();
}

// =============================================================================
// SIMULATOR (richer, more musical than basic version)
// =============================================================================

class Simulator {
public:
    Simulator(std::atomic<bool>& stop) : stop_(stop) {}

    void run() {
        using clock = std::chrono::steady_clock;
        auto last = clock::now();
        float t = 0.0f;
        float phase = 0.0f;
        float drift = 0.0f;
        std::string current_note = "G3";
        float base_y = pitch_to_y(current_note);
        bool is_rest = false;
        float rest_until = 0.0f;

        float local_ts = 0.0f; // our "teensy" time

        while (!stop_.load()) {
            auto now = clock::now();
            float dt = std::chrono::duration<float>(now - last).count();
            last = now;
            if (dt > 0.1f) dt = 0.1f;

            t += dt;
            local_ts += SAMPLE_INTERVAL_MS;
            phase += dt * 1.6f;

            // Occasionally change base note or insert a rest (feels like real practice)
            if (t > rest_until && (std::rand() % 180 == 0)) {
                is_rest = !is_rest;
                if (is_rest) {
                    rest_until = t + 0.6f + (std::rand() % 100) / 80.0f; // 0.6–1.8s rests
                } else {
                    // occasional note change (gliss / shift)
                    if (!g_note_labels.empty()) {
                        size_t idx = (size_t)(std::rand() % (int)g_note_labels.size());
                        current_note = g_note_labels[idx].first;
                    }
                    base_y = pitch_to_y(current_note);
                    rest_until = t + 0.15f;
                }
            }

            float cents = 0.0f;
            if (!is_rest) {
                drift += (float)std::normal_distribution<float>(0.0f, 0.09f)(rng_);
                drift = std::clamp(drift, -38.0f, 38.0f);

                // Expressive slow drift + faster vibrato-like motion + occasional "nail it"
                float vibrato = 3.5f * std::sin(phase * 5.3f) + 1.8f * std::sin(phase * 8.7f);
                float effort = 7.0f * std::sin(phase * 0.7f) + 2.5f * std::sin(phase * 1.9f);
                cents = drift + effort + vibrato;

                // Random "I got it perfect for a moment" moments
                if ((std::rand() % 220) == 0) cents = (std::rand() % 7) - 3.0f;

                cents = std::clamp(cents, -48.0f, 48.0f);
            }

            float y = base_y + (cents * 0.0118f); // approx 0.4 per 34 cents visual scaling

            PitchSample s;
            s.teensy_ts = local_ts;
            s.note = is_rest ? std::string("---") : current_note;
            s.cents = cents;
            s.y_pos = y;
            s.confidence = is_rest ? 0.0f : 0.7f + 0.3f * ((std::rand() % 1000) / 1000.0f);
            s.level = is_rest ? 0.0003f : 0.012f + 0.03f * ((std::rand() % 1000)/1000.0f);

            {
                std::lock_guard<std::mutex> lk(g_incoming_mtx);
                g_incoming.push_back(s);
                if (g_incoming.size() > 4000) g_incoming.pop_front();
            }

            std::this_thread::sleep_for(std::chrono::microseconds(8333)); // 120 Hz
        }
    }

private:
    std::atomic<bool>& stop_;
    std::mt19937 rng_{std::random_device{}()};
};

// =============================================================================
// WIN32 SERIAL READER (robust, auto-reconnect, same parsing spirit as Python)
// =============================================================================

#ifdef _WIN32
class SerialReader {
public:
    SerialReader(const std::string& port, int baud, std::atomic<bool>& stop)
        : port_(port), baud_(baud), stop_(stop) {}

    void run() {
        while (!stop_.load()) {
            if (!open_port()) {
                g_serial_connected.store(false);
                g_serial_open_failures.fetch_add(1);
                std::this_thread::sleep_for(std::chrono::milliseconds(800));
                continue;
            }
            g_serial_connected.store(true);
            printf("[serial] Connected to %s @ %d baud\n", port_.c_str(), baud_);
            read_loop();
            close_port();
            g_serial_connected.store(false);
            printf("[serial] Disconnected from %s\n", port_.c_str());
            if (!stop_.load()) {
                std::this_thread::sleep_for(std::chrono::milliseconds(600));
            }
        }
    }

private:
    bool open_port() {
        std::string dev = "\\\\.\\" + port_;
        hCom_ = CreateFileA(dev.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                            OPEN_EXISTING, 0, nullptr);
        if (hCom_ == INVALID_HANDLE_VALUE) {
            g_serial_last_error.store(GetLastError());
            return false;
        }

        SetupComm(hCom_, 8192, 8192);
        PurgeComm(hCom_, PURGE_RXCLEAR | PURGE_TXCLEAR);

        DCB dcb{};
        dcb.DCBlength = sizeof(dcb);
        if (!GetCommState(hCom_, &dcb)) { close_port(); return false; }

        dcb.BaudRate = baud_;
        dcb.ByteSize = 8;
        dcb.Parity   = NOPARITY;
        dcb.StopBits = ONESTOPBIT;
        dcb.fBinary  = TRUE;
        dcb.fDtrControl = DTR_CONTROL_ENABLE;  // match pyserial default
        if (!SetCommState(hCom_, &dcb)) { close_port(); return false; }

        // Match pyserial timeout=0.1s: block up to 100ms waiting for data
        COMMTIMEOUTS to{};
        to.ReadIntervalTimeout = MAXDWORD;
        to.ReadTotalTimeoutMultiplier = 0;
        to.ReadTotalTimeoutConstant = 100;
        SetCommTimeouts(hCom_, &to);

        // Must seed on connect: last_success_=0 trips the 1.8s idle disconnect immediately
        last_success_ = GetTickCount64();
        return true;
    }

    void close_port() {
        if (hCom_ != INVALID_HANDLE_VALUE) {
            CloseHandle(hCom_);
            hCom_ = INVALID_HANDLE_VALUE;
        }
    }

    void read_loop() {
        char buf[512];
        std::string line_acc;
        DWORD bytes = 0;

        while (!stop_.load()) {
            if (!ReadFile(hCom_, buf, sizeof(buf) - 1, &bytes, nullptr) || bytes == 0) {
                // lost connection or timeout
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
                if (GetTickCount64() - last_success_ > 1800) break;
                continue;
            }

            buf[bytes] = 0;
            line_acc.append(buf, bytes);

            // Split on \n (or \r\n)
            size_t pos;
            while ((pos = line_acc.find('\n')) != std::string::npos) {
                std::string line = line_acc.substr(0, pos);
                line_acc.erase(0, pos + 1);
                // trim \r
                if (!line.empty() && line.back() == '\r') line.pop_back();

                if (!line.empty() && line.find(',') != std::string::npos) {
                    parse_and_push(line);
                    last_success_ = GetTickCount64();
                }
            }
        }
    }

    void parse_and_push(const std::string& raw) {
        // Flexible parser mirroring the Python visualizer
        std::vector<std::string> parts;
        size_t start = 0;
        for (;;) {
            size_t c = raw.find(',', start);
            if (c == std::string::npos) {
                parts.push_back(raw.substr(start));
                break;
            }
            parts.push_back(raw.substr(start, c - start));
            start = c + 1;
        }

        std::string note;
        float cents = 0.0f;
        float conf = 0.0f;
        float lvl = 0.0f;
        float ts = (float)GetTickCount64();

        // Try primary: parts[1]=note, parts[2]=cents (matches Teensy)
        if (parts.size() >= 3) {
            auto cand_note = trim(parts[1]);
            float c = 0.0f;
            if (parse_float_c(trim(parts[2]), c) && is_valid_note_token(cand_note)) {
                note = cand_note;
                cents = c;
            }
        }
        // Fallback: scan for last two plausible fields
        if (note.empty() && parts.size() >= 2) {
            float c = 0.0f;
            auto cand = trim(parts[parts.size()-2]);
            if (parse_float_c(trim(parts.back()), c) && is_valid_note_token(cand)) {
                note = cand;
                cents = c;
            }
        }
        if (note.empty()) return;

        // ts (first field) — Teensy millis(); always accept parsed notes/rests
        if (!parts.empty()) {
            unsigned long ts_ul = 0;
            if (parse_ulong_c(trim(parts[0]), ts_ul)) {
                ts = (float)ts_ul;
            }
        }
        // conf (4th)
        if (parts.size() >= 4) {
            float v = 0.0f;
            if (parse_float_c(trim(parts[3]), v)) {
                conf = (v > 1.0f) ? (v / 100.0f) : v;
                conf = std::clamp(conf, 0.0f, 1.0f);
            }
        }
        // level (5th)
        if (parts.size() >= 5) {
            float v = 0.0f;
            if (parse_float_c(trim(parts[4]), v)) {
                lvl = std::clamp(v, 0.0f, 1.0f);
            }
        }

        PitchSample s;
        s.teensy_ts = ts;
        s.note = note;
        s.cents = cents;
        s.y_pos = pitch_to_y(note);
        s.confidence = conf;
        s.level = lvl;

        std::lock_guard<std::mutex> lk(g_incoming_mtx);
        g_incoming.push_back(s);
        if (g_incoming.size() > 4000) g_incoming.pop_front();
        g_serial_lines_parsed.fetch_add(1);
    }

    static std::string trim(const std::string& s) {
        size_t b = s.find_first_not_of(" \t\r\n");
        if (b == std::string::npos) return "";
        size_t e = s.find_last_not_of(" \t\r\n");
        return s.substr(b, e - b + 1);
    }

    static bool is_valid_note_token(const std::string& tok) {
        if (tok == "---") return true;
        if (tok.size() < 2) return false;
        char n = (char)std::toupper(tok[0]);
        if (n < 'A' || n > 'G') return false;
        // must contain a digit somewhere
        for (char c : tok) if (std::isdigit(c)) return true;
        return false;
    }

    std::string port_;
    int baud_;
    std::atomic<bool>& stop_;
    HANDLE hCom_ = INVALID_HANDLE_VALUE;
    unsigned long long last_success_ = 0;
};
#endif // _WIN32

// =============================================================================
// DRAW HELPERS
// =============================================================================

static void draw_clef_cutout(Vector2 c, float r) {
    DrawCircleV(c, r, STAFF_SURFACE);
}

void draw_alto_clef(Vector2 base, float scale, Color col) {
    float x = base.x, y = base.y, s = scale;
    DrawLineEx({x, y - 38*s}, {x, y + 38*s}, 3.5f*s, col);
    DrawLineEx({x, y - 28*s}, {x + 14*s, y - 32*s}, 2.8f*s, col);
    DrawLineEx({x + 14*s, y - 32*s}, {x + 22*s, y - 18*s}, 2.6f*s, col);
    DrawLineEx({x + 22*s, y - 18*s}, {x + 11*s, y - 8*s}, 2.6f*s, col);
    DrawLineEx({x + 11*s, y - 8*s}, {x + 2*s, y - 12*s}, 2.4f*s, col);
    DrawLineEx({x, y + 28*s}, {x + 14*s, y + 32*s}, 2.8f*s, col);
    DrawLineEx({x + 14*s, y + 32*s}, {x + 22*s, y + 18*s}, 2.6f*s, col);
    DrawLineEx({x + 22*s, y + 18*s}, {x + 11*s, y + 8*s}, 2.6f*s, col);
    DrawLineEx({x + 11*s, y + 8*s}, {x + 2*s, y + 12*s}, 2.4f*s, col);
    DrawCircleV({x + 4*s, y}, 3.5f*s, col);
    draw_clef_cutout({x + 4*s, y}, 1.6f*s);
}

void draw_bass_clef(Vector2 base, float scale, Color col) {
    float x = base.x, y = base.y, s = scale;
    // Stylized F-clef (bass): curved spine + two dots on F line.
    DrawLineEx({x - 4*s, y - 34*s}, {x + 6*s, y - 26*s}, 3.2f*s, col);
    DrawLineEx({x + 6*s, y - 26*s}, {x + 10*s, y - 10*s}, 3.0f*s, col);
    DrawLineEx({x + 10*s, y - 10*s}, {x + 2*s, y + 6*s}, 3.0f*s, col);
    DrawLineEx({x + 2*s, y + 6*s}, {x - 2*s, y + 24*s}, 2.8f*s, col);
    DrawLineEx({x - 2*s, y + 24*s}, {x + 8*s, y + 34*s}, 2.8f*s, col);
    DrawLineEx({x + 8*s, y + 34*s}, {x + 16*s, y + 22*s}, 2.6f*s, col);
    DrawLineEx({x + 16*s, y + 22*s}, {x + 12*s, y + 4*s}, 2.6f*s, col);
    DrawLineEx({x + 12*s, y + 4*s}, {x + 4*s, y - 8*s}, 2.4f*s, col);
    DrawCircleV({x + 24*s, y - 5*s}, 3.2f*s, col);
    DrawCircleV({x + 24*s, y + 11*s}, 3.2f*s, col);
}

void draw_treble_clef(Vector2 base, float scale, Color col) {
    float x = base.x, y = base.y, s = scale;
    // Stylized G-clef (treble): vertical stem + spiral around G line.
    DrawLineEx({x + 2*s, y + 30*s}, {x - 2*s, y - 34*s}, 3.0f*s, col);
    DrawLineEx({x - 2*s, y - 34*s}, {x + 10*s, y - 30*s}, 2.8f*s, col);
    DrawLineEx({x + 10*s, y - 30*s}, {x + 18*s, y - 18*s}, 2.6f*s, col);
    DrawLineEx({x + 18*s, y - 18*s}, {x + 14*s, y - 4*s}, 2.6f*s, col);
    DrawLineEx({x + 14*s, y - 4*s}, {x + 2*s, y + 2*s}, 2.6f*s, col);
    DrawLineEx({x + 2*s, y + 2*s}, {x - 4*s, y + 14*s}, 2.4f*s, col);
    DrawLineEx({x - 4*s, y + 14*s}, {x + 6*s, y + 22*s}, 2.4f*s, col);
    DrawLineEx({x + 6*s, y + 22*s}, {x + 16*s, y + 16*s}, 2.4f*s, col);
    DrawLineEx({x + 16*s, y + 16*s}, {x + 12*s, y + 6*s}, 2.2f*s, col);
    DrawLineEx({x + 12*s, y + 6*s}, {x + 4*s, y + 2*s}, 2.2f*s, col);
    DrawCircleV({x + 2*s, y + 2*s}, 2.8f*s, col);
    draw_clef_cutout({x + 2*s, y + 2*s}, 1.2f*s);
}

static void draw_active_clef(Vector2 base, float scale, Color col) {
    switch (g_inst->clef) {
        case ClefKind::Alto:   draw_alto_clef(base, scale, col); break;
        case ClefKind::Bass:   draw_bass_clef(base, scale, col); break;
        case ClefKind::Treble: draw_treble_clef(base, scale, col); break;
    }
}

void draw_glowing_polyline(const std::vector<Vector2>& pts, Color base_col, float core_w, int glow_layers) {
    if (pts.size() < 2) return;

    // Glow passes (from outside in)
    for (int g = glow_layers; g >= 1; --g) {
        float w = core_w + g * 2.8f;
        float a = 0.045f + (glow_layers - g) * 0.035f;
        Color gc = with_alpha(base_col, a);
        for (size_t i = 0; i + 1 < pts.size(); ++i) {
            DrawLineEx(pts[i], pts[i+1], w, gc);
        }
    }
    // Core
    for (size_t i = 0; i + 1 < pts.size(); ++i) {
        DrawLineEx(pts[i], pts[i+1], core_w, base_col);
    }
}

// Draw a nice horizontal shaded "in tune zone" band around a staff line y
void draw_intune_band(float staff_y, float x0, float x1, float staff_top, float y_scale, Color base) {
    float half_h = 0.115f * y_scale;
    float cy = staff_pitch_to_screen_y(staff_y, staff_top, y_scale);
    Rectangle r = {x0, cy - half_h, x1 - x0, half_h * 2.0f};
    DrawRectangleRec(r, with_alpha(base, 0.04f));
}

void draw_panel_frame(Rectangle r, Color fill, Color border, float round = 6.0f) {
    DrawRectangleRounded(r, round, 8, fill);
    DrawRectangleRoundedLinesEx(r, round, 8, 1.5f, border);
}

static float smoothstep01(float t) {
    t = std::clamp(t, 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

struct TraceVisPt { float x; float y; Color c; float a; };

static void densify_trace_x(std::vector<TraceVisPt>& pts) {
    if (pts.size() < 2) return;
    std::vector<TraceVisPt> out;
    out.reserve(pts.size() * 4);
    out.push_back(pts[0]);
    for (size_t i = 0; i + 1 < pts.size(); ++i) {
        const auto& a = pts[i];
        const auto& b = pts[i + 1];
        float dx = b.x - a.x;
        if (dx > 2.0f) {
            int steps = std::clamp((int)std::ceil(dx / 2.0f), 2, 14);
            for (int s = 1; s < steps; ++s) {
                float t = (float)s / (float)steps;
                out.push_back({a.x + dx * t, a.y + (b.y - a.y) * t, b.c, a.a + (b.a - a.a) * t});
            }
        }
        out.push_back(b);
    }
    pts.swap(out);
}

static void smooth_pitch_steps(std::vector<TraceVisPt>& pts) {
    if (pts.size() < 2) return;
    std::vector<TraceVisPt> out;
    out.reserve(pts.size() * 2);
    out.push_back(pts[0]);
    for (size_t i = 0; i + 1 < pts.size(); ++i) {
        const auto& a = pts[i];
        const auto& b = pts[i + 1];
        float dy = std::fabs(a.y - b.y);
        float dx = b.x - a.x;
        if (dy > 2.0f && dx > 4.0f) {
            constexpr int kSteps = 6;
            for (int s = 1; s < kSteps; ++s) {
                float t = smoothstep01((float)s / (float)kSteps);
                out.push_back({a.x + dx * t, a.y + (b.y - a.y) * t, b.c, b.a});
            }
        }
        out.push_back(b);
    }
    pts.swap(out);
}

static Font g_font_ui{};
static Font g_font_label{};
static bool g_fonts_loaded = false;

static void load_ui_fonts() {
    const char* candidates[] = {
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    };
    for (const char* path : candidates) {
        if (!FileExists(path)) continue;
        g_font_ui    = LoadFontEx(path, 64, nullptr, 0);
        g_font_label = LoadFontEx(path, 40, nullptr, 0);
        SetTextureFilter(g_font_ui.texture, TEXTURE_FILTER_BILINEAR);
        SetTextureFilter(g_font_label.texture, TEXTURE_FILTER_BILINEAR);
        g_fonts_loaded = true;
        return;
    }
}

static void unload_ui_fonts() {
    if (!g_fonts_loaded) return;
    UnloadFont(g_font_ui);
    UnloadFont(g_font_label);
    g_fonts_loaded = false;
}

static Vector2 measure_font(const Font& font, const char* text, float size) {
    if (g_fonts_loaded) return MeasureTextEx(font, text, size, 1.0f);
    return {(float)MeasureText(text, (int)size), (float)size};
}

static void draw_font_text(const Font& font, const char* text, Vector2 pos, float size, Color col) {
    if (g_fonts_loaded) {
        DrawTextEx(font, text, pos, size, 1.0f, col);
    } else {
        DrawText(text, (int)pos.x, (int)pos.y, (int)size, col);
    }
}

static void draw_label_caps(const char* text, int x, int y, int size, Color col) {
    draw_font_text(g_font_ui, text, {(float)x, (float)y}, (float)size, col);
}

// Pitch label: large letter + subscript octave (e.g. C with small 3)
static void draw_pitch_label(const char* name, float right_x, float center_y) {
    if (!name || !name[0]) return;

    char letter[4] = {name[0], '\0'};
    const char* octave = name + 1;
    while (*octave && !std::isdigit(static_cast<unsigned char>(*octave))) ++octave;
    if (!*octave) octave = "";

    const float letter_sz = 18.0f;
    const float octave_sz = 13.0f;
    Vector2 lw = measure_font(g_font_label, letter, letter_sz);
    Vector2 ow = octave[0] ? measure_font(g_font_label, octave, octave_sz) : Vector2{0, 0};
    float total_w = lw.x + (octave[0] ? ow.x + 2.0f : 0.0f);
    float x = right_x - total_w;
    float y = center_y - letter_sz * 0.52f;

    draw_font_text(g_font_label, letter, {x, y}, letter_sz, TEXT_BRIGHT);
    if (octave[0]) {
        draw_font_text(g_font_label, octave, {x + lw.x + 2.0f, y + 6.0f}, octave_sz,
                       with_alpha(LABEL_COLOR, 0.95f));
    }
}

// =============================================================================
// MAIN VISUALIZER
// =============================================================================

class IntuneRayViz {
public:
    explicit IntuneRayViz(const Config& cfg) : config_(cfg) {
        // deque does not support reserve(); it grows efficiently on its own.
    }

    // Present the back buffer. On GTX 970 + recent NVIDIA drivers, EndDrawing() alone
    // does not reliably update the window after startup — priming worked only because
    // it called SwapScreenBuffer() explicitly every frame.
    void present_frame() {
        EndDrawing();
        SwapScreenBuffer();
    }

    void run() {
        SetConfigFlags(FLAG_WINDOW_RESIZABLE | FLAG_VSYNC_HINT);
        InitWindow(DEFAULT_WIDTH, DEFAULT_HEIGHT, "Intune — Viola (Raylib)");
        SetTargetFPS(60);
        SetExitKey(KEY_NULL);
        SetWindowFocused();
        load_ui_fonts();
        apply_theme(0);
        apply_instrument(0);
        update_window_title();

        beats_visible_ = DEFAULT_BEATS;
        bpm_ = DEFAULT_BPM;
        display_now_ = 0.0f;
        paused_display_ms_ = 0.0f;
        scroll_anchor_ = std::chrono::steady_clock::now();
        last_wall_ = scroll_anchor_;
        start_reader_or_sim();
        if (!config_.simulate) {
            printf("[serial] Opening %s @ %d (close Serial Monitor / other apps first)\n",
                   config_.port.c_str(), config_.baud);
        }

        // Audio before the render loop — InitAudioDevice mid-loop can disrupt GL present on some Windows drivers.
        InitAudioDevice();
        if (IsAudioDeviceReady()) {
            generate_metronome_sounds();
            audio_initialized_ = true;
            printf("[audio] Metronome ready\n");
        } else {
            printf("[audio] Device not ready (metronome disabled)\n");
        }

        // Short GL wake-up: 2 presented frames using the same path as the main loop.
        for (int i = 0; i < 2; ++i) {
            PollInputEvents();
            BeginDrawing();
            ClearBackground(BG);
            DrawText("Intune starting...", 60, 200, 28, WHITE);
            present_frame();
        }

        printf("[render] Entering main loop (%s)\n",
               config_.simulate ? "simulator" : config_.port.c_str());

        int frame = 0;

        while (!WindowShouldClose() && !quit_) {
            PollInputEvents();

            auto now = std::chrono::steady_clock::now();
            float dt = std::chrono::duration<float>(now - last_wall_).count();
            last_wall_ = now;

            frame_dt_ = std::clamp(dt, 0.001f, 0.05f);
            update_layout();
            handle_input(dt);
            drain_incoming();
            update_timing(dt);
            update_streak_and_accuracy();
            update_metronome();

            BeginDrawing();
            ClearBackground(BG);

            draw_hud();
            draw_staff_view();
            draw_cents_ribbon();
            draw_inspection_overlay();
            draw_bottom_controls();

            if (config_.debug) {
                char live[80];
                std::snprintf(live, sizeof(live), "DBG f=%d hist=%zu trace=%zu",
                              frame, history_.size(), last_trace_pts_);
                draw_font_text(g_font_ui, live, {(float)GetScreenWidth() - 280, 8}, 13.0f, with_alpha(TEXT_DIM, 0.6f));
            }

            present_frame();

            if (IsKeyPressed(KEY_Q) || IsKeyPressed(KEY_ESCAPE)) quit_ = true;

            if (config_.debug && frame > 0 && (frame % 60) == 0) {
                printf("[debug] frame=%d history=%zu trace_pts=%zu latest_ts=%.0f trace_now=%.0f "
                       "serial_conn=%d lines=%u\n",
                       frame, history_.size(), last_trace_pts_, latest_ts_, scroll_now_ts(),
                       g_serial_connected.load() ? 1 : 0,
                       g_serial_lines_parsed.load());
            }
            ++frame;
        }

        shutdown();
    }

private:
    // State
    Config config_;
    std::deque<PitchSample> history_;
    std::atomic<bool> stop_{false};
    std::thread reader_thread_;

    float bpm_ = DEFAULT_BPM;
    float beats_visible_ = DEFAULT_BEATS;
    bool paused_ = false;
    bool quit_ = false;
    float display_now_ = 0.0f;
    float paused_display_ms_ = 0.0f;
    float latest_ts_ = 0.0f;
    std::chrono::steady_clock::time_point scroll_anchor_;
    std::chrono::steady_clock::time_point last_wall_;

    // Audio is initialized lazily after the first frame so the window becomes responsive immediately.
    // (InitAudioDevice + LoadSound can block for a long time on some Windows audio drivers.)
    bool audio_initialized_ = false;

    // Gamification
    float current_streak_s_ = 0.0f;
    float visible_accuracy_ = 0.0f; // 0..100
    // Metronome
    bool  metro_on_ = false;
    float last_beat_beat_ = -1.0f;
    Sound click_sound_{0};
    Sound accent_sound_{0};

    // Inspection (paused hover)
    bool  inspect_active_ = false;
    float inspect_x_ = 0.0f;
    float trace_x0_ = 0.0f;
    float trace_x1_ = 0.0f;
    PitchSample inspect_sample_{};

    // View geometry (updated each frame)
    Rectangle staff_rect_{};
    Rectangle cents_rect_{};
    float staff_y_scale_ = 82.0f; // pixels per staff unit
    size_t last_trace_pts_ = 0;
    float frame_dt_ = 1.0f / 60.0f;
    float bpm_hold_timer_ = 0.0f;
    float tune_hold_timer_ = 0.0f;
    float trace_screen_playhead_y_ = 0.0f;
    float trace_screen_target_y_ = 0.0f;

    void update_window_title() {
        const char* clef_name = (g_inst->clef == ClefKind::Alto) ? "Alto" :
                                (g_inst->clef == ClefKind::Bass) ? "Bass" : "Treble";
        char title[96];
        std::snprintf(title, sizeof(title), "Intune — %s (%s Clef)", g_inst->name, clef_name);
        SetWindowTitle(title);
    }

    float scroll_subpixel(float usable_w) const {
        const float visible_sec = beats_to_seconds(beats_visible_, bpm_);
        if (visible_sec < 0.01f) return 0.0f;
        const float px_per_ms = usable_w / (visible_sec * 1000.0f);
        const float scroll_px = scroll_now_ts() * px_per_ms;
        return scroll_px - std::floor(scroll_px);
    }

    void update_playhead_smooth(float dt) {
        float pitch_target = 4.0f;
        bool found = false;
        for (auto it = history_.rbegin(); it != history_.rend(); ++it) {
            if (it->note == "---") break;
            pitch_target = it->y_pos;
            found = true;
            break;
        }
        if (found) {
            trace_screen_target_y_ = staff_pitch_to_screen_y(pitch_target, staff_rect_.y, staff_y_scale_);
            if (trace_screen_playhead_y_ < 1.0f) {
                trace_screen_playhead_y_ = trace_screen_target_y_;
            }
        }
        const float smooth_k = std::min(1.0f, dt * 22.0f);
        trace_screen_playhead_y_ += (trace_screen_target_y_ - trace_screen_playhead_y_) * smooth_k;
    }

    // Host-master scroll clock — PC steady_clock drives all motion; device supplies pitch only.
    float host_now_ms() const {
        using ms = std::chrono::duration<float, std::milli>;
        return ms(std::chrono::steady_clock::now() - scroll_anchor_).count();
    }

    float scroll_now_ts() const {
        return display_now_;
    }

    void start_reader_or_sim() {
        if (config_.simulate) {
            reader_thread_ = std::thread([this] {
                Simulator sim(stop_);
                sim.run();
            });
        } else {
#ifdef _WIN32
            reader_thread_ = std::thread([this] {
                SerialReader r(config_.port, config_.baud, stop_);
                r.run();
            });
#else
            // On non-Windows you can still use --simulate, or extend here.
            reader_thread_ = std::thread([this] {
                Simulator sim(stop_);
                sim.run();
            });
#endif
        }
    }

    void shutdown() {
        stop_.store(true);
        if (reader_thread_.joinable()) reader_thread_.join();

        if (audio_initialized_) {
            UnloadSound(click_sound_);
            UnloadSound(accent_sound_);
            CloseAudioDevice();
        }
        unload_ui_fonts();
        CloseWindow();
    }

    void handle_input(float /*dt*/) {
        if (IsKeyPressed(KEY_SPACE) || IsKeyPressed(KEY_P)) {
            if (!paused_) {
                paused_display_ms_ = display_now_;
                paused_ = true;
            } else {
                scroll_anchor_ = std::chrono::steady_clock::now() -
                    std::chrono::milliseconds((long long)paused_display_ms_);
                display_now_ = paused_display_ms_;
                last_wall_ = std::chrono::steady_clock::now();
                paused_ = false;
            }
        }
        if (IsKeyPressed(KEY_C)) {
            clear_history();
        }
        if (IsKeyPressed(KEY_M)) {
            metro_on_ = !metro_on_;
        }

        // BPM — tap once; hold key for auto-repeat
        if (IsKeyPressed(KEY_LEFT_BRACKET)) {
            bpm_ = std::max(36.0f, bpm_ - 1.0f);
            bpm_hold_timer_ = 0.4f;
        } else if (IsKeyDown(KEY_LEFT_BRACKET)) {
            if (bpm_hold_timer_ > 0.0f) {
                bpm_hold_timer_ -= frame_dt_;
            } else {
                bpm_ = std::max(36.0f, bpm_ - 0.8f);
                bpm_hold_timer_ = 0.06f;
            }
        } else if (IsKeyPressed(KEY_RIGHT_BRACKET)) {
            bpm_ = std::min(200.0f, bpm_ + 1.0f);
            bpm_hold_timer_ = 0.4f;
        } else if (IsKeyDown(KEY_RIGHT_BRACKET)) {
            if (bpm_hold_timer_ > 0.0f) {
                bpm_hold_timer_ -= frame_dt_;
            } else {
                bpm_ = std::min(200.0f, bpm_ + 0.8f);
                bpm_hold_timer_ = 0.06f;
            }
        } else if (IsKeyReleased(KEY_LEFT_BRACKET) || IsKeyReleased(KEY_RIGHT_BRACKET)) {
            bpm_hold_timer_ = 0.0f;
        }

        if (IsKeyPressed(KEY_T)) {
            apply_theme(g_theme_idx + 1);
            printf("[theme] %s\n", g_pal.name);
        }
        if (IsKeyPressed(KEY_I)) {
            apply_instrument(g_instrument_idx + 1);
            update_window_title();
            printf("[instrument] %s  (%s clef, C-major %s–%s)\n",
                   g_inst->name,
                   g_inst->clef == ClefKind::Alto ? "Alto" :
                   g_inst->clef == ClefKind::Bass ? "Bass" : "Treble",
                   pitch_y_to_note(g_staff_pitch_min).c_str(),
                   pitch_y_to_note(g_staff_pitch_max).c_str());
        }
        if (IsKeyPressed(KEY_MINUS)) {
            g_in_tune_cents = std::max(2.0f, g_in_tune_cents - 1.0f);
            tune_hold_timer_ = 0.4f;
        } else if (IsKeyDown(KEY_MINUS)) {
            if (tune_hold_timer_ > 0.0f) {
                tune_hold_timer_ -= frame_dt_;
            } else {
                g_in_tune_cents = std::max(2.0f, g_in_tune_cents - 0.5f);
                tune_hold_timer_ = 0.06f;
            }
        } else if (IsKeyPressed(KEY_EQUAL)) {
            g_in_tune_cents = std::min(25.0f, g_in_tune_cents + 1.0f);
            tune_hold_timer_ = 0.4f;
        } else if (IsKeyDown(KEY_EQUAL)) {
            if (tune_hold_timer_ > 0.0f) {
                tune_hold_timer_ -= frame_dt_;
            } else {
                g_in_tune_cents = std::min(25.0f, g_in_tune_cents + 0.5f);
                tune_hold_timer_ = 0.06f;
            }
        } else if (IsKeyReleased(KEY_MINUS) || IsKeyReleased(KEY_EQUAL)) {
            tune_hold_timer_ = 0.0f;
        }

        // Visible window
        if (IsKeyPressed(KEY_SEMICOLON)) beats_visible_ = std::max(1.5f, beats_visible_ - 0.25f);
        if (IsKeyPressed(KEY_APOSTROPHE)) beats_visible_ = std::min(16.0f, beats_visible_ + 0.25f);

        // Paused: hover anywhere on the trace (staff + cents) to inspect
        if (paused_) {
            Vector2 m = GetMousePosition();
            Rectangle inspect_rect = {
                trace_x0_, staff_rect_.y,
                trace_x1_ - trace_x0_,
                (cents_rect_.y + cents_rect_.height) - staff_rect_.y
            };
            if (CheckCollisionPointRec(m, inspect_rect)) {
                inspect_x_ = std::clamp(m.x, trace_x0_, trace_x1_);
                inspect_active_ = pick_inspect_sample(inspect_x_);
            } else {
                inspect_active_ = false;
            }
        } else {
            inspect_active_ = false;
        }
    }

    void drain_incoming() {
        if (paused_) return;

        std::lock_guard<std::mutex> lk(g_incoming_mtx);
        const size_t batch = g_incoming.size();
        if (batch == 0) return;

        const float host_now = host_now_ms();
        size_t idx = 0;
        while (!g_incoming.empty()) {
            PitchSample s = g_incoming.front();
            // Spread batched serial lines across SAMPLE_INTERVAL_MS so they don't stack on one X.
            s.teensy_ts = host_now - (float)(batch - 1 - idx) * SAMPLE_INTERVAL_MS;
            history_.push_back(s);
            if (s.teensy_ts > latest_ts_) {
                latest_ts_ = s.teensy_ts;
            }
            g_incoming.pop_front();
            if (history_.size() > 5600) history_.pop_front();
            ++idx;
        }
    }

    void update_timing(float /*dt*/) {
        if (paused_) return;
        display_now_ = host_now_ms();
    }

    void update_streak_and_accuracy() {
        if (history_.empty()) {
            current_streak_s_ = 0.0f;
            visible_accuracy_ = 0.0f;
            return;
        }

        const float visible_sec = beats_to_seconds(beats_visible_, bpm_);
        const float now_ts = scroll_now_ts();

        float sum_good = 0.0f;
        int   count = 0;
        bool  sounding = false;

        // Continuous in-tune run ending at the latest visible sample
        float streak_start_ts = 0.0f;
        bool  in_streak = false;

        for (auto& s : history_) {
            if (s.teensy_ts <= 0.0f) continue;
            float age = (now_ts - s.teensy_ts) / 1000.0f;
            if (age < 0 || age > visible_sec + 0.6f) continue;

            if (s.note != "---") {
                sounding = true;
                float ac = std::clamp(1.0f - (std::fabs(s.cents) / 55.0f), 0.0f, 1.0f);
                sum_good += ac;
                count++;

                if (std::fabs(s.cents) <= g_in_tune_cents) {
                    if (!in_streak) {
                        streak_start_ts = s.teensy_ts;
                        in_streak = true;
                    }
                } else {
                    in_streak = false;
                }
            } else {
                in_streak = false;
            }
        }

        current_streak_s_ = (in_streak && streak_start_ts > 0.0f)
            ? (now_ts - streak_start_ts) / 1000.0f
            : 0.0f;

        visible_accuracy_ = (count > 0) ? (sum_good / count * 100.0f) : 0.0f;
        (void)sounding;
    }

    void update_metronome() {
        if (!metro_on_ || paused_ || !audio_initialized_) return;

        float beat_now = (scroll_now_ts() / 1000.0f) * (bpm_ / 60.0f);
        float beat_floor = std::floor(beat_now);
        if (beat_floor > last_beat_beat_) {
            last_beat_beat_ = beat_floor;
            bool accent = ((int)beat_floor % 4) == 0;
            PlaySound(accent ? accent_sound_ : click_sound_);
        }
    }

    void generate_metronome_sounds() {
        // Short "woodblock-ish" click + a slightly lower accent
        {
            Wave w = GenWaveSquare(880.0f, 0.018f, 44100);
            // Make it clickier by shaping amplitude quickly
            for (int i = 0; i < w.frameCount; ++i) {
                float env = 1.0f - (float)i / w.frameCount;
                env = env * env * 0.9f;
                ((float*)w.data)[i] *= env * 0.7f;
            }
            click_sound_ = LoadSoundFromWave(w);
            UnloadWave(w);
            SetSoundVolume(click_sound_, 0.55f);
        }
        {
            Wave w = GenWaveSquare(620.0f, 0.032f, 44100);
            for (int i = 0; i < w.frameCount; ++i) {
                float env = 1.0f - (float)i / w.frameCount;
                env = env * env * 0.85f;
                ((float*)w.data)[i] *= env * 0.95f;
            }
            accent_sound_ = LoadSoundFromWave(w);
            UnloadWave(w);
            SetSoundVolume(accent_sound_, 0.72f);
        }
    }

    void clear_history() {
        {
            std::lock_guard<std::mutex> lk(g_incoming_mtx);
            g_incoming.clear();
        }
        history_.clear();
        scroll_anchor_ = std::chrono::steady_clock::now();
        display_now_ = 0.0f;
        paused_display_ms_ = 0.0f;
        latest_ts_ = 0.0f;
        current_streak_s_ = 0.0f;
        inspect_active_ = false;
        trace_screen_playhead_y_ = 0.0f;
        trace_screen_target_y_ = 0.0f;
    }

    void update_layout() {
        int sw = GetScreenWidth();
        staff_rect_ = {36.0f, (float)HUD_HEIGHT + 14.0f, (float)sw - 72.0f, 508.0f};
        staff_y_scale_ = staff_rect_.height / (g_staff_pitch_max - g_staff_pitch_min + 0.6f);
        cents_rect_ = {36.0f, staff_rect_.y + staff_rect_.height + 12.0f, (float)sw - 72.0f, CENTS_RIBBON_H};
        trace_x0_ = staff_rect_.x + STAFF_GUTTER_W + 10.0f;
        trace_x1_ = staff_rect_.x + staff_rect_.width - 14.0f;
    }

    bool pick_inspect_sample(float screen_x) {
        if (history_.empty()) return false;

        const float usable_w = trace_x1_ - trace_x0_;
        const float left_beat = -beats_visible_;
        const float right_beat = 0.28f;
        const float sub_px = scroll_subpixel(usable_w);
        const float visible_sec = beats_to_seconds(beats_visible_, bpm_);
        const float now_ts = scroll_now_ts();

        auto beat_to_x = [&](float beat) {
            return trace_x0_ + (beat - left_beat) / (right_beat - left_beat) * usable_w;
        };

        float best_px = 1e9f;
        PitchSample best{};
        bool found = false;
        for (const auto& s : history_) {
            if (s.teensy_ts <= 0.0f) continue;
            float age = (now_ts - s.teensy_ts) / 1000.0f;
            if (age < 0.0f || age > visible_sec + 1.0f) continue;
            float sx = beat_to_x(-age * (bpm_ / 60.0f)) - sub_px;
            float d = std::fabs(sx - screen_x);
            if (d < best_px) {
                best_px = d;
                best = s;
                found = true;
            }
        }
        if (!found) return false;
        inspect_sample_ = best;
        return true;
    }

    void draw_inspection_overlay() {
        if (!paused_ || !inspect_active_) return;

        const float staff_top = staff_rect_.y + 4.0f;
        const float staff_bot = staff_rect_.y + staff_rect_.height - 4.0f;
        const float cents_top = cents_rect_.y + 28.0f;
        const float cents_bot = cents_rect_.y + cents_rect_.height - 10.0f;

        const bool is_rest = (inspect_sample_.note == "---" || inspect_sample_.note == "REST");
        Color accent = is_rest ? COL_REST : get_color(inspect_sample_.cents);

        // Vertical scrub line through staff + cents
        DrawLineEx({inspect_x_, staff_top}, {inspect_x_, cents_bot}, 2.2f, with_alpha(ACCENT_BLUE, 0.85f));
        DrawLineEx({inspect_x_, staff_top}, {inspect_x_, cents_bot}, 5.0f, with_alpha(ACCENT_BLUE, 0.12f));

        if (!is_rest) {
            float pitch_y = staff_pitch_to_screen_y(inspect_sample_.y_pos, staff_rect_.y, staff_y_scale_);
            DrawLineEx({trace_x0_, pitch_y}, {trace_x1_, pitch_y}, 1.2f, with_alpha(accent, 0.45f));
            DrawCircleV({inspect_x_, pitch_y}, 9.0f, with_alpha(accent, 0.18f));
            DrawCircleV({inspect_x_, pitch_y}, 5.0f, accent);

            const float plot_top = cents_rect_.y + 62.0f;
            const float plot_bot = cents_rect_.y + cents_rect_.height - 22.0f;
            const float mid_y = (plot_top + plot_bot) * 0.5f;
            const float scale_y = (plot_bot - plot_top) * 0.5f / 25.0f;
            float cents_y = mid_y - inspect_sample_.cents * scale_y;
            DrawCircleV({inspect_x_, cents_y}, 7.0f, with_alpha(accent, 0.20f));
            DrawCircleV({inspect_x_, cents_y}, 4.0f, accent);
        }

        // Readout card
        char note_line[32];
        char cents_line[48];
        if (is_rest) {
            std::snprintf(note_line, sizeof(note_line), "REST");
            cents_line[0] = '\0';
        } else {
            std::snprintf(note_line, sizeof(note_line), "%s", inspect_sample_.note.c_str());
            const char* qual = (std::fabs(inspect_sample_.cents) < g_in_tune_cents) ? "in tune" :
                               (inspect_sample_.cents > 0.0f) ? "sharp" : "flat";
            std::snprintf(cents_line, sizeof(cents_line), "%+.1f cents  (%s)",
                          inspect_sample_.cents, qual);
        }

        const float note_sz = 28.0f;
        const float cents_sz = 17.0f;
        Vector2 note_szv = measure_font(g_font_ui, note_line, note_sz);
        Vector2 cents_szv = is_rest ? Vector2{0, 0} : measure_font(g_font_ui, cents_line, cents_sz);
        float card_w = std::max(note_szv.x, cents_szv.x) + 28.0f;
        float card_h = is_rest ? 44.0f : 72.0f;

        float card_x = inspect_x_ + 16.0f;
        float card_y = staff_top + 12.0f;
        if (card_x + card_w > trace_x1_ - 8.0f) {
            card_x = inspect_x_ - card_w - 16.0f;
        }
        card_x = std::clamp(card_x, trace_x0_ + 4.0f, trace_x1_ - card_w - 4.0f);

        Rectangle card = {card_x, card_y, card_w, card_h};
        draw_panel_frame(card, with_alpha(PANEL_BG, 0.96f), with_alpha(accent, 0.75f), 8.0f);
        draw_font_text(g_font_ui, note_line, {card.x + 14.0f, card.y + 10.0f}, note_sz, accent);
        if (!is_rest) {
            draw_font_text(g_font_ui, cents_line, {card.x + 14.0f, card.y + 42.0f}, cents_sz, TEXT_DIM);
        }
    }

    // -------------------------------------------------------------------------
    // DRAWING
    // -------------------------------------------------------------------------

    void draw_hud() {
        int sw = GetScreenWidth();

        // Navy header gradient
        DrawRectangleGradientV(0, 0, sw, HUD_HEIGHT, HEADER_TOP, HEADER_BOT);
        DrawRectangle(0, HUD_HEIGHT - 2, sw, 2, with_alpha(ACCENT_BLUE, 0.45f));

        PitchSample latest{};
        bool have = false;
        for (auto it = history_.rbegin(); it != history_.rend(); ++it) {
            if (it->teensy_ts > 0) { latest = *it; have = true; break; }
        }

        std::string note_txt = have ? latest.note : "---";
        std::string cents_txt;
        Color main_col = TEXT_BRIGHT;
        if (have) {
            if (note_txt == "---") {
                note_txt = "REST";
                main_col = TEXT_DIM;
                cents_txt = "";
            } else {
                char buf[32];
                std::snprintf(buf, sizeof(buf), "%+.1f", latest.cents);
                cents_txt = buf;
                main_col = get_color(latest.cents);
            }
        }

        // Note readout card (left)
        Rectangle note_card = {32.0f, 14.0f, 220.0f, 68.0f};
        Color card_border = have && note_txt != "REST" ? with_alpha(main_col, 0.55f) : with_alpha(PANEL_BORDER, 0.7f);
        draw_panel_frame(note_card, with_alpha(PANEL_BG, 0.92f), card_border, 8.0f);

        float note_size = 46.0f;
        draw_font_text(g_font_ui, note_txt.c_str(), {note_card.x + 18, note_card.y + 10}, note_size, main_col);
        if (!cents_txt.empty()) {
            char cents_line[48];
            std::snprintf(cents_line, sizeof(cents_line), "%s cents", cents_txt.c_str());
            draw_font_text(g_font_ui, cents_line, {note_card.x + 18, note_card.y + 46}, 15.0f, with_alpha(TEXT_DIM, 0.9f));
        }

        // Connection status (center)
        char status[80];
        Color status_col = TEXT_DIM;
        if (config_.simulate) {
            std::snprintf(status, sizeof(status), "SIMULATION");
            status_col = ACCENT_BLUE;
        } else if (g_serial_connected.load()) {
            std::snprintf(status, sizeof(status), "%s  CONNECTED", config_.port.c_str());
            status_col = COL_IN_TUNE;
        } else if (g_serial_open_failures.load() > 0) {
            std::snprintf(status, sizeof(status), "%s  ERROR", config_.port.c_str());
            status_col = COL_SHARP;
        } else {
            std::snprintf(status, sizeof(status), "%s  CONNECTING", config_.port.c_str());
        }
        draw_label_caps("STATUS", sw / 2 - 40, 18, 11, with_alpha(TEXT_DIM, 0.65f));
        Vector2 st_sz = measure_font(g_font_ui, status, 17.0f);
        draw_font_text(g_font_ui, status, {(float)(sw / 2) - st_sz.x * 0.5f, 34.0f}, 17.0f, status_col);

        // Stats cards (right)
        char streak_val[32];
        std::snprintf(streak_val, sizeof(streak_val), "%.1fs", current_streak_s_);
        char acc_val[32];
        std::snprintf(acc_val, sizeof(acc_val), "%.0f%%", visible_accuracy_);

        Rectangle streak_card = {(float)sw - 258.0f, 14.0f, 118.0f, 68.0f};
        Rectangle acc_card    = {(float)sw - 132.0f, 14.0f, 100.0f, 68.0f};
        draw_panel_frame(streak_card, with_alpha(PANEL_BG, 0.88f), with_alpha(PANEL_BORDER, 0.5f), 6.0f);
        draw_panel_frame(acc_card,    with_alpha(PANEL_BG, 0.88f), with_alpha(PANEL_BORDER, 0.5f), 6.0f);

        draw_label_caps("IN TUNE", (int)streak_card.x + 12, (int)streak_card.y + 10, 11, with_alpha(TEXT_DIM, 0.65f));
        Color streak_col = (current_streak_s_ > 0.3f) ? COL_IN_TUNE : TEXT_BRIGHT;
        draw_font_text(g_font_ui, streak_val, {streak_card.x + 12, streak_card.y + 30}, 22.0f, streak_col);

        draw_label_caps("ACCURACY", (int)acc_card.x + 12, (int)acc_card.y + 10, 11, with_alpha(TEXT_DIM, 0.65f));
        draw_font_text(g_font_ui, acc_val, {acc_card.x + 12, acc_card.y + 30}, 22.0f, TEXT_BRIGHT);
    }

    void draw_staff_view() {
        draw_panel_frame(staff_rect_, STAFF_SURFACE, PANEL_BORDER, 8.0f);

        float trace_x0 = staff_rect_.x + STAFF_GUTTER_W + 10.0f;
        float trace_x1 = staff_rect_.x + staff_rect_.width - 14.0f;

        float left_beat  = -beats_visible_;
        float right_beat = 0.28f;
        float usable_width = trace_x1 - trace_x0;
        auto beat_to_screen = [&](float beat) -> float {
            return trace_x0 + (beat - left_beat) / (right_beat - left_beat) * usable_width;
        };
        auto y_to_screen = [&](float pitch_y) -> float {
            return staff_pitch_to_screen_y(pitch_y, staff_rect_.y, staff_y_scale_);
        };

        // Fixed left gutter background + divider
        Rectangle gutter = {staff_rect_.x + 4.0f, staff_rect_.y + 4.0f, STAFF_GUTTER_W, staff_rect_.height - 8.0f};
        DrawRectangleRounded(gutter, 6.0f, 6, with_alpha(HEADER_BOT, 0.55f));
        float div_x = staff_rect_.x + STAFF_GUTTER_W + 6.0f;
        DrawLineEx({div_x, staff_rect_.y + 10}, {div_x, staff_rect_.y + staff_rect_.height - 10},
                   1.0f, with_alpha(PANEL_BORDER, 0.45f));

        // In-tune shaded bands (trace area only)
        for (float sy : g_staff_main) {
            draw_intune_band(sy, trace_x0, trace_x1, staff_rect_.y, staff_y_scale_, COL_IN_TUNE);
        }

        // Staff lines (trace area only — don't cross the gutter)
        for (float sy : g_staff_main) {
            float yy = y_to_screen(sy);
            DrawLineEx({trace_x0, yy}, {trace_x1, yy}, 1.4f, STAFF_LINE);
        }
        for (float sy : g_staff_ledger) {
            float yy = y_to_screen(sy);
            DrawLineEx({trace_x0 + 4, yy}, {trace_x1 - 4, yy}, 0.8f, LEDGER_LINE);
        }

        // Clef — centered on instrument anchor pitch
        float clef_x = staff_rect_.x + 24.0f;
        float clef_scale = (g_inst->clef == ClefKind::Bass) ? 0.82f : 0.88f;
        draw_active_clef({clef_x, y_to_screen(g_inst->clef_anchor)}, clef_scale, with_alpha(STAFF_LINE, 0.92f));

        // Pitch labels — C-major range, every semitone
        float label_right = staff_rect_.x + STAFF_GUTTER_W - 8.0f;
        for (const auto& [nm, yy] : g_note_labels) {
            draw_pitch_label(nm.c_str(), label_right, y_to_screen(yy));
        }

        // Panel header (top-right of staff — avoids trace overlap)
        char time_label[128];
        std::snprintf(time_label, sizeof(time_label), "%s  %s–%s  |  %d BPM  |  %.0f beats",
                      g_inst->name,
                      pitch_y_to_note(g_staff_pitch_min).c_str(),
                      pitch_y_to_note(g_staff_pitch_max).c_str(),
                      (int)bpm_, beats_visible_);
        Vector2 tl_sz = measure_font(g_font_ui, time_label, 14.0f);
        draw_font_text(g_font_ui, time_label,
                       {staff_rect_.x + staff_rect_.width - tl_sz.x - 16, staff_rect_.y + 10},
                       14.0f, with_alpha(TEXT_DIM, 0.8f));
        draw_label_caps("PITCH TRACE", (int)trace_x0, (int)(staff_rect_.y + 52), 33, with_alpha(TEXT_DIM, 0.55f));

        // Beat / measure grid (behind trace)
        {
            float beat_now = (scroll_now_ts() / 1000.0f) * (bpm_ / 60.0f);
            int first_beat = (int)std::floor(beat_now - beats_visible_);
            int last_beat  = (int)std::ceil(beat_now + 0.6f);
            float grid_top = staff_rect_.y + 54.0f;
            float grid_bot = staff_rect_.y + staff_rect_.height - 10.0f;

            for (int b = first_beat; b <= last_beat; ++b) {
                float bx = (float)b - beat_now;
                float sx = beat_to_screen(bx);

                int beat_in_bar = b % 4;
                if (beat_in_bar < 0) beat_in_bar += 4;
                bool is_bar = (beat_in_bar == 0);

                float dist_to_now = std::fabs((float)b - beat_now);
                float pulse = 1.0f + 0.35f * std::exp(-dist_to_now * 2.0f);

                Color line_col = is_bar ? BAR_GRID_COL : BEAT_GRID_COL;
                float alpha = (is_bar ? 0.78f : 0.48f) * pulse;
                float w = is_bar ? 2.6f : 1.3f;

                DrawLineEx({sx, grid_top}, {sx, grid_bot}, w, with_alpha(line_col, alpha));

                char beat_lbl[4];
                std::snprintf(beat_lbl, sizeof(beat_lbl), "%d", beat_in_bar + 1);
                float lbl_sz = is_bar ? 42.0f : 36.0f;
                Color lbl_col = is_bar ? COL_IN_TUNE : with_alpha(TEXT_BRIGHT, 0.72f);
                Vector2 lw = measure_font(g_font_label, beat_lbl, lbl_sz);
                draw_font_text(g_font_label, beat_lbl, {sx - lw.x * 0.5f, staff_rect_.y + 6.0f}, lbl_sz, lbl_col);
            }
        }

        const float grid_top = staff_rect_.y + 54.0f;
        const float grid_bot = staff_rect_.y + staff_rect_.height - 10.0f;
        const float sub_px = scroll_subpixel(usable_width);

        update_playhead_smooth(frame_dt_);

        const float now_screen_x = beat_to_screen(0.0f) - sub_px;
        const float dot_y = (trace_screen_playhead_y_ > 1.0f)
            ? trace_screen_playhead_y_
            : y_to_screen(4.0f);

        // === THE TRACE (polyline from history — same path as cents ribbon) ===
        last_trace_pts_ = 0;
        if (!history_.empty()) {
            const float visible_sec = beats_to_seconds(beats_visible_, bpm_);
            const float now_ts = scroll_now_ts();
            const float oldest_ts = now_ts - visible_sec * 1000.0f - 50.0f;

            std::vector<TraceVisPt> vis;
            float last_y = 4.0f;

            for (const auto& sample : history_) {
                if (sample.teensy_ts <= 0.0f || sample.teensy_ts < oldest_ts) continue;

                float age = (now_ts - sample.teensy_ts) / 1000.0f;
                if (age < 0 || age > visible_sec + 0.7f) continue;

                float sx = beat_to_screen(-age * (bpm_ / 60.0f)) - sub_px;
                bool rest = (sample.note == "---");
                Color col;
                float alpha;
                float yy;

                if (rest) {
                    col = COL_REST;
                    alpha = 0.55f;
                    yy = (last_y > 0.1f) ? last_y : sample.y_pos;
                } else {
                    col = get_color(sample.cents);
                    alpha = (sample.confidence > 0.01f)
                        ? std::clamp(0.35f + sample.confidence * 0.65f, 0.45f, 1.0f) : 0.88f;
                    yy = sample.y_pos;
                    last_y = yy;
                }
                vis.push_back({sx, y_to_screen(yy), col, alpha});
            }

            // Hold last pitch forward to playhead so the right edge scrolls continuously.
            if (!vis.empty() && now_screen_x > vis.back().x + 0.5f) {
                vis.push_back({now_screen_x, dot_y, vis.back().c, vis.back().a});
            }

            densify_trace_x(vis);
            smooth_pitch_steps(vis);
            last_trace_pts_ = vis.size();

            if (vis.size() >= 2) {
                for (size_t i = 0; i + 1 < vis.size(); ++i) {
                    Vector2 a = {vis[i].x, vis[i].y};
                    Vector2 b = {vis[i+1].x, vis[i+1].y};
                    Color seg_col = with_alpha(vis[i].c, vis[i].a);
                    DrawLineEx(a, b, TRACE_CORE_WIDTH + 1.4f, with_alpha(vis[i].c, vis[i].a * 0.18f));
                    DrawLineEx(a, b, TRACE_CORE_WIDTH, seg_col);
                }
            }
        }

        // Playhead
        DrawLineEx({now_screen_x, grid_top}, {now_screen_x, grid_bot}, 2.0f, NOW_LINE);

        if (!history_.empty()) {
            DrawCircleV({now_screen_x, dot_y}, 7.0f, with_alpha(NOW_LINE, 0.12f));
            DrawCircleV({now_screen_x, dot_y}, 3.8f, with_alpha(NOW_LINE, 0.45f));
            DrawCircleV({now_screen_x, dot_y}, 1.8f, TEXT_BRIGHT);
        }

    }

    // Very small helper because raylib Color doesn't have == by default in all versions
    static bool ColorIsEqualish(Color a, Color b) {
        return a.r == b.r && a.g == b.g && a.b == b.b;
    }

    void draw_cents_ribbon() {
        draw_panel_frame(cents_rect_, with_alpha(STAFF_SURFACE, 0.95f), PANEL_BORDER, 8.0f);

        float trace_x0 = cents_rect_.x + STAFF_GUTTER_W + 10.0f;
        float trace_x1 = cents_rect_.x + cents_rect_.width - 14.0f;

        float left_beat  = -beats_visible_;
        float right_beat = 0.28f;
        float usable = trace_x1 - trace_x0;

        auto beat_to_x = [&](float b) {
            return trace_x0 + (b - left_beat) / (right_beat - left_beat) * usable;
        };

        const float plot_top = cents_rect_.y + 62.0f;
        const float plot_bot = cents_rect_.y + cents_rect_.height - 22.0f;
        const float mid_y = (plot_top + plot_bot) * 0.5f;
        const float scale_y = (plot_bot - plot_top) * 0.5f / 25.0f;
        const float label_left_right = cents_rect_.x + STAFF_GUTTER_W - 10.0f;
        const float label_right_x0 = trace_x1 + 6.0f;

        auto cents_to_y = [&](float cents_val) { return mid_y - cents_val * scale_y; };

        auto draw_scale_tick = [&](float cents_val, Color col, float len = 8.0f) {
            float y = cents_to_y(cents_val);
            DrawLineEx({trace_x0 - len, y}, {trace_x0, y}, 1.0f, col);
        };

        struct CentsScaleLabel {
            const char* txt;
            float cents_val;
            Color col;
            float size;
            bool right_edge;
        };

        auto layout_scale_labels = [&](const std::vector<CentsScaleLabel>& labels, bool right_edge) {
            struct Slot { float ideal_y; float y; float size; const char* txt; Color col; };
            std::vector<Slot> slots;
            for (const auto& lb : labels) {
                if (lb.right_edge != right_edge) continue;
                float ideal = cents_to_y(lb.cents_val) - lb.size * 0.42f;
                slots.push_back({ideal, ideal, lb.size, lb.txt, lb.col});
            }
            if (slots.empty()) return;

            std::sort(slots.begin(), slots.end(),
                      [](const Slot& a, const Slot& b) { return a.ideal_y < b.ideal_y; });

            const float gap = 4.0f;
            for (size_t i = 1; i < slots.size(); ++i) {
                float min_y = slots[i - 1].y + slots[i - 1].size + gap;
                if (slots[i].y < min_y) slots[i].y = min_y;
            }
            float overflow = slots.back().y + slots.back().size - plot_bot;
            if (overflow > 0.0f) {
                for (auto& s : slots) s.y -= overflow;
            }
            float underflow = plot_top - slots.front().y;
            if (underflow > 0.0f) {
                for (auto& s : slots) s.y += underflow;
            }

            for (const auto& s : slots) {
                Vector2 sz = measure_font(g_font_ui, s.txt, s.size);
                float x = right_edge ? label_right_x0 : (label_left_right - sz.x);
                draw_font_text(g_font_ui, s.txt, {x, s.y}, s.size, s.col);
            }
        };

        // Good zone ±10 (reference — Yousician-style target lane)
        const float good_off = GOOD_ZONE_CENTS * scale_y;
        DrawRectangle((int)trace_x0, (int)(mid_y - good_off), (int)(trace_x1 - trace_x0), (int)(good_off * 2.0f),
                      with_alpha(GOOD_ZONE_COL, 0.10f));
        DrawLineEx({trace_x0, mid_y - good_off}, {trace_x1, mid_y - good_off}, 1.2f, with_alpha(GOOD_ZONE_COL, 0.35f));
        DrawLineEx({trace_x0, mid_y + good_off}, {trace_x1, mid_y + good_off}, 1.2f, with_alpha(GOOD_ZONE_COL, 0.35f));

        // Active in-tune threshold (adjustable with - / =)
        const float tune_off = g_in_tune_cents * scale_y;
        DrawRectangle((int)trace_x0, (int)(mid_y - tune_off), (int)(trace_x1 - trace_x0), (int)(tune_off * 2.0f),
                      with_alpha(TUNE_MARKER_COL, 0.14f));
        DrawLineEx({trace_x0, mid_y - tune_off}, {trace_x1, mid_y - tune_off}, 2.0f, with_alpha(TUNE_MARKER_COL, 0.70f));
        DrawLineEx({trace_x0, mid_y + tune_off}, {trace_x1, mid_y + tune_off}, 2.0f, with_alpha(TUNE_MARKER_COL, 0.70f));

        DrawLineEx({trace_x0, mid_y}, {trace_x1, mid_y}, 1.4f, with_alpha(COL_IN_TUNE, 0.40f));

        draw_label_caps("CENTS DEVIATION", (int)(cents_rect_.x + 14), (int)(cents_rect_.y + 10), 33, with_alpha(TEXT_DIM, 0.65f));

        // Scale ticks + labels (±25 on right edge to avoid gutter crowding)
        draw_scale_tick(25.0f, with_alpha(TEXT_DIM, 0.35f), 10.0f);
        draw_scale_tick(10.0f, with_alpha(GOOD_ZONE_COL, 0.55f));
        draw_scale_tick(0.0f, with_alpha(TEXT_BRIGHT, 0.45f));
        draw_scale_tick(-10.0f, with_alpha(GOOD_ZONE_COL, 0.55f));
        draw_scale_tick(-25.0f, with_alpha(TEXT_DIM, 0.35f), 10.0f);

        std::vector<CentsScaleLabel> scale_labels = {
            {"+25", 25.0f, with_alpha(TEXT_DIM, 0.55f), 20.0f, true},
            {"+10", 10.0f, with_alpha(GOOD_ZONE_COL, 0.90f), 24.0f, false},
            {"0", 0.0f, with_alpha(TEXT_BRIGHT, 0.80f), 24.0f, false},
            {"-10", -10.0f, with_alpha(GOOD_ZONE_COL, 0.90f), 24.0f, false},
            {"-25", -25.0f, with_alpha(TEXT_DIM, 0.55f), 20.0f, true},
        };
        layout_scale_labels(scale_labels, false);
        layout_scale_labels(scale_labels, true);

        // Good-zone callout inside the band
        {
            const char* good_txt = "GOOD +/-10";
            Vector2 gs = measure_font(g_font_ui, good_txt, 16.0f);
            float gx = trace_x1 - gs.x - 12.0f;
            float gy = mid_y - gs.y * 0.5f;
            draw_font_text(g_font_ui, good_txt, {gx, gy}, 16.0f, with_alpha(GOOD_ZONE_COL, 0.70f));
        }

        // Adjustable in-tune threshold markers (gutter brackets + header label)
        {
            const float tune_y_top = cents_to_y(g_in_tune_cents);
            const float tune_y_bot = cents_to_y(-g_in_tune_cents);
            const float bracket_x = cents_rect_.x + STAFF_GUTTER_W + 2.0f;
            Color tc = with_alpha(TUNE_MARKER_COL, 0.85f);
            DrawLineEx({bracket_x, tune_y_top}, {bracket_x + 10.0f, tune_y_top}, 2.2f, tc);
            DrawLineEx({bracket_x, tune_y_top}, {bracket_x, tune_y_top + 6.0f}, 2.2f, tc);
            DrawLineEx({bracket_x, tune_y_bot}, {bracket_x + 10.0f, tune_y_bot}, 2.2f, tc);
            DrawLineEx({bracket_x, tune_y_bot}, {bracket_x, tune_y_bot - 6.0f}, 2.2f, tc);

            char tune_lbl[32];
            std::snprintf(tune_lbl, sizeof(tune_lbl), "TUNE +/-%.0f  (-/=)", g_in_tune_cents);
            Vector2 tl = measure_font(g_font_ui, tune_lbl, 18.0f);
            draw_font_text(g_font_ui, tune_lbl,
                           {trace_x1 - tl.x - 8.0f, cents_rect_.y + 12.0f}, 18.0f, with_alpha(TUNE_MARKER_COL, 0.9f));
        }

        char info_lbl[80];
        std::snprintf(info_lbl, sizeof(info_lbl), "%s  |  Theme: %s  |  I to switch",
                      g_inst->name, g_pal.name);
        draw_font_text(g_font_ui, info_lbl,
                       {cents_rect_.x + 14.0f, cents_rect_.y + 42.0f}, 16.0f, with_alpha(TEXT_DIM, 0.55f));

        const float sub_px = scroll_subpixel(usable);
        const float nx = beat_to_x(0.0f) - sub_px;

        if (!history_.empty()) {
            const float visible_sec = beats_to_seconds(beats_visible_, bpm_);
            const float now_ts = scroll_now_ts();
            const float oldest_ts = now_ts - visible_sec * 1000.0f - 50.0f;

            struct CentsVis { float x; float y; Color c; };
            std::vector<CentsVis> cvis;
            float last_cents = 0.0f;

            for (const auto& sample : history_) {
                if (sample.teensy_ts <= 0.0f || sample.teensy_ts < oldest_ts) continue;

                float age = (now_ts - sample.teensy_ts) / 1000.0f;
                if (age < 0 || age > visible_sec + 0.7f) continue;

                float sx = beat_to_x(-age * (bpm_ / 60.0f)) - sub_px;
                float cents_val = (sample.note == "---") ? last_cents : sample.cents;
                if (sample.note != "---") last_cents = sample.cents;
                Color col = (sample.note == "---") ? COL_REST : get_color(sample.cents);
                cvis.push_back({sx, mid_y - cents_val * scale_y, col});
            }

            if (!cvis.empty() && nx > cvis.back().x + 0.5f) {
                cvis.push_back({nx, cvis.back().y, cvis.back().c});
            }

            if (cvis.size() >= 2) {
                std::vector<CentsVis> dense;
                dense.reserve(cvis.size() * 3);
                dense.push_back(cvis[0]);
                for (size_t i = 0; i + 1 < cvis.size(); ++i) {
                    float dx = cvis[i + 1].x - cvis[i].x;
                    if (dx > 2.0f) {
                        int steps = std::clamp((int)std::ceil(dx / 2.0f), 2, 14);
                        for (int s = 1; s < steps; ++s) {
                            float t = (float)s / (float)steps;
                            dense.push_back({
                                cvis[i].x + dx * t,
                                cvis[i].y + (cvis[i + 1].y - cvis[i].y) * t,
                                cvis[i + 1].c
                            });
                        }
                    }
                    dense.push_back(cvis[i + 1]);
                }
                cvis.swap(dense);
            }
            if (cvis.size() >= 2) {
                for (size_t i = 0; i + 1 < cvis.size(); ++i) {
                    DrawLineEx({cvis[i].x, cvis[i].y}, {cvis[i+1].x, cvis[i+1].y},
                               1.6f, with_alpha(cvis[i].c, 0.16f));
                    DrawLineEx({cvis[i].x, cvis[i].y}, {cvis[i+1].x, cvis[i+1].y},
                               1.4f, with_alpha(cvis[i].c, 0.92f));
                }
            }
        }

        DrawLineEx({nx, cents_rect_.y + 28}, {nx, cents_rect_.y + cents_rect_.height - 10}, 1.6f, NOW_LINE);
    }

    void draw_bottom_controls() {
        int sw = GetScreenWidth();
        int sh = GetScreenHeight();
        float bar_y = sh - 100.0f;

        DrawRectangleGradientV(0, (int)bar_y, sw, 100, with_alpha(HEADER_BOT, 0.9f), with_alpha(HEADER_TOP, 0.95f));
        DrawRectangle(0, (int)bar_y, sw, 1, with_alpha(ACCENT_BLUE, 0.35f));

        int x = 40;
        auto btn = [&](const char* label, int w = 86) {
            Rectangle r = {(float)x, bar_y + 16, (float)w, 40};
            bool hot = CheckCollisionPointRec(GetMousePosition(), r);
            Color bgc = hot ? with_alpha(ACCENT_BLUE, 0.35f) : with_alpha(PANEL_BG, 0.92f);
            Color border = hot ? NOW_LINE : with_alpha(PANEL_BORDER, 0.6f);
            draw_panel_frame(r, bgc, border, 6.0f);
            draw_font_text(g_font_ui, label, {r.x + 14, r.y + 11}, 15.0f, TEXT_BRIGHT);
            x += w + 10;
            return IsMouseButtonPressed(MOUSE_LEFT_BUTTON) && hot;
        };

        if (btn(paused_ ? "RESUME" : "PAUSE", 96)) paused_ = !paused_;
        if (btn("CLEAR", 80)) clear_history();

        char bpm_txt[32]; std::snprintf(bpm_txt, sizeof(bpm_txt), "BPM %d", (int)bpm_);
        draw_font_text(g_font_ui, bpm_txt, {(float)x + 8, bar_y + 28}, 15.0f, TEXT_DIM);
        x += 88;

        char win_txt[32]; std::snprintf(win_txt, sizeof(win_txt), "WIN %.0f", beats_visible_);
        draw_font_text(g_font_ui, win_txt, {(float)x + 8, bar_y + 28}, 15.0f, TEXT_DIM);
        x += 88;

        const char* metro = metro_on_ ? "METRO ON" : "METRO OFF";
        if (btn(metro, 110)) metro_on_ = !metro_on_;

        const char* hints = paused_
            ? "PAUSED — move mouse over trace to inspect pitch + cents   SPACE resume   Q quit"
            : "[ ] BPM   ; ' window   - = tune   I instrument   T theme   SPACE pause   Q quit";
        Vector2 hint_sz = measure_font(g_font_ui, hints, 36.0f);
        draw_font_text(g_font_ui, hints, {(float)sw - hint_sz.x - 24, bar_y + 52}, 36.0f, with_alpha(TEXT_DIM, 0.60f));
    }

};

// =============================================================================
// ENTRY
// =============================================================================

static void print_usage() {
    std::printf("Intune Raylib Visualizer\n");
    std::printf("  --simulate            Run with built-in musical simulator (default)\n");
    std::printf("  --port COM3           Use real serial port (230400 baud default)\n");
    std::printf("  --baud 230400\n");
    std::printf("  --debug               Verbose console\n");
}

int main(int argc, char** argv) {
    Config cfg;
    cfg.simulate = true;

    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--simulate") {
            cfg.simulate = true;
        } else if (a == "--port" && i + 1 < argc) {
            cfg.port = argv[++i];
            cfg.simulate = false;  // --port always wins over default/--simulate
        } else if (a == "--baud" && i + 1 < argc) {
            cfg.baud = std::stoi(argv[++i]);
        } else if (a == "--debug") {
            cfg.debug = true;
        } else if (a == "--help" || a == "-h") {
            print_usage();
            return 0;
        }
    }
    // If user passed both --port and --simulate, prefer hardware
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--port") {
            cfg.simulate = false;
            break;
        }
    }

    // Seed for sim variety
    std::srand((unsigned)std::time(nullptr));

    IntuneRayViz app(cfg);
    app.run();
    return 0;
}
