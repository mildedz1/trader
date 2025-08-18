import os
import sys
import time

HEARTBEAT_PATH = os.getenv("HEARTBEAT_PATH", "/data/heartbeat")
TICK_INTERVAL_SEC = float(os.getenv("TICK_INTERVAL_SEC", "15"))
GRACE_MULTIPLIER = 3


def main() -> int:
    try:
        if not os.path.exists(HEARTBEAT_PATH):
            print("heartbeat missing", file=sys.stderr)
            return 1
        mtime = os.path.getmtime(HEARTBEAT_PATH)
        age = time.time() - mtime
        if age > TICK_INTERVAL_SEC * GRACE_MULTIPLIER:
            print(f"heartbeat stale: age={age:.1f}s", file=sys.stderr)
            return 2
        print("ok")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"healthcheck error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())