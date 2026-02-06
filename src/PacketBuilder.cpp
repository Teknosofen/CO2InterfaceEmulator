#include "PacketBuilder.h"

PacketBuilder::PacketBuilder() : index(0) {}

void PacketBuilder::reset() { 
  index = 0; 
}

void PacketBuilder::addByte(uint8_t b) { 
  if (index < 64) buffer[index++] = b; 
}

void PacketBuilder::addCommand(uint8_t cmd) {
  reset();
  addByte(cmd);
  addByte(0);  // NBF placeholder
}

void PacketBuilder::add2ByteValue(uint16_t value) {
  addByte((value >> 7) & 0x7F);
  addByte(value & 0x7F);
}

void PacketBuilder::addCO2Waveform(float co2Value) {
  int16_t encoded = (int16_t)(co2Value * 100.0) + 1000;
  if (encoded < 0) encoded = 0;
  add2ByteValue(encoded);
}

void PacketBuilder::finalize() {
  buffer[1] = index - 1;
  uint8_t sum = 0;
  for (uint8_t i = 0; i < index; i++) sum += buffer[i];
  addByte((-sum) & 0x7F);
}

void PacketBuilder::send(Stream& serial) { 
  serial.write(buffer, index); 
}

uint8_t PacketBuilder::calculateChecksum(const uint8_t* buf, uint8_t len) {
  uint8_t sum = 0;
  for (uint8_t i = 0; i < len; i++) sum += buf[i];
  return ((-sum) & 0x7F);
}

uint16_t PacketBuilder::decode2Bytes(uint8_t b1, uint8_t b2) {
  return (b1 * 128) + b2;
}
