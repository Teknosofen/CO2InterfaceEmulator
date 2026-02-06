#ifndef CONFIG_H
#define CONFIG_H

// LilyGo T-Display S3 Configuration
// Serial Configuration
#define HOST_SERIAL Serial1      // Use Serial1 for protocol (GPIO43/44)
#define CMD_SERIAL Serial        // USB Serial for commands
#define BAUD_RATE_HOST 19200
#define BAUD_RATE_CMD 115200

// I2C Configuration (using default I2C pins for T-Display S3)
#define I2C_SDA 43
#define I2C_SCL 44
#define I2C_SENSOR_ADDR 0x48

// TFT Display pins (configured in platformio.ini build_flags)
#define TFT_ENABLED true

// WiFi Configuration - CHANGE THESE!
#define WIFI_AP_MODE true           // true = Access Point, false = Station
#define WIFI_AP_SSID "CO2-Emulator"
#define WIFI_AP_PASSWORD "emulator123"

// Station mode settings (if WIFI_AP_MODE = false)
#define WIFI_STA_SSID "YourSSID"
#define WIFI_STA_PASSWORD "YourPassword"

// Protocol Constants
namespace Protocol {
  const uint8_t CMD_CO2_WAVEFORM = 0x80;
  const uint8_t CMD_ZERO = 0x82;
  const uint8_t CMD_GET_SET_SETTINGS = 0x84;
  const uint8_t CMD_STOP_CONTINUOUS = 0xC9;
  const uint8_t CMD_GET_REVISION = 0xCA;
  const uint8_t CMD_SENSOR_CAPS = 0xCB;
  const uint8_t CMD_RESET_NO_BREATH = 0xCC;
  const uint8_t CMD_NACK = 0xC8;

  const uint8_t DPI_CO2_STATUS = 1;
  const uint8_t DPI_ETCO2 = 2;
  const uint8_t DPI_RESP_RATE = 3;
  const uint8_t DPI_INSP_CO2 = 4;
  const uint8_t DPI_BREATH_DETECTED = 5;
  
  const uint8_t NACK_INVALID_CMD = 1;
  const uint8_t NACK_CHECKSUM = 2;
  const uint8_t NACK_TIMEOUT = 3;
}

#endif // CONFIG_H
