"""Domain errors that the API maps to specific HTTP status codes."""

from __future__ import annotations


class GraphUnavailableError(RuntimeError):
    """FalkorDB cannot be reached (maps to HTTP 503)."""


class GraphQueryError(RuntimeError):
    """FalkorDB rejected or failed a query (maps to HTTP 502)."""


class EntityNotFoundError(LookupError):
    """One or more requested graph entities do not exist (HTTP 404)."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(
            "Entity not found in the graph: " + ", ".join(repr(m) for m in missing)
        )
