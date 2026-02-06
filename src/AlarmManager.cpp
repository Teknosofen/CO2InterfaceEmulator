#include "AlarmManager.h"

AlarmManager::AlarmManager() 
  : highThreshold(50.0), lowThreshold(30.0), 
    highEnabled(false), lowEnabled(false) {}

void AlarmManager::setHighThreshold(float value) { highThreshold = value; }
void AlarmManager::setLowThreshold(float value) { lowThreshold = value; }
void AlarmManager::enableHigh(bool enable) { highEnabled = enable; }
void AlarmManager::enableLow(bool enable) { lowEnabled = enable; }

float AlarmManager::getHighThreshold() const { return highThreshold; }
float AlarmManager::getLowThreshold() const { return lowThreshold; }
bool AlarmManager::isHighEnabled() const { return highEnabled; }
bool AlarmManager::isLowEnabled() const { return lowEnabled; }

bool AlarmManager::checkAlarms(float value, uint8_t& statusByte) const {
  bool alarm = false;
  
  if (highEnabled && value > highThreshold) {
    statusByte |= 0x08;
    alarm = true;
  }
  
  if (lowEnabled && value < lowThreshold) {
    statusByte |= 0x08;
    alarm = true;
  }
  
  return alarm;
}

void AlarmManager::loadFromConfig(const ConfigStorage::Config& cfg) {
  highThreshold = cfg.alarmHigh;
  lowThreshold = cfg.alarmLow;
  highEnabled = cfg.alarmHighEnabled;
  lowEnabled = cfg.alarmLowEnabled;
}
