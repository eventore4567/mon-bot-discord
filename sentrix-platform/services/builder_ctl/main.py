"""Compatibility entrypoint for the production SentriX build worker."""

from agents.build_worker.main import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
