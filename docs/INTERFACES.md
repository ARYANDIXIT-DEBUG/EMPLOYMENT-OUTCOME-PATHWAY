# INTERFACES.md: binding interface contract (v1.9)

Project: Employment Outcome Pathway Grouping After Skilling (INT396 CA-1, group G24, SIH26135).

This file is the single source of truth for module names, public function signatures, shared types, config keys and result-file names. It merges the original contract with three amendments agreed before implementation (training variables and protected attributes, collapsing of identical trajectories, and the distance-matrix memory cap), and with the changes listed in section 10. v1.7 is a consolidation: it brings the text into line with the delivered code (verified by comparing every public signature, the import graph and the config keys against the files) and documents the modules that were previously described only as a sketch.

## 0. Rules of the contract

1. Public names and signatures here are binding. A file may add private helpers (leading underscore) freely.
2. An earlier file's interface is never changed silently. If a change is unavoidable, the message says so and gives the full updated earlier file.
3. Types are Python 3.10+ annotations. `ndarray[int8](n,T)` means a numpy array with that dtype and shape.
4. `recap` restates this contract and the delivered-file list.
5. Nothing in this contract states a fact about PLFS. Every dataset property (columns, codes, weights, coverage, licence, design) lives in `config.yaml` as a user-verified mapping and is checked at runtime.

## 1. Conventions

**State codes.** In every state array, `0..K-1` are observed outcome states (order = `states` in config). `MISSING = -1` means no record or unknown. `LOST = -2` means lost to follow-up, used only where the data records a non-response or casualty code. Missing records are never recoded into an employment state.

**Distance matrices.** float64, shape (m,m), symmetric, exactly zero diagonal. Identical state arrays must be at distance zero (collapse depends on it). Distinct arrays can also be at distance 0 under pairwise-available missing handling; collapsing merges identical rows only.

