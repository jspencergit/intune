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

void AudioAnalyzePitchYin::clearContinuity() {
  __disable_irq();
  last_freq_ = 0.0f;
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

float AudioAnalyzePitchYin::goertzelPower(const float* x, int n, float freq_hz) const {
  // Hann-windowed Goertzel power at freq_hz (Teensy-cheap single-bin DFT).
  const float sr = AUDIO_SAMPLE_RATE_EXACT;
  if (freq_hz < 1.0f || freq_hz > sr * 0.45f || n < 8) return 0.0f;
  const float w = 2.0f * 3.14159265f * freq_hz / sr;
  const float coeff = 2.0f * cosf(w);
  float s0 = 0.0f, s1 = 0.0f, s2 = 0.0f;
  const float inv_n1 = 1.0f / (float)(n - 1);
  for (int i = 0; i < n; i++) {
    const float hann = 0.5f - 0.5f * cosf(2.0f * 3.14159265f * (float)i * inv_n1);
    s0 = x[i] * hann + coeff * s1 - s2;
    s2 = s1;
    s1 = s0;
  }
  float p = s1 * s1 + s2 * s2 - coeff * s1 * s2;
  if (p < 0.0f) p = 0.0f;
  return p;
}

float AudioAnalyzePitchYin::harmonicScore(const float* x, int n, float f0_hz) const {
  // Pure-tone safe harmonic score:
  //   g(f0) * (eps + g(2f0)) * (eps + g(3f0))
  // True f0 keeps energy at f0; a pure tone at f wrongly scored as f/2 has ~0 at f/2.
  // Bowed partials still reward candidates whose integer harmonics are present.
  const float sr = AUDIO_SAMPLE_RATE_EXACT;
  if (f0_hz < fmin_hz_ * 0.9f || f0_hz > fmax_hz_ * 1.1f) return 0.0f;
  const float g1 = goertzelPower(x, n, f0_hz);
  const float g2 = (2.0f * f0_hz < sr * 0.45f) ? goertzelPower(x, n, 2.0f * f0_hz) : 0.0f;
  const float g3 = (3.0f * f0_hz < sr * 0.45f) ? goertzelPower(x, n, 3.0f * f0_hz) : 0.0f;
  const float eps = 1e-6f;
  return g1 * (eps + g2) * (eps + g3);
}

bool AudioAnalyzePitchYin::isLocalMin(const float* d, int tau, int tau_max) const {
  if (tau <= 0 || tau >= tau_max) return false;
  return d[tau] <= d[tau - 1] && d[tau] <= d[tau + 1];
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

  // Remember first-min (pre-continuity) so the referee can still recover.
  const int first_tau = chosen_tau;

  // Soft continuity: only prefer previous octave if it still has *better*
  // harmonic support. Blind continuity freezes a wrong D3 after one glitch.
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
          float s_new = harmonicScore(x, kWindow, f_new);
          float s_old = harmonicScore(x, kWindow, last_freq_);
          if (s_old > s_new * 1.15f) {
            chosen_tau = cont_tau;
            best_cmnd = cont_v;
          }
        }
      }
    }
  }

  // Octave / harmonic referee (v6): score {first-min, current, k·τ for k=½,2,3}
  // with Goertzel harmonic energy.
  //   2τ  — partial lock (G3→G4)
  //   τ/2 — subharmonic lock (D4→D3)
  //   3τ  — low-string 3rd-harmonic lock (C3→G4: 3·τ_G4 ≈ τ_C3)
  {
    int cands[10];
    int nc = 0;
    auto add_cand = [&](int t) {
      if (t <= tau_min || t >= tau_max) return;
      for (int i = 0; i < nc; i++) if (cands[i] == t) return;
      cands[nc++] = t;
    };
    add_cand(chosen_tau);
    add_cand(first_tau);

    // Half / double / triple of both current and first-min
    add_cand(chosen_tau / 2);
    add_cand(chosen_tau * 2);
    add_cand(chosen_tau * 3);
    add_cand(first_tau / 2);
    add_cand(first_tau * 2);
    add_cand(first_tau * 3);

    // Keep only trough-like candidates (local min or near-min)
    int viable[10];
    int nv = 0;
    float best_c = 1.0f;
    for (int i = 0; i < nc; i++) {
      int t = cands[i];
      float dv = d[t];
      // allow ±1 neighborhood min for shallow acoustic troughs
      if (t - 1 > tau_min && d[t - 1] < dv) dv = d[t - 1];
      if (t + 1 < tau_max && d[t + 1] < dv) dv = d[t + 1];
      bool trough = isLocalMin(d, t, tau_max) || dv < 0.16f;
      if (!trough || dv > 0.22f) continue;
      viable[nv++] = t;
      if (dv < best_c) best_c = dv;
    }

    if (nv >= 1) {
      int best_tau = chosen_tau;
      float best_score = -1.0f;
      for (int i = 0; i < nv; i++) {
        int t = viable[i];
        if (d[t] > best_c + 0.08f) continue;
        float f_c = sr / (float)t;
        if (f_c < fmin_hz_ * 0.95f || f_c > fmax_hz_ * 1.05f) continue;
        // Weight by inverse CMND so a deep 2τ trough (true G3) beats a shallow
        // first-min at the 2nd partial (G4), even when g(G4) energy is large.
        float harm = harmonicScore(x, kWindow, f_c);
        float sc = harm / (d[t] + 0.025f);
        bool better = (best_score < 0.0f) ||
                      (sc > best_score * 1.08f) ||
                      (sc > best_score * 0.92f && d[t] < d[best_tau] - 0.02f);
        // Prefer longer period (lower pitch) when its trough is clearly deeper:
        // classic bowed partial lock (first-min = 2f0).
        if (!better && best_score > 0.0f && t > best_tau &&
            d[t] + 0.04f < d[best_tau] && d[t] < 0.10f) {
          better = true;
        }
        // Octave-up only when longer candidate is a weak/double-period trough.
        if (!better && best_score > 0.0f && t < best_tau &&
            sc > best_score * 0.90f && d[t] < 0.08f && d[best_tau] > 0.06f) {
          better = true;
        }
        if (better) {
          best_score = sc;
          best_tau = t;
        }
      }
      chosen_tau = best_tau;
      best_cmnd = d[chosen_tau];
    }
  }

  // Final octave-up rescue (subharmonic lock only): half-period must have
  // clearly better harmonic *product* score, not merely a strong 2nd partial.
  // (A strong 2nd partial alone would wrongly flip true G3 → G4.)
  {
    int th = chosen_tau / 2;
    if (th > tau_min + 1 && d[th] < 0.12f && d[chosen_tau] > 0.03f) {
      float f_lo = sr / (float)chosen_tau;
      float f_hi = sr / (float)th;
      float s_lo = harmonicScore(x, kWindow, f_lo);
      float s_hi = harmonicScore(x, kWindow, f_hi);
      if (s_hi > s_lo * 1.35f && d[th] <= d[chosen_tau] + 0.02f) {
        chosen_tau = th;
        best_cmnd = d[th];
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
