#include "ProtocolHandler.h"

ProtocolHandler::ProtocolHandler(DeviceState& dev, WaveformGenerator& wave, 
                                 AlarmManager& alarm, Stream& ser)
  : device(dev), waveform(wave), alarms(alarm), serial(ser) {}

void ProtocolHandler::sendNACK(uint8_t errorCode) {
  PacketBuilder packet;
  packet.addCommand(Protocol::CMD_NACK);
  packet.addByte(errorCode);
  packet.finalize();
  packet.send(serial);
}

void ProtocolHandler::sendSimpleResponse(uint8_t cmd) {
  PacketBuilder packet;
  packet.addCommand(cmd);
  packet.finalize();
  packet.send(serial);
}

void ProtocolHandler::handleGetRevision(uint8_t format) {
  const char* revStr = "code-capno5-01 01/01/25 12:00:00";
  PacketBuilder packet;
  packet.addCommand(Protocol::CMD_GET_REVISION);
  packet.addByte(format);
  for (const char* p = revStr; *p; p++) packet.addByte(*p);
  packet.finalize();
  packet.send(serial);
}

void ProtocolHandler::handleSensorCapabilities(uint8_t sci, uint8_t scb) {
  PacketBuilder packet;
  packet.addCommand(Protocol::CMD_SENSOR_CAPS);
  packet.addByte(sci);
  packet.addByte((sci == 0 || sci == 1) ? 0x01 : (scb & 0x01));
  packet.finalize();
  packet.send(serial);
}

void ProtocolHandler::handleGetSetSettings(uint8_t isb, const uint8_t* data, uint8_t dataLen) {
  PacketBuilder packet;
  packet.addCommand(Protocol::CMD_GET_SET_SETTINGS);
  
  if (dataLen > 0) {
    switch (isb) {
      case 1: device.setBarometricPressure(PacketBuilder::decode2Bytes(data[0], data[1])); break;
      case 4: device.setGasTemp(PacketBuilder::decode2Bytes(data[0], data[1])); break;
      case 5: device.setETCO2TimePeriod(data[0]); break;
      case 6: device.setNoBreathTimeout(data[0]); break;
      case 7: device.setCO2Units(data[0]); break;
      case 11: device.setGasCompensations(data[0], data[1], 
                                         PacketBuilder::decode2Bytes(data[2], data[3])); break;
    }
  }
  
  packet.addByte(isb);
  
  switch (isb) {
    case 1: packet.add2ByteValue(device.getBarometricPressure()); break;
    case 4: packet.add2ByteValue(device.getGasTemp()); break;
    case 5: packet.addByte(device.getETCO2TimePeriod()); break;
    case 6: packet.addByte(device.getNoBreathTimeout()); break;
    case 7: packet.addByte(device.getCO2Units()); break;
    case 11:
      packet.addByte(device.getO2Compensation());
      packet.addByte(device.getBalanceGas());
      packet.add2ByteValue(device.getAnestheticAgent());
      break;
    case 18:
      for (const char* p = "1028494TL "; *p; p++) packet.addByte(*p);
      break;
    case 19: packet.addByte(0x01); break;
    default:
      packet.reset();
      packet.addCommand(Protocol::CMD_GET_SET_SETTINGS);
      packet.addByte(0);
      break;
  }
  
  packet.finalize();
  packet.send(serial);
}

void ProtocolHandler::handleZero() {
  PacketBuilder packet;
  packet.addCommand(Protocol::CMD_ZERO);
  
  if (!device.isCompensationsSet()) {
    packet.addByte(1);
  } else if (device.isZeroInProgress()) {
    packet.addByte(2);
  } else {
    device.startZero();
    packet.addByte(0);
  }
  
  packet.finalize();
  packet.send(serial);
}

void ProtocolHandler::sendWaveformPacket(bool includeDPI, uint8_t dpiType) {
  PacketBuilder packet;
  packet.addCommand(Protocol::CMD_CO2_WAVEFORM);
  packet.addByte(device.getAndIncrementSync());
  
  float co2Value = waveform.getSample();
  uint8_t status = device.getStatusByte1();
  alarms.checkAlarms(co2Value, status);
  device.setStatusByte1(status);
  
  packet.addCO2Waveform(co2Value);
  
  if (includeDPI) {
    packet.addByte(dpiType);
    
    switch (dpiType) {
      case Protocol::DPI_CO2_STATUS:
        packet.addByte(device.getStatusByte1());
        packet.addByte(device.getStatusByte2());
        packet.addByte(device.getStatusByte3());
        packet.addByte(0);
        packet.addByte(0);
        break;
      case Protocol::DPI_ETCO2: packet.add2ByteValue(device.getETCO2()); break;
      case Protocol::DPI_RESP_RATE: packet.add2ByteValue(device.getRespRate()); break;
      case Protocol::DPI_INSP_CO2: packet.add2ByteValue(device.getInspCO2()); break;
      case Protocol::DPI_BREATH_DETECTED: break;
    }
  }
  
  packet.finalize();
  packet.send(serial);
}

void ProtocolHandler::processCommand(uint8_t* buf, uint8_t len) {
  if (len < 2) return;
  
  uint8_t cmd = buf[0];
  uint8_t nbf = buf[1];
  
  if (PacketBuilder::calculateChecksum(buf, len) != 0) {
    sendNACK(Protocol::NACK_CHECKSUM);
    return;
  }
  
  switch (cmd) {
    case Protocol::CMD_CO2_WAVEFORM:
      device.startContinuousMode();
      sendWaveformPacket(false, 0);
      break;
    case Protocol::CMD_STOP_CONTINUOUS:
      device.stopContinuousMode();
      sendSimpleResponse(Protocol::CMD_STOP_CONTINUOUS);
      break;
    case Protocol::CMD_GET_REVISION:
      if (nbf >= 2) handleGetRevision(buf[2]);
      break;
    case Protocol::CMD_SENSOR_CAPS:
      if (nbf == 2) handleSensorCapabilities(buf[2], 0);
      else if (nbf == 3) handleSensorCapabilities(buf[2], buf[3]);
      break;
    case Protocol::CMD_GET_SET_SETTINGS:
      if (nbf >= 2) handleGetSetSettings(buf[2], &buf[3], nbf - 2);
      break;
    case Protocol::CMD_ZERO:
      handleZero();
      break;
    case Protocol::CMD_RESET_NO_BREATH:
      device.clearStatusByte1();
      sendSimpleResponse(Protocol::CMD_RESET_NO_BREATH);
      break;
    default:
      sendNACK(Protocol::NACK_INVALID_CMD);
      break;
  }
}
