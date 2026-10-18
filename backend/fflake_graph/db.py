from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from falkordb import FalkorDB
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .config import config
from .errors import GraphQueryError, GraphUnavailableError

logger = logging.getLogger("fflake.db")


@lru_cache(maxsize=1)
def get_graph():
    """Create the graph handle lazily, so importing the API doesn't need a live DB."""
    options: dict[str, Any] = {
        "host": config.host,
        "port": config.port,
        "socket_connect_timeout": 3,
        "socket_timeout": 15,
    }
    if config.username:
        options["username"] = config.username
    if config.password:
        options["password"] = config.password
    if config.ssl:
        options["ssl"] = True
    client = FalkorDB(**options)
    return client.select_graph(config.graph_name)


def run_query(query: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
    """Run a parameterized query and translate driver errors into domain errors."""
    try:
        result = get_graph().query(query, params or {})
    except (RedisConnectionError, RedisTimeoutError, OSError) as exc:
        logger.warning("FalkorDB unavailable: %s", exc)
        raise GraphUnavailableError(
            f"FalkorDB is not reachable at {config.host}:{config.port}"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - the driver raises assorted types
        logger.exception("Graph query failed")
        raise GraphQueryError("The graph database rejected the query") from exc
    return result.result_set or []
