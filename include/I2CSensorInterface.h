#ifndef I2C_SENSOR_INTERFACE_H
#define I2C_SENSOR_INTERFACE_H

#include <Arduino.h>
#include <Wire.h>
#include "Config.h"

class I2CSensorInterface {
private:
  uint8_t address;
  bool available;
  float lastReading;
  uint32_t lastReadTime;
  
  bool readSensorData(float& co2Value);
  
public:
  I2CSensorInterface(uint8_t addr = I2C_SENSOR_ADDR);
  
  bool begin();
  bool isAvailable() const;
  bool getSample(float& co2Value);
  float getLastReading() const;
  uint32_t getLastReadTime() const;
};

#endif // I2C_SENSOR_INTERFACE_H
