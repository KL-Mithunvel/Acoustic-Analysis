r"""Figures for docs/ACOUSTIC_REPORT.md, built from the real 2026-10-19 station sessions.

Writes four PNGs to docs/report_figures/ and prints the numbers quoted in the report:
  01 waveforms (room noise, striker only, good tile, cracked tile)
  02 average spectra, 5-250 ms after the strike (striker only / good / cracked)
  03 per-tile feature spread, good vs cracked (every labelled tile is a dot)
  04 energy decay, good vs cracked vs striker only

Needs the sessions pulled to <Tile_Sorting>/data/master/sessions and the labels in
data/labels.json. Strike alignment is a rough onset threshold, as in tools/striker_subtraction.py.

    venv\Scripts\python tools\make_report_figures.py
"""
import json
import wave
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.signal import welch

HERE = Path(__file__).resolve().parents[1]
SESSIONS = HERE.parent / 'data' / 'master' / 'sessions'
OUT = HERE / 'docs' / 'report_figures'
SR = 48000
TILE_SESSION, NOTILE_SESSION, ROOM_SESSION = '2026-10-19_18-44-39', '2026-10-19_18-26-52', '2026-10-19_18-20-14'
GOOD_EX, CRACK_EX, STRIKER_EX = 'S0020', 'S0024', 'S0010'
GREEN, RED, GREY = 'tab:green', 'tab:red', '0.25'


def load(path):
    w = wave.open(str(path))
    return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float) / 32768


def clip(session, sid):
    return load(SESSIONS / session / 'clips' / f'{sid}_strike.wav')


def onset(x):
    e = np.abs(np.diff(x, prepend=0))
    lo, hi = int(.35 * SR), int(.75 * SR)
    base = np.percentile(e[:int(.3 * SR)], 99)
    seg = e[lo:hi]
    idx = np.where(seg > max(base * 3, .2 * seg.max()))[0]
    return lo + (idx[0] if len(idx) else seg.argmax())


def after(x, a_ms, b_ms):
    o = onset(x)
    return x[o + int(a_ms * SR / 1000):o + int(b_ms * SR / 1000)]


def spectrum(x):
    f, p = welch(after(x, 5, 250), SR, nperseg=2048, noverlap=1536)
    return f, 10 * np.log10(p + 1e-20)


def band_db(x, lo, hi):
    f, p = welch(after(x, 5, 300), SR, nperseg=2048, noverlap=1536)
    m = (f >= lo) & (f < hi)
    return 10 * np.log10(p[m].sum() + 1e-20)


def centroid(x):
    f, p = welch(after(x, 5, 300), SR, nperseg=2048, noverlap=1536)
    m = f >= 100
    return float((f[m] * p[m]).sum() / p[m].sum())


def envelope_db(x, step_ms=10, n=30):
    seg = after(x, 0, step_ms * n)
    w = int(step_ms * SR / 1000)
    return np.array([10 * np.log10(np.mean(seg[i * w:(i + 1) * w] ** 2) + 1e-14) for i in range(n)])


labels = json.load(open(HERE / 'data' / 'labels.json'))['labels']
good = [k.split('/')[1] for k, v in labels.items() if k.startswith(TILE_SESSION) and v['label'] == 'good']
cracked = [k.split('/')[1] for k, v in labels.items() if k.startswith(TILE_SESSION) and v['label'] == 'cracked']
tiles = {s: clip(TILE_SESSION, s) for s in good + cracked}
striker = [clip(NOTILE_SESSION, f'S{i:04d}') for i in range(1, 26)]
print(f'good {len(good)}  cracked {len(cracked)}  striker-only {len(striker)}')

# 01 waveforms
room_file = sorted((SESSIONS / ROOM_SESSION / 'audio').glob('*.wav'))[0]
room = load(room_file)[:int(1.5 * SR)]
panels = [('Room noise, striker resting (1.5 s)', room, None),
          (f'Striker only, no tile ({STRIKER_EX})', striker[int(STRIKER_EX[1:]) - 1], GREY),
          (f'Good tile ({GOOD_EX})', tiles[GOOD_EX], GREEN),
          (f'Cracked tile ({CRACK_EX})', tiles[CRACK_EX], RED)]
fig, ax = plt.subplots(4, 1, figsize=(11, 9), sharey=True)
for a, (title, x, c) in zip(ax, panels):
    a.plot(np.arange(len(x)) / SR, x, lw=.5, color=c or 'tab:blue')
    a.set_title(title, loc='left', fontsize=10); a.set_ylabel('amplitude'); a.set_ylim(-1.05, 1.05)
