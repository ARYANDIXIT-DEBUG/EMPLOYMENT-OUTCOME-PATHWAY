# VIVA_GUIDE.md: Employment Outcome Pathway Grouping After Skilling (INT396 CA-1, G24)

How to use these notes. Each answer says why before what, and says where the evidence lives so you can open it instead of recalling it. Do not quote a number from memory: read it from `reports/report__<tag>.md` or the dashboard on the day. Everything produced so far is from SYNTHETIC data (pipeline testing). If the real-data gate is still open when you present (it is open in this release), say so first, and present the method and the tests, not findings.

## The 60-second version

Trainees move between employment states over a few survey visits. I group them by the shape of that movement (k-medoids on a sequence distance), choose the number of groups by a rule fixed in advance, and then test whether the groups say anything that a plain "employed or not" split does not, and whether they survive losing trainees or visits. The pipeline refuses to run on real data until an audit shows the files really contain the same person at more than one time point, because without that there are no trajectories to cluster.

## Questions you should expect, and answers

### Why does the real-data gate exist?
The Periodic Labour Force Survey (PLFS) is mostly a set of cross-sectional files. A person appears at more than one time point only in the rotational panel, and only if the release carries a verified linking key. Stacking cross-sectional files and calling the rows trajectories would invent pathways. So the first deliverable is an audit, `src/data_audit.py`, that reports linkage facts and nothing else. Evidence: `README.md`, `DATASET_SETUP.md`, the gate refusal (exit code 3) of `run_pipeline.py`.

### What if the audit says there are no usable trajectories?
Then the project's question has to change, and that is a scope decision, not a coding one. Plan B is cross-sectional outcome profiles and Plan C is aggregate only. Both need a scope-change memo that you write and the instructor's approval, and the pipeline will not run them as pathways. I would say plainly that this is possible.

### Can about four visits support the word "pathway"?
Only in a limited sense. Four visits is a short window, so what is found is a short-run pattern, not a career. The report says this in its first section and in its limitations, and the dashboard repeats it. Two pathways that are identical on the first visits cannot be told apart if only those visits are kept, which the censoring study shows directly.

### Why k-medoids and not k-means?
k-means averages points in a Euclidean space. A sequence of categorical states has no meaningful average, and a mean of states is not a state. k-medoids needs only a distance, so it can use a sequence distance, and each pathway is represented by a real trainee (its medoid) that you can read and question. This is reasoning from the method, not a measured comparison.

### Why dynamic Hamming and not optimal matching?
Everyone is observed on the same visit schedule, so two sequences can be compared position by position. Optimal matching lets a state slide in time, which a fixed visit schedule does not justify. Optimal matching is implemented as a sensitivity alternative, not the default. Evidence: `src/distances.py` docstring.

### How are the substitution costs set?
From the data being clustered: two states people often move between are close, and two states that never exchange people are far. The cost is estimated once from the analysed sample and passed consistently to the matrix and the extension. The consequence to admit: the metric depends on the sample, so each stability repeat re-estimates it.

### How are missing visits handled?
A missing or lost visit is never recoded into an employment state. The primary policy compares two people only on the visits both were observed, and takes the mean cost over those. A pair with too little overlap is treated as maximally dissimilar and a warning counts how many. Because of this the distance is not a true metric (the triangle inequality can fail), so the silhouette is a description, not a test. The report repeats the whole analysis under three other policies in a sensitivity table.

### Is the missing data random?
The audit runs a small set of tests with a Bonferroni correction and writes a verdict. The honest answer is that tests on observed information can fail to find a problem, but cannot prove missing-completely-at-random and cannot rule out dependence on what is unobserved. Say that, then point to the sensitivity table.

### How did you choose k?
By a rule written down before looking at results (`clustering.k_rule` in `config.yaml`), not by the silhouette alone. A candidate k is admissible only if it is stable on subsamples, has no group below the minimum share, and wastes no medoid (two medoids at distance zero). Among admissible values the smallest k within a margin of the best silhouette is chosen. If nothing is admissible the most stable k is returned with a reason that begins "FALLBACK", and I would say that the data then do not show a clearly supported number of pathways. Evidence: the k table in the report.

### How do you know the silhouette on collapsed data is right?
Identical sequences are merged and weighted by their count. The weighted silhouette is defined so that it equals the ordinary silhouette on every individual. This is tested against a one-person-at-a-time reference and against scikit-learn in `tests/test_evaluation.py`.

