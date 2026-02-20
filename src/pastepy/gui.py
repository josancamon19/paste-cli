"""Native macOS overlay picker for pastepy."""

import os
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*PyObjCPointer.*")

import objc  # noqa: E402
from AppKit import (  # noqa: E402
    NSApplication,
    NSBackingStoreBuffered,
    NSColor,
    NSFont,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSScrollView,
    NSTextField,
    NSTrackingArea,
    NSView,
    NSVisualEffectView,
    NSWorkspace,
)
from Foundation import NSObject  # noqa: E402
from Quartz import (  # noqa: E402
    CGColorCreateGenericRGB,
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
)

from pastepy.db import bump_item, get_items, init_db
from pastepy.picker import _format_time, copy_to_clipboard

# Layout
CARD_W = 200
CARD_H = 130
CARD_GAP = 12
PAD = 20

# Colors (pre-built CGColors for layer use)
CLR_SELECTED_BG = CGColorCreateGenericRGB(0.2, 0.5, 1.0, 0.30)
CLR_SELECTED_BORDER = CGColorCreateGenericRGB(0.35, 0.6, 1.0, 0.9)
CLR_NORMAL_BG = CGColorCreateGenericRGB(1.0, 1.0, 1.0, 0.06)
CLR_HOVER_BG = CGColorCreateGenericRGB(1.0, 1.0, 1.0, 0.12)

# NSTrackingArea options
TRACKING_MOUSE_ENTERED_EXITED = 0x01
TRACKING_ACTIVE_ALWAYS = 0x80

# Modifier flag masks
CMD_FLAG = 1 << 20


def _simulate_paste():
    """Simulate Cmd+V to paste into the frontmost app."""
    time.sleep(0.15)
    # keycode 9 = 'v'
    down = CGEventCreateKeyboardEvent(None, 9, True)
    CGEventSetFlags(down, CMD_FLAG)
    CGEventPost(0, down)  # kCGHIDEventTap
    up = CGEventCreateKeyboardEvent(None, 9, False)
    CGEventSetFlags(up, CMD_FLAG)
    CGEventPost(0, up)


# ── Card view with mouse tracking ───────────────────────────────


class CardView(NSView):
    """A card that responds to mouse hover and click."""

    def initWithFrame_(self, frame):
        self = objc.super(CardView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._pst_controller = None
        self._pst_index = 0
        return self

    def updateTrackingAreas(self):
        for area in self.trackingAreas():
            self.removeTrackingArea_(area)
        area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            TRACKING_MOUSE_ENTERED_EXITED | TRACKING_ACTIVE_ALWAYS,
            self,
            None,
        )
        self.addTrackingArea_(area)
        objc.super(CardView, self).updateTrackingAreas()

    def mouseEntered_(self, event):
        if self._pst_controller:
            self._pst_controller.set_selection(self._pst_index)

    def mouseDown_(self, event):
        if self._pst_controller:
            self._pst_controller.copy_only()


# ── Panel ────────────────────────────────────────────────────────


class OverlayPanel(NSPanel):
    """Borderless floating panel that accepts keyboard input."""

    controller = objc.ivar()

    def canBecomeKeyWindow(self):
        return True

    def keyDown_(self, event):
        ctrl = self.controller
        if ctrl is None:
            return
        kc = event.keyCode()
        flags = event.modifierFlags()
        has_cmd = bool(flags & CMD_FLAG)
        chars = event.characters()

        if kc == 53:  # Esc
            ctrl.cancel()
        elif kc == 36:  # Enter → copy + paste
            ctrl.copy_and_paste()
        elif has_cmd and kc == 8:  # Cmd+C → copy only
            ctrl.copy_only()
        elif has_cmd:
            pass  # ignore other Cmd combos (don't type in search)
        elif kc == 123:  # Left
            ctrl.move_selection(-1)
        elif kc == 124:  # Right
            ctrl.move_selection(1)
        elif kc == 48:  # Tab
            ctrl.cycle_filter()
        elif kc == 51:  # Backspace
            ctrl.backspace_search()
        elif chars:
            c = str(chars)
            if len(c) == 1 and c.isprintable() and ord(c) >= 32:
                ctrl.type_search(c)


# ── Controller ───────────────────────────────────────────────────


