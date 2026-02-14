#ifndef CONFIG_STORAGE_H
#define CONFIG_STORAGE_H

#include <Arduino.h>
#include <Preferences.h>

class ConfigStorage {
public:
  struct Config {
    float amplitude;
    float frequency;
    float baseline;
    bool useCocoSensor;
    uint8_t waveformType;  // 0 = SINE, 1 = CAPNOGRAM
  };
  
private:
  Preferences prefs;
  
public:
  bool begin();
  void saveConfig(const Config& cfg);
  Config loadConfig();
  void clearConfig();
};

#endif // CONFIG_STORAGE_H
