r"""Does anything in the sound tell good tiles from cracked ones once the striker is removed?

Averages the power spectrum of the striker-only (no tile) strikes of one session,
subtracts it from every strike you labelled in ``data/labels.json`` (station
sessions under ``<repo>/data/master/sessions``), then compares good vs cracked on
frequency bands + centroid, with a shuffle test and a decay check. Writes
``<repo>/data/striker_subtraction.png``. Written 2026-10-22; strike alignment is a
rough onset threshold, not ``strike_features``. Few cracked clips = weak test.

    venv\Scripts\python tools\striker_subtraction.py [no_tile_session_folder_name]
"""
import wave,json,glob,numpy as np
import sys
from pathlib import Path
# Acoustic-Analysis/tools/ -> the Tile_Sorting repo root (where data/master/sessions lives)
R=str(Path(__file__).resolve().parents[2])+'/'
NO_TILE_SESSION=sys.argv[1] if len(sys.argv)>1 else '2026-10-19_18-26-52'
SR=48000
def load(p):
    w=wave.open(p);return np.frombuffer(w.readframes(w.getnframes()),np.int16).astype(float)/32768
def onset(x):
    hp=np.diff(x,prepend=0)  # crude high-pass
    e=np.abs(hp); lo,hi=int(.35*SR),int(.75*SR)
    base=np.percentile(e[:int(.3*SR)],99)
    seg=e[lo:hi]; idx=np.where(seg>max(base*3,0.2*seg.max()))[0]
    return lo+(idx[0] if len(idx) else seg.argmax())
PRE,POST=int(.01*SR),int(.30*SR)
def cut(x):
    o=onset(x);return x[o-PRE:o+POST],o
nt=[cut(load(p)) for p in sorted(glob.glob(R+'data/master/sessions/'+NO_TILE_SESSION+'/clips/S*_strike.wav'))]
print('no-tile onsets (s):',np.round([o/SR for _,o in nt],3))
NT=np.array([c for c,_ in nt]);avg_t=NT.mean(0)
win=np.hanning(len(avg_t))
def ps(x):return np.abs(np.fft.rfft(x*win))**2
f=np.fft.rfftfreq(len(avg_t),1/SR)
NTps=np.array([ps(c) for c in NT]);avg_ps=NTps.mean(0)
print('no-tile spread: per-clip power vs mean, std of dB in 0.5-8k:',np.round(np.std(10*np.log10(NTps[:,(f>500)&(f<8000)].sum(1)/avg_ps[(f>500)&(f<8000)].sum())),2))
lab=json.load(open(R+'Acoustic-Analysis/data/labels.json'))['labels']
rows=[]
for k,v in sorted(lab.items()):
    s,i=k.split('/');x=load(R+f'data/master/sessions/{s}/clips/{i}_strike.wav');c,o=cut(x)
    rows.append((i,v['label'],c,o/SR))
bands=[(100,500),(500,1000),(1000,2000),(2000,4000),(4000,8000),(8000,16000)]
def feats(p):
    t=p.sum();out=[10*np.log10(t+1e-20)]
    out+=[10*np.log10(p[(f>=a)&(f<b)].sum()+1e-20) for a,b in bands]
    m=(f>100)
    out.append((f[m]*p[m]).sum()/p[m].sum());return out
names=['total_dB']+[f'{a}-{b}' for a,b in bands]+['centroid']
print('\nid label onset | raw feats | residual feats (tile power - mean no-tile power)')
R_raw=[];R_res=[];labs=[]
for i,l,c,o in rows:
    p=ps(c);res=np.maximum(p-avg_ps,p*1e-3)
    # time-domain subtraction
    td=c-avg_t;ptd=ps(td)
    R_raw.append(feats(p));R_res.append(feats(res));labs.append(l)
    print(i,l,round(o,3),'resid_ratio(dB)',round(10*np.log10(res.sum()/p.sum()),1),'td_resid(dB)',round(10*np.log10(ptd.sum()/p.sum()),1))
