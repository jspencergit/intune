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
//   C              Clear
//   Q / Esc        Quit
//   Mouse (paused) Inspect values
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
constexpr int   POINTS_PER_SEC  = 60;
constexpr float IN_TUNE_CENTS   = 5.0f;

struct Config {
    std::string port = "COM3";
    int baud = 115200;
    bool simulate = true;
    bool debug = false;
};

// Musical staff Y mapping (identical semantics to the Python version for compatibility)
constexpr float Y_REST     = 0.8f;
constexpr float Y_C3       = 1.2f;
constexpr float Y_STEP     = 0.4f;   // 0.4 per semitone step in our normalized space
// Pitch-space range for first-position viola (used to flip Y: low notes at bottom of screen)
constexpr float STAFF_PITCH_MIN = 1.2f;   // C3
constexpr float STAFF_PITCH_MAX = 7.6f;   // E5

// Full practical first-position range labels
const std::vector<std::pair<std::string, float>> NOTE_LABELS = {
    {"C3", 1.2f}, {"D3", 1.6f}, {"E3", 2.0f}, {"F3", 2.4f}, {"G3", 2.8f},
    {"A3", 3.2f}, {"B3", 3.6f}, {"C4", 4.0f}, {"D4", 4.4f}, {"E4", 4.8f},
    {"F4", 5.2f}, {"G4", 5.6f}, {"A4", 6.0f}, {"B4", 6.4f}, {"C5", 6.8f},
    {"D5", 7.2f}, {"E5", 7.6f},
};

const std::vector<float> STAFF_MAIN = {2.8f, 3.6f, 4.4f, 5.2f, 6.0f};
const std::vector<float> STAFF_LEDGER = {
    1.2f, 1.6f, 2.4f, 3.2f, 4.0f, 4.8f, 5.6f, 6.4f, 7.2f
};

// Keysight-style oscilloscope palette — dark graticule, high-contrast traces
const Color BG            = {0x0a, 0x0c, 0x0e, 0xff};
const Color HEADER_TOP    = {0x14, 0x18, 0x1c, 0xff};
const Color HEADER_BOT    = {0x1e, 0x24, 0x2a, 0xff};
const Color PANEL_BG      = {0x12, 0x16, 0x1a, 0xf0};
const Color PANEL_BORDER  = {0x3a, 0x48, 0x54, 0xff};
const Color STAFF_SURFACE = {0x0e, 0x12, 0x16, 0xff};
const Color STAFF_LINE    = {0x3a, 0x4e, 0x5c, 0xbb};
const Color LEDGER_LINE   = {0x2a, 0x38, 0x44, 0x88};
const Color LABEL_COLOR   = {0x8a, 0x9a, 0xa8, 0xff};
const Color NOW_LINE      = {0xe8, 0xec, 0xf0, 0xdd}; // bright scope cursor
const Color TEXT_BRIGHT   = {0xe8, 0xec, 0xf0, 0xff};
const Color TEXT_DIM      = {0x7a, 0x8a, 0x98, 0xff};
const Color ACCENT_BLUE   = {0x4a, 0x90, 0xc8, 0xff};

// Trace channels (Keysight ch1 yellow, ch2 cyan, warm red for sharp)
const Color COL_IN_TUNE   = {0x3d, 0xf0, 0x7a, 0xff}; // phosphor green
const Color COL_SHARP     = {0xff, 0x55, 0x44, 0xff}; // warm red
const Color COL_FLAT      = {0x00, 0xcc, 0xee, 0xff}; // cyan / ch2
const Color COL_REST      = {0x3a, 0x48, 0x54, 0x55};
const Color BEAT_GRID_COL = {0x3a, 0x4c, 0x58, 0xff};
const Color BAR_GRID_COL  = {0x5a, 0x70, 0x80, 0xff};

constexpr float TRACE_CORE_WIDTH = 2.4f;
constexpr int   HUD_HEIGHT       = 96;
constexpr float STAFF_GUTTER_W   = 80.0f;  // fixed left column for clef + labels

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
    float   teensy_ts;   // device millis or our sim time
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
    float flipped = STAFF_PITCH_MIN + STAFF_PITCH_MAX - pitch_y;
    return staff_top + flipped * y_scale;
}

