# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""CAP SDK package root.

Keep the package import lightweight so modules such as ``cap_sdk.hal`` can be
used without pulling in optional protobuf-backed helpers like ``frame``.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

__version__ = "0.1.0"

_EXPORTED_SUBMODULES = frozenset({"frame", "security", "skill_invocation", "validator"})


def __getattr__(name: str) -> ModuleType:
    """Lazily import convenience submodules on first access."""
    if name not in _EXPORTED_SUBMODULES:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)

    module = import_module(f"{__name__}.{name}")
    globals()[name] = module
    return module


__all__ = ["frame", "security", "skill_invocation", "validator"]
