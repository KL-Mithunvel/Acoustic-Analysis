"""Test Tile: connect the striker Nano and the microphone, strike a tile, see how it rang and how it grades.

    1 Connect   the Nano (USB serial) and the microphone; flash the Nano's firmware if it is blank
    2 Strike    "Strike now" (one manual strike) or "A tile is coming" (auto: the distance sensor decides)
    3 Result    a big verdict, the reasons, and the waveform / spectrum / fade of that strike

Thin on purpose: the link is ``io/nano_link``, the microphone ring ``io/audio_ring``, the analysis
``tile_test.analyse_strike``, saving ``io/strike_log`` (the saved tests open in the labelling tool). Hardware
callbacks only put things on a queue; the Tk thread does the rest. The link, ring and port-list factories are
class attributes so tests can swap in fakes.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import numpy as np

from ..config import repo_root, resolve_path
from ..io.audio_ring import AudioRing
from ..io.nano_flash import FlashError, Flasher
from ..io.nano_link import NanoLink, serial_ports
from ..io.strike_log import StrikeLogger
from ..label_model import load_wav
from ..strike_reference import ReferenceError as RefError, StrikeReference
from ..tile_test import analyse_strike, is_graded_source
from .plots import draw_strike_overview
from .screens import _Base
from .screens_live import _devices
from .theme import ACCENT, BAD, FG, FG_DIM, FG_MUTE, OK, WARN, mono_font, ui_font
from .widgets import MplPanel

_VERDICT = {                      # grade -> (colour, one line of meaning)
    "GOOD": (OK, "Sounds like your good tiles"),
    "BORDERLINE": (WARN, "A little different from your good tiles"),
    "DEFECTIVE": (BAD, "Sounds clearly different from your good tiles"),
    "RETEST": (WARN, "Not a clean strike - try again"),
    "UNGRADED": (FG_DIM, "Heard and analysed, but no reference to compare with yet"),
    "NO TILE": (FG_DIM, "The distance sensor saw no tile under the striker"),
}
_HISTORY_MAX = 200


def _db(level: float) -> float:
    return 20.0 * float(np.log10(max(level, 1e-9)))


class TesterScreen(_Base):
    title = "Test Tile"

    link_factory = staticmethod(lambda cfg: NanoLink(cfg))
    ring_factory = staticmethod(lambda cfg, device: AudioRing(cfg, device))
    ports_fn = staticmethod(serial_ports)

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self.cfg = ctx.state.cfg
        self.link = self.link_factory(self.cfg)
        self.ring = None
        self.logger: StrikeLogger | None = None
        self.q: queue.Queue = queue.Queue()
        self.reference: StrikeReference | None = None
        self._pending = 0                      # clips being cut right now
        self._rows = 0
        self.results: list[dict] = []          # every analysed strike this run (newest last)
        self._build()
        self._load_reference()
        self.after(50, self._pump)

    # ------------------------------------------------------------------ paths and reference
    def _path(self, key: str, default: str) -> Path:
        try:
            return resolve_path(self.cfg, key)
        except KeyError:
            return Path(self.cfg["paths"]["data_dir"]) / default

    def _load_reference(self) -> None:
        p = self._path("strike_reference", "strike_reference.json")
        try:
            self.reference = StrikeReference.load(p) if p.is_file() else None
        except RefError:
            self.reference = None
        self.ref_var.set(f"Sound reference: built from {self.reference.n_good} good tiles" if self.reference
                         else "Sound reference: none yet - tests are analysed but not graded")

    # ------------------------------------------------------------------ layout
    def _build(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        left = ttk.Frame(self, width=340)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        left.grid_propagate(False)
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_left(left)
        self._build_right(right)
        self.status = tk.StringVar(value="Plug in the Nano and the microphone, then press Connect.")
        ttk.Label(self, textvariable=self.status, style="Dim.TLabel", wraplength=900).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _card(self, parent, head):
        c = ttk.Frame(parent, style="Card.TFrame", padding=10)
        c.pack(fill="x", pady=(0, 8))
        ttk.Label(c, text=head, style="CardH.TLabel").pack(anchor="w")
        return c

    def _build_left(self, left):
        c = self._card(left, "1   CONNECT")
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=(6, 2))
        ttk.Label(row, text="Striker (Nano)", style="Card.TLabel", width=14).pack(side="left")
        self.port = ttk.Combobox(row, width=18, state="readonly")
        self.port.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="↻", width=3, command=self._refresh_ports).pack(side="left", padx=(4, 0))
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Microphone", style="Card.TLabel", width=14).pack(side="left")
        self.mic = ttk.Combobox(row, width=22, state="readonly")
        self.mic.pack(side="left", fill="x", expand=True)
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=(6, 2))
        self.connect_btn = ttk.Button(row, text="Connect", style="Accent.TButton", command=self._toggle_connect)
        self.connect_btn.pack(side="left")
        ttk.Button(row, text="Flash firmware…", command=self._flash).pack(side="left", padx=6)
        self.link_var = tk.StringVar(value="Striker: not connected")
        self.link_lbl = ttk.Label(c, textvariable=self.link_var, style="Card.TLabel", font=ui_font(10, "bold"))
        self.link_lbl.pack(anchor="w", pady=(6, 0))
        self.tof_var = tk.StringVar(value="Tile sensor: -")
        ttk.Label(c, textvariable=self.tof_var, style="Card.TLabel").pack(anchor="w")
        self.level = ttk.Progressbar(c, maximum=1.0)
        self.level.pack(fill="x", pady=(6, 0))
        self.level_var = tk.StringVar(value="Microphone: off")
        ttk.Label(c, textvariable=self.level_var, style="Card.TLabel").pack(anchor="w")

        c = self._card(left, "2   STRIKE")
        self.strike_btn = ttk.Button(c, text="Strike now", style="Accent.TButton", command=self._strike_now)
        self.strike_btn.pack(fill="x", pady=(6, 2))
        ttk.Label(c, text="One manual strike. Put the tile under the striker first.", style="Card.TLabel",
                  wraplength=300).pack(anchor="w")
        self.auto_btn = ttk.Button(c, text="A tile is coming (auto)", command=self._tile_coming)
        self.auto_btn.pack(fill="x", pady=(8, 2))
        ttk.Label(c, text="Raises the striker; when the sensor sees a tile it strikes about 2 s later.",
                  style="Card.TLabel", wraplength=300).pack(anchor="w")
        self.stop_btn = ttk.Button(c, text="Stop striker", style="Danger.TButton", command=self._stop_striker)
        self.stop_btn.pack(fill="x", pady=(8, 2))
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="Hold power", style="Card.TLabel").pack(side="left")
        self.hold = tk.DoubleVar(value=float(self.cfg["striker"]["hold_pct"]))
        sc = ttk.Scale(row, from_=10, to=60, variable=self.hold, length=130)
        sc.pack(side="left", padx=6)
        sc.bind("<ButtonRelease-1>", lambda _e: self._apply_hold())
        self.hold_lbl = ttk.Label(row, text=f"{self.hold.get():.0f} %", style="Card.TLabel")
        self.hold_lbl.pack(side="left")

        c = self._card(left, "3   MORE")
        self.save_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(c, text="Save every test so I can label it", variable=self.save_var).pack(anchor="w", pady=(4, 2))
        ttk.Button(c, text="Analyse a recording (WAV)…", command=self._analyse_file).pack(fill="x", pady=2)
        ttk.Button(c, text="Open the labelling tool", command=self._open_labelling).pack(fill="x", pady=2)
        self.ref_var = tk.StringVar(value="")
        ttk.Label(c, textvariable=self.ref_var, style="Card.TLabel", wraplength=300).pack(anchor="w", pady=(6, 0))

    def _build_right(self, right):
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        v = ttk.Frame(right, style="Card.TFrame", padding=12)
        v.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.verdict = ttk.Label(v, text="Waiting for a strike", font=ui_font(30, "bold"), style="Card.TLabel",
                                 foreground=FG_MUTE)
        self.verdict.pack(anchor="w")
        self.meaning = ttk.Label(v, text="", style="Card.TLabel", font=ui_font(11), wraplength=760)
        self.meaning.pack(anchor="w")
        self.reasons = ttk.Label(v, text="", style="Card.TLabel", foreground=FG_DIM, wraplength=760, justify="left")
        self.reasons.pack(anchor="w", pady=(4, 0))
        self.plot = MplPanel(right, figsize=(6.0, 2.7))
        self.plot.grid(row=1, column=0, sticky="nsew")
        self.tree = ttk.Treeview(right, columns=("tile", "verdict", "bright", "fade", "saved"), show="tree headings",
                                 height=5, selectmode="browse")
        for col, w, t in (("#0", 80, "time"), ("tile", 90, "tile sensor"), ("verdict", 100, "verdict"),
                          ("bright", 110, "brightness Hz"), ("fade", 100, "fade 20 dB ms"), ("saved", 90, "saved as")):
            self.tree.heading(col, text=t)
            self.tree.column(col, width=w, anchor="w" if col == "#0" else "center")
        for g, (colour, _m) in _VERDICT.items():
            self.tree.tag_configure(g, foreground=colour)
        self.tree.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected())

    # ------------------------------------------------------------------ connect / disconnect
    def _refresh_ports(self):
        try:
            ports = self.ports_fn(self.cfg)
        except Exception as exc:  # noqa: BLE001 - pyserial missing or the OS refused
            ports = []
            self.status.set(f"Could not list serial ports: {exc}")
        self._ports = ports
        self.port["values"] = [f"{p['device']}  {p['description']}".strip() for p in ports]
        if ports and not self.port.get():
            self.port.current(next((i for i, p in enumerate(ports) if p["candidate"]), 0))
        devs = _devices()
        self.mic["values"] = [f"{d['index']}: {d['name']}" for d in devs] if devs else ["(no microphone available)"]
        if not self.mic.get():
            want = self.cfg["audio"].get("device")
            idx = next((i for i, d in enumerate(devs or []) if d["index"] == want), 0)
            self.mic.current(idx)

    def _port_device(self) -> str | None:
        t = self.port.get().strip()
        return t.split()[0] if t else None

    def _mic_index(self):
        t = self.mic.get()
        return int(t.split(":")[0]) if t[:1].isdigit() else None

    def _toggle_connect(self):
        if self.link.connected or self.ring is not None:
            self._disconnect()
            return
        port = self._port_device()
        if not port:
            self.status.set("No serial port chosen. Plug the Nano in and press ↻.")
            return
        try:
            self.link.connect(port)
        except Exception as exc:  # noqa: BLE001
            self.status.set(f"Could not open {port}: {exc}")
            return
        msg = f"Connected to {port}. The Nano restarts when the port opens - keep clear of the striker."
        try:
            self.ring = self.ring_factory(self.cfg, self._mic_index())
            self.ring.start()
        except Exception as exc:  # noqa: BLE001
            self.ring = None
            msg += f"  The microphone did not start ({exc}): strikes can be made but not recorded."
        self.status.set(msg)
        self.connect_btn.configure(text="Disconnect")

    def _disconnect(self):
        try:
            self.link.disconnect()
        finally:
            if self.ring is not None:
                try:
                    self.ring.stop()
                except Exception:  # noqa: BLE001
                    pass
                self.ring = None
            if self.logger is not None:
                self.logger.close()
                self.logger = None
            self.connect_btn.configure(text="Connect")
            self.status.set("Disconnected. The striker is inhibited.")

    def shutdown(self):
        self._disconnect()

    # ------------------------------------------------------------------ commands
    def _send(self, fn, what: str):
        if not self.link.connected:
            self.status.set("Not connected to the Nano yet - press Connect.")
            return
        try:
            fn()
            self.status.set(what)
        except Exception as exc:  # noqa: BLE001
            self.status.set(f"The Nano did not take that: {exc}")

    def _strike_now(self):
        if self.ring is None and self.link.connected:
            self.status.set("The microphone is not running, so the strike will not be recorded.")
        self._send(self.link.strike_once, "Striking... (the striker lifts, holds, then drops)")

    def _tile_coming(self):
        self._send(self.link.request_tile, "Waiting for a tile: when the sensor sees one it strikes about 2 s later.")

    def _stop_striker(self):
        self._send(lambda: self.link.arm(False), "Striker inhibited.")

    def _apply_hold(self):
        self.hold_lbl.configure(text=f"{self.hold.get():.0f} %")
        if self.link.connected:
            self._send(lambda: self.link.set_hold(self.hold.get()), f"Hold power {self.hold.get():.0f} %.")

    # ------------------------------------------------------------------ events and clips
    def _pump(self):
        for ev in self.link.drain():
            self._on_link_event(ev)
        try:
            while True:
                kind, payload = self.q.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self._refresh_chips()
        self.after(50, self._pump)

    def _on_link_event(self, ev: dict):
        kind = ev["type"]
        if kind == "tap":
            src = ev.get("src")
            if not is_graded_source(src):
                self.status.set(f"Striker {('lowered itself' if src == 'rest' else 'released for safety')} - not a tile strike.")
            elif self.ring is None:
                self.status.set("The Nano struck, but the microphone is not running - nothing was recorded.")
            else:
                self._capture(ev)
        elif kind == "err":
            self.status.set(f"Nano says: {ev.get('code')} {ev.get('text', '')}".strip())
        elif kind == "hello":
            self.status.set(f"Nano ready ({ev.get('fw')}).")
        elif kind == "link" and not ev.get("up"):
            self.status.set("Lost contact with the Nano (no reply for a few seconds).")

    def _capture(self, ev: dict):
        ring = self.ring
        pre = float(self.cfg["strike"]["expect_s"])
        post = float(self.cfg["strike"]["clip_s"]) - pre
        self._pending += 1
        self.status.set("Struck - recording the ring...")

        def work():
            try:
                x = ring.cut_after(ev["t"], pre, post)
                self.q.put(("clip", (x, ring.fs, ev)))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("error", f"recording failed: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def _handle(self, kind, payload):
        if kind == "clip":
            self._pending = max(self._pending - 1, 0)
            x, fs, ev = payload
            if x is None:
                self.status.set("Could not cut the recording out of the microphone stream (it fell behind?). Strike again.")
            else:
                self.process_clip(x, fs, ev)
        elif kind == "error":
            self._pending = max(self._pending - 1, 0)
            self.status.set(str(payload))
        elif kind == "flashlog":
            self._flash_log(str(payload))
        elif kind == "flashdone":
            self._flash_log(str(payload))
            self.status.set("Flashing finished - press Connect.")

    def process_clip(self, x: np.ndarray, fs: int, ev: dict) -> dict:
        """Analyse one clip, show it, save it. Called for every strike heard (and for a loaded WAV)."""
        tile = ev.get("tile_present")
        res = analyse_strike(x, fs, self.cfg, self.reference, tile)
        sid = None
        if ev.get("src") != "file" and self.save_var.get():
            try:
                if self.logger is None:
                    self.logger = StrikeLogger(self._path("test_sessions_dir", "sessions"), fs)
                sid = self.logger.add(x, source=ev.get("src") or "tof", tile_present=tile, tof_mm=ev.get("tof_mm"),
                                      t=ev.get("t"), nano_seq=ev.get("seq"), nano_ms=ev.get("uptime_ms"),
                                      verdict=res["verdict"]["grade"])
            except Exception as exc:  # noqa: BLE001 - a full disk must not stop the test
                self.status.set(f"The result is shown but could not be saved: {exc}")
        res.update(saved_as=sid, tile_present=tile, when=time.strftime("%H:%M:%S"), tof_mm=ev.get("tof_mm"))
        self.results.append(res)
        self._add_history(res)
        self._show(res)
        return res

    # ------------------------------------------------------------------ showing a result
    def _show(self, res: dict):
        grade = res["verdict"]["grade"]
        colour, meaning = _VERDICT.get(grade, (FG, ""))
        self.verdict.configure(text=grade, foreground=colour)
        self.meaning.configure(text=meaning)
        self.reasons.configure(text="  ".join(res["verdict"]["reasons"]))
        draw_strike_overview(self.plot.figure, res["wave"], res["spec"], res["env"], {},
                             title=f"{res['when']}  -  {grade}")
        self.plot.canvas.draw_idle()
        saved = f"  Saved as {res['saved_as']}." if res.get("saved_as") else ""
        self.status.set(f"{res['when']}: {grade}.{saved}")

    def _add_history(self, res: dict):
        f = res["features"]
        tile = {True: "tile", False: "no tile", None: "-"}[res["tile_present"]]
        if res.get("tof_mm") is not None:
            tile += f" ({res['tof_mm']} mm)"
        self._rows += 1
        iid = str(len(self.results) - 1)
        self.tree.insert("", 0, iid=iid, text=res["when"], tags=(res["verdict"]["grade"],), values=(
            tile, res["verdict"]["grade"], "-" if f["centroid_hz"] is None else f"{f['centroid_hz']:.0f}",
            "-" if f["t20_ms"] is None else f"{f['t20_ms']:.0f}", res.get("saved_as") or "-"))
        self.tree.selection_set(iid)
        kids = self.tree.get_children()
        for old in kids[_HISTORY_MAX:]:
            self.tree.delete(old)

    def _show_selected(self):
        sel = self.tree.selection()
        if sel and sel[0].isdigit() and int(sel[0]) < len(self.results):
            self._show(self.results[int(sel[0])])

    # ------------------------------------------------------------------ chips
    def _refresh_chips(self):
        s = self.link.snapshot()
        if not s["connected"]:
            self.link_var.set("Striker: not connected")
            self.link_lbl.configure(foreground=FG_DIM)
            self.tof_var.set("Tile sensor: -")
        elif not s["link_ok"]:
            self.link_var.set("Striker: connected, waiting for the Nano to answer...")
            self.link_lbl.configure(foreground=WARN)
        else:
            mode = {True: "manual", False: "auto"}.get(s["manual"], "?")
            up = "  -  raised" if s["retracted"] else ""
            self.link_var.set(f"Striker: ready ({mode}){up}")
            self.link_lbl.configure(foreground=OK)
            mm = s["tof1_mm"]
            if s["tof1_ok"] is False:
                self.tof_var.set("Tile sensor: not answering")
            elif mm is None:
                self.tof_var.set("Tile sensor: nothing in range (no tile)")
            else:
                limit = int(self.cfg["striker"]["tile_mm"])
                self.tof_var.set(f"Tile sensor: {mm} mm  -  {'TILE' if mm <= limit else 'no tile'}")
        if self.ring is not None:
            lvl = self.ring.level
            self.level["value"] = max(0.0, min(1.0, (_db(lvl) + 70.0) / 70.0))
            self.level_var.set(f"Microphone: {_db(lvl):.0f} dBFS" + ("  (recording a strike...)" if self._pending else ""))
        else:
            self.level["value"] = 0.0
            self.level_var.set("Microphone: off")

    # ------------------------------------------------------------------ other buttons
    def _analyse_file(self):
        path = filedialog.askopenfilename(title="Analyse a recording", filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")])
        if not path:
            return
        try:
            x, fs = load_wav(path)
        except Exception as exc:  # noqa: BLE001
            self.status.set(f"Could not open {path}: {exc}")
            return
        self.process_clip(x, fs, {"src": "file", "tile_present": None, "t": time.time()})

    def _open_labelling(self):
        folders = [str(self._path("test_sessions_dir", "sessions"))]
        try:
            subprocess.Popen([sys.executable, str(repo_root() / "main.py"), "label", *folders], cwd=str(repo_root()))
            self.status.set("Opening the labelling tool in its own window...")
        except OSError as exc:
            self.status.set(f"Could not start the labelling tool: {exc}")

    def _flash(self):
        if self.link.connected or self.ring is not None:
            self._disconnect()                             # the port must be free
        top = tk.Toplevel(self)
        top.title("Flash the Nano firmware")
        top.geometry("620x360")
        ttk.Label(top, text="Keep clear of the striker while this runs.", foreground=WARN).pack(anchor="w", padx=10, pady=(10, 0))
        self._flash_text = tk.Text(top, wrap="word", font=mono_font(9), height=14)
        self._flash_text.pack(fill="both", expand=True, padx=10, pady=8)
        ttk.Button(top, text="Close", command=top.destroy).pack(anchor="e", padx=10, pady=(0, 10))
        port = self._port_device()

        def work():
            try:
                rep = Flasher(self.cfg, log=lambda m: self.q.put(("flashlog", m))).flash(port)
                self.q.put(("flashdone", f"Done. Uploaded to {rep['port']} ({rep['fqbn'].rsplit('=', 1)[-1]})."))
            except FlashError as exc:
                self.q.put(("flashdone", f"Failed: {exc}"))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("flashdone", f"Failed unexpectedly: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def _flash_log(self, text: str):
        try:
            self._flash_text.insert("end", text + "\n")
            self._flash_text.see("end")
        except (AttributeError, tk.TclError):
            pass                                           # the window was closed

    def refresh(self):
        self._load_reference()
        if not self.port["values"]:
            self._refresh_ports()
