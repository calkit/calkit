"""Functionality for client generation.

We do this our own way rather than using an OpenAPI generator so we can have
control over how the requests are made.
"""

import string
from typing import Annotated

import app.api.routes.projects as projects  # TODO: Structure better
from app import models
from sqlmodel.main import SQLModelMetaclass


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


def url_param_names_from_route(route) -> list[str]:
    param_names = []
    for (
        literal_text,
        field_name,
        format_spec,
        conversion,
    ) in string.Formatter().parse(route.path):
        param_names.append(field_name)
    return param_names


def router_func_src(route) -> str:
    func = getattr(projects, route.name)
    url_param_names = url_param_names_from_route(route)
    params_txt = "params = dict("
    model_input = ""
    txt = f"def {func.__name__}(\n"
    for arg_name, dtype in func.__annotations__.items():
        if isinstance(dtype, type) and arg_name != "return":
            is_model = isinstance(dtype, SQLModelMetaclass)
            dtype = dtype.__name__
            txt += f"    {arg_name}: {dtype},\n"
            if arg_name not in url_param_names and not is_model:
                params_txt += f"{arg_name}={arg_name}, "
            elif is_model:
                if model_input:
                    raise ValueError("Can only be one body model")
                model_input = f"json={arg_name}.model_dump(), "
    txt += "    **kwargs,\n"
    txt += f") -> {func.__annotations__['return'].__name__}:\n"
    params_txt += ")\n"
    txt += "    " + params_txt
    method = list(route.methods)[0].lower()
    # Extract path params from args and figure out which args are params
    # versus a JSON body
    txt += (
        f'    return client.{method}(f"{route.path}", params=params,'
        f" {model_input}**kwargs)"
    )
    return txt


def generate():
    """Create a client directory at the top of the repo."""
    # First create all models
    raise NotImplementedError
