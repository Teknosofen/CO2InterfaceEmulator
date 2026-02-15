# CO2 Interface Emulator - Project & Design Description

## Purpose

This firmware emulates the **Respironics Capnostat 5** CO2 sensor interface, allowing a host device (patient monitor, PC test software, etc.) to receive CO2 waveform data and parameter packets as if a real Capnostat 5 sensor were connected.

The CO2 data source is selectable:
- **Internal waveform generator** producing sine or realistic capnogram waveforms with user-adjustable parameters (amplitude, frequency, baseline).
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
- **PROTOCOL mode**: Mirrors the Respironics protocol output from Serial1, enabling PC test software to verify emulator behavior. Switching to protocol mode auto-starts continuous streaming.

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
| **ConfigStorage** | ConfigStorage.h/cpp | Saves/loads waveform settings to ESP32 NVS (non-volatile storage) using the Preferences library. |
| **ProtocolHandler** | ProtocolHandler.h/cpp | Implements the Capnostat 5 serial protocol. Handles incoming commands (start/stop waveform, zero cal, get/set settings, revision, capabilities). Builds and sends waveform + DPI response packets. Supports multiple simultaneous output streams. |
| **ProtocolReceiver** | ProtocolReceiver.h/cpp | Receives and reassembles incoming serial packets (start byte detection, NBF-based framing, 500 ms timeout). Passes complete packets to ProtocolHandler. |
| **PacketBuilder** | PacketBuilder.h/cpp | Constructs protocol packets byte-by-byte. Handles CO2 waveform encoding `(CO2 * 100 + 1000)` as 2-byte value. Calculates 7-bit negative-sum checksum. |
| **CommandLineInterface** | CommandLineInterface.h/cpp | Serial CLI with commands: `amp`, `freq`, `base`, `wavetype`, `usecoco`, `usbmode`, `save`, `load`, `clear`, `status`, `ip`, `help`. |
| **WebInterface** | WebInterface.h/cpp | Async web server (port 80) in AP mode. Embedded single-page HTML with canvas-based live waveform graph. JSON API (`/api/settings` GET/POST, `/api/save`, `/api/load`) and Server-Sent Events (`/events`) for real-time updates at 10 Hz. Controls all parameters including USB mode, streaming toggle, and CoCo sensor selection. |
| **TFTDisplay** | TFTDisplay.h/cpp | Landscape 320x170 layout with status bar (mode badges), sweep-style waveform trace (2px thick, dark green on blue-grey), and parameter panel (CO2 value, respiratory rate). Custom color palette. Updates at 10 Hz with dirty-checking to minimize redraws. |
| **Config** | Config.h | All compile-time constants: pin mappings, baud rates, WiFi credentials, Capnostat 5 protocol command IDs, SHDLC protocol constants (commands, error codes, timing). |

---

## Respironics Capnostat 5 Protocol (Emulator to Host)

### Physical Layer

- **Serial:** 19200 baud, 8N1
- **Port:** Serial1 (GPIO 43 TX, GPIO 44 RX), optionally mirrored on USB

### Packet Format

All packets use a simple binary format with **no start/stop delimiters**. The first byte (command) always has bit 7 set (`>= 0x80`), all subsequent bytes have bit 7 clear (`< 0x80`).

```
[ CMD ] [ NBF ] [ data bytes... ] [ CHK ]
  1B      1B       0..N bytes       1B
```

| Field | Description |
|-------|-------------|
| **CMD** | Command byte (bit 7 always set, `>= 0x80`) |
| **NBF** | Number of bytes following CMD (includes data + checksum) |
| **Data** | 0 or more payload bytes (all `< 0x80`) |
| **CHK** | Checksum: `(-sum_of_all_preceding_bytes) & 0x7F` |

### Checksum Calculation

The checksum is the 7-bit two's complement of the sum of all bytes in the packet (CMD + NBF + all data bytes). On reception, summing all bytes including the checksum should yield 0 (mod 128).

```
CHK = (-sum(CMD, NBF, data...)) & 0x7F
```

### Two-Byte Value Encoding

16-bit values are encoded as two 7-bit bytes (MSB first):
```
Byte1 = (value >> 7) & 0x7F    (upper 7 bits)
Byte2 = value & 0x7F           (lower 7 bits)
```
Decode: `value = Byte1 * 128 + Byte2`

