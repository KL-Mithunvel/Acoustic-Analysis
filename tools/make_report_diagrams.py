r"""The three diagrams of docs/FINAL_REPORT.md (architecture, strike state diagram, workflow).

Pure drawing, no data: writes docs/final_report_figures/fig1_architecture.png, fig2_strike_states.png
and fig3_workflow.png. Every arrow is numbered and described in a key under the picture, so no label
sits on top of a box.

    venv\Scripts\python tools\make_report_diagrams.py
"""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = Path(__file__).resolve().parents[1] / 'docs' / 'final_report_figures'
OUT.mkdir(parents=True, exist_ok=True)
INK, MUTE = '#1f2933', '#6b7785'
BLUE, GREEN, AMBER, RED, GREY, VIOLET = '#2b6cb0', '#2f855a', '#c77d0a', '#c53030', '#718096', '#6b46c1'


def box(ax, x, y, w, h, text, fc, ec=None, fs=8.5, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.004,rounding_size=0.012', fc=fc, ec=ec or fc, lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha='center', va='center', fontsize=fs, color=INK,
            fontweight='bold' if bold else 'normal', linespacing=1.3)


def arrow(ax, p, q, n=None, color=MUTE, rad=0.0, both=False, nx=0.0, ny=0.0):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle='<|-|>' if both else '-|>', mutation_scale=11, lw=1.4, color=color,
                                 connectionstyle=f'arc3,rad={rad}', shrinkA=1, shrinkB=1, zorder=3))
    if n is not None:
        mx, my = (p[0] + q[0]) / 2 + nx, (p[1] + q[1]) / 2 + ny
        ax.add_patch(plt.Circle((mx, my), .0135, fc='white', ec=color, lw=1.2, zorder=5))
        ax.text(mx, my, str(n), ha='center', va='center', fontsize=7.5, color=color, fontweight='bold', zorder=6)


