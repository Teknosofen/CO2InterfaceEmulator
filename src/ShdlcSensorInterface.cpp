#include "ShdlcSensorInterface.h"

ShdlcSensorInterface::ShdlcSensorInterface(Stream& ser, uint8_t addr)
  : serial(ser), slaveAddress(addr), available(false), measurementRunning(false),
    lastCO2Reading(0), lastReadTime(0), lastPollTime(0) {
  info.identified = false;
  info.fwMajor = 0;
  info.fwMinor = 0;
  info.hwMajor = 0;
  info.hwMinor = 0;
}

// --- Low-level SHDLC ---

uint8_t ShdlcSensorInterface::calculateChecksum(const uint8_t* data, uint8_t len) {
  uint8_t sum = 0;
  for (uint8_t i = 0; i < len; i++) {
    sum += data[i];
  }
  return ~sum;
}

uint16_t ShdlcSensorInterface::stuffAndAppend(uint8_t b, uint8_t* outBuf, uint16_t outIdx) {
  if (b == 0x7E || b == 0x7D || b == 0x11 || b == 0x13) {
    outBuf[outIdx++] = SHDLC::ESCAPE;
    outBuf[outIdx++] = b ^ SHDLC::ESCAPE_XOR;
  } else {
    outBuf[outIdx++] = b;
  }
  return outIdx;
}

uint16_t ShdlcSensorInterface::buildFrame(uint8_t addr, uint8_t cmd,
    const uint8_t* data, uint8_t dataLen, uint8_t* outBuf) {
  // Build checksum input: addr + cmd + length + data
  uint8_t checksumInput[259];
  uint8_t csLen = 0;
  checksumInput[csLen++] = addr;
  checksumInput[csLen++] = cmd;
  checksumInput[csLen++] = dataLen;
  for (uint8_t i = 0; i < dataLen; i++) {
    checksumInput[csLen++] = data[i];
  }
  uint8_t checksum = calculateChecksum(checksumInput, csLen);

  // Build stuffed frame
  uint16_t idx = 0;
  outBuf[idx++] = SHDLC::FRAME_START;
  idx = stuffAndAppend(addr, outBuf, idx);
  idx = stuffAndAppend(cmd, outBuf, idx);
  idx = stuffAndAppend(dataLen, outBuf, idx);
  for (uint8_t i = 0; i < dataLen; i++) {
    idx = stuffAndAppend(data[i], outBuf, idx);
  }
  idx = stuffAndAppend(checksum, outBuf, idx);
  outBuf[idx++] = SHDLC::FRAME_STOP;

  return idx;
}

bool ShdlcSensorInterface::receiveFrame(uint8_t& addr, uint8_t& cmd, uint8_t& state,
    uint8_t* data, uint8_t& dataLen, uint32_t timeoutMs) {
  uint32_t startTime = millis();
  uint16_t rawIdx = 0;
  bool frameStarted = false;

  // Collect raw bytes until stop byte or timeout
  while (millis() - startTime < timeoutMs) {
    if (serial.available()) {
      uint8_t b = serial.read();

      if (!frameStarted) {
        if (b == SHDLC::FRAME_START) {
          frameStarted = true;
          rawIdx = 0;
        }
        continue;
      }

      // Frame started, look for stop
      if (b == SHDLC::FRAME_STOP && rawIdx > 0) {
        // Frame complete - unstuff the raw bytes
        uint8_t unstuffed[280];
        uint16_t uIdx = 0;
        bool escape = false;

        for (uint16_t i = 0; i < rawIdx; i++) {
          if (escape) {
            unstuffed[uIdx++] = rxRaw[i] ^ SHDLC::ESCAPE_XOR;
            escape = false;
          } else if (rxRaw[i] == SHDLC::ESCAPE) {
            escape = true;
          } else {
            unstuffed[uIdx++] = rxRaw[i];
          }
        }

        // MISO frame: addr, cmd, state, length, data..., checksum
        if (uIdx < 5) return false; // Minimum: addr+cmd+state+len+chk

        addr = unstuffed[0];
        cmd = unstuffed[1];
        state = unstuffed[2];
        dataLen = unstuffed[3];

        if (uIdx < (uint16_t)(4 + dataLen + 1)) return false;

        for (uint8_t i = 0; i < dataLen; i++) {
          data[i] = unstuffed[4 + i];
        }

        // Verify checksum (over addr, cmd, state, length, data)
        uint8_t csInput[260];
        uint8_t csLen = 0;
        csInput[csLen++] = addr;
        csInput[csLen++] = cmd;
        csInput[csLen++] = state;
        csInput[csLen++] = dataLen;
        for (uint8_t i = 0; i < dataLen; i++) {
          csInput[csLen++] = data[i];
        }
        uint8_t expected = calculateChecksum(csInput, csLen);
        uint8_t received = unstuffed[4 + dataLen];

        return (expected == received);
      }

      if (rawIdx < MAX_FRAME_SIZE) {
        rxRaw[rawIdx++] = b;
      } else {
        return false; // Frame too large
      }
    }
  }

  return false; // Timeout
}

