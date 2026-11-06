# Employment Outcome Pathway Grouping After Skilling

INT396 Unsupervised Learning, CA-1 project. Problem statement SIH26135 (Government of Maharashtra). Group G24.

<!-- How this file works. It contains words and placeholders only. Every number below is a double-brace placeholder
     (result name, then key), filled by src/report_builder.py from reports/results/. If a number is not a
     placeholder it does not belong here. Build with:  python -m src.report_builder  (or python run_pipeline.py).
     The sentences make no claim that depends on a result's direction; they point to the numbers and say how to read them. -->

## 1. What this report asks, and what it cannot say

The question is whether the people who reported vocational training fall into a small number of recognisable employment pathways over the visits in the data, and whether that grouping tells a skilling programme more than a simple "employed or not" split does.

Who is analysed: the trainee definition used is `{{data_summary.trainee_definition}}`, and the questionnaire's support for dating the training is recorded as `{{data_summary.timing_support}}`. Unless that value is `dated`, the data do not say when the training happened relative to the visits, so the pathways below describe what trained people's employment looked like across the visits, not what happened after training. Nothing in this report is a causal claim about the effect of training.

How long a "pathway" is: each person is followed over {{config.time.n_points}} visits at most. A pattern over so few visits is a short-run pattern, not a career, and the word "pathway" is used in that limited sense throughout.

## 2. Data

The data plan is `{{data_summary.data_plan}}`. The panel holds {{data_summary.n_persons_in_panel}} people; after the eligibility rule (at least {{data_summary.min_time_points}} observed visits, where a missing or lost visit does not count) {{data_summary.n_trainees_analysed}} remain, so {{data_summary.eligibility.n_removed}} were removed by that rule. Survey weights attached: {{data_summary.weights_attached}}. Weights are never used to form the pathways; counts of people are used throughout unless a table says otherwise.

Records by kind: observed state {{data_summary.records_by_kind.state}}, unknown {{data_summary.records_by_kind.missing_or_unknown}}, lost to follow-up {{data_summary.records_by_kind.lost}}.

The list of states and the visit labels are saved in the `data_summary` result and shown in the dashboard.

## 3. Missing data

Of {{missingness.n_cells}} person-visit cells, {{missingness.cells.share_observed|.1%}} are observed, {{missingness.cells.share_missing|.1%}} are missing and {{missingness.cells.share_lost|.1%}} are lost to follow-up. A missing or lost cell is never recoded into an employment state. {{missingness.share_complete_cases|.1%}} of trainees are observed at every visit.

Dropout pattern: {{missingness.dropout.n_monotone_dropout}} trainees drop out and do not return, {{missingness.dropout.n_intermittent}} have gaps and later return, and {{missingness.dropout.n_unobserved_at_first_point}} are unobserved at the first visit.

Does missingness depend on what we can see? {{missingness.n_tests}} tests were run with a Bonferroni threshold of {{missingness.bonferroni_threshold|.4f}}. Verdict as written by the audit: {{missingness.verdict}}

Limits of that check: {{missingness.limits}}

The primary handling of missing visits is `{{missingness.primary_policy}}`: two people are compared on the visits both were observed. The analysis is repeated under the other policies in the sensitivity table later in this report.

![Missing data by visit](figures/{{figures.files.8}})

## 4. Method

Each person's visits form a sequence of states. The distance between two people is `{{data_summary.distance}}`: the mean substitution cost over the visits both were observed, with costs estimated from how often people move between each pair of states in these data (states people move between are close, states that never exchange people are far). Identical sequences are merged into one unit with a count before any matrix is built, which changes no result and keeps the matrix small.

Pathways are found with k-medoids, so every pathway is represented by the sequence of a real trainee (its medoid), not by an average that no one lives. The number of pathways is chosen by a rule fixed in advance in the configuration, not by the silhouette alone: a candidate is admissible only if it is stable on subsamples (adjusted Rand index at least {{config.clustering.k_rule.min_stability_ari}}), has no group below {{config.clustering.min_cluster_frac|.0%}} of trainees, and wastes no medoid; among admissible candidates the smallest one within {{config.clustering.k_rule.silhouette_margin}} of the best silhouette is taken.

Three comparisons guard against reading too much into the result. (a) A hierarchical method on the same distance. (b) A mandatory simple baseline: employed or not employed at one reference visit, built from the same trajectories. (c) A stability study: the whole analysis is repeated after removing trainees at random, removing them in a way that depends on an attribute, and after keeping only the first visits.

Randomness is controlled by one seed, so the same configuration gives the same files.

