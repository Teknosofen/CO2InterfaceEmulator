#include "ConfigStorage.h"
#include "Config.h"

bool ConfigStorage::begin() {
  return prefs.begin("co2-emulator", false);
}

void ConfigStorage::saveConfig(const Config& cfg) {
  prefs.putFloat("amplitude", cfg.amplitude);
  prefs.putFloat("frequency", cfg.frequency);
  prefs.putFloat("baseline", cfg.baseline);
  prefs.putFloat("phase", cfg.phase);
  prefs.putFloat("alarmHigh", cfg.alarmHigh);
  prefs.putFloat("alarmLow", cfg.alarmLow);
  prefs.putBool("alarmHighEn", cfg.alarmHighEnabled);
  prefs.putBool("alarmLowEn", cfg.alarmLowEnabled);
  prefs.putBool("useI2C", cfg.useI2CSensor);
  
  CMD_SERIAL.println("Configuration saved to EEPROM");
}

ConfigStorage::Config ConfigStorage::loadConfig() {
  Config cfg;
  cfg.amplitude = prefs.getFloat("amplitude", 38.0);
  cfg.frequency = prefs.getFloat("frequency", 0.25);
  cfg.baseline = prefs.getFloat("baseline", 0.0);
  cfg.phase = prefs.getFloat("phase", 0.0);
  cfg.alarmHigh = prefs.getFloat("alarmHigh", 50.0);
  cfg.alarmLow = prefs.getFloat("alarmLow", 30.0);
  cfg.alarmHighEnabled = prefs.getBool("alarmHighEn", false);
  cfg.alarmLowEnabled = prefs.getBool("alarmLowEn", false);
  cfg.useI2CSensor = prefs.getBool("useI2C", false);
  
  CMD_SERIAL.println("Configuration loaded from EEPROM");
  return cfg;
}

void ConfigStorage::clearConfig() {
  prefs.clear();
  CMD_SERIAL.println("Configuration cleared");
}
