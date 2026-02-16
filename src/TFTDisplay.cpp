#include "TFTDisplay.h"

// GFX Free Font references
#define FONT_TITLE  &FreeSansBold9pt7b
#define FONT_LABEL  &FreeSans9pt7b
#define FONT_VALUE  &FreeSansBold12pt7b
#define FONT_BIG    &FreeSansBold18pt7b
#define FONT_SMALL  &FreeSans9pt7b

TFTDisplay::TFTDisplay(WaveformGenerator& wave, DeviceState& dev)
  : waveform(wave), device(dev), writeX(0), lastUpdate(0),
    prevContinuousMode(false), prevUsbProtocol(false),
    prevCO2(-1), prevRate(0xFFFF),
    statusDrawn(false), paramsDrawn(false) {
  for (int i = 0; i < WAVE_WIDTH; i++) {
    waveY[i] = WAVE_TOP + WAVE_HEIGHT - 1;
  }
}

void TFTDisplay::begin() {
  tft.init();
  tft.setRotation(1);  // Landscape: 320 x 170
  tft.fillScreen(CLR_BACKGROUND);

  pinMode(TFT_BL_PIN, OUTPUT);
  digitalWrite(TFT_BL_PIN, HIGH);

  drawStaticFrame();
}

int16_t TFTDisplay::co2ToY(float co2) {
  int16_t y = WAVE_TOP + WAVE_HEIGHT - 1 - (int16_t)(co2 / 50.0f * (WAVE_HEIGHT - 2));
  return constrain(y, WAVE_TOP + 1, WAVE_TOP + WAVE_HEIGHT - 1);
}

void TFTDisplay::drawStaticFrame() {
  // Status bar background
  tft.fillRect(0, 0, SCREEN_W, STATUS_H, CLR_DEEPBLUE);

  // Title
  tft.setFreeFont(FONT_TITLE);
  tft.setTextColor(CLR_BACKGROUND, CLR_DEEPBLUE);
  tft.setTextDatum(ML_DATUM);
  tft.drawString("CAPNO EMULATOR", TITLE_MARGIN, STATUS_H / 2);

  // Waveform area border
  tft.drawRect(WAVE_LEFT, WAVE_TOP, WAVE_WIDTH, WAVE_HEIGHT, CLR_DARKERBLUE);

  // Dotted grid lines inside waveform area
  for (int mmHg = 10; mmHg < 50; mmHg += 10) {
    int16_t y = co2ToY((float)mmHg);
    for (int16_t x = WAVE_LEFT + 1; x < WAVE_LEFT + WAVE_WIDTH - 1; x += 4) {
      tft.drawPixel(x, y, CLR_MIDNIGHTBLUE);
    }
  }

  // Scale labels on waveform (small built-in font)
  tft.setFreeFont(NULL);
  tft.setTextFont(1);
  tft.setTextColor(CLR_SLATEBLUE, CLR_BACKGROUND);
  tft.setTextDatum(TL_DATUM);
  tft.drawString("50", WAVE_LEFT + SCALE_INSET, WAVE_TOP + SCALE_INSET);
  tft.setTextDatum(BL_DATUM);
  tft.drawString("0", WAVE_LEFT + SCALE_INSET, WAVE_TOP + WAVE_HEIGHT - SCALE_INSET);

  // Vertical separator between waveform and parameters
  tft.drawFastVLine(PARAM_LEFT - 1, WAVE_TOP, WAVE_HEIGHT, CLR_DARKERBLUE);

  // Parameter panel static labels
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(CLR_SLATEBLUE, CLR_BACKGROUND);

  // Section headers in GFX font
  tft.setFreeFont(FONT_LABEL);
  tft.drawString("CO2", PARAM_LEFT + PARAM_PAD, WAVE_TOP + CO2_LABEL_Y);
  tft.drawString("RR", PARAM_LEFT + PARAM_PAD, WAVE_TOP + RR_LABEL_Y);

  // Unit labels in small built-in font
  tft.setFreeFont(NULL);
  tft.setTextFont(1);
  tft.drawString("mmHg", PARAM_LEFT + PARAM_PAD, WAVE_TOP + CO2_UNIT_Y);
  tft.drawString("bpm", PARAM_LEFT + PARAM_PAD, WAVE_TOP + RR_UNIT_Y);

  statusDrawn = false;
  paramsDrawn = false;
}

void TFTDisplay::drawStatusBar() {
  bool continuous = device.isContinuousMode();
  bool usbProto = device.isUsbProtocolMode();

  if (statusDrawn && continuous == prevContinuousMode && usbProto == prevUsbProtocol) return;

  // Clear badge area on the right side of the status bar
  tft.fillRect(BADGE_AREA_X, 2, SCREEN_W - BADGE_AREA_X - 2, STATUS_H - 4, CLR_DEEPBLUE);

  tft.setFreeFont(FONT_SMALL);
  tft.setTextDatum(MR_DATUM);

  // Streaming mode badge
  if (continuous) {
    tft.setTextColor(CLR_GREENISH, CLR_DEEPBLUE);
    tft.drawString("RUN", SCREEN_W - BADGE_MARGIN, STATUS_H / 2);
  } else {
    tft.setTextColor(CLR_REDDISH, CLR_DEEPBLUE);
    tft.drawString("IDLE", SCREEN_W - BADGE_MARGIN, STATUS_H / 2);
  }

  // USB mode badge
  if (usbProto) {
    tft.setTextColor(CLR_LOGOBLUE, CLR_DEEPBLUE);
    tft.drawString("PROTO", SCREEN_W - BADGE_USB_OFS, STATUS_H / 2);
  } else {
    tft.setTextColor(CLR_SLATEBLUE, CLR_DEEPBLUE);
    tft.drawString("DEBUG", SCREEN_W - BADGE_USB_OFS, STATUS_H / 2);
  }

  prevContinuousMode = continuous;
  prevUsbProtocol = usbProto;
  statusDrawn = true;
}

