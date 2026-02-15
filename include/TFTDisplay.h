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
  static const int16_t PARAM_PAD = 9;       // horizontal content padding inside panel

  // Parameter panel vertical layout (offsets from WAVE_TOP)
  static const int16_t CO2_LABEL_Y = 4;     // "CO2" header
  static const int16_t CO2_VALUE_Y = 24;    // large CO2 number
  static const int16_t CO2_VALUE_H = 40;    // clear-rect height for CO2 value
  static const int16_t CO2_UNIT_Y  = 60;    // "mmHg" unit text

  static const int16_t RR_LABEL_Y  = 80;    // "RR" header
  static const int16_t RR_VALUE_Y  = 100;   // respiratory rate number
  static const int16_t RR_VALUE_H  = 28;    // clear-rect height for RR value
  static const int16_t RR_UNIT_Y   = 130;   // "bpm" unit text

  // Status bar layout
  static const int16_t BADGE_AREA_X   = 200; // left edge of badge clear region
  static const int16_t BADGE_MARGIN   = 8;   // right-edge margin for rightmost badge
  static const int16_t BADGE_USB_OFS  = 50;  // USB badge offset from right edge

  // Misc
  static const int16_t SCALE_INSET = 3;     // scale label inset from waveform edge
  static const int16_t TITLE_MARGIN = 8;    // title left margin in status bar
  static const uint8_t TFT_BL_PIN = 38;     // backlight GPIO

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