def legend(ax, items, y0, cols=3, x0=.01, dx=.33, dy=.035, fs=7.6):
    per = -(-len(items) // cols)
    for i, (n, t, c) in enumerate(items):
        x, y = x0 + (i // per) * dx, y0 - (i % per) * dy
        ax.add_patch(plt.Circle((x + .008, y), .0115, fc='white', ec=c, lw=1.1, zorder=5))
        ax.text(x + .008, y, str(n), ha='center', va='center', fontsize=7, color=c, fontweight='bold', zorder=6)
        ax.text(x + .024, y, t, ha='left', va='center', fontsize=fs, color=INK)


def canvas(w, h, title, sub=None):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis('off')
    ax.text(.01, .985, title, fontsize=13, fontweight='bold', color=INK, va='top')
    if sub:
        ax.text(.01, .94, sub, fontsize=8.8, color=MUTE, va='top')
    return fig, ax


def panel(ax, x, y, w, h, fc, ec, label, lc, right=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.004,rounding_size=0.015', fc=fc, ec=ec, lw=1))
    ax.text(x + w - .012 if right else x + .012, y + h - .02, label, fontsize=8, color=lc, fontweight='bold', va='top',
            ha='right' if right else 'left')


# ---- Figure 1: architecture
fig, ax = canvas(12.5, 8.4, 'Acoustic inspection module inside the tile-line station',
                 'Sensing -> computation -> decision -> actuation; each numbered arrow is described in the key below')
panel(ax, .01, .60, .31, .31, '#f1f5f9', '#cbd5e0', 'TEST POINT (physical)', MUTE)
box(ax, .03, .79, .27, .07, 'Sprung solenoid striker (above the tile)', '#fed7d7', RED)
box(ax, .03, .69, .27, .07, 'Clay tile on the belt (hand-turned)', '#feebc8', AMBER)
box(ax, .03, .615, .12, .06, 'USB microphone\n48 kHz, mono', '#bee3f8', BLUE, fs=7.6)
box(ax, .18, .615, .12, .06, 'VL53L0X ToF\nI2C 0x29', '#c6f6d5', GREEN, fs=7.6)
arrow(ax, (.165, .79), (.165, .76), color=RED)
box(ax, .39, .66, .17, .23, 'Arduino Nano\nATmega328P\n\nstriker state machine\n2 s Pi-silence watchdog\nCytron MDD10A drive', '#fefcbf', AMBER, fs=8)
arrow(ax, (.39, .825), (.30, .825), 1, RED)
arrow(ax, (.30, .645), (.39, .70), 2, GREEN)
panel(ax, .01, .12, .79, .45, '#ebf4ff', '#90cdf4', 'PI 5 STATION / LAPTOP (compute)', BLUE, right=True)
box(ax, .03, .39, .15, .10, 'Audio ring buffer\nwall-clock stamped', '#fff', BLUE, fs=7.8)
box(ax, .22, .39, .15, .10, 'Clip cutter\n-0.5 s ... +1.0 s\naround each TAP', '#fff', BLUE, fs=7.8)
box(ax, .41, .39, .15, .10, 'Nano link\nUART 115200\nchecksummed lines', '#fff', BLUE, fs=7.8)
box(ax, .03, .23, .22, .11, 'Strike features\ncentroid, band shares,\nfade slope, t20, SNR', '#fff', VIOLET, fs=7.8)
box(ax, .30, .23, .23, .11, 'Sound grade\nrobust z vs tiles labelled good\nGOOD / BORDERLINE / DEFECTIVE', '#fff', VIOLET, fs=7.6)
box(ax, .57, .23, .21, .11, 'Fusion + store\nworse of camera and sound\nSQLite, one row per tile', '#fff', GREY, fs=7.6)
box(ax, .03, .135, .22, .07, 'Session recorder: WAV, events, labels, SHA-256', '#fff', GREY, fs=7.4)
arrow(ax, (.09, .615), (.105, .49), 3, BLUE)
arrow(ax, (.18, .44), (.22, .44), None, BLUE)
arrow(ax, (.41, .44), (.37, .44), None, AMBER)
arrow(ax, (.475, .66), (.485, .49), 4, AMBER, both=True, nx=.03)
arrow(ax, (.285, .39), (.17, .34), 5, VIOLET)
arrow(ax, (.25, .285), (.30, .285), None, VIOLET)
arrow(ax, (.53, .285), (.57, .285), 6, VIOLET, ny=.03)
arrow(ax, (.14, .23), (.14, .205), None, GREY)
box(ax, .84, .70, .15, .19, 'Camera station\nPi camera, HSV + shape\ncrack / corner checks\nfirst grade', '#e9d8fd', VIOLET, fs=7.8)
box(ax, .84, .40, .15, .17, 'Mosquitto broker\n(on the Pi)\nMQTT topics', '#edf2f7', GREY, fs=7.8)
box(ax, .84, .12, .15, .19, 'UNO Q gantry\nfinal-grade queue\npick and place\n(optional master PC\nobserves)', '#c6f6d5', GREEN, fs=7.6)
arrow(ax, (.915, .70), (.915, .57), 7, VIOLET, nx=.03)
arrow(ax, (.84, .46), (.78, .30), 8, VIOLET, nx=.02, ny=.02)
arrow(ax, (.78, .25), (.84, .22), 9, GREEN, ny=-.03)
legend(ax, [(1, 'release / lift command: PWM via the MDD10A driver', RED),
            (2, 'tile distance over I2C, 25 ms poll; <= 100 mm = tile', GREEN),
            (3, 'PCM blocks over USB audio, continuous', BLUE),
            (4, 'both ways: TAP/RET/HB up, UP/STRIKE/HOLD down', AMBER),
            (5, 'one 1.5 s clip per strike goes to the feature step', VIOLET),
            (6, 'sound verdict and features go to fusion', VIOLET),
            (7, 'tile/<id>/camera/result (MQTT, QoS 1)', VIOLET),
            (8, 'camera result reaches the fusion ledger', VIOLET),
            (9, 'tile/<id>/final, acknowledged by the UNO Q', GREEN)],
       .088, cols=3, dx=.335, dy=.03)
ax.text(.01, -.02, 'Built and tested on a laptop; the Pi, the microphone with tiles and the UNO Q consumer have not run together.', fontsize=7.6, color=MUTE)
fig.savefig(OUT / 'fig1_architecture.png', dpi=130, bbox_inches='tight'); plt.close(fig)

# ---- Figure 2: striker / capture state diagram
fig, ax = canvas(12.5, 6.2, 'Striker and strike-capture sequence (AUTO mode)')
ax.text(.99, .985, 'Safety: no valid Pi line for 2 s -> disarm and lower; never lowered onto a tile;\nmanual hold longer than 8 s is released as a safety strike',
        ha='right', va='top', fontsize=7.8, color=RED)
st = [('1  RESTING\nDOWN', '#edf2f7', GREY, 'coil off, cool'),
      ('2  RAISED', '#bee3f8', BLUE, 'coil on, 30 % hold,\nwaiting for a tile'),
      ('3  TILE AT\nSENSOR', '#c6f6d5', GREEN, 'ToF <= 100 mm,\n5 samples (~125 ms),\n2 s countdown'),
      ('4  STRIKE', '#fed7d7', RED, 'coil released:\ngravity + spring,\nTAP src=tof'),
      ('5  LIFTED', '#fefcbf', AMBER, 'coil on again,\ntile can leave')]
bw, gap, x0 = .13, .075, .02
xs = [x0 + i * (bw + gap) for i in range(5)]
for (name, fc, ec, note), x in zip(st, xs):
    box(ax, x, .48, bw, .22, name, fc, ec, fs=9.5, bold=True)
    ax.text(x + bw / 2, .43, note, ha='center', va='top', fontsize=7.8, color=INK, linespacing=1.3)
for i in range(4):
    arrow(ax, (xs[i] + bw + .004, .59), (xs[i + 1] - .004, .59), i + 1, MUTE)
ax.add_patch(FancyArrowPatch((xs[4] + bw / 2, .70), (xs[0] + bw / 2, .70), arrowstyle='-|>', mutation_scale=11, lw=1.4,
                             color=MUTE, connectionstyle='arc3,rad=0.22', zorder=3))
cx, cy = (xs[0] + xs[4] + bw) / 2, .70 + .22 * .5 * (xs[4] - xs[0]) * 12.5 / 6.2 / 1.0 * .5
cy = min(cy, .93)
ax.add_patch(plt.Circle((cx, cy), .0135, fc='white', ec=MUTE, lw=1.2, zorder=5))
ax.text(cx, cy, '5', ha='center', va='center', fontsize=7.5, color=MUTE, fontweight='bold', zorder=6)
legend(ax, [(1, 'camera graded a tile: the Pi sends UP and arms (STRIKE 1)', MUTE),
            (2, 'tile reaches the ToF: <= 100 mm for about 125 ms', MUTE),
            (3, '+2.0 s and still armed', MUTE),
            (4, '+1.5 s (0.3 s strike + 1.2 s cooldown)', MUTE),
            (5, 'nothing to do for 3 s: quiet lowering (TAP src=rest, never paired with a tile)', MUTE)],
       .285, cols=2, dx=.5, dy=.042)
ax.add_patch(FancyBboxPatch((.02, .03), .96, .13, boxstyle='round,pad=0.004,rounding_size=0.012', fc='#f1f5f9', ec='#cbd5e0'))
ax.text(.03, .135, 'Capture on every TAP (Pi):', fontsize=8.5, fontweight='bold', color=INK, va='center')
ax.text(.03, .07, 'cut the ring buffer -0.5 s ... +1.0 s around the TAP  ->  onset after a 0.35 s quiet lead-in  ->  analyse 5-250 ms after the onset  ->  features  ->  verdict',
        fontsize=8.2, color=INK, va='center')
fig.savefig(OUT / 'fig2_strike_states.png', dpi=130, bbox_inches='tight'); plt.close(fig)

# ---- Figure 3: implementation workflow
fig, ax = canvas(12.5, 4.8, 'Implementation workflow: from a struck tile to a graded one')
steps = [('1  Record', 'continuous microphone\n(30 s WAV chunks),\nevents, video: one\nsession folder', BLUE),
         ('2  Clip', 'one 1.5 s WAV per\nretract / strike event;\nSHA-256 manifest', BLUE),
         ('3  Label', 'a person looks at the\ntile: good, cracked,\ncorner broken, other;\nplus a grade tier', AMBER),
         ('4  Features', 'strike_features():\ncentroid, band shares,\nfade slope, t20, SNR', VIOLET),
         ('5  Reference', 'median and 1.4826 x MAD\nof at least 8 good\ntiles; leave-one-out\ncheck', VIOLET),
         ('6  Grade', 'worst robust z:\n<= 3 GOOD,\n<= 6 BORDERLINE,\nelse DEFECTIVE', GREEN)]
bw, gap = .125, .04
for i, (t, d, c) in enumerate(steps):
    x = .02 + i * (bw + gap)
    box(ax, x, .56, bw, .22, t, '#fff', c, fs=10.5, bold=True)
    ax.text(x + bw / 2, .50, d, ha='center', va='top', fontsize=7.8, color=INK, linespacing=1.35)
    if i < len(steps) - 1:
        arrow(ax, (x + bw + .004, .67), (x + bw + gap - .004, .67), None, MUTE)
ax.add_patch(FancyBboxPatch((.02, .03), .96, .20, boxstyle='round,pad=0.004,rounding_size=0.012', fc='#f1f5f9', ec='#cbd5e0'))
ax.text(.03, .195, 'Commands used', fontsize=8.5, fontweight='bold', color=INK, va='center')
ax.text(.03, .135, 'python -m fusion.session clips <session> --pre 0.5 --post 1.0     python main.py label     "Build sound reference" (labelling tool)',
        fontsize=7.8, color=INK, family='monospace', va='center')
ax.text(.03, .075, 'python main.py   (Test Tile: strike, record, analyse, verdict)     python tools/make_final_report_figures.py   (plots and numbers)',
        fontsize=7.8, color=INK, family='monospace', va='center')
fig.savefig(OUT / 'fig3_workflow.png', dpi=130, bbox_inches='tight'); plt.close(fig)
print('wrote', *(p.name for p in sorted(OUT.glob('fig[123]_*.png'))))
