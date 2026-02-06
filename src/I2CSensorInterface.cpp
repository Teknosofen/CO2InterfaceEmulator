#include "I2CSensorInterface.h"

I2CSensorInterface::I2CSensorInterface(uint8_t addr) 
  : address(addr), available(false), lastReading(0), lastReadTime(0) {}

bool I2CSensorInterface::begin() {
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(100000);
  
  Wire.beginTransmission(address);
  available = (Wire.endTransmission() == 0);
  
  if (available) {
    CMD_SERIAL.print("I2C sensor found at 0x");
    CMD_SERIAL.println(address, HEX);
  } else {
    CMD_SERIAL.println("I2C sensor not found, using simulation");
  }
  
  return available;
}

bool I2CSensorInterface::isAvailable() const { 
  return available; 
}

bool I2CSensorInterface::readSensorData(float& co2Value) {
  // Template implementation - customize for your sensor
  // Example for generic I2C sensor:
  Wire.beginTransmission(address);
  Wire.write(0x00);  // Read command
  if (Wire.endTransmission() != 0) return false;
  
  delay(10);
  
  if (Wire.requestFrom(address, (uint8_t)2) != 2) return false;
  
  uint16_t rawValue = Wire.read() << 8;
  rawValue |= Wire.read();
  
  co2Value = rawValue * 0.01;  // Example conversion
  
  return true;
}

bool I2CSensorInterface::getSample(float& co2Value) {
  if (!available) return false;
  
  if (readSensorData(co2Value)) {
    lastReading = co2Value;
    lastReadTime = millis();
    return true;
  }
  
  return false;
}

float I2CSensorInterface::getLastReading() const { 
  return lastReading; 
}

uint32_t I2CSensorInterface::getLastReadTime() const { 
  return lastReadTime; 
}
