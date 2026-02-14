#include "CommandLineInterface.h"
#include "Config.h"
#include <WiFi.h>

CommandLineInterface::CommandLineInterface(WaveformGenerator& wave,
                                           DeviceState& dev, ConfigStorage& stor, Stream& ser)
  : waveform(wave), device(dev), storage(stor), serial(ser) {}

void CommandLineInterface::setUsbModeCallback(std::function<void(bool)> cb) {
  usbModeCallback = cb;
}

void CommandLineInterface::printHelp() {
  serial.println("\n=== CO2 Emulator Commands ===");
  serial.println("Wave: amp/freq/base <value>  (freq in br/min)");
  serial.println("Wave: wavetype <0=sine|1=capno>");
  serial.println("Sensor: usecoco <0/1>");
  serial.println("USB: usbmode <0=debug|1=protocol>");
  serial.println("Config: save/load/clear");
  serial.println("Info: status/help/ip");
}

void CommandLineInterface::printStatus() {
  serial.println("\n=== Current Settings ===");
  serial.print("Waveform: amp="); serial.print(waveform.getAmplitude());
  serial.print(" freq="); serial.print(waveform.getFrequency() * 60.0, 1); serial.print(" br/min");
  serial.print(" base="); serial.println(waveform.getBaseline());

  serial.print("Type: ");
  serial.println(waveform.getWaveformType() == WaveformGenerator::WaveformType::CAPNOGRAM ? "Capnogram" : "Sine");

  serial.print("Source: ");
  serial.println(waveform.isUsingCocoSensor() ? "CoCo Sensor" : "Simulation");

  serial.print("Device: ");
  serial.print(device.isContinuousMode() ? "CONTINUOUS" : "IDLE");
  serial.print(" init=");
  serial.println(device.isInitialized() ? "YES" : "NO");

  serial.print("USB: ");
  serial.println(device.isUsbProtocolMode() ? "PROTOCOL" : "DEBUG");
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
    float bpm = arg.toFloat();
    if (bpm >= 5.0 && bpm <= 90.0) {
      waveform.setFrequency(bpm / 60.0);
      serial.print("Resp rate: "); serial.print(bpm, 1); serial.println(" br/min");
    } else {
      serial.println("Range: 5-90 br/min");
    }
  }
  else if (cmd == "base" && arg.length() > 0) {
    waveform.setBaseline(arg.toFloat());
    serial.print("Baseline: "); serial.println(waveform.getBaseline());
  }
  else if (cmd == "wavetype" && arg.length() > 0) {
    int type = arg.toInt();
    if (type == 0) {
      waveform.setWaveformType(WaveformGenerator::WaveformType::SINE);
      serial.println("Waveform: Sine");
    } else if (type == 1) {
      waveform.setWaveformType(WaveformGenerator::WaveformType::CAPNOGRAM);
      serial.println("Waveform: Capnogram");
    } else {
      serial.println("Invalid. 0=Sine, 1=Capnogram");
    }
  }
  else if (cmd == "usecoco" && arg.length() > 0) {
    waveform.setUseCocoSensor(arg.toInt() != 0);
    serial.print("CoCo sensor ");
    serial.println(waveform.isUsingCocoSensor() ? "enabled" : "disabled");
  }
  else if (cmd == "usbmode" && arg.length() > 0) {
    if (usbModeCallback) {
      bool protocol = (arg.toInt() != 0);
      usbModeCallback(protocol);
    }
  }
  else if (cmd == "save") {
    ConfigStorage::Config cfg;
    cfg.amplitude = waveform.getAmplitude();
    cfg.frequency = waveform.getFrequency();
    cfg.baseline = waveform.getBaseline();
    cfg.useCocoSensor = waveform.isUsingCocoSensor();
    cfg.waveformType = (uint8_t)waveform.getWaveformType();
    storage.saveConfig(cfg);
  }
  else if (cmd == "load") {
    ConfigStorage::Config cfg = storage.loadConfig();
    waveform.loadFromConfig(cfg);
    printStatus();
  }
  else if (cmd == "clear") {
    storage.clearConfig();
  }
  else if (cmd == "ip") {
    #if WIFI_AP_MODE
      serial.print("SSID: "); serial.println(WIFI_AP_SSID);
      serial.print("Password: "); serial.println(WIFI_AP_PASSWORD);
      serial.print("IP: "); serial.println(WiFi.softAPIP());
    #else
      serial.print("SSID: "); serial.println(WIFI_STA_SSID);
      serial.print("IP: "); serial.println(WiFi.localIP());
    #endif
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
  serial.println("\n=== CO2 Interface Emulator ===");
  serial.println("Type 'help' for commands\n");
  printStatus();
}
