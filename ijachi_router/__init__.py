"""
ijachi-llm-router: One prompt, any model.

Library usage:
    from ijachi_router import route
    result = route("Explain quicksort in Python")
    print(result.text, result.model_used, result.cost)
"""

from ijachi_router.core import route, Router

__version__ = "0.1.0"
__all__ = ["route", "Router"]