R_raw=np.array(R_raw);R_res=np.array(R_res);labs=np.array(labs)
def cmp(M,title):
    print('\n',title);print('%-10s %8s %8s %8s %6s'%('feature','good','cracked','diff','d'))
    for j,n in enumerate(names):
        g=M[labs=='good',j];c=M[labs=='cracked',j]
        sp=np.sqrt((g.var(ddof=1)*(len(g)-1)+c.var(ddof=1)*(len(c)-1))/(len(g)+len(c)-2))
        print('%-10s %8.1f %8.1f %8.1f %6.2f'%(n,g.mean(),c.mean(),c.mean()-g.mean(),(c.mean()-g.mean())/sp))
cmp(R_raw,'RAW tile strikes (good n=%d, cracked n=%d)'%((labs=='good').sum(),(labs=='cracked').sum()))
cmp(R_res,'AFTER subtracting striker-only average')
# mean no-tile spectrum level vs tile
print('\nstriker-only mean features:',dict(zip(names,np.round(feats(avg_ps),1))))
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
fig,ax=plt.subplots(2,1,figsize=(11,8))
db=lambda p:10*np.log10(p+1e-12)
ax[0].semilogx(f[1:],db(avg_ps[1:]),'k',lw=2,label='striker only (avg of 25)')
for g,c in [('good','tab:green'),('cracked','tab:red')]:
    m=np.mean([ps(cc) for i,l,cc,o in rows if l==g],0);ax[0].semilogx(f[1:],db(m[1:]),c,label=g+' tile (avg)')
ax[0].set_xlim(100,20000);ax[0].legend();ax[0].set_title('Power spectrum, 300 ms after strike');ax[0].set_ylabel('dB')
for g,c in [('good','tab:green'),('cracked','tab:red')]:
    m=np.mean([np.maximum(ps(cc)-avg_ps,1e-9*avg_ps.max()) for i,l,cc,o in rows if l==g],0);ax[1].semilogx(f[1:],db(m[1:]),c,label=g+' minus striker')
ax[1].set_xlim(100,20000);ax[1].legend();ax[1].set_title('After removing striker-only spectrum');ax[1].set_ylabel('dB')
plt.tight_layout();plt.savefig(R+'data/striker_subtraction.png',dpi=110)

print('\n=== checks ===')
# 1. coherence among no-tile strikes: residual after subtracting mean of the OTHER 24
r=[10*np.log10(np.sum((NT[k]-np.delete(NT,k,0).mean(0))**2)/np.sum(NT[k]**2)) for k in range(25)]
print('no-tile clip minus mean of other 24 (dB, 0=no coherence, -inf=identical): median %.1f'%np.median(r))
# 2. strike vs noise floor: rms of 0-300ms after onset vs 300ms lead-in noise
def snr(x):
    o=onset(x);return 20*np.log10(np.sqrt(np.mean(x[o:o+int(.3*SR)]**2))/np.sqrt(np.mean(x[o-int(.35*SR):o-int(.05*SR)]**2)))
print('SNR strike/lead-in (dB): no-tile median %.1f'%np.median([snr(load(p)) for p in sorted(glob.glob(R+'data/master/sessions/'+NO_TILE_SESSION+'/clips/S*_strike.wav'))]),
 '| tile median %.1f'%np.median([snr(load(R+f"data/master/sessions/{k.split('/')[0]}/clips/{k.split('/')[1]}_strike.wav")) for k in lab]))
# 3. permutation test on residual features
rng=np.random.default_rng(0)
print('permutation p (|mean diff|, 20000 shuffles) on residual features:')
for j,n in enumerate(names):
    v=R_res[:,j];obs=abs(v[labs=='cracked'].mean()-v[labs=='good'].mean());cnt=0
    for _ in range(20000):
        pl=rng.permutation(labs);cnt+=abs(v[pl=='cracked'].mean()-v[pl=='good'].mean())>=obs
    print('  %-10s p=%.3f'%(n,cnt/20000))
# 4. time evolution of the residual: decay, 100-3000Hz energy in successive 50ms windows
print('\nenergy per 50 ms window after onset, dB (good / cracked / striker-only):')
def wins(c):return [10*np.log10(np.mean(c[PRE+k*2400:PRE+(k+1)*2400]**2)+1e-20) for k in range(6)]
G=np.mean([wins(c) for i,l,c,o in rows if l=='good'],0);C=np.mean([wins(c) for i,l,c,o in rows if l=='cracked'],0);N=np.mean([wins(c) for c in NT],0)
print(np.round(G,1),np.round(C,1),np.round(N,1))
