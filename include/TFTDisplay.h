#ifndef TFT_DISPLAY_H
#define TFT_DISPLAY_H

#include <Arduino.h>
#include <TFT_eSPI.h>
#include "WaveformGenerator.h"
#include "AlarmManager.h"
#include "DeviceState.h"

class TFTDisplay {
private:
  TFT_eSPI tft;
  WaveformGenerator& waveform;
  AlarmManager& alarms;
  DeviceState& device;
  
  float waveformData[170];  // Screen width
  uint8_t dataIndex;
  uint32_t lastUpdate;
  
  void drawWaveform();
  void drawStatus();
  void drawParameters();
  
public:
  TFTDisplay(WaveformGenerator& wave, AlarmManager& alarm, DeviceState& dev);
  
  void begin();
  void update();
  void clear();
  void showMessage(const char* msg);
};

#endif // TFT_DISPLAY_H
