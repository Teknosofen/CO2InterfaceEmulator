#include "ProtocolReceiver.h"

ProtocolReceiver::ProtocolReceiver(ProtocolHandler& h, Stream& ser)
  : index(0), lastByteTime(0), handler(h), serial(ser) {}

void ProtocolReceiver::update() {
  uint32_t now = millis();
  
  while (serial.available()) {
    uint8_t b = serial.read();
    
    if (b >= 0x80) {
      index = 0;
      buffer[index++] = b;
      lastByteTime = now;
    } else if (index > 0) {
      if (now - lastByteTime > 500) {
        index = 0;
        PacketBuilder packet;
        packet.addCommand(Protocol::CMD_NACK);
        packet.addByte(Protocol::NACK_TIMEOUT);
        packet.finalize();
        packet.send(serial);
      } else {
        buffer[index++] = b;
        
        if (index >= 2) {
          uint8_t nbf = buffer[1];
          if (index >= nbf + 2) {
            handler.processCommand(buffer, index);
            index = 0;
          }
        }
        
        lastByteTime = now;
      }
    }
  }
}
