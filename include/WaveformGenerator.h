#ifndef WAVEFORM_GENERATOR_H
#define WAVEFORM_GENERATOR_H

#include <Arduino.h>
#include "ShdlcSensorInterface.h"
#include "ConfigStorage.h"

class WaveformGenerator {
public:
  enum class WaveformType : uint8_t {
    SINE = 0,
    CAPNOGRAM = 1
  };

private:
  float amplitude;
  float frequency;
  float baseline;
  ShdlcSensorInterface* cocoSensor;
  bool useCocoSensor;
  WaveformType waveformType;

  float generateCapnogramSample(float breathPhase);

public:
  WaveformGenerator();

  void setCocoSensor(ShdlcSensorInterface* sensor);
  void setUseCocoSensor(bool use);
  bool isUsingCocoSensor() const;

  void setWaveformType(WaveformType type);
  WaveformType getWaveformType() const;

  void setAmplitude(float amp);
  void setFrequency(float freq);
  void setBaseline(float base);

  float getAmplitude() const;
  float getFrequency() const;
  float getBaseline() const;

  float getSample();
  uint16_t getRespiratoryRate() const;
  uint16_t getETCO2() const;

  void loadFromConfig(const ConfigStorage::Config& cfg);
};

#endif // WAVEFORM_GENERATOR_H
