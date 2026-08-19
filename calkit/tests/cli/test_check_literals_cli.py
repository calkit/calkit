import json
import subprocess


def test_check_repro_literals(tmp_dir):
    # Initialize calkit
    subprocess.check_call(["calkit", "init"])

    # Create JSON output of a script
    results = {"drag_coefficient": 0.42, "lift_coefficient": 1.23}
    with open("results.json", "w") as f:
        json.dump(results, f)

    # Mock a pipeline stage for from-json
    with open("dvc.yaml", "w") as f:
        f.write("""
stages:
  results-latex:
    cmd: calkit latex from-json results.json --output results.tex
    deps:
      - results.json
    outs:
      - results.tex
""")

    # Mock a generated from-json tex
    with open("results.tex", "w") as f:
        f.write("\\newcommand{\\resultsDragCoefficient}{0.42}\n")
        f.write("\\newcommand{\\resultsLiftCoefficient}{1.23}\n")

    # Mock a manuscript that includes an untraceable literal (3.14) and a traceable one (0.42)
    with open("main.tex", "w") as f:
        f.write("""
\\documentclass{article}
\\begin{document}
Here is a traceable literal: 0.42.
Here is an untraceable literal: 3.14.
\\end{document}
""")

    # Add main.tex as a publication in calkit.yaml
    with open("calkit.yaml", "a") as f:
        f.write("""
publications:
  - title: "My Paper"
    path: main.tex
    kind: journal-article
""")

    # Run check repro (text output)
    result = subprocess.run(
        ["calkit", "check", "repro"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Untraceable literals: 1" in result.stdout
    assert "Untraceable Literals" in result.stdout
    assert "3.14" in result.stdout

    # Traceable literal should not be in the table output
    assert "0.42" not in result.stdout.split("Untraceable Literals")[1]

    # Run check repro --json
    result_json = subprocess.run(
        ["calkit", "check", "repro", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )

    parsed = json.loads(result_json.stdout)
    assert "untraceable_literals" in parsed
    assert len(parsed["untraceable_literals"]) == 1
    assert parsed["untraceable_literals"][0]["value"] == "3.14"