void TFTDisplay::drawParamPanel() {
  float co2 = waveform.getSample();
  uint16_t rate = waveform.getRespiratoryRate();

  float co2Rounded = ((int)(co2 * 10.0f)) / 10.0f;
  bool co2Changed = (co2Rounded != prevCO2);
  bool rateChanged = (rate != prevRate);

  if (!paramsDrawn) {
    co2Changed = rateChanged = true;
  }

  // CO2 value — large font, only update when changed
  if (co2Changed) {
    tft.fillRect(PARAM_LEFT + 2, WAVE_TOP + CO2_VALUE_Y - 4, PARAM_WIDTH - 4, CO2_VALUE_H, CLR_BACKGROUND);

    tft.setFreeFont(FONT_BIG);
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(CLR_GREENISH, CLR_BACKGROUND);

    char buf[8];
    dtostrf(co2Rounded, 4, 1, buf);
    tft.drawString(buf, PARAM_LEFT + PARAM_PAD, WAVE_TOP + CO2_VALUE_Y);

    prevCO2 = co2Rounded;
  }

  // Respiratory rate
  if (rateChanged) {
    tft.fillRect(PARAM_LEFT + 2, WAVE_TOP + RR_VALUE_Y - 4, PARAM_WIDTH - 4, RR_VALUE_H, CLR_BACKGROUND);

    tft.setFreeFont(FONT_VALUE);
    tft.setTextColor(CLR_LOGOBLUE, CLR_BACKGROUND);
    tft.setTextDatum(TL_DATUM);

    char buf[12];
    snprintf(buf, sizeof(buf), "%d", rate);
    tft.drawString(buf, PARAM_LEFT + PARAM_PAD, WAVE_TOP + RR_VALUE_Y);

    prevRate = rate;
  }

  paramsDrawn = true;
}

void TFTDisplay::drawWaveformStep() {
  float co2 = waveform.getSample();
  int16_t newY = co2ToY(co2);

  uint16_t x = writeX;
  uint16_t prevX = (x == 0) ? (WAVE_WIDTH - 3) : (x - 1);

  // Clear a sweep gap 4 columns ahead of the write position
  for (int g = 1; g <= 4; g++) {
    int16_t cx = WAVE_LEFT + 1 + ((x + g) % (WAVE_WIDTH - 2));
    tft.drawFastVLine(cx, WAVE_TOP + 1, WAVE_HEIGHT - 2, CLR_BACKGROUND);
  }

  // Repair dotted grid lines at the cleared columns
  for (int g = 1; g <= 4; g++) {
    int16_t cx = WAVE_LEFT + 1 + ((x + g) % (WAVE_WIDTH - 2));
    for (int mmHg = 10; mmHg < 50; mmHg += 10) {
      if (cx % 4 == 0) {
        tft.drawPixel(cx, co2ToY((float)mmHg), CLR_MIDNIGHTBLUE);
      }
    }
  }

  // Draw waveform line from previous point to this point (2px thick for visibility)
  int16_t nx = WAVE_LEFT + 1 + x;
  if (x == 0) {
    // Wrap point: no line from far right, just plot the new point
    tft.drawPixel(nx, newY, CLR_GREENISH);
    tft.drawPixel(nx, newY + 1, CLR_GREENISH);
  } else {
    int16_t px = WAVE_LEFT + 1 + prevX;
    int16_t py = waveY[prevX];
    tft.drawLine(px, py, nx, newY, CLR_GREENISH);
    tft.drawLine(px, py + 1, nx, newY + 1, CLR_GREENISH);
  }

  waveY[x] = newY;
  writeX = (x + 1) % (WAVE_WIDTH - 2);
}

void TFTDisplay::update() {
  if (millis() - lastUpdate < 100) return;  // 10Hz
  lastUpdate = millis();

  drawStatusBar();
  drawWaveformStep();
  drawParamPanel();
}

void TFTDisplay::clear() {
  tft.fillScreen(CLR_BACKGROUND);
  for (int i = 0; i < WAVE_WIDTH; i++) {
    waveY[i] = WAVE_TOP + WAVE_HEIGHT - 1;
  }
  writeX = 0;
  statusDrawn = false;
  paramsDrawn = false;
  prevCO2 = -1;
  prevRate = 0xFFFF;
  drawStaticFrame();
}

void TFTDisplay::showMessage(const char* msg) {
  int16_t msgW = 200, msgH = 50;
  int16_t msgX = (SCREEN_W - msgW) / 2;
  int16_t msgY = (SCREEN_H - msgH) / 2;
  tft.fillRect(msgX, msgY, msgW, msgH, CLR_DEEPBLUE);
  tft.setFreeFont(FONT_VALUE);
  tft.setTextColor(CLR_BACKGROUND, CLR_DEEPBLUE);
  tft.setTextDatum(MC_DATUM);
  tft.drawString(msg, SCREEN_W / 2, msgY + msgH / 2);
}
