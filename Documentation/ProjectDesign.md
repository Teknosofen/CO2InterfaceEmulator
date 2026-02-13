# CO2 Interface Emulator - Project & Design Description

## Purpose

This firmware emulates the **Respironics Capnostat 5** CO2 sensor interface, allowing a host device (patient monitor, PC test software, etc.) to receive CO2 waveform data and parameter packets as if a real Capnostat 5 sensor were connected.

The CO2 data source is selectable:
- **Internal waveform generator** producing sine or realistic capnogram waveforms with user-adjustable parameters (amplitude, frequency, baseline, phase).
- **Sensirion CoCo CO2 sensor** connected via SHDLC/UART, providing real measured CO2 values.

## Hardware

**Platform:** LilyGo T-Display S3 (ESP32-S3, 16MB Flash, 320KB RAM, built-in ST7789 170x320 TFT)

### Serial Port Assignments

| Port | Hardware | Baud | Function |
|------|----------|------|----------|
| Serial (USB CDC) | Built-in USB | 115200 | Debug CLI (default) / Respironics protocol output (switchable) |
| Serial1 | GPIO 43 (TX), GPIO 44 (RX) | 19200 | Respironics Capnostat 5 protocol - **always active** |
| Serial2 | GPIO 17 (TX), GPIO 18 (RX) | 115200 | Sensirion CoCo sensor (SHDLC) |

### USB Port Dual-Mode

The USB serial port serves two purposes:
- **DEBUG mode** (default): Serial CLI for configuration and diagnostics.
- **PROTOCOL mode**: Mirrors the Respironics protocol output from Serial1, enabling PC test software to verify emulator behavior.

Mode is switchable via the WiFi web interface or CLI command (`usbmode`).

## Architecture

```
main.cpp
  |
  v
CO2Emulator          (orchestrator - owns all components)
  |
  +-- WaveformGenerator     generates CO2 samples (sine/capnogram/sensor)
  |     +-- ShdlcSensorInterface  (optional live CoCo sensor input)
  |
  +-- DeviceState            tracks all device parameters and mode flags
  +-- AlarmManager           high/low CO2 threshold monitoring
  +-- ConfigStorage          persistent settings (ESP32 Preferences/NVS)
  |
  +-- ProtocolHandler        builds and sends Capnostat 5 packets
  |     +-- PacketBuilder    low-level packet construction + checksum
  +-- ProtocolReceiver       parses incoming Capnostat 5 commands (Serial1)
  +-- ProtocolReceiver*      optional second receiver (USB, when in protocol mode)
  |
  +-- CommandLineInterface   serial debug/config CLI
  +-- WebInterface           WiFi AP web server with live dashboard
  +-- TFTDisplay             on-board TFT waveform visualization
```

### Component Responsibilities

