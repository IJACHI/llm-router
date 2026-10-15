"""Root CLI entrypoint proxy for ijachi-llm-router.

Re-exports entry points to ijachi_router.cli.router and ijachi_router.cli.code.
"""

from __future__ import annotations

from ijachi_router.cli.code import main as code_main
from ijachi_router.cli.router import main as router_main

# Backward-compatible main
main = router_main

if __name__ == "__main__":
    main()
