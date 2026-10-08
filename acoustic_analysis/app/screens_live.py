"""Live-input and configuration screens: Monitor, Record, Calibrate, Settings.

The audio screens degrade gracefully when PortAudio is unavailable - the
controls disable and say so, rather than erroring.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from ..config import resolve_path
from ..dsp.conditioning import bandpass, rms
from ..io import audio_out, recorder
from .screens import _Base
from .state import ClipData
from .theme import ui_font
from .widgets import MplPanel, info_button


def _devices():
    try:
        return recorder.list_input_devices()
    except RuntimeError:
        return None


class MonitorScreen(_Base):
    title = "Monitor"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._queue: queue.Queue = queue.Queue()
        self._monitor = None
        self._last_block = None

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Label(bar, text="input device").pack(side="left")
        self.device = ttk.Combobox(bar, width=40, state="readonly")
        self.device.pack(side="left", padx=4)
        ttk.Label(bar, text="gain").pack(side="left")
        self.gain = tk.DoubleVar(value=ctx.state.cfg["capture"].get("input_gain", 1.0))
        ttk.Entry(bar, textvariable=self.gain, width=6).pack(side="left", padx=4)
        self.start_btn = ttk.Button(bar, text="Start", command=self._toggle)
        self.start_btn.pack(side="left", padx=8)
        info_button(bar, ctx.explainer, "level_meter").pack(side="right")

        meter = ttk.Frame(self)
        meter.pack(fill="x", pady=8)
        ttk.Label(meter, text="level").pack(side="left")
        self.level = ttk.Progressbar(meter, maximum=1.0, length=360)
        self.level.pack(side="left", padx=6)
        self.level_lbl = tk.StringVar(value="-inf dBFS")
        ttk.Label(meter, textvariable=self.level_lbl).pack(side="left")

        self.note = ttk.Label(
            self,
            foreground="#b5651d",
            text="For real measurements, disable Windows microphone enhancements "
            "(Sound Control Panel -> input device -> Properties -> Enhancements).",
            wraplength=700,
        )
        self.note.pack(anchor="w")

        self.p_spec = MplPanel(self, ctx.explainer, "spectrum", figsize=(6.5, 3.2))
        self.p_spec.pack(fill="both", expand=True, pady=6)

    def refresh(self):
        devs = _devices()
        if devs is None:
            self.device["values"] = ["(PortAudio unavailable)"]
            self.device.current(0)
            self.start_btn.state(["disabled"])
            return
        self.device["values"] = [f"{d['index']}: {d['name']}" for d in devs]
        if devs and not self.device.get():
            self.device.current(0)

    def _toggle(self):
        if self._monitor is not None:
            self._stop()
        else:
            self._start()

    def _start(self):
        cfg = dict(self.ctx.state.cfg)
        cfg["capture"] = {**cfg["capture"], "input_gain": float(self.gain.get())}
        dev = int(self.device.get().split(":")[0]) if self.device.get()[:1].isdigit() else None
        try:
            self._monitor = recorder.LiveMonitor(cfg, self._on_block, device=dev)
            self._monitor.start()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Monitor", str(exc))
            self._monitor = None
            return
        self.start_btn.configure(text="Stop")
        self._pump()

    def _stop(self):
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None
        self.start_btn.configure(text="Start")

    def _on_block(self, block, level_rms):  # PortAudio thread
        self._queue.put((block, level_rms))

    def _pump(self):
        if self._monitor is None:
            return
        try:
            while True:
                block, level_rms = self._queue.get_nowait()
                self._last_block = block
                self.level["value"] = min(1.0, level_rms * 4)
                self.level_lbl.set(
                    f"{20 * np.log10(level_rms):.1f} dBFS" if level_rms > 0 else "-inf dBFS"
                )
        except queue.Empty:
            pass
        if self._last_block is not None and len(self._last_block) > 32:
            block = self._last_block
            fs = self.ctx.state.cfg["audio"]["sample_rate"]
            self.p_spec.draw_with(
                lambda ax: (
                    ax.magnitude_spectrum(block, Fs=fs, scale="dB"),
                    ax.set_title("Live spectrum (latest block)"),
                )
            )
        self.after(120, self._pump)


class RecordScreen(_Base):
    title = "Record"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        cfg = ctx.state.cfg
        form = ttk.Frame(self)
        form.pack(anchor="nw", fill="x")
        ttk.Label(form, text="input device").grid(row=0, column=0, sticky="w")
        self.device = ttk.Combobox(form, width=40, state="readonly")
        self.device.grid(row=0, column=1, sticky="w", pady=3)
        ttk.Label(form, text="trigger").grid(row=1, column=0, sticky="w")
        self.trigger = ttk.Combobox(form, values=["manual", "rms"], state="readonly", width=12)
        self.trigger.set(cfg["capture"].get("trigger", "manual"))
        self.trigger.grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(form, text=f"clip length {cfg['capture']['capture_duration_s']} s "
                  f"(pre-trigger {cfg['capture']['pre_trigger_ms']} ms)").grid(row=2, column=1, sticky="w")
        self.rec_btn = ttk.Button(form, text="Record", command=self._record)
        self.rec_btn.grid(row=3, column=1, sticky="w", pady=8)
        self.status = tk.StringVar(value="")
        ttk.Label(form, textvariable=self.status).grid(row=4, column=0, columnspan=2, sticky="w")

    def refresh(self):
        devs = _devices()
        if devs is None:
            self.device["values"] = ["(PortAudio unavailable)"]
            self.device.current(0)
            self.rec_btn.state(["disabled"])
            return
        self.device["values"] = [f"{d['index']}: {d['name']}" for d in devs]
        if devs and not self.device.get():
            self.device.current(0)

    def _record(self):
        self.rec_btn.state(["disabled"])
        self.status.set("recording...")
        dev = int(self.device.get().split(":")[0]) if self.device.get()[:1].isdigit() else None
        trig = self.trigger.get()
        cfg = self.ctx.state.cfg

        def worker():
            try:
                rec = recorder.Recorder(cfg, device=dev)
                samples, fs = rec.capture(trigger=trig)
                self.after(0, lambda: self._done(samples, fs))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._failed(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, samples, fs):
        n = len([c for c in self.ctx.state.clips() if c.source == "recorded"]) + 1
        idx = self.ctx.state.add_clip(ClipData(name=f"rec-{n:03d}", samples=samples, fs=fs, source="recorded"))
        self.ctx.service.submit(idx)
        self.status.set(f"captured rec-{n:03d} ({len(samples) / fs:.2f} s)")
        self.rec_btn.state(["!disabled"])

    def _failed(self, msg):
        self.status.set(f"failed: {msg}")
        self.rec_btn.state(["!disabled"])


class CalibrateScreen(_Base):
    title = "Calibrate"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._tone = None
        form = ttk.Frame(self)
        form.pack(anchor="nw", fill="x")
        ttk.Button(form, text="Load reference-tone WAV", command=self._load).grid(row=0, column=0, sticky="w", pady=3)
        self.src = tk.StringVar(value="no tone loaded")
        ttk.Label(form, textvariable=self.src).grid(row=0, column=1, sticky="w")

        ttk.Label(form, text="tone level (dB SPL)").grid(row=1, column=0, sticky="w")
        self.level_db = tk.DoubleVar(value=ctx.state.cfg["calibration"].get("reference_db_spl", 94.0))
        ttk.Entry(form, textvariable=self.level_db, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(form, text="tone frequency (Hz)").grid(row=2, column=0, sticky="w")
        self.freq = tk.DoubleVar(value=ctx.state.cfg["calibration"].get("reference_freq_hz", 1000.0))
        ttk.Entry(form, textvariable=self.freq, width=8).grid(row=2, column=1, sticky="w")

        ttk.Button(form, text="Compute", command=self._compute).grid(row=3, column=0, sticky="w", pady=8)
        ttk.Button(form, text="Apply to config", command=self._apply).grid(row=3, column=1, sticky="w")
        self.result = tk.StringVar(value="")
        ttk.Label(form, textvariable=self.result, font=("", 10, "bold")).grid(row=4, column=0, columnspan=2, sticky="w")
        self._cpp = None

    def refresh(self):
        pass

    def _load(self):
        path = filedialog.askopenfilename(filetypes=[("WAV", "*.wav")])
        if not path:
            return
        from ..io.wavstore import load_clip

        self._tone, self._fs, _ = load_clip(path)
        self.src.set(path)

    def _compute(self):
        if self._tone is None:
            self.result.set("load a tone first")
            return
        f0 = self.freq.get()
        band = bandpass(self._tone, self._fs, max(20.0, f0 * 0.7), min(0.49 * self._fs, f0 * 1.4))
        counts = rms(band)
        p_ref = 10.0 ** (self.level_db.get() / 20.0) * 20e-6
        self._cpp = counts / p_ref
        self.result.set(f"counts_per_pascal = {self._cpp:.6g}")

    def _apply(self):
        if self._cpp is None:
            self._compute()
        if self._cpp is None:
            return
        cfg = self.ctx.state.cfg
        cfg["calibration"]["enabled"] = True
        cfg["calibration"]["counts_per_pascal"] = float(self._cpp)
        _write_config(cfg)
        self.result.set(f"applied: calibration.counts_per_pascal = {self._cpp:.6g}")


# (config path, label, plain-language help, min, max, step, decimals)
_BASIC = (
    (("capture", "capture_duration_s"), "Clip length", "How many seconds to keep after each tap.", 0.3, 2.0, 0.05, 2, "s"),
    (("capture", "pre_trigger_ms"), "Lead-in", "Quiet audio kept before the strike. Needed to measure the noise floor.", 20, 300, 10, 0, "ms"),
    (("capture", "cooldown_s"), "Gap between taps", "Ignore new sounds for this long after a tap, so one strike is not counted twice.", 0.3, 5.0, 0.1, 1, "s"),
    (("machine", "motor_strength"), "Motor-noise removal", "0 = off, 1 = normal, higher removes more but can dull the ring.", 0.0, 3.0, 0.1, 1, "x"),
    (("machine", "min_residual_snr_db"), "How clearly a tile must ring", "A strike counts as a tile tap only if the ring is this far above the background. Raise it to reject more doubtful taps.", 3, 30, 1, 0, "dB"),
    (("machine", "dry_strikes_target"), "Dry strikes to record", "How many striker-only strikes the Setup step collects. More = a steadier template.", 5, 40, 1, 0, "strikes"),
)


class SettingsScreen(_Base):
    title = "Settings"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._vars: dict[tuple, tk.DoubleVar] = {}

        basic = ttk.Labelframe(self, text="Basic settings", padding=10)
        basic.pack(fill="x")
        basic.columnconfigure(2, weight=1)
        for r, (path, label, helptext, lo, hi, step, dec, unit) in enumerate(_BASIC):
            var = tk.DoubleVar()
            self._vars[path] = var
            ttk.Label(basic, text=label, font=ui_font(10, "bold")).grid(row=r, column=0, sticky="w", pady=4)
            sp = ttk.Spinbox(basic, from_=lo, to=hi, increment=step, textvariable=var, width=7,
                             format=f"%.{dec}f")
            sp.grid(row=r, column=1, sticky="w", padx=8)
            ttk.Label(basic, text=f"{unit}   {helptext}", style="Dim.TLabel", wraplength=700).grid(
                row=r, column=2, sticky="w")
        row = ttk.Frame(basic)
        row.grid(row=len(_BASIC), column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Button(row, text="Apply and save", style="Accent.TButton", command=self._apply_basic).pack(side="left")
        ttk.Button(row, text="Reset to defaults", command=self._reset_basic).pack(side="left", padx=8)
        self.note = tk.StringVar(value="Saved to data/user_settings.yaml - config.yaml is never rewritten.")
        ttk.Label(row, textvariable=self.note, style="Dim.TLabel").pack(side="left", padx=8)

        adv = ttk.Labelframe(self, text="Advanced - full configuration (read-only; edit config.yaml for the rest)", padding=6)
        adv.pack(fill="both", expand=True, pady=(10, 0))
        bar = ttk.Frame(adv)
        bar.pack(fill="x")
        ttk.Button(bar, text="Reload config.yaml", command=self._reload).pack(side="left")
        ttk.Button(bar, text="Save preset...", command=self._save_preset).pack(side="left", padx=4)
        ttk.Button(bar, text="Load preset...", command=self._load_preset).pack(side="left")
        self.text = tk.Text(adv, wrap="none", relief="flat", height=8)
        self.text.pack(fill="both", expand=True, pady=6)

    def _load_basic(self):
        cfg = self.ctx.state.cfg
        for (sec, key), var in self._vars.items():
            var.set(cfg[sec][key])

    def _apply_basic(self):
        from ..config import save_user_settings

        changes: dict = {}
        try:
            for (sec, key), var in self._vars.items():
                spec = next(b for b in _BASIC if b[0] == (sec, key))
                val = min(max(float(var.get()), spec[3]), spec[4])
                changes.setdefault(sec, {})[key] = int(val) if spec[6] == 0 else round(val, spec[6])
        except tk.TclError:
            self.note.set("One of the values is not a number.")
            return
        save_user_settings(self.ctx.state.cfg, changes)
        self._load_basic()
        self.note.set("Applied. Used from the next recording; saved for next time.")

    def _reset_basic(self):
        from ..config import reset_user_settings

        reset_user_settings(self.ctx.state.cfg)
        self.refresh()
        self.note.set("Back to the shipped defaults.")

    def refresh(self):
        import yaml

        self._load_basic()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", yaml.safe_dump(self.ctx.state.cfg, sort_keys=False))
        self.text.configure(state="disabled")

    def _reload(self):
        from ..config import load_config

        self.ctx.state.cfg.clear()
        self.ctx.state.cfg.update(load_config())
        self.refresh()
        messagebox.showinfo("Settings", "reloaded config.yaml (restart for filter defaults)")

    def _save_preset(self):
        path = filedialog.asksaveasfilename(defaultextension=".yaml", initialdir=str(resolve_path(self.ctx.state.cfg, "data_dir") / "presets"))
        if path:
            _write_config(self.ctx.state.cfg, path)
            messagebox.showinfo("Settings", f"wrote {path}")

    def _load_preset(self):
        path = filedialog.askopenfilename(filetypes=[("YAML", "*.yaml"), ("All", "*.*")])
        if not path:
            return
        import yaml

        self.ctx.state.cfg.clear()
        self.ctx.state.cfg.update(yaml.safe_load(open(path, encoding="utf-8")))
        self.refresh()


def _write_config(cfg: dict, path=None) -> None:
    import yaml

    from ..config import repo_root

    target = path or (repo_root() / "config.yaml")
    with open(target, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)


LIVE_SCREENS = [MonitorScreen, RecordScreen, CalibrateScreen, SettingsScreen]
