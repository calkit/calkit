"""Generate client code from the FastAPI app."""

from app import models  # TODO: Will need to be able to install cloud package
from sqlmodel.main import SQLModelMetaclass
import app.api.routes.projects as projects  # TODO: Structure better
from typing import Annotated


def get_all_sql_models():
    objs = models.__dict__
    sql_models = []
    for name, obj in objs.items():
        if (
            not name.startswith("_")
            and isinstance(obj, SQLModelMetaclass)
            and obj.__module__ == "app.models"
        ):
            sql_models.append(obj)
    return sql_models


def basemodel_src(model: SQLModelMetaclass) -> str:
    txt = f"class {model.__name__}(BaseModel):\n"
    for name, dtype in model.__annotations__.items():
        if isinstance(dtype, type):
            dtype = dtype.__name__
        print(name, dtype)
        txt += f"    {name}: {dtype}\n"
    return txt


def router_func_src(route) -> str:
    func = getattr(projects, route.name)
    txt = f"def {func.__name__}(\n"
    for arg_name, dtype in func.__annotations__.items():
        if isinstance(dtype, type) and arg_name != "return":
            dtype = dtype.__name__
            txt += f"    {arg_name}: {dtype},\n"
    txt += "    **kwargs,\n"
    txt += f") -> {func.__annotations__['return'].__name__}:\n"
    method = list(route.methods)[0].lower()
    path = route.path
    # Extract path params from args and figure out which args are params
    # versus a JSON body
    txt += f"    return client.{method}(f\"{route.path}\", **kwargs)"
    return txt


if __name__ == "__main__":
    pass
    # TODO: Generate models and client modules from routers
