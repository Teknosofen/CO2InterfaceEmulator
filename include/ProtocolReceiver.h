#ifndef PROTOCOL_RECEIVER_H
#define PROTOCOL_RECEIVER_H

#include <Arduino.h>
#include "ProtocolHandler.h"

class ProtocolReceiver {
private:
  uint8_t buffer[64];
  uint8_t index;
  uint32_t lastByteTime;
  ProtocolHandler& handler;
  Stream& serial;
  
public:
  ProtocolReceiver(ProtocolHandler& h, Stream& ser);
  void update();
};

#endif // PROTOCOL_RECEIVER_H
