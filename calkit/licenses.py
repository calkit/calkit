"""Functionality for working with licenses.

Calkit projects will often include code, data, text, and other content
and artifacts that may each have their own license.

By default, we will look for a LICENSE files in the repo and use those for
the folder in which they live.
Licenses can also be defined in the project metadata (calkit.yaml) like:

```yaml
licenses:
  - for_path: .
    path: LICENSE.txt
    name: CC-BY-4.0
  - for_path: src
    name: MIT
  - for_path: *.py
    name: PSF
```
"""

# IDs here come from https://spdx.org/licenses/
# Note this format is currently the one used by InvenioRDM,
# but we may want to use the spdx-license-list Python package
LICENSES = {
    "cc-by-4.0": {
        "id": "cc-by-4.0",
        "name": "CC-BY-4.0",
        "title": {"en": "Creative Commons Attribution 4.0 International"},
        "description": {
            "en": (
                "The Creative Commons Attribution license allows "
                "re-distribution and re-use of a licensed work on "
                "the condition that the creator is appropriately "
                "credited."
            )
        },
        "link": "https://creativecommons.org/licenses/by/4.0/",
    }
}


def get_project_licenses() -> dict:
    """Read project licenses.

    Returns a dictionary keyed by path, where `.` represents the default for
    the entire project.
    """
    # TODO: Finish this
    return {}
