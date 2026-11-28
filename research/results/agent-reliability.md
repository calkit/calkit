# Agent reliability

Passes out of trials where the check applies; – where none do. All four: trials that failed none of correct, consistent, damage, and traceable, counting those that don't apply as not failed. Also fixed: trials that failed correct only because the agent also fixed a planted bug the task didn't name, e.g., site D's IDs.

## By arm, all batches

| Arm | Trials | All four | Correct | Consistent | Damage | Traceable | Distant | Also fixed | $/trial | Min | Turns |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| none | 8 | 0 | 8/8 | 8/8 | 8/8 | 0/8 | – | 0 | 0.29 | 1.3 | 8 |
| messy | 12 | 4 | 12/12 | 8/8 | 12/12 | 0/8 | 8/8 | 0 | 0.41 | 1.6 | 9 |
| messy-git | 14 | 4 | 12/14 | 10/10 | 14/14 | 0/10 | 8/8 | 2 | 0.38 | 1.5 | 10 |
| make | 18 | 18 | 18/18 | 14/14 | 18/18 | 14/14 | 4/4 | 0 | 0.28 | 1.2 | 8 |
| calkit | 18 | 18 | 18/18 | 14/14 | 18/18 | 14/14 | 4/4 | 0 | 0.40 | 1.4 | 11 |

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

## Site D noticed unprompted

Trials whose task isn't fix-merge whose final message matches `site D|leading zero|zero-pad|\bD-\d+`.

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
| messy-git | data-correction | 0/2 |
| messy-git | distant-consumer | 0/2 |
| messy-git | provenance | 2/2 |
| messy-git | regression | 1/2 |
| messy-git | stale-clone | 2/2 |
| messy-git | undo | 0/2 |
| messy-git | all | 5/12 |
| make | data-correction | 0/2 |
| make | distant-consumer | 0/2 |
| make | filter | 0/2 |
| make | new-question | 0/2 |
| make | provenance | 0/2 |
| make | regression | 0/2 |
| make | stale-clone | 0/2 |
| make | undo | 0/2 |
| make | all | 0/16 |
| calkit | data-correction | 0/2 |
| calkit | distant-consumer | 0/2 |
| calkit | filter | 0/2 |
| calkit | new-question | 0/2 |
| calkit | provenance | 0/2 |
| calkit | regression | 0/2 |
| calkit | stale-clone | 0/2 |
| calkit | undo | 0/2 |
| calkit | all | 0/16 |

Messy arms 9/22, the others without the checking guidance 0/38; one-sided Fisher exact p = 3.4e-05.

## Checking guidance

In the batches the checking-guidance arms ran in (none yet): site D noticed as above, and site E's re-entered records noticed in add-site trials whose final message matches `[Dd]uplicat|[Rr]e-?enter(?:ed|s)?\b|[Rr]e-?entr(?:y|ies)\b|entered (?:twice|again)|entered_on|(?:latest|most recent) (?:entry|record)`. Skill: trials that loaded the conventions skill, where calkit-hint's guidance is. README: trials whose tool inputs name README.md, where make-hint's is. Site E handling: how the analysis table holds site E's re-entered participants.

| Arm | Trials | Skill | README | Site D noticed | Site E noticed | add-site correct | Site E handling |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| messy-git | 0 | 0 | 0 | 0/0 | 0/0 | 0/0 | – |
| make | 0 | 0 | 0 | 0/0 | 0/0 | 0/0 | – |
| make-hint | 0 | 0 | 0 | 0/0 | 0/0 | 0/0 | – |
| calkit | 0 | 0 | 0 | 0/0 | 0/0 | 0/0 | – |
| calkit-hint | 0 | 0 | 0 | 0/0 | 0/0 | 0/0 | – |

| calkit-hint against | Test | Site D p | Site E p |
| --- | --- | ---: | ---: |
| calkit | Fisher exact, greater | 1 | 1 |
| make-hint | Fisher exact, two-sided | 1 | 1 |

## Isolation

Trials whose tool inputs mention the benchmark itself: 0; that name any path outside their run and Calkit snapshot: 28.

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
