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

  // Waveform scrolling buffer — stores Y pixel position for each X column
  static const int WAVE_WIDTH = 170;
  static const int WAVE_TOP = 35;
  static const int WAVE_HEIGHT = 225;
  int16_t waveY[WAVE_WIDTH];      // current Y positions (pixel coords)
  int16_t prevWaveY[WAVE_WIDTH];  // previous Y positions for erasing
  uint8_t writeX;                 // next X column to write

  // Previous display state for dirty-checking
  bool prevContinuousMode;
  float prevCO2;
  uint16_t prevRate;
  bool prevAlarm;
  bool statusDrawn;

  uint32_t lastUpdate;

  int16_t co2ToY(float co2);
  void drawStatusBar();
  void drawParameterArea();
  void drawWaveformStep();
  void drawGrid();

public:
  TFTDisplay(WaveformGenerator& wave, AlarmManager& alarm, DeviceState& dev);

  void begin();
  void update();
  void clear();
  void showMessage(const char* msg);
};

#endif // TFT_DISPLAY_H
