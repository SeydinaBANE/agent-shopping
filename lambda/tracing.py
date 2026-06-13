from __future__ import annotations

import contextlib
import os
from typing import Any

_langfuse: Any = None


def create_trace(name: str, **kwargs: Any) -> Any:
    global _langfuse
    if _langfuse is None:
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
        if not secret_key or not public_key:
            return None
        try:
            from langfuse import Langfuse

            _langfuse = Langfuse(
                secret_key=secret_key,
                public_key=public_key,
                host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )
        except ImportError:
            return None

    try:
        return _langfuse.trace(name=name, **kwargs)
    except Exception:
        return None


def flush() -> None:
    global _langfuse
    if _langfuse is not None:
        with contextlib.suppress(Exception):
            _langfuse.flush()
