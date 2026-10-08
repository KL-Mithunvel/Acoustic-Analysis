"""SessionStore: cleaning + auto-filing of captured clips."""

from datetime import datetime

import numpy as np

from acoustic_analysis.dsp.machine_noise import build_striker_template
from acoustic_analysis.io.library import Library
from acoustic_analysis.io.machine_profile import MachineProfile
from acoustic_analysis.io.session import SessionStore, new_session_folder
from acoustic_analysis.io.wavstore import load_clip
from tests.test_machine_noise import FS, _cfg, _clip


def _profile(cfg):
    tpl = build_striker_template([_clip(cfg, seed=i)[0] for i in range(10)], FS, cfg)
    return MachineProfile(FS, np.random.default_rng(3).normal(0, 0.003, 3 * FS), tpl)


def test_session_folder_numbering(tmp_path):
    lib = Library(tmp_path)
    d = datetime(2026, 10, 8)
    assert new_session_folder(lib, now=d).name == "2026-10-08_01"
    assert new_session_folder(lib, now=d).name == "2026-10-08_02"


def test_tile_and_dry_strikes_are_filed_apart(tmp_path):
    cfg = _cfg()
    lib = Library(tmp_path)
    folder = new_session_folder(lib)
    store = SessionStore(lib, folder, cfg, _profile(cfg))

    hit = store.handle(_clip(cfg, tile=0.3, seed=11)[0], FS)
    dry = store.handle(_clip(cfg, seed=12)[0], FS)

    assert hit.accepted and hit.path.parent == folder
    assert not dry.accepted and dry.path.parent == folder / "rejected"
    assert hit.raw_path.is_file() and dry.raw_path.is_file()      # raw always kept
    assert store.counts() == {"total": 2, "tile": 1, "no_tile": 1, "no_strike": 0}
    _, _, meta = load_clip(hit.path)
    assert meta["verdict"] == "tile" and meta["machine_cleaned"] is True


def test_raw_folder_hidden_in_listing(tmp_path):
    cfg = _cfg()
    lib = Library(tmp_path)
    folder = new_session_folder(lib)
    store = SessionStore(lib, folder, cfg, _profile(cfg))
    store.handle(_clip(cfg, tile=0.3, seed=11)[0], FS)
    store.handle(_clip(cfg, seed=12)[0], FS)
    assert [e.name for e in lib.list(folder)] == ["rejected", "tap-001.wav"]


def test_sequence_continues_in_an_existing_folder(tmp_path):
    cfg = _cfg()
    lib = Library(tmp_path)
    folder = new_session_folder(lib)
    SessionStore(lib, folder, cfg).handle(_clip(cfg, tile=0.3, seed=1)[0], FS)
    again = SessionStore(lib, folder, cfg).handle(_clip(cfg, tile=0.3, seed=2)[0], FS)
    assert again.name == "tap-002"


def test_works_without_any_machine_profile(tmp_path):
    cfg = _cfg()
    lib = Library(tmp_path)
    store = SessionStore(lib, new_session_folder(lib), cfg)
    saved = store.handle(_clip(cfg, tile=0.3, seed=5)[0], FS)
    assert saved.scale == 0.0 and saved.path.is_file()
