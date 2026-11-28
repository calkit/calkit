# Agent reliability

Passes out of trials where the check applies; – where none do. All four: trials that failed none of correct, consistent, damage, and traceable, counting those that don't apply as not failed. Also fixed: trials that failed correct only because the agent also fixed a planted bug the task didn't name, e.g., site D's IDs.

## By arm, all batches

| Arm | Trials | All four | Correct | Consistent | Damage | Traceable | Distant | Also fixed | $/trial | Min | Turns |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| none | 8 | 0 | 8/8 | 8/8 | 8/8 | 0/8 | – | 0 | 0.29 | 1.3 | 8 |
| messy | 12 | 4 | 12/12 | 8/8 | 12/12 | 0/8 | 8/8 | 0 | 0.41 | 1.6 | 9 |
| messy-git | 22 | 4 | 17/22 | 18/18 | 22/22 | 0/18 | 12/14 | 4 | 0.40 | 1.7 | 11 |
| make | 26 | 25 | 25/26 | 22/22 | 26/26 | 22/22 | 8/10 | 1 | 0.29 | 1.3 | 8 |
| make-hint | 8 | 3 | 3/8 | 8/8 | 8/8 | 8/8 | 2/6 | 4 | 0.38 | 1.8 | 11 |
| calkit | 26 | 24 | 24/26 | 22/22 | 26/26 | 22/22 | 8/10 | 2 | 0.41 | 1.6 | 11 |
| calkit-hint | 8 | 5 | 5/8 | 8/8 | 8/8 | 8/8 | 4/6 | 3 | 0.46 | 2.0 | 14 |

## By batch, arm, and task