### CO2 Waveform Encoding

CO2 values (in mmHg) are encoded as: `encoded = (CO2_mmHg * 100) + 1000`, then transmitted as a 2-byte value.

### Receiver Framing (ProtocolReceiver)

The receiver uses the MSB of the first byte to detect packet start:
1. Wait for a byte with bit 7 set (`>= 0x80`) -> this is CMD, start of packet.
2. Next byte is NBF (number of following bytes).
3. Read NBF more bytes (data + checksum).
4. Pass complete packet to ProtocolHandler for checksum validation and processing.
5. **Timeout:** If 500 ms elapses between bytes mid-packet, the receiver resets and sends a NACK(timeout).

### Commands

#### Host -> Emulator (Incoming)

| CMD | Name | Payload | Description |
|-----|------|---------|-------------|
| `0x80` | Start Waveform | sync(1B) | Start continuous 100 Hz waveform mode |
| `0xC9` | Stop Continuous | - | Stop waveform streaming |
| `0x82` | Zero Calibration | - | Initiate zero calibration (5s simulated) |
| `0x84` | Get/Set Settings | ISB(1B) [data...] | Read or write device settings (see ISB table) |
| `0xCA` | Get Revision | format(1B) | Request firmware revision string |
| `0xCB` | Sensor Capabilities | SCI(1B) [SCB(1B)] | Query or set sensor capabilities |
| `0xCC` | Reset No-Breath | - | Clear the no-breath status flag |

#### Emulator -> Host (Outgoing)

| CMD | Name | Payload | Description |
|-----|------|---------|-------------|
| `0x80` | Waveform Packet | sync(1B) co2(2B) [DPI...] | CO2 waveform sample, optionally with DPI data appended |
| `0xC8` | NACK | error_code(1B) | Negative acknowledge (1=invalid cmd, 2=checksum, 3=timeout) |
| `0x82` | Zero Response | status(1B) | 0=started, 1=compensations not set, 2=already in progress |
| `0x84` | Settings Response | ISB(1B) data... | Current setting values |
| `0xCA` | Revision Response | format(1B) string... | Firmware revision string |
| `0xCB` | Capabilities Response | SCI(1B) value(1B) | Capability value |
| `0xC9` | Stop Ack | - | Confirms streaming stopped |
| `0xCC` | Reset No-Breath Ack | - | Confirms status cleared |

### Waveform Packet Structure (0x80)

Sent at 100 Hz during continuous mode:

```
[ 0x80 ] [ NBF ] [ sync ] [ CO2_hi ] [ CO2_lo ] [ DPI_type ] [ DPI_data... ] [ CHK ]
```

- **sync:** Rolling counter 0x00..0x7F, increments each packet
- **CO2_hi, CO2_lo:** Encoded CO2 value (see encoding above)
- **DPI (optional):** Appended every 1 second, cycling through 4 types:

| DPI Type | ID | Payload | Description |
|----------|----|---------|-------------|
| CO2 Status | 1 | status1(1B) status2(1B) status3(1B) 0 0 | Device status flags |
| ETCO2 | 2 | value(2B) | End-tidal CO2 (0.1 mmHg units, 2-byte encoded) |
| Resp Rate | 3 | value(2B) | Respiratory rate (breaths/min, 2-byte encoded) |
| Inspired CO2 | 4 | value(2B) | Inspired CO2 level (2-byte encoded) |

### Settings ISB (Index Select Byte) Table

| ISB | Setting | Data Format | Description |
|-----|---------|-------------|-------------|
| 1 | Barometric Pressure | 2-byte value | Ambient pressure compensation |
| 4 | Gas Temperature | 2-byte value | Gas sampling temperature |
| 5 | ETCO2 Time Period | 1 byte | ETCO2 averaging window |
| 6 | No-Breath Timeout | 1 byte | Seconds before no-breath alarm |
| 7 | CO2 Units | 1 byte | 0=mmHg, 1=kPa, 2=% |
| 11 | Gas Compensations | O2(1B) balance(1B) anesthetic(2B) | Gas mixture settings |
| 18 | Serial Number | 10-char string | Read-only sensor serial number |
| 19 | Sensor Type | 1 byte | Read-only, returns 0x01 |

---

## Sensirion CoCo SHDLC Protocol (Emulator to Sensor)

### Physical Layer

