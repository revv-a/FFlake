from __future__ import annotations
from functools import lru_cache
from typing import Any
from falkordb import FalkorDB
from .config import config

@lru_cache(maxsize=1)
def get_graph():
    """Create the graph handle lazily, so importing the API doesn't need a live DB."""
    options: dict[str, Any] = {"host": config.host, "port": config.port}
    if config.password:
        options["password"] = config.password
    client = FalkorDB(**options)
    return client.select_graph(config.graph_name)

def run_query(query: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
    result = get_graph().query(query, params or {})
    return result.result_set or []
