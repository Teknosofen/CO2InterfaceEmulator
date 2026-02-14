#include "ConfigStorage.h"
#include "Config.h"

bool ConfigStorage::begin() {
  return prefs.begin("co2-emulator", false);
}

void ConfigStorage::saveConfig(const Config& cfg) {
  prefs.putFloat("amplitude", cfg.amplitude);
  prefs.putFloat("frequency", cfg.frequency);
  prefs.putFloat("baseline", cfg.baseline);
  prefs.putBool("useCoco", cfg.useCocoSensor);
  prefs.putUChar("waveType", cfg.waveformType);

  CMD_SERIAL.println("Configuration saved to EEPROM");
}

ConfigStorage::Config ConfigStorage::loadConfig() {
  Config cfg;
  cfg.amplitude = prefs.getFloat("amplitude", 38.0);
  cfg.frequency = prefs.getFloat("frequency", 0.25);
  cfg.baseline = prefs.getFloat("baseline", 0.0);
  cfg.useCocoSensor = prefs.getBool("useCoco", false);
  cfg.waveformType = prefs.getUChar("waveType", 0);

  CMD_SERIAL.println("Configuration loaded from EEPROM");
  return cfg;
}

void ConfigStorage::clearConfig() {
  prefs.clear();
  CMD_SERIAL.println("Configuration cleared");
}
