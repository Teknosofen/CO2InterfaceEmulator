"""
CO2 Interface Emulator - PC Monitor & Logger
============================================

Reads the Respironics Capnostat 5 protocol stream from a serial port,
displays a live scrolling CO2 waveform plus ETCO2 / Respiratory Rate /
Inspired CO2 / Status, and optionally logs all samples to a CSV file.

Protocol summary (see Documentation/ProjectDesign.md):
  - Packets have no delimiters. First byte (CMD) has bit7 set (>=0x80),
    all following bytes have bit7 clear (<0x80).
  - Layout: [CMD][NBF][data...][CHK]   NBF = bytes following CMD (incl CHK)
  - Checksum: (-sum(CMD,NBF,data...)) & 0x7F
  - Waveform packet (CMD=0x80):
        sync(1B) co2_hi(1B) co2_lo(1B) [ optional DPI bytes ] CHK
        CO2_mmHg = ((co2_hi*128 + co2_lo) - 1000) / 100.0
  - DPI types (when appended): 1=Status(5B), 2=ETCO2(2B),
        3=RespRate(2B), 4=InspiredCO2(2B). 2-byte values: hi*128 + lo.

Default serial settings: 19200 baud, 8N1 (Serial1 of the emulator,
or USB when usbmode = PROTOCOL).

Dependencies:
    pip install pyserial matplotlib
"""

from __future__ import annotations

import csv
import queue
import sys
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass
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
CMD_WAVEFORM = 0x80
CMD_NACK = 0xC8
CMD_STOP_ACK = 0xC9
CMD_ZERO_RESP = 0x82
CMD_SETTINGS_RESP = 0x84
CMD_REVISION_RESP = 0xCA
CMD_CAPS_RESP = 0xCB
CMD_RESET_NB_ACK = 0xCC

DPI_STATUS = 1
DPI_ETCO2 = 2
DPI_RR = 3
DPI_INSP = 4

DEFAULT_BAUD = 19200
WAVEFORM_HZ = 100
PLOT_SECONDS = 10                 # window width on the live graph
MAX_SAMPLES = WAVEFORM_HZ * PLOT_SECONDS

# Ambient pressure used to convert partial pressure (mmHg) to volume
# fraction (%). 1013 mbar = 1013 * 0.750062 mmHg = 759.81 mmHg.
AMBIENT_MMHG = 1013.0 * 0.750062  # ~759.81 mmHg


def mmhg_to_pct(mmhg: float) -> float:
    return mmhg / AMBIENT_MMHG * 100.0


def build_packet(cmd: int, payload: bytes = b"") -> bytes:
    """Build a Capnostat-5 packet: [CMD][NBF][payload][CHK].

    NBF counts the bytes following CMD, including the checksum.
    CHK = (-sum(CMD,NBF,payload)) & 0x7F.
    """
    nbf = len(payload) + 1
    head = bytes([cmd, nbf]) + payload
    chk = (-sum(head)) & 0x7F
    return head + bytes([chk])


# ---------------------------------------------------------------------------
# Sample container
# ---------------------------------------------------------------------------
@dataclass
class Sample:
    t: float          # PC monotonic timestamp (s)
    sync: int
    co2: float        # mmHg
    raw_co2: int = 0  # 14-bit transmitted value (before -1000 / 100)
    raw_packet: bytes = b""  # full packet bytes incl. CMD/NBF/CHK
    etco2: Optional[float] = None
    rr: Optional[float] = None
    insp: Optional[float] = None
    status1: Optional[int] = None
    status2: Optional[int] = None
    status3: Optional[int] = None


