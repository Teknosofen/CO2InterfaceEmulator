"""
Capno + CoCo combined monitor / logger
======================================

Single-window tool that simultaneously streams ONE Respironics Capnostat 5
(Capno V) channel and ONE Sensirion CoCo channel, displays both on stacked
live plots, and logs each to its own CSV (plus optional raw byte capture).

The two channels run independently with their own serial port, baud rate
and natural sample rate:

  * Capno channel - pushed by the CO2 Interface Emulator at 100 Hz over
    19200 8N1 (Respironics protocol). Uses ``co2_monitor.SerialReader``.
  * CoCo channel  - host polls / drains the Sensirion CoCo at up to
    250 Hz over 115200 8N1 (SHDLC).  Uses ``coco_monitor.CocoReader``.
    Buffered mode (0x04) drains every sample; polled mode (0x03) returns
    only the latest one per request.

Mixed sample rates are fine - timestamps and CSV files are kept per
channel, plotted on independent axes that share the same wall-clock X.

Dependencies (same as the two standalone tools):
    pip install pyserial matplotlib
"""

from __future__ import annotations

import os
import queue
import sys
import time
import tkinter as tk
from collections import deque
from tkinter import filedialog, messagebox, ttk
from typing import Optional

# Reuse the proven parsers/readers/loggers from the standalone tools.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import co2_monitor as cap   # Capnostat 5 protocol
import coco_monitor as coc  # CoCo SHDLC protocol

import serial.tools.list_ports
from matplotlib.animation import FuncAnimation
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


# ---------------------------------------------------------------------------
# Display / window configuration
# ---------------------------------------------------------------------------
DEFAULT_PLOT_SECONDS = 10
MAX_PLOT_SECONDS = 600

# Per-axis ring-buffer size, sized for each sensor's worst-case rate so
# the live window can keep ``MAX_PLOT_SECONDS`` of data even when the
# user widens the time window after the run started.
CAP_BUF_LEN = cap.WAVEFORM_HZ * MAX_PLOT_SECONDS
COC_BUF_LEN = int(coc.NOMINAL_SENSOR_HZ * MAX_PLOT_SECONDS)


def _port_from_combobox(text: str) -> str:
    """Recover a bare device name from a ``\"COMx - <description>\"`` entry.

    The port combobox stores "device + description" for readability;
    pyserial only wants the device, so we strip the description back off
    here. Accepts a plain device name too (returned unchanged).
    """
    if not text:
        return ""
    return text.split(" - ", 1)[0].strip()


# ---------------------------------------------------------------------------
# Channel wrappers - one per sensor
# ---------------------------------------------------------------------------
class CapnoChannel:
    """Capnostat 5 (Capno V) channel."""

    name = "Capno V"
    color = "#1b8a3a"  # green

    def __init__(self) -> None:
        self.queue: "queue.Queue[cap.Sample]" = queue.Queue(maxsize=20000)
        self.raw_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=20000)
        self.reader: Optional[cap.SerialReader] = None
        self.logger: Optional[cap.CsvLogger] = None
        self.raw_logger: Optional[cap.RawLogger] = None

        self.times: deque[float] = deque(maxlen=CAP_BUF_LEN) 
        self.values: deque[float] = deque(maxlen=CAP_BUF_LEN)
        self.last: Optional[cap.Sample] = None

        # Per-channel rate accounting (samples/s actually arrived at PC).
        self._rate_t0: float = 0.0
        self._rate_n: int = 0
        self.measured_hz: float = 0.0

        # De-burst time anchor. pyserial.read() returns chunks every
        # ~100 ms containing many packets that share an essentially
        # identical ``time.monotonic()`` value - which on a plot looks
        # like ~110 ms dropouts. The sensor's ``sync`` byte is a perfect
        # per-sample counter (mod 128, bit7 always 0), so we rebuild a
        # monotonic 32-bit sample index from it and stamp every sample
        # with ``anchor_t + index/WAVEFORM_HZ``. The first sample's
        # arrival time is the anchor.
        self._anchor_t: Optional[float] = None
        self._anchor_index: int = 0
        self._abs_index: int = 0
        self._prev_sync: Optional[int] = None

        # Tk vars created by App._build_capno_row
        self.port_var: tk.StringVar
        self.port_cb: ttk.Combobox
        self.baud_var: tk.IntVar
        self.connect_btn: ttk.Button
        self.log_btn: ttk.Button
        self.path_var: tk.StringVar
        self.raw_log_btn: ttk.Button
        self.raw_path_var: tk.StringVar
        self.co2_var: tk.StringVar
        self.etco2_var: tk.StringVar
        self.rr_var: tk.StringVar
        self.insp_var: tk.StringVar
        self.stats_var: tk.StringVar
        self.line = None  # matplotlib Line2D

    # ---- IO control -----------------------------------------------------
    def start(self, status_cb) -> bool:
        port = _port_from_combobox(self.port_var.get())
        if not port:
            messagebox.showerror(self.name, "Pick a serial port first.")
            return False
        self.reader = cap.SerialReader(
            port=port,
            baud=int(self.baud_var.get()),
            out_queue=self.queue,
            status_cb=status_cb,
            raw_queue=self.raw_queue,
        )
        self.reader.start()
        return True

    def stop(self) -> None:
        if self.reader is not None:
            self.reader.stop()
            self.reader.join(timeout=2.0)
            self.reader = None
        self._close_loggers()
        self.reset_time_anchor()

    def _close_loggers(self) -> None:
        if self.logger is not None:
            self.logger.close()
            self.logger = None
        if self.raw_logger is not None:
            self.raw_logger.close()
            self.raw_logger = None

    # ---- per-sample handling -------------------------------------------
    def on_sample(self, s: cap.Sample) -> None:
        # Replace the bursty PC timestamp from pyserial with a smooth
        # per-sample timestamp derived from the sensor's ``sync``
        # counter. This restores the true 100 Hz cadence in both the
        # live plot and the CSV log without throwing away any real
        # samples (we verified the sync stream is gap-free).
        if self._anchor_t is None:
            self._anchor_t = s.t
            self._anchor_index = 0
            self._abs_index = 0
            self._prev_sync = s.sync
        else:
            # sync is 7-bit (0..127) and increments by 1 per sample.
            delta = (s.sync - self._prev_sync) & 0x7F
            if delta == 0:
                # Same sync = duplicate packet (shouldn't happen in
                # practice). Keep current index; do not re-log.
                return
            self._abs_index += delta
            self._prev_sync = s.sync
        s.t = self._anchor_t + (
            self._abs_index - self._anchor_index) / float(cap.WAVEFORM_HZ)

        self.last = s
        if self._rate_t0 == 0.0:
            self._rate_t0 = s.t
        self._rate_n += 1
        dt = s.t - self._rate_t0
        if dt >= 1.0:
            self.measured_hz = self._rate_n / dt
            self._rate_t0 = s.t
            self._rate_n = 0
        if self.logger is not None:
            try:
                self.logger.write(s)
            except Exception:
                pass

    def reset_time_anchor(self) -> None:
        """Drop the time anchor so the next sample restarts the timeline.

        Called on disconnect so reconnecting doesn't carry stale state.
        """
        self._anchor_t = None
        self._anchor_index = 0
        self._abs_index = 0
        self._prev_sync = None


