import curses
import textwrap
from datetime import datetime

from pastepy.db import bump_item, get_items


def _format_time(dt_str: str) -> str:
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        diff = now - dt
        if diff.days == 0:
            if diff.seconds < 60:
                return "just now"
            if diff.seconds < 3600:
                return f"{diff.seconds // 60}m ago"
            return f"{diff.seconds // 3600}h ago"
        if diff.days == 1:
            return "yesterday"
        if diff.days < 7:
            return f"{diff.days}d ago"
        return dt.strftime("%b %d")
    except Exception:
        return dt_str


def _preview(content: str, content_type: str, max_width: int) -> str:
    if content_type == "image":
        size_kb = len(content) * 3 // 4 // 1024
        return f"[Image: ~{size_kb}KB]"
    if content_type == "file":
        paths = content.split("\n")
        if len(paths) == 1:
            return f"[File: {paths[0]}]"
        return f"[{len(paths)} files]"
    line = content.replace("\n", " ").replace("\t", " ").strip()
    if len(line) > max_width:
        return line[: max_width - 1] + "\u2026"
    return line


def _type_badge(content_type: str) -> str:
    badges = {"text": "TXT", "image": "IMG", "file": "FILE"}
    return badges.get(content_type, content_type.upper())


def run_picker() -> dict | None:
    """Run the interactive curses picker. Returns the selected item dict or None."""
    return curses.wrapper(_picker_main)


