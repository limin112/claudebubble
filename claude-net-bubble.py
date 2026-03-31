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
  Click      = detailed network event log

How it works:
  Reads ~/.claude/projects/*/*.jsonl session logs every 2 seconds.
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
import math
import objc
from datetime import datetime, timezone
from AppKit import (
    NSApplication, NSWindow, NSPanel, NSView, NSColor, NSBezierPath,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskFullSizeContentView,
    NSBackingStoreBuffered,
    NSFloatingWindowLevel, NSScreen, NSTimer,
    NSMakeRect, NSMakePoint, NSFont,
    NSTextField, NSScrollView, NSTextView,
    NSTrackingArea, NSTrackingMouseEnteredAndExited, NSTrackingActiveAlways,
    NSMutableAttributedString, NSAttributedString,
    NSFontAttributeName, NSForegroundColorAttributeName,
    NSCursor, NSParagraphStyleAttributeName, NSMutableParagraphStyle,
)
from Foundation import NSObject, NSMutableDictionary
import signal

# --- Configuration ---
BUBBLE_SIZE = 20          # Final bubble diameter in pixels
SPLASH_SIZE = 260         # Startup splash bubble size
CHECK_INTERVAL = 2.0      # Seconds between status checks
ACTIVE_WINDOW_SECS = 600  # Sessions active within this window (10 min)

# Startup animation
SPLASH_ANIM_STEPS = 60    # Frames for splash shrink animation
SPLASH_ANIM_INTERVAL = 0.022  # ~45fps
SPLASH_HOLD_SECS = 3.5    # How long to show the splash before shrinking
CLICK_THRESHOLD = 4.0     # Max px movement to count as click (not drag)


# --- Timezone helper ---

def _to_local_time(ts_str):
    """Convert ISO timestamp to local timezone HH:MM:SS string."""
    try:
        cleaned = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        local_dt = dt.astimezone()
        return local_dt.strftime("%H:%M:%S")
    except (ValueError, AttributeError, TypeError):
        # Fallback: just extract HH:MM:SS from the string
        if ts_str and len(ts_str) > 19:
            return ts_str[11:19]
        return ts_str or ""


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
    """Get detailed network event log for the click panel."""
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
            ts = _to_local_time(entry.get("timestamp", ""))
            retry = entry.get("retryAttempt", 0)
            max_r = entry.get("maxRetries", 10)
            code = (entry.get("cause", {}).get("code")
                    or entry.get("error", {}).get("cause", {}).get("code")
                    or "ERR")
            events.append(("err", f"{ts}  ERR  {code}  retry {retry}/{max_r}"))
        if (entry.get("type") == "assistant"
                and entry.get("message", {}).get("stop_reason") is not None):
            ts = _to_local_time(entry.get("timestamp", ""))
            events.append(("ok", f"{ts}  OK   response received"))

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


# --- UI Components ---

class BubbleView(NSView):
    """The draggable bubble circle. Single-click opens detail panel."""
    _delegate_ref = None

    def initWithFrame_(self, frame):
        self = objc.super(BubbleView, self).initWithFrame_(frame)
        if self:
            self._color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.2, 0.8, 0.3, 0.9)
            self._drag_start = None
            self._mouse_down_screen = None
            self._did_drag = False
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
        self._drag_start = event.locationInWindow()
        screen_loc = self.window().convertPointToScreen_(event.locationInWindow())
        self._mouse_down_screen = (screen_loc.x, screen_loc.y)
        self._did_drag = False

    def mouseDragged_(self, event):
        window = self.window()
        if not window or not self._drag_start:
            return
        screen_loc = event.locationInWindow()
        origin = window.frame().origin
        dx = screen_loc.x - self._drag_start.x
        dy = screen_loc.y - self._drag_start.y
        if abs(dx) > CLICK_THRESHOLD or abs(dy) > CLICK_THRESHOLD:
            self._did_drag = True
        window.setFrameOrigin_((origin.x + dx, origin.y + dy))

    def mouseUp_(self, event):
        if not self._did_drag and self._delegate_ref:
            self._delegate_ref.showDetailPanel()
        self._drag_start = None
        self._mouse_down_screen = None
        self._did_drag = False

    def acceptsFirstMouse_(self, event):
        return True


# --- Detail Panel UI ---

PANEL_WIDTH = 440
PANEL_HEIGHT = 520
PANEL_CORNER_RADIUS = 14

_COLORS = {
    "bg":         (0.10, 0.10, 0.12, 0.94),
    "title":      (0.92, 0.92, 0.95, 1.0),
    "subtitle":   (0.55, 0.55, 0.60, 1.0),
    "separator":  (0.25, 0.25, 0.30, 0.6),
    "ok_dot":     (0.30, 0.82, 0.40, 1.0),
    "warn_dot":   (0.95, 0.70, 0.10, 1.0),
    "err_dot":    (0.95, 0.30, 0.25, 1.0),
    "ok_text":    (0.55, 0.78, 0.55, 1.0),
    "err_text":   (0.95, 0.50, 0.45, 1.0),
    "log_text":   (0.72, 0.72, 0.76, 1.0),
    "session":    (0.85, 0.85, 0.90, 1.0),
    "close_bg":   (0.20, 0.20, 0.24, 1.0),
    "close_hover": (0.30, 0.30, 0.35, 1.0),
    "close_text": (0.60, 0.60, 0.65, 1.0),
    "rule_text":  (0.68, 0.68, 0.72, 1.0),
    "rule_label": (0.80, 0.80, 0.84, 1.0),
    "empty":      (0.45, 0.45, 0.50, 0.7),
}

def _c(name):
    r, g, b, a = _COLORS[name]
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)


class CloseButton(NSView):
    _hovered = False
    _action_target = None

    def initWithFrame_(self, frame):
        self = objc.super(CloseButton, self).initWithFrame_(frame)
        if self:
            self._hovered = False
            area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(),
                NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways,
                self, None)
            self.addTrackingArea_(area)
        return self

    def drawRect_(self, rect):
        bg = _c("close_hover") if self._hovered else _c("close_bg")
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), 6, 6)
        bg.set()
        path.fill()
        font = NSFont.fontWithName_size_("Menlo", 13) or NSFont.systemFontOfSize_(13)
        attrs = NSMutableDictionary.alloc().init()
        attrs[NSFontAttributeName] = font
        attrs[NSForegroundColorAttributeName] = (
            _c("title") if self._hovered else _c("close_text"))
        s = NSAttributedString.alloc().initWithString_attributes_("\u2715", attrs)
        b = self.bounds()
        sz = s.size()
        s.drawAtPoint_((
            b.origin.x + (b.size.width - sz.width) / 2,
            b.origin.y + (b.size.height - sz.height) / 2 - 0.5))

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
    def drawRect_(self, rect):
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), PANEL_CORNER_RADIUS, PANEL_CORNER_RADIUS)
        _c("bg").set()
        path.fill()
        NSColor.colorWithCalibratedWhite_alpha_(0.25, 0.15).set()
        path.setLineWidth_(0.5)
        path.stroke()


def _build_detail_attributed_string(sessions):
    """Build rich attributed string with color rules + session data."""
    result = NSMutableAttributedString.alloc().init()

    mono = NSFont.fontWithName_size_("SF Mono", 11.5) or NSFont.fontWithName_size_("Menlo", 11.5)
    mono_sm = NSFont.fontWithName_size_("SF Mono", 10.5) or NSFont.fontWithName_size_("Menlo", 10.5)
    label_font = NSFont.fontWithName_size_("SF Pro Text", 12.5) or NSFont.systemFontOfSize_(12.5)
    label_bold = NSFont.boldSystemFontOfSize_(13)
    rule_font = NSFont.fontWithName_size_("SF Pro Text", 11.5) or NSFont.systemFontOfSize_(11.5)
    section_font = NSFont.boldSystemFontOfSize_(11)

    def _append(text, font, color):
        attrs = NSMutableDictionary.alloc().init()
        attrs[NSFontAttributeName] = font
        attrs[NSForegroundColorAttributeName] = color
        seg = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        result.appendAttributedString_(seg)

    # --- Color Rules Section ---
    _append("COLOR RULES\n", section_font, _c("subtitle"))
    _append("\n", mono_sm, _c("separator"))

    # Green rule
    _append("  \u25CF ", label_font, _c("ok_dot"))
    _append("Green", label_bold, _c("ok_dot"))
    _append("  \u2014  All sessions running normally\n", rule_font, _c("rule_text"))

    # Yellow rule
    _append("  \u25CF ", label_font, _c("warn_dot"))
    _append("Yellow", label_bold, _c("warn_dot"))
    _append("  \u2014  Some sessions retrying (partial errors)\n", rule_font, _c("rule_text"))

    # Red rule
    _append("  \u25CF ", label_font, _c("err_dot"))
    _append("Red", label_bold, _c("err_dot"))
    _append("  \u2014  All sessions retrying (network down)\n", rule_font, _c("rule_text"))

    _append("\n", mono_sm, _c("separator"))
    _append("\u2500" * 46 + "\n\n", mono_sm, _c("separator"))

    # --- Sessions Section ---
    _append("SESSIONS\n", section_font, _c("subtitle"))
    _append("\n", mono_sm, _c("separator"))

    if not sessions:
        _append("  No active sessions found\n", mono, _c("empty"))
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

        dot_color = _c("err_dot") if err_count > 0 else _c("ok_dot")
        _append("  \u25CF ", label_font, dot_color)
        _append(name, label_bold, _c("session"))

        if err_count > 0:
            _append(f"  {err_count} err", mono_sm, _c("err_text"))
        else:
            _append("  ok", mono_sm, _c("ok_text"))
        if ok_count > 0:
            _append(f"  {ok_count} recv", mono_sm, _c("ok_text"))
        _append("\n", mono, _c("log_text"))

        _append("  " + "\u2500" * 40 + "\n", mono_sm, _c("separator"))

        if events:
            for typ, text in events[-15:]:
                prefix = "  \u25B8 " if typ == "err" else "    "
                _append(f"{prefix}{text}\n", mono_sm,
                        _c("err_text") if typ == "err" else _c("log_text"))
        else:
            _append("    (no recent network events)\n", mono_sm, _c("empty"))

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
        if self._window and self._window.isVisible():
            self._window.orderOut_(None)
            self._window = None
            self._remove_click_outside_monitor()
            return

        screen = NSScreen.mainScreen().visibleFrame()
        px = anchor_frame.origin.x + anchor_frame.size.width / 2 - PANEL_WIDTH + 30
        py = anchor_frame.origin.y - PANEL_HEIGHT - 8
        if px < screen.origin.x + 10:
            px = screen.origin.x + 10
        if px + PANEL_WIDTH > screen.origin.x + screen.size.width - 10:
            px = screen.origin.x + screen.size.width - PANEL_WIDTH - 10
        if py < screen.origin.y + 10:
            py = anchor_frame.origin.y + anchor_frame.size.height + 8

        frame = NSMakeRect(px, py, PANEL_WIDTH, PANEL_HEIGHT)

        win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskBorderless | NSWindowStyleMaskFullSizeContentView,
            NSBackingStoreBuffered, False)
        win.setLevel_(NSFloatingWindowLevel + 1)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(True)
        win.setAlphaValue_(0.0)
        win.setMovableByWindowBackground_(True)

        root = RoundedPanelView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT))

        # Title
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

        # Subtitle
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

        # Divider
        divider_y = title_y - 26
        divider = NSView.alloc().initWithFrame_(
            NSMakeRect(16, divider_y, PANEL_WIDTH - 32, 1))
        divider.setWantsLayer_(True)
        divider.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.25, 0.3).CGColor())
        root.addSubview_(divider)

        # Scroll area
        scroll_y = 12
        scroll_h = divider_y - scroll_y - 6
        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(12, scroll_y, PANEL_WIDTH - 24, scroll_h))
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setBorderType_(0)
        scroll.setDrawsBackground_(False)
        scroll.setAutohidesScrollers_(True)

        text_view = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH - 36, scroll_h))
        text_view.setEditable_(False)
        text_view.setSelectable_(True)
        text_view.setDrawsBackground_(False)
        text_view.setTextContainerInset_((6, 8))
        text_view.textContainer().setWidthTracksTextView_(True)

        content = _build_detail_attributed_string(sessions)
        text_view.textStorage().setAttributedString_(content)

        scroll.setDocumentView_(text_view)
        root.addSubview_(scroll)

        win.setContentView_(root)
        win.makeKeyAndOrderFront_(None)
        self._window = win

        self._fade_step = 0
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.018, self, "fadeIn:", None, True)
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
            mask = 1 << 1
        def handler(event):
            if self._window and self._window.isVisible():
                if event.window() != self._window:
                    self.closePanel()
        self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            mask, handler)

    def _remove_click_outside_monitor(self):
        if self._monitor:
            from AppKit import NSEvent
            NSEvent.removeMonitor_(self._monitor)
            self._monitor = None


# --- Splash Screen (Startup Animation) ---

class SplashBubbleView(NSView):
    """The big animated bubble shown on startup."""
    _pulse_phase = 0.0

    def initWithFrame_(self, frame):
        self = objc.super(SplashBubbleView, self).initWithFrame_(frame)
        if self:
            self._pulse_phase = 0.0
        return self

    def drawRect_(self, rect):
        b = self.bounds()
        # Pulsing glow
        glow_alpha = 0.08 + 0.06 * math.sin(self._pulse_phase)
        glow_inset = -12
        glow_rect = NSMakeRect(
            b.origin.x + glow_inset, b.origin.y + glow_inset,
            b.size.width - 2 * glow_inset, b.size.height - 2 * glow_inset)
        glow_path = NSBezierPath.bezierPathWithOvalInRect_(glow_rect)
        NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.3, 0.85, 0.4, glow_alpha).set()
        glow_path.fill()

        # Main circle
        path = NSBezierPath.bezierPathWithOvalInRect_(b)
        NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.20, 0.80, 0.35, 0.92).set()
        path.fill()
        NSColor.colorWithCalibratedWhite_alpha_(0.5, 0.25).set()
        path.setLineWidth_(1.5)
        path.stroke()


class SplashController(NSObject):
    """Manages the dramatic startup splash animation."""

    def init(self):
        self = objc.super(SplashController, self).init()
        if self:
            self._window = None
            self._overlay = None
            self._bubble_view = None
            self._labels = []
            self._anim_step = 0
            self._phase = "hold"  # hold -> shrink -> done
            self._pulse_step = 0
            self._on_complete = None
            self._final_x = 0
            self._final_y = 0
        return self

    def startWithFinalX_finalY_onComplete_(self, final_x, final_y, on_complete):
        self._final_x = final_x
        self._final_y = final_y
        self._on_complete = on_complete

        screen = NSScreen.mainScreen().frame()
        scr_w = screen.size.width
        scr_h = screen.size.height

        # Semi-transparent dark overlay covering the whole screen
        self._overlay = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            screen, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        self._overlay.setLevel_(NSFloatingWindowLevel + 2)
        self._overlay.setOpaque_(False)
        self._overlay.setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.55))
        self._overlay.setIgnoresMouseEvents_(True)
        self._overlay.setAlphaValue_(0.0)

        # Overlay content for labels
        overlay_view = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, scr_w, scr_h))

        # --- Title ---
        cx = scr_w / 2
        cy = scr_h / 2
        title = NSTextField.labelWithString_("Claude Code Network Monitor")
        title.setFont_(
            NSFont.fontWithName_size_("SF Pro Display", 26)
            or NSFont.boldSystemFontOfSize_(26))
        title.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.95, 1.0))
        title.setBackgroundColor_(NSColor.clearColor())
        title.setBezeled_(False)
        title.setEditable_(False)
        title.sizeToFit()
        tw = title.frame().size.width
        title.setFrame_(NSMakeRect(cx - tw / 2, cy + SPLASH_SIZE / 2 + 48, tw, 32))
        overlay_view.addSubview_(title)
        self._labels.append(title)

        # --- Rule lines (below the bubble) ---
        rules = [
            ("\u25CF", (0.30, 0.82, 0.40), "Green", "All OK"),
            ("\u25CF", (0.95, 0.70, 0.10), "Yellow", "Some retrying"),
            ("\u25CF", (0.95, 0.30, 0.25), "Red", "All retrying"),
        ]
        rule_y_start = cy - SPLASH_SIZE / 2 - 50
        for i, (dot, dot_rgb, label, desc) in enumerate(rules):
            y = rule_y_start - i * 28
            line_str = f"  {dot}  {label}  \u2014  {desc}"
            lbl = NSTextField.labelWithString_(line_str)
            lbl.setFont_(
                NSFont.fontWithName_size_("SF Pro Text", 15)
                or NSFont.systemFontOfSize_(15))
            r, g, b = dot_rgb
            lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0))
            lbl.setBackgroundColor_(NSColor.clearColor())
            lbl.setBezeled_(False)
            lbl.setEditable_(False)
            lbl.sizeToFit()
            lw = lbl.frame().size.width
            lbl.setFrame_(NSMakeRect(cx - lw / 2, y, lw, 22))
            overlay_view.addSubview_(lbl)
            self._labels.append(lbl)

        # --- Hint at bottom ---
        hint = NSTextField.labelWithString_("Click the bubble to view details")
        hint.setFont_(
            NSFont.fontWithName_size_("SF Pro Text", 13)
            or NSFont.systemFontOfSize_(13))
        hint.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.6, 1.0))
        hint.setBackgroundColor_(NSColor.clearColor())
        hint.setBezeled_(False)
        hint.setEditable_(False)
        hint.sizeToFit()
        hw = hint.frame().size.width
        hint.setFrame_(NSMakeRect(cx - hw / 2, rule_y_start - 3 * 28 - 10, hw, 20))
        overlay_view.addSubview_(hint)
        self._labels.append(hint)

        self._overlay.setContentView_(overlay_view)
        self._overlay.makeKeyAndOrderFront_(None)

        # Bubble window (centered, big)
        bx = cx - SPLASH_SIZE / 2
        by = cy - SPLASH_SIZE / 2
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(bx, by, SPLASH_SIZE, SPLASH_SIZE),
            NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        self._window.setLevel_(NSFloatingWindowLevel + 3)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setHasShadow_(True)
        self._window.setIgnoresMouseEvents_(True)
        self._window.setAlphaValue_(0.0)

        self._bubble_view = SplashBubbleView.alloc().initWithFrame_(
            NSMakeRect(0, 0, SPLASH_SIZE, SPLASH_SIZE))
        self._window.setContentView_(self._bubble_view)
        self._window.makeKeyAndOrderFront_(None)

        # Start fade-in + pulse timer
        self._anim_step = 0
        self._phase = "fadein"
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            SPLASH_ANIM_INTERVAL, self, "animateSplash:", None, True)

    @objc.typedSelector(b"v@:@")
    def animateSplash_(self, timer):
        self._anim_step += 1
        self._pulse_step += 1

        if self._phase == "fadein":
            # Fade in over 15 frames
            t = min(1.0, self._anim_step / 15.0)
            ease = 1.0 - (1.0 - t) * (1.0 - t)
            if self._window:
                self._window.setAlphaValue_(ease)
            if self._overlay:
                self._overlay.setAlphaValue_(ease)
            if self._bubble_view:
                self._bubble_view._pulse_phase = self._pulse_step * 0.15
                self._bubble_view.setNeedsDisplay_(True)
            if t >= 1.0:
                self._phase = "hold"
                self._anim_step = 0

        elif self._phase == "hold":
            # Hold for SPLASH_HOLD_SECS, keep pulsing
            hold_frames = int(SPLASH_HOLD_SECS / SPLASH_ANIM_INTERVAL)
            if self._bubble_view:
                self._bubble_view._pulse_phase = self._pulse_step * 0.15
                self._bubble_view.setNeedsDisplay_(True)
            if self._anim_step >= hold_frames:
                self._phase = "shrink"
                self._anim_step = 0
                # Store start position
                screen = NSScreen.mainScreen().frame()
                self._start_cx = screen.size.width / 2
                self._start_cy = screen.size.height / 2

        elif self._phase == "shrink":
            t = min(1.0, self._anim_step / float(SPLASH_ANIM_STEPS))
            # Ease-in-out cubic
            if t < 0.5:
                ease = 4 * t * t * t
            else:
                ease = 1 - (-2 * t + 2) ** 3 / 2

            # Interpolate size
            size = SPLASH_SIZE + (BUBBLE_SIZE - SPLASH_SIZE) * ease

            # Interpolate position (center -> final corner)
            target_cx = self._final_x + BUBBLE_SIZE / 2
            target_cy = self._final_y + BUBBLE_SIZE / 2
            cx = self._start_cx + (target_cx - self._start_cx) * ease
            cy = self._start_cy + (target_cy - self._start_cy) * ease
            x = cx - size / 2
            y = cy - size / 2

            if self._window:
                self._window.setFrame_display_(
                    NSMakeRect(x, y, size, size), True)
                self._bubble_view.setFrame_(NSMakeRect(0, 0, size, size))
                self._bubble_view._pulse_phase = self._pulse_step * 0.15
                self._bubble_view.setNeedsDisplay_(True)

            # Fade out overlay and labels
            overlay_alpha = max(0.0, 1.0 - ease * 2.5)
            if self._overlay:
                self._overlay.setAlphaValue_(overlay_alpha)

            if t >= 1.0:
                timer.invalidate()
                if self._overlay:
                    self._overlay.orderOut_(None)
                    self._overlay = None
                if self._window:
                    self._window.orderOut_(None)
                    self._window = None
                if self._on_complete:
                    self._on_complete()


# --- Main App Delegate ---

class BubbleDelegate(NSObject):
    def init(self):
        self = objc.super(BubbleDelegate, self).init()
        if self:
            self._window = None
            self._view = None
            self._active_sessions = []
            self._detail_panel = DetailPanelController.alloc().init()
            self._splash = None
        return self

    def applicationDidFinishLaunching_(self, notification):
        screen = NSScreen.mainScreen().visibleFrame()
        self._final_x = screen.origin.x + screen.size.width - BUBBLE_SIZE - 20
        self._final_y = screen.origin.y + screen.size.height - BUBBLE_SIZE - 20

        # Start splash animation first
        self._splash = SplashController.alloc().init()
        self._splash.startWithFinalX_finalY_onComplete_(
            self._final_x, self._final_y, self._onSplashComplete)

        # Start status checking immediately (runs in background)
        self._check_status()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            CHECK_INTERVAL, self, "timerFired:", None, True)

    def _onSplashComplete(self):
        """Called when splash animation finishes. Show the real bubble."""
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(self._final_x, self._final_y, BUBBLE_SIZE, BUBBLE_SIZE),
            NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        self._window.setLevel_(NSFloatingWindowLevel)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setHasShadow_(True)
        self._window.setIgnoresMouseEvents_(False)
        self._window.setCollectionBehavior_(1 << 0)  # canJoinAllSpaces
        self._window.setAlphaValue_(1.0)

        self._view = BubbleView.alloc().initWithFrame_(
            NSMakeRect(0, 0, BUBBLE_SIZE, BUBBLE_SIZE))
        self._view._delegate_ref = self
        self._window.setContentView_(self._view)
        self._window.makeKeyAndOrderFront_(None)

        # Apply current status color
        self._check_status()
        self._splash = None

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

        if self._view:
            self._view.setColor_(color)
            self._view.setToolTip_(info)

    def showDetailPanel(self):
        if self._window:
            bubble_frame = self._window.frame()
            self._detail_panel.showSessions_anchorFrame_(
                self._active_sessions, bubble_frame)


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(1)  # Accessory - no dock icon
    delegate = BubbleDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    main()
