"""Bug 2: .docx upload crashed on the NAS with `No module named 'docx2txt'`.
Docx2txtLoader needs the docx2txt package; it must be a DECLARED runtime dep
so the prod image (built from pyproject) includes it — not just present in a
dev venv transitively."""
import tomllib
from pathlib import Path


def test_docx2txt_is_declared_dependency():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert any(d.split(">=")[0].split("==")[0].strip() == "docx2txt" for d in deps), \
        "docx2txt must be a declared runtime dependency (Docx2txtLoader needs it)"


def test_docx2txt_importable():
    import docx2txt  # noqa: F401
