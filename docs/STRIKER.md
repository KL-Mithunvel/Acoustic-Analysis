# Striker, Test Tile and the sound grade

How to strike a tile with the Arduino Nano from this app, see how it rang, and have the app grade it by sound.
Everything runs on **one laptop**: the Nano and the microphone both plug into its USB ports.

```
Nano (striker + distance sensor) --USB serial--> laptop <--USB-- microphone
                                                   |
                          Test Tile screen: strike -> record -> analyse -> verdict
                                                   |
                       every test saved -> labelling tool -> reference -> grades
```

## What you need

| Part | Notes |
|---|---|
| Arduino Nano (ATmega328P) | a CH340 clone worked; flashed over USB from this app |
| Striker | one sprung solenoid above the tile, driven by a Cytron MDD10A (PWM = D10, DIR = D8). Energised = lifted, released = gravity + spring strike |
| Distance sensor | VL53L0X on I2C (A4 = SDA, A5 = SCL). A tile reads about 91 mm, the empty surface 112-142 mm; **<= 100 mm counts as a tile** |
| Microphone | USB. Windows *Enhancements* (AGC, noise suppression) must be off |
| `arduino-cli` | `winget install ArduinoSA.CLI`, then open a **new** terminal |

The pins, the 100 mm limit and the strike timings come from the original build notes (`striker/README.md`);
none of them has been re-measured with this app.

## 1. Flash the Nano (once)

```powershell
python main.py flash --compile-only   # no board needed: checks the firmware builds
python main.py flash                  # finds the Nano, uploads
python main.py flash --port COM5      # if it cannot tell which port
python main.py flash --list-ports
```

The first run installs the AVR board support and the Pololu VL53L0X library (internet needed once). The upload tries
the new bootloader (115200 baud) and, if it answers "not in sync", the old one (57600). **Keep clear of the striker
while it uploads** - the Nano resets and the driver's inputs float for a moment. The same thing is behind the
**Flash firmware...** button on the Test Tile screen.

## 2. Test a tile

Open the app (`python main.py`): it starts on **Test Tile**.

1. Choose the Nano's port and the microphone, press **Connect**. The striker line turns green when the Nano answers
   and the tile sensor shows its distance live. Wave a hand under it to see it change.
2. Put a tile under the striker. Press **Strike now** (one manual strike), or **A tile is coming (auto)**: the striker
   rises, and when the sensor sees a tile it strikes about 2 s later.
3. The big word is the verdict. The three plots show *what it sounds like*, *which pitches ring* and *how fast it fades*.

**Hold power** sets how hard the coil holds the striker up (default 30 %). Too high and the coil overheats (it did at 60 %
parked up); too low and the striker drops by itself. **Stop striker** inhibits it. Closing the app inhibits it too, and
the Nano stops the striker by itself if the laptop goes silent for 2 s.

Without hardware, **Analyse a recording (WAV)...** runs the same analysis on any clip with a strike about 0.5 s in.

### How a strike becomes a verdict

1. The Nano sends `TAP` the instant the coil is released.
2. The microphone has been recording continuously into a ring buffer, so the app cuts a 1.5 s clip from 0.5 s before
   the `TAP` to 1.0 s after - the same layout as the tile-line station's clips (`io/audio_ring.py`).
3. `strike_features` finds the onset after a quiet lead-in, takes the ring (5-250 ms after it) and measures the
   spectrum's centroid and energy shares, and how fast the envelope fades.
4. The grade compares those with tiles **you** labelled good.

| Verdict | Meaning |
|---|---|
| GOOD | every measurement is within `z_ok` (3) typical spreads of your good tiles |
| BORDERLINE | the worst one is between 3 and 6 spreads away |
| DEFECTIVE | more than 6 spreads away: it sounds clearly different |
| RETEST | no strike heard, or it is under 20 dB over the background - strike again |
| UNGRADED | there is no reference yet |
| NO TILE | the distance sensor saw no tile at the moment of the strike |

The reasons under the verdict name the measurements that are off, e.g. *"spectral centroid is higher than the good tiles'
(4.2 spreads away)"*. It can only say a tile sounds **different** from the good ones - it cannot tell a crack from a chip.

## 3. Label, build the reference, grade

Every test is saved in the tile-line station's session layout under `data/sessions/<date_time>/` (untick *Save every test*
to stop). Then:

1. **Label tiles** screen -> **Open the labelling tool** (or `python main.py label`). It shows the station's sessions and
   your own tests: the tile picture (station only), camera and vision-model verdicts, the sound analysis and plots.
   Look at the tile, listen, and press **G** (good), **C** (cracked), **B** (broken corner), **O** (other defect).
2. When about 8 tiles are labelled good, press **Build sound reference**. It saves `data/strike_reference.json` and shows
   how it does on *your own labels* (good tiles are checked leave-one-out, so none is graded against itself).
3. Back on Test Tile the verdicts now say GOOD / BORDERLINE / DEFECTIVE.

Re-build whenever you label more. The settings are `strike.reference` in `config.yaml` (all provisional).

## Files

| Path | What |
|---|---|
| `data/sessions/<date_time>/` | your tests: `strikes.json`, `clips/S0001_strike.wav`, `manifest.json` (git-ignored) |
| `data/labels.json` | your labels, one entry per strike (never written into a session folder) |
| `data/strike_reference.json` | the good-tile reference the grade uses |
| `data/build/nano/` | the compiled firmware |

## Troubleshooting

| Symptom | Try |
|---|---|
| "arduino-cli was not found" | install it, then open a **new** terminal; or set `striker.arduino_cli` in `config.yaml` |
| "No Nano found" | plug it in and press the refresh button; Bluetooth ports are not Nanos. Or pass `--port COMx` |
| Upload says "not in sync" for both bootloaders | another program has the port, or the board is not a Nano; unplug and re-plug |
| "Access is denied" on connect or upload | something else holds the port (Arduino IDE serial monitor, another copy of this app) |
| Striker line stays "waiting for the Nano to answer" | wrong port, or the firmware is not flashed - press **Flash firmware...** |
| Tile sensor "not answering" | the VL53L0X is not wired or not powered; the striker will not auto-strike without it |
| It struck but "nothing was recorded" | the microphone did not start - pick it in the list and reconnect |
| RETEST every time | the strike is too quiet: raise the microphone's gain in Windows, or move it closer |
| UNGRADED | no reference yet: label tiles good and build it |

## Not verified

- **None of this has run on the real rig with this app.** It is tested against a scripted fake serial port, a fake
  microphone ring and real clips from the 2026-10-19 station sessions. The firmware compiled for AVR (17,308 bytes of
  flash, 1,397 of RAM) but was not uploaded from this app.
- The VL53L0X and the solenoid have not been exercised together with this app; the strike timing and the 0.5 s
  alignment of the clip are assumed from the station's clips (onsets in those clips ran from 0.47 to 0.57 s).
- The grade has never been checked on labelled real tiles. Until it is, treat it as a tool for *looking*, not for sorting.
