# Intervention effect on outcome scores

## Introduction

Does a randomized intervention raise outcome scores, and how do scores differ
by socioeconomic status (SES)?

## Methods

Missing SES is handled per {astra}`decisions.missing_ses`
({astra:value}`decisions.missing_ses`). Outcome is modeled with OLS on
condition and SES category; see {astra}`outputs.model_results`.

## Results

:::{astra} findings.treatment_effect
:::

:::{astra} findings.ses_gap
:::

:::{astra} outputs.outcome_by_ses
:caption: Mean outcome score by SES category and condition.
:::

The full report is {astra}`outputs.report`.
