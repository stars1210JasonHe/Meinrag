"""persist() must never leave a partial index at the live path.

WHY THIS EXISTS -- measured on the NAS, 2026-09-04, while an ingest was running:

    index.faiss sampled every 3s for 7 minutes
      12.1% of wall clock at less than full size
      9 separate episodes, each 3-9 s (mean 5.7 s)
      one sample caught it at ZERO bytes
      no .tmp sibling, no rename -- save_local writes straight into the live directory

    Reading the store during one of those windows raises
    `EOFError: Ran out of input` out of pickle.load. That is not hypothetical: it is how
    this file came to be written. The running container survives only because its store is
    already in memory -- a restart landing in a window cannot load its own index, and the
    service does not come back.

The guarantee under test is therefore NOT "the save is fast" but "a reader at the live path
sees either the complete old index or the complete new one, never a torn file, and a save
that FAILS leaves the previous index intact".
"""
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class _FakeStore:
    """Stands in for a langchain FAISS object. Records where it was asked to save."""

    def __init__(self, payload=b"INDEX-V1"):
        self.payload = payload
        self.saved_to = []
        self.docstore = MagicMock()

    def save_local(self, folder_path, index_name="index"):
        self.saved_to.append(folder_path)
        p = Path(folder_path)
        p.mkdir(parents=True, exist_ok=True)
        (p / f"{index_name}.faiss").write_bytes(self.payload)
        (p / f"{index_name}.pkl").write_bytes(self.payload + b"-PKL")


class _FailingStore(_FakeStore):
    """Writes a PARTIAL file and then dies -- the shape of an interrupted save."""

    def save_local(self, folder_path, index_name="index"):
        self.saved_to.append(folder_path)
        p = Path(folder_path)
        p.mkdir(parents=True, exist_ok=True)
        (p / f"{index_name}.faiss").write_bytes(b"TRUNCA")     # partial, then:
        raise RuntimeError("disk full halfway through the write")


def _manager(tmp_path):
    from app.vectorstore.faiss_store import FAISSStoreManager
    return FAISSStoreManager(tmp_path)


class TestPersistIsAtomic:

    def test_persist_does_not_write_into_the_live_directory(self, tmp_path):
        """The core of it. save_local must be handed somewhere else entirely.

        If it is handed the live directory, then for the duration of the write the live
        index.faiss IS the partial file -- which is precisely the 12.1% window measured on
        the NAS."""
        m = _manager(tmp_path)
        m._store = _FakeStore()
        m.persist()
        assert m._store.saved_to, "save_local was never called"
        for target in m._store.saved_to:
            assert Path(target).resolve() != m._persist_dir.resolve(), (
                "save_local wrote directly into the live directory %r -- a reader during "
                "the write sees a torn file" % target)

    def test_the_index_still_lands_at_the_live_path(self, tmp_path):
        """POSITIVE CONTROL. A persist that wrote nowhere would satisfy the test above."""
        m = _manager(tmp_path)
        m._store = _FakeStore(b"INDEX-V1")
        m.persist()
        live = m._persist_dir / "index.faiss"
        assert live.exists(), "nothing arrived at the live path"
        assert live.read_bytes() == b"INDEX-V1"
        assert (m._persist_dir / "index.pkl").read_bytes() == b"INDEX-V1-PKL"

    def test_a_second_persist_replaces_the_first(self, tmp_path):
        """Negative half of the control: the file must actually CHANGE.

        Without this, a persist that silently refused to overwrite would pass everything
        above while leaving the index permanently stale."""
        m = _manager(tmp_path)
        m._store = _FakeStore(b"INDEX-V1")
        m.persist()
        m._store = _FakeStore(b"INDEX-V2-LONGER")
        m.persist()
        assert (m._persist_dir / "index.faiss").read_bytes() == b"INDEX-V2-LONGER"

    def test_a_failed_save_leaves_the_previous_index_INTACT(self, tmp_path):
        """The guarantee that actually matters during an ingest.

        An interrupted save must not damage what is already on disk. In-place writing fails
        this by construction: the truncation happens before the failure."""
        m = _manager(tmp_path)
        m._store = _FakeStore(b"GOOD-INDEX-V1")
        m.persist()
        before = (m._persist_dir / "index.faiss").read_bytes()

        m._store = _FailingStore()
        with pytest.raises(RuntimeError):
            m.persist()

        after = (m._persist_dir / "index.faiss").read_bytes()
        assert after == before, (
            "a failed save damaged the live index: %r -> %r" % (before[:20], after[:20]))

    def test_no_temp_directory_is_left_behind(self, tmp_path):
        """A save every few seconds during a 40k-file ingest must not litter the volume."""
        m = _manager(tmp_path)
        m._store = _FakeStore()
        m.persist()
        m._store = _FailingStore()
        with pytest.raises(RuntimeError):
            m.persist()
        strays = [p for p in m._persist_dir.parent.iterdir()
                  if p.is_dir() and p.name.startswith(".")]
        assert not strays, "left temp directories behind: %r" % [p.name for p in strays]

    @pytest.mark.skipif(os.name != "posix", reason="directory fsync is POSIX-only")
    def test_directory_entry_is_flushed_on_posix(self, tmp_path):
        """The rename must survive power loss, which needs the DIRECTORY fsynced too.

        Skipped on Windows: os.open() on a directory is not permitted there, so the
        production behaviour (Linux container) cannot be exercised from a Windows dev box.
        Marked skip rather than silently passing -- a green tick here on Windows would
        assert something this platform never ran."""
        m = _manager(tmp_path)
        m._store = _FakeStore()
        synced = []
        real_fsync = os.fsync

        def spy(fd):
            try:
                if os.path.isdir(os.readlink("/proc/self/fd/%d" % fd)):
                    synced.append(fd)
            except OSError:
                pass
            return real_fsync(fd)

        os.fsync = spy
        try:
            m.persist()
        finally:
            os.fsync = real_fsync
        assert synced, "the containing directory was never fsynced"
