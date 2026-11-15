"""Build a standalone Windows executable (no Python needed by end users).

Usage, from the repository root with the project's virtual environment:

    .venv/Scripts/python scripts/build.py

Writes:
    dist/MHRiseQuriousPredictor.exe                      double-click to run
    dist/MHRiseQuriousPredictor-<version>-windows.zip     exe + README + LICENSE

The window uses Microsoft Edge WebView2, which ships with Windows 10/11.
Nothing from the game is bundled: game data and icons are read from the user's own install.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "build"
NAME = "MHRiseQuriousPredictor"


def run(*cmd):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT)


def version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version = "([^"]+)"', text, re.M).group(1)


def main():
    py = sys.executable
    # mhrise-exporter is usually an editable install, which PyInstaller cannot see: add its source dir.
    import mhrise_exporter
    exporter_src = Path(mhrise_exporter.__file__).resolve().parent.parent
    run(py, "-m", "pip", "install", "--quiet", "pyinstaller")
    try:  # the Rust engine is built by `pip install -e .` (maturin); refuse to ship without it
        import qurious_predictor._native  # noqa: F401
    except ImportError:
        sys.exit("qurious_predictor._native is missing: run `pip install -e .` (needs a Rust toolchain) first.")
    shutil.rmtree(WORK, ignore_errors=True)
    launcher = WORK / "launcher.py"
    WORK.mkdir(parents=True, exist_ok=True)
    launcher.write_text("from qurious_predictor.app import main\n\nif __name__ == '__main__':\n    main()\n", encoding="utf-8")
    web = ROOT / "qurious_predictor" / "web" / "index.html"
    run(py, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--log-level", "WARN",
        "--name", NAME, "--distpath", DIST, "--workpath", WORK / "work", "--specpath", WORK,
        "--paths", ROOT, "--paths", exporter_src, "--add-data", f"{web};qurious_predictor/web",
        "--collect-submodules", "qurious_predictor", "--collect-submodules", "mhrise_exporter",
        "--hidden-import", "qurious_predictor._native",
        launcher)
    exe = DIST / f"{NAME}.exe"
    archive = DIST / f"{NAME}-{version()}-windows.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(exe, exe.name)
        z.write(ROOT / "README.md", "README.md")
        z.write(ROOT / "LICENSE", "LICENSE.txt")
    print(f"\n{exe}  ({exe.stat().st_size / 1e6:.1f} MB)\n{archive}  ({archive.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
