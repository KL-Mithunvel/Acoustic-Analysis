r"""Is a narrow steady peak (default 4.4 kHz) after the strike a cracked-tile marker?

For every tile labelled in data/labels.json: take 100-300 ms after the strike onset (the
striker's own click is over by then), compute a fine power spectrum, and measure how far
the 4.2-4.6 kHz band stands above its neighbours (prominence, dB). Compares good vs
cracked (means, AUC, shuffle-test p), and scans every other frequency with the same
statistic so a 4.4 kHz result can be judged against the multiple-comparison chance.
Writes <repo>/data/steady_peak.png.

    venv\Scripts\python tools\test_steady_peak.py [centre_hz]
"""
import sys, wave, json
from pathlib import Path
import numpy as np
from scipy.signal import welch
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

R = Path(__file__).resolve().parents[2]; SR = 48000
F0 = float(sys.argv[1]) if len(sys.argv) > 1 else 4400.0; HW = 200.0
def load(p):
    w = wave.open(str(p)); return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float)/32768
def onset(x):
    e = np.abs(np.diff(x, prepend=0)); lo, hi = int(.35*SR), int(.75*SR)
    b = np.percentile(e[:int(.3*SR)], 99); s = e[lo:hi]
    i = np.where(s > max(b*3, .2*s.max()))[0]; return lo + (i[0] if len(i) else s.argmax())
def psd(x):
    o = onset(x); seg = x[o+int(.10*SR):o+int(.30*SR)]
    f, p = welch(seg, SR, nperseg=4096, noverlap=3072); return f, 10*np.log10(p+1e-20)
def prominence(f, d):  # dB above the local median +-700 Hz (excluding nothing: median is robust)
    out = np.empty_like(d)
    for i in range(len(f)): m = (abs(f-f[i]) < 700); out[i] = d[i]-np.median(d[m])
    return out
lab = json.load(open(R/'Acoustic-Analysis/data/labels.json'))['labels']
ids, ys, P = [], [], []
for k, v in sorted(lab.items()):
    s, i = k.split('/'); x = load(R/'data/master/sessions'/s/'clips'/f'{i}_strike.wav')
    f, d = psd(x); P.append(prominence(f, d)); ids.append(i); ys.append(1 if v['label'] == 'cracked' else 0)
P = np.array(P); y = np.array(ys); print('good', (y == 0).sum(), 'cracked', (y == 1).sum())
def stat(c): return P[:, (f >= c-HW) & (f <= c+HW)].max(1)
def auc(v): g, c = v[y == 0], v[y == 1]; return np.mean([(cc > gg) + .5*(cc == gg) for cc in c for gg in g])
def perm(v, n=20000, seed=0):
    rng = np.random.default_rng(seed); o = abs(v[y == 1].mean()-v[y == 0].mean())
    return np.mean([abs(v[(q := rng.permutation(y)) == 1].mean()-v[q == 0].mean()) >= o for _ in range(n)])
v = stat(F0)
print(f'\n{F0:.0f} Hz +-{HW:.0f}: peak prominence above neighbours (dB)')
print('  good    mean %.2f  sd %.2f   cracked mean %.2f  sd %.2f' % (v[y == 0].mean(), v[y == 0].std(ddof=1), v[y == 1].mean(), v[y == 1].std(ddof=1)))
print('  AUC (cracked > good) %.2f   shuffle p %.3f' % (auc(v), perm(v)))
print('\n id      label    prominence')
for i, l, a in sorted(zip(ids, y, v), key=lambda t: -t[2]): print(' %s  %-8s %5.1f' % (i, 'cracked' if l else 'good', a))
# scan
cs = np.arange(600, 12000, 100); A = np.array([auc(stat(c)) for c in cs]); D = np.array([stat(c)[y == 1].mean()-stat(c)[y == 0].mean() for c in cs])
print('\nscan: best centres by AUC'); 
for j in np.argsort(-A)[:6]: print('  %5.0f Hz  AUC %.2f  diff %.1f dB' % (cs[j], A[j], D[j]))
print('  AUC at %.0f Hz ranks %d of %d centres' % (F0, 1+np.sum(A > auc(v)), len(cs)))
fig, ax = plt.subplots(1, 2, figsize=(13, 4.5))
for g, c in [(0, 'tab:green'), (1, 'tab:red')]:
    for p in P[y == g]: ax[0].plot(f, p, c, alpha=.25)
    ax[0].plot(f, P[y == g].mean(0), c, lw=2, label=['good', 'cracked'][g])
ax[0].axvspan(F0-HW, F0+HW, color='k', alpha=.08); ax[0].set_xlim(500, 10000); ax[0].set_xlabel('Hz'); ax[0].set_ylabel('prominence, dB'); ax[0].legend(); ax[0].set_title('Peak prominence, 100-300 ms after strike')
ax[1].plot(cs, A, 'k'); ax[1].axhline(.5, color='grey', ls=':'); ax[1].axvline(F0, color='tab:red', alpha=.5); ax[1].set_xlabel('band centre, Hz'); ax[1].set_ylabel('AUC (cracked vs good)'); ax[1].set_title('Same test at every frequency')
fig.tight_layout(); fig.savefig(R/'data/steady_peak.png', dpi=110); print(R/'data/steady_peak.png')