- **Serial:** 115200 baud, 8N1
- **Port:** Serial2 (GPIO 17 TX, GPIO 18 RX)
- **Role:** Emulator acts as SHDLC master; CoCo sensor is the slave.

### SHDLC Frame Format

All communication uses SHDLC (Sensirion HDLC) frames delimited by `0x7E` start and stop bytes.

#### MOSI Frame (Master -> Slave)

```
[ 0x7E ] [ ADDR ] [ CMD ] [ LEN ] [ DATA... ] [ CHK ] [ 0x7E ]
  start    slave    cmd    data     payload     chk     stop
           addr            length
```

#### MISO Frame (Slave -> Master)

```
[ 0x7E ] [ ADDR ] [ CMD ] [ STATE ] [ LEN ] [ DATA... ] [ CHK ] [ 0x7E ]
  start    slave    cmd    status    data     payload     chk     stop
           addr             byte     length
```

The MISO frame has an additional **STATE** byte between CMD and LEN.

### Byte Stuffing

All bytes between start and stop delimiters are subject to byte stuffing. The following bytes must be escaped:

| Original Byte | Escaped Sequence | Purpose |
|---------------|-----------------|---------|
| `0x7E` | `0x7D 0x5E` | Frame delimiter |
| `0x7D` | `0x7D 0x5D` | Escape character itself |
| `0x11` | `0x7D 0x31` | XON (flow control) |
| `0x13` | `0x7D 0x33` | XOFF (flow control) |

**Escaping rule:** Replace the byte with `0x7D` followed by `(original_byte XOR 0x20)`.

**Unstuffing:** When `0x7D` is received, take the next byte and XOR it with `0x20`.

### Checksum Calculation

The checksum covers all unstuffed bytes between (but not including) the start and stop delimiters, excluding the checksum byte itself:

**MOSI:** checksum input = `ADDR + CMD + LEN + DATA...`
**MISO:** checksum input = `ADDR + CMD + STATE + LEN + DATA...`

```
CHK = ~(sum of all input bytes)     // bitwise NOT of the byte sum (LSB only)
```

The checksum byte itself is also byte-stuffed when transmitted.

### STATE Byte (MISO only)

| Bit | Meaning |
|-----|---------|
| 6:0 | Execution error code |
| 7 | Device error flag (sensor-level hardware error) |

#### Error Codes (bits 6:0)

| Code | Name | Description |
|------|------|-------------|
| `0x00` | Success | Command executed successfully |
| `0x01` | Data Size | Wrong data size for command |
| `0x02` | Unknown Command | Command not recognized |
| `0x04` | Parameter Error | Invalid parameter value |
| `0x20` | No Data | No measurement data available yet |
| `0x43` | Not Allowed | Command not allowed in current state |
| `0x70` | Configuration | Configuration error |
| `0x7F` | Fatal | Fatal device error |

### Commands Used

| CMD | Name | MOSI Data | MISO Data | Description |
|-----|------|-----------|-----------|-------------|
| `0x00` | Start Measurement | subcommand `0x01` (periodic) | - | Start periodic CO2 measurement |
| `0x01` | Stop Measurement | - | - | Stop measurement |
| `0x03` | Read Measurement | subcommand `0x00` | counter(4B) CO2(2B) flow(2B) pressure(4B) temp(2B) | Read latest measurement values |
| `0xD0` | Device Info | subcommand `0x00` (product type) | ASCII string (null-terminated) | Get product type string |
| `0xD1` | Get Version | - | fw_major(1B) fw_minor(1B) fw_debug(1B) hw_major(1B) hw_minor(1B) proto(2B) | Get firmware/hardware version |

### Measurement Data Format (CMD 0x03 Response)

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0 | 4 | uint32, BE | Measurement counter |
| 4 | 2 | uint16, BE | CO2 partial pressure (0.1 mmHg units). `0xFFFF` = invalid |
| 6 | 2 | uint16, BE | Gas flow |
| 8 | 4 | uint32, BE | Barometric pressure |
| 12 | 2 | uint16, BE | Temperature |

The emulator reads only the CO2 field (offset 4-5) and converts: `CO2_mmHg = raw_value / 10.0`

### Transaction Flow

