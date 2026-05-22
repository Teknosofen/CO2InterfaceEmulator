"""
CoCo Sensor Monitor & Logger
============================

Connects to one or two Sensirion CoCo CO2 sensors over the SHDLC/UART
interface (see Documentation/Coco_ShdlcUartInterface_v1.0.0.pdf), polls
each at a configurable rate, displays a live scrolling CO2 waveform with
per-channel readouts (CO2, ambient pressure, gas temperature, flow,
sample counter), and optionally logs every sample to a CSV file plus a
raw byte capture.

This is a sibling tool to ``co2_monitor.py``. That tool consumes the
Capnostat 5 stream pushed by the CO2 Interface Emulator at 100 Hz;
the CoCo sensor instead requires the host to act as SHDLC master and
issue ``Read Measurement Values`` commands itself.

Protocol summary (derived from the CoCo SHDLC manual and the matching
firmware in ``CoCo_simulator`` / ``CO2 Interface Emulator``):

  - 115200 8N1, slave address 0x00.
  - Frame: ``0x7E [addr] [cmd] [(state)] [len] [data...] [chk] 0x7E``.
    MOSI frames omit the ``state`` byte; MISO frames include it.
  - Byte stuffing: any of {0x7E, 0x7D, 0x11, 0x13} -> ``0x7D`` followed
    by ``b XOR 0x20``.
  - Checksum: ``~(sum of unstuffed fields) & 0xFF`` (one's complement
    of the sum over addr+cmd+(state)+len+data).
  - Commands used here:
        0x00 Start Measurement (subcmd 0x01 = periodic)
        0x01 Stop  Measurement
        0x03 Read  Measurement  (subcmd 0x00 = read values)
        0xD0 Device Info        (subcmd 0x00 = product type)
        0xD1 Get  Version
  - Read Measurement Values response payload (14 bytes, big-endian,
    units per the v1.0.0 spec):
        counter      (uint32)
        CO2 partial  (uint16, 0.1 mmHg, 0xFFFF      = invalid)
        flow         (int16,  1/120 slm,  0x7FFF    = invalid)
        pressure     (uint32, 1/4096 hPa, 0xFFFFFFFF = invalid)
        temperature  (int16,  1/200 °C,   0x7FFF    = invalid)
  - Read Buffered Values (0x04) returns multiple measurement data sets
    in a single SHDLC frame, but the per-sample layout is firmware-
    version-dependent and not pinned down in spec v1.0.0; this monitor
    therefore polls 0x03 only. The sensor itself samples internally at
    a much higher rate (Sensirion Control Center streams at 250 Hz via
    0x04), so 0x03 polling is sample-rate-limited regardless of how
    fast we poll.

Dependencies:
    pip install pyserial matplotlib
"""

from __future__ import annotations

import csv
import queue
import struct
import sys
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass, field
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import serial
import serial.tools.list_ports
from matplotlib.animation import FuncAnimation
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------
FRAME_START = 0x7E
FRAME_STOP = 0x7E
ESCAPE = 0x7D
ESCAPE_XOR = 0x20
STUFF_BYTES = {0x7E, 0x7D, 0x11, 0x13}

SLAVE_ADDR_DEFAULT = 0x00

CMD_START_MEASUREMENT = 0x00
CMD_STOP_MEASUREMENT = 0x01
CMD_READ_MEASUREMENT = 0x03
CMD_READ_BUFFERED = 0x04
CMD_DEVICE_INFO = 0xD0
CMD_GET_VERSION = 0xD1

SUB_START_PERIODIC = 0x01
SUB_READ_MEAS_VALUES = 0x00
SUB_READ_BUF_VALUES = 0x00
SUB_GET_PRODUCT_TYPE = 0x00

# Reader operating modes.
MODE_POLLED = "polled"      # 0x03 - one latest sample per request (<= poll rate)
MODE_BUFFERED = "buffered"  # 0x04 - drain circular buffer, retrieves every sample

# Nominal sensor sample rate (per Sensirion Control Center / counter delta
# observations). Used to synthesize per-sample timestamps in buffered mode
# until the runtime estimate stabilises.
NOMINAL_SENSOR_HZ = 250.0

ERROR_NAMES = {
    0x00: "Success",
    0x01: "Data size error",
    0x02: "Unknown command",
    0x04: "Parameter error",
    0x20: "No measurement data",
    0x28: "Configuration error",
    0x43: "Command not allowed in current state",
    0x7F: "Fatal error",
}

DEFAULT_BAUD = 115200
DEFAULT_POLL_HZ = 100
MAX_POLL_HZ = 250
MAX_PLOT_SECONDS = 600
DEFAULT_PLOT_SECONDS = 10

# Sentinel values that flag "no valid measurement available" per the spec.
INVALID_CO2 = 0xFFFF              # uint16
INVALID_FLOW = 0x7FFF             # int16 (raw)
INVALID_PRESSURE = 0xFFFFFFFF     # uint32
INVALID_TEMPERATURE = 0x7FFF      # int16 (raw)

# Scaling factors from the v1.0.0 SHDLC interface specification.
CO2_LSB_MMHG = 0.1
FLOW_LSB_SLM = 1.0 / 120.0
PRESSURE_LSB_HPA = 1.0 / 4096.0
TEMPERATURE_LSB_C = 1.0 / 200.0


# ---------------------------------------------------------------------------
# SHDLC framing helpers
# ---------------------------------------------------------------------------
def _checksum(fields: bytes) -> int:
    return (~sum(fields)) & 0xFF


