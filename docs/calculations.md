# Calculations

One of the primary purposes doing research is to create knowledge that
makes it possible to calculate predictions in order to make decisions.
Calkit makes it possible to define such calculations for a project.
For example:

```yaml
calculations:
  force:
    name: Calculate force
    description: This calculates force.
    kind: formula
    params:
      formula: y = 0.55 * x + 545
    inputs:
      - name: x
        description: This is the input variable.
        dtype: float
    output:
      name: y
      description: This is the output.
      dtype: int
      template: The result is {y:.1f}!
```

This calculation uses a very basic formula that computes an output
from one input.
It can be executed with:

```sh
calkit calc force --input x=122
```

Since the output has a `template` defined, Calkit will print a formatted
result unless the `--no-format` option is specified.

```
The result is 612.0!
```

The above example is trivial,
but the future vision is to enable
[all kinds of calculations](https://github.com/calkit/calkit/issues/34)
to be defined, and to have these hosted and executed on the project's
homepage on calkit.io such that consumers of your research
can make use of it directly.

Alternatively,
for complex calculations, an interactive [app](apps.md)
can be defined for the project.
