#!/usr/bin/env python3
"""
Claude Code Network Monitor - Desktop Floating Bubble

A small draggable floating circle on your macOS desktop that monitors
ALL active Claude Code sessions for network errors in real time.

Colors:
  Green  = all sessions OK
  Yellow = some sessions retrying
  Red    = all sessions retrying

Interactions:
  Drag       = move the bubble anywhere
  Hover      = tooltip with session summary
  Double-click = detailed network event log

How it works:
  Reads ~/.claude/projects/*//*.jsonl session logs every 2 seconds.
  Compares the last api_error timestamp vs the last successful assistant
  response timestamp to determine if a session is actively retrying.

Note: This relies on Claude Code's internal JSONL transcript format,
which is not a public API and may change between versions.
"""

import subprocess
import json
import os
import glob
import time
import objc
from AppKit import (
    NSApplication, NSWindow, NSPanel, NSView, NSColor, NSBezierPath,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskFullSizeContentView,
    NSBackingStoreBuffered,
    NSFloatingWindowLevel, NSScreen, NSTimer,
    NSMakeRect, NSFont,
    NSTextField, NSScrollView, NSTextView,
    NSTrackingArea, NSTrackingMouseEnteredAndExited, NSTrackingActiveAlways,
    NSMutableAttributedString, NSAttributedString,
    NSFontAttributeName, NSForegroundColorAttributeName,
    NSCursor,
)
from Foundation import NSObject, NSMutableDictionary
import signal

# --- Configuration ---
BUBBLE_SIZE = 20          # Final bubble diameter in pixels
BUBBLE_START_SIZE = 80    # Startup animation initial size
CHECK_INTERVAL = 2.0      # Seconds between status checks
ANIM_STEPS = 12           # Entrance animation frames
ANIM_INTERVAL = 0.03      # Seconds per animation frame
ACTIVE_WINDOW_SECS = 600  # Sessions active within this window (10 min)


# --- Session detection & status checking ---

def find_active_sessions():
    """Find all recently active JSONL session files."""
    project_dir = os.path.expanduser("~/.claude/projects")
    jsonl_files = glob.glob(os.path.join(project_dir, "*", "*.jsonl"))
    now = time.time()
    active = []
    for f in jsonl_files:
        try:
            if now - os.path.getmtime(f) < ACTIVE_WINDOW_SECS:
                active.append(f)
        except OSError:
            continue
    active.sort(key=os.path.getmtime, reverse=True)
    return active


