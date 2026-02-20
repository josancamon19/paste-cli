import subprocess


def get_frontmost_app() -> str | None:
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.localizedName()
    except Exception:
        return None


def get_browser_url(app_name: str) -> str | None:
    scripts = {
        "Google Chrome": 'tell application "Google Chrome" to get URL of active tab of front window',
        "Safari": 'tell application "Safari" to get URL of front document',
        "Arc": 'tell application "Arc" to get URL of active tab of front window',
        "Brave Browser": 'tell application "Brave Browser" to get URL of active tab of front window',
        "Microsoft Edge": 'tell application "Microsoft Edge" to get URL of active tab of front window',
        "Chromium": 'tell application "Chromium" to get URL of active tab of front window',
        "Opera": 'tell application "Opera" to get URL of active tab of front window',
        "Vivaldi": 'tell application "Vivaldi" to get URL of active tab of front window',
    }
    script = scripts.get(app_name)
    if not script:
        return None
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            return url if url else None
    except Exception:
        pass
    return None
