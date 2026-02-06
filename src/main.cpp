// main.cpp
#include <Arduino.h>
#include "CO2Emulator.h"

CO2Emulator emulator;

void setup() {
  emulator.begin();
}

void loop() {
  emulator.update();
}
