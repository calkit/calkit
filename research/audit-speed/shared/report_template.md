# Effect of the intervention on outcome scores

## Methods

Participants were randomized to a treatment or a control condition.
Socioeconomic status (SES) was self-reported as low, middle, or high.
{missing_ses_sentence}
We fit an ordinary least squares model of outcome score on condition and
SES category, with low SES as the reference category.

## Results

1. The analysis sample comprised N = {n_analyzed} participants
   (mean age {mean_age:.1f} years).
2. Mean outcome score was {mean_outcome_treatment:.1f} in the treatment
   group and {mean_outcome_control:.1f} in the control group.
3. Adjusting for SES, treatment raised outcome scores by
   {treatment_effect:.2f} points (95% CI {treatment_ci_low:.2f} to
   {treatment_ci_high:.2f}; p = {treatment_p:.2g}).
4. Adjusting for condition, high-SES participants scored
   {ses_high_vs_low:.2f} points higher than low-SES participants
   (95% CI {ses_high_ci_low:.2f} to {ses_high_ci_high:.2f};
   p = {ses_high_p:.2g}).
5. Condition and SES together explained {r_squared_pct:.1f}% of the
   variance in outcome scores (R² = {r_squared:.3f}).

![Mean outcome by SES and condition]({figure})

*Figure 1. Mean outcome score by SES category and condition.
Error bars are 95% confidence intervals.*
