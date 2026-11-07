"""Isolated entrypoint; renderer imports cannot leak into GPU node namespaces."""

import sys
from pathlib import Path
from .common import REPO


def main():
    action, *args = sys.argv[1:]
    if action == "classify":
        from .classification import run

        run(*map(Path, args))
        return
    sys.path.insert(0, str(REPO / "best-practices/body-scan-delivery"))
    from snapshot import verify_integrity

    verify_integrity()
    if action == "prepare":
        from .rendering import prepare

        prepare(args[0], Path(args[1]))
    elif action == "render":
        from .rendering import render

        render(
            Path(args[0]), args[1], Path(args[2]), args[3] if len(args) > 3 else None
        )
    else:
        raise ValueError("Unknown bridge action")


if __name__ == "__main__":
    main()