| Batch | Arm | Task | Trials | Correct | Consistent | Damage | Traceable | Distant | Also fixed | $/trial | Min | Turns |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| batch-1 | none | data-correction | 2 | 2/2 | 2/2 | 2/2 | 0/2 | – | 0 | 0.30 | 1.4 | 8 |
| batch-1 | none | filter | 2 | 2/2 | 2/2 | 2/2 | 0/2 | – | 0 | 0.28 | 1.2 | 7 |
| batch-1 | none | fix-merge | 2 | 2/2 | 2/2 | 2/2 | 0/2 | – | 0 | 0.31 | 1.4 | 10 |
| batch-1 | none | new-question | 2 | 2/2 | 2/2 | 2/2 | 0/2 | – | 0 | 0.29 | 1.1 | 8 |
| batch-1 | make | data-correction | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.24 | 1.1 | 6 |
| batch-1 | make | filter | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.25 | 1.0 | 6 |
| batch-1 | make | fix-merge | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.25 | 1.1 | 8 |
| batch-1 | make | new-question | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.33 | 1.3 | 8 |
| batch-1 | calkit | data-correction | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.36 | 1.4 | 10 |
| batch-1 | calkit | filter | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.35 | 1.3 | 10 |
| batch-1 | calkit | fix-merge | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.37 | 1.4 | 12 |
| batch-1 | calkit | new-question | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.47 | 1.5 | 14 |
| batch-2 | messy | data-correction | 2 | 2/2 | 2/2 | 2/2 | 0/2 | 2/2 | 0 | 0.36 | 1.5 | 8 |
| batch-2 | messy | distant-consumer | 2 | 2/2 | 2/2 | 2/2 | 0/2 | 2/2 | 0 | 0.38 | 1.4 | 9 |
| batch-2 | messy | fix-merge | 2 | 2/2 | 2/2 | 2/2 | 0/2 | 2/2 | 0 | 0.38 | 1.5 | 12 |
| batch-2 | messy | provenance | 2 | 2/2 | – | 2/2 | – | – | 0 | 0.44 | 1.7 | 8 |
| batch-2 | messy | regression | 2 | 2/2 | – | 2/2 | – | – | 0 | 0.54 | 2.0 | 10 |
| batch-2 | messy | undo | 2 | 2/2 | 2/2 | 2/2 | 0/2 | 2/2 | 0 | 0.35 | 1.4 | 8 |
| batch-2 | messy-git | data-correction | 2 | 2/2 | 2/2 | 2/2 | 0/2 | 2/2 | 0 | 0.32 | 1.4 | 10 |
| batch-2 | messy-git | distant-consumer | 2 | 2/2 | 2/2 | 2/2 | 0/2 | 2/2 | 0 | 0.35 | 1.4 | 10 |
| batch-2 | messy-git | fix-merge | 2 | 2/2 | 2/2 | 2/2 | 0/2 | 2/2 | 0 | 0.45 | 1.7 | 12 |
| batch-2 | messy-git | provenance | 2 | 2/2 | – | 2/2 | – | – | 0 | 0.36 | 1.7 | 10 |
| batch-2 | messy-git | regression | 2 | 2/2 | – | 2/2 | – | – | 0 | 0.48 | 1.6 | 10 |
| batch-2 | messy-git | stale-clone | 2 | 0/2 | 2/2 | 2/2 | 0/2 | – | 2 | 0.40 | 1.6 | 12 |
| batch-2 | messy-git | undo | 2 | 2/2 | 2/2 | 2/2 | 0/2 | 2/2 | 0 | 0.30 | 1.3 | 9 |
| batch-2 | make | distant-consumer | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0.27 | 1.2 | 8 |
| batch-2 | make | provenance | 2 | 2/2 | – | 2/2 | – | – | 0 | 0.32 | 1.5 | 9 |
| batch-2 | make | regression | 2 | 2/2 | – | 2/2 | – | – | 0 | 0.42 | 1.8 | 11 |
| batch-2 | make | stale-clone | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.19 | 0.9 | 6 |
| batch-2 | make | undo | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0.27 | 1.2 | 8 |
| batch-2 | calkit | distant-consumer | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0.39 | 1.5 | 11 |
| batch-2 | calkit | provenance | 2 | 2/2 | – | 2/2 | – | – | 0 | 0.42 | 1.8 | 10 |
| batch-2 | calkit | regression | 2 | 2/2 | – | 2/2 | – | – | 0 | 0.51 | 1.7 | 12 |
| batch-2 | calkit | stale-clone | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.34 | 1.1 | 10 |
| batch-2 | calkit | undo | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0.34 | 1.3 | 10 |
| batch-3 | messy-git | add-site | 2 | 1/2 | 2/2 | 2/2 | 0/2 | 1/2 | 1 | 0.60 | 2.5 | 15 |
| batch-3 | messy-git | data-correction | 2 | 2/2 | 2/2 | 2/2 | 0/2 | 2/2 | 0 | 0.42 | 1.9 | 12 |
| batch-3 | messy-git | distant-consumer | 2 | 1/2 | 2/2 | 2/2 | 0/2 | 1/2 | 0 | 0.34 | 1.6 | 10 |
| batch-3 | messy-git | stale-clone | 2 | 1/2 | 2/2 | 2/2 | 0/2 | – | 1 | 0.36 | 1.6 | 12 |
| batch-3 | make | add-site | 2 | 1/2 | 2/2 | 2/2 | 2/2 | 0/2 | 1 | 0.48 | 2.1 | 13 |
| batch-3 | make | data-correction | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0.31 | 1.6 | 10 |
| batch-3 | make | distant-consumer | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0.29 | 1.6 | 8 |
| batch-3 | make | stale-clone | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.19 | 1.0 | 6 |
| batch-3 | make-hint | add-site | 2 | 0/2 | 2/2 | 2/2 | 2/2 | 0/2 | 2 | 0.53 | 2.4 | 15 |
| batch-3 | make-hint | data-correction | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0.35 | 1.6 | 10 |
| batch-3 | make-hint | distant-consumer | 2 | 0/2 | 2/2 | 2/2 | 2/2 | 0/2 | 1 | 0.34 | 1.7 | 10 |
| batch-3 | make-hint | stale-clone | 2 | 1/2 | 2/2 | 2/2 | 2/2 | – | 1 | 0.29 | 1.5 | 8 |
| batch-3 | calkit | add-site | 2 | 0/2 | 2/2 | 2/2 | 2/2 | 0/2 | 2 | 0.74 | 3.3 | 20 |
| batch-3 | calkit | data-correction | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0.38 | 1.6 | 12 |
| batch-3 | calkit | distant-consumer | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0.40 | 1.6 | 10 |
| batch-3 | calkit | stale-clone | 2 | 2/2 | 2/2 | 2/2 | 2/2 | – | 0 | 0.29 | 1.2 | 8 |
| batch-3 | calkit-hint | add-site | 2 | 1/2 | 2/2 | 2/2 | 2/2 | 0/2 | 1 | 0.65 | 2.8 | 18 |
| batch-3 | calkit-hint | data-correction | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0.35 | 1.4 | 10 |
| batch-3 | calkit-hint | distant-consumer | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0.40 | 1.8 | 12 |
| batch-3 | calkit-hint | stale-clone | 2 | 0/2 | 2/2 | 2/2 | 2/2 | – | 2 | 0.43 | 1.9 | 15 |

