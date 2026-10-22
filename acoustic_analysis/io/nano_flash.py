"""Compile and upload the striker firmware to the Arduino Nano with ``arduino-cli``.

Everything that touches the outside world goes through one injectable ``runner`` (default:
``subprocess.run``), so the command sequences are tested without a board, a network or the CLI.

    python main.py flash                  find the Nano, install what is missing, compile, upload
    python main.py flash --compile-only   no board needed
    python main.py flash --list-ports

Settings are ``config.yaml`` ``striker:``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import load_config, repo_root

Runner = Callable[[list[str], float], "tuple[int, str, str]"]
Log = Callable[[str], None]

_DEFAULT_WIN_CLI = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Arduino CLI" / "arduino-cli.exe"


class FlashError(RuntimeError):
    """A step failed; the message says what to do about it."""


@dataclass
class PortInfo:
    address: str                 # COM5
    label: str                   # what to show a person
    board: str | None            # arduino-cli's guess, if any
    vid: str | None
    candidate: bool              # looks like a Nano (known USB chip, or arduino-cli matched a board)


def subprocess_runner(args: list[str], timeout: float) -> tuple[int, str, str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"timed out after {timeout:.0f} s: {' '.join(args[:3])} ..."
    except OSError as exc:
        return 127, "", str(exc)
    return r.returncode, r.stdout, r.stderr


def find_cli(cfg: dict | None = None) -> Path | None:
    """The configured path, ``$ARDUINO_CLI``, ``arduino-cli`` on PATH, then the winget install folder."""
    for cand in ((cfg or {}).get("striker", {}).get("arduino_cli"), os.environ.get("ARDUINO_CLI")):
        if cand and Path(cand).is_file():
            return Path(cand)
    found = shutil.which("arduino-cli")
    if found:
        return Path(found)
    return _DEFAULT_WIN_CLI if _DEFAULT_WIN_CLI.is_file() else None


class Flasher:
    def __init__(self, cfg: dict | None = None, runner: Runner = subprocess_runner,
                 cli: str | Path | None = None, log: Log = print):
        self.cfg = cfg or load_config()
        self.s = self.cfg["striker"]
        self.runner = runner
        self.log = log
        cli = cli or find_cli(self.cfg)
        if cli is None:
            raise FlashError("arduino-cli was not found. Install it (winget install ArduinoSA.CLI), then open a "
                             "NEW terminal - or set striker.arduino_cli in config.yaml.")
        self.cli = str(cli)

    # -- plumbing -----------------------------------------------------------------
    def _run(self, args: list[str], timeout: float | None = None) -> tuple[int, str, str]:
        return self.runner([self.cli, *args], float(timeout or self.s["compile_timeout_s"]))

    def _json(self, args: list[str], timeout: float | None = None):
        code, out, err = self._run([*args, "--format", "json"], timeout)
        if code != 0:
            raise FlashError(f"arduino-cli {' '.join(args)} failed: {(err or out).strip()[:300]}")
        try:
            return json.loads(out or "null")
        except ValueError as exc:
            raise FlashError(f"could not read arduino-cli's answer to {' '.join(args)}: {exc}") from exc

    def sketch_dir(self) -> Path:
        p = Path(self.s["sketch_dir"])
        return p if p.is_absolute() else repo_root() / p

    def build_dir(self) -> Path:
        p = Path(self.s["build_dir"])
        return p if p.is_absolute() else repo_root() / p

    # -- ports -----------------------------------------------------------------------
    def list_ports(self) -> list[PortInfo]:
        data = self._json(["board", "list"], 60)
        entries = data.get("detected_ports", []) if isinstance(data, dict) else (data or [])
        vids = {v.upper() for v in self.s["usb_vids"]}
        out: list[PortInfo] = []
        for e in entries:
            port = e.get("port") or {}
            if port.get("protocol") != "serial":
                continue
            props = port.get("properties") or {}
            vid = (props.get("vid") or "").upper().replace("0X", "") or None
            boards = e.get("matching_boards") or []
            board = boards[0].get("name") if boards else None
            out.append(PortInfo(address=port.get("address", ""), label=port.get("label") or port.get("address", ""),
                                board=board, vid=vid, candidate=bool(board) or (vid in vids if vid else False)))
        return out

    def choose_port(self, wanted: str | None = None) -> PortInfo:
        ports = self.list_ports()
        if wanted:
            hit = next((p for p in ports if p.address.lower() == wanted.lower()), None)
            return hit or PortInfo(wanted, wanted, None, None, True)       # trust the user's COM port
        cands = [p for p in ports if p.candidate]
        if len(cands) == 1:
            return cands[0]
        if not cands:
            seen = ", ".join(p.address for p in ports) or "none"
            raise FlashError(f"No Nano found (serial ports seen: {seen}). Plug it in, or pass --port COMx.")
        raise FlashError("More than one possible board: " + ", ".join(f"{p.address} ({p.board or p.vid})" for p in cands)
                         + ". Pass --port COMx.")

    # -- toolchain ---------------------------------------------------------------------
    def ensure_core(self) -> bool:
        """Install the board core if missing. Returns True if it had to install."""
        core = self.s["core"]
        data = self._json(["core", "list"], 60)
        rows = data.get("platforms", []) if isinstance(data, dict) else (data or [])
        if any(r.get("id") == core for r in rows):
            return False
        self.log(f"Installing board support {core} (one time, needs internet)...")
        self._run(["core", "update-index"], self.s["install_timeout_s"])
        code, out, err = self._run(["core", "install", core], self.s["install_timeout_s"])
        if code != 0:
            raise FlashError(f"Could not install {core}: {(err or out).strip()[:300]}")
        return True

    def ensure_libraries(self) -> list[str]:
        """Install any missing library the sketch #includes. Returns the names installed."""
        data = self._json(["lib", "list"], 60)
        rows = data.get("installed_libraries", []) if isinstance(data, dict) else (data or [])
        have = {(r.get("library") or r).get("name") for r in rows if isinstance(r, dict)}
        added = []
        for lib in self.s["libraries"]:
            if lib in have:
                continue
            self.log(f"Installing library {lib}...")
            code, out, err = self._run(["lib", "install", lib], self.s["install_timeout_s"])
            if code != 0:
                raise FlashError(f"Could not install library {lib}: {(err or out).strip()[:300]}")
            added.append(lib)
        return added

    # -- build and upload ----------------------------------------------------------------
    def compile(self) -> Path:
        sketch = self.sketch_dir()
        if not (sketch / f"{sketch.name}.ino").is_file():
            raise FlashError(f"Sketch not found: {sketch / (sketch.name + '.ino')}")
        build = self.build_dir()
        build.mkdir(parents=True, exist_ok=True)
        self.log("Compiling the firmware...")
        code, out, err = self._run(["compile", "--fqbn", self.s["fqbn"], "--build-path", str(build), str(sketch)],
                                   self.s["compile_timeout_s"])
        if code != 0:
            raise FlashError("Compile failed:\n" + (err or out).strip()[-800:])
        hexes = sorted(build.glob("*.hex"))
        if not hexes:
            raise FlashError(f"Compile reported success but no .hex file is in {build}.")
        return hexes[0]

    def upload(self, port: str) -> str:
        """Upload the compiled build. Tries the configured bootloader, then the other if it is not in sync."""
        last = ""
        for fqbn in (self.s["fqbn"], self.s["fqbn_alt"]):
            self.log(f"Uploading to {port} ({fqbn.rsplit('=', 1)[-1]})...")
            code, out, err = self._run(["upload", "-p", port, "--fqbn", fqbn, "--input-dir", str(self.build_dir()),
                                        str(self.sketch_dir())], self.s["upload_timeout_s"])
            if code == 0:
                return fqbn
            last = (err or out).strip()
            if "not in sync" not in last and "stk500" not in last.lower():
                break                       # a different problem (port busy, no permission): the other bootloader won't help
        raise FlashError("Upload failed: " + last[-600:]
                         + "\nClose anything else using the port (serial monitor, another copy of this app).")

    def flash(self, port: str | None = None, compile_only: bool = False) -> dict:
        report: dict = {"cli": self.cli}
        report["core_installed"] = self.ensure_core()
        report["libraries_installed"] = self.ensure_libraries()
        report["hex"] = str(self.compile())
        if compile_only:
            return report
        chosen = self.choose_port(port)
        self.log("Keep clear of the striker: the Nano resets when the port opens, so the driver inputs float briefly.")
        report["port"] = chosen.address
        report["fqbn"] = self.upload(chosen.address)
        return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="flash", description="Compile and upload the striker firmware to the Nano.")
    ap.add_argument("--port", help="serial port, e.g. COM5 (default: find the Nano)")
    ap.add_argument("--compile-only", action="store_true", help="build only; no board needed")
    ap.add_argument("--list-ports", action="store_true", help="show serial ports and exit")
    args = ap.parse_args(argv)
    try:
        fl = Flasher()
        if args.list_ports:
            for p in fl.list_ports():
                print(f"{p.address:8s} {'<- looks like a Nano  ' if p.candidate else '                      '}{p.label}"
                      f"  {p.board or ''} {p.vid or ''}")
            return 0
        rep = fl.flash(args.port, args.compile_only)
    except FlashError as exc:
        print(f"flash: {exc}", file=sys.stderr)
        return 1
    print("Done.", json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
