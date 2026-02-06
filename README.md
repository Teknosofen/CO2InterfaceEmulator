# CO2 Interface Emulator

[![PlatformIO CI](https://img.shields.io/badge/PlatformIO-passing-brightgreen)](https://platformio.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![ESP32](https://img.shields.io/badge/ESP32-S3-blue)](https://www.espressif.com/en/products/socs/esp32-s3)

Full-featured CO2 sensor emulator implementing the **Capnostat 5** serial protocol for ESP32, with built-in TFT display, web interface, and EEPROM storage.

![CO2 Emulator Display](docs/images/display-preview.jpg)

## ✨ Features

- 🌊 **Real-time Waveform Generation** - Adjustable sine wave simulation (amplitude, frequency, baseline, phase)
- 📺 **Built-in TFT Display** - Live waveform visualization on LilyGo T-Display S3
- 🌐 **Web Interface** - Control via browser (works as WiFi AP, no internet needed)
- 💾 **EEPROM Storage** - Save/load configurations
- 🚨 **Alarm System** - Configurable high/low thresholds with visual indicators
- 🔌 **I2C Sensor Support** - Template for real CO2 sensor integration
- 📡 **Capnostat 5 Protocol** - Full implementation at 19200 baud, 100Hz waveform transmission
- 💬 **Serial CLI** - ASCII command interface for configuration

## 🎯 Use Cases

- Medical device development and testing
- Capnostat 5 protocol validation
- CO2 monitoring system development
- Educational demonstrations
- Protocol analyzer testing

## 🛠️ Hardware Requirements

### Supported Boards
- **LilyGo T-Display S3** (recommended, includes display)
- Generic ESP32-S3
- ESP32 DevKit (modify pins in Config.h)

### Optional
- I2C CO2 Sensor (SCD30, SCD41, etc.)
- External host device for protocol communication

## 📋 Quick Start

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

Edit `src/Config.h`:

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
- AP Mode: Connect to "CO2-Emulator" WiFi → http://192.168.4.1
- Station Mode: Check serial monitor for IP address

**Serial CLI**: Connect at 115200 baud, type `help`

## 📺 TFT Display

The built-in display shows:
- Real-time CO2 waveform (cyan trace)
- Current CO2 value (mmHg)
- Respiratory rate (breaths/min)
- Mode indicator (RUN/IDLE)
- Alarm status (red indicator)

![Display Layout](docs/images/display-layout.png)

## 🌐 Web Interface

Access full control panel via browser:

![Web Interface](docs/images/web-interface.png)

**Features**:
- Live waveform visualization
- Interactive parameter sliders
- Alarm configuration
- Save/load settings to EEPROM
- No internet required (all assets embedded)

## 💻 Serial Commands

```
status          - Show current settings
amp <value>     - Set amplitude (mmHg)
freq <value>    - Set frequency (Hz)
base <value>    - Set baseline (mmHg)
phase <value>   - Set phase (degrees)
high <value>    - Set high alarm threshold
low <value>     - Set low alarm threshold
highen <0/1>    - Enable/disable high alarm
lowen <0/1>     - Enable/disable low alarm
usei2c <0/1>    - Enable/disable I2C sensor
save            - Save config to EEPROM
load            - Load config from EEPROM
ip              - Show IP address
help            - Show all commands
```

## 📡 Protocol Implementation

Implements **Capnostat 5** serial protocol:
- **Baud Rate**: 19200, 8N1
- **Waveform Rate**: 100 Hz
- **Commands**: Waveform mode, Zero, Settings, Revision, Capabilities
- **Data Parameters**: ETCO2, Respiratory Rate, Inspired CO2, Status
- **Checksums**: Full error detection

### Example Protocol Exchange

```
Host → Device: 0x80 0x02 0x00 0x7E  (Start waveform mode)
Device → Host: 0x80 0x05 0x00 0xXX 0xXX 0xXX  (Waveform packets at 100Hz)
```

See [PROTOCOL.md](docs/PROTOCOL.md) for complete specification.

## 🔌 Hardware Connections

### LilyGo T-Display S3

```
Protocol Serial (Serial1):
├── TX: GPIO 43
└── RX: GPIO 44

USB Serial (Commands):
└── Built-in USB CDC

TFT Display:
└── Built-in ST7789 (170x320)

Optional I2C Sensor:
├── SDA: GPIO 18 (change from GPIO 43 to avoid conflict)
└── SCL: GPIO 17 (change from GPIO 44 to avoid conflict)
```

### Generic ESP32

Edit `src/Config.h` to match your pins:

```cpp
#define HOST_SERIAL Serial1
#define I2C_SDA 21
#define I2C_SCL 22
```

## 🧪 I2C Sensor Integration

The project includes a template for real I2C CO2 sensors. To integrate your sensor:

1. Edit `src/I2CSensorInterface.cpp`
2. Modify `readSensorData()` method for your sensor protocol
3. Example for SCD30:

```cpp
bool I2CSensorInterface::readSensorData(float& co2Value) {
  Wire.beginTransmission(address);
  Wire.write(0x02); Wire.write(0x02);  // Read measurement command
  if (Wire.endTransmission() != 0) return false;
  
  delay(3);
  
  if (Wire.requestFrom(address, (uint8_t)18) != 18) return false;
  
  uint32_t co2Raw = (Wire.read() << 24) | (Wire.read() << 16) | 
                    (Wire.read() << 8) | Wire.read();
  memcpy(&co2Value, &co2Raw, 4);
  
  return true;
}
```

4. Enable via serial: `usei2c 1`
5. Or via web interface: Check "Use I2C Sensor"

## 📁 Project Structure

```
CO2InterfaceEmulator/
├── platformio.ini              # Build configuration
├── README.md                   # This file
├── LICENSE                     # MIT License
├── docs/                       # Documentation
│   ├── PROTOCOL.md            # Protocol specification
│   ├── T-DISPLAY-S3.md        # Hardware guide
│   └── images/                # Screenshots & diagrams
└── src/                        # Source code
    ├── main.cpp               # Entry point
    ├── Config.h               # Configuration
    ├── PacketBuilder.*        # Protocol packet builder
    ├── I2CSensorInterface.*   # I2C sensor template
    ├── ConfigStorage.*        # EEPROM persistence
    ├── WaveformGenerator.*    # Waveform generation
    ├── AlarmManager.*         # Alarm handling
    ├── DeviceState.*          # Device state management
    ├── ProtocolHandler.*      # Protocol command handler
    ├── CommandLineInterface.* # Serial CLI
    ├── ProtocolReceiver.*     # Serial packet receiver
    ├── WebInterface.*         # Web UI (embedded HTML)
    ├── TFTDisplay.*           # TFT display driver
    └── CO2Emulator.*          # Main application
```

## 🎨 Customization

### Change Default Waveform

Edit `src/WaveformGenerator.cpp`:

```cpp
WaveformGenerator::WaveformGenerator() 
  : amplitude(45.0),    // Your value
    frequency(0.3),     // Your value
    baseline(5.0),      // Your value
    phase(0.0) {}
```

### Modify Display Colors

Edit `src/TFTDisplay.cpp`:

```cpp
tft.drawLine(i-1, y1, i, y2, TFT_GREEN);  // Change waveform color
```

### Add Custom Protocol Commands

1. Add command to `src/Config.h`
2. Handle in `src/ProtocolHandler.cpp`

## 🐛 Troubleshooting

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
- Check all files present (see docs/FILE_CHECKLIST.md)

**Protocol not responding**
- Check baud rate (19200)
- Verify TX/RX connections
- Send test command: `0x80 0x02 0x00 0x7E`

## 📚 Documentation

- [Protocol Specification](docs/PROTOCOL.md)
- [Hardware Setup Guide](docs/T-DISPLAY-S3.md)
- [File Structure](docs/FILE_CHECKLIST.md)
- [Contributing Guidelines](CONTRIBUTING.md)

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Based on Respironics Capnostat 5 protocol specification
- Built with [PlatformIO](https://platformio.org/)
- Display powered by [TFT_eSPI](https://github.com/Bodmer/TFT_eSPI)
- Web server using [ESPAsyncWebServer](https://github.com/mathieucarbou/ESPAsyncWebServer)

## 📧 Contact

**Project**: [Teknosofen/CO2InterfaceEmulator](https://github.com/Teknosofen/CO2InterfaceEmulator)

**Issues**: [GitHub Issues](https://github.com/Teknosofen/CO2InterfaceEmulator/issues)

---

**Built with ❤️ for medical device development**
