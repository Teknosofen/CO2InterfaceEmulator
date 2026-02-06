#ifndef WAVEFORM_GENERATOR_H
#define WAVEFORM_GENERATOR_H

#include <Arduino.h>
#include "I2CSensorInterface.h"
#include "ConfigStorage.h"

class WaveformGenerator {
private:
  float amplitude;
  float frequency;
  float baseline;
  float phase;
  I2CSensorInterface* i2cSensor;
  bool useI2CSensor;
  
public:
  WaveformGenerator();
  
  void setI2CSensor(I2CSensorInterface* sensor);
  void setUseI2CSensor(bool use);
  bool isUsingI2CSensor() const;
  
  void setAmplitude(float amp);
  void setFrequency(float freq);
  void setBaseline(float base);
  void setPhase(float phaseRadians);
  
  float getAmplitude() const;
  float getFrequency() const;
  float getBaseline() const;
  float getPhase() const;
  
  float getSample();
  uint16_t getRespiratoryRate() const;
  uint16_t getETCO2() const;
  
  void loadFromConfig(const ConfigStorage::Config& cfg);
};

#endif // WAVEFORM_GENERATOR_H
