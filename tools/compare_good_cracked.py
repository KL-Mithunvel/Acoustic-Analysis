r"""Side-by-side picture of one good and one cracked tile strike, raw and with the striker removed.

Top row: spectrograms as recorded. Middle row: the same with the average striker-only
spectrogram (25 no-tile strikes, aligned at the onset) subtracted. Bottom row: spectra,
raw (left) and striker removed (right). Writes <repo>/data/good_vs_cracked.png.

    venv\Scripts\python tools\compare_good_cracked.py [good_id] [cracked_id]
"""
import sys, wave, glob, json
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.signal import stft

R = Path(__file__).resolve().parents[2]
SR = 48000; PRE = int(.03*SR); POST = int(.30*SR)
SESS = '2026-10-19_18-44-39'; NOTILE = '2026-10-19_18-26-52'
good = sys.argv[1] if len(sys.argv) > 1 else 'S0020'
crack = sys.argv[2] if len(sys.argv) > 2 else 'S0024'

def load(p):
    w = wave.open(str(p)); return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float)/32768
def cut(x):
    e = np.abs(np.diff(x, prepend=0)); lo, hi = int(.35*SR), int(.75*SR)
    b = np.percentile(e[:int(.3*SR)], 99); s = e[lo:hi]
    i = np.where(s > max(b*3, .2*s.max()))[0]; o = lo + (i[0] if len(i) else s.argmax())
    return x[o-PRE:o+POST]
def spec(c):
    f, t, Z = stft(c, SR, nperseg=1024, noverlap=768); return f, t-PRE/SR, np.abs(Z)**2
nt = [cut(load(p)) for p in sorted(glob.glob(str(R/'data/master/sessions'/NOTILE/'clips/S*_strike.wav')))]
NT = np.mean([spec(c)[2] for c in nt], 0)
clips = {k: cut(load(R/'data/master/sessions'/SESS/'clips'/f'{k}_strike.wav')) for k in (good, crack)}
lab = json.load(open(R/'Acoustic-Analysis/data/labels.json'))['labels']
for k in (good, crack): print(k, 'labelled', lab.get(f'{SESS}/{k}', {}).get('label'))
db = lambda p: 10*np.log10(p + 1e-12)
fig, ax = plt.subplots(3, 2, figsize=(12, 11))
raw_ps = {}; res_ps = {}
for j, (k, name) in enumerate([(good, 'GOOD'), (crack, 'CRACKED')]):
    f, t, P = spec(clips[k]); res = np.maximum(P - NT, P*1e-3)
    for i, (M, ttl) in enumerate([(P, 'as recorded'), (res, 'striker removed')]):
        im = ax[i, j].pcolormesh(t, f, db(M), vmin=-100, vmax=-40, shading='auto')
        ax[i, j].set_ylim(0, 8000); ax[i, j].set_title(f'{name} {k} - {ttl}'); ax[i, j].set_ylabel('Hz')
    raw_ps[name] = P.mean(1); res_ps[name] = res.mean(1)
for i, (d, ttl) in enumerate([(raw_ps, 'spectrum, as recorded'), (res_ps, 'spectrum, striker removed')]):
    a = ax[2, i]
    a.semilogx(f[1:], db(NT.mean(1))[1:], 'k', lw=1, label='striker only') if i == 0 else None
    a.semilogx(f[1:], db(d['GOOD'])[1:], 'tab:green', label='good'); a.semilogx(f[1:], db(d['CRACKED'])[1:], 'tab:red', label='cracked')
    a.set_xlim(100, 20000); a.set_title(ttl); a.set_ylabel('dB'); a.set_xlabel('Hz'); a.legend()
fig.colorbar(im, ax=ax[:2, :], label='dB'); 
out = R/'data/good_vs_cracked.png'; fig.savefig(out, dpi=110); print(out)
