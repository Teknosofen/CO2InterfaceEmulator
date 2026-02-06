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
    float phase;
    float alarmHigh;
    float alarmLow;
    bool alarmHighEnabled;
    bool alarmLowEnabled;
    bool useI2CSensor;
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
