#include "WaveformGenerator.h"

WaveformGenerator::WaveformGenerator()
  : amplitude(38.0), frequency(0.25), baseline(0.0),
    cocoSensor(nullptr), useCocoSensor(false), waveformType(WaveformType::SINE) {}

void WaveformGenerator::setCocoSensor(ShdlcSensorInterface* sensor) {
  cocoSensor = sensor;
}

void WaveformGenerator::setUseCocoSensor(bool use) {
  useCocoSensor = use && cocoSensor && cocoSensor->isAvailable();
  if (useCocoSensor && !cocoSensor->isMeasurementRunning()) {
    cocoSensor->startMeasuring();
  }
}

bool WaveformGenerator::isUsingCocoSensor() const {
  return useCocoSensor;
}

void WaveformGenerator::setWaveformType(WaveformType type) { waveformType = type; }
WaveformGenerator::WaveformType WaveformGenerator::getWaveformType() const { return waveformType; }

void WaveformGenerator::setAmplitude(float amp) { amplitude = amp; }
void WaveformGenerator::setFrequency(float freq) { frequency = freq; }
void WaveformGenerator::setBaseline(float base) { baseline = base; }

float WaveformGenerator::getAmplitude() const { return amplitude; }
float WaveformGenerator::getFrequency() const { return frequency; }
float WaveformGenerator::getBaseline() const { return baseline; }

float WaveformGenerator::generateCapnogramSample(float breathPhase) {
  float etco2 = amplitude;
  float base = baseline;

  if (breathPhase < 0.08f) {
    // Inspiratory baseline - no CO2
    return base;
  } else if (breathPhase < 0.18f) {
    // Expiratory upstroke - rapid rise (smoothstep)
    float t = (breathPhase - 0.08f) / 0.10f;
    float smooth = t * t * (3.0f - 2.0f * t);
    return base + smooth * etco2;
  } else if (breathPhase < 0.55f) {
    // Alveolar plateau with slight upslope
    float t = (breathPhase - 0.18f) / 0.37f;
    return base + etco2 * (1.0f + 0.05f * t);
  } else if (breathPhase < 0.60f) {
    // Inspiratory downstroke - sharp drop (smoothstep)
    float t = (breathPhase - 0.55f) / 0.05f;
    float smooth = t * t * (3.0f - 2.0f * t);
    return base + etco2 * 1.05f * (1.0f - smooth);
  } else {
    // Inspiratory baseline
    return base;
  }
}

float WaveformGenerator::getSample() {
  if (useCocoSensor && cocoSensor) {
    float sensorValue;
    if (cocoSensor->getSample(sensorValue)) {
      return max(0.0f, sensorValue);
    }
  }

  float time = millis() / 1000.0;

  if (waveformType == WaveformType::CAPNOGRAM) {
    float period = 1.0f / frequency;
    float breathPhase = fmod(time, period) / period;
    return max(0.0f, generateCapnogramSample(breathPhase));
  }

  // Default: sine wave
  float value = baseline + amplitude * sin(2.0 * PI * frequency * time);
  return max(0.0f, value);
}

uint16_t WaveformGenerator::getRespiratoryRate() const {
  return (uint16_t)(frequency * 60.0);
}

uint16_t WaveformGenerator::getETCO2() const {
  return (uint16_t)(amplitude * 10.0);
}

void WaveformGenerator::loadFromConfig(const ConfigStorage::Config& cfg) {
  amplitude = cfg.amplitude;
  frequency = cfg.frequency;
  baseline = cfg.baseline;
  useCocoSensor = cfg.useCocoSensor;
  waveformType = static_cast<WaveformType>(cfg.waveformType);
}