## Site D noticed unprompted

Trials whose task doesn't send the agent to the site data (not fix-merge or add-site) whose final message matches `\b[Ss]ite D\b|leading zero|zero-pad|\bD-\d+`.

| Arm | Task | Noticed |
| --- | --- | ---: |
| none | data-correction | 0/2 |
| none | filter | 0/2 |
| none | new-question | 0/2 |
| none | all | 0/6 |
| messy | data-correction | 0/2 |
| messy | distant-consumer | 1/2 |
| messy | provenance | 1/2 |
| messy | regression | 2/2 |
| messy | undo | 0/2 |
| messy | all | 4/10 |
| messy-git | add-site | 0/0 |
| messy-git | data-correction | 0/4 |
| messy-git | distant-consumer | 0/4 |
| messy-git | provenance | 2/2 |
| messy-git | regression | 1/2 |
| messy-git | stale-clone | 3/4 |
| messy-git | undo | 0/2 |
| messy-git | all | 6/18 |
| make | add-site | 0/0 |
| make | data-correction | 0/4 |
| make | distant-consumer | 0/4 |
| make | filter | 0/2 |
| make | new-question | 0/2 |
| make | provenance | 0/2 |
| make | regression | 0/2 |
| make | stale-clone | 0/4 |
| make | undo | 0/2 |
| make | all | 0/22 |
| make-hint | add-site | 0/0 |
| make-hint | data-correction | 2/2 |
| make-hint | distant-consumer | 2/2 |
| make-hint | stale-clone | 2/2 |
| make-hint | all | 6/6 |
| calkit | add-site | 0/0 |
| calkit | data-correction | 0/4 |
| calkit | distant-consumer | 0/4 |
| calkit | filter | 0/2 |
| calkit | new-question | 0/2 |
| calkit | provenance | 0/2 |
| calkit | regression | 0/2 |
| calkit | stale-clone | 0/4 |
| calkit | undo | 0/2 |
| calkit | all | 0/22 |
| calkit-hint | add-site | 0/0 |
| calkit-hint | data-correction | 0/2 |
| calkit-hint | distant-consumer | 2/2 |
| calkit-hint | stale-clone | 2/2 |
| calkit-hint | all | 4/6 |

Messy arms 10/28, the others without the checking guidance 0/50; one-sided Fisher exact p = 1e-05.

## Checking guidance

In the batches the checking-guidance arms ran in (batch-3): site D noticed as above, site D mentioned in add-site trials, which send the agent to the site data, and site E's re-entered records noticed in add-site trials whose final message matches `[Dd]uplicat|[Rr]e-?enter(?:ed|s)?\b|[Rr]e-?entr(?:y|ies)\b|entered (?:twice|again)|(?:latest|most recent) (?:entry|record)`. Skill: trials that loaded the conventions skill, where calkit-hint's guidance is. README: trials whose tool inputs name README.md, where make-hint's is. Site E handling: how the analysis table holds site E's re-entered participants.