bool ShdlcSensorInterface::transact(uint8_t cmd, const uint8_t* txData, uint8_t txLen,
    uint8_t& state, uint8_t* rxDataBuf, uint8_t& rxLen, uint32_t timeoutMs) {
  // Build and send MOSI frame
  uint16_t frameLen = buildFrame(slaveAddress, cmd, txData, txLen, txBuf);
  serial.write(txBuf, frameLen);
  serial.flush();

  // Small delay for slave processing
  delay(2);

  // Receive MISO frame
  uint8_t respAddr, respCmd;
  if (!receiveFrame(respAddr, respCmd, state, rxDataBuf, rxLen, timeoutMs)) {
    CMD_SERIAL.print("[CoCo] No response for cmd=0x");
    CMD_SERIAL.println(cmd, HEX);
    return false;
  }

  // Verify response matches command
  if (respCmd != cmd) {
    CMD_SERIAL.print("[CoCo] Command mismatch: sent=0x");
    CMD_SERIAL.print(cmd, HEX);
    CMD_SERIAL.print(" recv=0x");
    CMD_SERIAL.println(respCmd, HEX);
    return false;
  }
  return true;
}

// --- Diagnostics ---

const char* ShdlcSensorInterface::errorCodeToString(uint8_t state) {
  uint8_t errCode = state & 0x7F; // lower 7 bits = execution error
  switch (errCode) {
    case SHDLC::ERR_SUCCESS:         return "Success";
    case SHDLC::ERR_DATA_SIZE:       return "Data size error";
    case SHDLC::ERR_UNKNOWN_CMD:     return "Unknown command";
    case SHDLC::ERR_PARAMETER:       return "Parameter error";
    case SHDLC::ERR_NO_DATA:         return "No measurement data";
    case SHDLC::ERR_CMD_NOT_ALLOWED: return "Command not allowed in current state";
    case SHDLC::ERR_CONFIGURATION:   return "Configuration error";
    case SHDLC::ERR_FATAL:           return "Fatal error";
    default:                         return "Unknown error";
  }
}

void ShdlcSensorInterface::logError(const char* context, uint8_t cmd, uint8_t state) {
  CMD_SERIAL.print("[CoCo] ");
  CMD_SERIAL.print(context);
  CMD_SERIAL.print(" cmd=0x");
  CMD_SERIAL.print(cmd, HEX);
  CMD_SERIAL.print(" state=0x");
  CMD_SERIAL.print(state, HEX);
  CMD_SERIAL.print(" (");
  CMD_SERIAL.print(errorCodeToString(state));
  if (state & 0x80) {
    CMD_SERIAL.print(", DEVICE ERROR FLAG");
  }
  CMD_SERIAL.println(")");
}

// --- High-level CoCo commands ---

bool ShdlcSensorInterface::startPeriodicMeasurement() {
  uint8_t txData[] = { SHDLC::SUB_START_PERIODIC };
  uint8_t state, rxLen = 0;
  uint8_t rxBuf[32];

  if (transact(SHDLC::CMD_START_MEASUREMENT, txData, 1, state, rxBuf, rxLen)) {
    if (state == SHDLC::ERR_SUCCESS) {
      CMD_SERIAL.println("[CoCo] Measurement started");
      measurementRunning = true;
      return true;
    }
    logError("Start measurement failed:", SHDLC::CMD_START_MEASUREMENT, state);
  }
  return false;
}

bool ShdlcSensorInterface::stopMeasurement() {
  uint8_t state, rxLen = 0;
  uint8_t rxBuf[32];

  if (transact(SHDLC::CMD_STOP_MEASUREMENT, nullptr, 0, state, rxBuf, rxLen)) {
    if (state == SHDLC::ERR_SUCCESS) {
      CMD_SERIAL.println("[CoCo] Measurement stopped");
      measurementRunning = false;
      return true;
    }
    logError("Stop measurement failed:", SHDLC::CMD_STOP_MEASUREMENT, state);
  }
  return false;
}