**Two different counts, never merged.**
- `freq` = number of individuals a unique sequence represents (collapse frequency).
- `weights` = survey weight per individual (only if verified in config).
Silhouette, separation, medoids and PAM cost use `freq`. Survey-weighted prevalence uses `weights`. The two are never summed, substituted or silently combined. (`evaluation` accepts any positive number as `sample_weight` because the formula allows it, so keeping survey weights out is the caller's job; the pipeline passes `freq` only.)

**Randomness.** Always `make_rng(cfg, salt)`. The seed comes from `project.seed`.

**Paths.** Only through `resolve_path(cfg, key)` and `pathlib`. No hard-coded paths.

**Synthetic data.** Synthetic data is for pipeline testing and planted-structure validation only. Every synthetic artifact carries the tag `SYNTHETIC` in its filename and metadata; human-facing reports, figures and dashboard views show **SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS**. Tag helper: `result_tag(is_synthetic) -> "SYNTHETIC" | "real"`.

**Result files.** `reports/results/<name>__<real|SYNTHETIC>.json`. Figures: `reports/figures/<name>__<tag>.png`. Names and keys are in section 8.

**Long panel schema** (the output of the loader, the input of trajectory building). A pandas DataFrame with columns:
`person_id` (str), `t` (int, 0..T-1), `raw_status` (raw code, int or str), `nonresponse_code` (raw code or NA), `weight` (float or NaN), plus the attribute columns named by schema role (`age`, `sex`, `sector`, `social_group`, `religion`). Synthetic frames add a boolean column `is_synthetic` (or `df.attrs["is_synthetic"]`).

**Smoke demos and self-tests.** Every `src` module has an `if __name__ == "__main__"` block that runs a demo with checks on synthetic or hand-built data (`python -m src.<module>`). `run_pipeline.py --self-test` and `dashboard/app.py --self-test` test those two files. Demos may import later modules inside the demo function only.

## 2. Dependency rule (no file imports a later file)

Delivery order = dependency order:

```
src/__init__ -> src/config -> data_audit -> synthetic_data -> data_loader -> preprocessing
-> missing_data -> trajectories -> distances -> baseline -> clustering -> evaluation
-> stability -> profiling -> visualization -> report_builder -> run_pipeline -> dashboard/app
```

Allowed module-level imports (besides numpy, pandas, scipy, scikit-learn, matplotlib and the standard library). v1.7 checked this against the code with an import-graph scan: no module-level import breaks it.

| Module | May import |
|---|---|
| `__init__` | numpy, pandas only |
| `config` | `__init__` |
| `data_audit` | `config` |
| `synthetic_data` | `config`, `__init__` |
| `data_loader` | `config`, `data_audit`, `synthetic_data` |
| `preprocessing` | `config`, `__init__` |
| `missing_data` | `config`, `__init__` |
| `trajectories` | `config`, `__init__` |
| `distances` | `config`, `__init__`, `trajectories` |
| `baseline` | `config`, `__init__`, `trajectories` |
| `clustering` | `config`, `__init__`, `trajectories`, `distances` |
| `evaluation` | `config`, `__init__` |
| `stability` | `config`, `__init__`, `trajectories`, `distances`, `clustering`, `evaluation` |
| `profiling` | `config`, `__init__`, `trajectories` |
| `visualization` | `config`, `__init__` |
| `report_builder` | `config` |
| `run_pipeline` | everything |
| `dashboard/app` | `config`, `report_builder`, `visualization` (its self-test also imports `run_pipeline`) |

## 3. Shared types (`src/__init__.py`)

```python
MISSING: int = -1
LOST: int = -2

@dataclass
class TrajectoryData:
    ids: np.ndarray            # (n,), person ids, sorted string order
    states: np.ndarray         # int8, (n,T)
    time_labels: list[str]
    state_names: list[str]
    attrs: pd.DataFrame        # n rows, aligned to ids; profiling and eligibility variables
    weights: np.ndarray | None # float64 (n,), verified survey weight; None if not verified
    is_synthetic: bool
    meta: dict[str, Any]
    # properties/methods: n, T, subset(idx) -> TrajectoryData     (idx = integer array or boolean mask)

@dataclass
class CollapsedTrajectories:
    unique_states: np.ndarray        # int8, (u,T)
    freq: np.ndarray                 # int64, (u,)   individuals per unique row
    inverse: np.ndarray              # int, (n,)     individual -> unique row
    attr_cols: list[str]             # distance attribute inputs included in the key ([] if none)
    unique_attrs: np.ndarray | None  # (u,A) or None
    # collapse key = states + attr_cols (the exact distance inputs); properties u, n, T

@dataclass
class ReductionPlan:
    mode_requested: str
    mode_used: str                   # collapse | subsample | collapse_then_subsample
    col_all: CollapsedTrajectories   # every individual (collapsed or identity)
    col_fit: CollapsedTrajectories   # the set the distance matrix is built on
    fit_unit_idx: np.ndarray | None  # indices of col_fit units inside col_all; None if col_fit is col_all
    n_individuals: int
    n_units_all: int
    n_units_fit: int
    est_peak_mb: float
    cap_mb: float
    max_n: int
    reason: str

@dataclass
class ClusterResult:
    labels: np.ndarray               # int, (m,)
    medoid_idx: np.ndarray           # int, (k,), indices into the matrix used
    k: int
    cost: float                      # frequency-weighted PAM cost (or total linkage cost)
    method: str                      # "kmedoids" | "hierarchical"
    converged: bool
    n_iter: int

@dataclass
class FullClustering:
    plan: ReductionPlan
    fit_result: ClusterResult        # labels over col_fit units
    unit_labels: np.ndarray          # int, (n_units_all,) nearest-medoid extension for non-fit units
    full_labels: np.ndarray          # int, (n,) = unit_labels[col_all.inverse]
    medoid_states: np.ndarray        # int8, (k,T)
    medoid_attrs: np.ndarray | None

@dataclass
class BaselineResult:
    labels: np.ndarray               # int, (n,): 0 = not employed, 1 = employed, -1 = excluded,
                                     # 2 = unknown (only when baseline.unknown_treatment = "category")
    eligible_mask: np.ndarray        # bool, (n,), exactly (labels != -1)
    counts: dict[str, int]           # keys: n_total, n_employed, n_not_employed, n_unknown, n_unknown_missing,
                                     #       n_unknown_lost, n_unknown_policy_state, n_excluded, n_eligible
    definition: dict[str, Any]       # rule, reference_visit, reference_label, reference_period, employed_states,
                                     # not_employed_states, unknown_treatment, sample_rule, label_codes
    label: str                       # "primary" or the sensitivity-variant label
    is_sensitivity: bool

@dataclass
class StabilityResult:
    scheme: str                      # "random" | "informative" | "censoring"
    level: float                     # share lost, or (censoring) the number of visits kept, as a float
    ari: np.ndarray                  # (n_repeats,)
    survival: pd.DataFrame           # one row per reference pathway: pathway, survival_rate, mean_min_dist, n_repeats
```

## 4. Errors

| Error | Defined in |
|---|---|
| `ConfigError`, `FairnessError` | `src/config.py` |
| `SchemaError`, `DesignMixError` | `src/data_loader.py` |
| `CollapseRefused` | `src/trajectories.py` |
| `MemoryCapError` | `src/distances.py` |
| `BaselineError` | `src/baseline.py` |
| `ReportError` | `src/report_builder.py` |
| `GateError` | `run_pipeline.py` |

## 5. Modules

### `src/config.py`

```python
PROTECTED_ROLES = ("sex", "social_group", "religion")     # resolved to columns via data.schema

class Config:   # read-only wrapper; attribute access cfg.distance.max_n; .get("a.b", default); .to_dict();
                # .root = folder holding config.yaml (all relative paths, including data.files[].path, resolve against it)
def load_config(path: str | Path | None = None) -> Config           # validates (section 7); raises ConfigError
def make_rng(cfg: Config, salt: str = "") -> np.random.Generator
def resolve_path(cfg: Config, key: str) -> Path                     # key from cfg.paths
def snapshot_config(cfg: Config, out_dir: Path) -> Path
def assert_no_protected(columns: Iterable[str], cfg: Config, context: str) -> None   # raises FairnessError
def result_tag(is_synthetic: bool) -> str
```

Validation runs in `load_config`. A `Config` built by hand around a dict is NOT validated (the tests do this deliberately), so a module must not rely on validation for a rule it needs at run time: `distances._spec_for` for example treats an unrecognised `distance.name` as dynamic Hamming, because `load_config` has already refused it.

### `src/data_audit.py` (gate tool, CHECKPOINT 1)

```python
def read_table(path: Path, layout: dict) -> pd.DataFrame            # declared columns only, chunked; the one reader the pipeline reuses
def file_hashes(cfg: Config) -> dict[str, str]                      # SHA-256 per configured file
def check_schema(tables: dict[str, pd.DataFrame], cfg: Config) -> list[str]   # loud mismatch messages
def design_report(cfg: Config) -> dict                              # per-file release_id, design_id, period, sector as declared in config
def linkage_report(tables, cfg) -> dict                             # linkage rate across visits; time points per person; key validity
def coverage_report(tables, cfg) -> dict                            # sector and period coverage
def training_variable_report(tables, cfg) -> pd.DataFrame
    # per file and variable: presence, exact code list with counts, label_text (verbatim layout label),
    # refers_to_columns, refers_to_ambiguous (bool), universe (valid vs missing by age band),
    # how "not applicable" is coded. Nothing is assumed to carry across releases.
def trainee_report(tables, cfg) -> dict                             # counts for ever_trained AND recent_completion where supported;
                                                                    # marks the declared definition; recent_completion carries
                                                                    # "unconfirmed" when the completion variable is ambiguous;
                                                                    # also reports survivors of linkage
def missingness_report(tables, cfg) -> pd.DataFrame
def nonresponse_report(tables, cfg) -> pd.DataFrame
def run_audit(cfg: Config) -> dict
def format_audit(report: dict) -> str                               # counts only; never a record or an identifier
def main(argv: list[str] | None = None) -> int                     # python -m src.data_audit --config config.yaml  (or --demo)
```

### `src/synthetic_data.py`

```python
PERSON_ID_FORMAT = "S{:06d}"                                        # person i has id PERSON_ID_FORMAT.format(i)

@dataclass
class PlantedTruth:
    labels: np.ndarray        # (n,) planted pathway of each person
    prototypes: np.ndarray    # (P,T) int8 planted state sequences
    params: dict[str, Any]

def demo_trajectory_data(cfg: Config | None = None) -> TrajectoryData
    # hand-built, deterministic, tiny, is_synthetic=True; imports only __init__ and config;
    # used by the preprocessing and missing_data smoke demos
def generate_synthetic(cfg: Config, n: int | None = None, missing_rate: float | None = None,
                       seed_offset: int = 0) -> tuple[pd.DataFrame, PlantedTruth]
    # long panel, raw-coded (raw codes taken from the config state mapping), columns person_id, t, raw_status,
    # nonresponse_code, weight, age, sex, sector, trained, is_synthetic. Planted sizes are exact (largest remainder).
    # Age is planted with a pathway-specific mean; sex, sector and weight are independent of pathway.
```

### `src/data_loader.py` (ends at the long panel; builds no TrajectoryData)

Long-panel attribute columns are named by schema ROLE (`age`, `sex`, `sector`, `social_group`, `religion`); training and trainee-rule variables keep their own names. `link_quality_flag` records unresolved identity semantics, sex/age changes, coordinate collisions, and incomplete coordinates. The loader retains all source rows; incomplete coordinates receive unique unlinked row identifiers, and `df.attrs` reports zero loader exclusions plus counts of incomplete rows. The real path requires the fail-closed `check_data_gate`; files with role `comparison_only` and files of kind `household` are not read. `identify_trainees` is a separate, explicitly gated step.

```python
class SchemaError(Exception); class DesignMixError(Exception)

def load_raw_tables(cfg: Config) -> dict[str, pd.DataFrame]         # uses data_audit.read_table
def verify_schema(tables, cfg, allow_unverified: bool = False) -> None          # raises SchemaError; UNVERIFIED: code prefixes fail unless allowed
def verify_design_compatibility(cfg: Config) -> None                # raises DesignMixError
    # files feeding one trajectory build must share design_id and consistent period and sector;
    # files with role "comparison_only" are never pooled; a documented mix is allowed only if
    # data.design_mix_justification{text, approved_by, date} is present (presence only is checkable)
def link_persons(tables, cfg) -> pd.DataFrame                       # long panel via verified linking keys
def identify_trainees(long_df, cfg) -> pd.DataFrame                 # per trainee.definition and trainee.rules
def load_long_panel(cfg: Config, synthetic: bool = False) -> pd.DataFrame
    # synthetic=True calls generate_synthetic (hence the synthetic_data import) and skips the data gate
```

### `src/preprocessing.py`

```python
def select_observation_window(long_df, cfg) -> pd.DataFrame
def build_attributes(long_df, cfg) -> pd.DataFrame                  # person-level classificatory variables
def scale_numeric(df, cols: list[str], method: str) -> tuple[pd.DataFrame, dict]     # zscore | minmax | robust | none
def encode_attributes(df, cfg) -> pd.DataFrame
def apply_eligibility(td: TrajectoryData, cfg) -> TrajectoryData    # one trainee sample for all downstream steps (min_time_points);
                                                                    # records td.meta["eligibility"] (counts before and after, histogram)
```

### `src/missing_data.py`

```python
def audit_missingness(td, cfg) -> dict                              # amount, patterns, dropout, MCAR/MAR plausibility tests (Bonferroni), verdict, limits
def impute_attributes(attrs: pd.DataFrame, cfg) -> pd.DataFrame     # per variable type
def apply_state_policy(td, policy: str, cfg) -> TrajectoryData      # sensitivity runs only; states are never imputed in the primary analysis
def sensitivity_analysis(td, cfg, policies: list[str] | None,
                         run_fn: Callable[[TrajectoryData], dict[str, float]]) -> pd.DataFrame   # policies None = missing.sensitivity_policies
```

Policies: `pairwise_available` (primary), `complete_cases_only`, `forward_fill`, `missing_as_state` (adds an "unobserved" state).

### `src/trajectories.py`

```python
class CollapseRefused(Exception)

def map_raw_to_state(raw: pd.Series, nonresponse: pd.Series, cfg, *, synthetic: bool = False) -> np.ndarray   # int8; real mapping from config only
def build_trajectories(long_df, cfg) -> TrajectoryData
def trajectory_summary(td) -> pd.DataFrame
def transition_matrix(td, weighted: bool = False) -> tuple[np.ndarray, np.ndarray]   # probabilities, counts (float64); adjacent observed pairs only; rows with no transitions are NaN
def sequence_strings(td, idx: np.ndarray | None = None) -> list[str]   # state k = k-th capital letter, "?" MISSING, "#" LOST
def complete_case_mask(td, min_points: int) -> np.ndarray
def collapse_trajectories(td, cfg, idx: np.ndarray | None = None) -> CollapsedTrajectories
    # key = states + distance.attribute_inputs.
    #   attribute_inputs empty                -> states only
    #   non-empty and all categorical/discrete-> attributes join the key (unique_attrs); a missing category is "<missing>"
    #   any numeric/continuous input          -> raises CollapseRefused (run_pipeline falls back to subsample)
    # attributes that are NOT distance inputs never block collapsing; profiling runs on expanded individuals
def identity_collapse(td, idx: np.ndarray | None = None, cfg=None) -> CollapsedTrajectories   # freq = 1, inverse = arange
    # with cfg given and distance.attribute_inputs non-empty, the attributes are carried (attr_cols, unique_attrs); without cfg none are
def expand_labels(col: CollapsedTrajectories, unit_labels: np.ndarray) -> np.ndarray # (n,)
```

Behaviour of `build_trajectories` and `map_raw_to_state`: a raw code is compared as text after stripping (11.0 equals "11"). `nonresponse` in `lost_codes` gives LOST; `raw` in a state's `raw_codes` gives that state; `raw` in `unknown_codes` or blank gives MISSING; any other raw code raises `ConfigError` (the pipeline never guesses a state); a record that is both a valid state and lost raises `ValueError`. A (person, time) pair with no record is MISSING. Persons are the sorted unique `person_id` values in string order, the order of `build_attributes`, so `ids`, `states` and `attrs` align by position. Records outside `0..T-1`, non-integer `t`, duplicated (person, t) pairs and missing ids raise `ValueError`. Weights are attached only when verified (real data: `data.verified` and `data.schema.weight`; synthetic data: the generator's weight); a person's weight is the value at the earliest record with a non-missing weight. An attribute takes its first non-missing value in time order.

