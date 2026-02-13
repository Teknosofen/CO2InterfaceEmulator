#ifndef SHDLC_SENSOR_INTERFACE_H
#define SHDLC_SENSOR_INTERFACE_H

#include <Arduino.h>
#include "Config.h"

class ShdlcSensorInterface {
public:
  struct SensorInfo {
    String productType;
    uint8_t fwMajor;
    uint8_t fwMinor;
    uint8_t hwMajor;
    uint8_t hwMinor;
    bool identified;
  };

private:
  Stream& serial;
  uint8_t slaveAddress;
  bool available;
  bool measurementRunning;
  float lastCO2Reading;
  uint32_t lastReadTime;
  uint32_t lastPollTime;
  SensorInfo info;

  // SHDLC frame buffers
  static const uint16_t MAX_FRAME_SIZE = 300;
  uint8_t txBuf[MAX_FRAME_SIZE];
  uint8_t rxRaw[MAX_FRAME_SIZE];
  uint8_t rxData[256];

  // Low-level SHDLC methods
  uint8_t calculateChecksum(const uint8_t* data, uint8_t len);
  uint16_t stuffAndAppend(uint8_t b, uint8_t* outBuf, uint16_t outIdx);
  uint16_t buildFrame(uint8_t addr, uint8_t cmd, const uint8_t* data, uint8_t dataLen, uint8_t* outBuf);
  bool receiveFrame(uint8_t& addr, uint8_t& cmd, uint8_t& state,
                    uint8_t* data, uint8_t& dataLen, uint32_t timeoutMs);
  bool transact(uint8_t cmd, const uint8_t* txData, uint8_t txLen,
                uint8_t& state, uint8_t* rxDataBuf, uint8_t& rxLen, uint32_t timeoutMs = SHDLC::RESPONSE_TIMEOUT_MS);

  // Diagnostics
  static const char* errorCodeToString(uint8_t state);
  void logError(const char* context, uint8_t cmd, uint8_t state);

  // High-level CoCo commands
  bool startPeriodicMeasurement();
  bool stopMeasurement();
  bool readMeasurementValues();
  bool getProductType();
  bool getVersion();

public:
  ShdlcSensorInterface(Stream& ser, uint8_t addr = COCO_SENSOR_ADDR);

  bool begin();
  bool isAvailable() const;
  bool isMeasurementRunning() const;
  bool getSample(float& co2Value);
  float getLastReading() const;
  uint32_t getLastReadTime() const;
  const SensorInfo& getSensorInfo() const;

  bool startMeasuring();
  bool stopMeasuring();
  void update();
};

#endif // SHDLC_SENSOR_INTERFACE_H
