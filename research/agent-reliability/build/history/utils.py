"""Shared helpers for the cognitive training analysis."""

EDUCATION_LEVELS = ["secondary", "college", "graduate"]
# Eligible ages, inclusive
MIN_AGE = 60
MAX_AGE = @MAX_AGE@


def clean_ids(df):
    """Normalize participant IDs, which are typed in at the sites."""
    df = df.copy()
    df["participant_id"] = df["participant_id"].str.strip().str.upper()
    return df


def eligible(participants, min_age=MIN_AGE, max_age=MAX_AGE):
    """Participants within the eligible ages."""
    return participants[participants["age"].between(min_age, max_age)]


def format_p(p):
    return "p < 0.001" if p < 0.001 else f"p = {p:.2g}"
