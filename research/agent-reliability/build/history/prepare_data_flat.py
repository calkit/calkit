# merge participants + sessions into one table for the models
import pandas as pd

from utils import EDUCATION_LEVELS, clean_ids, eligible

PARTICIPANTS = "data/raw/participants.csv"
SESSIONS = "@SESSIONS@"
OUT = "@OUT@"

read = {"dtype": {"participant_id": str}}
participants = clean_ids(pd.read_csv(PARTICIPANTS, **read))
sessions = clean_ids(pd.read_csv(SESSIONS, **read))
participants = eligible(participants)

# complete sessions only, one score per person per week
sessions = sessions[sessions["status"] == "complete"]
scores = sessions.pivot(index="participant_id", columns="week", values="score")
scores.columns = [f"score_w{week}" for week in scores.columns]
df = participants.merge(scores.reset_index(), on="participant_id", how="inner")
df = df.dropna(subset=["score_w0", "score_w12"])
df["treated"] = (df["arm"] == "training").astype(int)
df["education"] = pd.Categorical(df["education"], categories=EDUCATION_LEVELS)
df = df.sort_values("participant_id")
df.to_csv(OUT, index=False)
print(df.shape)