| Component | File(s) | Role |
|-----------|---------|------|
| **CO2Emulator** | CO2Emulator.h/cpp | Initializes all subsystems, runs the main loop, manages USB mode switching, coordinates waveform packet generation at 100 Hz with DPI parameter packets every 1 s. |
| **WaveformGenerator** | WaveformGenerator.h/cpp | Produces CO2 sample values. In simulator mode: sine wave or realistic capnogram with smoothstep transitions. In sensor mode: passes through CoCo readings. Computes ETCO2 and respiratory rate. |
| **ShdlcSensorInterface** | ShdlcSensorInterface.h/cpp | Full SHDLC master implementation for the Sensirion CoCo sensor. Handles frame building, byte stuffing, checksum, command transactions, and measurement polling at 100 ms intervals. Includes diagnostic error logging. |
| **DeviceState** | DeviceState.h/cpp | Central state: USB mode, continuous mode flag, barometric pressure, gas temperature, CO2 units, gas compensations, zero calibration, status bytes, ETCO2/RR/InspCO2 values. |
| **AlarmManager** | AlarmManager.h/cpp | Configurable high/low CO2 thresholds with enable flags. Sets alarm bit in status byte when triggered. |
| **ConfigStorage** | ConfigStorage.h/cpp | Saves/loads waveform and alarm settings to ESP32 NVS (non-volatile storage) using the Preferences library. |
| **ProtocolHandler** | ProtocolHandler.h/cpp | Implements the Capnostat 5 serial protocol. Handles incoming commands (start/stop waveform, zero cal, get/set settings, revision, capabilities). Builds and sends waveform + DPI response packets. Supports multiple simultaneous output streams. |
| **ProtocolReceiver** | ProtocolReceiver.h/cpp | Receives and reassembles incoming serial packets (start byte detection, NBF-based framing, 500 ms timeout). Passes complete packets to ProtocolHandler. |
| **PacketBuilder** | PacketBuilder.h/cpp | Constructs protocol packets byte-by-byte. Handles CO2 waveform encoding `(CO2 * 100 + 1000)` as 2-byte value. Calculates 7-bit negative-sum checksum. |
| **CommandLineInterface** | CommandLineInterface.h/cpp | Serial CLI with commands: `amp`, `freq`, `base`, `phase`, `wavetype`, `usecoco`, `high`, `low`, `highen`, `lowen`, `usbmode`, `save`, `load`, `clear`, `status`, `ip`, `help`. |
| **WebInterface** | WebInterface.h/cpp | Async web server (port 80) in AP mode. Embedded single-page HTML with Chart.js live waveform graph. JSON API (`/api/settings` GET/POST, `/api/save`, `/api/load`) and Server-Sent Events (`/events`) for real-time updates. Controls all parameters including USB mode and CoCo sensor toggle. |
| **TFTDisplay** | TFTDisplay.h/cpp | Renders status bar (mode indicator), scrolling waveform trace (cyan on black grid), and parameter readout (CO2, RR, alarm indicator) on the built-in 170x320 TFT at 10 Hz. |
| **Config** | Config.h | All compile-time constants: pin mappings, baud rates, WiFi credentials, Capnostat 5 protocol command IDs, SHDLC protocol constants (commands, error codes, timing). |

## Protocol Details

### Respironics Capnostat 5 (Serial1 + optional USB)

- **Baud:** 19200, 8N1
- **Waveform packets:** 100 Hz (every 10 ms) when in continuous mode
- **DPI (Data Packet Interface):** Appended to waveform packets every 1 s, cycling through CO2 status, ETCO2, respiratory rate, inspired CO2
- **Commands supported:** Start waveform (0x80), Stop (0xC9), Zero (0x82), Get/Set settings (0x84), Get revision (0xCA), Sensor capabilities (0xCB), Reset no-breath (0xCC)
- **Checksum:** 7-bit negative sum

### Sensirion CoCo SHDLC (Serial2)

- **Baud:** 115200, 8N1
- **Frame format:** `[0x7E] addr cmd len data... checksum [0x7E]` with byte stuffing (0x7E, 0x7D, 0x11, 0x13 escaped via XOR 0x20)
- **MISO frame** adds a state byte between cmd and len
- **Checksum:** Sum all frame bytes (between start/stop), take LSB, invert
- **Commands used:** Start measurement (0x00, sub 0x01), Stop (0x01), Read measurement (0x03, sub 0x00), Get product type (0xD0, sub 0x00), Get version (0xD1)
- **Measurement data:** Counter (4B) + CO2 partial pressure (2B, uint16, 0.1 mmHg) + Flow (2B) + Pressure (4B) + Temperature (2B)
- **Polling interval:** 100 ms
- **Error codes:** Success (0x00), Data size (0x01), Unknown cmd (0x02), Parameter (0x04), No data (0x20), Not allowed (0x43), Config (0x70), Fatal (0x7F). Bit 7 = device error flag.

## Connectivity

- **WiFi:** Access Point mode by default (SSID: `CO2-Emulator`, password: `emulator123`). Station mode configurable in Config.h.
- **Web UI:** `http://192.168.4.1` when connected to the AP. Real-time waveform chart, parameter sliders, toggle switches, save/load buttons.

## Build

```
Platform:  PlatformIO (espressif32)
Board:     lilygo-t-display-s3
Framework: Arduino
Libraries: ESPAsyncWebServer 3.4.5, ArduinoJson 6.21.x, TFT_eSPI 2.5.43
```

Build command: `pio run`

## Memory Usage (typical build)

- **RAM:** ~14% (46 KB / 328 KB)
- **Flash:** ~13% (845 KB / 6.5 MB)
