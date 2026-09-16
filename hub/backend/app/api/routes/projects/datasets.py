"""Reading datasets for the dataset viewer: tabular files and HDF5.

These are datasets that happen to be tabular, not Calkit "tables" (which
are pipeline outputs declared as such).

The viewer is the same one the tables page uses, which wants CSV text. The
hub reads CSV, TSV, parquet, and JSON lines with polars and hands back CSV,
capped at a row count a browser can hold, from Git or from object storage.
"""

import base64
import io
import logging
import posixpath
import tempfile
from typing import Any

import polars as pl
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import app.projects
from app.api.deps import CurrentUserOptional, SessionDep
from app.git import get_repo, get_repo_tree_for_ref

logger = logging.getLogger(__name__)

router = APIRouter()

TABLE_SUFFIXES = {".csv", ".tsv", ".parquet", ".jsonl", ".ndjson"}
MAX_TABLE_BYTES = 500_000_000
MAX_ROW_LIMIT = 5000
DEFAULT_ROW_LIMIT = 1000
MAX_COL_LIMIT = 500
DEFAULT_COL_LIMIT = 100


class TableText(BaseModel):
    """A window of a table as CSV, which is what the table viewer reads.

    A table can be wider or longer than a browser can hold (a 2D array in
    an HDF5 file with thousands of columns, say), so the response is a
    window in both dimensions and says where it sits in the whole.
    """

    path: str
    # The window as CSV, base64-encoded
    content: str
    # Names of the columns in the window
    columns: list[str]
    n_rows: int
    n_cols: int
    row_offset: int
    row_limit: int
    col_offset: int
    col_limit: int
    # True when rows or columns lie outside the window
    truncated: bool


def scan_table(fpath: str, path: str) -> pl.LazyFrame:
    """A lazy frame over a tabular file, by its suffix.

    Lazy so that a window is cut at read time: a 500 MB CSV on a public
    project shouldn't be parsed whole, several times over for concurrent
    readers, to hand back a thousand rows.
    """
    suffix = posixpath.splitext(path)[1].lower()
    try:
        if suffix == ".parquet":
            return pl.scan_parquet(fpath)
        if suffix == ".tsv":
            return pl.scan_csv(
                fpath,
                separator="\t",
                infer_schema_length=1000,
                ignore_errors=True,
            )
        if suffix in (".jsonl", ".ndjson"):
            return pl.scan_ndjson(fpath)
        if suffix == ".csv":
            return pl.scan_csv(
                fpath, infer_schema_length=1000, ignore_errors=True
            )
    except Exception as e:
        raise HTTPException(422, f"Could not read '{path}' as a table: {e}")
    raise HTTPException(
        415, f"'{path}' isn't a table format this viewer reads"
    )


def read_table_window(
    data: bytes,
    path: str,
    row_offset: int,
    row_limit: int,
    col_offset: int,
    col_limit: int,
) -> TableText:
    """One window of a tabular file, read without materializing the rest."""
    suffix = posixpath.splitext(path)[1].lower()
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()
        lf = scan_table(tmp.name, path)
        try:
            names = lf.collect_schema().names()
            cols = names[col_offset : col_offset + col_limit]
            n_rows = int(lf.select(pl.len()).collect().item())
            window = (
                lf.select(cols).slice(row_offset, row_limit).collect()
                if cols
                else pl.DataFrame()
            )
        except Exception as e:
            raise HTTPException(
                422, f"Could not read '{path}' as a table: {e}"
            )
    return TableText(
        path=path,
        content=base64.b64encode(window.write_csv().encode("utf-8")).decode(
            "ascii"
        ),
        columns=list(cols),
        n_rows=n_rows,
        n_cols=len(names),
        row_offset=row_offset,
        row_limit=row_limit,
        col_offset=col_offset,
        col_limit=col_limit,
        truncated=(
            col_offset > 0
            or row_offset > 0
            or len(names) > col_offset + col_limit
            or n_rows > row_offset + row_limit
        ),
    )


