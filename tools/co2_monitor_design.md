# CO2 Monitor – Design Document

`tools/co2_monitor.py` is a desktop Tk + matplotlib utility for receiving,
visualizing and logging the Respironics Capnostat 5 protocol stream from one
or two CO2 sources connected over serial. It also acts as a manual host: it
can send the standard `Start Waveform` (0x80) and `Stop Continuous` (0xC9)
commands and shows decoded waveform plus DPI side-channel values (ETCO2,
Respiratory Rate, Inspired CO2, Status bytes).

This document describes the on-screen layout, data flow, and the key
design choices behind the current implementation.

---

## 1. Goals and non-goals

**Goals**

- Live waveform display from up to **two independent serial sources** on a
  single shared plot, with per-channel show/hide.
- Honest, uniform time spacing on the X axis (no visual jitter from
  pyserial’s burst delivery).
- Cross-channel time synchronization: samples received at the same wall
  clock instant share an X position.
- Unit selector: partial pressure (mmHg) or volume fraction (%) at
  1013 mbar ambient.
- Adjustable plot window length (X axis span, in seconds).
- Per-channel logging:
  - decoded CSV (CO2, ETCO2, RR, InspCO2, status, PC timestamps)
  - byte-faithful raw hex capture.
- Freeze / unfreeze for inspection without disturbing future data.
- Two draggable vertical cursors with t1, t2, Δt and per-channel Y / ΔY
  readouts, including cross-channel A − B.

**Non-goals**

- This is not a clinical device. There is no alarm logic, no waveform
  filtering, and no claim of diagnostic accuracy.
- It does not act as a *full* host stack — only the handful of commands
  needed for bring-up are implemented.
- It does not synchronize the two sensors’ 100 Hz oscillators; minor
  long-term drift between traces is expected.

---

## 2. Protocol summary (recap)

Packet layout (no delimiters):

```
[CMD][NBF][data ...][CHK]
```

- `CMD`: bit 7 set (>= 0x80). First byte of every packet.
- All bytes after `CMD` have bit 7 clear (< 0x80).
- `NBF`: number of bytes following `CMD` (data + CHK).
- `CHK`: `(-sum(CMD, NBF, data ...)) & 0x7F`.

Waveform packet (`CMD = 0x80`):

```
sync(1B) co2_hi(1B) co2_lo(1B) [optional DPI groups ...] CHK
CO2_mmHg = ((co2_hi * 128 + co2_lo) - 1000) / 100.0
```

DPI groups appended inside a waveform packet:

| DPI | Type        | Payload                                       |
|----:|-------------|-----------------------------------------------|
| 1   | Status      | 5 B: status1, status2, status3, 0, 0          |
| 2   | ETCO2       | 2 B: hi, lo → value / 10.0 mmHg               |
| 3   | RR          | 2 B: hi, lo → value (breaths/min)             |
| 4   | InspCO2     | 2 B: hi, lo → value / 10.0 mmHg               |

DPI values are *sticky* on the receiver side: the most recent value of
each type is held in `SerialReader` until a new value of the same type
arrives, and is then attached to every produced `Sample`.

Defaults: 19 200 baud 8N1, 100 Hz waveform rate.

---

## 3. Process model and threading

```
┌─────────────────────────┐         ┌─────────────────────────┐
│ Reader thread (Ch A)    │         │ Reader thread (Ch B)    │
│  - pyserial             │         │  - pyserial             │
│  - parses packets       │         │  - parses packets       │
│  - puts Sample on queue │         │  - puts Sample on queue │
│  - puts raw bytes on    │         │  - puts raw bytes on    │
│    raw_queue            │         │    raw_queue            │
└──────────┬──────────────┘         └──────────┬──────────────┘
           │                                   │
           ▼                                   ▼
   queue.Queue (Sample)               queue.Queue (Sample)
   queue.Queue (bytes)                queue.Queue (bytes)
           │                                   │
           └─────────────┬─────────────────────┘
                         ▼
                 ┌──────────────┐
                 │ Tk main loop │
                 │  - drain Qs  │  ← every 20 ms via root.after
                 │  - update UI │
                 │  - matplotlib FuncAnimation @ 50 ms (~20 fps)
                 └──────────────┘
```

