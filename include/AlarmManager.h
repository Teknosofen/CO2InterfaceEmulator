#ifndef ALARM_MANAGER_H
#define ALARM_MANAGER_H

#include <Arduino.h>
#include "ConfigStorage.h"

class AlarmManager {
private:
  float highThreshold;
  float lowThreshold;
  bool highEnabled;
  bool lowEnabled;
  
public:
  AlarmManager();
  
  void setHighThreshold(float value);
  void setLowThreshold(float value);
  void enableHigh(bool enable);
  void enableLow(bool enable);
  
  float getHighThreshold() const;
  float getLowThreshold() const;
  bool isHighEnabled() const;
  bool isLowEnabled() const;
  
  bool checkAlarms(float value, uint8_t& statusByte) const;
  void loadFromConfig(const ConfigStorage::Config& cfg);
};

#endif // ALARM_MANAGER_H
