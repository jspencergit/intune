#pragma once

#include <Arduino.h>
#include <AudioStream.h>

/*
 * Overlapping-window YIN pitch detector for monophonic bowed strings
 * (viola / violin range by default).
 *
 * Audio ISR only fills a ring buffer and sets a "hop ready" flag.
 * Call process() from loop() to run YIN (must not run inside ISR).
 */

class AudioAnalyzePitchYin : public AudioStream {
public:
  // 2048 ≈ 46 ms window @ 44.1 kHz; hop 256 ≈ 5.8 ms.
  static constexpr int kWindow = 2048;
  static constexpr int kHop = 256;

  AudioAnalyzePitchYin()
      : AudioStream(1, inputQueueArray),
        write_pos_(0),
        samples_since_hop_(0),
        filled_(0),
        enabled_(false),
        hop_ready_(false),
        new_output_(false),
        yin_threshold_(0.12f),
        fmin_hz_(120.0f),
        fmax_hz_(2800.0f),
        freq_hz_(0.0f),
        probability_(0.0f),
        level_rms_(0.0f),
        last_freq_(0.0f) {}

  void begin(float threshold = 0.12f);
  void threshold(float t);
  void setRange(float fmin_hz, float fmax_hz);

  // Run from loop(): processes at most one pending hop. Returns true if a new
  // pitch estimate was produced (also sets available()).
  bool process();

  bool available();
  float read();          // Hz
  float probability();   // 0..1
  float level();         // RMS ~0..1

  virtual void update(void) override;

private:
  void analyzeFromSnapshot();
  float refinePeriod(const float* d, int tau, int tau_max) const;

  audio_block_t* inputQueueArray[1];

  int16_t ring_[kWindow];
  int write_pos_;
  int samples_since_hop_;
  int filled_;

  // Snapshot for analysis in loop() (ISR only writes when hop_ready_ is clear).
  int16_t snapshot_[kWindow];
  bool enabled_;
  volatile bool hop_ready_;
  volatile bool new_output_;

  float yin_threshold_;
  float fmin_hz_;
  float fmax_hz_;

  float freq_hz_;
  float probability_;
  float level_rms_;
  float last_freq_;
};