def _picker_main(stdscr) -> dict | None:
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)  # selected
    curses.init_pair(2, curses.COLOR_CYAN, -1)  # header/accents
    curses.init_pair(3, curses.COLOR_WHITE, -1)  # dimmed
    curses.init_pair(4, curses.COLOR_YELLOW, -1)  # badge
    curses.init_pair(5, curses.COLOR_GREEN, -1)  # time

    search_query = ""
    selected_idx = 0
    scroll_offset = 0
    filter_type = None  # None = all
    filter_types = [None, "text", "image", "file"]
    filter_labels = ["All", "Text", "Image", "File"]
    filter_idx = 0

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < 6 or width < 30:
            stdscr.addstr(0, 0, "Terminal too small")
            stdscr.refresh()
            stdscr.getch()
            return None

        # Fetch items
        items = get_items(limit=200, search=search_query or None, content_type=filter_type)

        # Header
        header = " pst - clipboard history "
        stdscr.addstr(0, 0, " " * width, curses.color_pair(2))
        stdscr.addstr(0, max(0, (width - len(header)) // 2), header, curses.color_pair(2) | curses.A_BOLD)

        # Search bar
        search_display = f" Search: {search_query}\u2588"
        stdscr.addstr(1, 0, " " * width)
        stdscr.addstr(1, 0, search_display[:width - 1])

        # Filter tabs
        tab_line = " "
        for i, label in enumerate(filter_labels):
            if i == filter_idx:
                tab_line += f"[{label}] "
            else:
                tab_line += f" {label}  "
        stdscr.addstr(2, 0, " " * width)
        for i, label in enumerate(filter_labels):
            pos = 1 + sum(len(filter_labels[j]) + 3 for j in range(i))
            if i == filter_idx:
                stdscr.addstr(2, pos, f"[{label}]", curses.color_pair(2) | curses.A_BOLD)
            else:
                stdscr.addstr(2, pos, f" {label} ", curses.color_pair(3))

        # Separator
        stdscr.addstr(3, 0, "\u2500" * min(width, width - 1), curses.color_pair(3))

        # Items list
        list_start = 4
        list_height = height - list_start - 2  # reserve 2 for footer
        item_height = 2  # lines per item
        visible_count = max(1, list_height // item_height)

        # Clamp selection
        if items:
            selected_idx = max(0, min(selected_idx, len(items) - 1))
            if selected_idx < scroll_offset:
                scroll_offset = selected_idx
            if selected_idx >= scroll_offset + visible_count:
                scroll_offset = selected_idx - visible_count + 1
        else:
            selected_idx = 0
            scroll_offset = 0

        if not items:
            msg = "No items found" if search_query else "Clipboard history is empty"
            stdscr.addstr(list_start + 1, 2, msg, curses.color_pair(3))
        else:
            for vi in range(visible_count):
                idx = scroll_offset + vi
                if idx >= len(items):
                    break
                item = items[idx]
                y = list_start + vi * item_height
                if y + 1 >= height - 2:
                    break

                is_selected = idx == selected_idx
                attr = curses.color_pair(1) if is_selected else 0
                pointer = "\u25b8 " if is_selected else "  "

                # Line 1: pointer + content preview
                preview = _preview(item["content"], item["content_type"], width - 14)
                badge = _type_badge(item["content_type"])
                line1 = f"{pointer}{preview}"
                stdscr.addstr(y, 0, " " * min(width, width - 1), attr)
                try:
                    stdscr.addnstr(y, 0, line1, width - 7, attr)
                    stdscr.addnstr(y, max(0, width - 6), f" {badge:>4} ", 6, attr | curses.A_DIM)
                except curses.error:
                    pass

                # Line 2: metadata (time, app, url)
                time_str = _format_time(item["last_used_at"])
                meta = f"    {time_str}"
                if item["source_app"]:
                    meta += f" \u00b7 {item['source_app']}"
                if item["source_url"]:
                    url = item["source_url"]
                    # Show just the domain
                    try:
                        from urllib.parse import urlparse
                        domain = urlparse(url).netloc
                        if domain:
                            meta += f" \u00b7 {domain}"
                    except Exception:
                        pass
                meta_attr = (curses.color_pair(1) | curses.A_DIM) if is_selected else (curses.color_pair(3) | curses.A_DIM)
                stdscr.addstr(y + 1, 0, " " * min(width, width - 1), curses.color_pair(1) if is_selected else 0)
                try:
                    stdscr.addnstr(y + 1, 0, meta, width - 1, meta_attr)
                except curses.error:
                    pass

        # Footer
        footer_y = height - 1
        count_str = f" {len(items)} items"
        footer = " \u2191\u2193 Navigate \u00b7 Enter Select \u00b7 Tab Filter \u00b7 Esc Quit"
        stdscr.addstr(footer_y, 0, " " * min(width, width - 1), curses.color_pair(3) | curses.A_DIM)
        try:
            stdscr.addnstr(footer_y, 0, footer, width - len(count_str) - 1, curses.color_pair(3) | curses.A_DIM)
            stdscr.addnstr(footer_y, max(0, width - len(count_str) - 1), count_str, len(count_str) + 1, curses.color_pair(5) | curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()

        # Handle input
        key = stdscr.getch()

        if key == 27:  # Escape
            return None
        elif key == curses.KEY_UP or key == 16:  # Up or Ctrl+P
            selected_idx = max(0, selected_idx - 1)
        elif key == curses.KEY_DOWN or key == 14:  # Down or Ctrl+N
            if items:
                selected_idx = min(len(items) - 1, selected_idx + 1)
        elif key == 9:  # Tab - cycle filter
            filter_idx = (filter_idx + 1) % len(filter_types)
            filter_type = filter_types[filter_idx]
            selected_idx = 0
            scroll_offset = 0
        elif key == curses.KEY_BTAB:  # Shift+Tab - reverse cycle
            filter_idx = (filter_idx - 1) % len(filter_types)
            filter_type = filter_types[filter_idx]
            selected_idx = 0
            scroll_offset = 0
        elif key in (curses.KEY_ENTER, 10, 13):  # Enter
            if items:
                item = items[selected_idx]
                return dict(item)
            return None
        elif key in (curses.KEY_BACKSPACE, 127, 8):  # Backspace
            if search_query:
                search_query = search_query[:-1]
                selected_idx = 0
                scroll_offset = 0
        elif key == 21:  # Ctrl+U - clear search
            search_query = ""
            selected_idx = 0
            scroll_offset = 0
        elif key == curses.KEY_PPAGE:  # Page Up
            selected_idx = max(0, selected_idx - visible_count)
        elif key == curses.KEY_NPAGE:  # Page Down
            if items:
                selected_idx = min(len(items) - 1, selected_idx + visible_count)
        elif 32 <= key <= 126:  # Printable character
            search_query += chr(key)
            selected_idx = 0
            scroll_offset = 0


def copy_to_clipboard(content: str, content_type: str) -> None:
    """Copy content back to the system clipboard."""
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString
        import base64

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()

        if content_type == "text" or content_type == "file":
            pb.setString_forType_(content, NSPasteboardTypeString)
        elif content_type == "image":
            from AppKit import NSData, NSPasteboardTypePNG
            raw = base64.b64decode(content)
            data = NSData.dataWithBytes_length_(raw, len(raw))
            pb.setData_forType_(data, NSPasteboardTypePNG)
    except Exception as e:
        print(f"Failed to copy to clipboard: {e}")
