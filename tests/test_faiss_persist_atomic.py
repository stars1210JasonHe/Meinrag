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
import sys
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




class TestStaleSaveDirsAreSwept:
    """A SIGKILLed save leaves its temp dir behind - measured at 1.9 GB on the NAS."""

    def test_startup_removes_a_leftover_save_dir(self, tmp_path):
        m = _manager(tmp_path)
        stale = m._persist_dir.parent / ".save-abcd1234"
        stale.mkdir()
        (stale / "index.faiss").write_bytes(b"x" * 100)
        # Age it past the gate. Without this the test would pass only because the sweep was
        # unconditional - i.e. it would have been asserting the very bug review just found.
        import os as _os, time as _t
        from app.vectorstore.faiss_store import STALE_SAVE_DIR_SECONDS
        old_t = _t.time() - STALE_SAVE_DIR_SECONDS - 60
        _os.utime(stale, (old_t, old_t))
        m.initialize(MagicMock())
        assert not stale.exists(), "the orphaned save dir was not removed"

    def test_it_does_NOT_touch_the_live_directory(self, tmp_path):
        """The live dir is a SIBLING of the temp dirs. This is the test that matters: a
        careless glob here deletes the index."""
        m = _manager(tmp_path)
        # NOT named index.faiss: initialize() loads that file if it exists, and fake bytes
        # make faiss raise before the sweep is ever reached. The property under test is that
        # the sweep leaves the live DIRECTORY and its contents alone, which this shows without
        # requiring a real 1.5 GB index.
        (m._persist_dir / "keepme.bin").write_bytes(b"LIVE")
        m.initialize(MagicMock())
        assert m._persist_dir.is_dir(), "the sweep deleted the live directory itself"
        assert (m._persist_dir / "keepme.bin").read_bytes() == b"LIVE", (
            "the sweep destroyed the live directory contents")

    def test_a_FRESH_save_dir_is_left_alone(self, tmp_path):
        """The one that matters: another process may be writing into it RIGHT NOW.

        With TASK_BACKEND=arq each summary task builds its own FAISSStoreManager and calls
        initialize() in a separate worker process, so an unconditional sweep lets a worker
        delete the API process's in-flight save - turning a healthy persist into
        FileNotFoundError and leaving chunks added with no registry row. Found by independent
        review before it shipped; without this test the sweep looks correct in every other
        case."""
        m = _manager(tmp_path)
        live = m._persist_dir.parent / ".save-inflight"
        live.mkdir()
        (live / "index.faiss").write_bytes(b"HALF-WRITTEN")
        m.initialize(MagicMock())
        assert live.exists(), (
            "the sweep deleted a temp dir that had just been touched - under arq that is "
            "another process's live save")
        assert (live / "index.faiss").read_bytes() == b"HALF-WRITTEN"

    def test_it_does_NOT_touch_unrelated_siblings(self, tmp_path):
        """Negative half: only .save-* is fair game. The backup dirs that saved production
        this morning are siblings too, and they are named faiss_bak_*."""
        m = _manager(tmp_path)
        keep = m._persist_dir.parent / "faiss_bak_20260903"
        keep.mkdir()
        (keep / "index.faiss").write_bytes(b"BACKUP")
        m.initialize(MagicMock())
        assert (keep / "index.faiss").read_bytes() == b"BACKUP", (
            "the sweep deleted a backup directory")


@pytest.mark.skipif(os.name != "posix",
                    reason="the directory-flush block is POSIX-only; on Windows it does not "
                           "execute at all, so these tests would pass without running the "
                           "code under test -- verified: mutating the guard left them green")
class TestDirectoryFsyncFailureDoesNotFailTheWrite:
    """A filesystem that rejects directory fsync must not turn a successful publish into an
    error. The fsync happens AFTER both renames, so by then the write has landed; raising
    would make add_documents() and the upload flow treat a completed write as failed and skip
    the registry row, leaving chunks nothing points at.

    Found by independent review before deploy. Measured on the real target the same day:
    Synology btrfs DOES support directory fsync, so this was a portability guard rather than
    a live bug there - but the ordering was wrong regardless of filesystem.
    """

    def test_persist_survives_a_rejected_directory_fsync(self, tmp_path, monkeypatch):
        m = _manager(tmp_path)
        m._store = _FakeStore(b"PAYLOAD-V1")
        real = os.fsync

        def picky(fd):
            # reject only DIRECTORY fsync, exactly as an unsupporting filesystem would
            try:
                if os.fstat(fd).st_mode & 0o040000:
                    raise OSError(22, "Invalid argument")
            except OSError as e:
                if e.errno == 22:
                    raise
            return real(fd)

        monkeypatch.setattr(os, "fsync", picky)
        m.persist()          # must NOT raise
        assert (m._persist_dir / "index.faiss").read_bytes() == b"PAYLOAD-V1", (
            "the index must still be published even when the directory flush is refused")

    def test_a_DATA_fsync_failure_still_fails_loudly(self, tmp_path, monkeypatch):
        """Negative half. Only the post-publish directory flush is forgiven. A failure while
        flushing the FILE happens BEFORE anything is published, so it must still raise -
        otherwise this fix would have swallowed real write errors."""
        m = _manager(tmp_path)
        m._store = _FakeStore(b"PAYLOAD-V1")
        real = os.fsync

        def fail_files(fd):
            if not (os.fstat(fd).st_mode & 0o040000):
                raise OSError(5, "Input/output error")
            return real(fd)

        monkeypatch.setattr(os, "fsync", fail_files)
        with pytest.raises(OSError):
            m.persist()


class TestDirectoryEntryIsFlushed:
    """Kept separate from TestPersistIsAtomic so the Linux-only skip does not read as
    if the atomicity tests themselves were platform-conditional. They are not."""

    @pytest.mark.skipif(not sys.platform.startswith("linux"),
                        reason="this test reads /proc/self/fd, which is Linux-only")
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
