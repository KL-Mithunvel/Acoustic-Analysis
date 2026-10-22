r"""Numbers and figures for docs/FINAL_REPORT.md.

Runs the app's own strike analysis (``strike_features`` / ``strike_reference.evaluate``) on the
real 2026-10-19 station clips that are labelled in data/labels.json, plus timing and distance-sensor
statistics from strikes.json, (the three diagrams are drawn by make_report_diagrams.py) and plots:

  fig8_feature_auc.png    per-feature separation of cracked from good (AUC)
  fig9_reference_z.png    worst robust z-score per labelled tile (leave-one-out for good)
  fig10_sensor_timing.png ToF distance (tile vs empty) and strike position in the clip
  fig11_first_six.png     the first six tile strikes vs the rest (open question in TODO.md)

and writes docs/final_report_figures/numbers.json (every figure quoted in the report).

    venv\Scripts\python tools\make_final_report_figures.py
"""
import json
import wave
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import sys
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from acoustic_analysis.config import load_config  # noqa: E402
from acoustic_analysis.strike_features import strike_features  # noqa: E402
from acoustic_analysis.strike_reference import build_reference, grade_strike, evaluate  # noqa: E402

SESS = HERE.parent / 'data' / 'master' / 'sessions'
OUT = HERE / 'docs' / 'final_report_figures'
OUT.mkdir(parents=True, exist_ok=True)
TILE_S, NOTILE_S = '2026-10-19_18-44-39', '2026-10-19_18-26-52'
SR = 48000
INK, MUTE = '#1f2933', '#6b7785'
BLUE, GREEN, AMBER, RED, GREY, VIOLET = '#2b6cb0', '#2f855a', '#c77d0a', '#c53030', '#718096', '#6b46c1'
rng = np.random.default_rng(7)
cfg = load_config()
numbers = {}


def load(path):
    w = wave.open(str(path))
    return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float) / 32768


labels = json.load(open(HERE / 'data' / 'labels.json'))['labels']
tile_strikes = json.load(open(SESS / TILE_S / 'strikes.json'))
notile_strikes = json.load(open(SESS / NOTILE_S / 'strikes.json'))

# ------------------------------------------------------------------ features of every labelled tile strike
feats, lab = {}, {}
for key, v in labels.items():
    sess, sid = key.split('/')
    if sess != TILE_S:
        continue
    x = load(SESS / sess / 'clips' / f'{sid}_strike.wav')
    feats[sid] = strike_features(x, SR, cfg)
    lab[sid] = v['label']
good = [s for s in feats if lab[s] == 'good']
crack = [s for s in feats if lab[s] == 'cracked']
numbers['n_good'], numbers['n_cracked'] = len(good), len(crack)
numbers['onset_found'] = {'good': sum(feats[s]['onset_found'] for s in good), 'cracked': sum(feats[s]['onset_found'] for s in crack)}

keys = cfg['strike']['reference']['features']
numbers['features_good_median'] = {k: float(np.median([feats[s][k] for s in good if feats[s][k] is not None])) for k in keys}
numbers['features_cracked_median'] = {k: float(np.median([feats[s][k] for s in crack if feats[s][k] is not None])) for k in keys}
numbers['snr_db'] = {'min': float(min(f['snr_db'] for f in feats.values())), 'median': float(np.median([f['snr_db'] for f in feats.values()])),
                     'max': float(max(f['snr_db'] for f in feats.values()))}
numbers['onset_s'] = {'min': float(min(f['onset_s'] for f in feats.values())), 'max': float(max(f['onset_s'] for f in feats.values())),
                      'median': float(np.median([f['onset_s'] for f in feats.values()]))}

# ------------------------------------------------------------------ leave-one-out reference check (the app's own evaluate())
items = [(s, feats[s], lab[s]) for s in feats]
ev = evaluate(items, cfg)
numbers['evaluate'] = {k: v for k, v in ev.items()}
full = build_reference([feats[s] for s in good], cfg)
zmax = {}
for i, s in enumerate(good):
    loo = build_reference([feats[g] for g in good if g != s], cfg)
    zmax[s] = max(abs(z) for z in grade_strike(feats[s], loo, cfg)['z'].values())