class CoCoChannel:
    """Sensirion CoCo channel."""

    name = "CoCo"
    color = "#1f4fa8"  # blue

    def __init__(self) -> None:
        self.queue: "queue.Queue[coc.Sample]" = queue.Queue(maxsize=20000)
        self.raw_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=20000)
        self.reader: Optional[coc.CocoReader] = None
        self.logger: Optional[coc.CsvLogger] = None
        self.raw_logger: Optional[coc.RawLogger] = None

        self.times: deque[float] = deque(maxlen=COC_BUF_LEN)
        self.values: deque[float] = deque(maxlen=COC_BUF_LEN)
        self.last: Optional[coc.Sample] = None

        # Sensor-counter based diagnostics. The CoCo's internal counter
        # increments once per acquired sample (nominally 250 Hz) so the
        # delta gives the TRUE sensor rate even when our poll rate is
        # lower. ``measured_hz`` here is the unique-sample rate at the
        # host (what actually gets logged).
        self.last_counter: Optional[int] = None
        self._rate_t0: float = 0.0
        self._rate_n: int = 0
        self.measured_hz: float = 0.0
        self._sensor_t0: float = 0.0
        self._sensor_c0: Optional[int] = None
        self.sensor_hz: float = 0.0

        # Tk vars (built in App._build_coco_row)
        self.port_var: tk.StringVar
        self.port_cb: ttk.Combobox
        self.baud_var: tk.IntVar
        self.addr_var: tk.IntVar
        self.hz_var: tk.DoubleVar
        self.mode_var: tk.StringVar
        self.connect_btn: ttk.Button
        self.log_btn: ttk.Button
        self.path_var: tk.StringVar
        self.raw_log_btn: ttk.Button
        self.raw_path_var: tk.StringVar
        self.co2_var: tk.StringVar
        self.pres_var: tk.StringVar
        self.temp_var: tk.StringVar
        self.flow_var: tk.StringVar
        self.stats_var: tk.StringVar
        self.line = None

    def start(self, status_cb) -> bool:
        port = _port_from_combobox(self.port_var.get())
        if not port:
            messagebox.showerror(self.name, "Pick a serial port first.")
            return False
        self.reader = coc.CocoReader(
            port=port,
            baud=int(self.baud_var.get()),
            addr=int(self.addr_var.get()),
            poll_hz=float(self.hz_var.get()),
            out_queue=self.queue,
            status_cb=status_cb,
            raw_queue=self.raw_queue,
            mode=self.mode_var.get(),
        )
        self.reader.start()
        return True

    def stop(self) -> None:
        if self.reader is not None:
            self.reader.stop()
            self.reader.join(timeout=3.0)
            self.reader = None
        self._close_loggers()

    def _close_loggers(self) -> None:
        if self.logger is not None:
            self.logger.close()
            self.logger = None
        if self.raw_logger is not None:
            self.raw_logger.close()
            self.raw_logger = None

    def on_sample(self, s: coc.Sample) -> None:
        # De-duplicate polled-mode reads where the sensor counter has not
        # advanced (host polled faster than sensor produced new data).
        is_fresh = (self.last_counter is None) or (s.counter != self.last_counter)
        if not is_fresh:
            return
        self.last_counter = s.counter
        self.last = s

        # Host-side unique-sample rate (matches the logged CSV cadence).
        if self._rate_t0 == 0.0:
            self._rate_t0 = s.t
        self._rate_n += 1
        dt = s.t - self._rate_t0
        if dt >= 1.0:
            self.measured_hz = self._rate_n / dt
            self._rate_t0 = s.t
            self._rate_n = 0

        # True sensor rate via counter delta.
        if self._sensor_c0 is None:
            self._sensor_c0 = s.counter
            self._sensor_t0 = s.t
        else:
            dt_s = s.t - self._sensor_t0
            if dt_s >= 1.0:
                dc = (s.counter - self._sensor_c0) & 0xFFFFFFFF
                self.sensor_hz = dc / dt_s
                self._sensor_c0 = s.counter
                self._sensor_t0 = s.t

        if self.logger is not None:
            try:
                self.logger.write(s)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Capno + CoCo combined monitor")
        root.geometry("1280x860")

        self.capno = CapnoChannel()
        self.coco = CoCoChannel()
        self._t0 = time.monotonic()
        self._window_s = DEFAULT_PLOT_SECONDS
        self._frozen = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Idle")

        self._build_ui()
        self._refresh_ports()

        self.root.after(30, self._drain_queues)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # =============== UI =================================================
    def _build_ui(self) -> None:
        self._build_capno_row()
        self._build_coco_row()

        # Common controls
        info = ttk.Frame(self.root, padding=6)
        info.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(info, text="Refresh ports",
                   command=self._refresh_ports).pack(side=tk.LEFT)

        # Unified both-channels controls
        self.both_connect_btn = ttk.Button(
            info, text="Connect both", command=self._toggle_both_connect)
        self.both_connect_btn.pack(side=tk.LEFT, padx=(12, 4))

        self.both_log_btn = ttk.Button(
            info, text="Log both \u2192 folder\u2026",
            command=self._toggle_both_logs)
        self.both_log_btn.pack(side=tk.LEFT, padx=4)
        self.both_log_dir_var = tk.StringVar()
        ttk.Label(info, textvariable=self.both_log_dir_var, width=34,
                  foreground="#666").pack(side=tk.LEFT, padx=(4, 8))

        ttk.Label(info, text="   Window (s):").pack(side=tk.LEFT)
        self.window_var = tk.IntVar(value=self._window_s)
        spin = ttk.Spinbox(info, from_=2, to=MAX_PLOT_SECONDS, increment=1,
                           width=5, textvariable=self.window_var,
                           command=self._on_window_change)
        spin.pack(side=tk.LEFT, padx=(2, 8))
        spin.bind("<Return>", lambda _e: self._on_window_change())
        spin.bind("<FocusOut>", lambda _e: self._on_window_change())
        ttk.Checkbutton(info, text="Freeze plot",
                        variable=self._frozen).pack(side=tk.LEFT, padx=8)

        ttk.Label(info, textvariable=self.status_var,
                  foreground="#555").pack(side=tk.LEFT, padx=12)

        self._build_readouts()
        self._build_cursor_panel()
        self._build_plot()

    def _build_capno_row(self) -> None:
        ch = self.capno
        row = ttk.LabelFrame(self.root, text=f"{ch.name} channel", padding=6)
        row.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(6, 2))

        ttk.Label(row, text="Port:").pack(side=tk.LEFT)
        ch.port_var = tk.StringVar()
        ch.port_cb = ttk.Combobox(row, textvariable=ch.port_var,
                                  width=38, state="readonly")
        ch.port_cb.pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(row, text="Baud:").pack(side=tk.LEFT)
        ch.baud_var = tk.IntVar(value=cap.DEFAULT_BAUD)
        ttk.Combobox(row, textvariable=ch.baud_var, width=8,
                     values=(9600, 19200, 38400, 57600, 115200, 230400),
                     state="readonly").pack(side=tk.LEFT, padx=(2, 8))

        ch.connect_btn = ttk.Button(row, text="Connect",
                                    command=self._toggle_capno)
        ch.connect_btn.pack(side=tk.LEFT, padx=(0, 4))

        # Zero calibration (CMD 0x82). Sensor must be in room air for ~5 s.
        ch.zero_btn = ttk.Button(row, text="Zero",
                                 command=self._send_capno_zero,
                                 state=tk.DISABLED)
        ch.zero_btn.pack(side=tk.LEFT, padx=(0, 12))

        ch.path_var = tk.StringVar()
        ch.log_btn = ttk.Button(row, text="Start CSV log",
                                command=self._toggle_capno_log)
        ch.log_btn.pack(side=tk.LEFT)
        ttk.Label(row, textvariable=ch.path_var, width=32,
                  foreground="#666").pack(side=tk.LEFT, padx=(4, 12))

        ch.raw_path_var = tk.StringVar()
        ch.raw_log_btn = ttk.Button(row, text="Start raw log",
                                    command=self._toggle_capno_raw)
        ch.raw_log_btn.pack(side=tk.LEFT)
        ttk.Label(row, textvariable=ch.raw_path_var, width=24,
                  foreground="#666").pack(side=tk.LEFT, padx=(4, 0))

    def _build_coco_row(self) -> None:
        ch = self.coco
        row = ttk.LabelFrame(self.root, text=f"{ch.name} channel", padding=6)
        row.pack(side=tk.TOP, fill=tk.X, padx=6, pady=2)

        ttk.Label(row, text="Port:").pack(side=tk.LEFT)
        ch.port_var = tk.StringVar()
        ch.port_cb = ttk.Combobox(row, textvariable=ch.port_var,
                                  width=38, state="readonly")
        ch.port_cb.pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(row, text="Baud:").pack(side=tk.LEFT)
        ch.baud_var = tk.IntVar(value=coc.DEFAULT_BAUD)
        ttk.Combobox(row, textvariable=ch.baud_var, width=8,
                     values=(9600, 19200, 38400, 57600, 115200, 230400),
                     state="readonly").pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(row, text="Addr:").pack(side=tk.LEFT)
        ch.addr_var = tk.IntVar(value=coc.SLAVE_ADDR_DEFAULT)
        ttk.Spinbox(row, from_=0, to=255, width=4,
                    textvariable=ch.addr_var).pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(row, text="Mode:").pack(side=tk.LEFT)
        ch.mode_var = tk.StringVar(value=coc.MODE_BUFFERED)
        ttk.Combobox(row, textvariable=ch.mode_var, width=9,
                     values=(coc.MODE_POLLED, coc.MODE_BUFFERED),
                     state="readonly").pack(side=tk.LEFT, padx=(2, 8))

        ttk.Label(row, text="Poll Hz:").pack(side=tk.LEFT)
        ch.hz_var = tk.DoubleVar(value=float(coc.DEFAULT_POLL_HZ))
        ttk.Spinbox(row, from_=1, to=coc.MAX_POLL_HZ, increment=1, width=6,
                    textvariable=ch.hz_var).pack(side=tk.LEFT, padx=(2, 8))

        ch.connect_btn = ttk.Button(row, text="Connect",
                                    command=self._toggle_coco)
        ch.connect_btn.pack(side=tk.LEFT, padx=(0, 12))

        ch.path_var = tk.StringVar()
        ch.log_btn = ttk.Button(row, text="Start CSV log",
                                command=self._toggle_coco_log)
        ch.log_btn.pack(side=tk.LEFT)
        ttk.Label(row, textvariable=ch.path_var, width=28,
                  foreground="#666").pack(side=tk.LEFT, padx=(4, 12))

        ch.raw_path_var = tk.StringVar()
        ch.raw_log_btn = ttk.Button(row, text="Start raw log",
                                    command=self._toggle_coco_raw)
        ch.raw_log_btn.pack(side=tk.LEFT)
        ttk.Label(row, textvariable=ch.raw_path_var, width=20,
                  foreground="#666").pack(side=tk.LEFT, padx=(4, 0))

    def _build_readouts(self) -> None:
        ro = ttk.Frame(self.root, padding=(6, 0))
        ro.pack(side=tk.TOP, fill=tk.X)

        # Capno readouts
        cap_f = ttk.LabelFrame(ro, text="Capno V", padding=4)
        cap_f.pack(side=tk.LEFT, padx=(0, 8))
        self.capno.co2_var = tk.StringVar(value="CO2: -- mmHg")
        self.capno.etco2_var = tk.StringVar(value="EtCO2: --")
        self.capno.rr_var = tk.StringVar(value="RR: --")
        self.capno.insp_var = tk.StringVar(value="InspCO2: --")
        self.capno.stats_var = tk.StringVar(value="rate: --")
        for var in (self.capno.co2_var, self.capno.etco2_var,
                    self.capno.rr_var, self.capno.insp_var,
                    self.capno.stats_var):
            ttk.Label(cap_f, textvariable=var,
                      foreground=self.capno.color).pack(side=tk.LEFT, padx=6)

        # CoCo readouts
        coc_f = ttk.LabelFrame(ro, text="CoCo", padding=4)
        coc_f.pack(side=tk.LEFT)
        self.coco.co2_var = tk.StringVar(value="CO2: -- mmHg")
        self.coco.pres_var = tk.StringVar(value="P: -- hPa")
        self.coco.temp_var = tk.StringVar(value="T: -- °C")
        self.coco.flow_var = tk.StringVar(value="Flow: -- slm")
        self.coco.stats_var = tk.StringVar(value="rate: --")
        for var in (self.coco.co2_var, self.coco.pres_var,
                    self.coco.temp_var, self.coco.flow_var,
                    self.coco.stats_var):
            ttk.Label(coc_f, textvariable=var,
                      foreground=self.coco.color).pack(side=tk.LEFT, padx=6)

    def _build_plot(self) -> None:
        # Both sensors plot CO2 in mmHg, so share a single axes for direct
        # visual comparison.
        self.fig = Figure(figsize=(11, 5.4), dpi=100)
        self.ax = self.fig.add_subplot(1, 1, 1)
        self.ax.set_title("CO2 - Capno V vs CoCo", fontsize=10, loc="left")
        self.ax.set_xlabel("Time [s]")
        self.ax.set_ylabel("CO2 [mmHg]")
        self.ax.set_xlim(0, self._window_s)
        self.ax.set_ylim(-2, 80)
        self.ax.grid(True, alpha=0.3)
        (self.capno.line,) = self.ax.plot(
            [], [], color=self.capno.color, lw=1.2, label="Capno V")
        (self.coco.line,) = self.ax.plot(
            [], [], color=self.coco.color, lw=1.2, label="CoCo")

        # Two draggable vertical cursors (time) and two horizontal cursors
        # (amplitude). Click on the plot to move the nearest cursor; click
        # and drag for fine positioning. Most useful while frozen.
        w = self._window_s
        self.cur1 = self.ax.axvline(x=w / 3.0, color="#d62728",
                                    linestyle="--", linewidth=1.5,
                                    label="t1")
        self.cur2 = self.ax.axvline(x=2.0 * w / 3.0, color="#ff7f0e",
                                    linestyle="--", linewidth=1.5,
                                    label="t2")
        self.hcur1 = self.ax.axhline(y=20.0, color="#d62728",
                                     linestyle=":", linewidth=1.5,
                                     label="H1")
        self.hcur2 = self.ax.axhline(y=10.0, color="#ff7f0e",
                                     linestyle=":", linewidth=1.5,
                                     label="H2")
        self._dragging: Optional[tuple[str, int]] = None

        self.ax.legend(loc="upper right", fontsize=8, ncol=3)
        self.fig.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH,
                                         expand=True, padx=6, pady=6)

        self.canvas.mpl_connect("button_press_event", self._on_plot_press)
        self.canvas.mpl_connect("button_release_event", self._on_plot_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_plot_motion)

        self.anim = FuncAnimation(self.fig, self._on_frame,
                                  interval=50, blit=False,
                                  cache_frame_data=False)

    def _build_cursor_panel(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Cursors", padding=4)
        frame.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(0, 2))

        self.cur_t1_var = tk.StringVar(value="t1: ---")
        self.cur_t2_var = tk.StringVar(value="t2: ---")
        self.cur_dt_var = tk.StringVar(value="\u0394t: ---")
        # Amplitude (H) cursor StringVars hold a bare numeric value so the
        # user can edit the entries directly (Enter / focus-out to apply).
        # NOTE: the cursor panel is built before the plot, so we can't
        # query the axhlines yet - use the same defaults set in
        # ``_build_plot`` (H1=20, H2=10 mmHg).
        self.cur_h1_var = tk.StringVar(value="20.0")
        self.cur_h2_var = tk.StringVar(value="10.0")
        self.cur_dh_var = tk.StringVar(value="---")
        self.cur_cap1_var = tk.StringVar(value="Capno@1: ---")
        self.cur_cap2_var = tk.StringVar(value="Capno@2: ---")
        self.cur_dcap_var = tk.StringVar(value="\u0394Capno: ---")
        self.cur_coc1_var = tk.StringVar(value="CoCo@1: ---")
        self.cur_coc2_var = tk.StringVar(value="CoCo@2: ---")
        self.cur_dcoc_var = tk.StringVar(value="\u0394CoCo: ---")
        self.cur_dCC1_var = tk.StringVar(value="Cap-CoCo@1: ---")
        self.cur_dCC2_var = tk.StringVar(value="Cap-CoCo@2: ---")

        groups: list[tuple[str, list[tuple[tk.StringVar, str]]]] = [
            ("Time (V cursors)", [(self.cur_t1_var, "#d62728"),
                                  (self.cur_t2_var, "#ff7f0e"),
                                  (self.cur_dt_var, "#000")]),
            ("Capno", [(self.cur_cap1_var, self.capno.color),
                       (self.cur_cap2_var, self.capno.color),
                       (self.cur_dcap_var, self.capno.color)]),
            ("CoCo", [(self.cur_coc1_var, self.coco.color),
                      (self.cur_coc2_var, self.coco.color),
                      (self.cur_dcoc_var, self.coco.color)]),
            ("Cap - CoCo", [(self.cur_dCC1_var, "#000"),
                            (self.cur_dCC2_var, "#000")]),
        ]

        # Amplitude (H) group first - its entries are editable so the user
        # can type a value directly. Press Enter (or click away) to apply.
        amp_sub = ttk.LabelFrame(frame, text="Amplitude (H cursors)",
                                 padding=2)
        amp_sub.pack(side=tk.LEFT, padx=4)
        self._h_entries: dict[int, tk.Entry] = {}
        for which, var, color in ((1, self.cur_h1_var, "#d62728"),
                                  (2, self.cur_h2_var, "#ff7f0e")):
            ttk.Label(amp_sub, text=f"H{which}:",
                      foreground=color).pack(side=tk.LEFT)
            e = tk.Entry(amp_sub, textvariable=var,
                         font=("Consolas", 10), width=7,
                         justify=tk.RIGHT, foreground=color)
            e.pack(side=tk.LEFT, padx=(2, 0))
            ttk.Label(amp_sub, text="mmHg",
                      foreground=color).pack(side=tk.LEFT, padx=(2, 6))
            e.bind("<Return>",
                   lambda _e, w=which: self._apply_hcur_entry(w))
            e.bind("<FocusOut>",
                   lambda _e, w=which: self._apply_hcur_entry(w))
            self._h_entries[which] = e
        ttk.Label(amp_sub, text="\u0394H:",
                  foreground="#000").pack(side=tk.LEFT)
        dh_e = tk.Entry(amp_sub, textvariable=self.cur_dh_var,
                        font=("Consolas", 10), width=8,
                        justify=tk.RIGHT,
                        relief=tk.FLAT, readonlybackground="#f7f7f7")
        dh_e.configure(state="readonly")
        dh_e.pack(side=tk.LEFT, padx=(2, 2))
        ttk.Label(amp_sub, text="mmHg").pack(side=tk.LEFT)

        for label, vars_ in groups:
            sub = ttk.LabelFrame(frame, text=label, padding=2)
            sub.pack(side=tk.LEFT, padx=4)
            for var, color in vars_:
                e = tk.Entry(sub, textvariable=var,
                             font=("Consolas", 10), width=16,
                             relief=tk.FLAT,
                             readonlybackground="#f7f7f7",
                             foreground=color)
                e.configure(state="readonly")
                e.pack(side=tk.LEFT, padx=2)

    def _apply_hcur_entry(self, which: int) -> None:
        """Parse the H1/H2 entry and move the matching axhline."""
        var = self.cur_h1_var if which == 1 else self.cur_h2_var
        line = self.hcur1 if which == 1 else self.hcur2
        try:
            y = float(var.get())
        except (ValueError, tk.TclError):
            # Bad input - restore the entry to the line's current value.
            var.set(f"{float(line.get_ydata()[0]):.1f}")
            return
        line.set_ydata([y, y])
        var.set(f"{y:.1f}")
        self._update_cursor_readouts()
        self.canvas.draw_idle()

    # ---- cursor mouse handlers -----------------------------------------
    def _on_plot_press(self, event) -> None:
        if event.inaxes is not self.ax or event.xdata is None:
            return
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

    @staticmethod
    def _interp(xs, ys, x: float) -> Optional[float]:
        if not xs or x < xs[0] or x > xs[-1]:
            return None
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
        self.cur_t1_var.set(f"t1: {t1:7.3f} s")
        self.cur_t2_var.set(f"t2: {t2:7.3f} s")
        self.cur_dt_var.set(f"\u0394t: {t2 - t1:7.3f} s")

        h1 = float(self.hcur1.get_ydata()[0])
        h2 = float(self.hcur2.get_ydata()[0])
        # Only push H1/H2 into the editable entries when the user is not
        # currently typing in them, so keystrokes are never clobbered by
        # the animation timer.
        focus = self.root.focus_get()
        if self._h_entries.get(1) is not focus:
            self.cur_h1_var.set(f"{h1:.1f}")
        if self._h_entries.get(2) is not focus:
            self.cur_h2_var.set(f"{h2:.1f}")
        self.cur_dh_var.set(f"{h2 - h1:.1f}")

        def y_at(ch, t):
            return self._interp(list(ch.times), list(ch.values), t)

        cap1, cap2 = y_at(self.capno, t1), y_at(self.capno, t2)
        coc1, coc2 = y_at(self.coco, t1), y_at(self.coco, t2)

        def show(var, label, val):
            if val is None:
                var.set(f"{label}: ---")
            else:
                var.set(f"{label}: {val:6.1f} mmHg")

        show(self.cur_cap1_var, "Capno@1", cap1)
        show(self.cur_cap2_var, "Capno@2", cap2)
        show(self.cur_dcap_var, "\u0394Capno",
             None if cap1 is None or cap2 is None else cap2 - cap1)
        show(self.cur_coc1_var, "CoCo@1", coc1)
        show(self.cur_coc2_var, "CoCo@2", coc2)
        show(self.cur_dcoc_var, "\u0394CoCo",
             None if coc1 is None or coc2 is None else coc2 - coc1)
        show(self.cur_dCC1_var, "Cap-CoCo@1",
             None if cap1 is None or coc1 is None else cap1 - coc1)
        show(self.cur_dCC2_var, "Cap-CoCo@2",
             None if cap2 is None or coc2 is None else cap2 - coc2)

    def _ensure_cursors_visible(self, x_min: float, x_max: float) -> None:
        span = x_max - x_min
        x1 = float(self.cur1.get_xdata()[0])
        x2 = float(self.cur2.get_xdata()[0])
        if not (x_min <= x1 <= x_max):
            self.cur1.set_xdata([x_min + span / 3.0, x_min + span / 3.0])
        if not (x_min <= x2 <= x_max):
            self.cur2.set_xdata([x_min + 2.0 * span / 3.0,
                                 x_min + 2.0 * span / 3.0])

    # =============== Common helpers =====================================
    def _refresh_ports(self) -> None:
        # Show device + human-readable description so a user with multiple
        # USB adapters can tell which COM port is which. The string the
        # combobox stores is ``"COMx - <description>"``; ``_port_from_combobox``
        # strips that back down to just the device name when opening the
        # serial port. Two channels cannot share the same physical port,
        # so we also avoid auto-picking a duplicate.
        ports = serial.tools.list_ports.comports()
        items = [f"{p.device} - {p.description}" for p in ports]
        used: set[str] = set()
        for ch in (self.capno, self.coco):
            ch.port_cb["values"] = items
            current = ch.port_var.get()
            if current in items:
                used.add(current)
            else:
                ch.port_var.set("")
        for ch in (self.capno, self.coco):
            if ch.port_var.get():
                continue
            for item in items:
                if item not in used:
                    ch.port_var.set(item)
                    used.add(item)
                    break
        self._set_status(f"Found {len(items)} serial port(s)")

    def _on_window_change(self) -> None:
        try:
            self._window_s = max(2, int(self.window_var.get()))
        except (tk.TclError, ValueError):
            return

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _ts(self) -> str:
        return time.strftime("%Y%m%d_%H%M%S")

    # =============== Capno control ======================================
    def _toggle_capno(self) -> None:
        ch = self.capno
        if ch.reader is None:
            if ch.start(self._make_status_cb(ch.name)):
                ch.connect_btn.config(text="Disconnect")
                ch.zero_btn.config(state=tk.NORMAL)
                self._set_status(f"{ch.name}: connecting to {ch.port_var.get()}")
        else:
            ch.stop()
            ch.connect_btn.config(text="Connect")
            ch.zero_btn.config(state=tk.DISABLED)
            ch.log_btn.config(text="Start CSV log")
            ch.raw_log_btn.config(text="Start raw log")
            self._set_status(f"{ch.name}: disconnected")

    def _send_capno_zero(self) -> None:
        # Zero Calibration: CMD=0x82, no payload. Sensor takes ~5 s.
        ch = self.capno
        if ch.reader is None:
            return
        ch.reader.send(cap.build_packet(0x82))
        self._set_status(
            f"{ch.name}: sent Zero Calibration (0x82). "
            "Keep the sensor in room air for ~5 s.")

    def _toggle_capno_log(self) -> None:
        ch = self.capno
        if ch.logger is None:
            path = filedialog.asksaveasfilename(
                title=f"{ch.name} CSV log",
                defaultextension=".csv",
                initialfile=f"capno_log_{self._ts()}.csv",
                filetypes=(("CSV files", "*.csv"), ("All", "*.*")))
            if not path:
                return
            try:
                ch.logger = cap.CsvLogger(path)
            except OSError as e:
                messagebox.showerror(ch.name, f"Could not open log: {e}")
                return
            ch.path_var.set(os.path.basename(path))
            ch.log_btn.config(text="Stop CSV log")
            self._set_status(f"{ch.name}: logging to {path}")
        else:
            n = ch.logger.count
            ch.logger.close()
            ch.logger = None
            ch.log_btn.config(text="Start CSV log")
            self._set_status(f"{ch.name}: log closed ({n} rows)")

    def _toggle_capno_raw(self) -> None:
        ch = self.capno
        if ch.raw_logger is None:
            path = filedialog.asksaveasfilename(
                title=f"{ch.name} raw capture",
                defaultextension=".raw.txt",
                initialfile=f"capno_raw_{self._ts()}.raw.txt",
                filetypes=(("Raw hex", "*.raw.txt"), ("All", "*.*")))
            if not path:
                return
            try:
                ch.raw_logger = cap.RawLogger(path)
            except OSError as e:
                messagebox.showerror(ch.name, f"Could not open raw log: {e}")
                return
            ch.raw_path_var.set(os.path.basename(path))
            ch.raw_log_btn.config(text="Stop raw log")
        else:
            n = ch.raw_logger.bytes
            ch.raw_logger.close()
            ch.raw_logger = None
            ch.raw_log_btn.config(text="Start raw log")
            self._set_status(f"{ch.name}: raw log closed ({n} bytes)")

    # =============== CoCo control =======================================
    def _toggle_coco(self) -> None:
        ch = self.coco
        if ch.reader is None:
            if ch.start(self._make_status_cb(ch.name)):
                ch.connect_btn.config(text="Disconnect")
                self._set_status(
                    f"{ch.name}: connecting to {ch.port_var.get()} "
                    f"(mode={ch.mode_var.get()})")
        else:
            ch.stop()
            ch.connect_btn.config(text="Connect")
            ch.log_btn.config(text="Start CSV log")
            ch.raw_log_btn.config(text="Start raw log")
            ch.last_counter = None
            self._set_status(f"{ch.name}: disconnected")

    def _toggle_coco_log(self) -> None:
        ch = self.coco
        if ch.logger is None:
            path = filedialog.asksaveasfilename(
                title=f"{ch.name} CSV log",
                defaultextension=".csv",
                initialfile=f"coco_log_{self._ts()}.csv",
                filetypes=(("CSV files", "*.csv"), ("All", "*.*")))
            if not path:
                return
            try:
                ch.logger = coc.CsvLogger(path)
            except OSError as e:
                messagebox.showerror(ch.name, f"Could not open log: {e}")
                return
            ch.path_var.set(os.path.basename(path))
            ch.log_btn.config(text="Stop CSV log")
            self._set_status(f"{ch.name}: logging to {path}")
        else:
            n = ch.logger.count
            ch.logger.close()
            ch.logger = None
            ch.log_btn.config(text="Start CSV log")
            self._set_status(f"{ch.name}: log closed ({n} rows)")

    def _toggle_coco_raw(self) -> None:
        ch = self.coco
        if ch.raw_logger is None:
            path = filedialog.asksaveasfilename(
                title=f"{ch.name} raw capture",
                defaultextension=".raw.txt",
                initialfile=f"coco_raw_{self._ts()}.raw.txt",
                filetypes=(("Raw hex", "*.raw.txt"), ("All", "*.*")))
            if not path:
                return
            try:
                ch.raw_logger = coc.RawLogger(path)
            except OSError as e:
                messagebox.showerror(ch.name, f"Could not open raw log: {e}")
                return
            ch.raw_path_var.set(os.path.basename(path))
            ch.raw_log_btn.config(text="Stop raw log")
        else:
            n = ch.raw_logger.bytes
            ch.raw_logger.close()
            ch.raw_logger = None
            ch.raw_log_btn.config(text="Start raw log")
            self._set_status(f"{ch.name}: raw log closed ({n} bytes)")

    # =============== Both-channel unified control =======================
    def _toggle_both_connect(self) -> None:
        """Connect or disconnect both channels in one click.

        If either channel is currently disconnected we treat this as a
        "Connect both" press and start the disconnected one(s); otherwise
        we stop both. This is forgiving when only one channel happens to
        be configured.
        """
        any_off = (self.capno.reader is None) or (self.coco.reader is None)
        if any_off:
            if self.capno.reader is None and self.capno.port_var.get():
                self._toggle_capno()
            if self.coco.reader is None and self.coco.port_var.get():
                self._toggle_coco()
            if (self.capno.reader is not None and
                    self.coco.reader is not None):
                self.both_connect_btn.config(text="Disconnect both")
        else:
            self._toggle_capno()
            self._toggle_coco()
            self.both_connect_btn.config(text="Connect both")

    def _toggle_both_logs(self) -> None:
        """Start (or stop) CSV logging on BOTH channels into one folder.

        A directory is picked once; filenames are auto-generated with a
        shared timestamp so the two CSVs of the same session are easy to
        pair up afterwards:
            <folder>/capno_log_YYYYMMDD_HHMMSS.csv
            <folder>/coco_log_YYYYMMDD_HHMMSS.csv
        Pressing the button again closes both logs.
        """
        both_active = (self.capno.logger is not None
                       and self.coco.logger is not None)
        if both_active:
            cap_rows = self.capno.logger.count
            coc_rows = self.coco.logger.count
            self.capno.logger.close(); self.capno.logger = None
            self.coco.logger.close();  self.coco.logger = None
            self.capno.log_btn.config(text="Start CSV log")
            self.coco.log_btn.config(text="Start CSV log")
            self.both_log_btn.config(text="Log both \u2192 folder\u2026")
            self._set_status(
                f"Both logs closed (Capno {cap_rows} rows, "
                f"CoCo {coc_rows} rows)")
            return

        # Start: close any single-channel log already open so we don't
        # leak file handles, then open a fresh pair in one folder.
        for ch in (self.capno, self.coco):
            if ch.logger is not None:
                ch.logger.close()
                ch.logger = None
                ch.log_btn.config(text="Start CSV log")

        folder = filedialog.askdirectory(
            title="Choose folder for paired Capno + CoCo CSV logs")
        if not folder:
            return
        ts = self._ts()
        cap_path = os.path.join(folder, f"capno_log_{ts}.csv")
        coc_path = os.path.join(folder, f"coco_log_{ts}.csv")
        try:
            self.capno.logger = cap.CsvLogger(cap_path)
        except OSError as e:
            messagebox.showerror("Capno log", f"Could not open log: {e}")
            return
        try:
            self.coco.logger = coc.CsvLogger(coc_path)
        except OSError as e:
            self.capno.logger.close()
            self.capno.logger = None
            messagebox.showerror("CoCo log", f"Could not open log: {e}")
            return

        self.capno.path_var.set(os.path.basename(cap_path))
        self.coco.path_var.set(os.path.basename(coc_path))
        self.capno.log_btn.config(text="Stop CSV log")
        self.coco.log_btn.config(text="Stop CSV log")
        self.both_log_btn.config(text="Stop both logs")
        self.both_log_dir_var.set(folder)
        self._set_status(f"Logging both channels to {folder}")

    # =============== Reader status callback =============================
    def _make_status_cb(self, who: str):
        def cb(msg: str) -> None:
            # Reader threads call this from non-UI threads; schedule the
            # UI update on the Tk main loop.
            self.root.after(0, lambda: self._set_status(f"{who}: {msg}"))
        return cb

    # =============== Queue draining & plot refresh ======================
    def _drain_queues(self) -> None:
        # Capno
        try:
            while True:
                s = self.capno.queue.get_nowait()
                self.capno.on_sample(s)
                self.capno.times.append(s.t - self._t0)
                self.capno.values.append(s.co2)
        except queue.Empty:
            pass
        try:
            while True:
                chunk = self.capno.raw_queue.get_nowait()
                if self.capno.raw_logger is not None:
                    self.capno.raw_logger.write(chunk)
        except queue.Empty:
            pass

        # CoCo
        try:
            while True:
                s = self.coco.queue.get_nowait()
                pre_counter = self.coco.last_counter
                self.coco.on_sample(s)
                # on_sample drops duplicates, so only add to plot when fresh
                if self.coco.last_counter != pre_counter and s.co2_mmhg is not None:
                    self.coco.times.append(s.t - self._t0)
                    self.coco.values.append(s.co2_mmhg)
        except queue.Empty:
            pass
        try:
            while True:
                chunk = self.coco.raw_queue.get_nowait()
                if self.coco.raw_logger is not None:
                    self.coco.raw_logger.write(chunk)
        except queue.Empty:
            pass

        self._update_readouts()
        self._update_cursor_readouts()
        self.root.after(30, self._drain_queues)

    def _update_readouts(self) -> None:
        s = self.capno.last
        if s is not None:
            self.capno.co2_var.set(f"CO2: {s.co2:5.1f} mmHg")
            self.capno.etco2_var.set(
                "EtCO2: --" if s.etco2 is None else f"EtCO2: {s.etco2:4.1f}")
            self.capno.rr_var.set(
                "RR: --" if s.rr is None else f"RR: {s.rr:4.0f}")
            self.capno.insp_var.set(
                "InspCO2: --" if s.insp is None else f"InspCO2: {s.insp:4.1f}")
        self.capno.stats_var.set(f"rate: {self.capno.measured_hz:5.1f} Hz")

        s2 = self.coco.last
        if s2 is not None:
            self.coco.co2_var.set(
                "CO2: -- mmHg" if s2.co2_mmhg is None
                else f"CO2: {s2.co2_mmhg:5.1f} mmHg")
            self.coco.pres_var.set(
                "P: --" if s2.pressure_hpa is None
                else f"P: {s2.pressure_hpa:6.1f} hPa")
            self.coco.temp_var.set(
                "T: --" if s2.temperature_c is None
                else f"T: {s2.temperature_c:5.2f} °C")
            self.coco.flow_var.set(
                "Flow: --" if s2.flow_slm is None
                else f"Flow: {s2.flow_slm:6.3f} slm")
        self.coco.stats_var.set(
            f"host: {self.coco.measured_hz:5.1f} Hz  "
            f"sensor: {self.coco.sensor_hz:5.1f} Hz")

        # Keep unified buttons in sync with individual state.
        both_connected = (self.capno.reader is not None
                          and self.coco.reader is not None)
        self.both_connect_btn.config(
            text="Disconnect both" if both_connected else "Connect both")
        both_logging = (self.capno.logger is not None
                        and self.coco.logger is not None)
        self.both_log_btn.config(
            text="Stop both logs" if both_logging
            else "Log both \u2192 folder\u2026")

    def _on_frame(self, _frame):
        if self._frozen.get():
            return (self.capno.line, self.coco.line)

        now = time.monotonic() - self._t0
        x0 = max(0.0, now - self._window_s)
        x1 = x0 + self._window_s
        self.ax.set_xlim(x0, x1)

        ys_all: list[float] = []
        for ch in (self.capno, self.coco):
            if ch.times and ch.line is not None:
                ch.line.set_data(list(ch.times), list(ch.values))
                ys_all.extend(v for t, v in zip(ch.times, ch.values)
                              if t >= x0)
        if ys_all:
            lo = min(ys_all)
            hi = max(ys_all)
            pad = max(2.0, (hi - lo) * 0.15)
            self.ax.set_ylim(lo - pad, hi + pad)

        self._ensure_cursors_visible(x0, x1)
        return (self.capno.line, self.coco.line)

    # =============== Shutdown ==========================================
    def _on_close(self) -> None:
        try:
            self.capno.stop()
        except Exception:
            pass
        try:
            self.coco.stop()
        except Exception:
            pass
        self.root.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