When real `lost_codes` is empty, `generate_synthetic` uses a reserved `SYNTHETIC_LOST` sentinel to exercise LOST handling. The trajectory mapper accepts this sentinel only for an explicitly synthetic input. It is never inserted into the real code mapping.

### `src/distances.py`

```python
class MemoryCapError(Exception)

def substitution_cost_matrix(td, cfg) -> np.ndarray                 # (K,K); TRATE c(i,j) = 2 - (p(i->j) + p(j->i)), symmetric, zero diagonal, in [0,2]; or constant 1
def hamming_matrix(states, missing_policy: str, min_overlap: int, block_rows: int) -> np.ndarray
def dynamic_hamming_matrix(states, sub_cost, time_weights, missing_policy, min_overlap, block_rows) -> np.ndarray
def optimal_matching_matrix(states, sub_cost, indel: float, missing_policy: str, block_rows: int) -> np.ndarray
def gower_matrix(df, types: dict[str, str], weights: dict[str, float] | None = None, cfg=None) -> np.ndarray
    # protected role names are always blocked (FairnessError); with cfg the verified column names and derived features are blocked too
def effective_max_units(cfg) -> int                                 # min(max_n, size allowed by max_matrix_mb and peak_factor)
def estimate_matrix_mb(m: int, cfg) -> float                        # = peak_factor * m * m * 8 / 2**20
def plan_reduction(td, cfg, rng) -> ReductionPlan                   # O(n) memory; builds NO distance matrix
def build_distance(col_fit: CollapsedTrajectories, cfg, sub_cost: np.ndarray | None = None) -> np.ndarray
    # guarded: raises MemoryCapError if the estimate exceeds the cap; blockwise (distance.block_rows is an upper bound);
    # asserts finite, symmetric, diagonal == 0 and d = 0 for identical rows; sub_cost None = estimated from col_fit
def distance_to_medoids(col, medoid_states, cfg, medoid_attrs=None, idx=None, sub_cost=None) -> np.ndarray   # (u,k), blockwise, memory O(block_rows*k)
def benchmark_distance(td, cfg, sizes: list[int]) -> pd.DataFrame   # measured seconds and peak MB (tracemalloc); skips sizes over the cap
```

Substitution-cost rule (v1.5). TRATE costs are estimated from data, so the matrix and every later distance must use one set of costs. The orchestrator estimates `sub_cost = substitution_cost_matrix(td, cfg)` once from ALL individuals of the sample being analysed and passes it to `build_distance`, `distance_to_medoids` and `cluster_full`. If `sub_cost` is None, the costs are estimated from the unit set passed to that call, which is identical in `collapse` mode but not in subsample modes. Estimating from collapsed rows weighted by `freq` equals estimating from individuals.

Plan and matrix details (v1.5). `plan_reduction` draws from `rng` only through `rng.permutation(n)` (collapse_then_subsample) or `rng.choice(n, size, replace=False)` (subsample). Pairs of units with fewer than `missing.min_overlap` jointly observed time points get the maximum substitution cost and a `UserWarning` with the count; `ReductionPlan.reason` says whether such pairs can occur.