### Why a baseline, and is it a fair comparison?
A grouping is worth reporting only if it says something a simple split does not. The baseline is employed or not at one reference visit. It is built from the same trajectories, so agreement with it is not independent validation, and if the reference visit is the last visit, part of the agreement is by construction. The informative numbers are what the baseline hides (how many different pathways sit inside each class) and the like-for-like silhouette on the same units with the same distance. The report states both.

### Why compare with hierarchical clustering, and what did it show?
To see whether the pathways depend on one algorithm. Read the section on the hierarchical comparison and quote what the numbers show on the day: the silhouette, the smallest group share and whether any group falls below the size rule. On the SYNTHETIC run the hierarchical partition recovered the planted groups less well than k-medoids and left groups of a few people, far below the size rule, which is a known tendency of average linkage to split off tiny groups of unusual sequences. That is a statement about synthetic data. Do not present it as a finding about real trainees unless the real run shows it.

### What does the stability study show, and what are its limits?
It repeats the whole analysis after removing trainees at random, after removing them in a way that depends on an attribute, and after keeping only the first visits. Two questions: do the same people end up grouped together (adjusted Rand index), and does each reference pathway still exist (some new medoid is close to it)? Limits to state: censoring repeats differ only through random starts, so their spread understates the uncertainty a changed sample would bring; informative loss is a stress test, not a correction for attrition bias; and none of this measures sensitivity to the choice of distance or k.

### What does passing the planted-structure tests prove?
That the code can find clear structure it was given and does not find strong evidence of structure in pure noise. It says nothing about real data, where there is no truth to score against, and the synthetic pathways are easy by design. The thresholds are loose guards, not performance claims.

### How do you avoid unfairness?
Sex, social group and religion are blocked as clustering inputs at configuration load and again at run time in the distance and collapse code. They may be shown to describe who is in each pathway, and only if the data-use assessment allows. This is a fairness check on the result, not a use of those attributes to form it. Profiling is descriptive: no tests and no causal language.

### Are survey weights used?
Not to form pathways. Counts of identical sequences are never mixed with survey weights. Weighted profiles are available only if `profiling.weighted` is true and the weights are verified; otherwise the code refuses.

### How do you know the report matches the results?
Every number in the report template is a placeholder filled from `reports/results/` by `src/report_builder.py`. A placeholder that cannot be filled stops the build with a list; nothing is left blank or guessed. `claims_audit` lists every placeholder with the file and key behind it and flags any number typed into the text. This checks that numbers come from result files, not that the sentences around them are true.

### What would you do next, and what is out of scope?
Run the audit on real files first. Then, if Plan A holds, set the baseline lock, confirm the PROPOSED defaults in `config.yaml`, and run the pipeline. Tier 2 extensions are switched off (`tier2.enabled: false`) and were not built; say that you would ask before starting any of them.

## Weak points to own before they are found

- The design is only as good as the audit result. Until the audit is run on real files, no claim about real trainees is possible.
- Several defaults are PROPOSED and unverified (listed in `README.md`). Say which you would change if the data suggested it.
- The code was verified on one combination only: Python 3.13.16, Ubuntu 24.04.5, the versions in `requirements.lock.txt`. Windows, macOS, other Python versions and older pandas were not tested; `pytest` on your machine is the first step.
- The report tables show pathway numbers, not names, by design. A name is only meaningful when it is based on the profile of a cluster found in real data, and none exists yet. The dashboard's pathway selector uses the labels `profiling.name_pathways` derives from each run's own cluster profiles; on SYNTHETIC results those describe synthetic clusters only, so do not present them as findings.
- Real data will be harder: more missing visits, noisier states, less separation. Expect lower silhouette and lower stability than the synthetic run, and say that in advance.

## A four-minute demo script

1. Open the dashboard. Point to the SYNTHETIC banner if present, then read the sentence about who the trainees are.
2. Data quality tab: the share of observed, missing and lost cells, and the verdict with its limits.
3. Choosing k tab: the admissibility rule and why a candidate was excluded.
4. Pathways tab: pick one pathway, show its medoid (a real trainee) and its composition by visit.
5. Versus the baseline tab: what the baseline hides, then the like-for-like table.
6. Stability and limits tab: the censoring row and the hierarchical comparison, then read the limits aloud.
7. Close with the gate: a real run is refused until the audit supports trajectories.

## Commands to have ready

```
python run_pipeline.py --synthetic
streamlit run dashboard/app.py
python -m pytest tests -q
python run_pipeline.py --stage audit
```
