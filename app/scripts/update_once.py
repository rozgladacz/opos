from __future__ import annotations

import sys

from ..services import update_service


def main() -> int:
    if len(sys.argv) != 2:
        print("Użycie: python -m app.scripts.update_once TASK_ID", file=sys.stderr)
        return 2
    update_service.run_update_service_sequence(sys.argv[1], claim_slot=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
