#include "TFTDisplay.h"

TFTDisplay::TFTDisplay(WaveformGenerator& wave, AlarmManager& alarm, DeviceState& dev)
  : waveform(wave), alarms(alarm), device(dev), dataIndex(0), lastUpdate(0) {
  for (int i = 0; i < 170; i++) waveformData[i] = 0;
}

void TFTDisplay::begin() {
  tft.init();
  tft.setRotation(0);  // Portrait mode
  tft.fillScreen(TFT_BLACK);
  
  // Set backlight (GPIO 38)
  pinMode(38, OUTPUT);
  digitalWrite(38, HIGH);
  
  // Draw initial UI
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(2);
  tft.setCursor(20, 10);
  tft.println("CO2 Emulator");
  
  tft.setTextSize(1);
  tft.setCursor(10, 40);
  tft.println("Initializing...");
}

void TFTDisplay::update() {
  if (millis() - lastUpdate < 100) return;  // Update at 10Hz
  lastUpdate = millis();
  
  // Get current CO2 value
  float co2 = waveform.getSample();
  
  // Add to waveform buffer
  waveformData[dataIndex] = co2;
  dataIndex = (dataIndex + 1) % 170;
  
  // Draw everything
  drawStatus();
  drawParameters();
  drawWaveform();
}

void TFTDisplay::drawStatus() {
  // Status bar at top
  tft.fillRect(0, 0, 170, 35, TFT_NAVY);
  tft.setTextColor(TFT_WHITE, TFT_NAVY);
  tft.setTextSize(2);
  tft.setCursor(10, 10);
  tft.print("CO2 EMU");
  
  // Mode indicator
  tft.setTextSize(1);
  tft.setCursor(120, 15);
  if (device.isContinuousMode()) {
    tft.setTextColor(TFT_GREEN, TFT_NAVY);
    tft.print("RUN");
  } else {
    tft.setTextColor(TFT_YELLOW, TFT_NAVY);
    tft.print("IDLE");
  }
}

void TFTDisplay::drawParameters() {
  // Parameters display area
  tft.fillRect(0, 260, 170, 60, TFT_BLACK);
  
  float co2 = waveform.getSample();
  uint16_t rate = waveform.getRespiratoryRate();
  
  // Check alarms
  uint8_t status = 0;
  bool alarm = alarms.checkAlarms(co2, status);
  
  // Draw CO2 value
  tft.setTextSize(3);
  if (alarm) {
    tft.setTextColor(TFT_RED, TFT_BLACK);
  } else {
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
  }
  tft.setCursor(10, 265);
  tft.printf("%.1f", co2);
  
  tft.setTextSize(1);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setCursor(100, 275);
  tft.print("mmHg");
  
  // Draw rate
  tft.setTextSize(2);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.setCursor(10, 295);
  tft.printf("%d bpm", rate);
  
  // Alarm indicator
  if (alarm) {
    tft.fillCircle(155, 275, 8, TFT_RED);
  }
}

void TFTDisplay::drawWaveform() {
  // Waveform display area (35 to 260)
  int waveformHeight = 225;
  int waveformTop = 35;
  
  tft.fillRect(0, waveformTop, 170, waveformHeight, TFT_BLACK);
  
  // Draw grid
  tft.drawLine(0, waveformTop + waveformHeight/2, 170, waveformTop + waveformHeight/2, TFT_DARKGREY);
  
  // Draw waveform
  float minVal = 0;
  float maxVal = 100;
  
  for (int i = 1; i < 170; i++) {
    int idx1 = (dataIndex + i - 1) % 170;
    int idx2 = (dataIndex + i) % 170;
    
    float val1 = waveformData[idx1];
    float val2 = waveformData[idx2];
    
    int y1 = waveformTop + waveformHeight - (int)((val1 - minVal) / (maxVal - minVal) * waveformHeight);
    int y2 = waveformTop + waveformHeight - (int)((val2 - minVal) / (maxVal - minVal) * waveformHeight);
    
    // Constrain to display area
    y1 = constrain(y1, waveformTop, waveformTop + waveformHeight);
    y2 = constrain(y2, waveformTop, waveformTop + waveformHeight);
    
    tft.drawLine(i-1, y1, i, y2, TFT_CYAN);
  }
  
  // Draw scale
  tft.setTextSize(1);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.setCursor(5, waveformTop + 5);
  tft.print("100");
  tft.setCursor(5, waveformTop + waveformHeight - 10);
  tft.print("0");
}

void TFTDisplay::clear() {
  tft.fillScreen(TFT_BLACK);
}

void TFTDisplay::showMessage(const char* msg) {
  tft.fillRect(0, 100, 170, 60, TFT_NAVY);
  tft.setTextColor(TFT_WHITE, TFT_NAVY);
  tft.setTextSize(2);
  
  // Center text
  int16_t x = (170 - strlen(msg) * 12) / 2;
  tft.setCursor(x, 120);
  tft.print(msg);
}
