"""Results files and the report: every number in the report comes from a file in `reports/results/`.

Why this file exists: the easiest way to ship a wrong report is to type a number into it. So the pipeline saves
every result as a JSON file, the report template contains only placeholders such as `{{k_selection.chosen_k}}`, and
this module fills them from the files. A placeholder that cannot be filled stops the build with the full list of
problems; it is never left blank, never guessed and never filled with a number from another run.

Design choices worth defending in a viva:
  * One file per result: `reports/results/<name>__<tag>.json`, tag `SYNTHETIC` or `real`. The tag is part of the
    file name and is stored inside the file, so a synthetic result cannot be picked up for a real report by
    accident. If both tags exist and the caller does not say which, the build stops (ConfigError); it never mixes.
  * What can be saved is limited to what JSON can hold exactly: numbers, text, booleans, None, lists, dicts, numpy
    scalars and arrays, DataFrames (as a list of records) and dataclasses. NaN and infinity are stored as null and
    shown as "n/a", never as a number. Anything else raises TypeError: a result that cannot be read back is not saved.
  * Placeholder syntax: `{{name.key.0.key}}` walks into the saved result (list items by position); `|<format>`
    applies a Python format spec (`{{k_selection.silhouette|.3f}}`, `{{stability.ari|.1%}}`); `{{table:name.key}}`
    renders a list of records as a markdown table, `{{table:name.key|cols=a,b}}` chooses the columns; the pseudo
    result `config` reads the settings actually used (`{{config.time.n_points}}`), so even design facts such as the
    number of visits are never typed into the text. Without a format, floats show 4 significant digits.
  * The build collects ALL unresolved placeholders (missing result, missing key, bad position, a table where one
    value was expected) in one error with line numbers, writes nothing, and leaves any earlier report untouched.
  * `claims_audit` lists every placeholder with the file and key behind it, and flags numbers typed into the
    template outside any placeholder. That check is a heuristic: it catches digits (0.83, 40%), not number words
    ("four"), and it ignores years, dates, identifiers such as INT396 or P0, heading and list numbering, code, and
    lines marked `<!-- numbers-ok -->`. Typed numbers raise a UserWarning at render time; they do not stop the build.
  * A synthetic report opens with the configured SYNTHETIC banner, and every report ends with the list of result
    files it used, so a reader can trace each claim.

Limits: the module checks that numbers come from results files, not that the results are right or that the
sentences around them are true; the wording of the template still has to be honest. Nothing here computes a statistic.

Dependency rule: imports `config` only. The smoke demo uses temporary files and hand-made results.

Run the smoke demo with:  python -m src.report_builder
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
import re
import tempfile
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import Config, ConfigError, load_config, resolve_path

__all__ = [
    "ReportError",
    "save_result",
    "load_results",
    "render_report",
    "claims_audit",
]

_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_TAGS = ("SYNTHETIC", "real")
_PLACEHOLDER = re.compile(r"\{\{\s*(table:)?([A-Za-z0-9_\-\.=\[\]]+?)\s*(?:\|\s*([^{}]*?))?\s*\}\}")
_FILE_RE = re.compile(r"^(?P<name>[A-Za-z0-9_\-]+?)__(?P<tag>SYNTHETIC|real)\.json$")
_NUMBERS_OK = "<!-- numbers-ok -->"
_NA = "n/a"


class ReportError(Exception):
    """The report could not be built: one or more placeholders are unresolved, or a result file is unusable."""


# ---------------------------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------------------------
def _to_jsonable(x: Any, path: str = "result") -> Any:
    """Convert numpy, pandas and dataclass objects into plain JSON types. NaN and infinity become None."""
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, np.ndarray):
        return [_to_jsonable(v, f"{path}[]") for v in x.tolist()]
    if isinstance(x, pd.DataFrame):
        return [{str(k): _to_jsonable(v, f"{path}.{k}") for k, v in row.items()} for row in x.to_dict("records")]
    if isinstance(x, pd.Series):
        return [_to_jsonable(v, f"{path}[]") for v in x.tolist()]
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    if isinstance(x, Path):
        return str(x)
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {f.name: _to_jsonable(getattr(x, f.name), f"{path}.{f.name}") for f in dataclasses.fields(x)}
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if not isinstance(k, (str, int, np.integer)):
                raise TypeError(f"{path}: dictionary keys must be text or integers, got {type(k).__name__}")
            out[str(k)] = _to_jsonable(v, f"{path}.{k}")
        return out
    if isinstance(x, (list, tuple)):
        return [_to_jsonable(v, f"{path}[]") for v in x]
    if isinstance(x, (set, frozenset)):
        return [_to_jsonable(v, f"{path}[]") for v in sorted(x, key=str)]
    raise TypeError(f"{path}: {type(x).__name__} cannot be saved as a result (use numbers, text, lists, dicts, arrays or DataFrames)")


def _tag(is_synthetic: bool) -> str:
    return "SYNTHETIC" if is_synthetic else "real"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_result(name: str, obj: Any, cfg: Config, is_synthetic: bool) -> Path:
    """Save `obj` as `<paths.results_dir>/<name>__<tag>.json` and return the path.

    The file holds an envelope `{"name", "tag", "is_synthetic", "data"}`; placeholders address `data`. An existing file
    of the same name and tag is replaced (atomically: a crash leaves the old file, never half a file). Raises
    ValueError for a name outside letters, digits, `_` and `-`, and TypeError for an object JSON cannot hold.
    """
    if not isinstance(name, str) or not _NAME_RE.match(name) or name == "config":
        raise ValueError(f"result name {name!r} must use only letters, digits, '_' and '-' (and 'config' is reserved)")
    data = _to_jsonable(obj, name)
    envelope = {"name": name, "tag": _tag(is_synthetic), "is_synthetic": bool(is_synthetic), "data": data}
    text = json.dumps(envelope, indent=2, allow_nan=False)
    path = resolve_path(cfg, "results_dir") / f"{name}__{_tag(is_synthetic)}.json"
    _atomic_write(path, text + "\n")
    return path


# ---------------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------------
def _scan(cfg: Config) -> dict[str, dict[str, Path]]:
    """{tag: {name: path}} for every results file in the results folder."""
    found: dict[str, dict[str, Path]] = {t: {} for t in _TAGS}
    d = resolve_path(cfg, "results_dir")
    if d.is_dir():
        for p in sorted(d.iterdir()):
            m = _FILE_RE.match(p.name)
            if m:
                found[m.group("tag")][m.group("name")] = p
    return found


def _choose_tag(found: dict[str, dict[str, Path]], is_synthetic: bool | None) -> str:
    """The tag to use: the one asked for, else the only one present. Both present without a choice stops the build."""
    if is_synthetic is not None:
        return _tag(is_synthetic)
    present = [t for t in _TAGS if found[t]]
    if len(present) == 2:
        raise ConfigError("both SYNTHETIC and real results exist in the results folder: say which to use "
                          "(report.results_tag: SYNTHETIC or real, or is_synthetic=...). They are never mixed.")
    return present[0] if present else "SYNTHETIC"


def _read(path: Path, tag: str) -> Any:
    try:
        env = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ReportError(f"{path.name} cannot be read as JSON: {e}") from e
    if not isinstance(env, dict) or env.get("tag") != tag or "data" not in env:
        raise ReportError(f"{path.name} is not a valid results file for tag {tag} (envelope missing or tag mismatch)")
    return env["data"]


def load_results(cfg: Config, is_synthetic: bool | None = None) -> dict[str, Any]:
    """Every saved result of one tag as {name: data}.

    `is_synthetic` True or False picks the tag; None uses the only tag present and raises ConfigError if both
    exist. An empty or missing results folder gives {}. Raises ReportError for a file that is not valid.
    """
    found = _scan(cfg)
    tag = _choose_tag(found, is_synthetic)
    return {n: _read(p, tag) for n, p in found[tag].items()}


# ---------------------------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------------------------
def _walk(root: Any, segments: list[str]) -> tuple[bool, Any, str]:
    """Follow `segments` into `root`. Returns (found, value, reason when not found)."""
    cur = root
    for i, seg in enumerate(segments):
        here = ".".join(segments[:i]) or "(top)"
        if isinstance(cur, dict):
            if seg not in cur:
                return False, None, f"no key {seg!r} under {here} (available: {sorted(cur)[:8]})"
            cur = cur[seg]
        elif isinstance(cur, list):
            if not re.fullmatch(r"\d+", seg):
                return False, None, f"{here} is a list; use a position such as .0 instead of {seg!r}"
            if int(seg) >= len(cur):
                return False, None, f"position {seg} is out of range for {here} (length {len(cur)})"
            cur = cur[int(seg)]
        else:
            return False, None, f"{here} is a single value and has no {seg!r} inside"
    return True, cur, ""


def _fmt_default(v: Any) -> str:
    if v is None:
        return _NA
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return format(v, ".4g")
    return str(v)


def _fmt_value(v: Any, spec: str | None) -> str:
    if v is None:
        return _NA
    if spec:
        if isinstance(v, bool) or isinstance(v, str):
            raise ValueError(f"a format ({spec!r}) cannot be applied to {type(v).__name__} {v!r}")
        return format(v, spec)
    return _fmt_default(v)


def _table(records: Any, cols: list[str] | None) -> str:
    if not isinstance(records, list) or not records or not all(isinstance(r, dict) for r in records):
        raise ValueError("a table placeholder needs a non-empty list of records")
    names = cols or list(records[0].keys())
    for c in names:
        if c not in records[0]:
            raise ValueError(f"column {c!r} is not in the table (columns: {list(records[0].keys())[:10]})")
    head = "| " + " | ".join(names) + " |"
    sep = "|" + "|".join("---" for _ in names) + "|"
    body = ["| " + " | ".join(_fmt_default(r.get(c)).replace("|", "/") for c in names) + " |" for r in records]
    return "\n".join([head, sep] + body)


def _resolve(match: re.Match, results: dict[str, Any], cfg_dict: dict[str, Any]) -> tuple[bool, str, str | None, str]:
    """(ok, text, result_name, note) for one placeholder match."""
    is_table, path, arg = match.group(1), match.group(2), match.group(3)
    segs = path.split(".")
    name, rest = segs[0], segs[1:]
    if name == "config":
        root = cfg_dict
    elif name in results:
        root = results[name]
    else:
        return False, "", name, f"no results file for {name!r} with the chosen tag (available: {sorted(results)[:10]})"
    ok, val, why = _walk(root, rest)
    if not ok:
        return False, "", name, why
    try:
        if is_table:
            cols = None
            if arg:
                if not arg.startswith("cols="):
                    raise ValueError("a table placeholder accepts only |cols=a,b,c")
                cols = [c.strip() for c in arg[5:].split(",") if c.strip()]
            return True, _table(val, cols), name, "table"
        if isinstance(val, (dict, list)):
            return False, "", name, "points to a table or list, not a single value: address one element or use {{table:...}}"
        return True, _fmt_value(val, arg), name, "n/a (null in the result)" if val is None else ""
    except (ValueError, TypeError) as e:
        return False, "", name, str(e)


# ---------------------------------------------------------------------------------------------
# Typed numbers
# ---------------------------------------------------------------------------------------------
_NUM = re.compile(r"(?<![A-Za-z_\d.])-?\d+(?:[.,]\d+)?%?(?![A-Za-z_\d])")


def _find_typed_numbers(text: str) -> list[tuple[int, str]]:
    """(line number, number text) for digits typed outside placeholders, code, comments and identifiers."""
    out: list[tuple[int, str]] = []
    in_code = False
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or _NUMBERS_OK in line or re.fullmatch(r"[|:\-\s]+", s or "-"):
            continue
        t = _PLACEHOLDER.sub(" ", line)
        t = re.sub(r"<!--.*?-->", " ", t)
        t = re.sub(r"`[^`]*`", " ", t)
        t = re.sub(r"\(?https?://\S+", " ", t)
        t = re.sub(r"\d{4}-\d{2}-\d{2}", " ", t)                 # ISO dates
        t = re.sub(r"\b(?:19|20)\d{2}\b", " ", t)                 # years
        t = re.sub(r"[A-Za-z]+-\d+", " ", t)                      # CA-1, P-2
        t = re.sub(r"^\s*#+\s*\d+(?:\.\d+)*[.)]?\s", " ", t)      # numbered headings
        t = re.sub(r"^\s*\d+[.)]\s", " ", t)                      # numbered list items
        for m in _NUM.finditer(t):
            out.append((i, m.group(0)))
    return out


# ---------------------------------------------------------------------------------------------
# Template handling
# ---------------------------------------------------------------------------------------------
def _template_path(cfg: Config, template_path: Path | None) -> Path:
    if template_path is not None:
        return Path(template_path)
    t = cfg.report.template
    return (cfg.root / t).resolve() if t else resolve_path(cfg, "report_template")


def _tag_from_cfg(cfg: Config, found: dict[str, dict[str, Path]]) -> str:
    want = str(cfg.report.results_tag)
    if want == "auto":
        return _choose_tag(found, None)
    if want not in _TAGS:
        raise ConfigError(f"report.results_tag must be auto, SYNTHETIC or real, got {want!r}")
    return want


def _placeholders(text: str) -> list[tuple[int, re.Match]]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in _PLACEHOLDER.finditer(line):
            out.append((i, m))
    return out


def claims_audit(cfg: Config) -> pd.DataFrame:
    """One row per placeholder in the template, and one per number typed outside a placeholder.

    Columns: line, kind (value, table, config, untraced_number), placeholder, result_file, key_path, resolved,
    value_preview, note. Unresolved placeholders are listed, not raised: this is the table you read before a build.
    A missing template raises ReportError.
    """
    tpl = _template_path(cfg, None)
    if not tpl.is_file():
        raise ReportError(f"report template not found: {tpl}")
    text = tpl.read_text(encoding="utf-8")
    found = _scan(cfg)
    tag = _tag_from_cfg(cfg, found)
    results = {n: _read(p, tag) for n, p in found[tag].items()}
    cfg_dict = _to_jsonable(cfg.to_dict(), "config")
    rows = []
    for line, m in _placeholders(text):
        ok, rendered, name, note = _resolve(m, results, cfg_dict)
        path = m.group(2)
        is_cfg = path.split(".")[0] == "config"
        rows.append({"line": line, "kind": "table" if m.group(1) else ("config" if is_cfg else "value"), "placeholder": m.group(0),
                     "result_file": "(config)" if is_cfg else (found[tag][name].name if name in found[tag] else None),
                     "key_path": ".".join(path.split(".")[1:]), "resolved": bool(ok),
                     "value_preview": rendered[:60].replace("\n", " ") if ok else None, "note": note})
    for line, num in _find_typed_numbers(text):
        rows.append({"line": line, "kind": "untraced_number", "placeholder": num, "result_file": None, "key_path": None,
                     "resolved": False, "value_preview": None,
                     "note": "number typed in the template: move it to a results file or the config, or mark the line <!-- numbers-ok -->"})
    return pd.DataFrame(rows, columns=["line", "kind", "placeholder", "result_file", "key_path", "resolved", "value_preview", "note"])


def render_report(cfg: Config, template_path: Path | None = None, out_path: Path | None = None) -> Path:
    """Fill the template from the results files and write the report. Returns the output path.

    The tag comes from `report.results_tag` (auto = the only tag present). The template is `template_path`, else
    `report.template`, else `paths.report_template`. The default output is `report__<tag>.md` next to the results
    folder. Every placeholder must resolve: otherwise ReportError lists them all (with line numbers) and nothing is
    written. A synthetic report starts with `dashboard.synthetic_banner`; every report ends with the result files used.
    Numbers typed into the template raise a UserWarning (see `claims_audit`).
    """
    tpl = _template_path(cfg, template_path)
    if not tpl.is_file():
        raise ReportError(f"report template not found: {tpl}")
    text = tpl.read_text(encoding="utf-8")
    found = _scan(cfg)
    tag = _tag_from_cfg(cfg, found)
    results = {n: _read(p, tag) for n, p in found[tag].items()}
    cfg_dict = _to_jsonable(cfg.to_dict(), "config")
    problems: list[str] = []
    used: set[str] = set()
    lines = text.split("\n")
    out_lines = list(lines)
    for ln, line in enumerate(lines, 1):
        def sub(m: re.Match, ln: int = ln) -> str:
            ok, rendered, name, note = _resolve(m, results, cfg_dict)
            if not ok:
                problems.append(f"line {ln}: {m.group(0)} -> {note}")
                return m.group(0)
            if name != "config":
                used.add(found[tag][name].name)
            return rendered
        out_lines[ln - 1] = _PLACEHOLDER.sub(sub, line)
    if problems:
        raise ReportError(f"{len(problems)} unresolved placeholder(s) in {tpl.name}; nothing was written:\n  " + "\n  ".join(problems))
    typed = _find_typed_numbers(text)
    if typed:
        warnings.warn(f"{len(typed)} number(s) typed in the template outside placeholders (first: line {typed[0][0]}, {typed[0][1]!r}); "
                      "see claims_audit", UserWarning, stacklevel=2)
    body = "\n".join(out_lines)
    head = f"> **{cfg.dashboard.synthetic_banner}**\n\n" if tag == "SYNTHETIC" else ""
    foot = ("\n\n---\n*Results used (" + tag + "): " + (", ".join(sorted(used)) if used else "none") + ". Settings: config.yaml, seed "
            + str(int(cfg.project.seed)) + ".*\n")
    out = Path(out_path) if out_path is not None else resolve_path(cfg, "results_dir").parent / f"report__{tag}.md"
    _atomic_write(out, head + body.rstrip("\n") + foot)
    return out


# ---------------------------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------------------------
def _cfg_with(cfg: Config, section: str, **values: Any) -> Config:
    d = cfg.to_dict()
    return Config({**d, section: {**d[section], **values}}, cfg.root)


def _demo() -> int:
    from . import StabilityResult

    cfg0 = load_config()
    print("SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS")

    def raises(exc: type, fn: Any) -> bool:
        try:
            fn()
        except exc:
            return True
        except Exception:
            return False
        return False

    root = Path(tempfile.mkdtemp(prefix="report_demo_"))
    cfg = _cfg_with(cfg0, "paths", results_dir=str(root / "results"), report_template=str(root / "template.md"))
    cfg = _cfg_with(cfg, "report", template=None, results_tag="auto")

    table = pd.DataFrame({"k": [2, 3, 4], "silhouette": [0.41, 0.5234, float("nan")], "note": [None, "ok", "skipped"]})
    stab = StabilityResult(scheme="random", level=0.2, ari=np.array([0.9, 0.95, 1.0]), survival=pd.DataFrame({"pathway": [0, 1], "survival_rate": [1.0, 0.5]}))
    p1 = save_result("k_selection", {"chosen_k": np.int64(3), "table": table, "reason": "k=3: smallest within the margin", "flag": True,
                                     "arr": np.array([1.5, np.nan]), "inf": float("inf"), "set": {"b", "a"}}, cfg, True)
    p2 = save_result("stability", stab, cfg, True)
    save_result("headline", {"ari": 0.83456, "share": 0.6149, "n": 717, "empty": None}, cfg, True)
    raw = json.loads(p1.read_text())

    template = (
        "# Pathways report\n\n"
        "The chosen k is {{k_selection.chosen_k}} ({{k_selection.reason}}).\n"
        "ARI {{headline.ari|.2f}}, share {{headline.share|.1%}}, n = {{headline.n}}, default {{headline.ari}}.\n"
        "Missing value: {{headline.empty}}. Flag: {{k_selection.flag}}. Silhouette at the second k: {{k_selection.table.1.silhouette|.3f}}.\n"
        "First level: {{stability.level|.1f}}; first ARI {{stability.ari.0}}. Visits: {{config.time.n_points}}.\n\n"
        "{{table:k_selection.table|cols=k,silhouette}}\n\n"
        "Source INT396, P0, CA-1, 2026-10-28 and year 2025 are not typed numbers.\n"
    )
    (root / "template.md").write_text(template, encoding="utf-8")
    out = render_report(cfg)
    rep = out.read_text(encoding="utf-8")

    # unresolved placeholders: all listed, nothing written, old report untouched
    bad = ("A {{nope.x}} B {{k_selection.missing}} C {{k_selection.table.9.k}} D {{k_selection.table}} E {{headline.n|.2f|x}} "
           "F {{k_selection.reason|.2f}} G {{table:headline}} H {{stability.ari.z}}\n")
    (root / "bad.md").write_text(bad, encoding="utf-8")
    out_bad = root / "bad_out.md"
    err = ""
    try:
        render_report(cfg, root / "bad.md", out_bad)
    except ReportError as e:
        err = str(e)
    prior = out.read_text(encoding="utf-8")
    try:
        render_report(cfg, root / "bad.md", out)
    except ReportError:
        pass

    # typed numbers
    (root / "typed.md").write_text("# 1. Intro\n1. first\nThe ARI was 0.83 and 40% left; k = 6.\nSee `x = 3` and https://a.b/1 .\n"
                                   "Ignore 12 here <!-- numbers-ok -->\n```\n9 9 9\n```\n| a | 7 |\n|---|---|\n", encoding="utf-8")
    typed = _find_typed_numbers((root / "typed.md").read_text())
    cfg_t = _cfg_with(cfg, "report", template=str(root / "typed.md"))
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        render_report(cfg_t, out_path=root / "typed_out.md")
    audit_t = claims_audit(cfg_t)
    audit = claims_audit(cfg)

    # tags: both present, explicit choice, real report from synthetic-only results
    p_real = save_result("headline", {"ari": 0.5}, cfg, False)
    mixed_err = raises(ConfigError, lambda: load_results(cfg))
    syn = load_results(cfg, True)
    real = load_results(cfg, False)
    cfg_syn = _cfg_with(cfg, "report", results_tag="SYNTHETIC")
    cfg_real = _cfg_with(cfg, "report", results_tag="real")
    (root / "real_t.md").write_text("ARI {{headline.ari|.2f}}.\n", encoding="utf-8")
    rep_real = render_report(cfg_real, root / "real_t.md", root / "real_out.md").read_text()
    rep_syn = render_report(cfg_syn, root / "real_t.md", root / "syn_out.md").read_text()
    only_syn_real_err = raises(ReportError, lambda: render_report(cfg_real, root / "template.md", root / "x.md"))
    leftovers = [p.name for p in (root / "results").iterdir() if p.name.endswith(".tmp")]
    p_real.unlink()
    auto_syn = load_results(cfg)
    empty_cfg = _cfg_with(cfg, "paths", results_dir=str(root / "nothing_here"), report_template=str(root / "template.md"))
    corrupt = root / "results" / "broken__SYNTHETIC.json"
    corrupt.write_text("{not json", encoding="utf-8")
    corrupt_err = raises(ReportError, lambda: load_results(cfg))
    corrupt.unlink()
    wrongtag = root / "results" / "liar__SYNTHETIC.json"
    wrongtag.write_text(json.dumps({"name": "liar", "tag": "real", "is_synthetic": False, "data": {}}), encoding="utf-8")
    wrongtag_err = raises(ReportError, lambda: load_results(cfg))
    wrongtag.unlink()

    checks = {
        "save_result: tagged file names and an envelope with name, tag and data": p1.name == "k_selection__SYNTHETIC.json" and raw["tag"] == "SYNTHETIC"
            and raw["is_synthetic"] is True and raw["name"] == "k_selection" and "data" in raw,
        "save_result: numpy, DataFrame, dataclass and set become plain JSON; NaN and infinity become null": raw["data"]["chosen_k"] == 3
            and raw["data"]["table"][2]["silhouette"] is None and raw["data"]["table"][0]["k"] == 2 and raw["data"]["arr"] == [1.5, None]
            and raw["data"]["inf"] is None and raw["data"]["set"] == ["a", "b"] and json.loads(p2.read_text())["data"]["ari"] == [0.9, 0.95, 1.0]
            and json.loads(p2.read_text())["data"]["survival"][1]["survival_rate"] == 0.5,
        "save_result: strict JSON (no NaN tokens), atomic (no temporary files left)": "NaN" not in p1.read_text() and not leftovers,
        "save_result rejects bad names and objects JSON cannot hold": all(raises(ValueError, lambda n=n: save_result(n, {}, cfg, True)) for n in ("../x", "a b", "", "config"))
            and raises(TypeError, lambda: save_result("bad", {"f": lambda: 1}, cfg, True)) and raises(TypeError, lambda: save_result("bad", b"bytes", cfg, True))
            and raises(TypeError, lambda: save_result("bad", {(1, 2): 3}, cfg, True)),
        "load_results: tags are separate, both present without a choice stops, one present is used automatically": mixed_err and set(syn) == {"k_selection", "stability", "headline"}
            and real == {"headline": {"ari": 0.5}} and set(auto_syn) == set(syn) and load_results(empty_cfg) == {},
        "load_results rejects unreadable files and files whose tag disagrees with their name": corrupt_err and wrongtag_err,
        "render: values, formats, table, config, null shown as n/a, booleans as yes/no": "chosen k is 3 (k=3: smallest within the margin)" in rep
            and "ARI 0.83, share 61.5%, n = 717, default 0.8346" in rep and "Missing value: n/a. Flag: yes. Silhouette at the second k: 0.523." in rep
            and "First level: 0.2; first ARI 0.9. Visits: 4." in rep and "| k | silhouette |\n|---|---|\n| 2 | 0.41 |\n| 3 | 0.5234 |\n| 4 | n/a |" in rep,
        "render: synthetic report opens with the required warning and ends with the files used": rep.startswith("> **SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS**") and "Results used (SYNTHETIC): headline__SYNTHETIC.json, k_selection__SYNTHETIC.json, stability__SYNTHETIC.json" in rep
            and out.name == "report__SYNTHETIC.md" and "{{" not in rep,
        "render: every unresolved placeholder is reported with its line, in one error, and nothing is written": "8 unresolved" in err and "line 1:" in err
            and all(s in err for s in ("{{nope.x}}", "{{k_selection.missing}}", "out of range", "single value", "not a single value", "{{table:headline}}", "{{stability.ari.z}}"))
            and not out_bad.exists() and out.read_text(encoding="utf-8") == prior,
        "typed numbers: digits outside placeholders are found (also in a table cell); ids, years, dates, headings, list numbers, code, comments and separator rows are not": [n for _, n in typed] == ["0.83", "40%", "6", "7"]
            and not any(n in ("1", "12", "9", "3") for _, n in typed),
        "typed numbers raise a UserWarning at render time but do not stop the build": any(issubclass(x.category, UserWarning) and "typed in the template" in str(x.message) for x in w)
            and (root / "typed_out.md").exists(),
        "claims_audit: one row per placeholder with file, key and resolution; typed numbers flagged": len(audit) == 13 and audit["resolved"].all() and set(audit["kind"]) == {"value", "table", "config"}
            and audit.loc[audit["placeholder"] == "{{headline.ari|.2f}}", "result_file"].iloc[0] == "headline__SYNTHETIC.json"
            and audit.loc[audit["kind"] == "config", "result_file"].iloc[0] == "(config)" and (audit_t["kind"] == "untraced_number").sum() == 4,
        "tags are never mixed: a real report reads only real results, a synthetic one only synthetic": "ARI 0.50" in rep_real and not rep_real.startswith("> **SYNTHETIC")
            and rep_real.endswith("headline__real.json. Settings: config.yaml, seed 2026.*\n") and "ARI 0.83" in rep_syn and "Results used (SYNTHETIC)" in rep_syn
            and only_syn_real_err,
        "missing template raises ReportError": raises(ReportError, lambda: render_report(cfg, root / "no_such_template.md")) and raises(ReportError, lambda: claims_audit(_cfg_with(cfg, "report", template=str(root / "no.md")))),
        "bad results_tag is refused": raises(ConfigError, lambda: render_report(_cfg_with(cfg, "report", results_tag="both"), root / "real_t.md", root / "y.md")),
    }
    for name, ok in checks.items():
        print(f"  demo check [{'ok' if ok else 'FAILED'}]: {name}")
    if not all(checks.values()):
        print("--- rendered report ---\n" + rep + "\n--- error ---\n" + err + f"\n--- typed --- {typed}\n--- audit rows --- {len(audit)}")
        return 1
    print(f"Demo checks passed ({len(checks)}). All data above is SYNTHETIC or hand-built (files in {root}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