def check_session_status(jsonl_path):
    """Check one session. Returns ('ok'|'retry', summary_string)."""
    try:
        result = subprocess.run(
            ["tail", "-n", "50", jsonl_path],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n")
    except Exception:
        return ("ok", "read error")

    last_err = None
    last_ok_ts = None
    session_slug = None

    for line in lines:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not session_slug:
            session_slug = entry.get("slug", "")
        if entry.get("type") == "system" and entry.get("subtype") == "api_error":
            retry = entry.get("retryAttempt", 0)
            max_retry = entry.get("maxRetries", 10)
            ts = entry.get("timestamp", "")
            last_err = {"retry": retry, "max": max_retry, "ts": ts}
        if (entry.get("type") == "assistant"
                and entry.get("message", {}).get("stop_reason") is not None):
            last_ok_ts = entry.get("timestamp", "")

    name = session_slug or os.path.basename(jsonl_path)[:12]
    if last_err:
        if not last_ok_ts or last_err["ts"] > last_ok_ts:
            return ("retry", f"{name}: RETRY {last_err['retry']}/{last_err['max']}")
    return ("ok", f"{name}: OK")


def get_session_detail(jsonl_path):
    """Get detailed network event log for the double-click panel."""
    try:
        result = subprocess.run(
            ["tail", "-n", "100", jsonl_path],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n")
    except Exception:
        return None, []

    events = []
    session_slug = None
    for line in lines:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not session_slug:
            session_slug = entry.get("slug", "")
        if entry.get("type") == "system" and entry.get("subtype") == "api_error":
            ts = entry.get("timestamp", "")[11:19]
            retry = entry.get("retryAttempt", 0)
            max_r = entry.get("maxRetries", 10)
            code = (entry.get("cause", {}).get("code")
                    or entry.get("error", {}).get("cause", {}).get("code")
                    or "ERR")
            events.append(("err", f"  {ts}  ERR  {code}  retry {retry}/{max_r}"))
        if (entry.get("type") == "assistant"
                and entry.get("message", {}).get("stop_reason") is not None):
            ts = entry.get("timestamp", "")[11:19]
            events.append(("ok", f"  {ts}  OK   response received"))

    return session_slug, events


def check_all_sessions():
    """Check all active sessions. Returns (status, tooltip, session_paths)."""
    sessions = find_active_sessions()
    if not sessions:
        return ("ok", "No active sessions", [])

    results = []
    has_retry = False
    all_retry = True

    for s in sessions:
        status, detail = check_session_status(s)
        results.append((status, detail))
        if status == "retry":
            has_retry = True
        else:
            all_retry = False

    if not has_retry:
        all_retry = False

    tooltip = "\n".join(d for _, d in results)
    count = len(results)
    summary = f"{count} session{'s' if count > 1 else ''}"

    if has_retry and all_retry:
        return ("retry", f"{summary}\n{tooltip}", sessions)
    elif has_retry:
        return ("warn", f"{summary}\n{tooltip}", sessions)
    else:
        return ("ok", f"{summary}\n{tooltip}", sessions)


# --- UI ---

class BubbleView(NSView):
    _delegate_ref = None

    def initWithFrame_(self, frame):
        self = objc.super(BubbleView, self).initWithFrame_(frame)
        if self:
            self._color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.2, 0.8, 0.3, 0.9)
            self._drag_start = None
        return self

    def setColor_(self, color):
        self._color = color
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        path = NSBezierPath.bezierPathWithOvalInRect_(self.bounds())
        self._color.set()
        path.fill()
        NSColor.colorWithCalibratedWhite_alpha_(0.3, 0.5).set()
        path.setLineWidth_(1.0)
        path.stroke()

    def mouseDown_(self, event):
        if event.clickCount() == 2:
            if self._delegate_ref:
                self._delegate_ref.showDetailPanel()
        else:
            self._drag_start = event.locationInWindow()

    def mouseDragged_(self, event):
        window = self.window()
        if not window or not self._drag_start:
            return
        screen_loc = event.locationInWindow()
        origin = window.frame().origin
        dx = screen_loc.x - self._drag_start.x
        dy = screen_loc.y - self._drag_start.y
        window.setFrameOrigin_((origin.x + dx, origin.y + dy))

    def acceptsFirstMouse_(self, event):
        return True


# --- Detail Panel UI ---

PANEL_WIDTH = 420
PANEL_HEIGHT = 480
PANEL_CORNER_RADIUS = 14

# Color palette for the detail panel
_COLORS = {
    "bg":         (0.10, 0.10, 0.12, 0.94),
    "title":      (0.92, 0.92, 0.95, 1.0),
    "subtitle":   (0.55, 0.55, 0.60, 1.0),
    "separator":  (0.25, 0.25, 0.30, 0.6),
    "ok_dot":     (0.30, 0.82, 0.40, 1.0),
    "err_dot":    (0.95, 0.30, 0.25, 1.0),
    "ok_text":    (0.55, 0.78, 0.55, 1.0),
    "err_text":   (0.95, 0.50, 0.45, 1.0),
    "log_text":   (0.72, 0.72, 0.76, 1.0),
    "session":    (0.85, 0.85, 0.90, 1.0),
    "close_bg":   (0.20, 0.20, 0.24, 1.0),
    "close_hover":(0.30, 0.30, 0.35, 1.0),
    "close_text": (0.60, 0.60, 0.65, 1.0),
    "badge_err":  (0.95, 0.30, 0.25, 0.15),
    "badge_ok":   (0.30, 0.82, 0.40, 0.12),
    "empty":      (0.45, 0.45, 0.50, 0.7),
    "scrollbar":  (0.35, 0.35, 0.40, 0.5),
}

def _c(name):
    """Get an NSColor from the palette."""
    r, g, b, a = _COLORS[name]
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)