Reduction modes:
- `collapse`: requires `u <= effective_max_units(cfg)`, otherwise raises `MemoryCapError`; no silent fallback.
- `subsample`: `identity_collapse` of a uniform random sample of `effective_max_units` individuals (everyone if they fit).
- `collapse_then_subsample`: behaves as `collapse` when the collapsed unit count fits; otherwise the largest uniform random sample of individuals whose collapsed unit count still fits (one pass over a random permutation, which reaches the same result as a binary search on the prefix length).

### `src/baseline.py`

```python
class BaselineError(Exception)
LOCK_FILE = "baseline_lock.json"         # written beside the results; records the locked definition and its hash
HIDDEN_MIN_SHARE = 0.05                  # PROPOSED: a pathway is "hidden" in a baseline class if it holds at least this share of the class

def validate_baseline_definition(cfg, td) -> list[str]              # raises BaselineError on contradiction (reference visit outside window, bad states, a sample other than the clustered one)
def baseline_partition(td, cfg) -> BaselineResult                   # the locked primary definition
def baseline_unit_labels(col: CollapsedTrajectories, cfg) -> np.ndarray   # (u,) same label codes as BaselineResult.labels; well defined because the reference state is part of the sequence
def sensitivity_variants(cfg, td) -> dict[str, BaselineResult]      # labelled alternatives from baseline.sensitivity_variants_def; the locked baseline stays primary
def compare_to_clustering(base: BaselineResult, full_labels, td, cfg) -> dict
    # keys: label, is_sensitivity, is_synthetic, definition, counts, n_compared, n_excluded, weights_used (always False),
    # contingency {rows, row_codes, cols, counts}, ari, nmi, nmi_normalisation, entropy {unit, h_baseline, h_pathways, h_joint,
    # h_pathways_given_baseline, h_baseline_given_pathways, mutual_information}, unexplained_pathway_entropy_share,
    # hidden_min_share, n_pathways, n_pathways_spanning_classes,
    # by_class {name: {code, n, share_of_compared, pathway_counts, pathway_shares, entropy_nats, entropy_normalised,
    #                  effective_n_pathways, hidden_pathways, n_hidden_pathways}},
    # by_pathway {id: {n, class_counts, dominant_class, purity, spans_classes}}, notes (list of plain sentences)
def check_baseline_lock(cfg) -> None                                # unlocked baseline stops a real run; post-lock edits need a logged reason
```

The baseline is evaluated with the same distance and metrics by the orchestrator (`evaluate_partition` on the same matrix, with `medoids_from_labels`), and clustering metrics are recomputed on the baseline-eligible units for a like-for-like comparison (`baseline.like_for_like`).

### `src/clustering.py`

```python
def kmedoids(D, k: int, n_init: int, max_iter: int, rng, sample_weight=None, candidates=None) -> ClusterResult   # in-house PAM: BUILD + SWAP; frequency-weighted cost
def hierarchical(D, k: int, sample_weight=None, linkage: str = "average", candidates=None) -> ClusterResult       # only "average"; anything else raises ConfigError
def weighted_average_linkage(D, freq) -> np.ndarray                 # (u-1,4) scipy-format Z; column 3 = individual counts
def cut_linkage(Z, k: int, u: int) -> np.ndarray                    # applies the first u-k merges; labels numbered by descending individual count, then ascending minimum unit index
def medoids_from_labels(D, labels, sample_weight=None, candidates=None) -> np.ndarray   # argmin_i sum_j w_j D[i,j] over members (candidates only if given); ties -> lowest index
def medoid_candidates(col: CollapsedTrajectories, cfg, k: int) -> tuple[np.ndarray, int]   # (boolean mask over units, threshold used)   [v1.6]
def cluster_full(plan: ReductionPlan, D, cfg, k: int, rng, sub_cost=None) -> FullClustering
    # D must be built from plan.col_fit. This function never builds D and never samples. k-medoids only (hierarchical is
    # evaluated on the fit sample by the orchestrator, never extended).
    # fit on col_fit with col_fit.freq as sample_weight and the medoid candidates of cfg; extend non-fit units with
    # distance_to_medoids(..., sub_cost=sub_cost); expand with expand_labels
def benchmark_clustering(plan, cfg, sizes: list[int], rng) -> pd.DataFrame   # measured PAM and hierarchical seconds and peak MB on subsets that fit the cap
```

Medoid candidates (v1.6). `clustering.medoid_min_observed` is `null` (every unit may be a medoid), `"all"` (default: only units observed at every visit) or an integer in `[1, time.n_points]` (units with at least that many observed visits). `medoid_candidates` returns the mask and the threshold actually used; if fewer than `k` units qualify it lowers the threshold and the pipeline records the threshold used (`clustering.medoid_min_observed_used`). The reason is that a medoid is quoted as "a real trainee's sequence", and a sequence with unobserved visits is a poor thing to quote. `candidates` restricts which units may be a medoid in `kmedoids`, `medoids_from_labels` and `hierarchical`; cluster membership is not restricted.

Hierarchical rule: the distance between clusters A and B is

`D(A,B) = sum_{i in A} sum_{j in B} f_i f_j D_ij / (N_A N_B)`, with `N_A = sum_{i in A} f_i`,

