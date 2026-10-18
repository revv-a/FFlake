from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class GraphConfig:
    host: str = os.getenv("FALKORDB_HOST", "localhost")
    port: int = int(os.getenv("FALKORDB_PORT", "6379"))
    graph_name: str = os.getenv("FALKORDB_GRAPH", "fflake")
    password: str | None = os.getenv("FALKORDB_PASSWORD") or None

config = GraphConfig()
