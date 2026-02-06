#include "CommandLineInterface.h"
#include <WiFi.h>

CommandLineInterface::CommandLineInterface(WaveformGenerator& wave, AlarmManager& alarm, 
                                           DeviceState& dev, ConfigStorage& stor, Stream& ser)
  : waveform(wave), alarms(alarm), device(dev), storage(stor), serial(ser) {}

void CommandLineInterface::printHelp() {
  serial.println("\n=== CO2 Emulator Commands ===");
  serial.println("Wave: amp/freq/base/phase <value>");
  serial.println("Alarm: high/low/highen/lowen <value>");
  serial.println("I2C: usei2c <0/1>");
  serial.println("Config: save/load/clear");
  serial.println("Info: status/help/ip");
}

void CommandLineInterface::printStatus() {
  serial.println("\n=== Current Settings ===");
  serial.print("Waveform: amp="); serial.print(waveform.getAmplitude());
  serial.print(" freq="); serial.print(waveform.getFrequency());
  serial.print(" base="); serial.print(waveform.getBaseline());
  serial.print(" phase="); serial.println(waveform.getPhase() * 180.0 / PI);
  
  serial.print("Source: "); 
  serial.println(waveform.isUsingI2CSensor() ? "I2C Sensor" : "Simulation");
  
  serial.print("Alarms: high="); serial.print(alarms.getHighThreshold());
  serial.print(alarms.isHighEnabled() ? " (ON)" : " (OFF)");
  serial.print(" low="); serial.print(alarms.getLowThreshold());
  serial.println(alarms.isLowEnabled() ? " (ON)" : " (OFF)");
  
  serial.print("Device: ");
  serial.print(device.isContinuousMode() ? "CONTINUOUS" : "IDLE");
  serial.print(" init=");
  serial.println(device.isInitialized() ? "YES" : "NO");
}

void CommandLineInterface::processLine(String line) {
  line.trim();
  line.toLowerCase();
  
  int spaceIdx = line.indexOf(' ');
  String cmd = spaceIdx > 0 ? line.substring(0, spaceIdx) : line;
  String arg = spaceIdx > 0 ? line.substring(spaceIdx + 1) : "";
  
  if (cmd == "help") printHelp();
  else if (cmd == "status") printStatus();
  else if (cmd == "amp" && arg.length() > 0) {
    waveform.setAmplitude(arg.toFloat());
    serial.print("Amplitude: "); serial.println(waveform.getAmplitude());
  }
  else if (cmd == "freq" && arg.length() > 0) {
    waveform.setFrequency(arg.toFloat());
    serial.print("Frequency: "); serial.println(waveform.getFrequency());
  }
  else if (cmd == "base" && arg.length() > 0) {
    waveform.setBaseline(arg.toFloat());
    serial.print("Baseline: "); serial.println(waveform.getBaseline());
  }
  else if (cmd == "phase" && arg.length() > 0) {
    waveform.setPhase(arg.toFloat() * PI / 180.0);
    serial.print("Phase: "); serial.println(arg.toFloat());
  }
  else if (cmd == "high" && arg.length() > 0) {
    alarms.setHighThreshold(arg.toFloat());
    serial.print("High alarm: "); serial.println(alarms.getHighThreshold());
  }
  else if (cmd == "low" && arg.length() > 0) {
    alarms.setLowThreshold(arg.toFloat());
    serial.print("Low alarm: "); serial.println(alarms.getLowThreshold());
  }
  else if (cmd == "highen" && arg.length() > 0) {
    alarms.enableHigh(arg.toInt() != 0);
    serial.print("High alarm "); 
    serial.println(alarms.isHighEnabled() ? "enabled" : "disabled");
  }
  else if (cmd == "lowen" && arg.length() > 0) {
    alarms.enableLow(arg.toInt() != 0);
    serial.print("Low alarm "); 
    serial.println(alarms.isLowEnabled() ? "enabled" : "disabled");
  }
  else if (cmd == "usei2c" && arg.length() > 0) {
    waveform.setUseI2CSensor(arg.toInt() != 0);
    serial.print("I2C sensor "); 
    serial.println(waveform.isUsingI2CSensor() ? "enabled" : "disabled");
  }
  else if (cmd == "save") {
    ConfigStorage::Config cfg;
    cfg.amplitude = waveform.getAmplitude();
    cfg.frequency = waveform.getFrequency();
    cfg.baseline = waveform.getBaseline();
    cfg.phase = waveform.getPhase();
    cfg.alarmHigh = alarms.getHighThreshold();
    cfg.alarmLow = alarms.getLowThreshold();
    cfg.alarmHighEnabled = alarms.isHighEnabled();
    cfg.alarmLowEnabled = alarms.isLowEnabled();
    cfg.useI2CSensor = waveform.isUsingI2CSensor();
    storage.saveConfig(cfg);
  }
  else if (cmd == "load") {
    ConfigStorage::Config cfg = storage.loadConfig();
    waveform.loadFromConfig(cfg);
    alarms.loadFromConfig(cfg);
    printStatus();
  }
  else if (cmd == "clear") {
    storage.clearConfig();
  }
  else if (cmd == "ip") {
    serial.print("IP Address: ");
    serial.println(WiFi.localIP());
  }
  else {
    serial.println("Unknown command. Type 'help'");
  }
}

void CommandLineInterface::update() {
  while (serial.available()) {
    char c = serial.read();
    if (c == '\n' || c == '\r') {
      if (lineBuffer.length() > 0) {
        processLine(lineBuffer);
        lineBuffer = "";
      }
    } else {
      lineBuffer += c;
    }
  }
}

void CommandLineInterface::printWelcome() {
  serial.println("\n=== CO2 Sensor Emulator ===");
  serial.println("Type 'help' for commands\n");
  printStatus();
}