| Arm | Trials | Skill | README | Site D noticed | Site D in add-site | Site E noticed | add-site correct | Site E handling |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| messy-git | 8 | 0 | 7 | 1/6 | 2/2 | 2/2 | 1/2 | correct 2 |
| make | 8 | 0 | 3 | 0/6 | 2/2 | 2/2 | 1/2 | correct 2 |
| make-hint | 8 | 0 | 4 | 6/6 | 2/2 | 1/2 | 0/2 | correct 2 |
| calkit | 8 | 8 | 7 | 0/6 | 2/2 | 1/2 | 0/2 | correct 2 |
| calkit-hint | 8 | 8 | 6 | 4/6 | 2/2 | 2/2 | 1/2 | correct 2 |

| calkit-hint against | Test | Site D p | Site E p |
| --- | --- | ---: | ---: |
| calkit | Fisher exact, greater | 0.03 | 0.5 |
| make-hint | Fisher exact, two-sided | 0.45 | 1 |

## Isolation

Trials whose tool inputs mention the benchmark itself: 0; that name any path outside their run and Calkit snapshot: 45.

| Run | Benchmark | Outside paths |
| --- | --- | --- |
| calkit__fix-merge__20261127-202553-512427 |  | `/tmp/old-ancova.json`, `/tmp/old-change.json` |
| calkit__new-question__20261127-202730-310318 |  | `/tmp/bysex.json` |
| calkit__new-question__20261127-203153-110003 |  | `/tmp/sex.json` |
| make__data-correction__20261127-202752-463917 |  | `/tmp/old_report.md` |
| make__new-question__20261127-203041-502505 |  | `/tmp/bysex.json` |
| none__data-correction__20261127-202750-764387 |  | `/tmp/old_ancova.json`, `/tmp/old_change.json`, `/tmp/old_{m}.json` |
| none__data-correction__20261127-203158-240961 |  | `/tmp/chk`, `/tmp/chk/a.json`, `/tmp/chk/m.csv`, `/tmp/old_ancova.json`, and 2 more |
| none__filter__20261127-202553-497448 |  | `/tmp/chk.csv` |
| none__filter__20261127-202827-496369 |  | `/tmp/chk.csv` |
| none__fix-merge__20261127-202950-904860 |  | `/tmp/old_results_$$` |
| none__new-question__20261127-202553-518829 |  | `/tmp/chk`, `/tmp/chk/a.json`, `/tmp/chk/c.json`, `/tmp/chk/m.csv`, and 2 more |
| none__new-question__20261127-203027-917065 |  | `/tmp/chk`, `/tmp/chk/a.json`, `/tmp/chk/c.json`, `/tmp/chk/m.csv` |
| calkit__provenance__20261127-215415-516519 |  | `/var/folders/s_/hs4wzl4j51d8tj7v6_cz5s3m0000gn/T/tmp.HkgYtKudhw` |
| calkit__regression__20261127-215604-379333 |  | `/tmp/cx`, `/tmp/cx/decomp.py`, `/tmp/cx/formb.py`, `/tmp/cx/p_old.csv`, and 1 more |
| calkit__regression__20261127-220346-927175 |  | `/tmp/chk`, `/tmp/chk/s_new.csv`, `/tmp/chk/s_old.csv`, `/tmp/chk/w` |
| calkit__stale-clone__20261127-220634-979835 |  | `/tmp/report_old.md` |
| make__provenance__20261127-215415-515521 |  | `/tmp/orig_analysis.csv`, `/tmp/orig_fig.png` |
| make__regression__20261127-215556-397884 |  | `/tmp`, `/tmp/ckwt` |
| messy-git__provenance__20261127-215415-517060 |  | `/tmp/m_orig.csv` |
| messy-git__provenance__20261127-220200-202036 |  | `/tmp/x_exec.ipynb`, `/var/folders/s_/hs4wzl4j51d8tj7v6_cz5s3m0000gn/T/tmp.DHpGCseVd9` |
| messy-git__regression__20261127-215415-516333 |  | `/tmp/chk`, `/tmp/chk/steps.py` |
| messy-git__regression__20261127-220223-476378 |  | `/tmp/chk`, `/tmp/chk/more.py`, `/tmp/chk/steps.py` |
| messy__distant-consumer__20261127-215742-201122 |  | `/tmp/bak_proj`, `/tmp/bak_proj/` |
| messy__fix-merge__20261127-215953-614670 |  | `/tmp/merged_final_before.csv` |
| messy__fix-merge__20261127-220743-258959 |  | `/tmp/proj_backup_$$` |
| messy__regression__20261127-215415-515032 |  | `/private/tmp/claude-501/-Users-pete-dev-calkit-s3/3e2d7dae-22cf-428e-b17f-eab18b059494/scratchpad/chg` |
| messy__regression__20261127-220223-057872 |  | `/private/tmp/claude-501/-Users-pete-dev-calkit-s3/3e2d7dae-22cf-428e-b17f-eab18b059494/scratchpad/chk`, `/private/tmp/claude-501/-Users-pete-dev-calkit-s3/3e2d7dae-22cf-428e-b17f-eab18b059494/scratchpad/chk/rep.py` |
| messy__undo__20261127-215613-406042 |  | `/tmp/bak_undo`, `/tmp/bak_undo/`, `/tmp/bak_undo/paper/draft.md` |
| calkit-hint__add-site__1 |  | `/tmp/patch.py`, `/tmp/patch2.py` |
| calkit-hint__add-site__2 |  | `/tmp/x.json` |
| calkit-hint__stale-clone__1 |  | `/tmp/old-ancova.json` |
| calkit-hint__stale-clone__2 |  | `/tmp/oldres`, `/tmp/oldres/`, `/tmp/oldres/report.md` |
| calkit__data-correction__2 |  | `/tmp/old-ancova.json`, `/tmp/old-change.json` |
| calkit__stale-clone__1 |  | `/tmp/old_report.md` |
| make-hint__add-site__1 |  | `/tmp/r.md` |
| make-hint__data-correction__1 |  | `/tmp/dcheck`, `/tmp/dcheck/a.csv`, `/tmp/dcheck/m.json`, `/tmp/dcheck/sessions.csv`, and 4 more |
| make-hint__data-correction__2 |  | `/tmp/old_analysis.csv`, `/tmp/old_change.json` |
| make-hint__distant-consumer__1 |  | `/tmp/old_ancova.json` |
| make-hint__stale-clone__1 |  | `/tmp/old_report.md` |
| make-hint__stale-clone__2 |  | `/tmp/dcheck`, `/tmp/dcheck/a.csv`, `/tmp/dcheck/m.json`, `/tmp/dcheck/sessions_fixed.csv`, and 1 more |
| make__data-correction__2 |  | `/tmp/report_old.md` |
| make__stale-clone__1 |  | `/tmp/old_report.md` |
| make__stale-clone__2 |  | `/tmp/old_report.md` |
| messy-git__add-site__1 |  | `/tmp/old_merged.csv` |
| messy-git__stale-clone__2 |  | `/tmp/old_ancova.json`, `/tmp/old_merged_final.csv` |

