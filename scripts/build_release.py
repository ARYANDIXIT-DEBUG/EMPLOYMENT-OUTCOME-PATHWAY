"""Rebuild the release ZIP, reproducibly. Standard library only.

    python scripts/build_release.py                      # writes ../Employment_Outcome_Pathway_Grouping_After_Skilling.zip
    python scripts/build_release.py --out some/name.zip  # any name; the contents do not depend on the name

What it does, in order:
  1. Walks the project folder and sorts every file into include / exclude / UNEXPECTED. A file that is neither on the
     allowlist nor on the exclusion list stops the build, so nothing slips into the ZIP by accident.
  2. Checks that the files listed in the purpose table of PROJECT_MANIFEST.md are exactly the files to be shipped.
  3. Scans the shipped text files for private-key blocks and well-known token formats (a safety net, not a guarantee).
  4. Rewrites the SHA-256 block of PROJECT_MANIFEST.md (hashes of every shipped file except the manifest itself).
  5. Writes the ZIP: one top-level folder, files in sorted order, fixed timestamps, fixed permissions, fixed compression.
     The same files always give the same ZIP bytes. Prints the file count and the ZIP's SHA-256.

Excluded on purpose: caches and bytecode, virtual environments, drafts and temp files, credentials, any file under
data/raw or data/processed (the release ships data/raw/.gitkeep only), generated outputs (reports/results, reports/figures,
reports/report__*.md: they regenerate with `python run_pipeline.py --synthetic`), STATUS.md and ZIP files.
Exit codes: 0 built, 1 build refused (message says why).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import sys
import zipfile
from pathlib import Path

TOP = "Employment_Outcome_Pathway_Grouping_After_Skilling"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FIXED_MODE = 0o100644 << 16
MANIFEST = "PROJECT_MANIFEST.md"

# Allowlist: a file ships only if it matches one of these (paths use forward slashes, relative to the project root).
INCLUDE = [
    "README.md", "DATASET_SETUP.md", "PROJECT_MANIFEST.md", "VIVA_GUIDE.md", "FINAL_AUDIT_REPORT.md",
    "config.yaml", "requirements.txt", "requirements.lock.txt", "run_pipeline.py",
    "src/*.py", "tests/*.py", "dashboard/app.py", "docs/INTERFACES.md", "docs/DATA_USE_ASSESSMENT.md",
    "reports/report_template.md", "scripts/build_release.py", "data/raw/.gitkeep",
]
# Exclusions: matched against the path and against each path component. Checked first.
EXCLUDE = [
    "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".ipynb_checkpoints", ".git", ".venv", "venv", "env",
    "*.bak", "*.orig", "*.tmp", "*.temp", "*.swp", "*~", ".DS_Store", "Thumbs.db", "*.log", "draft*", "*_draft*", "*.draft.*",
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "credentials*", "secrets*", "*.zip", "STATUS.md", "VERIFICATION_RESULT.md",
    "reports/results/*", "reports/figures/*", "reports/report__*.md", "data/processed/*", "data/raw/*",
]
SECRET_PATTERNS = [r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"AKIA[0-9A-Z]{16}", r"ghp_[A-Za-z0-9]{36}", r"sk-[A-Za-z0-9]{32,}", r"xox[baprs]-[A-Za-z0-9-]{10,}"]
BEGIN_FILES, END_FILES = "<!-- BEGIN FILES -->", "<!-- END FILES -->"
BEGIN_HASH, END_HASH = "<!-- BEGIN HASHES -->", "<!-- END HASHES -->"


class BuildRefused(Exception):
    pass


def _match(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    for pat in patterns:
        if fnmatch.fnmatchcase(rel, pat) or any(fnmatch.fnmatchcase(p, pat) for p in parts):
            return True
    return False


def classify(root: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (include, exclude, unexpected) lists of relative paths."""
    inc, exc, unexpected = [], [], []
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(root).as_posix()
        if rel == "data/raw/.gitkeep":
            inc.append(rel)
        elif _match(rel, EXCLUDE):
            exc.append(rel)
        elif any(fnmatch.fnmatchcase(rel, pat) for pat in INCLUDE):
            inc.append(rel)
        else:
            unexpected.append(rel)
    return inc, exc, unexpected


def manifest_listed(root: Path) -> list[str]:
    text = (root / MANIFEST).read_text(encoding="utf-8")
    if BEGIN_FILES not in text or END_FILES not in text:
        raise BuildRefused(f"{MANIFEST} has no {BEGIN_FILES} ... {END_FILES} block")
    block = text.split(BEGIN_FILES, 1)[1].split(END_FILES, 1)[0]
    return sorted(re.findall(r"^\|\s*`([^`]+)`\s*\|", block, flags=re.M))


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def rewrite_hash_block(root: Path, files: list[str]) -> None:
    path = root / MANIFEST
    text = path.read_text(encoding="utf-8")
    if BEGIN_HASH not in text or END_HASH not in text:
        raise BuildRefused(f"{MANIFEST} has no {BEGIN_HASH} ... {END_HASH} block")
    rows = ["| File | SHA-256 |", "|---|---|"]
    rows += [f"| `{f}` | `{sha256_bytes((root / f).read_bytes())}` |" for f in files if f != MANIFEST]
    head, rest = text.split(BEGIN_HASH, 1)
    tail = rest.split(END_HASH, 1)[1]
    path.write_text(head + BEGIN_HASH + "\n" + "\n".join(rows) + "\n" + END_HASH + tail, encoding="utf-8", newline="\n")


def build(root: Path, out: Path) -> tuple[int, str]:
    inc, _exc, unexpected = classify(root)
    if unexpected:
        raise BuildRefused("files that are neither allowlisted nor excluded (move, delete or allowlist them): " + ", ".join(unexpected))
    listed, shipped = manifest_listed(root), sorted(inc)
    if listed != shipped:
        raise BuildRefused(f"{MANIFEST} purpose table and the shipped files differ. In table only: {sorted(set(listed) - set(shipped))}; "
                           f"shipped only: {sorted(set(shipped) - set(listed))}")
    for f in shipped:
        if f.endswith(".gitkeep"):
            continue
        text = (root / f).read_text(encoding="utf-8")
        for pat in SECRET_PATTERNS:
            if re.search(pat, text):
                raise BuildRefused(f"{f} matches the secret pattern {pat!r}")
    rewrite_hash_block(root, shipped)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in shipped:
            info = zipfile.ZipInfo(f"{TOP}/{f}", date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = FIXED_MODE
            info.create_system = 3
            z.writestr(info, (root / f).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return len(shipped), sha256_bytes(out.read_bytes())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/build_release.py", description="Rebuild the release ZIP reproducibly.")
    ap.add_argument("--out", default=None, help=f"ZIP path (default: ../{TOP}.zip next to the project folder)")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    out = Path(args.out).resolve() if args.out else root.parent / f"{TOP}.zip"
    try:
        n, digest = build(root, out)
    except BuildRefused as exc:
        print(f"BUILD REFUSED: {exc}", file=sys.stderr)
        return 1
    print(f"built {out.name}: {n} files under {TOP}/")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
