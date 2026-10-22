# Plan: labelling GUI, Nano striker and a single Test Tile GUI

Branch `feature/striker-and-labelling`. One commit per step, each after the full test
suite passes. Session folders written by the Tile_Sorting station are **never modified**
(they carry SHA-256 manifests); labels live in this repo's `data/`.

## Why

- 55 real strike clips exist (2026-10-19 sessions, 48 kHz): 26 striker alone, 22 ToF tile
  strikes, 7 rest strikes. Tile vs no tile separates cleanly (energy at 1-3 kHz, AUC 1.00).
- Good vs defective cannot be told yet: no human labels, and the camera's verdict (13 of 22
  "Reject" with corner fill 0.89-0.97) looks like false rejects, so it is not ground truth.
- The first six tile strikes (S0001-S0009) differ from the rest; cause unknown.
- `detect_impact` locked onto something 0.3 s before the real strike on a tile clip, so
  strike features anchor on the known strike time instead.

## Part A - labelling GUI

| # | Step |
|---|---|
| A0 | This plan |
| A1 | `strike_features.py` - pure strike metrics anchored on the strike time |
| A2 | `io/session_reader.py` - read-only loader for a station session folder |
| A3 | `io/label_store.py` - labels in `data/labels.json`, atomic writes, CSV export |
| A4 | Labelling window part 1 - list, filters, tile picture, camera and ToF panel |
| A5 | Labelling window part 2 - plots, metrics vs group, flags, play, label buttons |
| A6 | `python main.py label`, README |

## Part B - striker and single GUI

| # | Step |
|---|---|
| B1 | Nano firmware copied into `striker/nano_firmware/` |
| B2 | `io/nano_protocol.py` - checksummed line protocol |
| B3 | `io/nano_flash.py` + `python main.py flash` - arduino-cli wrapper |
| B4 | `io/nano_link.py` - USB-serial link (adds pyserial) |
| B5 | Test Tile screen - strike, record, clean, analyse, verdict |
| B6 | Simplify the GUI around the workflow |
| B7 | `docs/STRIKER.md`, README, TODO |

## Not verified by this plan

Anything needing the real Nano, ToF sensor, solenoid or microphone is tested against a fake
serial port, a mocked `arduino-cli` and synthetic audio. The grader stays UNGRADED until
labelled tiles exist.
