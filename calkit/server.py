"""A local server for interacting with project repos."""

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware


app = FastAPI(title="calkit-server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Only allow localhost and calkit.io?
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def get_health() -> str:
    return "All good!"
