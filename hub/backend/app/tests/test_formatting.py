from app.formatting import format_python


def test_format_python() -> None:
    # Black style at 79 columns
    assert format_python("x=1\nfig.savefig( 'figures/y.png' )\n") == (
        'x = 1\nfig.savefig("figures/y.png")\n'
    )
    long_call = (
        "ax.plot(" + ", ".join(f'df["col{i}"]' for i in range(8)) + ")\n"
    )
    formatted = format_python(long_call)
    assert all(len(line) <= 79 for line in formatted.splitlines())
    assert formatted != long_call
    # Already-formatted code is left alone, and so is code that doesn't
    # parse, since it's still the user's script
    assert format_python("x = 1\n") == "x = 1\n"
    assert format_python("def (:\n") == "def (:\n"
