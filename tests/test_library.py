"""Library file operations: rename / move / delete keep wav + sidecar + db together."""

import pytest

from acoustic_analysis.io.dataset import Dataset
from acoustic_analysis.io.library import Library, LibraryError, clean_name
from acoustic_analysis.io.wavstore import save_clip

import numpy as np


def _clip(lib, rel):
    return save_clip(np.zeros(100), 48000, lib.root / rel)


def test_list_orders_folders_then_wavs(tmp_path):
    lib = Library(tmp_path)
    lib.make_folder("", "b_dir")
    lib.make_folder("", "a_dir")
    _clip(lib, "z.wav")
    _clip(lib, "c.wav")
    assert [e.name for e in lib.list()] == ["a_dir", "b_dir", "c.wav", "z.wav"]


def test_sidecar_json_is_not_listed(tmp_path):
    lib = Library(tmp_path)
    _clip(lib, "a.wav")
    assert [e.name for e in lib.list()] == ["a.wav"]


def test_rename_moves_sidecar_and_keeps_extension(tmp_path):
    lib = Library(tmp_path)
    _clip(lib, "a.wav")
    new = lib.rename("a.wav", "tile7")
    assert new.name == "tile7.wav"
    assert new.is_file() and (tmp_path / "tile7.wav.json").is_file()
    assert not (tmp_path / "a.wav").exists() and not (tmp_path / "a.wav.json").exists()


def test_rename_refuses_clash_and_bad_names(tmp_path):
    lib = Library(tmp_path)
    _clip(lib, "a.wav")
    _clip(lib, "b.wav")
    with pytest.raises(LibraryError):
        lib.rename("a.wav", "b.wav")
    for bad in ["", "  ", "x/y", "a:b", "..", ".trash"]:
        with pytest.raises(LibraryError):
            clean_name(bad)
    assert (tmp_path / "a.wav").is_file()      # untouched after the refusal


def test_move_into_folder_and_undo(tmp_path):
    lib = Library(tmp_path)
    _clip(lib, "a.wav")
    dest = lib.make_folder("", "good")
    moved = lib.move("a.wav", "good")
    assert moved == dest / "a.wav" and (dest / "a.wav.json").is_file()
    lib.undo()
    assert (tmp_path / "a.wav").is_file() and (tmp_path / "a.wav.json").is_file()


def test_move_folder_into_itself_refused(tmp_path):
    lib = Library(tmp_path)
    lib.make_folder("", "a")
    lib.make_folder("a", "b")
    with pytest.raises(LibraryError):
        lib.move("a", "a/b")


def test_paths_cannot_escape_root(tmp_path):
    lib = Library(tmp_path / "lib")
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"x")
    with pytest.raises(LibraryError):
        lib.rename(outside, "x")
    with pytest.raises(LibraryError):
        lib.delete("../outside.wav")
    with pytest.raises(LibraryError):
        lib.make_folder("..", "evil")


def test_delete_goes_to_trash_and_undo_restores(tmp_path):
    lib = Library(tmp_path)
    _clip(lib, "a.wav")
    lib.delete("a.wav")
    assert not (tmp_path / "a.wav").exists()
    assert (tmp_path / ".trash" / "a.wav").is_file()
    assert (tmp_path / ".trash" / "a.wav.json").is_file()
    assert [e.name for e in lib.list()] == []          # trash is hidden
    lib.undo()
    assert (tmp_path / "a.wav").is_file() and (tmp_path / "a.wav.json").is_file()


def test_delete_same_name_twice_does_not_overwrite_trash(tmp_path):
    lib = Library(tmp_path)
    _clip(lib, "a.wav")
    lib.delete("a.wav")
    _clip(lib, "a.wav")
    lib.delete("a.wav")
    assert len(list((tmp_path / ".trash").glob("*.wav"))) == 2


def test_undo_refuses_to_overwrite(tmp_path):
    lib = Library(tmp_path)
    _clip(lib, "a.wav")
    lib.delete("a.wav")
    _clip(lib, "a.wav")                                # something new took the name
    with pytest.raises(LibraryError):
        lib.undo()
    assert lib.can_undo()                              # still undoable once resolved


def test_empty_trash(tmp_path):
    lib = Library(tmp_path)
    _clip(lib, "a.wav")
    lib.delete("a.wav")
    assert lib.empty_trash() >= 1
    assert not (tmp_path / ".trash").exists()


def test_folder_move_notifies_every_wav(tmp_path):
    seen = []
    lib = Library(tmp_path, on_path_changed=lambda o, n: seen.append((o.name, n.parent.name if n else None)))
    lib.make_folder("", "s1")
    _clip(lib, "s1/a.wav")
    _clip(lib, "s1/b.wav")
    lib.rename("s1", "session")
    assert sorted(seen) == [("a.wav", "session"), ("b.wav", "session")]


def test_dataset_follows_a_move(tmp_path):
    db = Dataset(tmp_path / "db.sqlite")
    lib = Library(tmp_path / "lib", on_path_changed=lambda o, n: n and db.update_path(o, n))
    wav = _clip(lib, "a.wav")
    sid = db.create_session("s")
    cid = db.add_clip(sid, str(wav.resolve()), "recorded", 48000)
    lib.make_folder("", "good")
    new = lib.move("a.wav", "good")
    assert db.get_clip(cid)["path"] == str(new)
    db.close()


def test_unique_name(tmp_path):
    lib = Library(tmp_path)
    _clip(lib, "tap.wav")
    assert lib.unique_name("", "tap").name == "tap-2.wav"
