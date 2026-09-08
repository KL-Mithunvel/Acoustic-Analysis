"""The notebook screens. Each is a ``ttk.Frame`` with a ``title`` and a
``refresh()`` the main window calls when the selection or analysis changes.
Plain tabs for now; the instrument-look restyle wraps these unchanged.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np

from ..classify.reference import ReferenceProfile
from ..classify.rules import grade
from ..config import resolve_path
from ..dsp import environment as _env
from ..dsp import noise as _noise
from ..dsp.filters import FilterChain
from ..features import conditioned_windows, extract_features
from . import plots
from .state import ClipData
from .widgets import FeatureTree, MplPanel, info_button


class _Base(ttk.Frame):
    title = "screen"

    def __init__(self, master, ctx):
        super().__init__(master, padding=8)
        self.ctx = ctx

    def refresh(self) -> None:  # overridden
        pass


# --------------------------------------------------------------------------
class AnalyzeScreen(_Base):
    title = "Analyze"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(0, 8))
        ttk.Label(left, text="Clips").pack(anchor="w")
        self.clip_list = tk.Listbox(left, height=14, exportselection=False, width=26)
        self.clip_list.pack(fill="y", expand=True)
        self.clip_list.bind("<<ListboxSelect>>", self._on_pick)
        ttk.Button(left, text="Analyze selected", command=self._analyze).pack(fill="x", pady=4)
        self.grade_var = tk.StringVar(value="-")
        ttk.Label(left, textvariable=self.grade_var, font=("", 11, "bold")).pack(anchor="w", pady=(6, 0))
        self.reasons = tk.Text(left, height=6, width=28, wrap="word", relief="flat")
        self.reasons.pack(fill="x", pady=4)

        grid = ttk.Frame(self)
        grid.pack(side="left", fill="both", expand=True)
        ex = ctx.explainer
        self.p_wave = MplPanel(grid, ex, "waveform", figsize=(4.4, 2.2))
        self.p_spec = MplPanel(grid, ex, "spectrum", figsize=(4.4, 2.2))
        self.p_oct = MplPanel(grid, ex, "octave", figsize=(4.4, 2.4))
        self.p_edc = MplPanel(grid, ex, "edc", figsize=(4.4, 2.4))
        self.p_wave.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self.p_spec.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)
        self.p_oct.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
        self.p_edc.grid(row=1, column=1, sticky="nsew", padx=2, pady=2)
        grid.rowconfigure((0, 1), weight=1)
        grid.columnconfigure((0, 1), weight=1)

        right = ttk.Frame(self)
        right.pack(side="left", fill="y", padx=(8, 0))
        row = ttk.Frame(right)
        row.pack(fill="x")
        ttk.Label(row, text="Features").pack(side="left")
        info_button(row, ex, "feature_table").pack(side="right")
        self.table = FeatureTree(right, height=20)
        self.table.pack(fill="both", expand=True)

    def _on_pick(self, _e=None):
        sel = list(self.clip_list.curselection())
        self.ctx.state.select(sel)

    def _analyze(self):
        self.ctx.service.submit_selection()

    def soft_keys(self):
        return [
            ("Analyze", self._analyze),
            ("Remove clip", lambda: [self.ctx.state.remove_clip(i) for i in reversed(self.ctx.state.selection())]),
        ]

    def refresh(self):
        clips = self.ctx.state.clips()
        cur = set(self.clip_list.curselection())
        self.clip_list.delete(0, "end")
        for c in clips:
            mark = {"GOOD": "[A] ", "BORDERLINE": "[B] ", "DEFECTIVE": "[X] ",
                    "RETEST": "[?] "}.get((c.grade or {}).get("grade"), "")
            self.clip_list.insert("end", f"{mark}{c.name}")
        for i in self.ctx.state.selection():
            self.clip_list.selection_set(i)

        clip = self.ctx.state.primary()
        cfg = self.ctx.state.cfg
        if clip is None:
            for p in (self.p_wave, self.p_spec, self.p_oct, self.p_edc):
                p.clear()
            self.table.show(None)
            self.grade_var.set("-")
            return
        self.p_wave.draw_with(plots.draw_waveform, clip, cfg)
        self.p_spec.draw_with(plots.draw_spectrum, [clip], cfg)
        self.p_oct.draw_with(plots.draw_octave, [clip], cfg, self.ctx.state.profile)
        self.p_edc.draw_with(plots.draw_energy_decay, [clip], cfg)
        self.table.show(clip.features)
        g = clip.grade or {}
        self.grade_var.set(f"Grade: {g.get('grade', 'not analysed')}")
        self.reasons.configure(state="normal")
        self.reasons.delete("1.0", "end")
        self.reasons.insert("1.0", "\n".join(f"- {r}" for r in g.get("reasons", [])))
        self.reasons.configure(state="disabled")


# --------------------------------------------------------------------------
class CompareScreen(_Base):
    title = "Compare"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(0, 8))
        ttk.Label(left, text="Clips (multi-select)").pack(anchor="w")
        self.clip_list = tk.Listbox(left, height=16, selectmode="extended", exportselection=False, width=26)
        self.clip_list.pack(fill="y", expand=True)
        self.clip_list.bind("<<ListboxSelect>>", lambda _e: self.ctx.state.select(list(self.clip_list.curselection())))
        self.diff = tk.Text(left, height=10, width=30, wrap="word", relief="flat")
        self.diff.pack(fill="x", pady=6)

        grid = ttk.Frame(self)
        grid.pack(side="left", fill="both", expand=True)
        ex = ctx.explainer
        self.p_spec = MplPanel(grid, ex, "spectrum", figsize=(5.6, 3.0))
        self.p_oct = MplPanel(grid, ex, "octave", figsize=(5.6, 3.0))
        self.p_edc = MplPanel(grid, ex, "edc", figsize=(5.6, 3.0))
        self.p_spec.pack(fill="both", expand=True, pady=2)
        self.p_oct.pack(fill="both", expand=True, pady=2)
        self.p_edc.pack(fill="both", expand=True, pady=2)

    def refresh(self):
        clips = self.ctx.state.clips()
        self.clip_list.delete(0, "end")
        for c in clips:
            self.clip_list.insert("end", c.name)
        for i in self.ctx.state.selection():
            self.clip_list.selection_set(i)

        chosen = self.ctx.state.selected_clips() or clips[:1]
        cfg = self.ctx.state.cfg
        if not chosen:
            for p in (self.p_spec, self.p_oct, self.p_edc):
                p.clear()
            return
        self.p_spec.draw_with(plots.draw_spectrum, chosen, cfg)
        self.p_oct.draw_with(plots.draw_octave, chosen, cfg, self.ctx.state.profile)
        self.p_edc.draw_with(plots.draw_energy_decay, chosen, cfg)
        self._show_diffs(chosen)

    def _show_diffs(self, clips):
        self.diff.configure(state="normal")
        self.diff.delete("1.0", "end")
        feats = [(c.name, c.features) for c in clips if c.features and c.features.get("valid")]
        if len(feats) < 2:
            self.diff.insert("1.0", "Analyze at least two clips to compare.")
        else:
            keys = ["dominant_freq_hz", "t30_s", "decay_rate_db_s", "spectral_centroid_hz",
                    "spectral_flatness", "snr_db"]
            ranked = []
            for k in keys:
                vals = [(n, f.get(k)) for n, f in feats if isinstance(f.get(k), (int, float))]
                if len(vals) >= 2:
                    lo = min(vals, key=lambda p: p[1])
                    hi = max(vals, key=lambda p: p[1])
                    spread = abs(hi[1] - lo[1]) / (abs(np.mean([v for _, v in vals])) + 1e-9)
                    ranked.append((spread, k, lo, hi))
            ranked.sort(reverse=True)
            self.diff.insert("1.0", "Biggest differences:\n")
            for spread, k, lo, hi in ranked[:6]:
                self.diff.insert("end", f"\n{k}\n  {lo[0]}: {lo[1]:.3g}\n  {hi[0]}: {hi[1]:.3g}\n")
        self.diff.configure(state="disabled")


# --------------------------------------------------------------------------
class FiltersScreen(_Base):
    title = "Filters"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        cfg = ctx.state.cfg
        controls = ttk.LabelFrame(self, text="Filter chain", padding=8)
        controls.pack(side="left", fill="y", padx=(0, 8))

        bp = cfg["analysis"]["bandpass_hz"]
        self.low = tk.DoubleVar(value=bp[0])
        self.high = tk.DoubleVar(value=bp[1])
        self.order = tk.IntVar(value=cfg["analysis"].get("bandpass_order", 4))
        self.weight = tk.StringVar(value=cfg.get("weighting", {}).get("default", "Z"))
        self.notches = tk.StringVar(value="; ".join(f"{f},{q}" for f, q in cfg["analysis"].get("notches", [])))

        for label, var in (("band low (Hz)", self.low), ("band high (Hz)", self.high), ("order", self.order)):
            r = ttk.Frame(controls)
            r.pack(fill="x", pady=2)
            ttk.Label(r, text=label, width=14).pack(side="left")
            ttk.Entry(r, textvariable=var, width=10).pack(side="left")
        r = ttk.Frame(controls)
        r.pack(fill="x", pady=2)
        ttk.Label(r, text="weighting", width=14).pack(side="left")
        ttk.Combobox(r, textvariable=self.weight, values=["Z", "A", "C"], width=8, state="readonly").pack(side="left")
        r = ttk.Frame(controls)
        r.pack(fill="x", pady=2)
        ttk.Label(r, text="notches f,Q;...", width=14).pack(side="left")
        ttk.Entry(r, textvariable=self.notches, width=16).pack(side="left")

        ttk.Button(controls, text="Update", command=self.refresh).pack(fill="x", pady=(8, 2))
        ttk.Button(controls, text="Write to config.yaml", command=self._write_config).pack(fill="x")
        self.desc = tk.Text(controls, height=8, width=26, wrap="word", relief="flat")
        self.desc.pack(fill="x", pady=6)

        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True)
        self.p_resp = MplPanel(right, ctx.explainer, "filter_response", figsize=(6.0, 3.0))
        self.p_pair = MplPanel(right, ctx.explainer, "spectrum", figsize=(6.0, 3.0))
        self.p_resp.pack(fill="both", expand=True, pady=2)
        self.p_pair.pack(fill="both", expand=True, pady=2)

    def _chain(self) -> FilterChain:
        parsed = []
        for pair in self.notches.get().split(";"):
            pair = pair.strip()
            if not pair:
                continue
            f, q = pair.split(",")
            parsed.append((float(f), float(q)))
        return FilterChain(
            bandpass=(self.low.get(), self.high.get()),
            bandpass_order=int(self.order.get()),
            notches=parsed,
            weighting=self.weight.get(),
        )

    def _write_config(self):
        cfg = self.ctx.state.cfg
        chain = self._chain()
        cfg["analysis"]["bandpass_hz"] = [chain.bandpass[0], chain.bandpass[1]]
        cfg["analysis"]["bandpass_order"] = chain.bandpass_order
        cfg["analysis"]["notches"] = [list(n) for n in chain.notches]
        cfg["weighting"]["default"] = chain.weighting
        try:
            import yaml

            path = resolve_path(cfg, "data_dir").parent / "config.yaml"
            path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            messagebox.showinfo("Filters", f"wrote {path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Filters", str(exc))

    def soft_keys(self):
        return [("Update", self.refresh), ("Write to config", self._write_config)]

    def refresh(self):
        cfg = self.ctx.state.cfg
        fs = cfg["audio"]["sample_rate"]
        try:
            chain = self._chain()
        except Exception:  # noqa: BLE001 - bad entry text; keep the last good plot
            return
        self.p_resp.draw_with(plots.draw_filter_response, chain, fs)
        self.desc.configure(state="normal")
        self.desc.delete("1.0", "end")
        self.desc.insert("1.0", "\n".join(f"- {s}" for s in chain.describe()))
        self.desc.configure(state="disabled")

        clip = self.ctx.state.primary()
        if clip is None:
            self.p_pair.clear()
            return

        def _pair(ax):
            before = np.asarray(clip.samples, float)
            after = chain.apply(before, clip.fs)
            plots.draw_signal_pair(ax, clip.fs, before, after[: before.size])
            ax.set_title("Original vs filtered")

        self.p_pair.draw_with(_pair)


# --------------------------------------------------------------------------
class NoiseScreen(_Base):
    title = "Noise"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(0, 8))
        ttk.Label(left, text="Noise-profile clip").pack(anchor="w")
        self.noise_pick = ttk.Combobox(left, width=26, state="readonly")
        self.noise_pick.pack(fill="x")
        ttk.Label(left, text="Target clip to denoise").pack(anchor="w", pady=(8, 0))
        self.target_pick = ttk.Combobox(left, width=26, state="readonly")
        self.target_pick.pack(fill="x")
        self.strength = tk.DoubleVar(value=ctx.state.cfg["noise"]["strength"])
        r = ttk.Frame(left)
        r.pack(fill="x", pady=6)
        ttk.Label(r, text="strength").pack(side="left")
        ttk.Scale(r, from_=0.0, to=3.0, variable=self.strength, command=lambda _v: self.refresh()).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(left, text="Update", command=self.refresh).pack(fill="x")
        row = ttk.Frame(left)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="Environment").pack(side="left")
        info_button(row, ctx.explainer, "nc_rating").pack(side="right")
        self.env_text = tk.Text(left, height=12, width=30, wrap="word", relief="flat")
        self.env_text.pack(fill="x")

        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True)
        self.p_denoise = MplPanel(right, ctx.explainer, "denoise", figsize=(6.0, 3.4))
        self.p_denoise.pack(fill="both", expand=True)

    def refresh(self):
        clips = self.ctx.state.clips()
        names = [c.name for c in clips]
        self.noise_pick["values"] = names
        self.target_pick["values"] = names
        if names and not self.noise_pick.get():
            self.noise_pick.current(0)
        if names and not self.target_pick.get():
            self.target_pick.current(min(1, len(names) - 1))

        cfg = self.ctx.state.cfg
        noise_clip = self._by_name(self.noise_pick.get())
        target_clip = self._by_name(self.target_pick.get())

        self.env_text.configure(state="normal")
        self.env_text.delete("1.0", "end")
        if noise_clip is not None:
            try:
                env = _env.environmental_analysis(noise_clip.samples, noise_clip.fs, cfg)
                self.env_text.insert(
                    "1.0",
                    f"Leq {env['leq_db']} dB\nL10/50/90 {env['l10_db']}/{env['l50_db']}/{env['l90_db']}\n"
                    f"NC {env.get('nc_rating')} (band {env.get('nc_limiting_band_hz')} Hz)\n\ntones:\n"
                    + "\n".join(f"  {t['freq_hz']:.0f} Hz +{t['prominence_db']:.0f} dB" for t in env["tones"]),
                )
            except Exception as exc:  # noqa: BLE001
                self.env_text.insert("1.0", f"analysis error: {exc}")
        self.env_text.configure(state="disabled")

        if noise_clip is None or target_clip is None:
            self.p_denoise.clear()
            return

        def _plot(ax):
            before = np.asarray(target_clip.samples, float)
            after = _noise.reduce_noise(
                before, target_clip.fs, np.asarray(noise_clip.samples, float),
                strength=float(self.strength.get()),
                method=cfg["noise"]["method"], nperseg=cfg["noise"]["stft_nperseg"],
                floor_db=cfg["noise"]["floor_db"],
            )
            plots.draw_signal_pair(ax, target_clip.fs, before, after[: before.size], ("noisy", "denoised"))
            ax.set_title(f"Denoise preview (strength {self.strength.get():.1f})")

        self.p_denoise.draw_with(_plot)

    def _by_name(self, name):
        for c in self.ctx.state.clips():
            if c.name == name:
                return c
        return None


# --------------------------------------------------------------------------
class LabelScreen(_Base):
    title = "Label"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        cfg = ctx.state.cfg
        form = ttk.Frame(self)
        form.pack(anchor="nw", fill="x")
        self.clip_name = tk.StringVar(value="-")
        ttk.Label(form, textvariable=self.clip_name, font=("", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(form, text="class").grid(row=1, column=0, sticky="w", pady=4)
        self.label = ttk.Combobox(form, values=cfg["labels"]["classes"] + cfg["labels"]["extra"], state="readonly", width=20)
        self.label.grid(row=1, column=1, sticky="w")
        ttk.Label(form, text="grader").grid(row=2, column=0, sticky="w", pady=4)
        self.grader = ttk.Entry(form, width=22)
        self.grader.grid(row=2, column=1, sticky="w")
        ttk.Label(form, text="notes").grid(row=3, column=0, sticky="nw", pady=4)
        self.notes = tk.Text(form, height=4, width=32, wrap="word")
        self.notes.grid(row=3, column=1, sticky="w")
        self.in_ref = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="add to reference set", variable=self.in_ref).grid(row=4, column=1, sticky="w", pady=4)
        ttk.Button(form, text="Save to dataset", command=self._save).grid(row=5, column=1, sticky="w", pady=6)
        self.status = tk.StringVar(value="")
        ttk.Label(form, textvariable=self.status).grid(row=6, column=0, columnspan=2, sticky="w")

    def refresh(self):
        clip = self.ctx.state.primary()
        self.clip_name.set(clip.name if clip else "no clip selected")
        if clip and (clip.grade or {}).get("grade") in self.label["values"]:
            pass

    def soft_keys(self):
        return [("Save to dataset", self._save)]

    def _save(self):
        clip = self.ctx.state.primary()
        if clip is None or not self.label.get():
            self.status.set("pick a clip and a class first")
            return
        db = self.ctx.db
        cfg = self.ctx.state.cfg
        sid = self.ctx.ensure_session()
        rec_dir = resolve_path(cfg, "recordings_dir")
        rec_dir.mkdir(parents=True, exist_ok=True)
        from ..io.wavstore import save_clip

        wav = save_clip(clip.samples, clip.fs, rec_dir / f"{_safe_name(clip.name)}.wav",
                        metadata={"source": clip.source, "label": self.label.get()})
        cid = db.add_clip(sid, str(wav), clip.source, clip.fs, clip.duration_s)
        if clip.features is None:
            clip.features = extract_features(clip.samples, clip.fs, cfg)
        db.set_features(cid, clip.features)
        db.set_label(cid, self.label.get(), grader=self.grader.get(),
                     in_reference=self.in_ref.get())
        self.status.set(f"saved clip #{cid} to session {sid}")


# --------------------------------------------------------------------------
class DatasetScreen(_Base):
    title = "Dataset"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(bar, text="Export CSV", command=lambda: self._export("csv")).pack(side="left", padx=4)
        ttk.Button(bar, text="Export JSON", command=lambda: self._export("json")).pack(side="left")
        ttk.Button(bar, text="Delete selected", command=self._delete).pack(side="left", padx=4)
        ttk.Button(bar, text="Build reference from flagged", command=self._build_ref).pack(side="left")

        cols = ("session", "seq", "label", "grade", "f_dom", "T30", "SNR")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=20)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=90, anchor="center")
        self.tree.pack(fill="both", expand=True, pady=6)

    def soft_keys(self):
        return [
            ("Export CSV", lambda: self._export("csv")),
            ("Export JSON", lambda: self._export("json")),
            ("Build reference", self._build_ref),
        ]

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for clip in self.ctx.db.list_clips():
            f = clip.get("features") or {}
            lab = clip.get("label") or {}
            self.tree.insert(
                "", "end", iid=str(clip["id"]),
                values=(
                    clip["session_id"], clip["seq"], lab.get("label", ""),
                    f.get("status", ""), _g(f, "dominant_freq_hz"),
                    _g(f, "t30_s"), _g(f, "snr_db"),
                ),
            )

    def _export(self, kind):
        path = filedialog.asksaveasfilename(defaultextension=f".{kind}")
        if not path:
            return
        if kind == "csv":
            self.ctx.db.export_csv(path)
        else:
            self.ctx.db.export_json(path)
        messagebox.showinfo("Dataset", f"wrote {path}")

    def _delete(self):
        for iid in self.tree.selection():
            self.ctx.db.delete_clip(int(iid))
        self.refresh()

    def _build_ref(self):
        feats = [c["features"] for c in self.ctx.db.reference_clips() if c.get("features")]
        try:
            profile = ReferenceProfile.build(feats)
        except ValueError as exc:
            messagebox.showerror("Dataset", str(exc))
            return
        self.ctx.state.profile = profile
        path = resolve_path(self.ctx.state.cfg, "reference_profile")
        profile.save(path)
        messagebox.showinfo("Dataset", f"reference profile from {profile.n} clips -> {path}")


# --------------------------------------------------------------------------
class LearnScreen(_Base):
    title = "Learn"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        ctrl = ttk.Frame(self)
        ctrl.pack(side="left", fill="y", padx=(0, 8))
        self.freq = tk.DoubleVar(value=2000.0)
        self.tau = tk.DoubleVar(value=0.15)
        for label, var, lo, hi in (("frequency Hz", self.freq, 200, 12000), ("decay tau s", self.tau, 0.01, 0.5)):
            r = ttk.Frame(ctrl)
            r.pack(fill="x", pady=3)
            ttk.Label(r, text=label, width=14).pack(side="left")
            ttk.Scale(r, from_=lo, to=hi, variable=var, command=lambda _v: self.refresh()).pack(side="left", fill="x", expand=True)
        self.glossary = tk.Text(ctrl, height=18, width=34, wrap="word", relief="flat")
        self.glossary.pack(fill="both", expand=True, pady=6)
        for title, body in ctx.explainer.glossary():
            self.glossary.insert("end", f"{title}\n{body}\n\n")
        self.glossary.configure(state="disabled")

        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True)
        self.p_wave = MplPanel(right, ctx.explainer, "waveform", figsize=(6.0, 2.6))
        self.p_spec = MplPanel(right, ctx.explainer, "spectrum", figsize=(6.0, 2.6))
        self.p_wave.pack(fill="both", expand=True, pady=2)
        self.p_spec.pack(fill="both", expand=True, pady=2)

    def refresh(self):
        fs = self.ctx.state.cfg["audio"]["sample_rate"]
        n = int(0.5 * fs)
        t = np.arange(n) / fs
        sig = np.exp(-t / max(1e-3, self.tau.get())) * np.sin(2 * np.pi * self.freq.get() * t)
        clip = ClipData(name="synthetic", samples=sig, fs=fs, source="synthetic")

        self.p_wave.draw_with(lambda ax: (ax.plot(t, sig, lw=0.5), ax.set_title("Synthetic decaying tone"),
                                          ax.set_xlabel("time (s)")))
        self.p_spec.draw_with(plots.draw_spectrum, [clip], self.ctx.state.cfg)


ALL_SCREENS = [
    AnalyzeScreen, CompareScreen, FiltersScreen, NoiseScreen,
    LabelScreen, DatasetScreen, LearnScreen,
]


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60] or "clip"


def _g(features: dict, key: str) -> str:
    v = features.get(key)
    return f"{v:.3g}" if isinstance(v, (int, float)) else ""