for s in crack:
    zmax[s] = max(abs(z) for z in grade_strike(feats[s], full, cfg)['z'].values())
numbers['worst_z'] = {'good_median': float(np.median([zmax[s] for s in good])), 'good_max': float(max(zmax[s] for s in good)),
                      'cracked_median': float(np.median([zmax[s] for s in crack])), 'cracked_max': float(max(zmax[s] for s in crack)),
                      'cracked_min': float(min(zmax[s] for s in crack))}
numbers['z_by_tile'] = {s: round(zmax[s], 2) for s in zmax}


# ------------------------------------------------------------------ per-feature AUC + permutation p (cracked vs good)
def auc(a, b):                       # P(a > b) + 0.5 P(a == b)
    a, b = np.asarray(a), np.asarray(b)
    return float(((a[:, None] > b[None, :]).sum() + 0.5 * (a[:, None] == b[None, :]).sum()) / (a.size * b.size))


def perm_p(a, b, n=20000):
    a, b = np.asarray(a, float), np.asarray(b, float)
    obs = abs(a.mean() - b.mean())
    pool = np.concatenate([a, b]); cnt = 0
    for _ in range(n):
        rng.shuffle(pool)
        cnt += abs(pool[:a.size].mean() - pool[a.size:].mean()) >= obs
    return (cnt + 1) / (n + 1)               # Phipson & Smyth: the observed value counts as one permutation


allkeys = ['snr_db', 'centroid_hz', 'peak_hz', 'f_low', 'f_mid', 'f_high', 'f_top', 'slope_db_ms']
rows = []
for k in allkeys:
    g = [feats[s][k] for s in good if feats[s][k] is not None]
    c = [feats[s][k] for s in crack if feats[s][k] is not None]
    rows.append({'feature': k, 'good_median': float(np.median(g)), 'cracked_median': float(np.median(c)),
                 'auc': auc(c, g), 'p': perm_p(c, g)})
numbers['feature_tests'] = rows

fig, ax = plt.subplots(figsize=(8, 4.2))
names = [r['feature'] for r in rows]
vals = [r['auc'] for r in rows]
ax.barh(names, vals, color=[BLUE if abs(v - .5) < .2 else AMBER for v in vals])
ax.axvline(.5, color=MUTE, ls='--', lw=1); ax.set_xlim(0, 1)
for i, r in enumerate(rows):
    ax.text(min(r['auc'] + .02, .84), i, f"AUC {r['auc']:.2f}  p={r['p']:.2f}", va='center', fontsize=8, color=INK)
ax.set_xlabel(f"AUC, cracked (n={len(crack)}) ranked above good (n={len(good)}); 0.5 = no separation")
ax.invert_yaxis(); ax.set_title('How well each sound feature separates cracked from good', loc='left', fontsize=10)
for sp in ('top', 'right'): ax.spines[sp].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / 'fig8_feature_auc.png', dpi=130); plt.close(fig)

fig, ax = plt.subplots(figsize=(8, 4.2))
order = sorted(zmax, key=lambda s: zmax[s])
ax.bar(range(len(order)), [zmax[s] for s in order], color=[RED if s in crack else GREEN for s in order])
ax.axhline(cfg['strike']['reference']['z_ok'], color=AMBER, ls='--', lw=1); ax.axhline(cfg['strike']['reference']['z_bad'], color=RED, ls='--', lw=1)
ax.text(.2, cfg['strike']['reference']['z_ok'] + .1, 'GOOD / BORDERLINE (z=3)', fontsize=8, color=AMBER)
ax.text(.2, cfg['strike']['reference']['z_bad'] + .1, 'BORDERLINE / DEFECTIVE (z=6)', fontsize=8, color=RED)
ax.set_xticks(range(len(order))); ax.set_xticklabels(order, rotation=90, fontsize=7)
ax.set_ylabel('worst robust z-score'); ax.set_title('Distance from the good-tile reference (green = good, leave-one-out; red = cracked)', loc='left', fontsize=10)
for sp in ('top', 'right'): ax.spines[sp].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / 'fig9_reference_z.png', dpi=130); plt.close(fig)

