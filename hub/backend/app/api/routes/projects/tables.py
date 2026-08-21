"""Reading tabular files for the dataset viewer.

The viewer is the same one the tables page uses, which wants CSV text. The
hub reads CSV, TSV, parquet, and JSON lines with polars and hands back CSV,
capped at a row count a browser can hold, from Git or from object storage.
"""

import base64
import io
import logging
import posixpath

import git
import polars as pl
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import app.projects
from app.api.deps import CurrentUserOptional, SessionDep
from app.dvc import get_data_fpath_for_md5
from app.git import get_repo, get_repo_tree_for_ref
from app.models import Project, User
from app.storage import get_object_fs

logger = logging.getLogger(__name__)

router = APIRouter()

TABLE_SUFFIXES = {".csv", ".tsv", ".parquet", ".jsonl", ".ndjson"}
MAX_TABLE_BYTES = 500_000_000
MAX_ROWS = 200_000


class TableText(BaseModel):
    path: str
    # The table as CSV, base64-encoded, which is what the table viewer reads
    content: str
    columns: list[str]
    n_rows: int
    # True when the file has more rows than are included
    truncated: bool


def _read_project_file(
    project: Project,
    repo: git.Repo,
    path: str,
    ref: str | None,
    max_bytes: int,
    session: SessionDep | None = None,
    current_user: User | None = None,
) -> bytes:
    """A file's bytes, from Git or from DVC storage.

    A dataset imported from another Calkit project is a pointer whose
    ``remote`` names that project; its bytes live in that project's storage
    (the pointer is ``push: false``, so they never get copied here). Such a
    read goes to the source project, after checking the reader can see it.
    """
    tree = get_repo_tree_for_ref(repo, ref)
    if tree.is_file(path):
        data = bytes(tree.read_bytes(path))
        if len(data) > max_bytes:
            raise HTTPException(413, f"'{path}' is too large to view")
        return data
    outs = app.projects.dvc_outputs_from_tree(project=project, tree=tree)
    out = outs.get(path)
    if out is None or (out.get("md5") or "").endswith(".dir"):
        raise HTTPException(404, f"'{path}' is not a file in this project")
    if (out.get("size") or 0) > max_bytes:
        raise HTTPException(413, f"'{path}' is too large to view")
    owner_name, project_name = project.owner_account_name, project.name
    remote = str(out.get("remote") or "")
    if remote.startswith("calkit:") and "/" in remote:
        src_owner, src_project = remote[len("calkit:") :].split("/", 1)
        if session is not None:
            # Raises if the source project is missing or not readable
            app.projects.get_project(
                session=session,
                owner_name=src_owner,
                project_name=src_project,
                current_user=current_user,
                min_access_level="read",
            )
        owner_name, project_name = src_owner, src_project
    fs = get_object_fs()
    fpath = get_data_fpath_for_md5(
        owner_name=owner_name,
        project_name=project_name,
        md5=out["md5"],
        fs=fs,
    )
    if fpath is None:
        where = (
            f"{owner_name}/{project_name}'s storage" if remote else "storage"
        )
        raise HTTPException(404, f"'{path}' has not been pushed to {where}")
    with fs.open(fpath, "rb") as f:
        data = bytes(f.read(max_bytes + 1))
    if len(data) > max_bytes:
        raise HTTPException(413, f"'{path}' is too large to view")
    return data


def read_table(data: bytes, path: str) -> pl.DataFrame:
    """Parse a tabular file by its suffix."""
    suffix = posixpath.splitext(path)[1].lower()
    buf = io.BytesIO(data)
    try:
        if suffix == ".parquet":
            return pl.read_parquet(buf)
        if suffix == ".tsv":
            return pl.read_csv(
                buf,
                separator="\t",
                infer_schema_length=1000,
                ignore_errors=True,
            )
        if suffix in (".jsonl", ".ndjson"):
            return pl.read_ndjson(buf)
        return pl.read_csv(buf, infer_schema_length=1000, ignore_errors=True)
    except Exception as e:
        raise HTTPException(422, f"Could not read '{path}' as a table: {e}")


def to_csv_text(df: pl.DataFrame, max_rows: int) -> tuple[str, bool]:
    """The frame as CSV text, cut at ``max_rows``."""
    truncated = df.height > max_rows
    return df.head(max_rows).write_csv(), truncated


