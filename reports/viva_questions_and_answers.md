# Viva questions and suggested answers

## 1. What does this study estimate?

It estimates the annual weighted CWS distribution at first visit among PLFS respondents aged 15–59 who reported formal vocational/technical training. Results are shown overall and separately for rural and urban records.

## 2. Why did the analysis change from pathways to a cross-sectional design?

The Catalogue 213 documents and current files do not validate a persistent person-link key or prove training completion happened before each revisit. A trajectory would imply a sequence of observations for the same person after training, which the evidence does not establish.

## 3. Does this measure the effect of training?

No. It describes employment status among people reporting formal vocational/technical training. There is no comparison design that identifies a causal effect, and timing relative to the CWS reference period is not known exactly.

## 4. Why include both rural and urban respondents?

The `perv1` file contains first-visit samples in both sectors, and Catalogue 213 describes annual estimates for rural and urban areas. The annual survey weight uses the documented multiplier and number of contributing quarters. Results are also stratified by sector.

## 5. What is the annual weight?

`MULT / (100 if NSS equals NSC, otherwise 200) / NO_QTR`. The rider documents the combined subsample scaling and annual `NO_QTR` adjustment. The implementation checks all components and reports the weight used.

## 6. What does b4q12 code 1 mean here?

The field asks whether vocational/technical training was received. The schedule's Block 4.1 is the formal vocational/technical training particulars block for people aged 12–59 with code 1 in Block 4 column 12. The analysis calls this the reported formal-training group, not a verified training treatment.

## 7. Why not define a post-training cohort using b4pt1q3?

That field indicates whether training was completed during the last 365 days; it does not give the exact date or establish order relative to the CWS reference week. A recent-completion subgroup could be described with that label, but it was not used here and cannot support a post-training claim.

## 8. Why were 91–98 grouped together?

Instruction Manual Vol. I §3.6.14 documents 91–98 as the broad out-of-labour-force group. Individual labels were not invented. Code 99 and blank values remain unresolved/missing, never unemployment.

## 9. Why were PAM and hierarchical clustering not run?

The validated analysis uses broad CWS as one categorical outcome. Clustering that alone would reproduce its categories rather than discover meaningful groups. Occupation and industry only apply to employed records and no profiling-variable whitelist is recorded. There is no defensible permitted feature matrix for clustering this cohort.

## 10. Can the weighted percentages be treated as population facts with known precision?

They are weighted point estimates under the rider's annual multiplier instructions. This implementation does not calculate design-based standard errors or confidence intervals, so it does not support claims about statistical significance or precision.

## 11. What does a 62.24% WPR mean?

Within the selected formal-training cohort, the annual weighted employed CWS estimate is 62.24% of the weighted cohort population. It is not the share whose jobs were caused by training.

## 12. What remains blocked?

The original longitudinal pathway analysis remains blocked by unresolved person linkage, training timing, linked weights, lost-code semantics, and profiling scope. For the revised cross-sectional work, instructor acceptance of the changed question and design-based uncertainty estimation remain before strong inferential claims or full submission readiness.
