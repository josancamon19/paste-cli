from pathlib import Path

APP_DIR = Path.home() / ".pastepy"
DB_PATH = APP_DIR / "history.db"
PID_FILE = APP_DIR / "daemon.pid"
LOG_FILE = APP_DIR / "daemon.log"
LAUNCHD_LABEL = "com.pastepy.daemon"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
MAX_ITEM_SIZE = 100 * 1024  # 100KB
POLL_INTERVAL = 0.5  # seconds

BROWSER_APPS = frozenset({
    "Google Chrome",
    "Safari",
    "Arc",
    "Brave Browser",
    "Microsoft Edge",
    "Firefox",
    "Chromium",
    "Opera",
    "Vivaldi",
})
