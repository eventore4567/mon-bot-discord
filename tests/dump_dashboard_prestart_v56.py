from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: dump_dashboard_prestart_v56.py <output.html>")

    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    target = Path(sys.argv[1])
    target.write_text(str(dashboard.INDEX_HTML), encoding="utf-8")
    print(f"dashboard pre-start: {target} ({target.stat().st_size} octets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