class OverlayController(NSObject):
    """Manages the overlay panel, cards, and user interaction."""

    def init(self):
        self = objc.super(OverlayController, self).init()
        if self is None:
            return None
        self._items = []
        self._cards = []
        self._selected = 0
        self._search = ""
        self._filter_type = None
        self._filter_idx = 0
        self._filters = [None, "text", "image", "file"]
        self._filter_names = ["All", "Text", "Image", "File"]
        self._panel = None
        self._scroll = None
        self._doc = None
        self._search_label = None
        self._filter_label = None
        self._count_label = None
        self._previous_app = None
        self._should_paste = False
        return self

    @objc.python_method
    def show(self):
        # Remember the app that was active before us
        self._previous_app = NSWorkspace.sharedWorkspace().frontmostApplication()

        screen = NSScreen.mainScreen()
        sf = screen.frame()
        vf = screen.visibleFrame()
        sw = sf.size.width
        panel_h = CARD_H + PAD * 2 + 68

        panel = OverlayPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, vf.origin.y, sw, panel_h),
            0,  # borderless
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(25)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setCollectionBehavior_(1 << 0 | 1 << 8)
        panel.setAcceptsMouseMovedEvents_(True)
        panel.controller = self
        self._panel = panel

        cv = panel.contentView()

        # Blurred background
        blur = NSVisualEffectView.alloc().initWithFrame_(cv.bounds())
        blur.setBlendingMode_(1)  # behindWindow
        blur.setMaterial_(13)  # HUD window
        blur.setState_(1)  # active
        blur.setAutoresizingMask_(18)
        cv.addSubview_(blur)

        # ── Top bar ──
        y = panel_h - PAD - 18

        # Title
        title = self._make_label("Clipboard", 14, NSColor.whiteColor(), bold=True)
        title.setFrame_(NSMakeRect(PAD, y, 100, 20))
        cv.addSubview_(title)

        # Search
        self._search_label = self._make_label("", 13, NSColor.whiteColor())
        self._search_label.setFrame_(NSMakeRect(PAD + 108, y, sw * 0.4, 20))
        cv.addSubview_(self._search_label)

        # Item count
        self._count_label = self._make_label(
            "", 12, NSColor.systemGreenColor().colorWithAlphaComponent_(0.8)
        )
        self._count_label.setFrame_(NSMakeRect(sw - 120, y, 100, 20))
        self._count_label.setAlignment_(2)
        cv.addSubview_(self._count_label)

        # Filter tabs
        y -= 22
        self._filter_label = self._make_label("", 11, NSColor.secondaryLabelColor())
        self._filter_label.setFrame_(NSMakeRect(PAD, y, sw - PAD * 2, 18))
        cv.addSubview_(self._filter_label)

        # ── Cards scroll area ──
        scroll_h = CARD_H + PAD
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 18, sw, scroll_h))
        scroll.setHasHorizontalScroller_(False)
        scroll.setHasVerticalScroller_(False)
        scroll.setDrawsBackground_(False)
        cv.addSubview_(scroll)
        self._scroll = scroll

        doc = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, sw, scroll_h))
        scroll.setDocumentView_(doc)
        self._doc = doc

        # ── Footer ──
        footer = self._make_label(
            " \u2190 \u2192 Navigate  \u00b7  Enter Paste  \u00b7  \u2318C Copy  \u00b7  Click Copy  \u00b7  Tab Filter  \u00b7  Esc Close",
            10,
            NSColor.tertiaryLabelColor(),
        )
        footer.setFrame_(NSMakeRect(PAD, 2, sw - PAD * 2, 14))
        cv.addSubview_(footer)

        self._refresh()
        panel.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    @objc.python_method
    def _make_label(self, text, size, color, bold=False):
        tf = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 20))
        tf.setStringValue_(text)
        tf.setBezeled_(False)
        tf.setDrawsBackground_(False)
        tf.setEditable_(False)
        tf.setSelectable_(False)
        if bold:
            tf.setFont_(NSFont.boldSystemFontOfSize_(size))
        else:
            tf.setFont_(NSFont.systemFontOfSize_(size))
        tf.setTextColor_(color)
        return tf

    @objc.python_method
    def _refresh(self):
        items = get_items(
            limit=100,
            search=self._search or None,
            content_type=self._filter_type,
        )
        self._items = [dict(i) for i in items]
        self._selected = min(self._selected, max(0, len(self._items) - 1))
        self._build_cards()
        self._update_labels()

    @objc.python_method
    def _build_cards(self):
        for c in self._cards:
            c.removeFromSuperview()
        self._cards = []

        x = PAD
        scroll_h = self._doc.frame().size.height
        card_y = (scroll_h - CARD_H) / 2

        for i, item in enumerate(self._items):
            card = CardView.alloc().initWithFrame_(NSMakeRect(x, card_y, CARD_W, CARD_H))
            card._pst_controller = self
            card._pst_index = i
            card.setWantsLayer_(True)
            card.layer().setCornerRadius_(12)

            # ── Content preview ──
            content = item["content"]
            ctype = item["content_type"]
            size_bytes = item.get("size_bytes") or len(
                content.encode("utf-8", errors="replace")
            )

            if ctype == "image":
                raw_kb = len(content) * 3 // 4 // 1024
                preview = f"[Image \u2013 ~{raw_kb}KB]"
            elif ctype == "file":
                paths = content.split("\n")
                name = paths[0].split("/")[-1] if paths else "[File]"
                preview = (
                    name if len(paths) == 1 else f"{name} +{len(paths) - 1} more"
                )
            else:
                preview = content.replace("\n", "\u23ce ").replace("\t", " ").strip()
                if len(preview) > 120:
                    preview = preview[:119] + "\u2026"

            pl = NSTextField.wrappingLabelWithString_(preview)
            pl.setFrame_(NSMakeRect(12, 38, CARD_W - 24, CARD_H - 48))
            pl.setFont_(NSFont.monospacedSystemFontOfSize_weight_(11, 0.0))
            pl.setTextColor_(NSColor.whiteColor().colorWithAlphaComponent_(0.9))
            pl.setMaximumNumberOfLines_(4)
            card.addSubview_(pl)

            # ── Size info ──
            if ctype == "text":
                char_count = len(content)
                size_str = (
                    f"{char_count} chars"
                    if char_count < 1000
                    else f"{char_count:,} chars"
                )
            elif ctype == "image":
                size_str = (
                    f"{size_bytes // 1024}KB" if size_bytes >= 1024 else f"{size_bytes}B"
                )
            else:
                n_files = len(content.split("\n"))
                size_str = f"{n_files} file{'s' if n_files > 1 else ''}"

            sl = self._make_label(
                size_str,
                9,
                NSColor.systemYellowColor().colorWithAlphaComponent_(0.5),
            )
            sl.setFrame_(NSMakeRect(12, 22, CARD_W - 24, 14))
            card.addSubview_(sl)

            # ── Bottom row: badge · app · time ──
            badges = {"text": "TXT", "image": "IMG", "file": "FILE"}
            bl = self._make_label(
                badges.get(ctype, "?"), 9, NSColor.systemGrayColor(), bold=True
            )
            bl.setFrame_(NSMakeRect(12, 6, 35, 14))
            card.addSubview_(bl)

            app_name = item.get("source_app") or ""
            if item.get("source_url"):
                try:
                    from urllib.parse import urlparse

                    domain = urlparse(item["source_url"]).netloc
                    if domain:
                        app_name = domain
                except Exception:
                    pass
            if app_name:
                al = self._make_label(app_name[:20], 9, NSColor.secondaryLabelColor())
                al.setFrame_(NSMakeRect(48, 6, 95, 14))
                card.addSubview_(al)

            tl = self._make_label(
                _format_time(item["last_used_at"]),
                9,
                NSColor.systemGreenColor().colorWithAlphaComponent_(0.6),
            )
            tl.setFrame_(NSMakeRect(CARD_W - 62, 6, 50, 14))
            tl.setAlignment_(2)
            card.addSubview_(tl)

            self._doc.addSubview_(card)
            self._cards.append(card)
            x += CARD_W + CARD_GAP

        total_w = max(x + PAD, self._scroll.frame().size.width)
        self._doc.setFrameSize_((total_w, self._doc.frame().size.height))
        self._highlight()
        self._scroll_to()

    @objc.python_method
    def _highlight(self):
        for i, card in enumerate(self._cards):
            layer = card.layer()
            if i == self._selected:
                layer.setBackgroundColor_(CLR_SELECTED_BG)
                layer.setBorderWidth_(2)
                layer.setBorderColor_(CLR_SELECTED_BORDER)
            else:
                layer.setBackgroundColor_(CLR_NORMAL_BG)
                layer.setBorderWidth_(0)

    @objc.python_method
    def _scroll_to(self):
        if not self._cards:
            return
        f = self._cards[self._selected].frame()
        expanded = NSMakeRect(
            f.origin.x - CARD_GAP,
            f.origin.y,
            f.size.width + CARD_GAP * 2,
            f.size.height,
        )
        self._doc.scrollRectToVisible_(expanded)

    @objc.python_method
    def _update_labels(self):
        if self._search:
            self._search_label.setStringValue_(f"\u2315  {self._search}\u2588")
        else:
            self._search_label.setStringValue_("\u2315  Type to search\u2026")
            self._search_label.setTextColor_(
                NSColor.whiteColor().colorWithAlphaComponent_(0.3)
            )
        if self._search:
            self._search_label.setTextColor_(NSColor.whiteColor())

        ft = "  ".join(
            f"[{n}]" if i == self._filter_idx else f" {n} "
            for i, n in enumerate(self._filter_names)
        )
        self._filter_label.setStringValue_(ft)
        self._count_label.setStringValue_(f"{len(self._items)} items")

    # ── Actions ──

    @objc.python_method
    def set_selection(self, index):
        """Mouse hover: update selection."""
        if 0 <= index < len(self._items):
            self._selected = index
            self._highlight()

    @objc.python_method
    def move_selection(self, delta):
        if not self._items:
            return
        self._selected = max(0, min(len(self._items) - 1, self._selected + delta))
        self._highlight()
        self._scroll_to()

    @objc.python_method
    def copy_only(self):
        """Cmd+C or Click: copy to clipboard, close. Don't paste."""
        if not self._items:
            return
        item = self._items[self._selected]
        copy_to_clipboard(item["content"], item["content_type"])
        bump_item(item["id"])
        self._close()

    @objc.python_method
    def copy_and_paste(self):
        """Enter: copy to clipboard, close, then paste into the previous app."""
        if not self._items:
            return
        item = self._items[self._selected]
        copy_to_clipboard(item["content"], item["content_type"])
        bump_item(item["id"])
        self._should_paste = True
        self._close_for_paste()

    @objc.python_method
    def cancel(self):
        self._close()

    @objc.python_method
    def type_search(self, char):
        self._search += char
        self._selected = 0
        self._refresh()

    @objc.python_method
    def backspace_search(self):
        if self._search:
            self._search = self._search[:-1]
            self._selected = 0
            self._refresh()

    @objc.python_method
    def cycle_filter(self):
        self._filter_idx = (self._filter_idx + 1) % len(self._filters)
        self._filter_type = self._filters[self._filter_idx]
        self._selected = 0
        self._refresh()

    # ── Exit helpers ──

    @objc.python_method
    def _close(self):
        """Close overlay, reactivate previous app, terminate."""
        self._panel.orderOut_(None)
        self._restore_focus()
        NSApplication.sharedApplication().terminate_(None)

    @objc.python_method
    def _close_for_paste(self):
        """Close overlay, reactivate previous app, stop run loop (don't terminate)."""
        self._panel.orderOut_(None)
        self._restore_focus()
        # Use stop_ instead of terminate_ so main() continues and can simulate paste
        app = NSApplication.sharedApplication()
        app.stop_(None)
        # Post a dummy event to unblock the run loop
        from AppKit import NSEvent, NSMakePoint

        dummy = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            15, NSMakePoint(0, 0), 0, 0, 0, None, 0, 0, 0  # NSApplicationDefined
        )
        app.postEvent_atStart_(dummy, True)

    @objc.python_method
    def _restore_focus(self):
        """Give focus back to the app that was active before the picker."""
        if self._previous_app:
            self._previous_app.activateWithOptions_(2)  # ignoring other apps


# ── App delegate ─────────────────────────────────────────────────


class AppDelegate(NSObject):
    controller = objc.ivar()

    def applicationDidFinishLaunching_(self, notification):
        self.controller = OverlayController.alloc().init()
        self.controller.show()


# ── Entry point ──────────────────────────────────────────────────


def main():
    init_db()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(1)  # no dock icon

    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()

    # If we get here (via stop_), check if we should paste
    ctrl = delegate.controller
    if ctrl and ctrl._should_paste:
        time.sleep(0.15)
        _simulate_paste()


if __name__ == "__main__":
    main()
