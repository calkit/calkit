# Subprojects

To place smaller projects in broader contexts, it can be helpful to define
_subprojects_ in folders of other, larger projects.
Subproject environments and pipelines are checked/run by default when
running parent or superproject pipelines.
Subprojects can be declared in `calkit.yaml` like:

```yaml
subprojects:
  - path: path/to/your/subproject
```

<!-- prettier-ignore -->
!!! tip
    Don't break projects into subprojects so small that they can't be
    understood or provide value outside of the superproject context.
    That can result in fragmentation, tight coupling, and slow development.