class CloseButton(NSView):
    """Custom close button with hover effect."""
    _hovered = False
    _action_target = None

    def initWithFrame_(self, frame):
        self = objc.super(CloseButton, self).initWithFrame_(frame)
        if self:
            self._hovered = False
            area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(),
                NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways,
                self, None
            )
            self.addTrackingArea_(area)
        return self

    def drawRect_(self, rect):
        bg = _c("close_hover") if self._hovered else _c("close_bg")
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), 6, 6)
        bg.set()
        path.fill()

        # Draw "×" symbol
        _c("close_text").set()
        font = NSFont.fontWithName_size_("Menlo", 13)
        if not font:
            font = NSFont.systemFontOfSize_(13)
        attrs = NSMutableDictionary.alloc().init()
        attrs[NSFontAttributeName] = font
        attrs[NSForegroundColorAttributeName] = (
            _c("title") if self._hovered else _c("close_text"))
        s = NSAttributedString.alloc().initWithString_attributes_("✕", attrs)
        b = self.bounds()
        sz = s.size()
        s.drawAtPoint_((
            b.origin.x + (b.size.width - sz.width) / 2,
            b.origin.y + (b.size.height - sz.height) / 2 - 0.5
        ))

    def mouseEntered_(self, event):
        self._hovered = True
        NSCursor.pointingHandCursor().set()
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self._hovered = False
        NSCursor.arrowCursor().set()
        self.setNeedsDisplay_(True)

    def mouseDown_(self, event):
        if self._action_target:
            self._action_target.closePanel()

    def resetCursorRects(self):
        self.addCursorRect_cursor_(self.bounds(), NSCursor.pointingHandCursor())


class RoundedPanelView(NSView):
    """Background view with rounded corners and dark fill."""
    def drawRect_(self, rect):
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), PANEL_CORNER_RADIUS, PANEL_CORNER_RADIUS)
        _c("bg").set()
        path.fill()
        # Subtle inner border
        NSColor.colorWithCalibratedWhite_alpha_(0.25, 0.15).set()
        path.setLineWidth_(0.5)
        path.stroke()


def _build_detail_attributed_string(sessions):
    """Build a rich NSMutableAttributedString from session data."""
    result = NSMutableAttributedString.alloc().init()

    mono = NSFont.fontWithName_size_("SF Mono", 11.5)
    if not mono:
        mono = NSFont.fontWithName_size_("Menlo", 11.5)
    mono_sm = NSFont.fontWithName_size_("SF Mono", 10.5)
    if not mono_sm:
        mono_sm = NSFont.fontWithName_size_("Menlo", 10.5)
    label_font = NSFont.fontWithName_size_("SF Pro Text", 13) or NSFont.systemFontOfSize_(13)
    label_bold = NSFont.boldSystemFontOfSize_(13)

    def _append(text, font, color):
        attrs = NSMutableDictionary.alloc().init()
        attrs[NSFontAttributeName] = font
        attrs[NSForegroundColorAttributeName] = color
        seg = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        result.appendAttributedString_(seg)

    if not sessions:
        _append("No active sessions found", mono, _c("empty"))
        return result

    first_session = True
    for s in sessions:
        slug, events = get_session_detail(s)
        name = slug or os.path.basename(s)[:24]
        err_count = sum(1 for t, _ in events if t == "err")
        ok_count = sum(1 for t, _ in events if t == "ok")

        if not first_session:
            _append("\n", mono, _c("separator"))
        first_session = False

        # Session header: colored dot + name
        dot_color = _c("err_dot") if err_count > 0 else _c("ok_dot")
        _append("● ", label_font, dot_color)
        _append(name, label_bold, _c("session"))

        # Badge
        if err_count > 0:
            _append(f"  {err_count} err", mono_sm, _c("err_text"))
        else:
            _append("  ok", mono_sm, _c("ok_text"))
        if ok_count > 0:
            _append(f"  {ok_count} recv", mono_sm, _c("ok_text"))
        _append("\n", mono, _c("log_text"))

        # Separator line
        _append("─" * 42 + "\n", mono_sm, _c("separator"))

        # Event log
        if events:
            for typ, text in events[-15:]:
                color = _c("err_text") if typ == "err" else _c("ok_text")
                prefix = "▸ " if typ == "err" else "  "
                # Clean up the text - remove leading spaces
                clean = text.strip()
                _append(f"{prefix}{clean}\n", mono_sm, color if typ == "err" else _c("log_text"))
        else:
            _append("  (no recent network events)\n", mono_sm, _c("empty"))

    return result


