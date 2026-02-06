#include "WaveformGenerator.h"

WaveformGenerator::WaveformGenerator() 
  : amplitude(38.0), frequency(0.25), baseline(0.0), phase(0.0),
    i2cSensor(nullptr), useI2CSensor(false) {}

void WaveformGenerator::setI2CSensor(I2CSensorInterface* sensor) { 
  i2cSensor = sensor; 
}

void WaveformGenerator::setUseI2CSensor(bool use) { 
  useI2CSensor = use && i2cSensor && i2cSensor->isAvailable(); 
}

bool WaveformGenerator::isUsingI2CSensor() const { 
  return useI2CSensor; 
}

void WaveformGenerator::setAmplitude(float amp) { amplitude = amp; }
void WaveformGenerator::setFrequency(float freq) { frequency = freq; }
void WaveformGenerator::setBaseline(float base) { baseline = base; }
void WaveformGenerator::setPhase(float phaseRadians) { phase = phaseRadians; }

float WaveformGenerator::getAmplitude() const { return amplitude; }
float WaveformGenerator::getFrequency() const { return frequency; }
float WaveformGenerator::getBaseline() const { return baseline; }
float WaveformGenerator::getPhase() const { return phase; }

float WaveformGenerator::getSample() {
  if (useI2CSensor && i2cSensor) {
    float sensorValue;
    if (i2cSensor->getSample(sensorValue)) {
      return max(0.0f, sensorValue);
    }
  }
  
  float time = millis() / 1000.0;
  float value = baseline + amplitude * sin(2.0 * PI * frequency * time + phase);
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
  phase = cfg.phase;
  useI2CSensor = cfg.useI2CSensor;
}
