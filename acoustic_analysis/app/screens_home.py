"""The Home screen: a launcher plus a summary of the current session - how many
clips, the last grade, calibration state, and whether a reference profile is
loaded (docs/UI_DESIGN.md).
"""

from __future__ import annotations

from collections import Counter
from tkinter import ttk

from .screens import _Base
from .theme import BAD, FG_DIM, OK, WARN, ui_font


def _fmt(value) -> str:
    return f"{value:.3g}" if isinstance(value, (int, float)) else ""


def _grade_colour(grade: str | None) -> str:
    return {"GOOD": OK, "BORDERLINE": WARN, "DEFECTIVE": BAD, "RETEST": FG_DIM}.get(grade or "", FG_DIM)


class HomeScreen(_Base):
    title = "Home"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(2, 14))
        ttk.Label(header, text="Acoustic-Analysis", font=ui_font(17, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text="Impact-acoustic workbench - record or import taps, analyse, label, export a dataset.",
            style="Dim.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        cards = ttk.Frame(self)
        cards.pack(fill="x")
        for i in range(4):
            cards.columnconfigure(i, weight=1, uniform="stat")
        self._clips = self._card(cards, 0, "CLIPS IN SESSION")
        self._grade = self._card(cards, 1, "LAST GRADE")
        self._cal = self._card(cards, 2, "CALIBRATION")
        self._ref = self._card(cards, 3, "REFERENCE PROFILE")

        actions = ttk.Labelframe(self, text="Quick actions", padding=10)
        actions.pack(fill="x", pady=(14, 0))
        ttk.Button(actions, text="Record a tap   R", style="Accent.TButton",
                   command=lambda: ctx.navigate("Record")).pack(side="left")
        ttk.Button(actions, text="Open WAV files   Ctrl+O",
                   command=lambda: ctx.open_files()).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Analyze clips",
                   command=lambda: ctx.navigate("Analyze")).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Dataset / export",
                   command=lambda: ctx.navigate("Dataset")).pack(side="left", padx=(8, 0))

        recent = ttk.Labelframe(self, text="Recent clips", padding=6)
        recent.pack(fill="both", expand=True, pady=(14, 0))
        self._recent = ttk.Treeview(recent, columns=("grade", "f", "t30"),
                                    show="tree headings", height=8)
        self._recent.heading("#0", text="clip")
        self._recent.column("#0", width=200)
        for col, width, text in (("grade", 90, "grade"), ("f", 130, "dominant Hz"), ("t30", 110, "T30 s")):
            self._recent.heading(col, text=text)
            self._recent.column(col, width=width, anchor="center")
        vsb = ttk.Scrollbar(recent, orient="vertical", command=self._recent.yview)
        self._recent.configure(yscrollcommand=vsb.set)
        self._recent.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        ttk.Label(
            self,
            text="Confirm Windows microphone enhancements (AGC / noise suppression) are OFF in "
            "Sound Control Panel before trusting level or spectrum data.",
            style="Mute.TLabel", wraplength=1000,
        ).pack(anchor="w", pady=(12, 2))

    def _card(self, parent, column, label):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=12)
        frame.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))
        ttk.Label(frame, text=label, style="CardH.TLabel").pack(anchor="w")
        value = ttk.Label(frame, text="-", style="Big.TLabel")
        value.pack(anchor="w", pady=(6, 2))
        foot = ttk.Label(frame, text="", style="Card.TLabel", font=ui_font(8))
        foot.pack(anchor="w")
        return value, foot

    def refresh(self):
        clips = self.ctx.state.clips()
        graded = [c for c in clips if c.grade]

        self._clips[0].configure(text=str(len(clips)))
        counts = Counter((c.grade or {}).get("grade") for c in graded if (c.grade or {}).get("grade"))
        self._clips[1].configure(
            text="  ".join(f"{k[:1]} {v}" for k, v in counts.items()) or "none analysed yet"
        )

        last = graded[-1] if graded else None
        last_grade = (last.grade or {}).get("grade") if last else None
        self._grade[0].configure(text=last_grade or "-", foreground=_grade_colour(last_grade))
        self._grade[1].configure(text=last.name if last else "no grades yet")

        cal = self.ctx.state.cfg.get("calibration", {})
        on = bool(cal.get("enabled"))
        self._cal[0].configure(text="dB SPL" if on else "relative", foreground=OK if on else FG_DIM)
        self._cal[1].configure(text="calibrated" if on else "run Calibrate for real levels")

        profile = self.ctx.state.profile
        self._ref[0].configure(text=str(getattr(profile, "n", "?")) if profile else "none")
        self._ref[1].configure(text="loaded" if profile else "build one on the Dataset screen")

        self._recent.delete(*self._recent.get_children())
        for clip in reversed(clips[-10:]):
            grade = (clip.grade or {}).get("grade", "")
            feats = clip.features or {}
            self._recent.insert("", "end", text=clip.name,
                                values=(grade, _fmt(feats.get("dominant_freq_hz")),
                                        _fmt(feats.get("t30_s"))))
