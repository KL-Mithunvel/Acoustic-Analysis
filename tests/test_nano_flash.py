"""nano_flash: the arduino-cli command sequences, with a scripted fake runner (no CLI, board or network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acoustic_analysis.config import load_config
from acoustic_analysis.io.nano_flash import FlashError, Flasher, find_cli

CORE_ROWS = {"platforms": [{"id": "arduino:avr"}]}
LIB_ROWS = {"installed_libraries": [{"library": {"name": "VL53L0X"}}]}
CH340 = {"detected_ports": [{"port": {"address": "COM5", "label": "COM5", "protocol": "serial",
                                      "properties": {"vid": "0x1A86", "pid": "0x7523"}}}]}


class FakeCli:
    """Answers arduino-cli calls from a script and records every command."""

    def __init__(self, tmp_path, core=CORE_ROWS, libs=LIB_ROWS, ports=CH340, upload_codes=(0,), upload_err="not in sync"):
        self.calls: list[list[str]] = []
        self.core, self.libs, self.ports = core, libs, ports
        self.upload_codes = list(upload_codes)
        self.upload_err = upload_err
        self.tmp = tmp_path

    def __call__(self, args, timeout):
        self.calls.append(args[1:])
        a = args[1:]
        if a[:2] == ["core", "list"]:
            return 0, json.dumps(self.core), ""
        if a[:2] == ["lib", "list"]:
            return 0, json.dumps(self.libs), ""
        if a[:2] == ["board", "list"]:
            return 0, json.dumps(self.ports), ""
        if a[0] == "compile":
            build = Path(a[a.index("--build-path") + 1])
            (build / "nano_firmware.ino.hex").write_text(":00000001FF")
            return 0, "", ""
        if a[0] == "upload":
            code = self.upload_codes.pop(0) if self.upload_codes else 0
            return code, "", (self.upload_err if code else "")
        return 0, "", ""

    def cmds(self, first):
        return [c for c in self.calls if c[0] == first]


@pytest.fixture()
def cfg(tmp_path):
    c = load_config()
    c["striker"] = {**c["striker"], "build_dir": str(tmp_path / "build")}
    return c


def _flasher(cfg, fake):
    return Flasher(cfg, runner=fake, cli="arduino-cli", log=lambda _m: None)


def test_flash_sequence_when_everything_is_installed(cfg, tmp_path):
    fake = FakeCli(tmp_path)
    rep = _flasher(cfg, fake).flash()
    assert rep["port"] == "COM5" and rep["fqbn"].endswith("atmega328") and rep["hex"].endswith(".hex")
    assert rep["core_installed"] is False and rep["libraries_installed"] == []
    assert fake.cmds("core") == [["core", "list", "--format", "json"]]          # nothing installed, nothing updated
    assert not fake.cmds("lib")[1:]                                              # only the list call
    comp = fake.cmds("compile")[0]
    assert comp[comp.index("--fqbn") + 1] == cfg["striker"]["fqbn"]
    assert comp[-1].endswith("nano_firmware")
    up = fake.cmds("upload")[0]
    assert up[up.index("-p") + 1] == "COM5"


def test_missing_core_and_library_are_installed_first(cfg, tmp_path):
    fake = FakeCli(tmp_path, core={"platforms": []}, libs={"installed_libraries": []})
    rep = _flasher(cfg, fake).flash(compile_only=True)
    assert rep["core_installed"] is True and rep["libraries_installed"] == ["VL53L0X"]
    names = [c[:2] for c in fake.calls]
    assert ["core", "install"] in names and ["lib", "install"] in names
    assert names.index(["core", "install"]) < names.index(["lib", "install"]) < names.index(["compile", "--fqbn"])
    assert not fake.cmds("upload") and not fake.cmds("board")                  # compile-only never touches a port


def test_not_in_sync_retries_with_the_other_bootloader(cfg, tmp_path):
    fake = FakeCli(tmp_path, upload_codes=(1, 0))
    rep = _flasher(cfg, fake).flash()
    ups = fake.cmds("upload")
    assert len(ups) == 2
    assert ups[0][ups[0].index("--fqbn") + 1] == cfg["striker"]["fqbn"]
    assert ups[1][ups[1].index("--fqbn") + 1] == cfg["striker"]["fqbn_alt"]
    assert rep["fqbn"] == cfg["striker"]["fqbn_alt"]


def test_other_upload_errors_do_not_retry(cfg, tmp_path):
    fake = FakeCli(tmp_path, upload_codes=(1,), upload_err="can't open device COM5: Access is denied")
    with pytest.raises(FlashError, match="Access is denied"):
        _flasher(cfg, fake).flash()
    assert len(fake.cmds("upload")) == 1


def test_both_bootloaders_failing_says_what_to_do(cfg, tmp_path):
    fake = FakeCli(tmp_path, upload_codes=(1, 1))
    with pytest.raises(FlashError, match="Close anything else"):
        _flasher(cfg, fake).flash()


def test_port_choice(cfg, tmp_path):
    none = FakeCli(tmp_path, ports={"detected_ports": [{"port": {"address": "COM1", "protocol": "serial", "properties": {}}}]})
    with pytest.raises(FlashError, match="No Nano found .*COM1"):
        _flasher(cfg, none).choose_port()
    two = FakeCli(tmp_path, ports={"detected_ports": [
        {"port": {"address": "COM5", "protocol": "serial", "properties": {"vid": "0x1A86"}}},
        {"port": {"address": "COM7", "protocol": "serial", "properties": {"vid": "0x2341"}}}]})
    with pytest.raises(FlashError, match="More than one"):
        _flasher(cfg, two).choose_port()
    assert _flasher(cfg, two).choose_port("com7").address == "COM7"
    assert _flasher(cfg, FakeCli(tmp_path)).choose_port("COM9").address == "COM9"      # an unlisted port is trusted when named
    bt = FakeCli(tmp_path, ports={"detected_ports": [{"port": {"address": "COM3", "protocol": "serial"}},
                                                    {"port": {"address": "x", "protocol": "network"}}]})
    assert [p.address for p in _flasher(cfg, bt).list_ports()] == ["COM3"]              # network ports are ignored


def test_arduino_board_match_makes_a_candidate_without_a_known_vid(cfg, tmp_path):
    f = FakeCli(tmp_path, ports={"detected_ports": [{"matching_boards": [{"name": "Arduino Nano"}],
                                                    "port": {"address": "COM4", "protocol": "serial", "properties": {"vid": "0x9999"}}}]})
    p = _flasher(cfg, f).choose_port()
    assert p.address == "COM4" and p.board == "Arduino Nano"


def test_failed_compile_reports_the_compiler_output(cfg, tmp_path):
    def runner(args, timeout):
        if args[1] == "compile":
            return 1, "", "nano_firmware.ino:12: fatal error: VL53L0X.h: No such file"
        return FakeCli(tmp_path)(args, timeout)
    with pytest.raises(FlashError, match="VL53L0X.h"):
        Flasher(cfg, runner=runner, cli="arduino-cli", log=lambda _m: None).compile()


def test_missing_sketch_and_missing_cli(cfg, tmp_path, monkeypatch):
    bad = {**cfg, "striker": {**cfg["striker"], "sketch_dir": str(tmp_path / "nope")}}
    with pytest.raises(FlashError, match="Sketch not found"):
        Flasher(bad, runner=FakeCli(tmp_path), cli="x", log=lambda _m: None).compile()
    import acoustic_analysis.io.nano_flash as mod
    monkeypatch.setattr(mod, "find_cli", lambda cfg=None: None)
    with pytest.raises(FlashError, match="arduino-cli was not found"):
        Flasher(cfg, runner=FakeCli(tmp_path))


def test_find_cli_prefers_the_configured_path(tmp_path, monkeypatch):
    exe = tmp_path / "arduino-cli.exe"
    exe.write_text("")
    assert find_cli({"striker": {"arduino_cli": str(exe)}}) == exe
    monkeypatch.setenv("ARDUINO_CLI", str(exe))
    assert find_cli({"striker": {"arduino_cli": None}}) == exe


def test_the_real_sketch_is_where_the_config_says():
    cfg = load_config()
    f = Flasher(cfg, runner=lambda a, t: (0, "{}", ""), cli="x", log=lambda _m: None)
    assert (f.sketch_dir() / "nano_firmware.ino").is_file() and (f.sketch_dir() / "nano_core.h").is_file()
