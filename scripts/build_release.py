"""Build the reproducible Turkey CA submission directory and ZIP.

The package contains source, documentation, tests, the Turkey presentation and
aggregate outputs. Raw microdata and respondent-level derived files are never
included. The package contents are explicitly allowlisted in PROJECT_MANIFEST.md.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import sys
import zipfile
from pathlib import Path

TOP = "Turkey_CA_Submission"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FIXED_MODE = 0o100644 << 16
MANIFEST = "PROJECT_MANIFEST.md"

# (source under project root, destination within the package)
ROOT_FILES = [
    "README.md", "DATASET_SETUP.md", "PROJECT_MANIFEST.md", "VIVA_GUIDE.md",
    "FINAL_AUDIT_REPORT.md", "config.yaml", "requirements.txt",
    "requirements.lock.txt", "run_pipeline.py", "pytest.ini",
]
SOURCE_FILES = ["src/*.py", "tests/*.py", "docs/*.md", "docs/mospi/*"]
EXACT_FILES = [
    "dashboard/app.py", "scripts/build_release.py",
    "reports/TURKEY_FINAL_REPORT.md", "reports/TURKEY_REQUIREMENT_AUDIT.md",
    "reports/viva_questions_and_answers.md",
    "reports/dashboard_screenshots/primary_turkey_1366x768.jpg",
    "reports/dashboard_screenshots/primary_turkey_1920x1080.jpg",
    "outputs/turkey/summary.json", "outputs/turkey/cluster_profile_report.md",
    "outputs/turkey/cluster_admin_profile.csv", "outputs/turkey/baseline_employment_by_cluster.csv",
    "outputs/turkey/baseline_employed_comparison.csv", "outputs/turkey/attrition_admin_comparison.csv",
    "outputs/turkey/cluster_jan2012_state_profile.csv", "outputs/turkey/cluster_gender_profile.csv",
    "outputs/turkey/cluster_prevalence.csv", "outputs/turkey/cluster_method_evaluation.csv",
    "submission/Turkey_ISKUR_CA_presentation_v4.pptx",
    "submission/PLFS_2023-24_Cross_Sectional_Study_final_submission_v3.pptx",
    "data/raw/.gitkeep",
]
FORBIDDEN_NAMES = {"trainee_analysis.csv", "valid_post_training_trajectories.csv", "TurkeyPublicUseData.dta",
                   "perv1.csv", "perrv.csv", "hhv1.csv", "hhrv.csv"}
SECRET_PATTERNS = [r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"AKIA[0-9A-Z]{16}",
                   r"ghp_[A-Za-z0-9]{36}", r"sk-[A-Za-z0-9]{32,}", r"xox[baprs]-[A-Za-z0-9-]{10,}"]
BEGIN_FILES, END_FILES = "<!-- BEGIN FILES -->", "<!-- END FILES -->"
BEGIN_HASH, END_HASH = "<!-- BEGIN HASHES -->", "<!-- END HASHES -->"


class BuildRefused(Exception):
    pass


def source_files(root: Path) -> list[str]:
    files = set(ROOT_FILES + EXACT_FILES)
    for pattern in SOURCE_FILES:
        files.update(p.relative_to(root).as_posix() for p in root.glob(pattern) if p.is_file())
    files.discard(MANIFEST)  # added below so its generated hash block is the version copied
    files.add(MANIFEST)
    forbidden = sorted(f for f in files if Path(f).name in FORBIDDEN_NAMES)
    if forbidden:
        raise BuildRefused("restricted or respondent-level files entered the package list: " + ", ".join(forbidden))
    missing = sorted(f for f in files if not (root / f).is_file())
    if missing:
        raise BuildRefused("required package files are missing: " + ", ".join(missing))
    return sorted(files)


def manifest_listed(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if BEGIN_FILES not in text or END_FILES not in text:
        raise BuildRefused(f"{MANIFEST} has no {BEGIN_FILES} ... {END_FILES} block")
    block = text.split(BEGIN_FILES, 1)[1].split(END_FILES, 1)[0]
    return sorted(re.findall(r"^\|\s*`([^`]+)`\s*\|", block, flags=re.M))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rewrite_hash_block(root: Path, stage: Path, files: list[str]) -> None:
    path = root / MANIFEST
    text = path.read_text(encoding="utf-8")
    if BEGIN_HASH not in text or END_HASH not in text:
        raise BuildRefused(f"{MANIFEST} has no {BEGIN_HASH} ... {END_HASH} block")
    rows = ["| File | SHA-256 |", "|---|---|"]
    for f in files:
        if f == MANIFEST:
            continue
        rows.append(f"| `{f}` | `{sha256(root / f)}` |")
    head, rest = text.split(BEGIN_HASH, 1)
    tail = rest.split(END_HASH, 1)[1]
    path.write_text(head + BEGIN_HASH + "\n" + "\n".join(rows) + "\n" + END_HASH + tail,
                    encoding="utf-8", newline="\n")


def _match(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(rel, p) for p in patterns)


def build(root: Path, out: Path, stage: Path) -> tuple[int, str]:
    files = source_files(root)
    if manifest_listed(root / MANIFEST) != files:
        listed, expected = manifest_listed(root / MANIFEST), files
        raise BuildRefused(f"{MANIFEST} purpose table differs from package allowlist; table only: "
                           f"{sorted(set(listed) - set(expected))}; package only: {sorted(set(expected) - set(listed))}")
    # Never silently absorb files placed in the final submission directory.
    if stage.exists():
        staged_existing = sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file())
        old_manifest = stage / MANIFEST
        if staged_existing:
            if not old_manifest.is_file() or manifest_listed(old_manifest) != staged_existing:
                raise BuildRefused("submission directory contains files not exactly accounted for by its previous manifest")
            stale = sorted(set(staged_existing) - set(files))
            stage_root = stage.resolve()
            for rel in stale:
                entry = stage / rel
                candidate = entry.resolve()
                if entry.is_symlink() or not candidate.is_relative_to(stage_root) or not candidate.is_file():
                    raise BuildRefused(f"refusing to remove unsafe stale package entry: {rel}")
                entry.unlink()
    rewrite_hash_block(root, stage, files)
    for f in files:
        dst = stage / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((root / f).read_bytes())
    staged = sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file())
    if staged != files:
        raise BuildRefused("staged submission does not exactly match the manifest")
    if any(Path(f).name in FORBIDDEN_NAMES for f in staged):
        raise BuildRefused("a restricted raw or respondent-level file is staged")
    for f in staged:
        if f.endswith((".md", ".py", ".yaml", ".yml", ".txt", ".json", ".csv")):
            body = (stage / f).read_text(encoding="utf-8")
            for pattern in SECRET_PATTERNS:
                if re.search(pattern, body):
                    raise BuildRefused(f"{f} matches the secret pattern {pattern!r}")
    out.parent.mkdir(parents=True, exist_ok=True)
    # Keep a previous release intact until the replacement archive has been
    # fully written, listed, CRC-checked and compared against staged bytes.
    candidate = out.with_name(out.name + ".candidate")
    try:
        with zipfile.ZipFile(candidate, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for f in staged:
                info = zipfile.ZipInfo(f"{TOP}/{f}", date_time=FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = FIXED_MODE
                info.create_system = 3
                z.writestr(info, (stage / f).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        with zipfile.ZipFile(candidate, "r") as z:
            expected_names = [f"{TOP}/{f}" for f in staged]
            if z.namelist() != expected_names:
                raise BuildRefused("replacement ZIP has an unexpected top-level structure or file list")
            if z.testzip() is not None:
                raise BuildRefused("replacement ZIP failed its CRC check")
            for f in staged:
                if z.read(f"{TOP}/{f}") != (stage / f).read_bytes():
                    raise BuildRefused(f"replacement ZIP content differs from staged file: {f}")
        digest = sha256(candidate)
        candidate.replace(out)
    except (BuildRefused, OSError, zipfile.BadZipFile):
        candidate.unlink(missing_ok=True)
        raise
    return len(staged), digest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the Turkey CA submission folder and deterministic ZIP.")
    ap.add_argument("--out", default=None, help="ZIP destination (default: submission/Turkey_CA_Submission.zip)")
    ap.add_argument("--stage", default=None, help="package directory (default: submission/Turkey_CA_Submission)")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    stage = Path(args.stage).resolve() if args.stage else root / "submission" / TOP
    out = Path(args.out).resolve() if args.out else root / "submission" / f"{TOP}.zip"
    try:
        count, digest = build(root, out, stage)
    except (BuildRefused, OSError, UnicodeError) as exc:
        print(f"BUILD REFUSED: {exc}", file=sys.stderr)
        return 1
    print(f"built {stage}: {count} files")
    print(f"built {out}: sha256 {digest}")
    print("Raw microdata and respondent-level derived files were excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
