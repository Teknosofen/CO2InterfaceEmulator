#ifndef CONFIG_H
#define CONFIG_H

// LilyGo T-Display S3 Configuration
// Serial Configuration
#define HOST_SERIAL Serial1      // Use Serial1 for protocol (GPIO43/44)
#define CMD_SERIAL Serial        // USB Serial for commands
#define BAUD_RATE_HOST 19200
#define BAUD_RATE_CMD 115200

// CoCo Sensor UART Configuration (Serial2)
#define COCO_SERIAL Serial2
#define COCO_TX_PIN 17
#define COCO_RX_PIN 18
#define COCO_BAUD_RATE 115200       // Default SHDLC baud rate (update per sensor spec)
#define COCO_SENSOR_ADDR 0x00       // Default SHDLC slave address

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

// SHDLC Protocol Constants (Sensirion CoCo sensor)
namespace SHDLC {
  const uint8_t FRAME_START = 0x7E;
  const uint8_t FRAME_STOP  = 0x7E;
  const uint8_t ESCAPE      = 0x7D;
  const uint8_t ESCAPE_XOR  = 0x20;

  // CoCo Commands
  const uint8_t CMD_START_MEASUREMENT = 0x00;
  const uint8_t CMD_STOP_MEASUREMENT  = 0x01;
  const uint8_t CMD_READ_MEASUREMENT  = 0x03;
  const uint8_t CMD_READ_BUFFERED     = 0x04;
  const uint8_t CMD_GET_SET_BAUDRATE  = 0x91;
  const uint8_t CMD_GET_FW_BUILD      = 0x9F;
  const uint8_t CMD_DEVICE_INFO       = 0xD0;
  const uint8_t CMD_GET_VERSION       = 0xD1;

  // Subcommands
  const uint8_t SUB_START_PERIODIC    = 0x01;
  const uint8_t SUB_READ_MEAS_VALUES  = 0x00;
  const uint8_t SUB_READ_BUFFERED     = 0x00;
  const uint8_t SUB_GET_PRODUCT_TYPE  = 0x00;

  // MISO State byte error codes (lower 7 bits; bit 7 = device error flag)
  const uint8_t ERR_SUCCESS           = 0x00;
  const uint8_t ERR_DATA_SIZE         = 0x01;
  const uint8_t ERR_UNKNOWN_CMD       = 0x02;
  const uint8_t ERR_PARAMETER         = 0x04;
  const uint8_t ERR_NO_DATA           = 0x20;
  const uint8_t ERR_CMD_NOT_ALLOWED   = 0x43;
  const uint8_t ERR_CONFIGURATION     = 0x70;
  const uint8_t ERR_FATAL             = 0x7F;

  // Timing
  const uint32_t RESPONSE_TIMEOUT_MS  = 200;
  const uint32_t POLL_INTERVAL_MS     = 100;
}

#endif // CONFIG_H