Threading rules:

- All Tk variable writes happen on the main thread. Status messages from
  the reader thread are marshalled via `root.after(0, …)` in
  `App._set_status`.
- The reader threads write only to: their own queues, plain ints
  (`bytes_total`, `packets_ok/bad`) read by the GUI for diagnostics, and
  the status callback. No locks are required: the queues handle the
  sample handoff, and the diagnostic counters are int loads which are
  atomic enough for an information-only status line.

`SerialReader.run()` drains **all** complete packets per `read()` chunk
before going back to block on the next chunk. Without that inner loop a
100 Hz stream visibly throttled to ~10 Hz at the GUI because each outer
iteration only handled one packet per `read()` return.

---

## 4. Data model

### `Sample` (dataclass)

```python
@dataclass
class Sample:
    t: float                   # PC monotonic time when parsed (s)
    sync: int
    co2: float                 # mmHg, signed
    raw_co2: int               # 14-bit transmitted value
    raw_packet: bytes          # full packet incl CMD/NBF/CHK
    etco2: Optional[float]     # mmHg
    rr:    Optional[float]     # bpm
    insp:  Optional[float]     # mmHg
    status1/2/3: Optional[int]
```

### `Channel`

Per-sensor container created twice by `App`. Owns:

- the `SerialReader` thread (or `None` when disconnected),
- decoded `Sample` queue and raw-byte queue,
- `CsvLogger` and `RawLogger` (optional),
- bounded `deque`s for plot data (`times`, `values`),
- matplotlib `Line2D` reference,
- diagnostic counters,
- time-base anchor used to enforce uniform sample spacing (see § 6).

### `App`

Top-level GUI object. Owns the matplotlib `Figure`/`Axes`, the two
`Channel`s, the shared time origin `_t0`, the freeze flag, the two
cursor `axvline`s, and the periodic queue-drain timer.

---

## 5. UI layout

Top to bottom:

1. **Channel A** group: port + baud + Connect / Send Start / Send Stop,
   Show-curve checkbox, color swatch, CSV path + Browse + Start logging,
   Raw path + Browse + Start raw.
2. **Channel B** group: same.
3. **Global controls** row: Refresh ports, Units (mmHg / %), Window (s)
   spinbox, Freeze button.
4. **Cursor readouts**: Time / Ch A / Ch B / A − B groups.
5. **Channel A readouts**: CO2 / ETCO2 / RR / InspCO2 (colored green).
6. **Channel B readouts**: same (colored blue).
7. **Plot**: shared X axis, two traces, two draggable vertical cursors,
   legend in the upper-right.
8. **Status bar** (bottom): per-channel byte rate, ok/bad packet counts,
   sample rate, plus screen FPS.

Colors are fixed: Channel A = green `#1b8a3a`, Channel B = blue
`#1f4fa8`, Cursor 1 = red `#d62728`, Cursor 2 = orange `#ff7f0e`.

---

## 6. Time base — the most important design decision

Two requirements pull in opposite directions:

- **Uniform sample spacing within each trace.** Pyserial delivers bytes
  in 50–100 ms bursts. Naïvely stamping samples with `time.monotonic()`
  at parse time makes the curve clump into short clusters separated by
  visible gaps, even though the underlying 100 Hz stream is intact.
- **Cross-channel synchronization.** A pure sample-index time base
  (`n / 100 Hz`) gives perfectly uniform spacing *within* a trace but
  the two channels then start at independent t = 0 and drift apart
  arbitrarily depending on when each thread saw its first sample.

The implementation combines both:

```
_t0           = wall-clock time of the first sample on any channel
ch._t_anchor  = X-position of this channel's first sample, in shared
                wall-clock coordinates (= s.t - _t0)
ch._anchor_idx= ch._samples_total at that first sample
x(n) = ch._t_anchor + (n - ch._anchor_idx) / WAVEFORM_HZ
```

Effect:

- Each channel’s X advances by exactly 10 ms per sample → no visual
  jitter from pyserial bursts.
- Both channels share `_t0`, so their first-sample anchors live on the
  same axis → samples that arrived simultaneously line up.
- If the two sensors’ 100 Hz oscillators drift, the traces will slowly
  drift relative to each other. This is acceptable for the intended
  use; a periodic re-anchor could be added if needed.

Reset rules:

- `_t0` is reset to `None` only when **both** channels are disconnected,
  so connecting/disconnecting one channel does not jump the timeline of
  the other.
- On **Unfreeze**, all buffers and anchors are cleared and `_t0` is
  reset so that presentation continues from a fresh t = 0.

---

## 7. Freeze / discard semantics

- The Freeze button toggles `App._frozen` (a `BooleanVar`).
- While frozen, `_drain_one_channel` still pulls samples from the queue
  (preventing back-pressure), still writes them to CSV if logging is
  enabled, but **does not** append them to the plot buffers and does
  not advance the time anchor.
- `_update_plot` does not auto-shift the X axis while frozen, so the
  frozen waveform stays exactly where it was — making the cursors
  usable for measurement.
- Unfreeze:
  1. clears each channel’s `times`/`values`/anchor,
  2. resets `_t0` to `None`,
  3. drains any pending samples from each queue so the next sample
     received is what defines the new t = 0,
  4. button label flips back to “Freeze”.

This satisfies the request that "data collected during freeze can be
discarded so when resuming presentation it starts from now".

---

## 8. Cursors and measurement panel

- Two `Axes.axvline` objects (`cur1`, `cur2`) added once at construction.
- Mouse interaction: `button_press_event` picks the nearest cursor by
  X distance, `motion_notify_event` while a button is held updates that
  cursor’s X, `button_release_event` ends the drag.
- The cursor readouts are recomputed:
  - on every cursor move (immediate feedback while dragging),
  - on every plot frame (so unit / window changes propagate even while
    the cursors stand still).
- Y values at a cursor are produced by `App._interp`: linear
  interpolation between the two surrounding samples in the
  channel’s deque. Outside the visible buffer the value is `None` and
  the readout shows `---`.
- All Y readouts honor the current unit (mmHg or %). Time values are
  always in seconds.

Readout groups:

| Group  | Entries                                          |
|--------|--------------------------------------------------|
| Time   | t1, t2, Δt                                       |
| Ch A   | A@1, A@2, ΔA (= A@2 − A@1)                       |
| Ch B   | B@1, B@2, ΔB                                     |
| A − B  | A−B@1, A−B@2                                     |

---

## 9. Units

Conversion uses a fixed ambient pressure of 1013 mbar:

```
AMBIENT_MMHG = 1013 mbar * 0.750062 mmHg/mbar ≈ 759.81 mmHg
% = mmHg / AMBIENT_MMHG * 100
```

- The selector is a pair of radio buttons (`mmHg` / `% (1013 mbar)`).
- The plot Y label and Y-range defaults switch when the unit changes:
  - mmHg: default range 0 .. 60, margins ±2 / +5
  - %:    default range 0 .. mmHg_to_pct(60), margins ±0.25 / +0.5
- All on-screen value readouts and the cursor panel respect the unit.
- **CSV files always store mmHg.** The wire protocol is mmHg-native and
  re-converting later is trivial; keeping the file unit fixed makes
  off-line analysis less error-prone.

---

## 10. Window length

`Window (s)` spinbox (default 10, range 2 .. 300). Changing it:

- updates `App._window_s`,
- re-creates each channel’s `times` / `values` `deque` with
  `maxlen = WAVEFORM_HZ * new_s`, preserving the most recent samples,
- updates the X-axis label so the current window is visible to the
  user.

The animation’s X-limit calculation always uses `_window_s`.

---

## 11. Logging

### Decoded CSV (`CsvLogger`)

Columns:

```
pc_time_iso, pc_time_s, sync, co2_mmHg,
etco2_mmHg, resp_rate_bpm, insp_co2_mmHg,
status1, status2, status3
```

- `pc_time_s` is relative to the logger’s own creation time.
- Sticky DPI fields are written on every sample (last known value).
- Logging is independent per channel; either, both, or neither may be
  active at any time.
- Logging continues during freeze. Choosing whether to discard frozen
  data from the *file* is up to the user (just press Stop logging
  before pressing Freeze).

### Raw capture (`RawLogger`)

One line per `Serial.read()` chunk:

```
<pc_time_s>  <hex bytes ...>
```

Useful for off-line replay and for diagnosing protocol issues that the
decoder skipped over (bad checksums, malformed DPI groups, etc.).

---

## 12. Status bar / diagnostics

Refreshed roughly every 0.5 s with:

```
ChA: <byte_rate> B/s ok=<n> bad=<n> <samp_rate> Hz |
ChB: <byte_rate> B/s ok=<n> bad=<n> <samp_rate> Hz |
screen=<fps> fps
```

- `byte_rate` and `samp_rate` are deltas over the refresh interval.
- `screen` FPS is measured by counting `FuncAnimation` callbacks; useful
  to verify that the display is not the bottleneck (target ~20 fps).
- Channels that are not connected show `Ch?: --`.

---

## 13. Error / edge handling

- **Two channels picking the same COM port** is rejected with a message
  box on Connect; `_refresh_ports` also avoids auto-picking the same
  port for both channels.
- **Bad packet** (bit-7 violation, bad checksum, oversize NBF) increments
  `packets_bad`. The byte stream is then resynced by dropping bytes
  until a fresh `CMD` (bit 7 set) is found.
- **Queue full** is treated as a drop with a `try / except queue.Full`
  pattern; the producer keeps moving even if the consumer is stuck.
- **Pre-open RTS / post-open DTR** dance: pyserial’s defaults can
  inadvertently pulse `EN` on CP210x/CH340 boards (auto-reset) or leave
  ESP32-S3 USB-CDC firmware in the "host not present" state. The reader
  forces `rts = False` *before* `open()` and `dtr = True` *after*.

---

## 14. Known limitations / possible future work

- No long-running re-anchor of the time base; over hours, two sensors
  with slightly different 100 Hz crystals will drift relative to each
  other on the X axis. A re-anchor that nudges the per-channel anchor
  when wall-clock and sample-derived X diverge by more than N ms would
  fix this.
- Cursor interaction uses the canvas mouse, not draggable artists; on
  very dense plots picking the *nearest* cursor by X distance is good
  enough but could be improved with explicit drag handles.
- The CSV header is fixed; if more DPI fields are added the loggers need
  to be updated in lockstep.
- No persisted settings: ports, baud, paths, unit, window and freeze
  state are not saved across runs.
- The host-side command set is intentionally minimal (Start / Stop). A
  full Capnostat-5 host emulator is out of scope.

---

## 15. File map

| File                                       | Purpose                              |
|--------------------------------------------|--------------------------------------|
| `tools/co2_monitor.py`                     | The monitor itself (this design).    |
| `tools/co2_monitor_design.md`              | This document.                       |
| `tools/README.md`                          | End-user notes / running the tool.   |
| `Documentation/ProjectDesign.md`           | Embedded emulator firmware design.   |

The PC monitor and the firmware speak the protocol described in § 2; any
change there must be made in **both** the device firmware *and* this
monitor.