1. Master builds MOSI frame (with byte stuffing and checksum)
2. Master sends frame via UART
3. Master waits for MISO response (200 ms timeout)
4. Master receives and unstuffs MISO frame
5. Master validates checksum and checks that response CMD matches request CMD
6. Master checks STATE byte for errors

### Polling

- Measurement values are polled every **100 ms** via `readMeasurementValues()`
- On startup, `begin()` probes the sensor with `getProductType()` and `getVersion()`
- If the sensor is not found, the emulator falls back to simulation mode

---

## TFT Display Layout

Landscape mode, 320 x 170 pixels, custom color palette on blue-grey background.

```
+--[ CO2 EMULATOR ]------[DEBUG]--[IDLE]-+   <- Status bar (26px, dark blue)
|                         |               |
|  50                     |  CO2          |   <- Waveform area (230x144)
|  ........................| 38.0          |      with 0-50 mmHg scale
|  ........../\...........| mmHg          |      Dotted grid at 10,20,30,40
|  ........./  \..........| RR            |   <- Parameter panel (88x144)
|  ......../    \.........| 15 bpm        |      CO2 value (large, green)
|  ......./      \........|               |      Respiratory rate (blue)
|  ....../        \.......|               |
|  0                      |               |
+-----------------------------------------+
```

### Color Palette (RGB565)

| Name | Value | Use |
|------|-------|-----|
| CLR_BACKGROUND | `0x85BA` | General background (blue-grey) |
| CLR_DEEPBLUE | `0x1A6F` | Status bar, message boxes |
| CLR_DARKERBLUE | `0x3A97` | Borders, separators |
| CLR_SLATEBLUE | `0x2B4F` | Labels, scale text |
| CLR_MIDNIGHTBLUE | `0x1028` | Grid dots |
| CLR_LOGOBLUE | `0x5497` | Respiratory rate value |
| CLR_GREENISH | `0x2444` | Waveform trace, CO2 value |
| CLR_REDDISH | `0xA4B2` | IDLE badge |

## Serial CLI Commands

The debug CLI is available on the USB serial port (115200 baud) when in DEBUG mode. Commands are case-insensitive, terminated by newline. The CLI is unavailable when USB is in PROTOCOL mode — use the web interface instead.

### Waveform Control

| Command | Arguments | Description |
|---------|-----------|-------------|
| `amp <value>` | mmHg (float) | Set CO2 waveform amplitude (peak EtCO2 value). Default: 38.0 mmHg |
| `freq <value>` | br/min (5–90) | Set respiratory rate in breaths per minute. Internally stored as Hz (value / 60). Default: 15 br/min (0.25 Hz) |
| `base <value>` | mmHg (float) | Set inspiratory CO2 baseline. Default: 0.0 mmHg |
| `wavetype <n>` | 0 or 1 | Select waveform shape. 0 = sine wave, 1 = realistic capnogram with smoothstep transitions |

### Source Selection

| Command | Arguments | Description |
|---------|-----------|-------------|
| `usecoco <n>` | 0 or 1 | Enable (1) or disable (0) the Sensirion CoCo sensor as CO2 source. Falls back to simulation if sensor is not connected |

### USB Mode

| Command | Arguments | Description |
|---------|-----------|-------------|
| `usbmode <n>` | 0 or 1 | Switch USB port function. 0 = DEBUG (CLI available), 1 = PROTOCOL (USB mirrors Serial1 Respironics output, CLI becomes unavailable, streaming auto-starts) |

### Configuration Persistence

| Command | Arguments | Description |
|---------|-----------|-------------|
| `save` | - | Save current waveform settings (amplitude, frequency, baseline, waveform type, CoCo enable) to ESP32 NVS (non-volatile storage) |
| `load` | - | Load saved settings from NVS and apply them. Prints updated status |
| `clear` | - | Erase saved configuration from NVS, restoring factory defaults on next boot |

### Information

| Command | Arguments | Description |
|---------|-----------|-------------|
| `status` | - | Display all current settings: waveform parameters (amplitude, resp rate in br/min, baseline), waveform type, CO2 source, device mode (CONTINUOUS/IDLE), initialization state, USB mode |
| `ip` | - | Show WiFi connection info. In AP mode: SSID, password, and IP (`WiFi.softAPIP()`). In STA mode: SSID and IP (`WiFi.localIP()`) |
| `help` | - | Print command summary |

---

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
- **Flash:** ~13% (854 KB / 6.5 MB)
