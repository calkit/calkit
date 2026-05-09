# Subprojects

If a project gets to the point where it could be split into multiple
subprojects with standalone value,
the smaller parts can be defined as subprojects in the parent.
Another use case could be a larger project that wants to use figures from
a smaller one,
and therefore wants the parent's project to run the child's pipeline if
a given artifact is out-of-date.

A subproject can be added by simply adding to the parent project's `calkit.yaml`
file:

```yaml
name: parent-project
title: This is my parent project

subprojects:
  - path: my-subproject
    ref:
      kind: branch
      name: main
```

These can be added as Git submodules or subtrees.
If submodules, they will track the default branch from the origin remote by
default,
which is different from typical Git submodule behavior,
where a commit is tracked.
This means a `calkit pull` will pull all subprojects from their
defined ref.

When calling `calkit run` from a parent project, all subproject `dvc.yaml`
files are compiled (and written) recursively.
DVC then auto-discovers every `dvc.yaml` in the repository tree when running
`dvc repro`, so subproject stages run as part of the same dependency graph as
the parent without any synthetic wrapper stages.

To express ordering between parent and subproject stages, add explicit file
dependencies. For example, if a parent stage consumes an output produced by
a subproject stage, list that file as a `dep` of the parent stage — DVC will
resolve the full cross-pipeline DAG automatically.
