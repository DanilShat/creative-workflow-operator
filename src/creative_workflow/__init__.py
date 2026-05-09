"""Creative Workflow runtime package.

The package intentionally keeps server, worker, and shared contracts separate:
the server owns state and orchestration, the worker owns browser/DCC execution,
and shared contracts define every payload that crosses that boundary.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"

