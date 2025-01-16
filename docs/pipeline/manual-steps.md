# Manual steps

Sometimes there are steps in a pipeline that are too cumbersome to
automate,
but are not complex enough to warrant defining an entire
[procedure](../tutorials/procedures.md).
Or maybe they will not need to be iterated much,
so automation would not be worth the trouble.

For example,
imagine you want to save a mesh snapshot image from a CFD simulation using
[ParaView](https://www.paraview.org/).
You can use the `calkit manual-step` command to pause the pipeline,
execute a command to open ParaView,
and display a message with instructions.

```yaml
stages:
  save-mesh-snapshot-isometric:
    cmd: >
      calkit manual-step
      --cmd
      "touch sim/cases/k-epsilon-ny-40/case.foam && paraview sim/cases/k-epsilon-ny-40/case.foam"
      --message
      "Save isometric mesh image to figures/rans-mesh-snapshot-isometric.png"
    deps:
      - sim/cases/k-epsilon-ny-40/constant/polyMesh
    outs:
      - figures/rans-mesh-snapshot-isometric.png
    meta:
      calkit:
        type: figure
        title: RANS simulation mesh snapshot
        description: A snapshot of the RANS simulation mesh.
```

After confirming, DVC will check that the defined outputs exist,
and if so, continue with the pipeline execution.