# ---------------------------------------------------------------------------
# Serial reader / packet parser (background thread)
# ---------------------------------------------------------------------------
class SerialReader(threading.Thread):
    def __init__(self, port: str, baud: int, out_queue: "queue.Queue[Sample]",
                 status_cb, raw_queue: "Optional[queue.Queue[bytes]]" = None):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.out_queue = out_queue
        self.raw_queue = raw_queue
        self.status_cb = status_cb
        self._stop = threading.Event()
        self.ser: Optional[serial.Serial] = None

        # Diagnostic counters (read by GUI, written by reader thread).
        self.bytes_total = 0
        self.packets_ok = 0
        self.packets_bad = 0

        # Outgoing command queue (host -> emulator).
        self._tx: "queue.Queue[bytes]" = queue.Queue()

        # Sticky DPI values: held until a new value of the same type arrives.
        self._etco2: Optional[float] = None
        self._rr: Optional[float] = None
        self._insp: Optional[float] = None
        self._st1: Optional[int] = None
        self._st2: Optional[int] = None
        self._st3: Optional[int] = None

    def stop(self) -> None:
        self._stop.set()

    def send(self, data: bytes) -> None:
        self._tx.put(data)

    # ---- helpers --------------------------------------------------------
    @staticmethod
    def _u14(hi: int, lo: int) -> int:
        return (hi & 0x7F) * 128 + (lo & 0x7F)

    def _parse_waveform(self, data: bytes, packet: bytes = b"") -> Optional[Sample]:
        # data = [sync, co2_hi, co2_lo, optional DPI bytes...]
        if len(data) < 3:
            return None
        sync = data[0]
        raw = self._u14(data[1], data[2])
        co2 = (raw - 1000) / 100.0

        # Walk through any appended DPI groups
        i = 3
        while i < len(data):
            dpi = data[i]
            i += 1
            if dpi == DPI_STATUS and i + 5 <= len(data):
                self._st1, self._st2, self._st3 = data[i], data[i + 1], data[i + 2]
                i += 5  # status1, status2, status3, 0, 0
            elif dpi == DPI_ETCO2 and i + 2 <= len(data):
                self._etco2 = self._u14(data[i], data[i + 1]) / 10.0  # 0.1 mmHg units
                i += 2
            elif dpi == DPI_RR and i + 2 <= len(data):
                self._rr = float(self._u14(data[i], data[i + 1]))
                i += 2
            elif dpi == DPI_INSP and i + 2 <= len(data):
                self._insp = self._u14(data[i], data[i + 1]) / 10.0
                i += 2
            else:
                break  # unknown / malformed DPI

        return Sample(
            t=time.monotonic(),
            sync=sync,
            co2=co2,
            raw_co2=raw,
            raw_packet=packet,
            etco2=self._etco2,
            rr=self._rr,
            insp=self._insp,
            status1=self._st1,
            status2=self._st2,
            status3=self._st3,
        )

    # ---- main loop ------------------------------------------------------
    def run(self) -> None:
        # Open the port. Hold RTS low before open so a CP210x/CH340 auto-reset
        # circuit (classic ESP32 boards) does not pulse EN. Then assert DTR
        # AFTER open: the ESP32-S3 native USB-CDC firmware uses DTR as the
        # "host present" signal and won't transmit while it's deasserted.
        try:
            self.ser = serial.Serial()
            self.ser.port = self.port
            self.ser.baudrate = self.baud
            self.ser.bytesize = serial.EIGHTBITS
            self.ser.parity = serial.PARITY_NONE
            self.ser.stopbits = serial.STOPBITS_ONE
            self.ser.timeout = 0.1
            self.ser.write_timeout = 0.5
            self.ser.dsrdtr = False
            self.ser.rtscts = False
            self.ser.xonxoff = False
            try:
                # Pre-open: keep RTS low to avoid an EN pulse on auto-reset boards.
                self.ser.rts = False
            except Exception:
                pass
            self.ser.open()
            try:
                # Post-open: assert DTR so USB-CDC firmware sees "host connected".
                self.ser.dtr = True
                self.ser.rts = False
            except Exception:
                pass
            self.ser.reset_input_buffer()
        except serial.SerialException as e:
            self.status_cb(f"ERROR: {e}")
            return

        self.status_cb(f"Connected to {self.port} @ {self.baud}")
        buf = bytearray()

        while not self._stop.is_set():
            # Send any pending host->emulator bytes
            try:
                while True:
                    out = self._tx.get_nowait()
                    self.ser.write(out)
            except queue.Empty:
                pass
            except serial.SerialException as e:
                self.status_cb(f"Write error: {e}")
                break

            try:
                chunk = self.ser.read(256)
            except serial.SerialException as e:
                self.status_cb(f"Serial error: {e}")
                break
            if chunk:
                buf.extend(chunk)
                self.bytes_total += len(chunk)
                if self.raw_queue is not None:
                    try:
                        self.raw_queue.put_nowait(chunk)
                    except queue.Full:
                        pass

            # Drain ALL complete packets that are already in buf before
            # going back to read() (which blocks up to 100 ms). Without
            # this inner loop a 100 Hz stream becomes ~10 Hz at the GUI
            # because read() returns bursts of bytes that contain many
            # packets, but only one was being parsed per outer iteration.
            while True:
                # Resync: drop any leading bytes without bit7 set
                while buf and (buf[0] & 0x80) == 0:
                    buf.pop(0)
                if len(buf) < 2:
                    break

                cmd = buf[0]
                nbf = buf[1]
                total = 2 + nbf  # CMD + NBF + (data + CHK)
                if nbf > 64:     # sanity: drop garbage
                    buf.pop(0)
                    self.packets_bad += 1
                    continue
                if len(buf) < total:
                    break  # wait for more bytes

                packet = bytes(buf[:total])
                del buf[:total]

                # Verify all data bytes have bit7 clear
                if any(b & 0x80 for b in packet[1:]):
                    self.packets_bad += 1
                    continue

                # Verify checksum
                if (sum(packet) & 0x7F) != 0:
                    self.packets_bad += 1
                    continue

                self.packets_ok += 1
                data = packet[2:-1]  # strip CMD, NBF, CHK
                if cmd == CMD_WAVEFORM:
                    sample = self._parse_waveform(data, packet)
                    if sample is not None:
                        try:
                            self.out_queue.put_nowait(sample)
                        except queue.Full:
                            pass
                # Other CMDs are ignored for plotting purposes.

        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.status_cb("Disconnected")


# ---------------------------------------------------------------------------
# CSV logger
# ---------------------------------------------------------------------------
class CsvLogger:
    HEADER = ["pc_time_iso", "pc_time_s", "sync", "co2_mmHg",
              "etco2_mmHg", "resp_rate_bpm", "insp_co2_mmHg",
              "status1", "status2", "status3"]

    def __init__(self, path: str):
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
            s.sync,
            f"{s.co2:.2f}",
            "" if s.etco2 is None else f"{s.etco2:.2f}",
            "" if s.rr is None else f"{s.rr:.0f}",
            "" if s.insp is None else f"{s.insp:.2f}",
            "" if s.status1 is None else s.status1,
            "" if s.status2 is None else s.status2,
            "" if s.status3 is None else s.status3,
        ])
        self.count += 1

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass


class RawLogger:
    """Append every received raw byte to a file.

    Format: one line per read chunk, with monotonic timestamp and a
    space-separated hex dump. Easy to grep / replay.
    """

    def __init__(self, path: str):
        self._fh = open(path, "w", encoding="utf-8", buffering=1)
        self._fh.write(f"# Raw capture started {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
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
class Channel:
    """Per-sensor state: serial reader, queues, plot line, loggers, UI vars.

    Two of these are owned by ``App``. They share the figure/axes but have
    independent ports, deques, files and show/hide checkboxes.
    """

    def __init__(self, name: str, color: str, default_path_prefix: str):
        self.name = name
        self.color = color
        self.default_prefix = default_path_prefix

        # Threading / IO
        self.queue: "queue.Queue[Sample]" = queue.Queue(maxsize=10000)
        self.raw_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=10000)
        self.reader: Optional[SerialReader] = None
        self.logger: Optional[CsvLogger] = None
        self.raw_logger: Optional[RawLogger] = None

        # Plot data
        self.times: deque[float] = deque(maxlen=MAX_SAMPLES)
        self.values: deque[float] = deque(maxlen=MAX_SAMPLES)
        self._last: Optional[Sample] = None

        # Diagnostics
        self._last_bytes = 0
        self._last_rate_t = 0.0
        self._samples_total = 0
        self._samples_at_last_rate = 0
        self.last_rate_text: str = ""

        # Per-channel time anchor: wall-clock X (relative to App._t0)
        # of this channel's first sample, plus the sample index at that
        # moment. Subsequent samples advance at 1/WAVEFORM_HZ regardless
        # of pyserial burst timing.
        self._t_anchor: Optional[float] = None
        self._anchor_index: int = 0

        # Tk variables (created later by App._build_ui)
        self.port_var: tk.StringVar
        self.port_cb: ttk.Combobox
        self.baud_var: tk.IntVar
        self.connect_btn: ttk.Button
        self.start_btn: ttk.Button
        self.stop_btn: ttk.Button
        self.zero_btn: ttk.Button
        self.show_var: tk.BooleanVar
        self.path_var: tk.StringVar
        self.log_btn: ttk.Button
        self.raw_path_var: tk.StringVar
        self.raw_log_btn: ttk.Button
        self.co2_var: tk.StringVar
        self.etco2_var: tk.StringVar
        self.rr_var: tk.StringVar
        self.insp_var: tk.StringVar

        # Matplotlib line, created after axes exist
        self.line = None


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Capno V logger - dual channel")
        root.geometry("1200x780")

        # Two channels. Colors picked to be distinguishable on a capnogram.
        self.channels: list[Channel] = [
            Channel("A", "#1b8a3a", "co2A"),  # green
            Channel("B", "#1f4fa8", "co2B"),  # blue
        ]

        # Shared wall-clock time origin so both channels are plotted on
        # the same X axis. Set on the first sample received from any
        # channel (see _drain_one_channel).
        self._t0: Optional[float] = None

        # Window length (seconds) is user-adjustable; deques are re-sized
        # when it changes. Default matches the original PLOT_SECONDS.
        self._window_s: int = PLOT_SECONDS
        for ch in self.channels:
            ch.times = deque(maxlen=WAVEFORM_HZ * self._window_s)
            ch.values = deque(maxlen=WAVEFORM_HZ * self._window_s)

        self.status_var = tk.StringVar(value="Idle")

        # Screen FPS tracking (independent from data rate).
        self._frames_total = 0
        self._frames_at_last_rate = 0
        self._last_rate_t = 0.0

        self._build_ui()
        self._refresh_ports()

        # Periodic queue drain (independent from animation, for CSV logging)
        self.root.after(20, self._drain_queues)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- UI construction -----------------------------------------------
    def _build_ui(self) -> None:
        # One row per channel: port, baud, connect/start/stop, show, CSV, raw
        for ch in self.channels:
            self._build_channel_row(ch)

        # Global controls row: units, window, refresh ports
        info = ttk.Frame(self.root, padding=6)
        info.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(info, text="Refresh ports",
                   command=self._refresh_ports).pack(side=tk.LEFT)

        ttk.Label(info, text="   Units:").pack(side=tk.LEFT)
        self.unit_var = tk.StringVar(value="mmHg")
        ttk.Radiobutton(info, text="mmHg", value="mmHg",
                        variable=self.unit_var,
                        command=self._on_unit_change).pack(side=tk.LEFT)
        ttk.Radiobutton(info, text="% (1013 mbar)", value="%",
                        variable=self.unit_var,
                        command=self._on_unit_change).pack(side=tk.LEFT)

        ttk.Label(info, text="   Window (s):").pack(side=tk.LEFT)
        self.window_var = tk.IntVar(value=self._window_s)
        spin = ttk.Spinbox(info, from_=2, to=300, increment=1, width=5,
                           textvariable=self.window_var,
                           command=self._on_window_change)
        spin.pack(side=tk.LEFT, padx=(2, 4))
        spin.bind("<Return>", lambda _e: self._on_window_change())
        spin.bind("<FocusOut>", lambda _e: self._on_window_change())

        # Freeze / unfreeze. While frozen, incoming samples are dropped
        # (queues are still drained to avoid backlog) and the plot stops
        # auto-scrolling. Unfreezing clears the buffers and restarts the
        # time axis at 0, so data collected during freeze is discarded.
        self._frozen = tk.BooleanVar(value=False)
        self.freeze_btn = ttk.Button(info, text="Freeze",
                                     command=self._toggle_freeze)
        self.freeze_btn.pack(side=tk.LEFT, padx=(12, 4))

        # Cursor readout panel
        self._build_cursor_panel()

        # Per-channel readouts (CO2/ETCO2/RR/InspCO2)
        for ch in self.channels:
            self._build_channel_readouts(ch)

        # Status bar
        status_entry = tk.Entry(self.root, textvariable=self.status_var,
                                relief=tk.SUNKEN,
                                readonlybackground="#eaeaea")
        status_entry.configure(state="readonly")
        status_entry.pack(side=tk.BOTTOM, fill=tk.X)

        # Plot
        self.fig = Figure(figsize=(10, 4.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("CO2 Waveform")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("CO2 (mmHg)")
        self.ax.set_ylim(-2, 60)
        self.ax.set_xlim(0, PLOT_SECONDS)
        self.ax.grid(True, alpha=0.3)
        for ch in self.channels:
            (ch.line,) = self.ax.plot([], [], color=ch.color, linewidth=1.5,
                                      label=f"Ch {ch.name}")
        self.ax.legend(loc="upper right")

        # Two draggable vertical cursors. Click on the plot to move the
        # nearest cursor; click-and-drag for fine positioning. They are
        # always visible but only useful while frozen.
        self.cur1 = self.ax.axvline(x=PLOT_SECONDS / 3.0, color="#d62728",
                                    linestyle="--", linewidth=1.5,
                                    label="Cursor 1", picker=False)
        self.cur2 = self.ax.axvline(x=2.0 * PLOT_SECONDS / 3.0,
                                    color="#ff7f0e",
                                    linestyle="--", linewidth=1.5,
                                    label="Cursor 2", picker=False)
        # Two draggable horizontal cursors for amplitude measurement.
        self.hcur1 = self.ax.axhline(y=20.0, color="#d62728",
                                     linestyle=":", linewidth=1.5,
                                     label="H1")
        self.hcur2 = self.ax.axhline(y=40.0, color="#ff7f0e",
                                     linestyle=":", linewidth=1.5,
                                     label="H2")
        # Drag state: ("v", 1) ("v", 2) ("h", 1) ("h", 2) or None.
        self._dragging: Optional[tuple[str, int]] = None

        canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas = canvas

        # Mouse handlers for cursor placement / dragging.
        canvas.mpl_connect("button_press_event", self._on_plot_press)
        canvas.mpl_connect("button_release_event", self._on_plot_release)
        canvas.mpl_connect("motion_notify_event", self._on_plot_motion)

        self.anim = FuncAnimation(self.fig, self._update_plot,
                                  interval=50, blit=False,
                                  cache_frame_data=False)

    def _build_channel_row(self, ch: Channel) -> None:
        frame = ttk.LabelFrame(self.root,
                               text=f"Channel {ch.name}",
                               padding=4)
        frame.pack(side=tk.TOP, fill=tk.X, padx=6, pady=2)

        # Row 1: port / baud / connect / send start/stop / show toggle
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
                     values=(9600, 19200, 38400, 57600, 115200)).pack(
            side=tk.LEFT, padx=(2, 8))

        ch.connect_btn = ttk.Button(r1, text="Connect",
                                    command=lambda c=ch: self._toggle_connect(c))
        ch.connect_btn.pack(side=tk.LEFT, padx=2)
        ch.start_btn = ttk.Button(r1, text="Send Start",
                                  command=lambda c=ch: self._send_start(c),
                                  state=tk.DISABLED)
        ch.start_btn.pack(side=tk.LEFT, padx=2)
        ch.stop_btn = ttk.Button(r1, text="Send Stop",
                                 command=lambda c=ch: self._send_stop(c),
                                 state=tk.DISABLED)
        ch.stop_btn.pack(side=tk.LEFT, padx=2)
        ch.zero_btn = ttk.Button(r1, text="Zero",
                                 command=lambda c=ch: self._send_zero(c),
                                 state=tk.DISABLED)
        ch.zero_btn.pack(side=tk.LEFT, padx=2)

        ch.show_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r1, text="Show curve", variable=ch.show_var,
                        command=lambda c=ch: self._on_show_change(c)).pack(
            side=tk.LEFT, padx=(10, 2))

        # Small color swatch so the user can correlate row -> trace color.
        swatch = tk.Label(r1, text="  ", background=ch.color, width=2,
                          relief=tk.SUNKEN)
        swatch.pack(side=tk.LEFT, padx=(2, 6))

        # Row 2: CSV file + raw capture file
        r2 = ttk.Frame(frame)
        r2.pack(side=tk.TOP, fill=tk.X, pady=(2, 0))

        ttk.Label(r2, text="CSV:").pack(side=tk.LEFT)
        ch.path_var = tk.StringVar(value="")
        ttk.Entry(r2, textvariable=ch.path_var, width=40).pack(
            side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        ttk.Button(r2, text="Browse...",
                   command=lambda c=ch: self._browse_path(c)).pack(side=tk.LEFT)
        ch.log_btn = ttk.Button(r2, text="Start logging",
                                command=lambda c=ch: self._toggle_logging(c))
        ch.log_btn.pack(side=tk.LEFT, padx=4)

        ttk.Label(r2, text="  Raw:").pack(side=tk.LEFT)
        ch.raw_path_var = tk.StringVar(value="")
        ttk.Entry(r2, textvariable=ch.raw_path_var, width=30).pack(
            side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        ttk.Button(r2, text="Browse...",
                   command=lambda c=ch: self._browse_raw_path(c)).pack(side=tk.LEFT)
        ch.raw_log_btn = ttk.Button(r2, text="Start raw",
                                    command=lambda c=ch: self._toggle_raw_logging(c))
        ch.raw_log_btn.pack(side=tk.LEFT, padx=4)

    def _build_channel_readouts(self, ch: Channel) -> None:
        frame = ttk.LabelFrame(self.root,
                               text=f"Channel {ch.name} readouts",
                               padding=4)
        frame.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(0, 2))

        ch.co2_var = tk.StringVar(value="CO2: --- mmHg")
        ch.etco2_var = tk.StringVar(value="ETCO2: --- mmHg")
        ch.rr_var = tk.StringVar(value="RR: --- bpm")
        ch.insp_var = tk.StringVar(value="InspCO2: --- mmHg")
        for var in (ch.co2_var, ch.etco2_var, ch.rr_var, ch.insp_var):
            e = tk.Entry(frame, textvariable=var,
                         font=("Segoe UI", 11, "bold"), width=22,
                         relief=tk.FLAT,
                         readonlybackground="#f0f0f0",
                         foreground=ch.color)
            e.configure(state="readonly")
            e.pack(side=tk.LEFT, padx=4)

    def _build_cursor_panel(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Cursors", padding=4)
        frame.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(0, 2))

        self.cur_t1_var = tk.StringVar(value="t1: ---")
        self.cur_t2_var = tk.StringVar(value="t2: ---")
        self.cur_dt_var = tk.StringVar(value="Δt: ---")
        # Horizontal cursors: absolute Y values and ΔY.
        self.cur_h1_var = tk.StringVar(value="H1: ---")
        self.cur_h2_var = tk.StringVar(value="H2: ---")
        self.cur_dh_var = tk.StringVar(value="ΔH: ---")
        # Per-channel y values at each cursor, and within-channel Δy.
        self.cur_yA1_var = tk.StringVar(value="A@1: ---")
        self.cur_yA2_var = tk.StringVar(value="A@2: ---")
        self.cur_dyA_var = tk.StringVar(value="ΔA: ---")
        self.cur_yB1_var = tk.StringVar(value="B@1: ---")
        self.cur_yB2_var = tk.StringVar(value="B@2: ---")
        self.cur_dyB_var = tk.StringVar(value="ΔB: ---")
        # Cross-channel Δy at each cursor.
        self.cur_dAB1_var = tk.StringVar(value="A-B@1: ---")
        self.cur_dAB2_var = tk.StringVar(value="A-B@2: ---")

        groups: list[tuple[str, list[tuple[tk.StringVar, str]]]] = [
            ("Time (V cursors)", [(self.cur_t1_var, "#d62728"),
                                  (self.cur_t2_var, "#ff7f0e"),
                                  (self.cur_dt_var, "#000")]),
            ("Amplitude (H cursors)", [(self.cur_h1_var, "#d62728"),
                                       (self.cur_h2_var, "#ff7f0e"),
                                       (self.cur_dh_var, "#000")]),
            ("Ch A", [(self.cur_yA1_var, self.channels[0].color),
                      (self.cur_yA2_var, self.channels[0].color),
                      (self.cur_dyA_var, self.channels[0].color)]),
            ("Ch B", [(self.cur_yB1_var, self.channels[1].color),
                      (self.cur_yB2_var, self.channels[1].color),
                      (self.cur_dyB_var, self.channels[1].color)]),
            ("A - B", [(self.cur_dAB1_var, "#000"),
                       (self.cur_dAB2_var, "#000")]),
        ]
        for label, vars_ in groups:
            sub = ttk.LabelFrame(frame, text=label, padding=2)
            sub.pack(side=tk.LEFT, padx=4)
            for var, color in vars_:
                e = tk.Entry(sub, textvariable=var,
                             font=("Consolas", 10), width=18,
                             relief=tk.FLAT,
                             readonlybackground="#f7f7f7",
                             foreground=color)
                e.configure(state="readonly")
                e.pack(side=tk.LEFT, padx=2)

        ttk.Label(frame, text=" (click on plot to set nearest cursor; "
                  "drag for fine position. Most useful when frozen.)",
                  foreground="#666").pack(side=tk.LEFT, padx=8)

    # ---- port handling --------------------------------------------------
    def _refresh_ports(self) -> None:
        ports = serial.tools.list_ports.comports()
        items = [f"{p.device} - {p.description}" for p in ports]
        used: set[str] = set()
        for ch in self.channels:
            current = ch.port_var.get()
            ch.port_cb["values"] = items
            if current in items:
                ch.port_var.set(current)
                used.add(current)
        # Auto-pick a port for any channel that still has none, avoiding
        # duplicates (two channels cannot share the same physical COM port).
        for ch in self.channels:
            if ch.port_var.get():
                continue
            for item in items:
                if item not in used:
                    ch.port_var.set(item)
                    used.add(item)
                    break

    @staticmethod
    def _selected_port(ch: Channel) -> Optional[str]:
        sel = ch.port_var.get()
        if not sel:
            return None
        return sel.split(" - ", 1)[0].strip()

    # ---- connect/disconnect --------------------------------------------
    def _toggle_connect(self, ch: Channel) -> None:
        if ch.reader is None:
            port = self._selected_port(ch)
            if not port:
                messagebox.showwarning("No port",
                                       f"Select a serial port for channel {ch.name}.")
                return
            # Prevent two channels from opening the same physical port.
            for other in self.channels:
                if other is ch:
                    continue
                if other.reader is not None and self._selected_port(other) == port:
                    messagebox.showerror(
                        "Port already in use",
                        f"Port {port} is already open on channel {other.name}.\n"
                        f"Pick a different port for channel {ch.name}.")
                    return
            ch.times.clear()
            ch.values.clear()
            ch._samples_total = 0
            ch._samples_at_last_rate = 0
            ch._last_bytes = 0
            ch._last_rate_t = time.monotonic()
            ch._t_anchor = None
            ch._anchor_index = 0
            ch.reader = SerialReader(port, int(ch.baud_var.get()),
                                     ch.queue, self._set_status,
                                     raw_queue=ch.raw_queue)
            ch.reader.start()
            ch.connect_btn.config(text="Disconnect")
            ch.start_btn.config(state=tk.NORMAL)
            ch.stop_btn.config(state=tk.NORMAL)
            ch.zero_btn.config(state=tk.NORMAL)
        else:
            ch.reader.stop()
            ch.reader = None
            ch.connect_btn.config(text="Connect")
            ch.start_btn.config(state=tk.DISABLED)
            ch.stop_btn.config(state=tk.DISABLED)
            ch.zero_btn.config(state=tk.DISABLED)
            # If no channel is connected any more, drop the shared time
            # origin so the next session starts at X=0.
            if all(c.reader is None for c in self.channels):
                self._t0 = None
                for c in self.channels:
                    c.times.clear()
                    c.values.clear()
                    c._t_anchor = None
                    c._anchor_index = 0

    def _send_start(self, ch: Channel) -> None:
        if ch.reader is not None:
            ch.reader.send(build_packet(0x80, bytes([0x00])))
            self._set_status(f"Ch {ch.name}: sent Start Waveform (0x80)")

    def _send_stop(self, ch: Channel) -> None:
        if ch.reader is not None:
            ch.reader.send(build_packet(0xC9))
            self._set_status(f"Ch {ch.name}: sent Stop Continuous (0xC9)")

    def _send_zero(self, ch: Channel) -> None:
        # Zero Calibration: CMD=0x82, no payload (see ProjectDesign.md).
        # Sensor responds with 0x82 status: 0=started, 1=compensations
        # not set, 2=already in progress. The takes ~5 s on the device.
        if ch.reader is not None:
            ch.reader.send(build_packet(0x82))
            self._set_status(
                f"Ch {ch.name}: sent Zero Calibration (0x82). "
                "Keep the sensor in room air for ~5 s.")

    def _on_show_change(self, ch: Channel) -> None:
        if ch.line is not None:
            ch.line.set_visible(ch.show_var.get())
            self.canvas.draw_idle()

    # ---- logging --------------------------------------------------------
    def _browse_path(self, ch: Channel) -> None:
        default = time.strftime(f"{ch.default_prefix}_log_%Y%m%d_%H%M%S.csv")
        path = filedialog.asksaveasfilename(
            title=f"Save channel {ch.name} log as...",
            defaultextension=".csv",
            initialfile=default,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            ch.path_var.set(path)

    def _toggle_logging(self, ch: Channel) -> None:
        if ch.logger is None:
            path = ch.path_var.get().strip()
            if not path:
                self._browse_path(ch)
                path = ch.path_var.get().strip()
                if not path:
                    return
            try:
                ch.logger = CsvLogger(path)
            except OSError as e:
                messagebox.showerror("Cannot open file", str(e))
                return
            ch.log_btn.config(text="Stop logging")
            self._set_status(f"Ch {ch.name}: logging to {path}")
        else:
            path = ch.logger.path
            count = ch.logger.count
            ch.logger.close()
            ch.logger = None
            ch.log_btn.config(text="Start logging")
            self._set_status(f"Ch {ch.name}: saved {count} samples to {path}")

    def _browse_raw_path(self, ch: Channel) -> None:
        default = time.strftime(f"{ch.default_prefix}_raw_%Y%m%d_%H%M%S.txt")
        path = filedialog.asksaveasfilename(
            title=f"Save channel {ch.name} raw capture as...",
            defaultextension=".txt",
            initialfile=default,
            filetypes=[("Text/hex files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            ch.raw_path_var.set(path)

    def _toggle_raw_logging(self, ch: Channel) -> None:
        if ch.raw_logger is None:
            path = ch.raw_path_var.get().strip()
            if not path:
                self._browse_raw_path(ch)
                path = ch.raw_path_var.get().strip()
                if not path:
                    return
            try:
                ch.raw_logger = RawLogger(path)
            except OSError as e:
                messagebox.showerror("Cannot open file", str(e))
                return
            ch.raw_log_btn.config(text="Stop raw")
            self._set_status(f"Ch {ch.name}: raw capture to {path}")
        else:
            path = ch.raw_logger.path
            count = ch.raw_logger.bytes
            ch.raw_logger.close()
            ch.raw_logger = None
            ch.raw_log_btn.config(text="Start raw")
            self._set_status(f"Ch {ch.name}: saved {count} raw bytes to {path}")

    # ---- queue/plot -----------------------------------------------------
    def _drain_queues(self) -> None:
        for ch in self.channels:
            self._drain_one_channel(ch)
        self._update_readouts()
        self._update_status_line()
        self.root.after(20, self._drain_queues)

    def _drain_one_channel(self, ch: Channel) -> None:
        # Raw bytes first so capture file has byte-for-byte fidelity
        if ch.raw_logger is not None:
            try:
                while True:
                    chunk = ch.raw_queue.get_nowait()
                    try:
                        ch.raw_logger.write(chunk)
                    except Exception as e:
                        self._set_status(f"Ch {ch.name}: raw write error: {e}")
                        ch.raw_logger.close()
                        ch.raw_logger = None
                        ch.raw_log_btn.config(text="Start raw")
                        break
            except queue.Empty:
                pass
        else:
            try:
                while True:
                    ch.raw_queue.get_nowait()
            except queue.Empty:
                pass

        try:
            while True:
                s = ch.queue.get_nowait()
                ch._samples_total += 1
                # While frozen, drain queues to prevent backlog but
                # discard the data and skip the plot update.
                if self._frozen.get():
                    if ch.logger is not None:
                        try:
                            ch.logger.write(s)
                        except Exception:
                            pass
                    ch._last = s
                    continue
                # Time base: shared wall-clock origin (t0, set by the
                # first sample on any channel) so channels align in
                # real time, BUT each channel advances by a fixed
                # 1 / WAVEFORM_HZ per sample from its own first-sample
                # anchor. This gives uniform sample spacing within each
                # trace (no burst-clumping from pyserial) while still
                # keeping the two channels on the same X axis.
                if self._t0 is None:
                    self._t0 = s.t
                if ch._t_anchor is None:
                    ch._t_anchor = s.t - self._t0
                    ch._anchor_index = ch._samples_total
                x = ch._t_anchor + (ch._samples_total - ch._anchor_index) / WAVEFORM_HZ
                ch.times.append(x)
                ch.values.append(s.co2)
                ch._last = s
                if ch.logger is not None:
                    try:
                        ch.logger.write(s)
                    except Exception as e:
                        self._set_status(f"Ch {ch.name}: log write error: {e}")
                        ch.logger.close()
                        ch.logger = None
                        ch.log_btn.config(text="Start logging")
        except queue.Empty:
            pass

    def _update_readouts(self) -> None:
        use_pct = self.unit_var.get() == "%"
        unit_lbl = "%" if use_pct else "mmHg"
        conv = mmhg_to_pct if use_pct else (lambda x: x)
        fmt = "{:5.2f}" if use_pct else "{:5.1f}"
        for ch in self.channels:
            s = ch._last
            if s is None:
                continue
            ch.co2_var.set(f"CO2: {fmt.format(conv(s.co2))} {unit_lbl}")
            ch.etco2_var.set(
                "ETCO2: ---" if s.etco2 is None
                else f"ETCO2: {fmt.format(conv(s.etco2))} {unit_lbl}")
            ch.rr_var.set(
                "RR: ---" if s.rr is None else f"RR: {s.rr:3.0f} bpm")
            ch.insp_var.set(
                "InspCO2: ---" if s.insp is None
                else f"InspCO2: {fmt.format(conv(s.insp))} {unit_lbl}")

    def _update_status_line(self) -> None:
        # Refresh diagnostic line ~2 Hz.
        now = time.monotonic()
        dt = now - self._last_rate_t
        if dt < 0.5:
            return
        frames = self._frames_total - self._frames_at_last_rate
        fps = frames / dt if dt > 0 else 0.0
        self._frames_at_last_rate = self._frames_total
        self._last_rate_t = now

        parts: list[str] = []
        for ch in self.channels:
            if ch.reader is None:
                parts.append(f"Ch{ch.name}: --")
                continue
            delta_b = ch.reader.bytes_total - ch._last_bytes
            samp = ch._samples_total - ch._samples_at_last_rate
            byte_rate = delta_b / dt if dt > 0 else 0.0
            samp_rate = samp / dt if dt > 0 else 0.0
            ch._last_bytes = ch.reader.bytes_total
            ch._samples_at_last_rate = ch._samples_total
            parts.append(
                f"Ch{ch.name}: {byte_rate:.0f} B/s "
                f"ok={ch.reader.packets_ok} bad={ch.reader.packets_bad} "
                f"{samp_rate:.0f} Hz")
        parts.append(f"screen={fps:.1f} fps")
        self._set_status("  |  ".join(parts))

    def _update_plot(self, _frame):
        self._frames_total += 1
        use_pct = self.unit_var.get() == "%"
        any_data = False
        all_vals: list[float] = []
        x_max = 0.0
        for ch in self.channels:
            if not ch.times:
                if ch.line is not None:
                    ch.line.set_data([], [])
                continue
            xs = list(ch.times)
            ys = list(ch.values)
            if use_pct:
                ys = [mmhg_to_pct(v) for v in ys]
            ch.line.set_data(xs, ys)
            if ch.show_var.get():
                all_vals.extend(ys)
                x_max = max(x_max, xs[-1])
            any_data = True

        if not any_data:
            return tuple(c.line for c in self.channels)

        if not self._frozen.get():
            x_min = max(0.0, x_max - self._window_s)
            self.ax.set_xlim(x_min, max(x_min + self._window_s, x_max))
            # Keep both cursors inside the visible window so they don't
            # scroll off-screen as new data arrives.
            self._ensure_cursors_visible(x_min, max(x_min + self._window_s,
                                                    x_max))

        # Y range. Defaults like single-channel version.
        if use_pct:
            default_max = mmhg_to_pct(60.0)
            default_min = mmhg_to_pct(-2.0)
            margin_hi, margin_lo = 0.5, 0.25
        else:
            default_max = 60.0
            default_min = 0.0
            margin_hi, margin_lo = 5.0, 2.0
        if all_vals:
            ymax = max(default_max, max(all_vals) + margin_hi)
            ymin = min(default_min, min(all_vals) - margin_lo)
        else:
            ymax = default_max
            ymin = default_min
        self.ax.set_ylim(ymin, ymax)
        self._update_cursor_readouts()
        self.canvas.draw_idle()
        return tuple(c.line for c in self.channels)

    # ---- misc -----------------------------------------------------------
    def _set_status(self, msg: str) -> None:
        self.root.after(0, lambda: self.status_var.set(msg))

    def _on_unit_change(self) -> None:
        unit = self.unit_var.get()
        # Convert horizontal-cursor Y positions to the new unit so they
        # keep representing the same physical CO2 level.
        old_was_pct = getattr(self, "_last_unit", "mmHg") == "%"
        new_is_pct = unit == "%"
        if old_was_pct != new_is_pct:
            for hcur in (self.hcur1, self.hcur2):
                y = float(hcur.get_ydata()[0])
                if new_is_pct:        # mmHg -> %
                    y = mmhg_to_pct(y)
                else:                 # % -> mmHg
                    y = y * AMBIENT_MMHG / 100.0
                hcur.set_ydata([y, y])
        self._last_unit = unit
        if unit == "%":
            self.ax.set_ylabel("CO2 (%)")
        else:
            self.ax.set_ylabel("CO2 (mmHg)")
        self.canvas.draw_idle()

    def _on_window_change(self) -> None:
        try:
            new_s = int(self.window_var.get())
        except (tk.TclError, ValueError):
            return
        new_s = max(2, min(300, new_s))
        if new_s == self._window_s:
            return
        self._window_s = new_s
        new_max = WAVEFORM_HZ * new_s
        for ch in self.channels:
            ch.times = deque(ch.times, maxlen=new_max)
            ch.values = deque(ch.values, maxlen=new_max)
        self.ax.set_xlabel(f"Time (s)  [window = {new_s} s]")
        self.canvas.draw_idle()

    # ---- freeze / cursors ----------------------------------------------
    def _toggle_freeze(self) -> None:
        now_frozen = not self._frozen.get()
        self._frozen.set(now_frozen)
        if now_frozen:
            self.freeze_btn.config(text="Unfreeze")
            self._set_status("Frozen. Data during freeze is discarded.")
        else:
            self.freeze_btn.config(text="Freeze")
            # Discard buffered data and restart the time axis at 0 so
            # presentation continues from "now".
            self._t0 = None
            for ch in self.channels:
                ch.times.clear()
                ch.values.clear()
                ch._t_anchor = None
                ch._anchor_index = 0
                # Drain any queued samples so the first new sample is
                # truly "now".
                try:
                    while True:
                        ch.queue.get_nowait()
                except queue.Empty:
                    pass
            self._set_status("Resumed.")
        self.canvas.draw_idle()

    def _on_plot_press(self, event) -> None:
        if event.inaxes is not self.ax or event.xdata is None:
            return
        # Pick the cursor (vertical or horizontal) closest to the click,
        # using fractional axes coordinates so X (seconds) and Y (mmHg
        # or %) are comparable.
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        xspan = max(1e-9, x1 - x0)
        yspan = max(1e-9, y1 - y0)
        fx = (event.xdata - x0) / xspan
        fy = (event.ydata - y0) / yspan

        candidates: list[tuple[float, tuple[str, int]]] = []
        for which, line in ((1, self.cur1), (2, self.cur2)):
            cx = float(line.get_xdata()[0])
            candidates.append((abs(((cx - x0) / xspan) - fx), ("v", which)))
        for which, line in ((1, self.hcur1), (2, self.hcur2)):
            cy = float(line.get_ydata()[0])
            candidates.append((abs(((cy - y0) / yspan) - fy), ("h", which)))
        candidates.sort(key=lambda c: c[0])
        self._dragging = candidates[0][1]
        self._drag_to(event)

    def _on_plot_release(self, _event) -> None:
        self._dragging = None

    def _on_plot_motion(self, event) -> None:
        if self._dragging is None:
            return
        if event.inaxes is not self.ax or event.xdata is None:
            return
        self._drag_to(event)

    def _drag_to(self, event) -> None:
        kind, which = self._dragging
        if kind == "v":
            line = self.cur1 if which == 1 else self.cur2
            line.set_xdata([event.xdata, event.xdata])
        else:
            line = self.hcur1 if which == 1 else self.hcur2
            line.set_ydata([event.ydata, event.ydata])
        self._update_cursor_readouts()
        self.canvas.draw_idle()

    def _ensure_cursors_visible(self, x_min: float, x_max: float) -> None:
        """Place cursors inside [x_min, x_max] if they currently fall outside.

        Used after the X axis scrolls so the user doesn't lose track of
        them. Cursor 1 is parked 1/3 from the left, Cursor 2 at 2/3.
        Cursors are left alone if they are already in view.
        """
        span = x_max - x_min
        x1 = float(self.cur1.get_xdata()[0])
        x2 = float(self.cur2.get_xdata()[0])
        if not (x_min <= x1 <= x_max):
            self.cur1.set_xdata([x_min + span / 3.0, x_min + span / 3.0])
        if not (x_min <= x2 <= x_max):
            self.cur2.set_xdata([x_min + 2.0 * span / 3.0,
                                 x_min + 2.0 * span / 3.0])

    @staticmethod
    def _interp(xs: list[float], ys: list[float],
                x: float) -> Optional[float]:
        if not xs or x < xs[0] or x > xs[-1]:
            return None
        # Linear search is fine for the small buffers we keep on screen.
        # Find index i with xs[i] <= x <= xs[i+1].
        for i in range(len(xs) - 1):
            if xs[i] <= x <= xs[i + 1]:
                x0, x1 = xs[i], xs[i + 1]
                if x1 == x0:
                    return ys[i]
                frac = (x - x0) / (x1 - x0)
                return ys[i] + frac * (ys[i + 1] - ys[i])
        return ys[-1]

    def _update_cursor_readouts(self) -> None:
        t1 = float(self.cur1.get_xdata()[0])
        t2 = float(self.cur2.get_xdata()[0])
        use_pct = self.unit_var.get() == "%"
        unit_lbl = "%" if use_pct else "mmHg"
        fmt = "{:6.2f}" if use_pct else "{:6.1f}"

        self.cur_t1_var.set(f"t1: {t1:7.3f} s")
        self.cur_t2_var.set(f"t2: {t2:7.3f} s")
        self.cur_dt_var.set(f"Δt: {t2 - t1:7.3f} s")

        # Horizontal cursors. They live in the *displayed* unit
        # (Y axis is already mmHg or %), so no conversion is needed.
        h1 = float(self.hcur1.get_ydata()[0])
        h2 = float(self.hcur2.get_ydata()[0])
        self.cur_h1_var.set(f"H1: {fmt.format(h1)} {unit_lbl}")
        self.cur_h2_var.set(f"H2: {fmt.format(h2)} {unit_lbl}")
        self.cur_dh_var.set(f"ΔH: {fmt.format(h2 - h1)} {unit_lbl}")

        def y_at(ch: Channel, t: float) -> Optional[float]:
            v = self._interp(list(ch.times), list(ch.values), t)
            if v is None:
                return None
            return mmhg_to_pct(v) if use_pct else v

        ch_a, ch_b = self.channels[0], self.channels[1]
        yA1, yA2 = y_at(ch_a, t1), y_at(ch_a, t2)
        yB1, yB2 = y_at(ch_b, t1), y_at(ch_b, t2)

        def show(var: tk.StringVar, label: str, val: Optional[float]) -> None:
            if val is None:
                var.set(f"{label}: ---")
            else:
                var.set(f"{label}: {fmt.format(val)} {unit_lbl}")

        show(self.cur_yA1_var, "A@1", yA1)
        show(self.cur_yA2_var, "A@2", yA2)
        show(self.cur_dyA_var, "ΔA",
             None if yA1 is None or yA2 is None else yA2 - yA1)
        show(self.cur_yB1_var, "B@1", yB1)
        show(self.cur_yB2_var, "B@2", yB2)
        show(self.cur_dyB_var, "ΔB",
             None if yB1 is None or yB2 is None else yB2 - yB1)
        show(self.cur_dAB1_var, "A-B@1",
             None if yA1 is None or yB1 is None else yA1 - yB1)
        show(self.cur_dAB2_var, "A-B@2",
             None if yA2 is None or yB2 is None else yA2 - yB2)

    def _on_close(self) -> None:
        for ch in self.channels:
            if ch.reader is not None:
                ch.reader.stop()
            if ch.logger is not None:
                ch.logger.close()
            if ch.raw_logger is not None:
                ch.raw_logger.close()
        self.root.destroy()


# ---------------------------------------------------------------------------
def main() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