@router.get("/projects/{owner_name}/{project_name}/dataset-csv/{path:path}")
def get_project_dataset_csv(
    owner_name: str,
    project_name: str,
    path: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> TableText:
    """A tabular file as CSV, for the table viewer.

    CSV and TSV are read and re-emitted (which also normalizes them);
    parquet and JSON lines are converted. Rows beyond ``MAX_ROWS`` are cut
    and the response says so, rather than sending a browser more than it
    can hold.
    """
    if posixpath.splitext(path)[1].lower() not in TABLE_SUFFIXES:
        raise HTTPException(
            415, f"'{path}' isn't a table format this viewer reads"
        )
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ref=ref
    )
    data = _read_project_file(
        project, repo, path, ref, MAX_TABLE_BYTES, session, current_user
    )
    df = read_table(data, path)
    text, truncated = to_csv_text(df, MAX_ROWS)
    return TableText(
        path=path,
        content=base64.b64encode(text.encode("utf-8")).decode("ascii"),
        columns=list(df.columns),
        n_rows=df.height,
        truncated=truncated,
    )


HDF5_SUFFIXES = {".h5", ".hdf5", ".hdf", ".he5"}


class Hdf5Key(BaseModel):
    key: str
    kind: str  # "dataset" or "group"
    shape: list[int] | None = None
    dtype: str | None = None
    # Whether the viewer can show it as a table (1D or 2D, or compound)
    tabular: bool = False


class Hdf5Listing(BaseModel):
    path: str
    keys: list[Hdf5Key]


def _hdf5_keys(data: bytes) -> list[Hdf5Key]:
    import h5py  # type: ignore[import-not-found,import-untyped,unused-ignore]

    keys: list[Hdf5Key] = []
    with h5py.File(io.BytesIO(data), "r") as f:

        def visit(name: str, obj: object) -> None:
            if isinstance(obj, h5py.Dataset):
                shape = [int(n) for n in obj.shape]
                compound = obj.dtype.names is not None
                keys.append(
                    Hdf5Key(
                        key=name,
                        kind="dataset",
                        shape=shape,
                        dtype=str(obj.dtype),
                        tabular=compound or len(shape) in (1, 2),
                    )
                )
            else:
                keys.append(Hdf5Key(key=name, kind="group"))

        f.visititems(visit)
    return keys


def _hdf5_dataset_frame(data: bytes, key: str) -> pl.DataFrame:
    """One HDF5 dataset as a frame: columns for 2D, one column for 1D,
    fields for a compound dtype. Scalars and higher ranks aren't tables."""
    import h5py  # type: ignore[import-not-found,import-untyped,unused-ignore]
    import numpy as np

    with h5py.File(io.BytesIO(data), "r") as f:
        if key not in f or not isinstance(f[key], h5py.Dataset):
            raise HTTPException(404, f"'{key}' is not a dataset in the file")
        ds = f[key]
        if ds.dtype.names is not None:
            arr = ds[()]
            return pl.DataFrame(
                {
                    name: [
                        v.decode() if isinstance(v, bytes) else v
                        for v in arr[name].tolist()
                    ]
                    for name in ds.dtype.names
                }
            )
        arr = np.asarray(ds[()])
        if arr.ndim == 0:
            return pl.DataFrame({"value": [arr.item()]})
        if arr.ndim == 1:
            values = arr.tolist()
            if arr.dtype.kind in ("S", "O"):
                values = [
                    v.decode() if isinstance(v, bytes) else v for v in values
                ]
            return pl.DataFrame({key.split("/")[-1]: values})
        if arr.ndim == 2:
            return pl.DataFrame(
                {f"col{j}": arr[:, j].tolist() for j in range(arr.shape[1])}
            )
        raise HTTPException(
            415, f"'{key}' has {arr.ndim} dimensions; only 1D and 2D show here"
        )


@router.get("/projects/{owner_name}/{project_name}/dataset-hdf5/{path:path}")
def get_project_dataset_hdf5(
    owner_name: str,
    project_name: str,
    path: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    key: str | None = None,
    ref: str | None = None,
) -> Hdf5Listing | TableText:
    """Browse an HDF5 file: its keys, or one dataset as CSV.

    Without ``key`` the response lists every group and dataset with shape
    and dtype; with ``key`` it returns that dataset the way the CSV route
    does, so the same table viewer shows it.
    """
    if posixpath.splitext(path)[1].lower() not in HDF5_SUFFIXES:
        raise HTTPException(415, f"'{path}' isn't an HDF5 file")
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ref=ref
    )
    data = _read_project_file(
        project, repo, path, ref, MAX_TABLE_BYTES, session, current_user
    )
    try:
        if key is None:
            return Hdf5Listing(path=path, keys=_hdf5_keys(data))
        df = _hdf5_dataset_frame(data, key)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"Could not read '{path}': {e}")
    text, truncated = to_csv_text(df, MAX_ROWS)
    return TableText(
        path=f"{path}:{key}",
        content=base64.b64encode(text.encode("utf-8")).decode("ascii"),
        columns=list(df.columns),
        n_rows=df.height,
        truncated=truncated,
    )