# ------------------------------------------------------------------ distance sensor + where the strike sits in the clip
tof_tile = [s['tof_mm'] for s in tile_strikes if s['kind'] == 'strike' and s['source'] == 'tof' and s['tile_present']]
tof_empty = [s['tof_mm'] for s in notile_strikes if s['kind'] == 'strike' and s['tof_mm'] is not None]
numbers['tof_tile_mm'] = {'n': len(tof_tile), 'min': min(tof_tile), 'max': max(tof_tile), 'median': float(np.median(tof_tile))}
numbers['tof_empty_mm'] = {'n': len(tof_empty), 'min': min(tof_empty), 'max': max(tof_empty), 'median': float(np.median(tof_empty))}
ret = [s['retract_to_strike_ms'] for s in tile_strikes if s['kind'] == 'strike' and s.get('retract_to_strike_ms') and s['source'] == 'tof']
numbers['retract_to_strike_ms_tof'] = {'n': len(ret), 'min': min(ret), 'median': float(np.median(ret)), 'max': max(ret)}
ret_m = [s['retract_to_strike_ms'] for s in notile_strikes if s['kind'] == 'strike' and s.get('retract_to_strike_ms')]
numbers['retract_to_strike_ms_manual'] = {'n': len(ret_m), 'min': min(ret_m), 'median': float(np.median(ret_m)), 'max': max(ret_m)}

noonsets = []
for i in range(1, 26):
    f = strike_features(load(SESS / NOTILE_S / 'clips' / f'S{i:04d}_strike.wav'), SR, cfg)
    if f['onset_found']:
        noonsets.append(f['onset_s'])
numbers['onset_s_no_tile'] = {'n': len(noonsets), 'min': float(min(noonsets)), 'max': float(max(noonsets)), 'median': float(np.median(noonsets))}

fig, ax = plt.subplots(1, 2, figsize=(10.5, 3.9))
bins = np.arange(75, 185, 5)
ax[0].hist(tof_tile, bins, color=GREEN, alpha=.85, label=f'tile under striker (n={len(tof_tile)})')
ax[0].hist(tof_empty, bins, color=GREY, alpha=.85, label=f'empty surface (n={len(tof_empty)})')
ax[0].axvline(100, color=RED, ls='--', lw=1.2); ax[0].text(101, ax[0].get_ylim()[1] * .9, 'threshold 100 mm', color=RED, fontsize=8)
ax[0].set_xlabel('ToF distance at the strike, mm'); ax[0].set_ylabel('strikes'); ax[0].legend(fontsize=8, frameon=False)
ax[0].set_title('Tile-present sensor', loc='left', fontsize=10)
on_t = [f['onset_s'] for f in feats.values()]
ax[1].hist(noonsets, np.arange(.40, .62, .01), color=GREY, alpha=.85, label=f'striker alone (n={len(noonsets)})')
ax[1].hist(on_t, np.arange(.40, .62, .01), color=BLUE, alpha=.85, label=f'labelled tiles (n={len(on_t)})')
ax[1].axvline(cfg['strike']['expect_s'], color=RED, ls='--', lw=1.2); ax[1].text(cfg['strike']['expect_s'] + .003, ax[1].get_ylim()[1] * .9, 'expected 0.5 s', color=RED, fontsize=8)
ax[1].set_xlabel('detected strike onset in the 1.5 s clip, s'); ax[1].set_ylabel('clips'); ax[1].legend(fontsize=8, frameon=False)
ax[1].set_title('Where the strike lands in each clip', loc='left', fontsize=10)
for a in ax:
    for sp in ('top', 'right'): a.spines[sp].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / 'fig10_sensor_timing.png', dpi=130); plt.close(fig)

# ------------------------------------------------------------------ the first six tile strikes vs the rest
tile_ids = [s['id'] for s in tile_strikes if s['kind'] == 'strike' and s['source'] == 'tof']
first6 = tile_ids[:6]
numbers['first_six_ids'] = first6
fx = {}
for sid in tile_ids:
    fx[sid] = strike_features(load(SESS / TILE_S / 'clips' / f'{sid}_strike.wav'), SR, cfg)
