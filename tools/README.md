# PC Tools

## `co2_monitor.py`

A small PC application that connects to the CO2 Interface Emulator over a
serial port, decodes the Respironics Capnostat 5 protocol stream, shows a
live scrolling CO2 waveform plus ETCO2 / Respiratory Rate / Inspired CO2 /
Status, and (optionally) logs every sample to a CSV file.

### Install

```powershell
pip install pyserial matplotlib
```

### Run

```powershell
python tools/co2_monitor.py
```

### Use

1. Pick the COM port the emulator is on, then click **Connect**.
   - Use **19200 baud** for the dedicated Serial1 output.
   - Use **115200 baud** for the USB port when the emulator's `usbmode` is
     set to `PROTOCOL`.
   - Opening the port does *not* toggle DTR/RTS, so connecting over USB
     will not reset the ESP32-S3.
2. The emulator only streams when the host asks. Click **Send Start** to
   transmit a `Start Waveform` (`0x80`) command. Click **Send Stop** to
   transmit `Stop Continuous` (`0xC9`).
3. Click **Browse...** to choose where to save the CSV file (path and file
   name are both selectable), then click **Start logging** to begin
   saving samples. Click **Stop logging** to close the file.

### What the GUI shows

- **Live graph** — 10 s rolling window of the CO2 waveform, auto-scaling Y.
- **Numeric readouts** — current CO2, ETCO2, RR, InspCO2 (DPI fields stay
  populated with the most recent reported value until the next update).
- **Latest received packet** panel:
  - `sync` — rolling sync byte from the emulator
  - `raw CO2` — the raw 14-bit transmitted word and the decoded mmHg
    value (`(raw - 1000) / 100`)
  - `hex` — the full bytes of the most recent waveform packet
- **Status bar** — live byte count, byte rate, packets ok / bad. Useful to
  diagnose connection issues at a glance.

### Diagnosing "no data" / "all zeros"

Watch the status bar after **Connect** and after **Send Start**:

| Status bar shows                         | Likely cause |
|------------------------------------------|--------------|
| `Rx 0 B (0 B/s)` always                  | Wrong port, wrong baud, wires swapped, or (on USB) `usbmode` is `DEBUG` instead of `PROTOCOL`. |
| Bytes climbing, `packets ok=0, bad>0`    | Wrong baud or inverted TX/RX. |
| `packets ok` climbing, raw CO2 == `1000` | Stream is fine but emulator is encoding 0 mmHg — set `amp`, `freq`, `wavetype` via the emulator CLI / web UI, and make sure CoCo sensor mode is off if no sensor is attached. |
| `packets ok` climbing, raw CO2 == `0`    | Encoded value clamped at 0 — same root cause as above. |

### CSV format

Columns: `pc_time_iso, pc_time_s, sync, co2_mmHg, etco2_mmHg,
resp_rate_bpm, insp_co2_mmHg, status1, status2, status3`.

DPI-derived columns (ETCO2, RR, InspCO2, status*) hold the most recent
reported value and stay populated until the next update arrives.
