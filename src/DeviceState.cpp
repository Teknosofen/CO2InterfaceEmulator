#include "DeviceState.h"

DeviceState::DeviceState() 
  : continuousMode(false), initialized(false), syncCounter(0),
    barometricPressure(760), o2Compensation(16), balanceGas(0),
    anestheticAgent(0), gasTemp(350), etco2TimePeriod(10),
    noBreathTimeout(20), co2Units(0),
    zeroInProgress(false), zeroStartTime(0), compensationsSet(false),
    statusByte1(0), statusByte2(0x10), statusByte3(0),
    etco2(380), respRate(15), inspCO2(0) {}

void DeviceState::startContinuousMode() { 
  continuousMode = true; 
  initialized = true;
  syncCounter = 0;
}

void DeviceState::stopContinuousMode() { continuousMode = false; }
bool DeviceState::isContinuousMode() const { return continuousMode; }
bool DeviceState::isInitialized() const { return initialized; }

uint8_t DeviceState::getAndIncrementSync() {
  uint8_t val = syncCounter;
  syncCounter = (syncCounter + 1) & 0x7F;
  return val;
}

void DeviceState::setBarometricPressure(uint16_t value) { 
  barometricPressure = value;
  compensationsSet = true;
  statusByte2 &= ~0x10;
}

uint16_t DeviceState::getBarometricPressure() const { return barometricPressure; }

void DeviceState::setGasTemp(uint16_t value) { gasTemp = value; }
uint16_t DeviceState::getGasTemp() const { return gasTemp; }

void DeviceState::setETCO2TimePeriod(uint8_t value) { etco2TimePeriod = value; }
uint8_t DeviceState::getETCO2TimePeriod() const { return etco2TimePeriod; }

void DeviceState::setNoBreathTimeout(uint8_t value) { noBreathTimeout = value; }
uint8_t DeviceState::getNoBreathTimeout() const { return noBreathTimeout; }

void DeviceState::setCO2Units(uint8_t value) { co2Units = value; }
uint8_t DeviceState::getCO2Units() const { return co2Units; }

void DeviceState::setGasCompensations(uint8_t o2, uint8_t balance, uint16_t anesthetic) {
  o2Compensation = o2;
  balanceGas = balance;
  anestheticAgent = anesthetic;
  compensationsSet = true;
  statusByte2 &= ~0x10;
}

uint8_t DeviceState::getO2Compensation() const { return o2Compensation; }
uint8_t DeviceState::getBalanceGas() const { return balanceGas; }
uint16_t DeviceState::getAnestheticAgent() const { return anestheticAgent; }

bool DeviceState::canStartZero() const { return compensationsSet && !zeroInProgress; }

void DeviceState::startZero() {
  zeroInProgress = true;
  zeroStartTime = millis();
}

void DeviceState::updateZero() {
  if (zeroInProgress && (millis() - zeroStartTime > 2000)) {
    zeroInProgress = false;
    statusByte2 &= ~0x0C;
  }
}

bool DeviceState::isZeroInProgress() const { return zeroInProgress; }
bool DeviceState::isCompensationsSet() const { return compensationsSet; }

uint8_t DeviceState::getStatusByte1() const { return statusByte1; }
uint8_t DeviceState::getStatusByte2() const { return statusByte2; }
uint8_t DeviceState::getStatusByte3() const { return statusByte3; }

void DeviceState::setStatusByte1(uint8_t value) { statusByte1 = value; }
void DeviceState::clearStatusByte1() { statusByte1 = 0; }

void DeviceState::updateParameters(uint16_t etco2Val, uint16_t respRateVal) {
  etco2 = etco2Val;
  respRate = respRateVal;
}

uint16_t DeviceState::getETCO2() const { return etco2; }
uint16_t DeviceState::getRespRate() const { return respRate; }
uint16_t DeviceState::getInspCO2() const { return inspCO2; }
