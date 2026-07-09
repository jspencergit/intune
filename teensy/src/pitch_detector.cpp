#include "pitch_detector.h"
#include <math.h>
#include <string.h>

static constexpr int kMaxLags = 512;

void AudioAnalyzePitchYin::begin(float threshold) {
  __disable_irq();
  yin_threshold_ = threshold;
  write_pos_ = 0;
  samples_since_hop_ = 0;
  filled_ = 0;
  hop_ready_ = false;
  new_output_ = false;
  freq_hz_ = 0.0f;
  probability_ = 0.0f;
  level_rms_ = 0.0f;
  last_freq_ = 0.0f;
  enabled_ = true;
  memset(ring_, 0, sizeof(ring_));
  __enable_irq();
}

void AudioAnalyzePitchYin::threshold(float t) {
  __disable_irq();
  yin_threshold_ = t;
  __enable_irq();
}

void AudioAnalyzePitchYin::setRange(float fmin_hz, float fmax_hz) {
  __disable_irq();
  if (fmin_hz < 40.0f) fmin_hz = 40.0f;
  if (fmax_hz <= fmin_hz + 20.0f) fmax_hz = fmin_hz + 20.0f;
  fmin_hz_ = fmin_hz;
  fmax_hz_ = fmax_hz;
  __enable_irq();
}

bool AudioAnalyzePitchYin::available() {
  __disable_irq();
  bool flag = new_output_;
  if (flag) new_output_ = false;
  __enable_irq();
  return flag;
}

float AudioAnalyzePitchYin::read() {
  __disable_irq();
  float f = freq_hz_;
  __enable_irq();
  return f;
}

float AudioAnalyzePitchYin::probability() {
  __disable_irq();
  float p = probability_;
  __enable_irq();
  return p;
}

float AudioAnalyzePitchYin::level() {
  __disable_irq();
  float l = level_rms_;
  __enable_irq();
  return l;
}

void AudioAnalyzePitchYin::update() {
  audio_block_t* block = receiveReadOnly();
  if (!block) return;

  if (!enabled_) {
    release(block);
    return;
  }

  const int n = AUDIO_BLOCK_SAMPLES;
  for (int i = 0; i < n; i++) {
    ring_[write_pos_] = block->data[i];
    write_pos_++;
    if (write_pos_ >= kWindow) write_pos_ = 0;
  }
  if (filled_ < kWindow) {
    filled_ += n;
    if (filled_ > kWindow) filled_ = kWindow;
  }
  samples_since_hop_ += n;
  release(block);

  // If a hop is already waiting to be processed, do not overwrite snapshot
  // (drop this hop rather than race). Keeps latency bounded.
  if (filled_ >= kWindow && samples_since_hop_ >= kHop && !hop_ready_) {
    samples_since_hop_ = 0;
    const int base = write_pos_;
    for (int i = 0; i < kWindow; i++) {
      int idx = base + i;
      if (idx >= kWindow) idx -= kWindow;
      snapshot_[i] = ring_[idx];
    }
    hop_ready_ = true;
  } else if (samples_since_hop_ >= kHop) {
    // Still advance hop clock if we dropped so we don't burst later
    samples_since_hop_ = 0;
  }
}

bool AudioAnalyzePitchYin::process() {
  if (!hop_ready_) return false;
  // Copy flag first so ISR may queue the next hop while we analyze.
  analyzeFromSnapshot();
  hop_ready_ = false;
  return true;
}

float AudioAnalyzePitchYin::refinePeriod(const float* d, int tau, int tau_max) const {
  if (tau <= 1 || tau >= tau_max) return (float)tau;
  // Parabolic interpolation on CMND trough: x = 0.5*(s0-s2)/(s0-2*s1+s2)
  float s0 = d[tau - 1];
  float s1 = d[tau];
  float s2 = d[tau + 1];
  float denom = s0 - 2.0f * s1 + s2;
  if (fabsf(denom) < 1e-12f) return (float)tau;
  float delta = 0.5f * (s0 - s2) / denom;
  if (delta < -0.5f) delta = -0.5f;
  if (delta > 0.5f) delta = 0.5f;
  return (float)tau + delta;
}

