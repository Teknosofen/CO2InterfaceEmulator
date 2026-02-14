# CO2 Interface Emulator

[![PlatformIO CI](https://img.shields.io/badge/PlatformIO-passing-brightgreen)](https://platformio.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![ESP32](https://img.shields.io/badge/ESP32-S3-blue)](https://www.espressif.com/en/products/socs/esp32-s3)

Full-featured CO2 sensor emulator implementing the **Capnostat 5** serial protocol for ESP32-S3, with built-in TFT display, web interface, and EEPROM storage.

## Features

- **Real-time Waveform Generation** - Sine wave or realistic capnogram simulation (amplitude, frequency, baseline)
- **Built-in TFT Display** - Live sweep-style waveform visualization on LilyGo T-Display S3
- **Web Interface** - Full control via browser (WiFi AP mode, no internet needed)
- **EEPROM Storage** - Save/load configurations persistently
- **CoCo Sensor Support** - Sensirion CoCo CO2 sensor integration via SHDLC/UART
- **Capnostat 5 Protocol** - Full implementation at 19200 baud, 100Hz waveform transmission
- **Serial CLI** - ASCII command interface for configuration
- **USB Dual-Mode** - Debug CLI or protocol mirror, switchable at runtime

## Use Cases

- Medical device development and testing
- Capnostat 5 protocol validation
- CO2 monitoring system development
- Educational demonstrations
- Protocol analyzer testing

## Hardware Requirements

### Supported Boards
- **LilyGo T-Display S3** (recommended, includes display)

### Optional
- Sensirion CoCo CO2 sensor (SHDLC/UART, connected via Serial2)
- External host device for protocol communication

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/Teknosofen/CO2InterfaceEmulator.git
cd CO2InterfaceEmulator
```

### 2. Install PlatformIO

```bash
# VS Code: Install PlatformIO IDE extension
# Or CLI:
pip install platformio
```

### 3. Configure WiFi (Optional)

Edit `include/Config.h`:

```cpp
// Access Point mode (default - no internet needed)
#define WIFI_AP_MODE true
#define WIFI_AP_SSID "CO2-Emulator"
#define WIFI_AP_PASSWORD "emulator123"

// Or connect to existing WiFi
#define WIFI_AP_MODE false
#define WIFI_STA_SSID "YourWiFiSSID"
#define WIFI_STA_PASSWORD "YourPassword"
```

### 4. Build & Upload

```bash
pio run -t upload
pio device monitor
```

### 5. Access

**TFT Display**: Built-in screen shows waveform immediately

**Web Interface**:
- AP Mode: Connect to "CO2-Emulator" WiFi, open http://192.168.4.1
- Station Mode: Check serial monitor for IP address

**Serial CLI**: Connect at 115200 baud, type `help`

## TFT Display

The built-in display shows (landscape, 320x170):
- Sweep-style CO2 waveform trace (0-50 mmHg scale)
- Current CO2 value (mmHg)
- Respiratory rate (breaths/min)
- Mode badges (RUN/IDLE, DEBUG/PROTO)

## Web Interface

Access full control panel via browser:

**Features**:
- Live waveform visualization (canvas-based)
- Interactive parameter sliders (amplitude, frequency, baseline)
- Waveform type selection (sine / capnogram)
- CoCo sensor toggle
- USB mode switching (debug / protocol mirror)
- Streaming start/stop control
- Save/load settings to EEPROM
- No internet required (all assets embedded)

## Serial Commands

```
amp <value>      - Set amplitude (mmHg)
freq <value>     - Set frequency (Hz)
base <value>     - Set baseline (mmHg)
wavetype <0/1>   - Set waveform type (0=sine, 1=capnogram)
usecoco <0/1>    - Enable/disable CoCo sensor
usbmode <0/1>    - Set USB mode (0=debug, 1=protocol)
save             - Save config to EEPROM
load             - Load config from EEPROM
clear            - Clear saved config
status           - Show current settings
ip               - Show IP address
help             - Show all commands
```

## Protocol Implementation

Implements **Capnostat 5** serial protocol:
- **Baud Rate**: 19200, 8N1
- **Waveform Rate**: 100 Hz continuous
- **Commands**: Start/stop waveform, zero calibration, get/set settings, revision, capabilities
- **Data Parameters**: ETCO2, respiratory rate, inspired CO2, status
- **Packet format**: CMD(1B) + NBF(1B) + data + 7-bit checksum

See [ProjectDesign.md](Documentation/ProjectDesign.md) for complete protocol specification including the Sensirion SHDLC interface.

## Hardware Connections

### LilyGo T-Display S3

```
Protocol Serial (Serial1):    19200 baud
  TX: GPIO 43
  RX: GPIO 44

CoCo Sensor (Serial2):        115200 baud
  TX: GPIO 17
  RX: GPIO 18

USB Serial (Commands):
  Built-in USB CDC             115200 baud

TFT Display:
  Built-in ST7789 (170x320)
```

## Project Structure

```
CO2InterfaceEmulator/
+-- platformio.ini              # Build configuration
+-- README.md                   # This file
+-- Documentation/
|   +-- ProjectDesign.md        # Architecture & protocol specification
+-- include/                    # Header files
|   +-- Config.h                # Pin mappings, baud rates, protocol constants
|   +-- CO2Emulator.h           # Main application orchestrator
|   +-- WaveformGenerator.h     # Waveform generation (sine/capnogram/sensor)
|   +-- ShdlcSensorInterface.h  # Sensirion CoCo SHDLC driver
|   +-- DeviceState.h           # Device state management
|   +-- ConfigStorage.h         # EEPROM persistence
|   +-- ProtocolHandler.h       # Capnostat 5 protocol handler
|   +-- ProtocolReceiver.h      # Serial packet receiver/framer
|   +-- PacketBuilder.h         # Packet construction + checksum
|   +-- CommandLineInterface.h  # Serial CLI
|   +-- WebInterface.h          # Web server + embedded HTML
|   +-- TFTDisplay.h            # TFT display driver
+-- src/                        # Implementation files
|   +-- main.cpp                # Entry point
|   +-- CO2Emulator.cpp
|   +-- WaveformGenerator.cpp
|   +-- ShdlcSensorInterface.cpp
|   +-- DeviceState.cpp
|   +-- ConfigStorage.cpp
|   +-- ProtocolHandler.cpp
|   +-- ProtocolReceiver.cpp
|   +-- PacketBuilder.cpp
|   +-- CommandLineInterface.cpp
|   +-- WebInterface.cpp
|   +-- TFTDisplay.cpp
```

## Customization

### Change Default Waveform

Edit `src/WaveformGenerator.cpp`:

```cpp
WaveformGenerator::WaveformGenerator()
  : amplitude(38.0),    // EtCO2 peak (mmHg)
    frequency(0.25),    // Breath rate (Hz, 0.25 = 15 bpm)
    baseline(0.0),      // Inspiratory CO2 baseline
    ...
```

### Modify Display Colors

Edit `include/TFTDisplay.h` color palette defines (`CLR_GREENISH`, etc.)

### Add Custom Protocol Commands

1. Add command constant to `include/Config.h` (Protocol namespace)
2. Handle in `src/ProtocolHandler.cpp` (`processCommand` switch)

## Troubleshooting

**Display stays black**
- Check TFT_eSPI library installed
- Verify build_flags in platformio.ini
- Press reset button after upload

**Web interface not loading**
- Check serial monitor for IP address
- Try http:// not https://
- Verify WiFi credentials in Config.h

**Compilation errors**
- Clean build: `pio run -t clean`
- Update PlatformIO: `pio upgrade`

**Protocol not responding**
- Check baud rate (19200)
- Verify TX/RX connections (GPIO 43/44)
- Use `usbmode 1` to mirror protocol on USB for debugging

## Acknowledgments

- Based on Respironics Capnostat 5 protocol specification
- Built with [PlatformIO](https://platformio.org/)
- Display powered by [TFT_eSPI](https://github.com/Bodmer/TFT_eSPI)
- Web server using [ESPAsyncWebServer](https://github.com/mathieucarbou/ESPAsyncWebServer)

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

---

**Project**: [Teknosofen/CO2InterfaceEmulator](https://github.com/Teknosofen/CO2InterfaceEmulator)
