"""Configuration loading, validation and deterministic randomness.

Why this file exists: every dataset fact and method choice lives in config.yaml, and every
module reads it through the objects here. Loading and validating in one place means a bad
setting fails at start-up with one readable message, not as a KeyError halfway through a run.

Design choices worth defending in a viva:
  * `load_config` collects every problem and raises ONE ConfigError listing all of them, so you
    fix the file in one pass instead of one error at a time.
  * The protected attributes (sex, social group, religion) are blocked from every distance and
    clustering input at three layers: here at load time (declared inputs and declared
    derivations), and again at run time through `assert_no_protected`. Limitation: only declared
    inputs and declared derivations can be caught, not an undeclared proxy such as a variable
    that happens to correlate with religion.
  * Randomness is derived from `project.seed` and a text salt through numpy's SeedSequence and
    a SHA-256 digest. Python's built-in hash() is salted per process, so it would break
    reproducibility; the digest does not.
  * Paths in the config are relative to the folder holding config.yaml and are rejected if they
    are absolute or climb out of it with "..", on Windows and POSIX alike.
  * `Config` is read-only; lists come back as fresh copies, so no module can change a setting
    by accident.

Beyond the eleven rules in docs/INTERFACES.md section 7, this file checks three internal
consistency conditions that would otherwise fail later with an index error: `time.labels` has
`time.n_points` entries, every `stability.censor_points` value lies in [1, n_points - 1], and
`clustering.medoid_min_observed` is null, "all" or an integer in [1, n_points] (v1.6).

Run the smoke demo from the project root with:  python -m src.config
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Iterator

import numpy as np
import yaml

__all__ = [
    "PROTECTED_ROLES",
    "Config",
    "ConfigError",
    "FairnessError",
    "load_config",
    "make_rng",
    "resolve_path",
    "snapshot_config",
    "assert_no_protected",
    "result_tag",
]

PROTECTED_ROLES: tuple[str, ...] = ("sex", "social_group", "religion")

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    """config.yaml is missing, malformed or breaks a validation rule."""


class FairnessError(Exception):
    """A protected attribute (or a feature derived from one) reached a distance or clustering input."""


# ---------------------------------------------------------------------------------------------
# Read-only config object
# ---------------------------------------------------------------------------------------------
def _wrap(value: Any, root: Path) -> Any:
    if isinstance(value, dict):
        return Config(value, root)
    if isinstance(value, list):
        return [_wrap(v, root) for v in value]
    return value


class Config:
    """Read-only view of config.yaml: `cfg.distance.max_n`, `cfg.get("a.b", default)`, `cfg.to_dict()`.

    `cfg.root` is the folder that holds config.yaml; every relative path is resolved against it.
    """

    __slots__ = ("_data", "_root")

    def __init__(self, data: dict[str, Any], root: Path | str) -> None:
        object.__setattr__(self, "_data", data)
        object.__setattr__(self, "_root", Path(root))

    @property
    def root(self) -> Path:
        """Folder containing config.yaml (the project root)."""
        return self._root

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            value = self._data[name]
        except KeyError:
            raise AttributeError(f"config has no key {name!r}; available keys: {sorted(self._data)}") from None
        return _wrap(value, self._root)

    def __getitem__(self, key: str) -> Any:
        return _wrap(self._data[key], self._root)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Config is read-only")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Config is read-only")

    def __reduce__(self) -> tuple[Any, ...]:
        return (Config, (self._data, str(self._root)))

    def __repr__(self) -> str:
        return f"Config(keys={sorted(self._data)})"

    def keys(self) -> list[str]:
        return list(self._data)

    def items(self) -> list[tuple[str, Any]]:
        return [(k, _wrap(v, self._root)) for k, v in self._data.items()]

    def get(self, path: str, default: Any = None) -> Any:
        """Dotted lookup, e.g. cfg.get("distance.max_n", 3000). Returns default if any step is missing."""
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return _wrap(node, self._root)

    def to_dict(self) -> dict[str, Any]:
        """A deep copy of the raw settings as plain dicts and lists."""
        return copy.deepcopy(self._data)


# ---------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------
_REQUIRED: dict[str, tuple[str, ...]] = {
    "project": ("seed", "group", "name"),
    "paths": ("raw_dir", "processed_dir", "results_dir", "figures_dir", "report_template", "docs_dir"),
    "data": (
        "plan", "scope_approved", "period", "sector_coverage", "files", "layouts",
        "design_mix_justification", "schema", "verified", "verified_note",
    ),
    "time": ("n_points", "labels", "reference_period"),
    "trainee": ("definition", "rules", "min_time_points", "timing_support", "timing_evidence"),
    "missing": ("policy", "min_overlap", "attr_handling", "sensitivity_policies"),
    "distance": (
        "name", "substitution", "indel", "attribute_inputs", "reduction",
        "max_n", "max_matrix_mb", "peak_factor", "block_rows",
    ),
    "baseline": (
        "reference_visit", "employed_states", "unknown_treatment", "sample_rule",
        "locked", "change_log", "sensitivity_variants_def",
    ),
    "clustering": (
        "k_candidates", "primary", "comparison", "linkage", "n_init", "max_iter",
        "medoid_min_observed", "min_cluster_frac", "k_rule", "k_stability_repeats", "feature_inputs",
    ),
    "evaluation": ("feature_representation",),
    "stability": ("n_repeats", "random_loss", "informative", "censor_points", "survival_max_dist"),
    "profiling": ("permitted_vars", "weighted"),
    "synthetic": ("n", "planted", "noise", "missing_rate"),
    "dashboard": ("title", "synthetic_banner"),
    "report": ("template", "results_tag"),
    "tier2": ("enabled",),
}
_REQUIRED_SCHEMA_KEYS = (
    "person_id", "household_id", "visit", "month", "sector", "age", "sex", "social_group",
    "religion", "weight", "status_col", "nonresponse_col", "training_cols",
)
_DISTANCE_NAMES = ("hamming", "dynamic_hamming", "optimal_matching")
_REDUCTION_MODES = ("collapse", "subsample", "collapse_then_subsample")
_PLANS = ("UNSET", "A", "B", "C")
_TIMING = ("none", "coarse_flag", "dated")
_TRAINEE_DEFS = ("ever_trained", "recent_completion")
_UNKNOWN_TREATMENT = ("exclude", "category")


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_relative_path(p: Any) -> bool:
    """True for a non-empty relative path that does not climb out with '..' (Windows or POSIX)."""
    if not isinstance(p, str) or not p.strip():
        return False
    win, posix = PureWindowsPath(p), PurePosixPath(p)
    if win.is_absolute() or posix.is_absolute() or win.drive or win.root:
        return False
    if p.startswith(("/", "\\", "~")):
        return False
    return ".." not in set(win.parts) | set(posix.parts)


def _string_leaves(obj: Any) -> Iterator[str]:
    """Every string anywhere inside a nested structure (dict keys included)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _string_leaves(k)
            yield from _string_leaves(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _string_leaves(v)


def _protected_names(data: dict[str, Any]) -> set[str]:
    """Lower-cased protected role names, their verified column names, and features derived from them."""
    schema = (data.get("data") or {}).get("schema") or {}
    names = {r.lower() for r in PROTECTED_ROLES}
    for role in PROTECTED_ROLES:
        col = schema.get(role)
        if isinstance(col, str) and col.strip():
            names.add(col.strip().lower())
    features = data.get("features") or {}
    derived: set[str] = set()
    changed = True
    while changed:  # a feature derived from a protected-derived feature is protected-derived too
        changed = False
        for fname, spec in features.items():
            if fname.lower() in derived or not isinstance(spec, dict):
                continue
            sources = {str(s).lower() for s in (spec.get("derived_from") or [])}
            if sources & (names | derived):
                derived.add(fname.lower())
                changed = True
    return names | derived


def _validate(data: Any) -> list[str]:
    """Return every rule violation found (empty list means the config is valid)."""
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["config.yaml must contain a mapping at the top level"]

    # Rule 1: required sections and keys, relative paths
    for section, keys in _REQUIRED.items():
        node = data.get(section)
        if not isinstance(node, dict):
            errs.append(f"missing or malformed section '{section}'")
            continue
        for k in keys:
            if k not in node:
                errs.append(f"missing key '{section}.{k}'")
    for top, kind in (("states", list), ("unknown_codes", list), ("lost_codes", list), ("features", dict)):
        if not isinstance(data.get(top), kind):
            errs.append(f"'{top}' must be a {kind.__name__}")
    schema = (data.get("data") or {}).get("schema")
    if not isinstance(schema, dict):
        errs.append("'data.schema' must be a mapping")
        schema = {}
    else:
        for k in _REQUIRED_SCHEMA_KEYS:
            if k not in schema:
                errs.append(f"missing key 'data.schema.{k}'")
    if errs:  # structural problems make the value checks below meaningless
        return errs

    if not _is_int(data["project"]["seed"]):
        errs.append("project.seed must be an integer")
    for key, rel in data["paths"].items():
        if not _is_relative_path(rel):
            errs.append(f"paths.{key} must be a relative path that stays inside the project, got {rel!r}")
    files = data["data"]["files"]
    if not isinstance(files, list):
        errs.append("data.files must be a list")
        files = []
    for i, entry in enumerate(files):
        if not isinstance(entry, dict) or not _is_relative_path(entry.get("path")):
            errs.append(f"data.files[{i}].path must be a relative path that stays inside the project")

    # Rule 2: states
    states = data["states"]
    if not 5 <= len(states) <= 7:
        errs.append(f"states must list 5 to 7 outcome states, found {len(states)}")
    owners: dict[str, str] = {}
    names: list[str] = []

    def claim(code: Any, owner: str) -> None:
        key = str(code)
        if key in owners:
            errs.append(f"raw code {key!r} is claimed by both '{owners[key]}' and '{owner}'")
        else:
            owners[key] = owner

    for i, st in enumerate(states):
        if not (isinstance(st, dict) and isinstance(st.get("name"), str) and st["name"].strip()):
            errs.append(f"states[{i}] needs a non-empty 'name'")
            continue
        names.append(st["name"])
        codes = st.get("raw_codes")
        if not (isinstance(codes, list) and codes):
            errs.append(f"state '{st['name']}' needs a non-empty 'raw_codes' list")
            continue
        for c in codes:
            claim(c, f"state:{st['name']}")
    if len(set(names)) != len(names):
        errs.append("state names must be unique")
    for key, label in (("unknown_codes", "unknown_codes"), ("lost_codes", "lost_codes")):
        if isinstance(data[key], list):
            for c in data[key]:
                claim(c, label)

    # Rule 3: time
    t = data["time"]
    n_points = t["n_points"]
    if not _is_int(n_points) or n_points < 2:
        errs.append("time.n_points must be an integer >= 2")
        n_points = None
    if not (isinstance(t["reference_period"], str) and t["reference_period"].strip()):
        errs.append("time.reference_period must be ONE non-empty string (reference periods are never mixed)")
    if not isinstance(t["labels"], list) or (n_points is not None and len(t["labels"]) != n_points):
        errs.append("time.labels must be a list with exactly time.n_points entries")

    # Rule 4: baseline
    b = data["baseline"]
    emp = b["employed_states"]
    if not (isinstance(emp, list) and emp and all(s in names for s in emp)):
        errs.append("baseline.employed_states must be a non-empty list of declared state names")
    rv = b["reference_visit"]
    if not _is_int(rv) or (n_points is not None and not 0 <= rv <= n_points - 1):
        errs.append("baseline.reference_visit must be an integer inside [0, time.n_points - 1]")
    if b["unknown_treatment"] not in _UNKNOWN_TREATMENT:
        errs.append(f"baseline.unknown_treatment must be one of {_UNKNOWN_TREATMENT}")

    # Rule 5: distance
    d = data["distance"]
    if d["name"] not in _DISTANCE_NAMES:
        errs.append(f"distance.name must be one of {_DISTANCE_NAMES}")
    if d["reduction"] not in _REDUCTION_MODES:
        errs.append(f"distance.reduction must be one of {_REDUCTION_MODES}")
    if not (_is_int(d["max_n"]) and d["max_n"] > 0):
        errs.append("distance.max_n must be a positive integer")
    if not (_is_num(d["max_matrix_mb"]) and d["max_matrix_mb"] > 0):
        errs.append("distance.max_matrix_mb must be a positive number")
    if not (_is_num(d["peak_factor"]) and d["peak_factor"] >= 1):
        errs.append("distance.peak_factor must be a number >= 1")
    if not (_is_int(d["block_rows"]) and d["block_rows"] > 0):
        errs.append("distance.block_rows must be a positive integer")

    # Rule 6: clustering
    c = data["clustering"]
    if c["primary"] != "kmedoids":
        errs.append("clustering.primary must be 'kmedoids'")
    if c["comparison"] != "hierarchical":
        errs.append("clustering.comparison must be 'hierarchical'")
    if c["linkage"] != "average":
        errs.append("clustering.linkage must be 'average'")
    ks = c["k_candidates"]
    if not (isinstance(ks, list) and ks and all(_is_int(k) and k >= 2 for k in ks)
            and all(a < b2 for a, b2 in zip(ks, ks[1:]))):
        errs.append("clustering.k_candidates must be a strictly ascending list of integers >= 2")
    mm = c["medoid_min_observed"]
    if not (mm is None or mm == "all" or (_is_int(mm) and mm >= 1 and (n_points is None or mm <= n_points))):
        errs.append("clustering.medoid_min_observed must be null, 'all', or an integer in [1, time.n_points]")

    # Rule 7: protected attributes never reach a distance or clustering input
    protected = _protected_names(data)
    for where, value in (
        ("distance.attribute_inputs", d["attribute_inputs"]),
        ("clustering.feature_inputs", c["feature_inputs"]),
        ("evaluation.feature_representation", data["evaluation"]["feature_representation"]),
    ):
        bad = sorted({s for s in _string_leaves(value) if s.lower() in protected})
        if bad:
            errs.append(f"protected attribute(s) {bad} (or features derived from them) appear in {where}")

    # Rule 8: trainee definition and timing
    tr = data["trainee"]
    if tr["definition"] not in _TRAINEE_DEFS:
        errs.append(f"trainee.definition must be one of {_TRAINEE_DEFS}")
    if tr["timing_support"] not in _TIMING:
        errs.append(f"trainee.timing_support must be one of {_TIMING}")
    elif tr["timing_support"] != "none":
        ev = tr["timing_evidence"]
        if not (isinstance(ev, dict) and ev.get("source") and ev.get("note")):
            errs.append("trainee.timing_support is not 'none' but trainee.timing_evidence lacks 'source' and 'note'")

    # Rule 9: plan and scope approval
    dd = data["data"]
    if dd["plan"] not in _PLANS:
        errs.append(f"data.plan must be one of {_PLANS}")
    if not isinstance(dd["scope_approved"], bool):
        errs.append("data.scope_approved must be true or false")

    # Rule 10: stability levels, repeats, permitted profile variables
    s = data["stability"]
    rl = s["random_loss"]
    if not (isinstance(rl, list) and rl and all(_is_num(x) and 0 < x < 1 for x in rl)):
        errs.append("stability.random_loss must be a non-empty list of numbers strictly between 0 and 1")
    if not (_is_int(s["n_repeats"]) and s["n_repeats"] >= 1):
        errs.append("stability.n_repeats must be an integer >= 1")
    cp = s["censor_points"]
    if not (isinstance(cp, list) and all(_is_int(x) and x >= 1 and (n_points is None or x <= n_points - 1) for x in cp)):
        errs.append("stability.censor_points must be integers in [1, time.n_points - 1]")
    pv = data["profiling"]["permitted_vars"]
    if not isinstance(pv, list):
        errs.append("profiling.permitted_vars must be a list")
    else:
        for v in pv:
            if v not in schema:
                errs.append(f"profiling.permitted_vars entry {v!r} is not a role declared in data.schema")

    # Rule 11: baseline change log
    log = b["change_log"]
    if not isinstance(log, list):
        errs.append("baseline.change_log must be a list")
    else:
        for i, entry in enumerate(log):
            if not (isinstance(entry, dict) and all(entry.get(k) for k in ("date", "reason", "change"))):
                errs.append(f"baseline.change_log[{i}] needs 'date', 'reason' and 'change'")
    return errs


def _config_from_dict(data: Any, root: Path | str) -> Config:
    """Validate a settings dict and wrap it. Used by load_config and by tests."""
    errs = _validate(data)
    if errs:
        raise ConfigError("config is invalid:\n  - " + "\n  - ".join(errs))
    return Config(copy.deepcopy(data), Path(root))


def load_config(path: str | Path | None = None) -> Config:
    """Read, validate and wrap config.yaml. Raises ConfigError listing every problem found.

    With no argument it loads config.yaml from the project root (the folder above src/).
    A given relative path is taken from the current directory; the folder holding the file
    becomes cfg.root, so paths inside the config always resolve against the config's own folder.
    """
    cfg_path = Path(path) if path is not None else _DEFAULT_ROOT / "config.yaml"
    if not cfg_path.is_file():
        raise ConfigError(f"config file not found: {cfg_path}")
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{cfg_path} is not valid YAML: {exc}") from exc
    return _config_from_dict(data, cfg_path.resolve().parent)


# ---------------------------------------------------------------------------------------------
# Helpers used by every module
# ---------------------------------------------------------------------------------------------
def make_rng(cfg: Config, salt: str = "") -> np.random.Generator:
    """A reproducible generator from project.seed and a text salt (one salt per purpose).

    The same seed and salt always give the same stream; different salts give independent
    streams. The salt goes through SHA-256, not hash(), so results do not change between runs.
    """
    digest = hashlib.sha256(salt.encode("utf-8")).digest()
    entropy = [int(cfg.project.seed), int.from_bytes(digest[:8], "big"), int.from_bytes(digest[8:16], "big")]
    return np.random.default_rng(np.random.SeedSequence(entropy))


def resolve_path(cfg: Config, key: str) -> Path:
    """Absolute path for a key of cfg.paths, resolved against the project root."""
    rel = cfg.get(f"paths.{key}")
    if rel is None:
        raise ConfigError(f"unknown paths key {key!r}; available: {sorted(cfg.to_dict()['paths'])}")
    return (cfg.root / rel).resolve()


def snapshot_config(cfg: Config, out_dir: Path) -> Path:
    """Write the settings actually used to <out_dir>/config_snapshot.yaml and return that path.

    The snapshot has no timestamp, so identical settings give an identical file (comments from
    the original config.yaml are not kept).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "config_snapshot.yaml"
    with open(target, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg.to_dict(), fh, sort_keys=False, allow_unicode=True)
    return target


def assert_no_protected(columns: Iterable[str], cfg: Config, context: str) -> None:
    """Raise FairnessError if any column is a protected attribute or derived from one.

    Protected means the roles in PROTECTED_ROLES, the verified column names for them in
    data.schema, and any feature whose `derived_from` chain reaches one. `context` names the
    place the check guards (e.g. "gower_matrix"). Undeclared proxies cannot be detected.
    """
    protected = _protected_names(cfg.to_dict())
    bad = sorted({str(c) for c in columns if str(c).lower() in protected})
    if bad:
        raise FairnessError(f"protected attribute(s) {bad} may not be used as input to {context}")


def result_tag(is_synthetic: bool) -> str:
    """'SYNTHETIC' or 'real'; used in every result and figure filename."""
    return "SYNTHETIC" if is_synthetic else "real"


if __name__ == "__main__":
    import tempfile

    cfg = load_config()
    print(f"Loaded config from {cfg.root / 'config.yaml'}")
    print(f"  group={cfg.project.group}, seed={cfg.project.seed}, plan={cfg.data.plan}, "
          f"states={len(cfg.states)}, n_points={cfg.time.n_points}")
    print(f"  results dir -> {resolve_path(cfg, 'results_dir')}")

    a = make_rng(cfg, "demo").integers(0, 1000, 5).tolist()
    b = make_rng(cfg, "demo").integers(0, 1000, 5).tolist()
    c = make_rng(cfg, "other").integers(0, 1000, 5).tolist()
    print(f"  same salt reproducible: {a == b}; different salt differs: {a != c}")

    with tempfile.TemporaryDirectory() as tmp:
        snap = snapshot_config(cfg, Path(tmp))
        print(f"  snapshot written: {snap.name}, {snap.stat().st_size} bytes")

    base = cfg.to_dict()
    def tampered(mutate):
        d = copy.deepcopy(base)
        mutate(d)
        return d
    cases = {
        "protected attribute in distance inputs": lambda d: d["distance"].update(attribute_inputs=["religion"]),
        "timing claimed without evidence": lambda d: d["trainee"].update(timing_support="dated"),
        "only four states": lambda d: d.update(states=d["states"][:4]),
        "absolute path": lambda d: d["paths"].update(raw_dir="/data/raw"),
        "medoid_min_observed above n_points": lambda d: d["clustering"].update(medoid_min_observed=99),
    }
    for label, mutate in cases.items():
        try:
            _config_from_dict(tampered(mutate), cfg.root)
            print(f"  NOT REJECTED ({label})")
        except ConfigError as exc:
            print(f"  Rejected as expected ({label}): {str(exc).splitlines()[1].strip()}")
    try:
        assert_no_protected(["age", "religion"], cfg, "demo guard")
    except FairnessError as exc:
        print(f"  Runtime guard rejected as expected: {exc}")