rest = [s for s in tile_ids if s not in first6]
cmp_keys = ['centroid_hz', 'f_low', 'f_top', 'slope_db_ms', 't20_ms']
numbers['first_six_vs_rest'] = {k: {'first6_median': float(np.median([fx[s][k] for s in first6 if fx[s][k] is not None])),
                                    'rest_median': float(np.median([fx[s][k] for s in rest if fx[s][k] is not None])),
                                    'first6_n_none': sum(fx[s][k] is None for s in first6),
                                    'rest_n_none': sum(fx[s][k] is None for s in rest)} for k in cmp_keys}
numbers['first_six_vs_rest']['n_first6'], numbers['first_six_vs_rest']['n_rest'] = len(first6), len(rest)
fig, ax = plt.subplots(1, 3, figsize=(11, 3.6))
for a, k, t in zip(ax, ['centroid_hz', 'f_low', 'slope_db_ms'], ['spectral centroid, Hz', 'share of energy below 1 kHz', 'fade slope, dB/ms']):
    a.scatter(rng.uniform(-.12, .12, len(first6)) + 1, [fx[s][k] for s in first6], color=AMBER, s=26, zorder=3)
    a.scatter(rng.uniform(-.12, .12, len(rest)) + 2, [fx[s][k] for s in rest], color=BLUE, s=26, zorder=3)
    a.set_xticks([1, 2]); a.set_xticklabels([f'first {len(first6)}', f'later {len(rest)}']); a.set_title(t, fontsize=9)
    for sp in ('top', 'right'): a.spines[sp].set_visible(False)
fig.suptitle('Tile strikes of session 2026-10-19_18-44-39: the first six against the rest', fontsize=10, x=.01, ha='left')
fig.tight_layout(); fig.savefig(OUT / 'fig11_first_six.png', dpi=130); plt.close(fig)


# ------------------------------------------------------------------ baseline: the camera's own grade on the same tiles
cam = {}
for line in open(SESS / TILE_S / 'events.jsonl', encoding='utf-8'):
    e = json.loads(line)
    t = e.get('topic', '')
    if t.startswith('tile/') and t.endswith('/camera/result'):
        cam[t.split('/')[1]] = e['payload']
tile_of = {x['id']: x['tile_id'] for x in tile_strikes if x['kind'] == 'strike'}
cam_reject = {s for s in feats if tile_of.get(s) in cam and cam[tile_of[s]].get('grade') == 'Reject'}
cam_have = {s for s in feats if tile_of.get(s) in cam}
sound_flag = {s for s in feats if grade_strike(feats[s], full if s in crack else
                                              build_reference([feats[g] for g in good if g != s], cfg), cfg)['grade'] in ('BORDERLINE', 'DEFECTIVE')}
union = cam_reject | sound_flag
numbers['camera_baseline'] = {
    'tiles_with_camera_result': len(cam_have),
    'good_rejected_by_camera': len(cam_reject & set(good)), 'good_total': len(good),
    'cracked_rejected_by_camera': len(cam_reject & set(crack)), 'cracked_total': len(crack),
    'corner_broken_flag_on_rejects': sum(bool(cam[tile_of[s]].get('corner_broken')) for s in cam_reject),
    'corner_fill_ratio_range_on_rejects': [min(cam[tile_of[s]]['corner_fill_ratio'] for s in cam_reject),
                                           max(cam[tile_of[s]]['corner_fill_ratio'] for s in cam_reject)],
}
numbers['sound_flags'] = {'good_flagged': len(sound_flag & set(good)), 'cracked_flagged': len(sound_flag & set(crack))}
numbers['worse_of_camera_and_sound'] = {'good_flagged': len(union & set(good)), 'cracked_flagged': len(union & set(crack))}
later = [s for s in tile_ids if s not in first6 and s in feats]
numbers['later16'] = {'n': len(later), 'max_worst_z': float(max(zmax[s] for s in later)),
                      'good': sum(lab[s] == 'good' for s in later), 'cracked': sum(lab[s] == 'cracked' for s in later)}

# ------------------------------------------------------------------ numbers
def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


json.dump(clean(numbers), open(OUT / 'numbers.json', 'w'), indent=1)
print(json.dumps(clean(numbers), indent=1))
print('wrote', *(p.name for p in sorted(OUT.glob('*.png'))))