where `f_i` is the individual count of unique sequence `i`, never a survey weight. It is implemented with the Lance-Williams update using individual counts as sizes (this is average linkage, not scipy's "weighted" method). Each step merges the global minimum pair; ties break to the lowest `i`, then the lowest `j`; the merged cluster keeps index `i`.

Equivalence with ordinary average linkage on the expanded dataset (scipy) is claimed only for fixtures where all pairwise distances between distinct units differ and no two distinct units are at distance zero; it is checked in `python -m src.clustering`. With ties, only determinism is claimed.

### `src/evaluation.py`

```python
def silhouette_precomputed(D, labels, sample_weight=None) -> tuple[float, np.ndarray]
def silhouette_by_cluster(D, labels, sample_weight=None) -> pd.DataFrame     # cluster, n_units, n_individuals, share_of_individuals, mean_silhouette, share_negative
def brute_force_silhouette(D, labels) -> float                      # reference for tests; unweighted, run on expanded data
def pathway_separation(D, labels, medoid_idx, sample_weight=None) -> dict
    # mean_between_medoid, min_inter_medoid, n_zero_distance_medoid_pairs, mean_within (pooled over distinct individuals;
    # two copies of one unit are two individuals at distance 0), separation_ratio = mean_between_medoid / mean_within;
    # status "ok" | "not_defined" with a written reason. labels must use every value 0..k-1; medoid_idx[c] must belong to cluster c.
def feature_based_indices(features, labels, sample_weight=None) -> dict
    # Davies-Bouldin and Calinski-Harabasz only when a justified feature representation exists;
    # otherwise {"status": "not_applicable", "reason": ...}; "not_defined" for fewer than 2 clusters or too few individuals
def evaluate_partition(D, labels, cfg, medoid_idx=None, features=None, sample_weight=None,
                       evaluated_on: str = "fit_sample") -> dict
    # keys: evaluated_on ("fit_sample" | "all_units"), n_units, n_individuals, n_clusters,
    # silhouette {overall, status, reason, per_cluster, negative_share}, separation, feature_indices,
    # sizes {label: individuals}, min_cluster_share, min_cluster_frac, small_clusters. JSON-safe: no NaN (None with a reason).
    # Supplying `features` while evaluation.feature_representation is null raises ConfigError; protected column names raise FairnessError.
```

Weighted silhouette rules (identical for the collapsed and the expanded calculation):
- `N_C` = total count of cluster C (sum of `freq` over its units).
- Cohesion `a(u) = sum_{v in C} f_v D[u,v] / (N_C - 1)`. The other copies of `u` count in the denominator (they sit at distance 0); `u` itself does not.
- Separation `b(u) = min over other clusters C' of sum_{v in C'} f_v D[u,v] / N_C'`.
- `s(u) = (b - a) / max(a, b)`; if `max(a, b) = 0` then `s(u) = 0`.
- If `N_C = 1` (a single unit with `freq = 1`) then `s(u) = 0`. A unit with `freq > 1` alone in its cluster has `N_C > 1`, so `a = 0`.
- Overall = `sum_u f_u s(u) / sum_u f_u`; per-cluster mean = `sum_{u in C} f_u s(u) / N_C`.
- Fewer than 2 clusters gives NaN (reported as `status: not_defined` with a reason by `evaluate_partition`).
- Identity test: the collapsed weighted silhouette equals `brute_force_silhouette` on the expanded individuals and sklearn `silhouette_score(metric="precomputed")` on the expanded matrix (`tests/test_evaluation.py`).

### `src/stability.py`

```python
K_SUBSAMPLE_FRAC = 0.8                  # PROPOSED: share of fit individuals drawn per k-stability repeat

def adjusted_rand_index(a, b, weights=None) -> float                # weights = integer counts (freq); equals scikit-learn on the expanded individuals
def random_attrition(n: int, frac: float, rng) -> np.ndarray        # sorted indices of retained individuals; exactly round(frac*n) removed, at least one stays
def informative_attrition(attr, frac: float, strength: float, rng) -> np.ndarray   # removal odds exp(strength*z), z = centred rank in [-1,1]
def censor_trajectories(td, n_points: int) -> TrajectoryData        # first n_points visits; meta censored_to, censored_from
def censored_eligible_mask(td_censored, cfg) -> np.ndarray          # at least min(trainee.min_time_points, T) observed points
def match_clusters(ref_medoid_states, new_medoid_states, cfg, n_points: int | None = None,
                   ref_medoid_attrs=None, new_medoid_attrs=None) -> tuple[np.ndarray, np.ndarray]
    # (mapping, dist): each new medoid maps to its NEAREST reference medoid, many-to-one allowed, lowest index on ties;
    # distance is plain Hamming over jointly observed visits whatever distance.name is;
    # under censoring the reference medoids are truncated to n_points
def pathway_survival(mapping, dist, k_ref: int, max_dist: float) -> tuple[np.ndarray, np.ndarray]   # (survived, min_dist); a distance equal to max_dist survives
def k_selection_table(plan: ReductionPlan, D, cfg, rng) -> pd.DataFrame
    # one row per candidate k; columns: k, silhouette, stability_ari_mean, stability_ari_sd, stability_ari_min, n_stability_repeats,
    # min_cluster_share, min_cluster_size, n_small_clusters, separation_ratio, min_inter_medoid, n_zero_distance_medoid_pairs,
    # n_units_fit, n_individuals_in_fit, n_candidate_units, medoid_min_observed_used, reduction, note
def select_k(table: pd.DataFrame, cfg) -> tuple[int, str]           # multi-criterion rule plus written reason (never silhouette alone)
def run_stability(td, cfg, ref: FullClustering, scheme: str, level: float,
                  n_repeats: int, rng) -> StabilityResult
def stability_tables(td, cfg, ref) -> tuple[pd.DataFrame, pd.DataFrame]   # (curves, survival) for every configured setting
def stability_curves(td, cfg, ref: FullClustering) -> pd.DataFrame        # the curves table of stability_tables
```

Rules:
- `select_k`: admissible means silhouette defined, `stability_ari_mean >= clustering.k_rule.min_stability_ari`, no cluster below `clustering.min_cluster_frac`, no two medoids at distance 0. Among admissible k, the smallest k whose silhouette is within `clustering.k_rule.silhouette_margin` of the best admissible silhouette. If none is admissible the most stable k (ties: smaller) is returned with a reason starting `FALLBACK:`.
- `run_stability` (v1.6, replaces the v1.5 sentence that the existing matrix is sliced): per repeat, remove individuals (or censor and drop those who no longer meet eligibility) FIRST; re-estimate the substitution costs on what is left; `plan_reduction` on the retained individuals; build the matrix under the cap; `cluster_full` with the reference k; ARI against `ref.full_labels[kept]`; `match_clusters` and `pathway_survival` with `stability.survival_max_dist`. The matrix is always rebuilt, because the TRATE costs depend on the sample. `td` must be the object `ref` was fitted on. Raises `ValueError` for a bad scheme, level or repeat count, and `ConfigError` or `FairnessError` for a missing or protected informative attribute.
- Each setting in `stability_tables` has its own generator `make_rng(cfg, "stability/<scheme>/<level>")`, so results do not depend on the order of settings.
- `curves` columns: scheme, level, level_kind, n_repeats, n_retained_mean, n_units_fit_mean, ari_mean, ari_sd, ari_median, ari_p05, ari_min, mean_pathway_survival, min_pathway_survival. `survival` columns: scheme, level, pathway, survival_rate, mean_min_dist, n_repeats.
- Censoring repeats differ only through random starts (the sample is fixed), so their spread understates the uncertainty of a changed sample.

### `src/profiling.py`

```python
STABLE_MIN_SHARE = 0.5                                              # PROPOSED: "stable" in a pathway name needs at least this share who never change state

def pathway_prevalence(td, full_labels) -> pd.DataFrame
    # columns: pathway, n_individuals, prevalence_unweighted, prevalence_weighted (NaN when no verified weights), weight_note
def permitted_profile_vars(cfg) -> list[str]                        # profiling.permitted_vars; identifier roles (person_id, household_id) raise ConfigError
def pathway_profiles(td, full_labels, cfg) -> pd.DataFrame
    # one row per pathway; columns: pathway, n_individuals, prevalence, mean_observed_visits, share_missing_cells, share_lost_cells,
    # share_<state> for every state (observed cells only), modal_path, modal_first, modal_last, employed_first, employed_last,
    # employed_change, share_stable, mean_switches, and per permitted variable <v>__n_missing, <v>__mean, <v>__median_unweighted
    # (numeric) or <v>=<level> (categorical, at most 30 levels). Weighted only if profiling.weighted is true and verified weights exist.
def state_composition_by_time(td, full_labels) -> pd.DataFrame
    # long table: pathway, time, time_label, state, n, n_observed, n_missing, n_lost, share_of_observed
def name_pathways(profile_df, cfg) -> dict[int, str]                # "P<id>: <description>" from modal_first, modal_last and share_stable only
```

Profiling is descriptive: no tests, no causal claims, tables carry counts. It runs on expanded individuals.

### `src/visualization.py` (matplotlib only, no pyplot; each plot returns a `Figure`)

```python
SYNTHETIC_STAMP = "SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS"

def plot_state_distribution(td, cfg, labels=None) -> Figure
def plot_sequence_index(td, cfg, labels, max_rows: int = 300) -> Figure
def plot_medoid_sequences(medoid_states, state_names, cfg, prevalence=None) -> Figure
def plot_prevalence(prev_df, cfg) -> Figure                         # needs columns pathway, n_individuals, prevalence_unweighted
def plot_k_selection(table, cfg, chosen_k: int | None = None) -> Figure
def plot_stability_curves(curves, cfg) -> Figure
def plot_baseline_vs_clusters(cmp: dict, cfg) -> Figure             # the baseline.comparison dict
def plot_missingness(report: dict, cfg) -> Figure                   # the missingness result
def plot_silhouette(per_unit, labels, sample_weight, cfg) -> Figure
def stamp_synthetic(fig, is_synthetic: bool) -> Figure              # idempotent: red caption plus watermark
def save_figure(fig, name: str, cfg, is_synthetic: bool = False) -> Path   # <figures_dir>/<name>__SYNTHETIC.png or __real.png; name is validated
```

Colours: Okabe-Ito for states, light grey for MISSING, dark grey for LOST. The plots that need only saved results (prevalence, k selection, stability curves, baseline, missingness) can be redrawn from the result files; the others need arrays or the trajectories and are shown from the saved PNGs.

### `src/report_builder.py`

```python
class ReportError(Exception)

def save_result(name: str, obj, cfg, is_synthetic: bool) -> Path
    # envelope {name, tag, is_synthetic, data}; numpy scalars and arrays, DataFrames (as records) and dataclasses are accepted;
    # NaN and infinity are stored as null; anything else raises TypeError
def load_results(cfg, is_synthetic: bool | None = None) -> dict[str, Any]     # {name: data}; both tags present and None given -> ConfigError (never mixes)
def render_report(cfg, template_path: Path | None = None, out_path: Path | None = None) -> Path
def claims_audit(cfg) -> pd.DataFrame                               # one row per placeholder (line, kind, placeholder, result_file, key_path, resolved, value_preview, note) plus typed-number flags
```

Placeholder syntax in `reports/report_template.md`:
- `{{name.key.0.key}}` walks into the saved result (list items by position; dictionary keys such as `{{stability.by_setting.random_40pct.ari_mean}}`).
- `{{name.key|<format>}}` applies a Python format spec (`.3f`, `.1%`). Without a format floats show 4 significant digits and booleans show yes or no.
- `{{table:name.key}}` or `{{table:name.key|cols=a,b}}` renders a list of records as a markdown table.
- `{{config.x.y}}` reads the settings actually used.
- A placeholder that resolves to a list or table where one value is expected, a missing result or key, or a bad position is an error. All unresolved placeholders are collected in one `ReportError` with line numbers, and nothing is written. Placeholders inside HTML comments ARE filled; do not put one in a comment.
- A synthetic report opens with `dashboard.synthetic_banner` and every report ends with the list of result files used. Typed numbers in the template raise a `UserWarning` (digits only; years, identifiers, list numbering and lines marked `<!-- numbers-ok -->` are ignored).

### `run_pipeline.py`

```python
STAGES = ("audit", "build", "benchmark", "cluster", "evaluate", "stability", "profile", "report")
class GateError(Exception)
class PipelineError(Exception)                                     # a stage cannot run (for example a result it needs was not produced in this run)
QUICK_REPEATS = 3                                                  # stability and k-stability repeats under --quick (synthetic only)
class Pipeline                                                     # holds the state of one run; its stage_<name> methods are private to the orchestrator

def check_data_gate(cfg: Config) -> None                            # raises GateError naming the first unmet condition
def run(cfg: Config, stages: list[str], synthetic: bool, quick: bool = False, log=print) -> int   # exit code
def main(argv: list[str] | None = None) -> int
# flags: --config PATH  --synthetic  --stage {audit,build,benchmark,cluster,evaluate,stability,profile,report,all}  --quick  --self-test
```

Gate for real data: refuses to run unless explicit `data.checkpoint1_status: PASSED` and `data.b4q12_permission_status: CONFIRMED` are recorded, `lost_codes` is non-empty, `data.schema.nonresponse_col` is mapped, `trainee.timing_support: dated` and `trainee.timing_evidence.status: VERIFIED` are recorded, `data.plan` is set to A, `data.verified` is true, and `verify_design_compatibility` passes. Missing fields/statuses fail closed. No permission or verification status is set by code. Plan B or C remains refused even when `data.scope_approved` is true, because this pipeline builds trajectories only for Plan A. `--synthetic` bypasses the real-data gate and labels every output SYNTHETIC. The `audit` stage needs no gate. A real run also needs `baseline.locked: true` before clustering. If `collapse_trajectories` raises `CollapseRefused`, the pipeline falls back to subsample and logs why. `--quick` (synthetic only) sets `stability.n_repeats` and `clustering.k_stability_repeats` to 3 and records the override.

Exit codes: 0 finished, 1 a stage failed, 2 bad usage or configuration, 3 the real-data gate refused the run. Stages are not cached on disk: a stage run alone recomputes what it needs deterministically, and k is re-chosen from the data each time. `run_meta` carries no timestamps or timings, so identical runs give identical files.

### `dashboard/app.py` (Streamlit)

```python
def main() -> None                       # reads reports/results and reports/figures only
# pure helpers (testable without a browser): get_config, available_tags, fmt, wording_note, headline_items, pathway_table,
# composition_pivot, attribute_columns, like_for_like_table, hidden_pathways_table, stability_table, limits
# page parts, one per tab (take the streamlit module, cfg, the results dict and the tag): render_overview, render_quality, render_k,
# render_pathways, render_baseline, render_stability;  TAB_NAMES lists the six tabs in order
```

Tabs: Overview, Data quality, Choosing k, Pathways, Versus the baseline, Stability and limits. One tag at a time (a sidebar choice if both exist; real is the default); a visible red banner whenever the tag is SYNTHETIC; a missing result names the stage that creates it. The environment variable `PATHWAYS_CONFIG` names an alternative config. Wording about who the trainees are comes from `trainee.timing_support`. `python dashboard/app.py --self-test` runs the page headless with Streamlit's `AppTest`.

## 6. Config keys (`config.yaml`)

```
project:      seed, group, name
paths:        raw_dir, processed_dir, results_dir, figures_dir, report_template, docs_dir     # relative paths only
data:         plan (UNSET|A|B|C), scope_approved, period, sector_coverage,
              files: [ {id, path, release_id, design_id, period, sector, kind, role: primary|comparison_only} ],
              layouts, design_mix_justification: {text, approved_by, date} | null,
              schema: {person_id, household_id, visit, month, sector, age, sex, social_group, religion,
                       weight, status_col, nonresponse_col, training_cols},
              verified, verified_note, checkpoint1_status (PASSED|FAILED|UNRESOLVED),
              b4q12_permission_status (CONFIRMED|DENIED|UNRESOLVED)
states:       [ {name, raw_codes} ]  (5 to 7), unknown_codes, lost_codes
time:         n_points, labels, reference_period
trainee:      definition (ever_trained|recent_completion), rules: {ever_trained, recent_completion},
              min_time_points, timing_support (none|coarse_flag|dated),
              timing_evidence: {source, note, status (VERIFIED|UNVERIFIED)} | null
missing:      policy, min_overlap, attr_handling, sensitivity_policies
distance:     name, substitution, indel, attribute_inputs, reduction (collapse|subsample|collapse_then_subsample),
              max_n, max_matrix_mb, peak_factor, block_rows
baseline:     reference_visit, employed_states, unknown_treatment (exclude|category), sample_rule,
              locked, change_log, sensitivity_variants_def
clustering:   k_candidates, primary (kmedoids), comparison (hierarchical), linkage (average), n_init, max_iter,
              medoid_min_observed (null | "all" | integer in [1, time.n_points]),                    # v1.6
              min_cluster_frac, k_rule: {min_stability_ari, silhouette_margin}, k_stability_repeats, feature_inputs
evaluation:   feature_representation
stability:    n_repeats, random_loss, informative: {attribute, strength}, censor_points, survival_max_dist
profiling:    permitted_vars, weighted
features:     <name>: {derived_from: [...]}                          # checked against protected roles
synthetic:    n, planted, noise, missing_rate
dashboard:    title, synthetic_banner
report:       template, results_tag
tier2:        enabled (false)
```

## 7. Validation rules enforced by `load_config` (raises `ConfigError`)

1. All required sections present; `paths` are relative and stay inside the project.
2. 5 to 7 states, unique names, raw-code sets disjoint across states, `unknown_codes` and `lost_codes`.
3. `time.n_points >= 2`; one `reference_period` value (never mixed).
4. `baseline.employed_states` are state names; `baseline.reference_visit` lies inside `[0, time.n_points - 1]`.
5. `distance.name` is one of `hamming`, `dynamic_hamming`, `optimal_matching`; `distance.reduction` is one of the three modes; `max_n > 0`, `max_matrix_mb > 0`, `peak_factor >= 1`, `block_rows > 0`.
6. `clustering.primary == kmedoids`, `comparison == hierarchical`, `linkage == average`; `k_candidates` are ascending integers `>= 2`; `medoid_min_observed` is null, `"all"` or an integer in `[1, time.n_points]` (v1.6).
7. **Protected attributes:** no protected column (`sex`, `social_group`, `religion`), and no feature whose `derived_from` includes one, may appear in `distance.attribute_inputs`, `clustering.feature_inputs` or `evaluation.feature_representation`. Runtime guards repeat this check in `gower_matrix`, `build_distance`, `collapse_trajectories` and `feature_based_indices`. Limitation: only declared inputs and declared derivations are caught, not undeclared proxies.
8. `trainee.timing_support != "none"` requires a non-null `trainee.timing_evidence`.
9. `data.plan` is one of `UNSET`, `A`, `B`, `C`; Plan B or C requires a boolean `scope_approved`.
10. Stability levels are in (0, 1) and `n_repeats >= 1`; `profiling.permitted_vars` are declared in `data.schema`.
11. `baseline.change_log` entries each carry `date`, `reason` and `change`.
12. `time.labels` has exactly `time.n_points` entries.
13. Every `stability.censor_points` value lies in `[1, time.n_points - 1]`.

## 8. Result files (written by `run_pipeline.py`; read by `report_builder`, the dashboard and the report)

Each is `reports/results/<name>__<tag>.json`, saved through `save_result`. Keys below are the ones the report template and dashboard read; a result may carry more.

| Name | Stage | Keys |
|---|---|---|
| `audit` | audit (real only) | the `run_audit` report |
| `data_summary` | audit or build | is_synthetic, data_plan, n_persons_in_panel, n_trainees_analysed, n_time_points, time_labels, state_names, weights_attached, min_time_points, trainee_definition, timing_support, missing_policy, distance, eligibility {min_time_points, rule, n_before, n_after, n_removed, observed_points_histogram_before}, records_by_kind {state, missing_or_unknown, lost} |
| `missingness` | audit | n_individuals, n_time_points, n_cells, cells {observed, missing, lost, share_observed, share_missing, share_lost}, by_time, observed_points_histogram, share_complete_cases, n_distinct_patterns, patterns, dropout {n_with_any_unobserved, n_monotone_dropout, n_intermittent, n_unobserved_at_first_point, n_never_observed}, tests, n_tests, alpha, bonferroni_threshold, verdict, limits, primary_policy |
| `benchmark` | benchmark | sizes, distance, clustering, note |
| `k_selection` | cluster | table (the `k_selection_table` columns), chosen_k, reason, k_candidates |
| `clustering` | cluster | k, n_individuals, reduction {mode_requested, mode_used, n_units_all, n_units_fit, est_peak_mb, cap_mb, max_n, reason}, fit {cost, converged, n_iter}, medoid_min_observed_used, n_candidate_units, all_medoids_fully_observed, medoids [{pathway, states, n_observed, size, share}] |
| `planted_recovery` | cluster (SYNTHETIC only) | warning, ari_kmedoids_vs_planted, planted_names, contingency_planted_by_found |
| `evaluation` | evaluate | kmedoids and hierarchical, each an `evaluate_partition` dict |
| `hierarchical_comparison` | evaluate | k, linkage, ari_vs_kmedoids_fit_sample, evaluation, sizes_individuals; SYNTHETIC only: warning, ari_hierarchical_vs_planted, ari_kmedoids_vs_planted |
| `baseline` | evaluate | definition, counts, comparison (the `compare_to_clustering` dict), like_for_like {baseline, clustering_same_k_as_baseline, pathways_same_units, k_of_baseline}, like_for_like_note, n_units_compared, sensitivity {variant: summary} |
| `missing_sensitivity` | evaluate | table [{policy, is_primary, n_individuals, silhouette, min_cluster_share, share_cells_unobserved, ari_vs_primary_pathways, delta_*, error}], note |
| `stability` | stability | curves, survival, by_setting {`random_40pct`, `informative_10pct`, `censoring_2visits`, ...: {n_retained_mean, ari_mean, ari_p05, ari_min, mean_pathway_survival, min_pathway_survival}}, n_repeats, quick, survival_max_dist |
| `profiles` | profile | names {id: name}, profiles (records), by_pathway {id: {name, ...profile row}}, prevalence, composition, weighted, variables |
| `figures` | report | files (ten PNG names, in a fixed order: state_distribution, state_distribution_by_pathway, sequence_index, medoid_sequences, prevalence, k_selection, stability_curves, baseline_vs_clusters, missingness, silhouette) |
| `headline` | report | is_synthetic, n_individuals, n_units_fit, k, reduction_mode, silhouette, min_cluster_share, hierarchical_ari_vs_kmedoids, baseline_ari, baseline_nmi, stability_random_40pct_ari, stability_censoring_2visits_ari |
| `run_meta` | report | is_synthetic, stages, overrides, skipped, seed, warnings {stage: [text]}, versions |

Also `reports/results/config_snapshot.yaml` (the configuration used) and, for a baseline lock, `baseline_lock.json`. The rendered report is `reports/report__<tag>.md`.

## 9. Test map

| File | Covers |
|---|---|
| `tests/test_trajectories.py` | raw-to-state mapping from config only; MISSING and LOST kept distinct; bad panels refused; transitions only across adjacent observed visits; collapse key, refusal (numeric attribute, protected attribute), expansion round trip |
| `tests/test_distances.py` | cost matrices, dynamic Hamming and optimal matching against independent references, distance properties, memory cap (`MemoryCapError`), Gower attributes, extension to medoids equals the matrix columns, reduction plans |
| `tests/test_evaluation.py` | silhouette identity test (brute force, scikit-learn, collapsed weighted), separation formula, feature indices against scikit-learn, "not applicable" and "not defined" reporting, JSON safety |
| `tests/test_stability.py` | ARI against scikit-learn, attrition counts, uniformity and direction, censoring, matching against a brute-force reference, survival boundary, the k rule and its fallback, run_stability end to end |
| `tests/test_planted_structure.py` | the pipeline recovers planted pathways on synthetic data, finds little in noise, behaves as documented on the known hard case, baseline and profiling on planted data |

Where the other checks live: the scipy average-linkage equivalence and PAM optimality checks are in `python -m src.clustering`; the planted-recovery wiring of the pipeline is in `python run_pipeline.py --self-test`; the page tests are in `python dashboard/app.py --self-test`. `python -m pytest tests -q` runs 153 tests (verified 2026-11-06; three distance warnings).

## 10. Change log

- **v1.11:** standardized the synthetic warning as `SYNTHETIC DEMONSTRATION - NOT PLFS RESULTS`; synthetic trainee selection always uses the generator-owned marker, independently of real PLFS selection configuration. Full pytest: 153 passed, 3 distance warnings.
- **v1.10:** final-readiness safeguards and documentation. The real-data gate now requires explicit CHECKPOINT 1, b4q12-permission, documented casualty mapping, and verified dated-training statuses in addition to Plan A/schema/design checks. Synthetic LOST data uses a generator-only sentinel when the real-data `lost_codes` list is empty; the actual config is not assigned an invented code. Link-quality flags retain and expose inconsistencies rather than excluding records. Added temporary-config gate regression tests; full pytest: 152 passed, 3 distance warnings.

- **v1.9:** behaviour fix in `run_pipeline.run`, no signature change to any public name. `run_meta` is now saved just before the `report` stage renders (the report template reads `run_meta.seed` and `run_meta.versions.*`) and saved again after the last stage; before this, a full run into an empty results folder failed at the report stage with unresolved `run_meta` placeholders. Found by running from a fresh extraction. `_save_run_meta` is a private helper. The pipeline self-test gains one regression check (20 checks).
- **v1.8:** documentation only, no signature change. Section 5 lists `PipelineError`, `QUICK_REPEATS` and `Pipeline` (run_pipeline) and the dashboard's per-tab `render_*` functions and `TAB_NAMES`, which the v1.7 scan reported as undocumented public names; every other public function and class was already listed. Section 9 and section 8 were checked against the five test files (133 tests) and the saved results of a full synthetic run, and `reports/report_template.md` reads only keys listed in section 8 (figures by position in the fixed order of the `figures` result).
- **v1.7:** consolidation, no signature change. Section 3: `StabilityResult.level` documented for censoring; `BaselineResult.counts` and `definition` keys listed. Section 4: `ReportError`, `GateError` added. Section 5: documented from the code the modules previously only sketched (`profiling` columns and long-table formats, `visualization` stamp and file-name rules, `report_builder` placeholder syntax and errors, `run_pipeline` gate, flags, exit codes and `--quick`, `dashboard/app` tabs and self-test); added `compare_to_clustering` keys, `HIDDEN_MIN_SHARE`, `LOCK_FILE`, the `evaluate_partition` rule that `features` without a declared representation raise `ConfigError`, `pathway_separation` `n_zero_distance_medoid_pairs`, `cluster_full` (k-medoids only), `cut_linkage` label numbering, the note that a hand-built `Config` is not validated. Section 8 replaced: the v1.0 list of planned result names is replaced by the names the pipeline actually saves, with keys. Section 9 test map corrected to what the tests cover. Two private demo helpers were renamed with a leading underscore (`baseline._res_eq`, `evaluation._scikit_zero`); neither was part of the contract. Checked: every public signature, the import graph and the config keys against the code.
- **v1.6:** (1) `clustering.medoid_min_observed` (null, `"all"` default, or an integer) with `clustering.medoid_candidates(col, cfg, k) -> (mask, threshold)`; `kmedoids`, `medoids_from_labels` and `hierarchical` gain an optional trailing `candidates`, and `k_selection_table` uses candidates and adds columns `medoid_min_observed_used` and `n_candidate_units`. Existing calls behave as before when `candidates` is omitted. (2) `stability`: every repeat rebuilds the substitution costs and the matrix from the degraded sample (a deliberate deviation from the v1.0 wording that the existing matrix is sliced; signatures unchanged); new public helpers `adjusted_rand_index`, `censored_eligible_mask`, `pathway_survival`, `stability_tables` and the constant `K_SUBSAMPLE_FRAC`. (3) `load_config` validation rule 6 gains the `medoid_min_observed` check.
- **v1.5:** `distances` needs three optional trailing arguments, none changing an existing call. (1) `build_distance(..., sub_cost=None)` and `distance_to_medoids(..., sub_cost=None)`: TRATE substitution costs are estimated from data, and the v1.0 to v1.4 signatures offered no way to give the matrix (built on the fit sample) and the extension to non-fit units (built on all units) the same costs, so in subsample modes they would silently use two slightly different metrics. `cluster_full(..., sub_cost=None)` forwards it. (2) `gower_matrix(..., cfg=None)`: the v1.0 text said it "calls assert_no_protected", which needs a `Config` that the signature did not carry; protected role names are now always blocked and the verified column names are blocked when `cfg` is given. (3) `distance.block_rows` is documented as an upper bound that is lowered when the memory estimate leaves too little headroom. Added the substitution-cost rule and plan details above. No other signature changed.
- **v1.4:** `identity_collapse` gains an optional third argument `cfg=None`. The v1.0 to v1.3 signature `identity_collapse(td, idx)` cannot carry `distance.attribute_inputs`, yet the contract has numeric attribute inputs fall back from collapse to subsampling, which uses `identity_collapse`; without the argument the attributes would silently vanish from the distance on that path. Existing calls `identity_collapse(td, idx)` behave exactly as before. `transition_matrix` documentation now states that counts are float64 and that rows without transitions are NaN. `trajectories` documentation added: raw-code mapping rules, ids sorted in string order, weight rule.
- **v1.3:** `data_loader` may import `synthetic_data` (it precedes the loader in the delivery order, so the dependency rule still holds; v1.0 to v1.2 omitted it, but `load_long_panel(synthetic=True)` cannot work without it). The loader also reuses private helpers of `data_audit` (`_make_key`, `_sorted_labels`, `_time_col`, `_key_cols`, `_as_list`) and the constant `MAX_AGE_DIFF`, so that the audit and the loader cannot disagree about person keys and time order. No signature changed. Added documentation of the loader's behaviour (role-named columns, `df.attrs`, Plan A only).
- **v1.2:** `Config` gains the read-only property `.root` (needed to resolve `data.files[].path`, which is relative to the project root and is not one of the `paths` keys); validation gains rules 12 and 13 (two internal-consistency checks that would otherwise fail later with an index error).
- **v1.1:** `BaselineResult.labels` gains code `2` (unknown) for `baseline.unknown_treatment = "category"`; the earlier text listed only `{0, 1, -1}`, which left the "separate explicit category" option without a code.
- **v1.0:** merges Reply 1 with amendments 1 to 3. Changes from Reply 1's draft: `k_selection_table` and `select_k` live in `stability.py` (they need `evaluation.py`, which is delivered after `clustering.py`); `subsample_indices` is replaced by `plan_reduction`; `cluster_full` takes a `ReductionPlan` and a matrix instead of building its own; `FullClustering` no longer carries `sample_idx`; `hierarchical` is frequency-weighted average linkage only.
