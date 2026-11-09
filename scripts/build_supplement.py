"""Build the supplement (paper/supplement.tex) into output/pdf, named after its title.

The supplement uses the paper's acmart class and typefaces. Its tables and
number macros are first regenerated from the derived evidence by
scripts/supplement_tables.py. XeLaTeX runs three times so that references and
the page count settle; SOURCE_DATE_EPOCH is fixed, so a rebuild from the same
sources is byte-identical. The build fails on any overfull or underfull box,
undefined reference or unembedded font, or if the file name does not match the
title stored in the PDF.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
NAME = "Uniqueness Is Not Continuity - Supplementary Material.pdf"
OUTPUT = ROOT / "output" / "pdf" / NAME
EPOCH = "1794096000"            # 2026-11-08T00:00:00Z, the date of this build


def main() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "supplement_tables.py")], check=True)
    env = dict(os.environ, SOURCE_DATE_EPOCH=EPOCH, FORCE_SOURCE_DATE="1")
    with tempfile.TemporaryDirectory() as directory:
        # Build in a copy with relative paths: the PDF trailer ID then does not
        # depend on where the repository or the temporary directory lives.
        for name in ("supplement.tex", "numbers.tex", "acmart.cls"):
            shutil.copy2(PAPER / name, directory)
        shutil.copytree(PAPER / "supplement", Path(directory) / "supplement")
        for _ in range(3):
            result = subprocess.run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", "supplement.tex"],
                                    cwd=directory, env=env, capture_output=True, text=True)
            if result.returncode != 0:
                raise SystemExit(result.stdout[-3000:])
        log = (Path(directory) / "supplement.log").read_text(errors="replace")
        problems = re.findall(r"^(?:Overfull|Underfull) \\[hv]box.*$|^LaTeX Warning: (?:Reference|Citation).*$",
                              log, re.M)
        # The balance package notes when \balance is called in the second column; it is harmless.
        assert not problems, "supplement layout problems:\n" + "\n".join(problems)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(directory) / "supplement.pdf", OUTPUT)
    fonts = subprocess.run(["pdffonts", str(OUTPUT)], capture_output=True, text=True, check=True).stdout
    for line in fonts.splitlines()[2:]:
        assert " yes " in line and "Type 3" not in line, ("font not embedded or Type 3", line)
    info = subprocess.run(["pdfinfo", str(OUTPUT)], capture_output=True, text=True, check=True).stdout
    title = re.search(r"^Title:\s+(.+)$", info, re.M).group(1).strip()
    assert NAME == title.replace(": ", " - ") + ".pdf", ("file name does not match the title", title)
    pages = re.search(r"Pages:\s+(\d+)", info).group(1)
    print(f"{OUTPUT.relative_to(ROOT)}: {pages} pages; fonts embedded; no box or reference warnings")


if __name__ == "__main__":
    main()
