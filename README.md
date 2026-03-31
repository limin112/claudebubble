# Claude Code Network Bubble

A floating desktop bubble for macOS that monitors your Claude Code sessions' network health in real time.

![macOS](https://img.shields.io/badge/platform-macOS-blue)
![Python 3](https://img.shields.io/badge/python-3.9+-green)

## What it does

A small floating circle sits on your desktop and changes color based on network status:

- **Green** - All sessions healthy
- **Yellow** - Some sessions experiencing network errors
- **Red** - All sessions retrying

### Interactions

| Action | Result |
|--------|--------|
| **Hover** | Tooltip showing per-session status |
| **Drag** | Move the bubble anywhere on screen |
| **Double-click** | Detailed network event log for all sessions |

### Multi-session support

Automatically monitors **all active Claude Code sessions** (modified within the last 10 minutes). If you have multiple Claude Code windows open, the bubble tracks them all.

## How it works

Claude Code writes session events to JSONL transcript files at `~/.claude/projects/`. The bubble reads the tail of these files every 2 seconds and compares:

- The **last `api_error`** entry (network failure + retry attempt)
- The **last successful `assistant` response**

If the last error is newer than the last success, that session is actively retrying.

> **Note:** This relies on Claude Code's internal JSONL transcript format, which is not a public API and may change between versions.

## Install

### Prerequisites

- macOS
- Python 3.9+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

### Setup

```bash
# Install the macOS Python bridge
pip3 install pyobjc-framework-Cocoa

# Download the script
curl -o ~/.claude/claude-net-bubble.py \
  https://raw.githubusercontent.com/YOUR_USER/claude-net-bubble/main/claude-net-bubble.py
```

### Run manually

```bash
# Run in background
nohup python3 ~/.claude/claude-net-bubble.py &
```

### Auto-start with Claude Code (recommended)

Add a `SessionStart` hook to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "pgrep -f claude-net-bubble.py > /dev/null || nohup python3 ~/.claude/claude-net-bubble.py > /dev/null 2>&1 &",
            "async": true
          }
        ]
      }
    ]
  }
}
```

This starts the bubble on your first Claude Code session and keeps it running across sessions.

### Stop

```bash
pkill -f claude-net-bubble.py
```

## Configuration

Edit the constants at the top of `claude-net-bubble.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `BUBBLE_SIZE` | `20` | Bubble diameter in pixels |
| `CHECK_INTERVAL` | `2.0` | Seconds between status checks |
| `ACTIVE_WINDOW_SECS` | `600` | Consider sessions active if modified within this window (seconds) |

## JSONL format reference

Network errors in the session log:

```json
{
  "type": "system",
  "subtype": "api_error",
  "cause": { "code": "ECONNRESET" },
  "retryAttempt": 3,
  "maxRetries": 10,
  "timestamp": "2026-03-30T15:27:34.050Z"
}
```

Successful responses:

```json
{
  "type": "assistant",
  "message": { "stop_reason": "end_turn" },
  "timestamp": "2026-03-30T15:28:17.959Z"
}
```

## License

MIT