float pitch_to_y(const std::string& note_str) {
    if (note_str.empty()) return 4.0f;
    if (note_str == "---" || note_str == "REST") return Y_REST;
    char note = static_cast<char>(std::toupper(note_str[0]));
    // Extract octave (last digit char)
    int octave = 3;
    for (int i = (int)note_str.size() - 1; i >= 0; --i) {
        if (std::isdigit(note_str[i])) {
            octave = note_str[i] - '0';
            break;
        }
    }
    static const int base[7] = {0,2,4,5,7,9,11}; // C D E F G A B  (for semitone, not needed here)
    // Our normalized staff space: C3=1.2, each step = 0.4
    int step = 0;
    switch (note) {
        case 'C': step=0; break; case 'D': step=1; break; case 'E': step=2; break;
        case 'F': step=3; break; case 'G': step=4; break; case 'A': step=5; break;
        case 'B': step=6; break;
        default: return 4.0f;
    }
    float y = 1.2f + (step + (octave - 3) * 7) * Y_STEP;
    return y;
}

Color get_color(float cents) {
    if (std::fabs(cents) < IN_TUNE_CENTS) return COL_IN_TUNE;
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
            local_ts += dt * 1000.0f;
            phase += dt * 1.6f;

            // Occasionally change base note or insert a rest (feels like real practice)
            if (t > rest_until && (std::rand() % 180 == 0)) {
                is_rest = !is_rest;
                if (is_rest) {
                    rest_until = t + 0.6f + (std::rand() % 100) / 80.0f; // 0.6–1.8s rests
                } else {
                    // occasional note change (gliss / shift)
                    static const char* notes[] = {"C3","D3","E3","F3","G3","A3","B3","C4","D4","E4","F4","G4","A4"};
                    current_note = notes[std::rand() % (sizeof(notes)/sizeof(notes[0]))];
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

            // ~50-60 Hz output rate
            std::this_thread::sleep_for(std::chrono::milliseconds(18));
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

void draw_alto_clef(Vector2 base, float scale, Color col) {
    // Stylized alto clef (C-clef). Good enough to read as "proper" on the staff.
    // Vertical spine + two "C" curves (upper + lower) + small diamond/ear.
    float x = base.x;
    float y = base.y;
    float s = scale;

    // Main vertical bar
    DrawLineEx({x, y - 38*s}, {x, y + 38*s}, 3.5f*s, col);

    // Upper curve (like a fat C or backwards 3)
    Vector2 p1 = {x, y - 28*s};
    Vector2 p2 = {x + 14*s, y - 32*s};
    Vector2 p3 = {x + 22*s, y - 18*s};
    DrawLineEx(p1, p2, 2.8f*s, col);
    DrawLineEx(p2, p3, 2.6f*s, col);
    DrawLineEx(p3, {x + 11*s, y - 8*s}, 2.6f*s, col);
    DrawLineEx({x + 11*s, y - 8*s}, {x + 2*s, y - 12*s}, 2.4f*s, col);

    // Lower curve
    Vector2 q1 = {x, y + 28*s};
    Vector2 q2 = {x + 14*s, y + 32*s};
    Vector2 q3 = {x + 22*s, y + 18*s};
    DrawLineEx(q1, q2, 2.8f*s, col);
    DrawLineEx(q2, q3, 2.6f*s, col);
    DrawLineEx(q3, {x + 11*s, y + 8*s}, 2.6f*s, col);
    DrawLineEx({x + 11*s, y + 8*s}, {x + 2*s, y + 12*s}, 2.4f*s, col);

    // Small central "waist" diamond / ear
    DrawCircleV({x + 4*s, y}, 3.5f*s, col);
    DrawCircleV({x + 4*s, y}, 1.6f*s, BG); // cutout for classic look
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
        InitWindow(DEFAULT_WIDTH, DEFAULT_HEIGHT, "Intune — Viola (Raylib) • Smooth Musical Staff");
        SetTargetFPS(60);
        SetExitKey(KEY_NULL);
        SetWindowFocused();
        load_ui_fonts();

        beats_visible_ = DEFAULT_BEATS;
        bpm_ = DEFAULT_BPM;
        display_now_ = 0.0f;
        last_wall_ = std::chrono::steady_clock::now();
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
    float latest_ts_ = 0.0f;
    std::chrono::steady_clock::time_point last_wall_;

    // Audio is initialized lazily after the first frame so the window becomes responsive immediately.
    // (InitAudioDevice + LoadSound can block for a long time on some Windows audio drivers.)
    bool audio_initialized_ = false;

    // Gamification
    float current_streak_s_ = 0.0f;
    bool  clock_initialized_ = false;
    float visible_accuracy_ = 0.0f; // 0..100
    // Metronome
    bool  metro_on_ = false;
    float last_beat_beat_ = -1.0f;
    Sound click_sound_{0};
    Sound accent_sound_{0};

    // Inspection (paused)
    bool  show_crosshair_ = false;
    float cross_x_ = 0.0f;
    float cross_y_ = 0.0f;
    PitchSample cross_sample_{};

    // View geometry (updated each frame)
    Rectangle staff_rect_{};
    Rectangle cents_rect_{};
    float staff_y_scale_ = 82.0f; // pixels per staff unit
    size_t last_trace_pts_ = 0;   // visible polyline points last frame (HUD diagnostic)

    // Smooth scroll clock: advances every frame; catches up if device is ahead.
    float scroll_now_ts() const {
        float now = display_now_;
        if (latest_ts_ > now) now = latest_ts_;
        return now;
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

    // Reference "now" for age/scroll math. Teensy millis() is absolute since boot;
    // display_now_ starts near 0 — must use max() like the Python visualizer or every
    // hardware sample has negative age and is filtered out of the trace.
    float effective_now_ts() const {
        return std::max(display_now_, latest_ts_);
    }

    void refresh_latest_ts() {
        for (auto it = history_.rbegin(); it != history_.rend(); ++it) {
            if (it->teensy_ts > latest_ts_) {
                latest_ts_ = it->teensy_ts;
            }
        }
    }

    void handle_input(float /*dt*/) {
        if (IsKeyPressed(KEY_SPACE) || IsKeyPressed(KEY_P)) {
            paused_ = !paused_;
            if (!paused_) {
                last_wall_ = std::chrono::steady_clock::now();
                if (latest_ts_ > 0.0f) {
                    display_now_ = std::max(display_now_, latest_ts_);
                }
            }
        }
        if (IsKeyPressed(KEY_C)) {
            clear_history();
        }
        if (IsKeyPressed(KEY_M)) {
            metro_on_ = !metro_on_;
        }

        // BPM
        if (IsKeyPressed(KEY_LEFT_BRACKET))  bpm_ = std::max(36.0f, bpm_ - 1.0f);
        if (IsKeyPressed(KEY_RIGHT_BRACKET)) bpm_ = std::min(200.0f, bpm_ + 1.0f);
        if (IsKeyDown(KEY_LEFT_BRACKET) && GetFrameTime() > 0.12f) bpm_ = std::max(36.0f, bpm_ - 0.6f);
        if (IsKeyDown(KEY_RIGHT_BRACKET) && GetFrameTime() > 0.12f) bpm_ = std::min(200.0f, bpm_ + 0.6f);

        // Visible window
        if (IsKeyPressed(KEY_SEMICOLON)) beats_visible_ = std::max(1.5f, beats_visible_ - 0.25f);
        if (IsKeyPressed(KEY_APOSTROPHE)) beats_visible_ = std::min(16.0f, beats_visible_ + 0.25f);

        // Mouse inspection only meaningful when paused
        if (paused_) {
            Vector2 m = GetMousePosition();
            if (CheckCollisionPointRec(m, staff_rect_)) {
                if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON) || IsMouseButtonDown(MOUSE_LEFT_BUTTON)) {
                    show_crosshair_ = true;
                    cross_x_ = m.x;
                    cross_y_ = m.y;
                    pick_crosshair_sample(m.x);
                }
            } else {
                if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON)) {
                    show_crosshair_ = false;
                }
            }
        } else {
            show_crosshair_ = false;
        }
    }

    void drain_incoming() {
        if (paused_) return;

        std::lock_guard<std::mutex> lk(g_incoming_mtx);
        while (!g_incoming.empty()) {
            const auto& s = g_incoming.front();
            history_.push_back(s);
            if (s.teensy_ts > latest_ts_) {
                latest_ts_ = s.teensy_ts;
            }
            g_incoming.pop_front();
            if (history_.size() > 2800) history_.pop_front();
        }

        // One-time clock sync on first HW packet (Teensy millis is absolute since boot).
        // Do NOT snap every batch — that causes scroll jitter.
        if (!config_.simulate && latest_ts_ > 0.0f && !clock_initialized_) {
            display_now_ = latest_ts_;
            clock_initialized_ = true;
        }
    }

    void update_timing(float dt) {
        if (paused_) return;

        // Advance display time for smooth creep between packets
        display_now_ += dt * 1000.0f;
        refresh_latest_ts();
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

                if (std::fabs(s.cents) <= IN_TUNE_CENTS) {
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
        display_now_ = 0.0f;
        latest_ts_ = 0.0f;
        current_streak_s_ = 0.0f;
        show_crosshair_ = false;
    }

    void pick_crosshair_sample(float screen_x) {
        if (history_.size() < 2) return;

        float left_beat = -beats_visible_;
        float right_beat = 0.28f;
        float trace_x0 = staff_rect_.x + STAFF_GUTTER_W + 10.0f;
        float trace_x1 = staff_rect_.x + staff_rect_.width - 14.0f;
        float usable_w = trace_x1 - trace_x0;

        float target_beat = left_beat + (screen_x - trace_x0) / usable_w * (right_beat - left_beat);

        float best_d = 1e9f;
        PitchSample best{};
        for (auto& s : history_) {
            if (s.teensy_ts <= 0.0f) continue;
            float age = (scroll_now_ts() - s.teensy_ts) / 1000.0f;
            if (age < 0 || age > beats_to_seconds(beats_visible_, bpm_) + 1.0f) continue;
            float bx = -age * (bpm_ / 60.0f);
            float d = std::fabs(bx - target_beat);
            if (d < best_d) {
                best_d = d;
                best = s;
            }
        }
        if (best_d < 0.6f) {
            cross_sample_ = best;
            cross_x_ = screen_x;
            cross_y_ = staff_pitch_to_screen_y(best.y_pos, staff_rect_.y, staff_y_scale_);
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
        draw_panel_frame(note_card, with_alpha({0x08, 0x14, 0x30}, 0.75f), card_border, 8.0f);

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
        draw_panel_frame(streak_card, with_alpha({0x08, 0x14, 0x30}, 0.65f), with_alpha(PANEL_BORDER, 0.5f), 6.0f);
        draw_panel_frame(acc_card,    with_alpha({0x08, 0x14, 0x30}, 0.65f), with_alpha(PANEL_BORDER, 0.5f), 6.0f);

        draw_label_caps("IN TUNE", (int)streak_card.x + 12, (int)streak_card.y + 10, 11, with_alpha(TEXT_DIM, 0.65f));
        Color streak_col = (current_streak_s_ > 0.3f) ? COL_IN_TUNE : TEXT_BRIGHT;
        draw_font_text(g_font_ui, streak_val, {streak_card.x + 12, streak_card.y + 30}, 22.0f, streak_col);

        draw_label_caps("ACCURACY", (int)acc_card.x + 12, (int)acc_card.y + 10, 11, with_alpha(TEXT_DIM, 0.65f));
        draw_font_text(g_font_ui, acc_val, {acc_card.x + 12, acc_card.y + 30}, 22.0f, TEXT_BRIGHT);
    }

    void draw_staff_view() {
        int sw = GetScreenWidth();

        staff_rect_ = {36.0f, (float)HUD_HEIGHT + 14.0f, (float)sw - 72.0f, 508.0f};
        staff_y_scale_ = staff_rect_.height / 8.6f;

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
        DrawRectangleRounded(gutter, 6.0f, 6, with_alpha({0x15, 0x1a, 0x22}, 0.85f));
        float div_x = staff_rect_.x + STAFF_GUTTER_W + 6.0f;
        DrawLineEx({div_x, staff_rect_.y + 10}, {div_x, staff_rect_.y + staff_rect_.height - 10},
                   1.0f, with_alpha(PANEL_BORDER, 0.45f));

        // In-tune shaded bands (trace area only)
        for (float sy : STAFF_MAIN) {
            draw_intune_band(sy, trace_x0, trace_x1, staff_rect_.y, staff_y_scale_, COL_IN_TUNE);
        }

        // Staff lines (trace area only — don't cross the gutter)
        for (float sy : STAFF_MAIN) {
            float yy = y_to_screen(sy);
            DrawLineEx({trace_x0, yy}, {trace_x1, yy}, 1.4f, STAFF_LINE);
        }
        for (float sy : STAFF_LEDGER) {
            float yy = y_to_screen(sy);
            DrawLineEx({trace_x0 + 4, yy}, {trace_x1 - 4, yy}, 0.8f, LEDGER_LINE);
        }

        // Alto clef — fixed in gutter, centered on middle line
        float clef_x = staff_rect_.x + 22.0f;
        draw_alto_clef({clef_x, y_to_screen(4.4f)}, 0.88f, with_alpha(STAFF_LINE, 0.9f));

        // Pitch labels — fixed column, all notes, letter + subscript octave
        float label_right = staff_rect_.x + STAFF_GUTTER_W - 8.0f;
        for (const auto& [nm, yy] : NOTE_LABELS) {
            draw_pitch_label(nm.c_str(), label_right, y_to_screen(yy));
        }

        // Panel header (top-right of staff — avoids trace overlap)
        char time_label[64];
        std::snprintf(time_label, sizeof(time_label), "%d BPM  |  %.0f beats", (int)bpm_, beats_visible_);
        Vector2 tl_sz = measure_font(g_font_ui, time_label, 14.0f);
        draw_font_text(g_font_ui, time_label,
                       {staff_rect_.x + staff_rect_.width - tl_sz.x - 16, staff_rect_.y + 10},
                       14.0f, with_alpha(TEXT_DIM, 0.8f));
        draw_label_caps("PITCH TRACE", (int)trace_x0, (int)(staff_rect_.y + 52), 11, with_alpha(TEXT_DIM, 0.55f));

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

        // === THE TRACE ===
        last_trace_pts_ = 0;
        if (history_.size() >= 2) {
            const float visible_sec = beats_to_seconds(beats_visible_, bpm_);
            const float now_ts = scroll_now_ts();

            std::vector<TraceVisPt> vis;
            float last_y = 4.0f;
            TraceVisPt latest_pt{};
            bool have_latest = false;

            for (const auto& s : history_) {
                if (s.teensy_ts <= 0.0f) continue;
                float age = (now_ts - s.teensy_ts) / 1000.0f;
                if (age < 0 || age > visible_sec + 0.7f) continue;

                float bx = -age * (bpm_ / 60.0f);
                float sx = beat_to_screen(bx);

                bool rest = (s.note == "---");
                Color col;
                float alpha;
                float yy;

                if (rest) {
                    col = COL_REST;
                    alpha = 0.55f;
                    yy = (last_y > 0.1f) ? last_y : s.y_pos;
                } else {
                    col = get_color(s.cents);
                    alpha = (s.confidence > 0.01f) ? std::clamp(0.35f + s.confidence * 0.65f, 0.45f, 1.0f) : 0.88f;
                    yy = s.y_pos;
                    last_y = yy;
                    latest_pt = {sx, y_to_screen(yy), col, alpha};
                    have_latest = true;
                }

                vis.push_back({sx, y_to_screen(yy), col, alpha});
            }

            if (have_latest) {
                float play_x = beat_to_screen(0.0f);
                if (play_x > latest_pt.x + 1.0f) {
                    vis.push_back({play_x, latest_pt.y, latest_pt.c, latest_pt.a});
                }
            }

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

        // Playhead — gold cursor line
        float now_screen_x = beat_to_screen(0.0f);
        DrawLineEx({now_screen_x, staff_rect_.y + 54}, {now_screen_x, staff_rect_.y + staff_rect_.height - 10},
                   2.0f, NOW_LINE);

        if (!history_.empty()) {
            float target_y = 4.0f;
            for (auto it = history_.rbegin(); it != history_.rend(); ++it) {
                if (it->note != "---") { target_y = it->y_pos; break; }
            }
            float ty = y_to_screen(target_y);
            DrawCircleV({now_screen_x, ty}, 7.0f, with_alpha(NOW_LINE, 0.12f));
            DrawCircleV({now_screen_x, ty}, 3.8f, with_alpha(NOW_LINE, 0.45f));
            DrawCircleV({now_screen_x, ty}, 1.8f, TEXT_BRIGHT);
        }

        // Crosshair + tooltip (paused inspection)
        if (paused_ && show_crosshair_) {
            DrawLineEx({cross_x_, staff_rect_.y + 4}, {cross_x_, staff_rect_.y + staff_rect_.height - 4},
                       1.0f, with_alpha(COL_SHARP, 0.7f));
            DrawLineEx({staff_rect_.x + 4, cross_y_}, {staff_rect_.x + staff_rect_.width - 4, cross_y_},
                       1.0f, with_alpha(COL_SHARP, 0.7f));

            // Tooltip
            char tip[128];
            std::snprintf(tip, sizeof(tip), "%s  %+.1f¢", cross_sample_.note.c_str(), cross_sample_.cents);
            Vector2 tip_sz = measure_font(g_font_ui, tip, 16.0f);
            float tx = cross_x_ + 14;
            float ty = cross_y_ - 28;
            DrawRectangle((int)tx - 6, (int)ty - 4, (int)tip_sz.x + 12, 24, with_alpha({0x0a, 0x0a, 0x12}, 0.85f));
            draw_font_text(g_font_ui, tip, {tx, ty}, 16.0f, TEXT_BRIGHT);
        }
    }

    // Very small helper because raylib Color doesn't have == by default in all versions
    static bool ColorIsEqualish(Color a, Color b) {
        return a.r == b.r && a.g == b.g && a.b == b.b;
    }

    void draw_cents_ribbon() {
        int sw = GetScreenWidth();
        cents_rect_ = {36.0f, staff_rect_.y + staff_rect_.height + 12.0f, (float)sw - 72.0f, 152.0f};

        draw_panel_frame(cents_rect_, with_alpha(STAFF_SURFACE, 0.95f), PANEL_BORDER, 8.0f);

        float trace_x0 = cents_rect_.x + STAFF_GUTTER_W + 10.0f;
        float trace_x1 = cents_rect_.x + cents_rect_.width - 14.0f;

        float left_beat  = -beats_visible_;
        float right_beat = 0.28f;
        float usable = trace_x1 - trace_x0;

        auto beat_to_x = [&](float b) {
            return trace_x0 + (b - left_beat) / (right_beat - left_beat) * usable;
        };

        float mid_y = cents_rect_.y + cents_rect_.height * 0.52f;
        float scale_y = (cents_rect_.height * 0.38f) / 25.0f;

        // In-tune band (±5¢)
        float off = IN_TUNE_CENTS * scale_y;
        DrawRectangle((int)trace_x0, (int)(mid_y - off), (int)(trace_x1 - trace_x0), (int)(off * 2.0f),
                      with_alpha(COL_IN_TUNE, 0.06f));

        DrawLineEx({trace_x0, mid_y}, {trace_x1, mid_y}, 1.4f, with_alpha(COL_IN_TUNE, 0.45f));
        DrawLineEx({trace_x0, mid_y - off}, {trace_x1, mid_y - off}, 0.8f, with_alpha(COL_IN_TUNE, 0.22f));
        DrawLineEx({trace_x0, mid_y + off}, {trace_x1, mid_y + off}, 0.8f, with_alpha(COL_IN_TUNE, 0.22f));

        draw_label_caps("CENTS DEVIATION", (int)(cents_rect_.x + 14), (int)(cents_rect_.y + 10), 11, with_alpha(TEXT_DIM, 0.65f));
        draw_font_text(g_font_ui, "+25", {cents_rect_.x + 14, mid_y - scale_y * 25.0f - 6}, 12.0f, with_alpha(TEXT_DIM, 0.45f));
        draw_font_text(g_font_ui, "0",   {cents_rect_.x + 14, mid_y - 6}, 12.0f, with_alpha(TEXT_DIM, 0.45f));
        draw_font_text(g_font_ui, "-25", {cents_rect_.x + 14, mid_y + scale_y * 25.0f - 6}, 12.0f, with_alpha(TEXT_DIM, 0.45f));

        // Trace (colored like the staff trace for consistency)
        if (history_.size() >= 2) {
            const float visible_sec = beats_to_seconds(beats_visible_, bpm_);
            const float now_ts = scroll_now_ts();

            struct CentsVis { float x; float y; Color c; };
            std::vector<CentsVis> cvis;
            float last_cents = 0.0f;
            for (const auto& s : history_) {
                if (s.teensy_ts <= 0.0f) continue;
                float age = (now_ts - s.teensy_ts) / 1000.0f;
                if (age < 0 || age > visible_sec + 0.7f) continue;
                float bx = -age * (bpm_ / 60.0f);
                float sx = beat_to_x(bx);
                float cents_val = (s.note == "---") ? last_cents : s.cents;
                if (s.note != "---") last_cents = s.cents;
                float cy = mid_y - cents_val * scale_y;
                Color col = (s.note == "---") ? COL_REST : get_color(s.cents);
                cvis.push_back({sx, cy, col});
            }
            if (!cvis.empty()) {
                float play_x = beat_to_x(0.0f);
                if (play_x > cvis.back().x + 1.0f) {
                    cvis.push_back({play_x, cvis.back().y, cvis.back().c});
                }
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

        float nx = beat_to_x(0.0f);
        DrawLineEx({nx, cents_rect_.y + 28}, {nx, cents_rect_.y + cents_rect_.height - 10}, 1.6f, NOW_LINE);
    }

    void draw_bottom_controls() {
        int sw = GetScreenWidth();
        int sh = GetScreenHeight();
        float bar_y = sh - 72.0f;

        DrawRectangleGradientV(0, (int)bar_y, sw, 72, with_alpha(HEADER_BOT, 0.9f), with_alpha(HEADER_TOP, 0.95f));
        DrawRectangle(0, (int)bar_y, sw, 1, with_alpha(ACCENT_BLUE, 0.35f));

        int x = 40;
        auto btn = [&](const char* label, int w = 86) {
            Rectangle r = {(float)x, bar_y + 16, (float)w, 40};
            bool hot = CheckCollisionPointRec(GetMousePosition(), r);
            Color bgc = hot ? with_alpha(ACCENT_BLUE, 0.35f) : with_alpha({0x08, 0x14, 0x30}, 0.8f);
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

        const char* hints = "[ ] BPM  ; ' window  M metro  SPACE pause  C clear  Q quit";
        Vector2 hint_sz = measure_font(g_font_ui, hints, 12.0f);
        draw_font_text(g_font_ui, hints, {(float)sw - hint_sz.x - 36, bar_y + 30}, 12.0f, with_alpha(TEXT_DIM, 0.55f));
    }

};

// =============================================================================
// ENTRY
// =============================================================================

static void print_usage() {
    std::printf("Intune Raylib Visualizer\n");
    std::printf("  --simulate            Run with built-in musical simulator (default)\n");
    std::printf("  --port COM3           Use real serial port (115200 baud default)\n");
    std::printf("  --baud 115200\n");
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