## 5. Results

### 5.1 How many pathways

The rule above chose k = {{k_selection.chosen_k}} from the candidates in the table below. The reason as written by the rule:

> {{k_selection.reason}}

{{table:k_selection.table|cols=k,silhouette,stability_ari_mean,min_cluster_share,n_small_clusters,n_zero_distance_medoid_pairs}}

![Choosing k](figures/{{figures.files.5}})

### 5.2 The pathways

{{clustering.k}} pathways were found among {{clustering.n_individuals}} trainees, using {{clustering.reduction.n_units_fit}} distinct sequences. The reduction decision was: {{clustering.reduction.reason}} All medoids fully observed: {{clustering.all_medoids_fully_observed}}.

{{table:profiles.profiles|cols=pathway,n_individuals,prevalence,modal_path,employed_first,employed_last,share_stable}}

The columns `employed_first` and `employed_last` are the share of the pathway's observed members in an employed state at the first and last visit; `share_stable` is the share who never change state. Cells that are missing or lost are not counted as states. The medoid of each pathway, a real trainee's sequence:

{{table:clustering.medoids|cols=pathway,size,share,n_observed}}

![Medoid sequences](figures/{{figures.files.3}})

![Pathway prevalence](figures/{{figures.files.4}})

![State shares by visit and pathway](figures/{{figures.files.1}})

Pathway names are built from the tables only (the most common first and last state and the share who never change) and are shown in the dashboard. Attribute profiling is limited to the variables listed in `profiling.permitted_vars`, which come from the data-use assessment; when that list is empty, no attribute profile is shown.

### 5.3 How well separated are they

On the {{evaluation.kmedoids.n_individuals}} trainees in the fit sample, the weighted silhouette of the k-medoids pathways is {{evaluation.kmedoids.silhouette.overall|.3f}}, and {{evaluation.kmedoids.silhouette.negative_share|.1%}} of trainees are on average closer to another pathway than to their own. The mean distance between pathway medoids divided by the mean distance within a pathway is {{evaluation.kmedoids.separation.separation_ratio|.2f}} (a descriptive ratio, not a test). The smallest pathway holds {{evaluation.kmedoids.min_cluster_share|.1%}} of trainees.

{{table:evaluation.kmedoids.silhouette.per_cluster}}

![Silhouette by pathway](figures/{{figures.files.9}})

A high silhouette shows that the groups are separated under this distance. It does not show that they are meaningful, and a low one does not show that they are not.

### 5.4 Does the pathway grouping say more than "employed or not"?

The baseline rule is: {{baseline.definition.rule}}

{{baseline.counts.n_eligible}} trainees were compared and {{baseline.counts.n_excluded}} were excluded because their state at the reference visit was unknown. Agreement between the baseline and the pathways: adjusted Rand index {{baseline.comparison.ari|.3f}}, normalised mutual information {{baseline.comparison.nmi|.3f}}. Of the uncertainty in which pathway a trainee is in, {{baseline.comparison.unexplained_pathway_entropy_share|.1%}} remains after knowing the baseline class. The number of pathways that contain both employed and not-employed trainees in meaningful share is {{baseline.comparison.n_pathways_spanning_classes}} of {{baseline.comparison.n_pathways}}.

Like for like, on the same trainees and the same distance:

| Partition | Groups | Silhouette | Smallest group share |
|---|---|---|---|
| Employed or not (baseline) | {{baseline.like_for_like.baseline.n_clusters}} | {{baseline.like_for_like.baseline.silhouette.overall|.3f}} | {{baseline.like_for_like.baseline.min_cluster_share|.1%}} |
| k-medoids with the baseline's number of groups | {{baseline.like_for_like.clustering_same_k_as_baseline.n_clusters}} | {{baseline.like_for_like.clustering_same_k_as_baseline.silhouette.overall|.3f}} | {{baseline.like_for_like.clustering_same_k_as_baseline.min_cluster_share|.1%}} |
| The pathways | {{baseline.like_for_like.pathways_same_units.n_clusters}} | {{baseline.like_for_like.pathways_same_units.silhouette.overall|.3f}} | {{baseline.like_for_like.pathways_same_units.min_cluster_share|.1%}} |

How to read this. The baseline is not independent of the pathways: it is read from the same trajectories. The reference visit is `{{baseline.definition.reference_label}}`; when it is the last visit, part of the agreement is by construction, and the informative numbers are those about what the baseline hides, namely how many distinct pathways sit inside each baseline class and how the silhouette compares when the number of groups is held equal.