ax[-1].set_xlabel('time in clip, s (strike is about 0.5 s in)')
fig.tight_layout(); fig.savefig(OUT / '01_waveforms.png', dpi=110); plt.close(fig)
print('room noise rms', round(float(np.sqrt(np.mean(room ** 2))), 4))
for name, x in (('striker', striker[int(STRIKER_EX[1:]) - 1]), ('good', tiles[GOOD_EX]), ('cracked', tiles[CRACK_EX])):
    print(f'peak {name}: {np.abs(x).max():.3f}')

# 02 average spectra
def mean_spec(clips):
    f, _ = spectrum(clips[0])
    return f, np.mean([10 ** (spectrum(c)[1] / 10) for c in clips], 0)
f, sp_nt = mean_spec(striker); _, sp_g = mean_spec(list(tiles[s] for s in good)); _, sp_c = mean_spec(list(tiles[s] for s in cracked))
fig, ax = plt.subplots(1, 2, figsize=(13, 4.8))
for a, ymax in zip(ax, (None, None)):
    a.semilogx(f[1:], 10 * np.log10(sp_nt[1:]), color=GREY, label=f'striker only (n={len(striker)})')
    a.semilogx(f[1:], 10 * np.log10(sp_g[1:]), color=GREEN, label=f'good (n={len(good)})')
    a.semilogx(f[1:], 10 * np.log10(sp_c[1:]), color=RED, label=f'cracked (n={len(cracked)})')
    a.set_xlim(100, 20000); a.set_xlabel('Hz'); a.set_ylabel('dB (relative)'); a.legend(); a.grid(alpha=.3, which='both')
ax[0].set_title('Average spectrum, 5-250 ms after the strike')
ax[1].set_title('Same, 100 Hz - 8 kHz'); ax[1].set_xlim(100, 8000)
fig.tight_layout(); fig.savefig(OUT / '02_average_spectra.png', dpi=110); plt.close(fig)

# 03 per-tile features
feats = [('100-500 Hz band, dB', lambda x: band_db(x, 100, 500)),
         ('500-2000 Hz band, dB', lambda x: band_db(x, 500, 2000)),
         ('2000-8000 Hz band, dB', lambda x: band_db(x, 2000, 8000)),
         ('spectral centroid, Hz', centroid)]
rng = np.random.default_rng(1)
fig, ax = plt.subplots(1, 4, figsize=(14, 4.2))
print('\nfeature                  good mean   cracked mean')
for a, (name, fn) in zip(ax, feats):
    g = [fn(tiles[s]) for s in good]; c = [fn(tiles[s]) for s in cracked]
    a.boxplot([g, c], widths=.5, showfliers=False)
    for i, (vals, col) in enumerate(((g, GREEN), (c, RED)), 1):
        a.scatter(i + rng.uniform(-.12, .12, len(vals)), vals, color=col, zorder=3, s=22)
    a.set_xticks([1, 2]); a.set_xticklabels([f'good\nn={len(g)}', f'cracked\nn={len(c)}']); a.set_title(name, fontsize=10)
    print(f'{name:24s} {np.mean(g):9.1f} {np.mean(c):12.1f}')
fig.tight_layout(); fig.savefig(OUT / '03_feature_spread.png', dpi=110); plt.close(fig)

# 04 decay
t = np.arange(30) * 10 + 5
env = lambda clips: np.array([envelope_db(x) for x in clips])
eg, ec, es = env([tiles[s] for s in good]), env([tiles[s] for s in cracked]), env(striker)
fig, a = plt.subplots(figsize=(8, 4.6))
for e, col, name in ((es, GREY, 'striker only'), (eg, GREEN, 'good'), (ec, RED, 'cracked')):
    m, sd = e.mean(0), e.std(0)
    a.plot(t, m, color=col, label=f'{name} (n={len(e)})'); a.fill_between(t, m - sd, m + sd, color=col, alpha=.15)
a.set_xlabel('ms after the strike'); a.set_ylabel('energy per 10 ms, dB'); a.legend(); a.grid(alpha=.3)
a.set_title('How fast the sound fades (mean +/- 1 sd)')
fig.tight_layout(); fig.savefig(OUT / '04_decay.png', dpi=110); plt.close(fig)
print('\nwrote', *(p.name for p in sorted(OUT.glob('0[1-4]*.png'))))