void AudioAnalyzePitchYin::analyzeFromSnapshot() {
  static float x[kWindow];
  static float d[kMaxLags + 2];

  double energy = 0.0;
  for (int i = 0; i < kWindow; i++) {
    float s = (float)snapshot_[i] * (1.0f / 32768.0f);
    x[i] = s;
    energy += (double)s * (double)s;
  }
  float rms = (float)sqrt(energy / (double)kWindow);
  level_rms_ = rms;

  if (rms < 0.0008f) {
    freq_hz_ = 0.0f;
    probability_ = 0.0f;
    new_output_ = true;
    return;
  }

  const float sr = AUDIO_SAMPLE_RATE_EXACT;
  int tau_min = (int)floorf(sr / fmax_hz_);
  int tau_max = (int)ceilf(sr / fmin_hz_);
  if (tau_min < 2) tau_min = 2;
  if (tau_max >= kWindow / 2) tau_max = kWindow / 2 - 1;
  if (tau_max >= kMaxLags) tau_max = kMaxLags - 1;
  if (tau_max <= tau_min + 2) {
    freq_hz_ = 0.0f;
    probability_ = 0.0f;
    new_output_ = true;
    return;
  }

  // YIN difference function
  d[0] = 1.0f;
  for (int tau = 1; tau <= tau_max; tau++) {
    float sum = 0.0f;
    const int nsum = kWindow - tau;
    int j = 0;
    for (; j + 3 < nsum; j += 4) {
      float d0 = x[j] - x[j + tau];
      float d1 = x[j + 1] - x[j + 1 + tau];
      float d2 = x[j + 2] - x[j + 2 + tau];
      float d3 = x[j + 3] - x[j + 3 + tau];
      sum += d0 * d0 + d1 * d1 + d2 * d2 + d3 * d3;
    }
    for (; j < nsum; j++) {
      float dd = x[j] - x[j + tau];
      sum += dd * dd;
    }
    d[tau] = sum;
  }

  // Cumulative mean normalized difference
  float running = 0.0f;
  d[0] = 1.0f;
  for (int tau = 1; tau <= tau_max; tau++) {
    running += d[tau];
    if (running > 0.0f) {
      d[tau] = d[tau] * (float)tau / running;
    } else {
      d[tau] = 1.0f;
    }
  }

  // Classic YIN: first (smallest-tau) local minimum below absolute threshold.
  // Preferring long periods causes subharmonic errors (A4→D3 = 3× period).
  int chosen_tau = -1;
  float best_cmnd = 1.0f;

  for (int tau = tau_min + 1; tau < tau_max; tau++) {
    if (d[tau] < yin_threshold_ && d[tau] <= d[tau - 1] && d[tau] < d[tau + 1]) {
      chosen_tau = tau;
      best_cmnd = d[tau];
      break;
    }
  }

  // Soft fallback: global min if nothing under threshold
  if (chosen_tau < 0) {
    int best_tau = tau_min;
    float best_v = d[tau_min];
    for (int tau = tau_min + 1; tau <= tau_max; tau++) {
      if (d[tau] < best_v) {
        best_v = d[tau];
        best_tau = tau;
      }
    }
    if (best_v < 0.30f && best_tau > tau_min && best_tau < tau_max) {
      chosen_tau = best_tau;
      best_cmnd = best_v;
    } else {
      freq_hz_ = 0.0f;
      probability_ = 0.0f;
      new_output_ = true;
      return;
    }
  }

  // Continuity: only suppress sudden *octave* flips, not stepwise pitch changes.
  // If the new estimate is ~2× or ~½× the previous stable pitch, and a strong
  // trough still exists near the previous period, keep the previous octave.
  if (last_freq_ > 50.0f) {
    float f_new = sr / (float)chosen_tau;
    float ratio = f_new / last_freq_;
    if (ratio < 1.0f) ratio = 1.0f / ratio;
    if (ratio > 1.85f && ratio < 2.20f) {
      int tau_prev = (int)lroundf(sr / last_freq_);
      if (tau_prev > tau_min + 1 && tau_prev < tau_max - 1) {
        int lo = tau_prev - 2;
        int hi = tau_prev + 2;
        if (lo < tau_min + 1) lo = tau_min + 1;
        if (hi > tau_max - 1) hi = tau_max - 1;
        int cont_tau = -1;
        float cont_v = 1.0f;
        for (int tau = lo; tau <= hi; tau++) {
          if (d[tau] <= d[tau - 1] && d[tau] <= d[tau + 1] && d[tau] < cont_v) {
            cont_v = d[tau];
            cont_tau = tau;
          }
        }
        if (cont_tau > 0 && cont_v < 0.20f) {
          chosen_tau = cont_tau;
          best_cmnd = cont_v;
        }
      }
    }
  }

  // Octave-down correction only: if first min is likely 2f0 (strong partial),
  // and 2*tau is also a clean min with similar/better CMND, take the lower pitch.
  // Do NOT walk to 3τ/4τ (subharmonics).
  {
    int t2 = chosen_tau * 2;
    if (t2 + 1 < tau_max && t2 - 1 > tau_min) {
      bool t2_min = (d[t2] <= d[t2 - 1] && d[t2] <= d[t2 + 1]);
      if (t2_min && d[t2] < yin_threshold_ * 1.05f && d[t2] <= best_cmnd + 0.04f) {
        // Only if half-period trough is not *much* deeper than 2τ (partial case)
        // When true f0 is chosen_tau, d[t2] is usually higher; when chosen is T/2, d[t2]≈d[T].
        if (d[t2] < best_cmnd + 0.02f || best_cmnd > 0.08f) {
          // Require last_freq agreement OR first min relatively weak
          float f2 = sr / (float)t2;
          bool cont = (last_freq_ > 50.0f && fabsf(f2 - last_freq_) / last_freq_ < 0.06f);
          bool weak_first = best_cmnd > 0.06f && d[t2] < 0.10f;
          if (cont || weak_first) {
            chosen_tau = t2;
            best_cmnd = d[t2];
          }
        }
      }
    }
  }

  float period = refinePeriod(d, chosen_tau, tau_max);
  if (period < 2.0f) {
    freq_hz_ = 0.0f;
    probability_ = 0.0f;
    new_output_ = true;
    return;
  }

  float f = sr / period;
  if (f < fmin_hz_ * 0.95f || f > fmax_hz_ * 1.05f) {
    freq_hz_ = 0.0f;
    probability_ = 0.0f;
    new_output_ = true;
    return;
  }

  float cmnd = d[chosen_tau];
  float prob = 1.0f - cmnd;
  if (prob < 0.0f) prob = 0.0f;
  if (prob > 1.0f) prob = 1.0f;

  freq_hz_ = f;
  probability_ = prob;
  last_freq_ = f;
  new_output_ = true;
}
