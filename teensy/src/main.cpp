#include <Arduino.h>
#include <Audio.h>

AudioSynthWaveformSine sine1;
AudioAnalyzeFFT1024 fft1024;
AudioConnection patchCord1(sine1, fft1024);

const char* noteToName(int midi);

void setup() {
  Serial.begin(115200);
  delay(1500);
  AudioMemory(40);
  
  Serial.println("=== Intune Teensy 4.1 - Overlapping FFT Test ===");
  
  sine1.amplitude(0.9);
  sine1.frequency(440.0);
}

void loop() {
  static uint32_t lastPrint = 0;
  static float currentFreq = 440.0;
  static uint32_t noteChangeTime = 0;

  // Change note every 1 second for easy testing
  if (millis() - noteChangeTime > 1000) {
    noteChangeTime = millis();
    static int scaleIndex = 0;
    const float scale[8] = {261.63, 293.66, 329.63, 349.23, 392.00, 440.00, 493.88, 523.25}; // C4 to C5
    currentFreq = scale[scaleIndex];
    sine1.frequency(currentFreq);
    scaleIndex = (scaleIndex + 1) % 8;
    Serial.printf("--- Changing to %s ---\n", noteToName(round(12*log2(currentFreq/440.0)+69)));
  }

  if (millis() - lastPrint > 20) {        // Faster updates ~50 Hz
    lastPrint = millis();

    if (fft1024.available()) {
      float maxMag = 0;
      int maxBin = 0;
      
      for (int i = 4; i < 250; i++) {
        float mag = fft1024.read(i);
        if (mag > maxMag) {
          maxMag = mag;
          maxBin = i;
        }
      }

      if (maxMag > 0.07) {
        float binFreq = maxBin * (AUDIO_SAMPLE_RATE_EXACT / 1024.0);
        
        float magL = fft1024.read(maxBin-1);
        float magR = fft1024.read(maxBin+1);
        float delta = (magR - magL) / (2.0f * (2.0f*maxMag - magL - magR));
        float freq = binFreq + delta * (AUDIO_SAMPLE_RATE_EXACT / 1024.0);

        float midiFloat = 12.0 * log2(freq / 440.0) + 69.0;
        int midiNote = round(midiFloat);
        float cents = (midiFloat - midiNote) * 100.0;

        Serial.printf("%lu,%s,%+.1f,%.3f\n", millis(), noteToName(midiNote), cents, maxMag);
      }
    }
  }
}

const char* noteToName(int midi) {
  static const char* names[12] = {"C","C#","D","D#","E","F","F#","G","G#","A","A#","B"};
  static char buf[8];
  int octave = (midi / 12) - 1;
  snprintf(buf, sizeof(buf), "%s%d", names[midi % 12], octave);
  return buf;
}