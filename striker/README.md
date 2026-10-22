# striker/ - the Arduino Nano that strikes the tile

The Nano drives the striker (one sprung solenoid above the tile, behind a Cytron MDD10A) and
reads the ToF distance sensor. This app talks to it over **USB serial from the laptop** - the
same USB hub as the microphone. `python main.py flash` compiles and uploads the firmware;
the **Test Tile** screen then drives it.

| File | What |
|---|---|
| `nano_firmware/nano_firmware.ino` | Board glue: pins, ToF sensor, serial, PWM. |
| `nano_firmware/nano_core.h` | All the logic (portable C++): serial protocol, watchdog, strike sequence. |
| `PROTOCOL.md` | The serial protocol this app speaks (`acoustic_analysis/io/nano_protocol.py`). |

**Provenance.** Copied by hand (this repo never imports from the tile-line project) from
`Tile_Sorting/acoustic_node/nano_firmware/` at commit `00204ce` (2026-10-19 prototype build).
That repo stays the source of truth for the firmware; if it changes, copy the two files again.

## Flash it

```powershell
python main.py flash                 # finds the Nano, installs what is missing, compiles, uploads
python main.py flash --port COM5     # if there is more than one candidate port
python main.py flash --compile-only  # no board needed: just check the sketch builds
```

First run only: it installs the `arduino:avr` core and the **Pololu VL53L0X** library through
`arduino-cli` (needs internet once). `arduino-cli` is installed separately
(`winget install ArduinoSA.CLI`) and must be on `PATH`; open a **new** terminal after installing.

- **Board:** Arduino Nano, ATmega328P. **Bootloader:** the CH340 clone tested here took the *new*
  bootloader at **115200 baud**; the "old bootloader" setting (57600) answered `not in sync`.
  `flash` tries one and, on `not in sync`, the other (`striker.fqbn` in `config.yaml`).
- **Keep clear of the striker while flashing.** The Nano resets when the port opens, so the
  driver's inputs float for a moment.
- Close anything else holding the port (the Arduino IDE's serial monitor, another copy of this app).

## What the prototype firmware does (from the original build notes)

- **Striker:** ONE solenoid. Energised = retracted (noisy), released = gravity + spring strike.
  `RET` is sent when it is energised, `TAP` when it is released.
- **Modes:** `MODE 1` manual (the `TAP` command retracts, holds, releases once); `MODE 0` auto
  (the ToF starts cycles; an `UP` command says "a tile is coming").
- **ToF:** one VL53L0X. Measured on the rig: a tile reads about 91 mm, the empty surface 112-142 mm;
  **<= 100 mm counts as a tile**, debounced over ~125 ms. Only ~20 mm separates them.
- **Watchdog:** no valid line from the laptop for 2 s -> striker inhibited and belt 0. This app
  pings every 0.5 s while connected.
- **Safety:** the coil is never left energised: held longer than the limit, `STRIKE 0`, a watchdog
  trip or the e-stop all let it down (a strike, reported with a reason).
- **Hold power** (`HOLD n`, default 30 %) trades holding force against coil heat; the coil
  overheated at 60 % parked up. Too low drops the striker by itself.

## Not verified

- The ToF module and the solenoid have never been exercised together on the rig with *this* app.
- The sketch compiled for AVR and flashed to a real Nano on 2026-10-19 (it booted and answered the
  protocol). The Pololu VL53L0X calls, the coil's duty rating and the strike timings are unmeasured.
- Pins `D9` (belt PWM) and `D12` (ToF 3 reset) are unconfirmed; the prototype uses neither.