class DetailPanelController(NSObject):
    """Manages the custom detail panel window."""

    def init(self):
        self = objc.super(DetailPanelController, self).init()
        if self:
            self._window = None
            self._fade_step = 0
            self._monitor = None
        return self

    def showSessions_anchorFrame_(self, sessions, anchor_frame):
        """Create and show the detail panel near the bubble."""
        if self._window and self._window.isVisible():
            self._window.orderOut_(None)
            self._window = None

        # Position: above and to the left of the bubble
        screen = NSScreen.mainScreen().visibleFrame()
        px = anchor_frame.origin.x + anchor_frame.size.width / 2 - PANEL_WIDTH + 30
        py = anchor_frame.origin.y - PANEL_HEIGHT - 8
        # Keep on screen
        if px < screen.origin.x + 10:
            px = screen.origin.x + 10
        if py < screen.origin.y + 10:
            py = anchor_frame.origin.y + anchor_frame.size.height + 8

        frame = NSMakeRect(px, py, PANEL_WIDTH, PANEL_HEIGHT)

        win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskBorderless | NSWindowStyleMaskFullSizeContentView,
            NSBackingStoreBuffered,
            False,
        )
        win.setLevel_(NSFloatingWindowLevel + 1)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(True)
        win.setAlphaValue_(0.0)
        win.setMovableByWindowBackground_(True)

        # Root view with rounded background
        root = RoundedPanelView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT))

        # Title bar area
        title_y = PANEL_HEIGHT - 42
        title_label = NSTextField.labelWithString_("Network Status")
        title_label.setFont_(
            NSFont.fontWithName_size_("SF Pro Display", 15)
            or NSFont.boldSystemFontOfSize_(15))
        title_label.setTextColor_(_c("title"))
        title_label.setBackgroundColor_(NSColor.clearColor())
        title_label.setBezeled_(False)
        title_label.setEditable_(False)
        title_label.setFrame_(NSMakeRect(18, title_y, 300, 22))
        root.addSubview_(title_label)

        # Session count subtitle
        count = len(sessions)
        sub_text = f"{count} active session{'s' if count != 1 else ''}"
        sub_label = NSTextField.labelWithString_(sub_text)
        sub_label.setFont_(
            NSFont.fontWithName_size_("SF Pro Text", 11)
            or NSFont.systemFontOfSize_(11))
        sub_label.setTextColor_(_c("subtitle"))
        sub_label.setBackgroundColor_(NSColor.clearColor())
        sub_label.setBezeled_(False)
        sub_label.setEditable_(False)
        sub_label.setFrame_(NSMakeRect(18, title_y - 18, 300, 16))
        root.addSubview_(sub_label)

        # Close button
        close_btn = CloseButton.alloc().initWithFrame_(
            NSMakeRect(PANEL_WIDTH - 38, title_y - 2, 26, 26))
        close_btn._action_target = self
        root.addSubview_(close_btn)

        # Divider line
        divider_y = title_y - 26
        divider = NSView.alloc().initWithFrame_(
            NSMakeRect(16, divider_y, PANEL_WIDTH - 32, 1))
        divider.setWantsLayer_(True)
        divider.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.25, 0.3).CGColor())
        root.addSubview_(divider)

        # Scrollable text area
        scroll_y = 12
        scroll_h = divider_y - scroll_y - 6
        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(12, scroll_y, PANEL_WIDTH - 24, scroll_h))
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setBorderType_(0)  # No border
        scroll.setDrawsBackground_(False)
        scroll.setAutohidesScrollers_(True)

        text_view = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH - 36, scroll_h))
        text_view.setEditable_(False)
        text_view.setSelectable_(True)
        text_view.setDrawsBackground_(False)
        text_view.setTextContainerInset_((6, 8))
        text_view.textContainer().setWidthTracksTextView_(True)

        # Build and set attributed content
        content = _build_detail_attributed_string(sessions)
        text_view.textStorage().setAttributedString_(content)

        scroll.setDocumentView_(text_view)
        root.addSubview_(scroll)

        win.setContentView_(root)
        win.makeKeyAndOrderFront_(None)
        self._window = win

        # Fade-in animation
        self._fade_step = 0
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.018, self, "fadeIn:", None, True
        )

        # Click-outside monitor
        self._install_click_outside_monitor()

    @objc.typedSelector(b"v@:@")
    def fadeIn_(self, timer):
        self._fade_step += 1
        t = self._fade_step / 10.0
        if t >= 1.0:
            timer.invalidate()
            if self._window:
                self._window.setAlphaValue_(1.0)
            return
        # Ease-out quad
        alpha = 1.0 - (1.0 - t) * (1.0 - t)
        if self._window:
            self._window.setAlphaValue_(alpha)

    def closePanel(self):
        if self._window:
            self._window.orderOut_(None)
            self._window = None
        self._remove_click_outside_monitor()

    def _install_click_outside_monitor(self):
        from AppKit import NSEvent
        try:
            from AppKit import NSEventMaskLeftMouseDown
            mask = NSEventMaskLeftMouseDown
        except ImportError:
            mask = 1 << 1  # NSLeftMouseDownMask
        def handler(event):
            if self._window and self._window.isVisible():
                if event.window() != self._window:
                    self.closePanel()
        self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            mask, handler
        )

    def _remove_click_outside_monitor(self):
        if self._monitor:
            from AppKit import NSEvent
            NSEvent.removeMonitor_(self._monitor)
            self._monitor = None


