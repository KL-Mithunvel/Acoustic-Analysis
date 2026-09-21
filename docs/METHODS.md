# Acoustic Analysis Methods

How Acoustic-Analysis processes a clip and what every metric means. This is a standalone
reference — the repo does not depend on any external document.

Method set informed by Crystal Instruments' *Acoustic Analysis* overview
(<https://www.crystalinstruments.com/acoustic-analysis>) and the standards it cites.
Crystal's tools target *noise-emission* measurement (how loud / how annoying a steady
source is); this app targets *impact-acoustic NDT* (what a decaying ring says about a
part's integrity), so only the methods that transfer are implemented — see §5.

---

## 1. The processing chain

```text
raw clip (mono, float)
  -> apply calibration factor        counts -> pascals            (dsp/conditioning)
  -> remove DC offset                x -= mean(x)
  -> split windows:
       pre-impact  = [start .. impact]        -> noise / validity metrics (§4)
       impact      = first |x| > k * noise_rms  -> t0
       ring        = [t0 + skip .. t0 + ring_ms]
       decay       = [t0 + skip .. t0 + decay_ms]
  -> band-pass filter the ring/decay windows   (Butterworth, zero-phase)
  -> Hann window (before any FFT)
  -> feature extraction (§3)          spectrum + octave bands + decay + levels
  -> (optional) grade against a reference profile (§6)
```

Everything from "remove DC offset" onward is pure: `numpy` array in, numbers out, no
audio/file/GUI calls. That is what makes it unit-testable with synthetic signals.

## 1a. Getting to a clip: slicing a long take

Everything in §1 assumes a clip holding **one** strike. Real footage rarely
arrives that way - a tap test is usually filmed as one continuous take with
dozens of strikes on several tiles. `dsp/segmentation.py` turns such a take into
clips, and the Slice screen drives it.

```text
video file
  -> ffmpeg: decode audio track, downmix to mono, resample   (io/videoaudio)
  -> RMS envelope over ~5 ms                                 (moving_rms)
  -> noise floor = 25th percentile of that envelope          (noise_floor)
  -> threshold = mult x floor; keep rising edges only
  -> enforce a refractory gap between accepted onsets
  -> drop candidates below a fraction of the loudest strike
  -> walk each crossing back to the start of its attack      (detect_onsets)
  -> window each onset: [-30 ms .. +700 ms], clamped,
     trimmed so no window reaches into the next strike       (segments_from_onsets)
  -> one clip per strike -> §1
```

**Why the noise floor is a percentile of the take itself.** `detect_impact`
(§1) can use the clip's own pre-roll as its reference because the clip was cut
to have one. A whole take has no such quiet header - it has strikes, gaps,
handling noise and talking. The strikes are loud, brief and comparatively rare,
so the low percentiles of the envelope describe the room between them. Taking a
mean instead would let the strikes raise the very floor they are measured
against.

**Why onsets are walked back.** A threshold crossing happens partway up the
attack, delayed by the envelope window and the threshold margin. Cutting there
would remove the leading edge - exactly the part `detect_impact` looks for and
the decay fit starts from. Each onset is therefore moved back to where the level
last sat at the noise floor.

**Why windows are trimmed by `max(pre_ms, guard_ms)`.** Two strikes closer
together than the ring window would otherwise produce overlapping clips, and the
same audio would be exported twice under two labels. The trim is the larger of
the pre-roll and the guard because the *next* window already begins `pre_ms`
early to collect its own lead-in.

Every threshold here is **provisional** - `config.yaml` `video.onsets` was tuned
against synthetic taps only, never against real footage. Expect to move
`threshold_mult` (the Slice screen's sensitivity slider) on the first real
video, and `min_gap_s` if the operator taps faster than 3 per second.

## 2. Windows and why

| Window | Default | Purpose |
|---|---|---|
| pre-impact | 100 ms before the strike | measure the noise floor; decide if the clip is usable at all |
| impact skip | first 5 ms after `t0` | discard the strike transient / striker bounce / contact click |
| ring | 5–250 ms after `t0` | the resonance the spectral features are computed on |
| decay | 5–500 ms after `t0` | long enough to fit the envelope decay (T20/T30) |

All configurable in `config.yaml`. Shorten for a short "thud", lengthen for a long ring.

## 3. Features extracted per clip

### 3.1 Fractional-octave-band levels — `dsp/octave_bands.py`

A bank of band-pass filters with **constant-percentage bandwidth**, centre frequencies
spaced logarithmically. Standards: **IEC 61260-1:2014** / **ANSI S1.11:2004** base-2
band edges.

- Resolutions: 1/1, 1/3, 1/6, 1/12 octave (default **1/3**, ~30 bands 25 Hz–20 kHz).
- Output: level in dB per band.
- Normalised by total energy -> a **shape vector** that does not move with mic gain or
  strike force — the primary feature for comparing clips.
- Band ratios: `high(6–20k)/low(0.3–1k)`, `mid/low`, `high/total`.

Why octave bands and not just the raw FFT: ~30 stable numbers instead of thousands,
matches how resonance energy actually clusters, robust to small frequency shifts.

### 3.2 Spectrum descriptors — `dsp/spectrum.py`

From the Hann-windowed FFT of the ring window:

| Feature | Meaning |
|---|---|
| `f_dominant` | frequency of the highest peak — the fundamental ring mode; drops when cracked |
| `peaks[]` — freq, amplitude, **Q** = f / Δf(−3 dB) | a crack broadens peaks, so Q falls |
| `spectral_centroid` | "brightness" — Σ(f·mag) / Σ(mag); lower = duller |
| `spectral_bandwidth` | spread around the centroid; broader when damped/cracked |
| `spectral_rolloff` (85 %) | frequency below which 85 % of energy sits; lower for a dead tile |
| `spectral_flatness` | tonal (near 0) vs noise-like (near 1); rises with a crack |

### 3.3 Decay / damping — `dsp/decay.py`

The most discriminating group. Computed from the analytic-signal (Hilbert) envelope of
the decay window.

| Feature | Method |
|---|---|
| `T20`, `T30` | time for the envelope to fall 20 / 30 dB from its post-impact peak (a reverberation-time-style measure) |
| `decay_rate_db_s` | slope of a straight-line fit to the envelope in dB |
| `per_band_decay_db_s` | the same slope computed **inside each octave band** — a healthy part's bands decay slowly and evenly; a crack makes one or more bands collapse within a few ms |
| `energy_ratio_early_late` | energy in 0–50 ms vs 200–500 ms; a fast collapse ⇒ suspect |

### 3.4 Level and loudness scalars — `dsp/sound_level.py`, `dsp/weighting.py`

| Feature | Method / standard |
|---|---|
| `L_Zeq`, `L_Aeq` (ring) | equivalent-continuous level, Z (flat) and A weighting |
| `L_peak` | peak level of the strike (C-weighted) |
| `L_AF_max`, `L_A_impulse_max` | Fast (125 ms) and Impulse (35 ms attack / 1500 ms decay) time-weighted maxima — "ring vs thud" separates cleanly here |
| statistical levels `Ln` | level exceeded n % of the time — used on the **pre-impact** window (§4) |
| A / C / Z weighting | IIR filters per **IEC 61672-1** |
| `loudness_sone` *(planned)* | equal-loudness-contour loudness; a cracked part is quantifiably less loud for the same strike |
| `crest_factor` | peak / RMS — how impulsive the signal is |

> For NDT, analyse the **Z-weighted** (flat) signal — defect energy is often above 5 kHz
> where A-weighting attenuates 3–12 dB and would hide it. A-weighted level is kept only
> as one extra "does it sound duller to a person" scalar.

## 4. Validity / noise gate — not a grade, a veto

Computed on the pre-impact window; marks a clip **RETEST** rather than grading it:

| Check | RETEST when |
|---|---|
| noise floor `L95`, spread `L1 − L95` | floor above the configured ceiling |
| SNR = 20·log10(ring_rms / noise_rms) | below ~10 dB |
| impact found? exactly one? not clipped? | no impact / multiple impacts / clipping |
| conveyor/machine tones inside a ring band | strong narrowband tone overlapping a resonance |

## 5. What is deliberately not implemented

| Method | Why not |
|---|---|
| Sound power (ISO 3744 / 3745) | needs a steady source, an enclosing measurement surface, and an (hemi-)anechoic room — none apply to a single impulse |
| Sound intensity, absorption tests | measure room / material acoustic properties, not part integrity |
| Closed-loop acoustic control (SISO/MIMO) | this app generates no sound. The "reference profile + alarm + abort band" idea *is* borrowed — see §6 |
| Zwicker/Moore ISO 532 loudness, sharpness, roughness, fluctuation strength | out of scope for v0.1; classical equal-loudness loudness only, and that is deferred, not built (`dsp/loudness.py`) |

**Noise Criterion (NC)** *is* implemented (`dsp/environment.py`) — not as a part metric
but to qualify the test environment: `nc_rating` by the tangency method against the
NC-15..70 curves, with Leq / L10 / L50 / L90 and a dominant-tone finder. Use the Noise
screen or `cli noise`.

## 6. Labelling and classification

### 6.1 Labels

**Two independent axes per clip**, both configurable (`config.yaml` → `labels`):

| Axis | Column | Default set | What it says |
|---|---|---|---|
| defect | `label` | `good`, `cracked`, `corner_broken`, `other_defect` (+ `retest` / `discard`) | what is physically wrong with the tile |
| grade | `grade_tier` | `3A`, `3B`, `4`, `5` | its cosmetic grade — the same tiers the camera station sorts into |

They are kept apart rather than merged into one class list because they are
genuinely independent: a grade-4 tile can be perfectly intact and a grade-3A
tile can be cracked. A merged label would make the exported dataset unable to
answer either question cleanly, and the acoustic signal only speaks to the
first axis anyway — the grade travels with the row so the two stations' data
can be joined later.

The Label screen writes the defect axis (plus `grader`, `labelled_at`,
`confidence`); the Slice screen writes both. `grade_tier` is nullable, so clips
labelled before it existed, and clips where only the defect matters, stay
valid.

### 6.2 Reference profile — `classify/reference.py`

From ≥ ~30 known-good clips of one part type: mean ± σ of the normalised 1/3-octave
vector, `f_dominant`, `T30`, per-band decay rates, `spectral_centroid`, `L_Zeq`.

### 6.3 Rule-based grade — `classify/rules.py`

A first-pass, explainable grade (the borrowed "alarm / abort band" pattern):

```text
if any §4 validity check fails            -> RETEST
d = deviation(features, reference)         # per-band z-score distance
if d within ALARM band                     -> GOOD
elif d within ABORT band                   -> BORDERLINE
else                                       -> DEFECTIVE
```

First concrete rules (all thresholds tuned on real data, not guessed):

| Rule | Outcome |
|---|---|
| SNR < 10 dB or impact invalid | RETEST |
| `f_dominant` outside reference ± 15 % | DEFECTIVE |
| `T30` < 0.6 × reference T30 | DEFECTIVE |
| `high/low` band ratio < 0.5 × reference | DEFECTIVE |
| any single octave band decays > 3× faster than reference | DEFECTIVE |
| `spectral_centroid` 1–2 σ low, everything else in band | BORDERLINE |
| all features within ALARM band | GOOD |

### 6.4 Trained model — separate repo

The point of the rule grader and the dataset export is to get to a labelled feature
table. A model (Random Forest / SVM / gradient boosting to start) is trained on that
table **outside this app**; only the trained model is deployed downstream.

## 7. Calibration

A one-time **94 dB / 1 kHz** (or 114 dB) pistonphone tone sets the counts→pascal factor,
stored in `config.yaml`. With it, every level feature is in real dB SPL and portable
across microphones and machines. Without it, levels are relative and only comparable
within one recording session on one mic.

## 8. Hardware notes

- The impulsive ring can be loud close up → prefer a **lower-sensitivity, higher-max-SPL**
  measurement capsule over a studio/USB condenser that clips.
- Want **flat response to ≥ 16 kHz** and an **omnidirectional free-field** capsule, fixed
  on-axis to the strike point at a constant distance.
- Disable Windows "microphone enhancements" (AGC, noise suppression) in Sound Control
  Panel — they cannot be controlled from Python and make levels and spectra untrustworthy.

## 9. Standards referenced

| Standard | Used for |
|---|---|
| IEC 61260-1 / ANSI S1.11 | fractional-octave-band filter design |
| IEC 61672-1 | A / C / Z frequency weighting, time weighting |
| ISO 3382 | reverberation time by Schroeder backward integration (`dsp/decay.py`) |
| ISO 532 | (deferred) psychoacoustic loudness |
| ISO 3744 / 3745 | (not implemented) sound power |
