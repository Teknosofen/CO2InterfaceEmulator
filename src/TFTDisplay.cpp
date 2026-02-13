#include "TFTDisplay.h"

TFTDisplay::TFTDisplay(WaveformGenerator& wave, AlarmManager& alarm, DeviceState& dev)
  : waveform(wave), alarms(alarm), device(dev), writeX(0), lastUpdate(0),
    prevContinuousMode(false), prevCO2(-1), prevRate(0xFFFF), prevAlarm(false),
    statusDrawn(false) {
  for (int i = 0; i < WAVE_WIDTH; i++) {
    waveY[i] = WAVE_TOP + WAVE_HEIGHT; // bottom (0 mmHg)
    prevWaveY[i] = WAVE_TOP + WAVE_HEIGHT;
  }
}

void TFTDisplay::begin() {
  tft.init();
  tft.setRotation(0);  // Portrait mode
  tft.fillScreen(TFT_BLACK);

  // Set backlight (GPIO 38)
  pinMode(38, OUTPUT);
  digitalWrite(38, HIGH);

  drawGrid();
}

int16_t TFTDisplay::co2ToY(float co2) {
  // Map 0..100 mmHg to pixel range WAVE_TOP+WAVE_HEIGHT..WAVE_TOP
  int16_t y = WAVE_TOP + WAVE_HEIGHT - (int16_t)(co2 / 100.0f * WAVE_HEIGHT);
  return constrain(y, WAVE_TOP, WAVE_TOP + WAVE_HEIGHT);
}

void TFTDisplay::drawGrid() {
  // Horizontal grid lines at 25, 50, 75 mmHg
  int16_t gridColor = tft.color565(40, 40, 40);
  for (int mmHg = 25; mmHg < 100; mmHg += 25) {
    int16_t y = co2ToY(mmHg);
    tft.drawFastHLine(0, y, WAVE_WIDTH, gridColor);
  }
  // Scale labels
  tft.setTextSize(1);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.setCursor(2, WAVE_TOP + 3);
  tft.print("100");
  tft.setCursor(2, WAVE_TOP + WAVE_HEIGHT - 10);
  tft.print("0");
}

void TFTDisplay::drawStatusBar() {
  bool continuous = device.isContinuousMode();

  // Only redraw if state changed or first draw
  if (statusDrawn && continuous == prevContinuousMode) return;

  tft.fillRect(0, 0, 170, WAVE_TOP, TFT_NAVY);
  tft.setTextColor(TFT_WHITE, TFT_NAVY);
  tft.setTextSize(2);
  tft.setCursor(10, 10);
  tft.print("CO2 EMU");

  tft.setTextSize(1);
  tft.setCursor(120, 15);
  if (continuous) {
    tft.setTextColor(TFT_GREEN, TFT_NAVY);
    tft.print("RUN ");
  } else {
    tft.setTextColor(TFT_YELLOW, TFT_NAVY);
    tft.print("IDLE");
  }

  prevContinuousMode = continuous;
  statusDrawn = true;
}

void TFTDisplay::drawParameterArea() {
  float co2 = waveform.getSample();
  uint16_t rate = waveform.getRespiratoryRate();
  uint8_t status = 0;
  bool alarm = alarms.checkAlarms(co2, status);

  // Round to 1 decimal to avoid redrawing on tiny float changes
  float co2Rounded = ((int)(co2 * 10.0f)) / 10.0f;

  bool co2Changed = (co2Rounded != prevCO2);
  bool rateChanged = (rate != prevRate);
  bool alarmChanged = (alarm != prevAlarm);

  // CO2 value — only redraw if changed
  if (co2Changed || alarmChanged) {
    tft.setTextSize(3);
    if (alarm) {
      tft.setTextColor(TFT_RED, TFT_BLACK);
    } else {
      tft.setTextColor(TFT_GREEN, TFT_BLACK);
    }
    tft.setCursor(10, 265);
    // Fixed-width format to overwrite previous digits with background color
    tft.printf("%-6.1f", co2Rounded);

    // "mmHg" label (only needs drawing once, but it's cheap)
    tft.setTextSize(1);
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.setCursor(100, 275);
    tft.print("mmHg");

    prevCO2 = co2Rounded;
  }

  // Respiratory rate — only redraw if changed
  if (rateChanged) {
    tft.setTextSize(2);
    tft.setTextColor(TFT_CYAN, TFT_BLACK);
    tft.setCursor(10, 295);
    // Fixed-width format to overwrite old text
    tft.printf("%-4d bpm", rate);

    prevRate = rate;
  }

  // Alarm indicator — only redraw if changed
  if (alarmChanged) {
    if (alarm) {
      tft.fillCircle(155, 275, 8, TFT_RED);
    } else {
      tft.fillCircle(155, 275, 8, TFT_BLACK);
    }
    prevAlarm = alarm;
  }
}

