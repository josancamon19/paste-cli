import base64
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

from pastepy.config import BROWSER_APPS, MAX_ITEM_SIZE, PID_FILE, POLL_INTERVAL
from pastepy.db import add_item, init_db
from pastepy.source import get_browser_url, get_frontmost_app


def _open_picker() -> None:
    """Open the native GUI overlay picker."""
    subprocess.Popen(
        [sys.executable, "-m", "pastepy.gui"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _start_hotkey_listener() -> None:
    """Listen for Cmd+Ctrl+V globally and open the picker."""
    try:
        from pynput import keyboard

        pressed = set()

        def on_press(key):
            pressed.add(key)
            # Cmd+Ctrl+V
            if (
                keyboard.Key.cmd in pressed
                and keyboard.Key.ctrl in pressed
                and hasattr(key, "char")
                and key.char == "v"
            ):
                _open_picker()

        def on_release(key):
            pressed.discard(key)

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()
    except Exception:
        pass


class ClipboardMonitor:
    def __init__(self) -> None:
        self.last_hash: str | None = None
        self.last_change_count: int = -1
        self.running = False
        init_db()

    def _get_clipboard_content(self) -> tuple[str | None, str | None]:
        try:
            from AppKit import NSPasteboard

            pb = NSPasteboard.generalPasteboard()

            change_count = pb.changeCount()
            if change_count == self.last_change_count:
                return None, None
            self.last_change_count = change_count

            # Check for file URLs first
            file_urls = pb.propertyListForType_("NSFilenamesPboardType")
            if file_urls:
                content = "\n".join(str(f) for f in file_urls)
                if len(content.encode("utf-8")) <= MAX_ITEM_SIZE:
                    return content, "file"

            # Check for text
            text = pb.stringForType_("public.utf8-plain-text")
            if text:
                content = str(text)
                if len(content.encode("utf-8")) <= MAX_ITEM_SIZE:
                    return content, "text"

            # Check for images (PNG then TIFF)
            for img_type in ["public.png", "public.tiff"]:
                data = pb.dataForType_(img_type)
                if data:
                    raw = bytes(data)
                    if len(raw) <= MAX_ITEM_SIZE:
                        return base64.b64encode(raw).decode("ascii"), "image"

        except Exception:
            pass
        return None, None

    def _compute_hash(self, content: str) -> str:
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def start(self) -> None:
        self.running = True
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # Start global hotkey listener (Cmd+Shift+V)
        _start_hotkey_listener()

        pid = os.getpid()
        print(f"Clipboard monitor started (PID: {pid})")
        print("Hotkey: Cmd+Ctrl+V to open picker")

        while self.running:
            try:
                content, content_type = self._get_clipboard_content()
                if content:
                    content_hash = self._compute_hash(content)
                    if content_hash != self.last_hash:
                        self.last_hash = content_hash
                        source_app = get_frontmost_app()
                        source_url = None
                        if source_app and source_app in BROWSER_APPS:
                            source_url = get_browser_url(source_app)
                        size_bytes = len(content.encode("utf-8"))
                        add_item(
                            content,
                            content_type,
                            source_app,
                            source_url,
                            size_bytes,
                            content_hash,
                        )
            except Exception:
                pass
            time.sleep(POLL_INTERVAL)

    def _handle_signal(self, signum: int, frame) -> None:
        self.running = False
        PID_FILE.unlink(missing_ok=True)
        print("\nClipboard monitor stopped.")
        sys.exit(0)


def stop_daemon() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink(missing_ok=True)
        return True
    except (ProcessLookupError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False


def is_running() -> tuple[bool, int | None]:
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return True, pid
        except (ProcessLookupError, ValueError):
            PID_FILE.unlink(missing_ok=True)
    return False, None
