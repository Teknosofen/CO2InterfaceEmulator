#ifndef PACKET_BUILDER_H
#define PACKET_BUILDER_H

#include <Arduino.h>

class PacketBuilder {
private:
  uint8_t buffer[64];
  uint8_t index;
  
public:
  PacketBuilder();
  
  void reset();
  void addByte(uint8_t b);
  void addCommand(uint8_t cmd);
  void add2ByteValue(uint16_t value);
  void addCO2Waveform(float co2Value);
  void finalize();
  void send(Stream& serial);
  
  static uint8_t calculateChecksum(const uint8_t* buf, uint8_t len);
  static uint16_t decode2Bytes(uint8_t b1, uint8_t b2);
};

#endif // PACKET_BUILDER_H