void TFTDisplay::drawWaveformStep() {
  float co2 = waveform.getSample();
  int16_t newY = co2ToY(co2);

  // The column we're about to overwrite
  uint8_t x = writeX;
  uint8_t prevX = (x == 0) ? WAVE_WIDTH - 1 : x - 1;

  // Erase the old line segment AT this column (old data being scrolled out)
  // We erase the segment from prevWaveY[prevX] to prevWaveY[x]
  if (prevWaveY[x] != prevWaveY[prevX]) {
    tft.drawLine(prevX, prevWaveY[prevX], x, prevWaveY[x], TFT_BLACK);
  } else {
    tft.drawPixel(x, prevWaveY[x], TFT_BLACK);
  }

  // Also erase the segment going FORWARD from this column (the next old segment)
  uint8_t nextX = (x + 1) % WAVE_WIDTH;
  if (prevWaveY[nextX] != prevWaveY[x]) {
    tft.drawLine(x, prevWaveY[x], nextX, prevWaveY[nextX], TFT_BLACK);
  }

  // Repair grid lines that may have been erased
  int16_t gridColor = tft.color565(40, 40, 40);
  for (int mmHg = 25; mmHg < 100; mmHg += 25) {
    int16_t gy = co2ToY(mmHg);
    // Redraw grid pixels in the columns we touched
    tft.drawPixel(x, gy, gridColor);
    if (x > 0) tft.drawPixel(prevX, gy, gridColor);
    tft.drawPixel(nextX, gy, gridColor);
  }

  // Store the new Y value
  waveY[x] = newY;

  // Draw the new line segment from previous column to this column
  int16_t fromY = waveY[prevX];
  tft.drawLine(prevX, fromY, x, newY, TFT_CYAN);

  // Draw a cursor/gap marker: erase a small column ahead so trace appears to scroll
  uint8_t gapX = (x + 2) % WAVE_WIDTH;
  tft.drawFastVLine(gapX, WAVE_TOP + 1, WAVE_HEIGHT - 1, TFT_BLACK);
  // Repair grid at gap column
  for (int mmHg = 25; mmHg < 100; mmHg += 25) {
    tft.drawPixel(gapX, co2ToY(mmHg), gridColor);
  }

  // Shift previous buffer: current becomes previous for next erase cycle
  prevWaveY[x] = newY;

  writeX = (x + 1) % WAVE_WIDTH;
}

void TFTDisplay::update() {
  if (millis() - lastUpdate < 100) return;  // 10Hz
  lastUpdate = millis();

  drawStatusBar();
  drawWaveformStep();
  drawParameterArea();
}

void TFTDisplay::clear() {
  tft.fillScreen(TFT_BLACK);
  statusDrawn = false;
  prevCO2 = -1;
  prevRate = 0xFFFF;
  prevAlarm = false;
}

void TFTDisplay::showMessage(const char* msg) {
  tft.fillRect(0, 100, 170, 60, TFT_NAVY);
  tft.setTextColor(TFT_WHITE, TFT_NAVY);
  tft.setTextSize(2);

  int16_t x = (170 - strlen(msg) * 12) / 2;
  tft.setCursor(x, 120);
  tft.print(msg);
}
