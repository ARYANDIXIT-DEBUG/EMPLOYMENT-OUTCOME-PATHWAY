# DATA_USE_ASSESSMENT.md

Project: Employment Outcome Pathway Grouping After Skilling (INT396 CA-1, group G24, SIH26135)

**This is not legal advice, and I have not read the rider.** I cannot reach the MoSPI portal, so everything
below rests on the one-sentence description you gave me **[from you, unverified]**. The actual text of the
rider that comes with the files you download governs, not my summary of your summary. Confirm every row
with your instructor before running anything on real data, and correct this file if the rider says
something different.

### Evidence check, 2026-11-06

The official Catalogue 213 dictionary labels `b4q12_perv1` “Whether received any Vocational/Technical Training.”
That variable label establishes what the field describes; it does not state that the field may be used to select
the analysis sample. The official rider located in a PLFS July 2022–June 2023 unit-level README says:
“The unit level data of PLFS should not be specifically used for studying of any variable other than the
employment and unemployment indicators.” That is prior-release evidence, not a verified copy of the
2023–24 rider. The online Catalogue 213 related-materials listing has a README but the release-specific rider
text and an explicit selection permission have not been reviewed. Therefore use of `b4q12` solely to select
trainees is **UNRESOLVED**. Obtain the 2023–24 rider and written clarification; do not treat this note or the
variable's presence in the config as permission.

Sources: [Catalogue 213 perv1 dictionary](https://microdata.gov.in/NADA/index.php/catalog/213/data-dictionary/F4),
[Catalogue 213 related materials](https://microdata.gov.in/nada/index.php/catalog/213/related-materials),
[official PLFS 2022–23 rider](https://microdata.gov.in/nada43/index.php/catalog/210/download/2445).

---

## 1. What I am working from

Your description of the rider:

- The unit-level data should not be **specifically used to study variables other than employment and
  unemployment indicators**.
- It **lists classificatory variables**, for example age, gender, household type, religion, social group
  and household expenditure.

I read this as: employment and unemployment indicators are the subject of study, and the listed
classificatory variables are there to break those indicators down. I do **not** know whether the rider
(a) permits studying a classificatory variable's own relationship to outcomes, (b) says anything about
the training or vocational variables, or (c) says anything about redistributing unit-level or
small-cell outputs. Those are the unclear points below. **[VERIFY in the rider text]**

## 2. Rating scale

- **Permitted**: sits squarely inside "employment and unemployment indicators".
- **Unclear**: depends on rider wording I have not seen. Do not run on real data until resolved.
- **Likely outside**: the analysis studies a variable that is neither an employment indicator nor a
  listed classificatory breakdown, or studies a classificatory variable as the subject. Do not run
  without written clarification.

## 3. Assessment per planned analysis

| # | Planned analysis | Rating | Reasoning |
|---|---|---|---|
| 1 | **Clustering of employment-state sequences** (current weekly status at each visit, state-space distance, k-medoids and hierarchical) | **Permitted** | The only inputs are employment and unemployment states. This is the core of the project. |
| 2 | **Employed-versus-not baseline** and stability under attrition | **Permitted** | Same inputs: employment status. The baseline is a binary employment indicator. |
| 3 | **Identifying trainees** with the declared training variable, and restricting the sample to them | **Unclear** | The training variable is not an employment indicator and is not on the list you gave me. Using it only to *select* the sample is weaker than *studying* it, but the rider may not draw that line. Ask. |
| 4 | **Adding an attribute to the distance** (`distance.attribute_inputs`) such as age | **Unclear** | Age is on the classificatory list, but putting it inside the clustering makes it a driver of the result rather than a breakdown. Default stays empty. Protected attributes (sex, social group, religion) are blocked from clustering by this project regardless. |
| 5 | **Profiling clusters by classificatory variables** (describe each cluster's age band, sector, household type, and so on, after clustering) | **Unclear, leaning permitted** | This looks like the "breakdown of employment indicators" use the list exists for. It becomes riskier if the write-up presents the classificatory variable as an explanation rather than a description. Describe, do not explain. |
| 6 | **Profiling by sex, social group, religion** | **Unclear** | These are on the list, but they are also the most sensitive, and the project treats them as profiling-only. Report them only if your instructor confirms. Wording must say "differs by", never "caused by". |
| 7 | **Profiling by household expenditure** | **Unclear** | Listed as classificatory, but it is not an employment indicator and would be studying an economic-status variable. Treat as off until cleared. |
| 8 | **Predictor analysis** (which variables predict cluster membership or employment outcome) | **Likely outside** | It studies the relationship of non-employment variables to outcomes, which is what the rider, as you describe it, warns against. Recommended default: **do not do it** unless cleared in writing. |
| 9 | **Reporting any table or figure** that could expose small cells or unit records | **Unclear** | I have no information on redistribution or minimum cell size. The pipeline reports counts and aggregates only, never records, but a small cluster crossed with several attributes can identify individuals. Set a floor once the rider or instructor says what it should be. |

Synthetic data analyses are unaffected: the rider applies to the real files, not to data this project
generates.

## 4. What this changes in the project

- **`profiling.permitted_vars` stays `[]`** in `config.yaml` until you confirm rows 5–7. Empty means the
  profiler produces no attribute profiles at all.
- **Predictor analysis is not built** into Tier 1 unless row 8 is cleared in writing. If cleared, it
  would be an addition requested by you, not a default.
- **`distance.attribute_inputs` stays `[]`.**
- **The report template** carries a "data-use scope" paragraph that lists exactly which of rows 1–9 were
  run on real data, so the claim in the report matches what was done.
- If row 3 comes back "outside", the project cannot define trainees from the training variable. That would
  be a scope change (Plan B or C, with `docs/SCOPE_CHANGE_MEMO.md`), and I would stop and tell you.

## 5. What to ask your instructor (copy as-is)

1. "The PLFS rider says the data should not be specifically used to study variables other than employment
   and unemployment indicators. Is it acceptable to use the vocational-training variable to select the
   sample of people we study?"
2. "May we describe our employment-pathway clusters by age, sector and household type, as a breakdown?
   Which of sex, social group, religion and household expenditure may we also use that way?"
3. "Should we avoid a predictor model of cluster membership entirely?"
4. "Is there a minimum cell size or other rule for what we may show in the report and dashboard?"

## 6. Decision log (you fill this in)

| Row | Decision | Who confirmed | Date | Rider section |
|---|---|---|---|---|
| 3 |  |  |  |  |
| 4 |  |  |  |  |
| 5 |  |  |  |  |
| 6 |  |  |  |  |
| 7 |  |  |  |  |
| 8 |  |  |  |  |
| 9 |  |  |  |  |

Rows 1 and 2 are the only ones I treat as cleared without a decision, and even those assume the rider
reads the way you described it.