class BubbleDelegate(NSObject):
    def init(self):
        self = objc.super(BubbleDelegate, self).init()
        if self:
            self._window = None
            self._view = None
            self._active_sessions = []
            self._detail_panel = DetailPanelController.alloc().init()
        return self

    def applicationDidFinishLaunching_(self, notification):
        screen = NSScreen.mainScreen().visibleFrame()
        self._final_x = screen.origin.x + screen.size.width - BUBBLE_SIZE - 20
        self._final_y = screen.origin.y + screen.size.height - BUBBLE_SIZE - 20

        start_size = BUBBLE_START_SIZE
        x = self._final_x - (start_size - BUBBLE_SIZE) / 2
        y = self._final_y - (start_size - BUBBLE_SIZE) / 2

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, start_size, start_size),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(NSFloatingWindowLevel)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setHasShadow_(True)
        self._window.setIgnoresMouseEvents_(False)
        self._window.setCollectionBehavior_(1 << 0)  # canJoinAllSpaces
        self._window.setAlphaValue_(0.0)

        self._view = BubbleView.alloc().initWithFrame_(
            NSMakeRect(0, 0, start_size, start_size))
        self._view._delegate_ref = self
        self._window.setContentView_(self._view)
        self._window.makeKeyAndOrderFront_(None)

        self._anim_step = 0
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            ANIM_INTERVAL, self, "animateEntrance:", None, True
        )

        self._check_status()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            CHECK_INTERVAL, self, "timerFired:", None, True
        )

    def animateEntrance_(self, timer):
        self._anim_step += 1
        t = self._anim_step / ANIM_STEPS

        if t >= 1.0:
            timer.invalidate()
            self._window.setFrame_display_(
                NSMakeRect(self._final_x, self._final_y,
                           BUBBLE_SIZE, BUBBLE_SIZE), True)
            self._view.setFrame_(NSMakeRect(0, 0, BUBBLE_SIZE, BUBBLE_SIZE))
            self._window.setAlphaValue_(1.0)
            self._view.setNeedsDisplay_(True)
            return

        ease = 1 - (1 - t) * (1 - t)
        size = BUBBLE_START_SIZE + (BUBBLE_SIZE - BUBBLE_START_SIZE) * ease
        alpha = min(1.0, t * 2.5)
        x = self._final_x - (size - BUBBLE_SIZE) / 2
        y = self._final_y - (size - BUBBLE_SIZE) / 2

        self._window.setFrame_display_(NSMakeRect(x, y, size, size), False)
        self._view.setFrame_(NSMakeRect(0, 0, size, size))
        self._window.setAlphaValue_(alpha)
        self._view.setNeedsDisplay_(True)

    def timerFired_(self, timer):
        self._check_status()

    def _check_status(self):
        status, info, sessions = check_all_sessions()
        self._active_sessions = sessions

        if status == "retry":
            color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.9, 0.2, 0.2, 0.9)
        elif status == "warn":
            color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.95, 0.7, 0.1, 0.9)
        else:
            color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.2, 0.8, 0.3, 0.9)

        self._view.setColor_(color)
        self._view.setToolTip_(info)

    def showDetailPanel(self):
        bubble_frame = self._window.frame()
        self._detail_panel.showSessions_anchorFrame_(self._active_sessions, bubble_frame)


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(1)  # Accessory - no dock icon
    delegate = BubbleDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    main()
