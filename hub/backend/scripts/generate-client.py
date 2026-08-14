"""Automatically generate a client subpackage from the models and routes.

Should create two modules: `models` and `routes`.
"""

import app.client

# TODO: Make sure this is run from the top of the repo or move there
app.client.generate()
