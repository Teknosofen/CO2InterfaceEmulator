#ifndef PROTOCOL_HANDLER_H
#define PROTOCOL_HANDLER_H

#include <Arduino.h>
#include "DeviceState.h"
#include "WaveformGenerator.h"
#include "AlarmManager.h"
#include "PacketBuilder.h"
#include "Config.h"

class ProtocolHandler {
private:
  DeviceState& device;
  WaveformGenerator& waveform;
  AlarmManager& alarms;
  Stream& serial;
  
  void sendNACK(uint8_t errorCode);
  void sendSimpleResponse(uint8_t cmd);
  void handleGetRevision(uint8_t format);
  void handleSensorCapabilities(uint8_t sci, uint8_t scb);
  void handleGetSetSettings(uint8_t isb, const uint8_t* data, uint8_t dataLen);
  void handleZero();
  
public:
  ProtocolHandler(DeviceState& dev, WaveformGenerator& wave, 
                  AlarmManager& alarm, Stream& ser);
  
  void sendWaveformPacket(bool includeDPI, uint8_t dpiType);
  void processCommand(uint8_t* buf, uint8_t len);
};

#endif // PROTOCOL_HANDLER_H