def _stuff(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b in STUFF_BYTES:
            out.append(ESCAPE)
            out.append(b ^ ESCAPE_XOR)
        else:
            out.append(b)
    return bytes(out)


def build_mosi_frame(addr: int, cmd: int, payload: bytes = b"") -> bytes:
    """Build a MOSI (master->slave) SHDLC frame."""
    body = bytes([addr, cmd, len(payload)]) + payload
    chk = _checksum(body)
    return bytes([FRAME_START]) + _stuff(body + bytes([chk])) + bytes([FRAME_STOP])


def _unstuff(raw: bytes) -> Optional[bytes]:
    out = bytearray()
    esc = False
    for b in raw:
        if esc:
            out.append(b ^ ESCAPE_XOR)
            esc = False
        elif b == ESCAPE:
            esc = True
        else:
            out.append(b)
    if esc:
        return None
    return bytes(out)


@dataclass
class MisoFrame:
    addr: int
    cmd: int
    state: int
    data: bytes
    raw: bytes  # exact bytes received (including 0x7E delimiters)

    @property
    def ok(self) -> bool:
        return (self.state & 0x7F) == 0x00 and (self.state & 0x80) == 0

    def err_name(self) -> str:
        code = self.state & 0x7F
        name = ERROR_NAMES.get(code, f"Unknown error 0x{code:02X}")
        if self.state & 0x80:
            name += " [DEVICE ERROR FLAG]"
        return name


def parse_miso_frame(raw_between_delimiters: bytes) -> Optional[MisoFrame]:
    """Parse the unstuffed contents of a MISO frame (between the 0x7E bytes).

    Returns None on malformed or bad-checksum frame.
    """
    unstuffed = _unstuff(raw_between_delimiters)
    if unstuffed is None or len(unstuffed) < 5:
        return None
    addr = unstuffed[0]
    cmd = unstuffed[1]
    state = unstuffed[2]
    n = unstuffed[3]
    if len(unstuffed) < 4 + n + 1:
        return None
    data = unstuffed[4:4 + n]
    chk = unstuffed[4 + n]
    if _checksum(unstuffed[:4 + n]) != chk:
        return None
    return MisoFrame(addr=addr, cmd=cmd, state=state, data=bytes(data),
                     raw=bytes([FRAME_START]) + raw_between_delimiters + bytes([FRAME_STOP]))


# ---------------------------------------------------------------------------
# Sample container
# ---------------------------------------------------------------------------
@dataclass
class Sample:
    t: float                          # PC monotonic timestamp (s)
    counter: int                      # sensor's own sample counter (uint32)
    co2_mmhg: Optional[float]         # None if sensor reported invalid
    flow_slm: Optional[float]         # standard L/min, None if invalid
    pressure_hpa: Optional[float]     # hPa (== mbar), None if invalid
    temperature_c: Optional[float]    # °C, None if invalid
    raw_response: bytes = b""         # full MISO frame bytes (incl 0x7E)


# ---------------------------------------------------------------------------
# Serial reader / polling thread
# ---------------------------------------------------------------------------
class CocoReader(threading.Thread):
    """Background thread that polls a single CoCo sensor over SHDLC.

    Workflow on start:
      1. Open the serial port (no DTR/RTS toggling).
      2. Issue ``Stop Measurement`` (ignored if not measuring) to make sure
         the sensor is in a known idle state.
      3. Issue ``Get Version`` and ``Device Info / Product Type`` for the
         status pane (best-effort; failure is non-fatal).
      4. Issue ``Start Measurement (periodic)``.
      5. Poll ``Read Measurement Values`` at the configured rate, pushing
         a ``Sample`` to ``out_queue`` for every successful response.

    On stop the thread issues ``Stop Measurement`` before closing the port.
    """

    def __init__(self, port: str, baud: int, addr: int,
                 poll_hz: float,
                 out_queue: "queue.Queue[Sample]",
                 status_cb,
                 raw_queue: "Optional[queue.Queue[bytes]]" = None,
                 mode: str = MODE_POLLED) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.addr = addr
        self.poll_period = 1.0 / max(1.0, poll_hz)
        self.mode = mode
        self.out_queue = out_queue
        self.raw_queue = raw_queue
        self.status_cb = status_cb

        self._stop_evt = threading.Event()
        self.ser: Optional[serial.Serial] = None

        # Diagnostics (read by the GUI thread; integer writes are atomic
        # enough in CPython that we do not need a lock for displaying).
        self.bytes_total = 0
        self.frames_ok = 0
        self.frames_bad = 0
        self.timeouts = 0

        # Discovered sensor identity (best effort).
        self.product_type: Optional[str] = None
        self.fw_version: Optional[str] = None
        self.hw_version: Optional[str] = None

        # Buffered-mode state.
        self.buffered_format: Optional[int] = None      # format byte from response
        self.buffered_sample_size: Optional[int] = None # bytes per data set
        self.buffered_last_counter: Optional[int] = None
        self.buffered_overflows: int = 0                # circular-buffer gaps seen

    def stop(self) -> None:
        self._stop_evt.set()

    def set_poll_hz(self, hz: float) -> None:
        self.poll_period = 1.0 / max(1.0, hz)

    # ---- transaction helpers ------------------------------------------------
    def _read_frame(self, timeout_s: float = 0.3) -> Optional[MisoFrame]:
        """Block until a complete frame arrives or ``timeout_s`` elapses."""
        assert self.ser is not None
        deadline = time.monotonic() + timeout_s
        buf = bytearray()
        in_frame = False
        while time.monotonic() < deadline and not self._stop_evt.is_set():
            chunk = self.ser.read(64)
            if chunk:
                self.bytes_total += len(chunk)
                if self.raw_queue is not None:
                    try:
                        self.raw_queue.put_nowait(bytes(chunk))
                    except queue.Full:
                        pass
                for b in chunk:
                    if not in_frame:
                        if b == FRAME_START:
                            in_frame = True
                            buf.clear()
                    else:
                        if b == FRAME_STOP:
                            if not buf:
                                # 0x7E 0x7E sequence: treat the second one
                                # as a new start byte rather than an empty
                                # frame.
                                continue
                            frame = parse_miso_frame(bytes(buf))
                            if frame is None:
                                self.frames_bad += 1
                                in_frame = False
                                buf.clear()
                                continue
                            self.frames_ok += 1
                            return frame
                        else:
                            buf.append(b)
            else:
                # short sleep handled by serial timeout
                pass
        self.timeouts += 1
        return None

    def _transact(self, cmd: int, payload: bytes = b"",
                  timeout_s: float = 0.3) -> Optional[MisoFrame]:
        assert self.ser is not None
        try:
            self.ser.reset_input_buffer()
            self.ser.write(build_mosi_frame(self.addr, cmd, payload))
        except serial.SerialException as e:
            self.status_cb(f"Write error: {e}")
            return None
        # Small dwell so the slave can answer (matches the firmware which
        # delays 2 ms before responding).
        end = time.monotonic() + timeout_s
        while time.monotonic() < end and not self._stop_evt.is_set():
            frame = self._read_frame(timeout_s=max(0.0, end - time.monotonic()))
            if frame is None:
                return None
            if frame.cmd == cmd:
                return frame
            # Stray response (e.g. delayed reply to previous command).
            # Drop and keep waiting.
        return None

    # ---- response parsing ---------------------------------------------------
    @staticmethod
    def _decode_meas_tuple(buf: bytes) -> tuple:
        """Decode the 10-byte CO2/flow/pressure/temperature tuple."""
        raw_co2, raw_flow, raw_pressure, raw_temp = struct.unpack(
            ">HhIh", buf[:10])
        co2 = None if raw_co2 == INVALID_CO2 else raw_co2 * CO2_LSB_MMHG
        flow = None if raw_flow == 0x7FFF else raw_flow * FLOW_LSB_SLM
        pressure = (None if (raw_pressure & 0xFFFFFFFF) == INVALID_PRESSURE
                    else raw_pressure * PRESSURE_LSB_HPA)
        temperature = (None if raw_temp == 0x7FFF
                       else raw_temp * TEMPERATURE_LSB_C)
        return co2, flow, pressure, temperature

    @classmethod
    def _parse_measurement(cls, data: bytes) -> Optional[Sample]:
        if len(data) < 14:
            return None
        counter = struct.unpack(">I", data[:4])[0]
        co2, flow, pressure, temperature = cls._decode_meas_tuple(data[4:14])
        return Sample(
            t=time.monotonic(),
            counter=counter,
            co2_mmhg=co2,
            flow_slm=flow,
            pressure_hpa=pressure,
            temperature_c=temperature,
        )

    def _parse_buffered(self, data: bytes,
                        arrival_t: float,
                        sensor_period: float) -> list:
        """Decode a Read-Buffered-Values response into a list of Samples.

        Response layout (per v1.0.0 spec):
            0..3  counter_start (uint32, BE) - counter of OLDEST sample
            4..7  n_remaining   (uint32, BE) - samples still in buffer
            8     format        (uint8)      - firmware-version-dependent
            9..n  data sets concatenated, layout determined by ``format``

        The per-sample layout is firmware-version dependent. We try the
        two layouts that are plausible for this device:
          * 14 B: same as 0x03 (counter | CO2 | flow | pressure | temp)
          * 10 B: CO2 | flow | pressure | temp  (counter implicit from
                  ``counter_start`` + index)
        The first call that yields exact divisibility for one of the
        candidates is locked in for subsequent calls.
        """
        if len(data) < 9:
            return []
        counter_start, n_remaining, fmt = struct.unpack(">IIB", data[:9])
        payload = data[9:]
        if not payload:
            return []

        # Lock layout on first successful parse.
        if self.buffered_sample_size is None:
            chosen = None
            # 14 B layout: embedded uint32 counters must equal
            # counter_start, counter_start+1, ... (mod 2^32). If they
            # don't, this is the 10 B layout (where counter is implicit).
            if len(payload) >= 14 and len(payload) % 14 == 0:
                n = len(payload) // 14
                ok = True
                for i in range(min(n, 4)):  # check up to first 4 samples
                    embedded = struct.unpack(">I", payload[i * 14:i * 14 + 4])[0]
                    if embedded != ((counter_start + i) & 0xFFFFFFFF):
                        ok = False
                        break
                if ok:
                    chosen = 14
            if chosen is None and len(payload) % 10 == 0:
                chosen = 10
            if chosen is None and len(payload) % 14 == 0:
                # 14-byte layout failed self-check but is the only option;
                # accept it but warn.
                chosen = 14
                self.status_cb(
                    "Buffered mode: 14 B layout selected by size only "
                    "(counter mismatch in payload)")
            if chosen is not None:
                self.buffered_sample_size = chosen
                self.buffered_format = fmt
                self.status_cb(
                    f"Buffered mode: format=0x{fmt:02X}  "
                    f"sample_size={chosen} B  first_counter={counter_start}"
                )
            else:
                if self.buffered_format != fmt:
                    self.status_cb(
                        f"Buffered mode: unknown format 0x{fmt:02X}, "
                        f"payload {len(payload)} B - dropping response"
                    )
                    self.buffered_format = fmt
                return []

        if fmt != self.buffered_format:
            # Format changed mid-stream (shouldn't happen).
            self.status_cb(
                f"Buffered mode: format changed 0x{self.buffered_format:02X}"
                f" -> 0x{fmt:02X}, re-detecting")
            self.buffered_format = None
            self.buffered_sample_size = None
            return []

        size = self.buffered_sample_size
        n_samples = len(payload) // size
        if n_samples == 0:
            return []

        # Detect buffer overflow (gap since last response).
        if (self.buffered_last_counter is not None
                and counter_start != (self.buffered_last_counter + 1) & 0xFFFFFFFF):
            gap = (counter_start - self.buffered_last_counter - 1) & 0xFFFFFFFF
            if 0 < gap < 1_000_000:
                self.buffered_overflows += 1

        # Synthesize per-sample timestamps. The newest sample is assumed
        # to have been acquired just before the response was sent; older
        # samples step back by ``sensor_period``.
        newest_t = arrival_t
        samples = []
        for i in range(n_samples):
            off = i * size
            chunk = payload[off:off + size]
            if size == 14:
                counter = struct.unpack(">I", chunk[:4])[0]
                co2, flow, pressure, temperature = self._decode_meas_tuple(
                    chunk[4:14])
            else:  # size == 10
                counter = (counter_start + i) & 0xFFFFFFFF
                co2, flow, pressure, temperature = self._decode_meas_tuple(chunk)
            # Sample i corresponds to position (n_samples - 1 - i) back
            # from the newest one in time.
            steps_back = (n_samples - 1 - i) + n_remaining
            t = newest_t - steps_back * sensor_period
            samples.append(Sample(
                t=t,
                counter=counter,
                co2_mmhg=co2,
                flow_slm=flow,
                pressure_hpa=pressure,
                temperature_c=temperature,
            ))

        self.buffered_last_counter = (counter_start + n_samples - 1) & 0xFFFFFFFF
        return samples

    # ---- main loop ----------------------------------------------------------
    def run(self) -> None:
        try:
            self.ser = serial.Serial()
            self.ser.port = self.port
            self.ser.baudrate = self.baud
            self.ser.bytesize = serial.EIGHTBITS
            self.ser.parity = serial.PARITY_NONE
            self.ser.stopbits = serial.STOPBITS_ONE
            self.ser.timeout = 0.05
            self.ser.write_timeout = 0.5
            self.ser.dsrdtr = False
            self.ser.rtscts = False
            self.ser.xonxoff = False
            try:
                self.ser.rts = False
            except Exception:
                pass
            self.ser.open()
            try:
                self.ser.dtr = True
                self.ser.rts = False
            except Exception:
                pass
            self.ser.reset_input_buffer()
        except serial.SerialException as e:
            self.status_cb(f"ERROR: {e}")
            return

        self.status_cb(f"Connected to {self.port} @ {self.baud}")

        # Best-effort: clear any stale measurement state, then identify the
        # sensor before we start streaming.
        self._transact(CMD_STOP_MEASUREMENT, timeout_s=0.2)

        ver = self._transact(CMD_GET_VERSION, timeout_s=0.3)
        if ver is not None and ver.ok and len(ver.data) >= 7:
            self.fw_version = f"{ver.data[0]}.{ver.data[1]}.{ver.data[2]}"
            self.hw_version = f"{ver.data[3]}.{ver.data[4]}"

        info = self._transact(CMD_DEVICE_INFO, bytes([SUB_GET_PRODUCT_TYPE]),
                              timeout_s=0.3)
        if info is not None and info.ok and info.data:
            try:
                self.product_type = info.data.rstrip(b"\x00").decode("ascii")
            except UnicodeDecodeError:
                self.product_type = info.data.hex()

        start = self._transact(CMD_START_MEASUREMENT, bytes([SUB_START_PERIODIC]),
                               timeout_s=0.3)
        if start is None:
            self.status_cb("ERROR: no reply to Start Measurement")
        elif not start.ok:
            self.status_cb(f"ERROR: Start Measurement -> {start.err_name()}")
        else:
            self.status_cb(
                f"Measuring [{self.mode}] @ {1.0 / self.poll_period:.0f} Hz"
                + (f"  [{self.product_type}]" if self.product_type else "")
            )

        # ---- polling loop ----
        next_t = time.monotonic()
        while not self._stop_evt.is_set():
            now = time.monotonic()
            wait = next_t - now
            if wait > 0:
                # Use the serial timeout to wait; this also drains any
                # spurious bytes that might be in the buffer.
                self._stop_evt.wait(min(wait, 0.1))
                continue
            next_t += self.poll_period
            # Avoid runaway catch-up if the loop fell badly behind.
            if next_t < now - self.poll_period:
                next_t = now + self.poll_period

            if self.mode == MODE_BUFFERED:
                # Buffered read: one transaction returns multiple samples.
                # Allow a generous timeout because the response can be
                # large (>200 B at 230400 baud takes ~10 ms).
                frame = self._transact(
                    CMD_READ_BUFFERED, bytes([SUB_READ_BUF_VALUES]),
                    timeout_s=max(0.1, self.poll_period * 0.9 + 0.05))
                if frame is None:
                    continue
                if not frame.ok:
                    # No data yet is normal right after Start; the
                    # circular buffer is empty until the first sample.
                    continue
                arrival_t = time.monotonic()
                samples = self._parse_buffered(
                    frame.data, arrival_t, 1.0 / NOMINAL_SENSOR_HZ)
                for sample in samples:
                    sample.raw_response = frame.raw
                    try:
                        self.out_queue.put_nowait(sample)
                    except queue.Full:
                        pass
                continue

            # Polled mode (0x03): one latest sample per request.
            frame = self._transact(CMD_READ_MEASUREMENT,
                                   bytes([SUB_READ_MEAS_VALUES]),
                                   timeout_s=self.poll_period * 0.9 + 0.05)
            if frame is None:
                continue
            if not frame.ok:
                # No data yet is normal right after Start.
                continue
            sample = self._parse_measurement(frame.data)
            if sample is None:
                continue
            sample.raw_response = frame.raw
            try:
                self.out_queue.put_nowait(sample)
            except queue.Full:
                pass

        # Ask the sensor to stop streaming before we close.
        try:
            self._transact(CMD_STOP_MEASUREMENT, timeout_s=0.2)
        except Exception:
            pass

        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass
        self.status_cb("Disconnected")


# ---------------------------------------------------------------------------
# Loggers
# ---------------------------------------------------------------------------
class CsvLogger:
    HEADER = ["pc_time_iso", "pc_time_s", "counter",
              "co2_mmHg", "flow_slm", "pressure_hPa", "temperature_C"]

    def __init__(self, path: str) -> None:
        self._fh = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh)
        self._writer.writerow(self.HEADER)
        self._t0 = time.monotonic()
        self.path = path
        self.count = 0

    def write(self, s: Sample) -> None:
        self._writer.writerow([
            time.strftime("%Y-%m-%dT%H:%M:%S"),
            f"{s.t - self._t0:.4f}",
            s.counter,
            "" if s.co2_mmhg is None else f"{s.co2_mmhg:.2f}",
            "" if s.flow_slm is None else f"{s.flow_slm:.4f}",
            "" if s.pressure_hpa is None else f"{s.pressure_hpa:.3f}",
            "" if s.temperature_c is None else f"{s.temperature_c:.3f}",
        ])
        self.count += 1

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass


class RawLogger:
    """Append every received raw byte chunk to a text dump file."""

    def __init__(self, path: str) -> None:
        self._fh = open(path, "w", encoding="utf-8", buffering=1)
        self._fh.write(f"# CoCo raw capture started {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._fh.write("# Format: <pc_time_s> <hex bytes ...>\n")
        self._t0 = time.monotonic()
        self.path = path
        self.bytes = 0

    def write(self, chunk: bytes) -> None:
        ts = time.monotonic() - self._t0
        hexstr = " ".join(f"{b:02X}" for b in chunk)
        self._fh.write(f"{ts:9.4f} {hexstr}\n")
        self.bytes += len(chunk)

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
@dataclass
class Channel:
    name: str
    color: str
    default_prefix: str

    sample_queue: "queue.Queue[Sample]" = field(
        default_factory=lambda: queue.Queue(maxsize=10000))
    raw_queue: "queue.Queue[bytes]" = field(
        default_factory=lambda: queue.Queue(maxsize=10000))
    reader: Optional[CocoReader] = None
    logger: Optional[CsvLogger] = None
    raw_logger: Optional[RawLogger] = None

    times: deque = field(default_factory=lambda: deque(
        maxlen=int(NOMINAL_SENSOR_HZ * DEFAULT_PLOT_SECONDS * 1.5)))
    values: deque = field(default_factory=lambda: deque(
        maxlen=int(NOMINAL_SENSOR_HZ * DEFAULT_PLOT_SECONDS * 1.5)))
    last: Optional[Sample] = None

    # Counter-based diagnostics so we can distinguish "sensor produced a
    # new sample" from "sensor returned the same latest value again".
    # The sensor's internal counter increments once per acquired sample
    # (nominally 250 Hz), regardless of how often the host polls 0x03 --
    # so (counter_delta / time_delta) yields the true sensor data rate
    # even when our poll rate is lower.
    last_counter: Optional[int] = None
    fresh_total: int = 0
    dup_total: int = 0
    _fresh_window_t0: float = 0.0
    _fresh_window_n: int = 0
    fresh_hz: float = 0.0  # unique-sample rate at the host (<= poll rate)
    _rate_window_t0: float = 0.0
    _rate_window_c0: Optional[int] = None
    _rate_window_polls: int = 0
    sensor_hz: float = 0.0  # true sensor sampling rate (from counter delta)
    poll_hz_actual: float = 0.0  # measured 0x03 transaction rate

    # Tk vars - populated by App._build_channel_row
    port_var: Optional[tk.StringVar] = None
    port_cb: Optional[ttk.Combobox] = None
    baud_var: Optional[tk.IntVar] = None
    addr_var: Optional[tk.IntVar] = None
    hz_var: Optional[tk.DoubleVar] = None
    mode_var: Optional[tk.StringVar] = None
    connect_btn: Optional[ttk.Button] = None
    show_var: Optional[tk.BooleanVar] = None
    path_var: Optional[tk.StringVar] = None
    log_btn: Optional[ttk.Button] = None
    raw_path_var: Optional[tk.StringVar] = None
    raw_log_btn: Optional[ttk.Button] = None
    co2_var: Optional[tk.StringVar] = None
    pres_var: Optional[tk.StringVar] = None
    temp_var: Optional[tk.StringVar] = None
    flow_var: Optional[tk.StringVar] = None
    info_var: Optional[tk.StringVar] = None
    stats_var: Optional[tk.StringVar] = None
    line = None  # matplotlib Line2D


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("CoCo sensor logger - dual channel")
        root.geometry("1200x820")

        self.channels: list[Channel] = [
            Channel("A", "#1b8a3a", "cocoA"),
            Channel("B", "#1f4fa8", "cocoB"),
        ]

        self._t0: Optional[float] = None
        self._window_s: int = DEFAULT_PLOT_SECONDS
        self._frozen = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Idle")

        self._build_ui()
        self._refresh_ports()

        self.root.after(50, self._drain_queues)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- UI construction ----------------------------------------------------
    def _build_ui(self) -> None:
        for ch in self.channels:
            self._build_channel_row(ch)

        info = ttk.Frame(self.root, padding=6)
        info.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(info, text="Refresh ports",
                   command=self._refresh_ports).pack(side=tk.LEFT)

        ttk.Label(info, text="   Window (s):").pack(side=tk.LEFT)
        self.window_var = tk.IntVar(value=self._window_s)
        spin = ttk.Spinbox(info, from_=2, to=MAX_PLOT_SECONDS, increment=1,
                           width=5, textvariable=self.window_var,
                           command=self._on_window_change)
        spin.pack(side=tk.LEFT, padx=(2, 4))
        spin.bind("<Return>", lambda _e: self._on_window_change())
        spin.bind("<FocusOut>", lambda _e: self._on_window_change())

        self.freeze_btn = ttk.Button(info, text="Freeze",
                                     command=self._toggle_freeze)
        self.freeze_btn.pack(side=tk.LEFT, padx=(12, 4))

        for ch in self.channels:
            self._build_channel_readouts(ch)

        # Plot
        self.fig = Figure(figsize=(10, 4.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("CoCo CO2 waveform")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("CO2 (mmHg)")
        self.ax.set_ylim(-2, 60)
        self.ax.set_xlim(0, self._window_s)
        self.ax.grid(True, alpha=0.3)
        for ch in self.channels:
            (ch.line,) = self.ax.plot([], [], color=ch.color, linewidth=1.5,
                                      label=f"Ch {ch.name}")
        self.ax.legend(loc="upper right")

        canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas = canvas

        # Status bar
        status_entry = tk.Entry(self.root, textvariable=self.status_var,
                                relief=tk.SUNKEN,
                                readonlybackground="#eaeaea")
        status_entry.configure(state="readonly")
        status_entry.pack(side=tk.BOTTOM, fill=tk.X)

        self.anim = FuncAnimation(self.fig, self._update_plot,
                                  interval=80, blit=False,
                                  cache_frame_data=False)

    def _build_channel_row(self, ch: Channel) -> None:
        frame = ttk.LabelFrame(self.root,
                               text=f"Channel {ch.name}", padding=4)
        frame.pack(side=tk.TOP, fill=tk.X, padx=6, pady=2)

        r1 = ttk.Frame(frame)
        r1.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(r1, text="Port:").pack(side=tk.LEFT)
        ch.port_var = tk.StringVar()
        ch.port_cb = ttk.Combobox(r1, textvariable=ch.port_var, width=28,
                                  state="readonly")
        ch.port_cb.pack(side=tk.LEFT, padx=(2, 6))

        ttk.Label(r1, text="Baud:").pack(side=tk.LEFT)
        ch.baud_var = tk.IntVar(value=DEFAULT_BAUD)
        ttk.Combobox(r1, textvariable=ch.baud_var, width=8,
                     values=(9600, 19200, 38400, 57600, 115200,
                             230400, 460800)).pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(r1, text="Addr:").pack(side=tk.LEFT)
        ch.addr_var = tk.IntVar(value=SLAVE_ADDR_DEFAULT)
        ttk.Spinbox(r1, from_=0, to=255, width=4,
                    textvariable=ch.addr_var).pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(r1, text="Poll Hz:").pack(side=tk.LEFT)
        ch.hz_var = tk.DoubleVar(value=DEFAULT_POLL_HZ)
        hz_spin = ttk.Spinbox(r1, from_=1, to=MAX_POLL_HZ, increment=1, width=5,
                              textvariable=ch.hz_var,
                              command=lambda c=ch: self._on_hz_change(c))
        hz_spin.pack(side=tk.LEFT, padx=(2, 8))
        hz_spin.bind("<Return>", lambda _e, c=ch: self._on_hz_change(c))
        hz_spin.bind("<FocusOut>", lambda _e, c=ch: self._on_hz_change(c))

        ttk.Label(r1, text="Mode:").pack(side=tk.LEFT)
        ch.mode_var = tk.StringVar(value=MODE_BUFFERED)
        ttk.Combobox(r1, textvariable=ch.mode_var, width=9, state="readonly",
                     values=(MODE_POLLED, MODE_BUFFERED)).pack(
            side=tk.LEFT, padx=(2, 8))

        ch.connect_btn = ttk.Button(
            r1, text="Connect",
            command=lambda c=ch: self._toggle_connect(c))
        ch.connect_btn.pack(side=tk.LEFT, padx=2)

        ch.show_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r1, text="Show curve", variable=ch.show_var,
                        command=lambda c=ch: self._on_show_change(c)).pack(
            side=tk.LEFT, padx=(10, 2))

        tk.Label(r1, text="  ", background=ch.color, width=2,
                 relief=tk.SUNKEN).pack(side=tk.LEFT, padx=(2, 6))

        # Row 2: CSV and raw file paths
        r2 = ttk.Frame(frame)
        r2.pack(side=tk.TOP, fill=tk.X, pady=(2, 0))

        ttk.Label(r2, text="CSV:").pack(side=tk.LEFT)
        ch.path_var = tk.StringVar(value="")
        ttk.Entry(r2, textvariable=ch.path_var, width=40).pack(
            side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        ttk.Button(r2, text="Browse...",
                   command=lambda c=ch: self._browse_csv(c)).pack(side=tk.LEFT)
        ch.log_btn = ttk.Button(
            r2, text="Start logging",
            command=lambda c=ch: self._toggle_logging(c))
        ch.log_btn.pack(side=tk.LEFT, padx=4)

        ttk.Label(r2, text="  Raw:").pack(side=tk.LEFT)
        ch.raw_path_var = tk.StringVar(value="")
        ttk.Entry(r2, textvariable=ch.raw_path_var, width=30).pack(
            side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        ttk.Button(r2, text="Browse...",
                   command=lambda c=ch: self._browse_raw(c)).pack(side=tk.LEFT)
        ch.raw_log_btn = ttk.Button(
            r2, text="Start raw",
            command=lambda c=ch: self._toggle_raw_logging(c))
        ch.raw_log_btn.pack(side=tk.LEFT, padx=4)

    def _build_channel_readouts(self, ch: Channel) -> None:
        frame = ttk.LabelFrame(self.root,
                               text=f"Channel {ch.name} readouts",
                               padding=4)
        frame.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(0, 2))

        ch.co2_var = tk.StringVar(value="CO2: --- mmHg")
        ch.pres_var = tk.StringVar(value="P: --- hPa")
        ch.temp_var = tk.StringVar(value="T: --- °C")
        ch.flow_var = tk.StringVar(value="Flow: --- slm")
        ch.info_var = tk.StringVar(value="Sensor: ---")
        ch.stats_var = tk.StringVar(value="Rx 0 B  ok 0 / bad 0")

        for var in (ch.co2_var, ch.pres_var, ch.temp_var, ch.flow_var):
            e = tk.Entry(frame, textvariable=var,
                         font=("Segoe UI", 11, "bold"), width=18,
                         relief=tk.FLAT, readonlybackground="#f0f0f0",
                         foreground=ch.color)
            e.configure(state="readonly")
            e.pack(side=tk.LEFT, padx=4)

        ttk.Label(frame, textvariable=ch.info_var).pack(side=tk.LEFT, padx=(10, 4))
        ttk.Label(frame, textvariable=ch.stats_var).pack(side=tk.LEFT, padx=4)

    # ---- port enumeration ---------------------------------------------------
    def _refresh_ports(self) -> None:
        ports = [f"{p.device} - {p.description}"
                 for p in serial.tools.list_ports.comports()]
        for ch in self.channels:
            cur = ch.port_var.get() if ch.port_var is not None else ""
            ch.port_cb["values"] = ports
            if cur and cur in ports:
                ch.port_var.set(cur)
            elif ports:
                ch.port_var.set(ports[0])
            else:
                ch.port_var.set("")

    @staticmethod
    def _port_device(s: str) -> str:
        return s.split(" - ", 1)[0].strip() if s else ""

    # ---- connect / disconnect ----------------------------------------------
    def _toggle_connect(self, ch: Channel) -> None:
        if ch.reader is None:
            port = self._port_device(ch.port_var.get())
            if not port:
                messagebox.showerror("CoCo monitor", f"No port selected for Ch {ch.name}")
                return
            ch.reader = CocoReader(
                port=port,
                baud=ch.baud_var.get(),
                addr=int(ch.addr_var.get()) & 0xFF,
                poll_hz=float(ch.hz_var.get()),
                out_queue=ch.sample_queue,
                status_cb=lambda msg, c=ch: self._set_status(c, msg),
                raw_queue=ch.raw_queue,
                mode=(ch.mode_var.get() if ch.mode_var is not None else MODE_POLLED),
            )
            # Reset rate-tracking state for a clean session.
            ch.last_counter = None
            ch.fresh_total = 0
            ch.dup_total = 0
            ch._fresh_window_t0 = 0.0
            ch._fresh_window_n = 0
            ch.fresh_hz = 0.0
            ch._rate_window_t0 = 0.0
            ch._rate_window_c0 = None
            ch._rate_window_polls = 0
            ch.sensor_hz = 0.0
            ch.poll_hz_actual = 0.0
            ch.reader.start()
            ch.connect_btn.configure(text="Disconnect")
        else:
            ch.reader.stop()
            ch.reader = None
            ch.connect_btn.configure(text="Connect")

    def _on_hz_change(self, ch: Channel) -> None:
        try:
            hz = float(ch.hz_var.get())
        except (tk.TclError, ValueError):
            return
        if ch.reader is not None:
            ch.reader.set_poll_hz(hz)
        # Resize buffers to keep the configured window length covered even
        # at the new rate. In buffered mode the host receives multiple
        # samples per poll, so the effective data rate is the sensor rate
        # (nominally 250 Hz), not the poll rate.
        mode = ch.mode_var.get() if ch.mode_var is not None else MODE_POLLED
        effective_hz = NOMINAL_SENSOR_HZ if mode == MODE_BUFFERED else hz
        n = int(max(2.0, effective_hz) * self._window_s * 1.5)
        ch.times = deque(ch.times, maxlen=n)
        ch.values = deque(ch.values, maxlen=n)

    # ---- file dialogs -------------------------------------------------------
    def _suggest_path(self, ch: Channel, suffix: str) -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        return f"{ch.default_prefix}_{ts}.{suffix}"

    def _browse_csv(self, ch: Channel) -> None:
        path = filedialog.asksaveasfilename(
            title=f"CoCo CSV - channel {ch.name}",
            defaultextension=".csv",
            initialfile=self._suggest_path(ch, "csv"),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            ch.path_var.set(path)

    def _browse_raw(self, ch: Channel) -> None:
        path = filedialog.asksaveasfilename(
            title=f"CoCo raw capture - channel {ch.name}",
            defaultextension=".txt",
            initialfile=self._suggest_path(ch, "raw.txt"),
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            ch.raw_path_var.set(path)

    # ---- logging toggles ----------------------------------------------------
    def _toggle_logging(self, ch: Channel) -> None:
        if ch.logger is None:
            path = ch.path_var.get().strip()
            if not path:
                messagebox.showerror("CoCo monitor",
                                     f"No CSV path set for Ch {ch.name}")
                return
            try:
                ch.logger = CsvLogger(path)
            except OSError as e:
                messagebox.showerror("CoCo monitor", f"Cannot open CSV: {e}")
                return
            ch.log_btn.configure(text="Stop logging")
        else:
            ch.logger.close()
            ch.logger = None
            ch.log_btn.configure(text="Start logging")

    def _toggle_raw_logging(self, ch: Channel) -> None:
        if ch.raw_logger is None:
            path = ch.raw_path_var.get().strip()
            if not path:
                messagebox.showerror("CoCo monitor",
                                     f"No raw path set for Ch {ch.name}")
                return
            try:
                ch.raw_logger = RawLogger(path)
            except OSError as e:
                messagebox.showerror("CoCo monitor", f"Cannot open raw file: {e}")
                return
            ch.raw_log_btn.configure(text="Stop raw")
        else:
            ch.raw_logger.close()
            ch.raw_logger = None
            ch.raw_log_btn.configure(text="Start raw")

    def _on_show_change(self, ch: Channel) -> None:
        if ch.line is not None:
            ch.line.set_visible(ch.show_var.get())

    def _on_window_change(self) -> None:
        try:
            w = int(self.window_var.get())
        except (tk.TclError, ValueError):
            return
        w = max(2, min(MAX_PLOT_SECONDS, w))
        self._window_s = w
        for ch in self.channels:
            hz = float(ch.hz_var.get()) if ch.hz_var is not None else DEFAULT_POLL_HZ
            n = int(max(2.0, hz) * w * 1.5)
            ch.times = deque(ch.times, maxlen=n)
            ch.values = deque(ch.values, maxlen=n)

    def _toggle_freeze(self) -> None:
        self._frozen.set(not self._frozen.get())
        if self._frozen.get():
            self.freeze_btn.configure(text="Unfreeze")
        else:
            # Reset the time axis so the next samples start at t=0.
            self._t0 = None
            for ch in self.channels:
                ch.times.clear()
                ch.values.clear()
            self.freeze_btn.configure(text="Freeze")

    # ---- status -------------------------------------------------------------
    def _set_status(self, ch: Channel, msg: str) -> None:
        # status callback runs from the reader thread; schedule it to the
        # Tk thread so we never touch widgets from the wrong thread.
        self.root.after(0, lambda: self.status_var.set(f"[Ch {ch.name}] {msg}"))

    # ---- queue drain / plot update -----------------------------------------
    def _drain_queues(self) -> None:
        try:
            for ch in self.channels:
                # Raw bytes -> raw logger
                while True:
                    try:
                        chunk = ch.raw_queue.get_nowait()
                    except queue.Empty:
                        break
                    if ch.raw_logger is not None:
                        ch.raw_logger.write(chunk)

                # Samples -> plot deques + CSV + readouts
                while True:
                    try:
                        s = ch.sample_queue.get_nowait()
                    except queue.Empty:
                        break

                    if self._t0 is None:
                        self._t0 = s.t

                    # Drop duplicates: 0x03 returns the same latest sample
                    # whenever the host polls faster than the sensor's
                    # internal update rate. Plotting / logging duplicates
                    # would create flat plateaus and slanted edges that
                    # look nothing like a real capnogram.
                    is_fresh = (ch.last_counter is None
                                or s.counter != ch.last_counter)
                    if is_fresh:
                        ch.fresh_total += 1
                        ch._fresh_window_n += 1
                    else:
                        ch.dup_total += 1

                    # Sensor-rate window: every 0x03 response (fresh or
                    # duplicate) marks one poll, and the counter delta
                    # between window endpoints gives the true sensor rate.
                    ch._rate_window_polls += 1
                    if ch._rate_window_c0 is None:
                        ch._rate_window_c0 = s.counter

                    ch.last_counter = s.counter
                    ch.last = s

                    if not is_fresh:
                        continue

                    if ch.logger is not None:
                        ch.logger.write(s)

                    if not self._frozen.get():
                        x = s.t - self._t0
                        y = s.co2_mmhg if s.co2_mmhg is not None else float("nan")
                        ch.times.append(x)
                        ch.values.append(y)

                # Refresh the rolling "fresh samples per second" estimate
                # roughly once per second per channel.
                now = time.monotonic()
                if ch._fresh_window_t0 == 0.0:
                    ch._fresh_window_t0 = now
                elif now - ch._fresh_window_t0 >= 1.0:
                    dt = now - ch._fresh_window_t0
                    ch.fresh_hz = ch._fresh_window_n / dt if dt > 0 else 0.0
                    ch._fresh_window_t0 = now
                    ch._fresh_window_n = 0

                # Refresh sensor-rate (counter-delta) and actual-poll rate.
                if ch._rate_window_t0 == 0.0:
                    ch._rate_window_t0 = now
                elif (now - ch._rate_window_t0 >= 1.0
                      and ch._rate_window_c0 is not None
                      and ch.last_counter is not None):
                    dt = now - ch._rate_window_t0
                    # Counter is uint32 in the wire frame; wrap defensively.
                    cdelta = (ch.last_counter - ch._rate_window_c0) & 0xFFFFFFFF
                    ch.sensor_hz = cdelta / dt if dt > 0 else 0.0
                    ch.poll_hz_actual = ch._rate_window_polls / dt if dt > 0 else 0.0
                    ch._rate_window_t0 = now
                    ch._rate_window_c0 = ch.last_counter
                    ch._rate_window_polls = 0

                # Update readouts (channel may have no new sample this tick
                # but the cached one is still valid).
                if ch.last is not None:
                    s = ch.last
                    if s.co2_mmhg is None:
                        ch.co2_var.set("CO2: invalid")
                    else:
                        ch.co2_var.set(f"CO2: {s.co2_mmhg:6.2f} mmHg")
                    if s.pressure_hpa is None:
                        ch.pres_var.set("P: invalid")
                    else:
                        ch.pres_var.set(f"P: {s.pressure_hpa:7.2f} hPa")
                    if s.temperature_c is None:
                        ch.temp_var.set("T: invalid")
                    else:
                        ch.temp_var.set(f"T: {s.temperature_c:6.2f} °C")
                    if s.flow_slm is None:
                        ch.flow_var.set("Flow: invalid")
                    else:
                        ch.flow_var.set(f"Flow: {s.flow_slm:7.3f} slm")

                if ch.reader is not None:
                    rdr = ch.reader
                    info_bits = []
                    if rdr.product_type:
                        info_bits.append(rdr.product_type)
                    if rdr.fw_version:
                        info_bits.append(f"FW {rdr.fw_version}")
                    if rdr.hw_version:
                        info_bits.append(f"HW {rdr.hw_version}")
                    ch.info_var.set(
                        "Sensor: " + (", ".join(info_bits) if info_bits else "---"))
                    ch.stats_var.set(
                        f"Rx {rdr.bytes_total} B  ok {rdr.frames_ok}"
                        f" / bad {rdr.frames_bad} / to {rdr.timeouts}"
                        f"  |  poll {ch.poll_hz_actual:5.1f} Hz"
                        f"  sensor {ch.sensor_hz:5.1f} Hz"
                        f"  fresh {ch.fresh_hz:5.1f}/s"
                        f"  dup {ch.dup_total}"
                    )
        finally:
            self.root.after(50, self._drain_queues)

    def _update_plot(self, _frame_idx):
        any_data = False
        for ch in self.channels:
            if ch.line is None:
                continue
            if ch.times:
                ch.line.set_data(list(ch.times), list(ch.values))
                any_data = True
            else:
                ch.line.set_data([], [])

        if any_data and not self._frozen.get():
            # Sliding window: show the most recent `_window_s` seconds.
            latest = max((ch.times[-1] for ch in self.channels if ch.times),
                         default=self._window_s)
            x0 = max(0.0, latest - self._window_s)
            self.ax.set_xlim(x0, x0 + self._window_s)
            # Auto-scale Y to data with a comfortable margin.
            ymin = float("inf")
            ymax = float("-inf")
            for ch in self.channels:
                if not ch.values:
                    continue
                # Use values inside the visible window only.
                for tx, vy in zip(ch.times, ch.values):
                    if tx < x0:
                        continue
                    if vy == vy:  # not NaN
                        if vy < ymin:
                            ymin = vy
                        if vy > ymax:
                            ymax = vy
            if ymin < float("inf") and ymax > float("-inf"):
                if ymax - ymin < 5:
                    ymax = ymin + 5
                self.ax.set_ylim(ymin - 2, ymax + 2)
        return [ch.line for ch in self.channels if ch.line is not None]

    # ---- shutdown -----------------------------------------------------------
    def _on_close(self) -> None:
        for ch in self.channels:
            if ch.reader is not None:
                ch.reader.stop()
            if ch.logger is not None:
                ch.logger.close()
            if ch.raw_logger is not None:
                ch.raw_logger.close()
        # Give reader threads a brief moment to send Stop Measurement and
        # close their ports cleanly.
        deadline = time.monotonic() + 1.0
        for ch in self.channels:
            if ch.reader is not None and ch.reader.is_alive():
                ch.reader.join(timeout=max(0.0, deadline - time.monotonic()))
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        # Use a slightly nicer theme where available.
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