![Baseline against pathways](figures/{{figures.files.7}})

### 5.5 Comparison with hierarchical clustering

Hierarchical clustering with `{{hierarchical_comparison.linkage}}` linkage was run on the same distance with the same k. Agreement with the k-medoids pathways on the fit sample: adjusted Rand index {{hierarchical_comparison.ari_vs_kmedoids_fit_sample|.3f}}.

| Method | Silhouette | Smallest group share | Separation ratio |
|---|---|---|---|
| k-medoids | {{evaluation.kmedoids.silhouette.overall|.3f}} | {{evaluation.kmedoids.min_cluster_share|.2%}} | {{evaluation.kmedoids.separation.separation_ratio|.2f}} |
| Hierarchical | {{evaluation.hierarchical.silhouette.overall|.3f}} | {{evaluation.hierarchical.min_cluster_share|.2%}} | {{evaluation.hierarchical.separation.separation_ratio|.2f}} |

The group-size rule for admissibility is a smallest group of at least {{hierarchical_comparison.evaluation.min_cluster_frac|.0%}} of trainees. The per-group table for the hierarchical partition follows, so a group below that rule shows in the individuals column:

{{table:evaluation.hierarchical.silhouette.per_cluster}}

This comparison is reported whichever method looks better. It is a finding about method as much as about the data: when the hierarchical partition is lower on the silhouette, or leaves groups below the size rule, it is the weaker description of these data under this distance. Average linkage is known to tend to split off very small groups of unusual sequences and leave one large remainder, whereas k-medoids assigns every sequence to its nearest medoid, which tends to give groups of more even size. The numbers above, not this sentence, are the evidence.

### 5.6 Stability

Each setting was repeated {{stability.n_repeats}} times. "Survives" means some new medoid lies within {{stability.survival_max_dist|.2f}} of a reference pathway's medoid on the visits both are observed, so the threshold is the same in every repeat.

{{table:stability.curves|cols=scheme,level,level_kind,n_retained_mean,ari_mean,ari_p05,ari_min,mean_pathway_survival,min_pathway_survival}}

![Stability curves](figures/{{figures.files.6}})

Reading the table. The adjusted Rand index compares each repeat with the reference pathways on the trainees that remain. Censoring repeats differ only through random starts, because the sample is fixed, so their spread understates the uncertainty a changed sample would bring. Two pathways that are identical on the first visits cannot be told apart after censoring to those visits, and a pathway that fails to survive censoring is a statement about the short window as well as about stability. Informative loss is a stress test of how far a plausible dependence of dropout on one attribute can move the pathways; it is not a correction for attrition bias.

### 5.7 Other ways of handling missing visits

{{missing_sensitivity.note}}

{{table:missing_sensitivity.table|cols=policy,is_primary,n_individuals,silhouette,min_cluster_share,ari_vs_primary_pathways}}

## 6. Limitations

- A pathway here is a short-run pattern over a few visits, not a career, and the number of visits is fixed by the survey design.
- The trainee definition is `{{data_summary.trainee_definition}}` with timing support `{{data_summary.timing_support}}`. Without dated training the results do not describe outcomes after training and are not causal.
- Pathways are descriptive groupings under one chosen distance. Another reasonable distance or number of groups could give a different, equally defensible grouping; the stability study measures sensitivity to the sample, not to these choices.
- Missing and lost visits are never recoded into employment states; the primary policy compares people on the visits both were observed, and a pair with too little overlap is treated as maximally dissimilar. The missing-data tests use observed information only and cannot rule out dependence on what is unobserved.
- The employed-or-not baseline is built from the same trajectories as the pathways, so agreement with it is not independent validation.
- Sex, social group and religion are never used to form pathways. Where they are shown, it is only to describe who is in each pathway.
- Survey weights are used only where a table says so, and only when they are verified. Pooling data across the 2025 survey redesign is not done unless a documented justification is recorded.
- Structure recovery was checked only on synthetic data made for that purpose (see the tests). That check shows the code can find clear structure it was given; it says nothing about real trainees.

## 7. Reproducibility

Seed {{run_meta.seed}}. The stages run are listed in the `run_meta` result. Versions: Python {{run_meta.versions.python}}, numpy {{run_meta.versions.numpy}}, pandas {{run_meta.versions.pandas}}, scipy {{run_meta.versions.scipy}}, scikit-learn {{run_meta.versions.scikit_learn}}, matplotlib {{run_meta.versions.matplotlib}}. The configuration used is saved beside the results as `config_snapshot.yaml`. Warnings raised during the run, by stage, are in the file `run_meta`.
