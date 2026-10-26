---
name: resolve-merge-conflicts
description: Resolve Git merge conflicts in a Calkit project, including
  dvc.lock, stage run records, and pipeline outputs. Use when the user
  invokes `/calkit:resolve-merge-conflicts`, asks to merge a branch, or a
  merge, pull, or rebase stopped with conflicts.
---

# Resolve merge conflicts

Some conflicted files record what the pipeline ran rather than what anyone
wrote, so they're resolved per stage by Calkit, not by editing text.

## Division of labor

Done by Calkit, never by hand:

- `dvc.lock` and `.calkit/stage-runs.json`, in the project and any
  subproject. Don't edit them or take one side whole with
  `git checkout --ours/--theirs`: that mixes stages, or drops the records of
  stages that only ran on the other side.
- Git-tracked pipeline outputs, which are checked out from the side each
  stage's `dvc.lock` entry came from.
- `dvc.yaml`, which is generated from `calkit.yaml`. Once `calkit.yaml` is
  resolved, take either side (`git checkout --ours dvc.yaml`) and run
  `calkit status`, which rewrites it.

Done by you, with judgment: everything else, e.g., source code,
`calkit.yaml`, and manuscripts. When the two sides disagree about intent,
not just text, ask the user.

## Starting a merge

Prefer `calkit merge BRANCH` to `git merge`. It sets up the merge driver,
resolves what it can, and checks out DVC-tracked outputs afterwards. Most
stages merge without a conflict: one changed on one side only takes that
side.

## Stages changed on both sides

Each needs one choice, which decides its `dvc.lock` entry, run record, and
Git-tracked outputs together:

- `ours` or `theirs`: keep that side's result.
- `rerun`: keep neither, so `calkit run` reruns it.

You have no terminal for the prompt, so pass choices as options:

```sh
calkit fix merge-conflicts --theirs fit --rerun figures
calkit fix merge-conflicts --prefer rerun
```

Name subproject stages as `calkit check stage-runs` does, e.g.,
`sub/dvc.yaml:stage`. Run it without options first to list the stages that
need a choice.

To choose, compare each side's inputs with the merged ones. If the merged
inputs match one side, keep that side. If they match neither, e.g., both
sides edited the code, the stage will rerun either way, so choose `rerun`.
If a stage is expensive to run, or its result is shared with others, ask the
user. During a rebase, "ours" is the branch being rebased onto, and
"theirs" is the commit being replayed.

## Finishing

1. Resolve and `git add` the remaining files.
2. For a merge, run `calkit merge --continue`, with any stage choices still
   needed. For a rebase or cherry-pick, run `calkit fix merge-conflicts`,
   then `git rebase --continue` or `git cherry-pick --continue`.
3. Run `calkit status`, then `calkit run` if stages are stale.
4. Run `calkit check stage-runs` to confirm every stage matches its run.