@router.get("/projects/{owner_name}/{project_name}/dataset-csv/{path:path}")
def get_project_dataset_csv(
    owner_name: str,
    project_name: str,
    path: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
    row_offset: int = Query(0, ge=0),
    row_limit: int = Query(DEFAULT_ROW_LIMIT, ge=1, le=MAX_ROW_LIMIT),
    col_offset: int = Query(0, ge=0),
    col_limit: int = Query(DEFAULT_COL_LIMIT, ge=1, le=MAX_COL_LIMIT),
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
    data = app.projects.read_project_file(
        project,
        get_repo_tree_for_ref(repo, ref),
        path,
        MAX_TABLE_BYTES,
        session=session,
        current_user=current_user,
    )
    return read_table_window(
        data, path, row_offset, row_limit, col_offset, col_limit
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


def _hdf5_window(
    data: bytes,
    key: str,
    row_offset: int,
    row_limit: int,
    col_offset: int,
    col_limit: int,
) -> tuple[pl.DataFrame, int, int, list[str]]:
    """A window of one HDF5 dataset, with the full shape it was cut from.

    Columns for 2D, one column for 1D, fields for a compound dtype; the
    slice is taken on the h5py dataset itself, so a window of a large
    array never reads more than the window. Scalars and higher ranks
    aren't tables. Returns the frame, total rows, total columns, and
    every column name.
    """
    import h5py  # type: ignore[import-not-found,import-untyped,unused-ignore]

    rows = slice(row_offset, row_offset + row_limit)
    with h5py.File(io.BytesIO(data), "r") as f:
        if key not in f or not isinstance(f[key], h5py.Dataset):
            raise HTTPException(404, f"'{key}' is not a dataset in the file")
        ds = f[key]

        def decode(v: Any) -> Any:
            return v.decode() if isinstance(v, bytes) else v

        if ds.dtype.names is not None:
            names = list(ds.dtype.names)
            cols = names[col_offset : col_offset + col_limit]
            arr = ds[rows]
            frame = pl.DataFrame(
                {
                    name: [decode(v) for v in arr[name].tolist()]
                    for name in cols
                }
            )
            return frame, int(ds.shape[0]), len(names), names
        if ds.ndim == 0:
            names = ["value"]
            frame = pl.DataFrame({"value": [decode(ds[()].item())]})
            return frame, 1, 1, names
        if ds.ndim == 1:
            names = [key.split("/")[-1]]
            cols = names[col_offset : col_offset + col_limit]
            values = [decode(v) for v in ds[rows].tolist()] if cols else []
            frame = (
                pl.DataFrame({names[0]: values}) if cols else pl.DataFrame()
            )
            return frame, int(ds.shape[0]), 1, names
        if ds.ndim == 2:
            names = [f"col{j}" for j in range(ds.shape[1])]
            cols = names[col_offset : col_offset + col_limit]
            arr = ds[rows, col_offset : col_offset + col_limit]
            frame = pl.DataFrame(
                {cols[j]: arr[:, j].tolist() for j in range(len(cols))}
            )
            return frame, int(ds.shape[0]), int(ds.shape[1]), names
        raise HTTPException(
            415, f"'{key}' has {ds.ndim} dimensions; only 1D and 2D show here"
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
    row_offset: int = Query(0, ge=0),
    row_limit: int = Query(DEFAULT_ROW_LIMIT, ge=1, le=MAX_ROW_LIMIT),
    col_offset: int = Query(0, ge=0),
    col_limit: int = Query(DEFAULT_COL_LIMIT, ge=1, le=MAX_COL_LIMIT),
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
    data = app.projects.read_project_file(
        project,
        get_repo_tree_for_ref(repo, ref),
        path,
        MAX_TABLE_BYTES,
        session=session,
        current_user=current_user,
    )
    try:
        if key is None:
            return Hdf5Listing(path=path, keys=_hdf5_keys(data))
        window, n_rows, n_cols, names = _hdf5_window(
            data, key, row_offset, row_limit, col_offset, col_limit
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"Could not read '{path}': {e}")
    return TableText(
        path=f"{path}:{key}",
        content=base64.b64encode(window.write_csv().encode("utf-8")).decode(
            "ascii"
        ),
        columns=list(window.columns),
        n_rows=n_rows,
        n_cols=n_cols,
        row_offset=row_offset,
        row_limit=row_limit,
        col_offset=col_offset,
        col_limit=col_limit,
        truncated=(
            col_offset > 0
            or row_offset > 0
            or n_cols > col_offset + col_limit
            or n_rows > row_offset + row_limit
        ),
    )