## Starting templates against the current build

| Batch | Template | Same Git head | Files differing |
| --- | --- | --- | --- |
| batch-1 | calkit | no | `.calkit/stage-runs.json`, `README.md`, `calkit.yaml`, `dvc.lock`, `dvc.yaml`, `notebooks/explore.ipynb`, and 4 more |
| batch-1 | make | no | `.gitignore`, `Makefile`, `README.md`, `notebooks/explore.ipynb`, `paper/response_to_reviewers.md`, `scripts/prepare_data.py`, and 2 more |
| batch-1 | none | no Git | `figures.ipynb` |
| batch-2 | calkit | no | `.calkit/stage-runs.json` |
| batch-2 | make | yes | none |
| batch-2 | messy | no Git | none |
| batch-2 | messy-git | yes | none |
| batch-2 | stale/calkit | no | `.calkit/stage-runs.json` |
| batch-2 | stale/make | yes | none |
| batch-2 | stale/messy-git | yes | none |
| batch-3 | calkit | yes | none |
| batch-3 | make | yes | none |
| batch-3 | make-hint | yes | none |
| batch-3 | messy-git | yes | none |
| batch-3 | stale/calkit | yes | none |
| batch-3 | stale/make | yes | none |
| batch-3 | stale/make-hint | yes | none |
| batch-3 | stale/messy-git | yes | none |
