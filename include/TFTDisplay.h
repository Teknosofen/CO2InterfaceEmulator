#ifndef TFT_DISPLAY_H
#define TFT_DISPLAY_H

#include <Arduino.h>
#include <TFT_eSPI.h>
#include "WaveformGenerator.h"
#include "DeviceState.h"

// Custom color palette
#define CLR_BACKGROUND       0x85BA
#define CLR_LOGOBLUE         0x5497
#define CLR_DARKERBLUE       0x3A97
#define CLR_DEEPBLUE         0x1A6F
#define CLR_SLATEBLUE        0x2B4F
#define CLR_MIDNIGHTBLUE     0x1028
#define CLR_REDDISH          0xA4B2
#define CLR_GREENISH         0x2444

class TFTDisplay {
private:
  TFT_eSPI tft;
  WaveformGenerator& waveform;
  DeviceState& device;

  // Landscape layout: 320 x 170
  // Status bar: full width, top 26px
  // Waveform:  x=0..229, y=26..169 (230 x 144)
  // Params:    x=232..319, y=26..169 (88 x 144)
  static const int16_t SCREEN_W = 320;
  static const int16_t SCREEN_H = 170;

  static const int16_t STATUS_H = 26;

  static const int16_t WAVE_LEFT = 0;
  static const int16_t WAVE_TOP = STATUS_H;
  static const int16_t WAVE_WIDTH = 230;
  static const int16_t WAVE_HEIGHT = SCREEN_H - STATUS_H; // 144

  static const int16_t PARAM_LEFT = 232;
  static const int16_t PARAM_WIDTH = SCREEN_W - PARAM_LEFT; // 88

  // Waveform circular buffer — Y pixel position per X column
  int16_t waveY[230];
  uint16_t writeX;

  // Previous state for dirty-checking
  bool prevContinuousMode;
  bool prevUsbProtocol;
  float prevCO2;
  uint16_t prevRate;
  bool statusDrawn;
  bool paramsDrawn;

  uint32_t lastUpdate;

  int16_t co2ToY(float co2);
  void drawStatusBar();
  void drawParamPanel();
  void drawWaveformStep();
  void drawStaticFrame();

public:
  TFTDisplay(WaveformGenerator& wave, DeviceState& dev);

  void begin();
  void update();
  void clear();
  void showMessage(const char* msg);
};

#endif // TFT_DISPLAY_H