bool ShdlcSensorInterface::readMeasurementValues() {
  uint8_t txData[] = { SHDLC::SUB_READ_MEAS_VALUES };
  uint8_t state, rxLen = 0;
  uint8_t rxBuf[32];

  if (!transact(SHDLC::CMD_READ_MEASUREMENT, txData, 1, state, rxBuf, rxLen)) {
    return false;
  }

  if (state != SHDLC::ERR_SUCCESS) {
    logError("Read measurement failed:", SHDLC::CMD_READ_MEASUREMENT, state);
    return false;
  }

  // Parse response: counter(4) + CO2(2) + flow(2) + pressure(4) + temperature(2) = 14 bytes
  // CO2 partial pressure at bytes 4-5: uint16, big-endian, 0.1 mmHg units. 0xFFFF = invalid.
  if (rxLen >= 6) {
    uint16_t rawCO2 = ((uint16_t)rxBuf[4] << 8) | rxBuf[5];
    if (rawCO2 != 0xFFFF) {
      lastCO2Reading = (float)rawCO2 / 10.0f;
      lastReadTime = millis();
      return true;
    }
  }

  return false;
}

bool ShdlcSensorInterface::getProductType() {
  uint8_t txData[] = { SHDLC::SUB_GET_PRODUCT_TYPE };
  uint8_t state, rxLen = 0;
  uint8_t rxBuf[64];

  if (!transact(SHDLC::CMD_DEVICE_INFO, txData, 1, state, rxBuf, rxLen)) {
    return false;
  }

  if (state == SHDLC::ERR_SUCCESS && rxLen > 0) {
    info.productType = "";
    for (uint8_t i = 0; i < rxLen; i++) {
      if (rxBuf[i] == 0) break;
      info.productType += (char)rxBuf[i];
    }
    return true;
  }
  if (state != SHDLC::ERR_SUCCESS) {
    logError("Get product type failed:", SHDLC::CMD_DEVICE_INFO, state);
  }
  return false;
}

bool ShdlcSensorInterface::getVersion() {
  uint8_t state, rxLen = 0;
  uint8_t rxBuf[16];

  if (!transact(SHDLC::CMD_GET_VERSION, nullptr, 0, state, rxBuf, rxLen)) {
    return false;
  }

  if (state == SHDLC::ERR_SUCCESS && rxLen >= 7) {
    info.fwMajor = rxBuf[0];
    info.fwMinor = rxBuf[1];
    // rxBuf[2] = fw develop flag
    info.hwMajor = rxBuf[3];
    info.hwMinor = rxBuf[4];
    // rxBuf[5..6] = protocol version
    info.identified = true;
    return true;
  }
  if (state != SHDLC::ERR_SUCCESS) {
    logError("Get version failed:", SHDLC::CMD_GET_VERSION, state);
  }
  return false;
}

// --- Public API ---

bool ShdlcSensorInterface::begin() {
  CMD_SERIAL.println("Probing CoCo sensor...");

  // Try to get device info
  if (getProductType()) {
    CMD_SERIAL.print("CoCo sensor found: ");
    CMD_SERIAL.println(info.productType);
  } else {
    CMD_SERIAL.println("CoCo sensor not found, using simulation");
    available = false;
    return false;
  }

  getVersion();
  if (info.identified) {
    CMD_SERIAL.print("Firmware: ");
    CMD_SERIAL.print(info.fwMajor);
    CMD_SERIAL.print(".");
    CMD_SERIAL.println(info.fwMinor);
  }

  available = true;
  return true;
}

bool ShdlcSensorInterface::isAvailable() const { return available; }
bool ShdlcSensorInterface::isMeasurementRunning() const { return measurementRunning; }

bool ShdlcSensorInterface::getSample(float& co2Value) {
  if (!available || !measurementRunning) return false;
  if (lastReadTime == 0) return false;

  co2Value = lastCO2Reading;
  return true;
}

float ShdlcSensorInterface::getLastReading() const { return lastCO2Reading; }
uint32_t ShdlcSensorInterface::getLastReadTime() const { return lastReadTime; }
const ShdlcSensorInterface::SensorInfo& ShdlcSensorInterface::getSensorInfo() const { return info; }

bool ShdlcSensorInterface::startMeasuring() {
  if (!available) return false;
  return startPeriodicMeasurement();
}

bool ShdlcSensorInterface::stopMeasuring() {
  if (!available) return false;
  return stopMeasurement();
}

void ShdlcSensorInterface::update() {
  if (!available || !measurementRunning) return;

  uint32_t now = millis();
  if (now - lastPollTime >= SHDLC::POLL_INTERVAL_MS) {
    lastPollTime = now;
    readMeasurementValues();
  }
}
