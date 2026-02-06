#ifndef DEVICE_STATE_H
#define DEVICE_STATE_H

#include <Arduino.h>

class DeviceState {
private:
  bool continuousMode;
  bool initialized;
  uint8_t syncCounter;
  
  uint16_t barometricPressure;
  uint8_t o2Compensation;
  uint8_t balanceGas;
  uint16_t anestheticAgent;
  uint16_t gasTemp;
  uint8_t etco2TimePeriod;
  uint8_t noBreathTimeout;
  uint8_t co2Units;
  
  bool zeroInProgress;
  uint32_t zeroStartTime;
  bool compensationsSet;
  uint8_t statusByte1;
  uint8_t statusByte2;
  uint8_t statusByte3;
  
  uint16_t etco2;
  uint16_t respRate;
  uint16_t inspCO2;
  
public:
  DeviceState();
  
  void startContinuousMode();
  void stopContinuousMode();
  bool isContinuousMode() const;
  bool isInitialized() const;
  
  uint8_t getAndIncrementSync();
  
  void setBarometricPressure(uint16_t value);
  uint16_t getBarometricPressure() const;
  
  void setGasTemp(uint16_t value);
  uint16_t getGasTemp() const;
  
  void setETCO2TimePeriod(uint8_t value);
  uint8_t getETCO2TimePeriod() const;
  
  void setNoBreathTimeout(uint8_t value);
  uint8_t getNoBreathTimeout() const;
  
  void setCO2Units(uint8_t value);
  uint8_t getCO2Units() const;
  
  void setGasCompensations(uint8_t o2, uint8_t balance, uint16_t anesthetic);
  uint8_t getO2Compensation() const;
  uint8_t getBalanceGas() const;
  uint16_t getAnestheticAgent() const;
  
  bool canStartZero() const;
  void startZero();
  void updateZero();
  bool isZeroInProgress() const;
  bool isCompensationsSet() const;
  
  uint8_t getStatusByte1() const;
  uint8_t getStatusByte2() const;
  uint8_t getStatusByte3() const;
  
  void setStatusByte1(uint8_t value);
  void clearStatusByte1();
  
  void updateParameters(uint16_t etco2Val, uint16_t respRateVal);
  uint16_t getETCO2() const;
  uint16_t getRespRate() const;
  uint16_t getInspCO2() const;
};

#endif // DEVICE_STATE_H
