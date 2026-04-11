[English](#claude-code-network-bubble) | [中文说明](#claude-code-network-bubble-中文说明)

# Claude Code Network Bubble (中文说明)

macOS 桌面悬浮气泡，实时监控 Claude Code 会话的网络状态。

![macOS](https://img.shields.io/badge/platform-macOS-blue)
![Python 3](https://img.shields.io/badge/python-3.9+-green)

## 功能说明

桌面上会出现一个像素风螃蟹，通过视觉指示器显示网络状态：

| 正常 | 警告 | 错误 |
|:-:|:-:|:-:|
| ![OK](screenshot-ok.png) | ![Warn](screenshot-warn.png) | ![Error](screenshot-error.png) |
| 绿色勾勾 | 黄色圆点 + 皮鞭（慢） + 粒子 | 红色圆点 + 皮鞭（快） + 粒子 |

- **OK** - 所有会话正常运行
- **Warn** - 部分会话出现网络错误，正在重试
- **Error** - 所有会话都在重试（网络异常）

### 交互方式

| 操作 | 效果 |
|------|------|
| **悬停** | 显示每个会话的状态摘要 |
| **拖拽** | 移动螃蟹到屏幕任意位置 |
| **单击** | 弹出详细面板，包含动画状态图示和网络事件日志 |
| **右键** | 上下文菜单（详情 / 退出） |

### 启动动画

启动时，屏幕中央会出现大号螃蟹，配合半透明遮罩展示状态规则。动画阶段会依次展示三种状态（OK、Warn、Error），让你直观看到每种状态的效果。停留数秒后，螃蟹缩小并飞向屏幕角落。

### 详情面板

单击螃蟹打开详情面板，包含：
- **状态规则** 区域，三个动画小螃蟹图示
- **可交互螃蟹预览**（右上角），点击切换状态
- **会话列表**，每个会话的网络事件日志

### 多会话支持

自动监控所有活跃的 Claude Code 会话（10 分钟内有更新的）。如果你同时打开了多个 Claude Code 窗口，气泡会统一追踪。

## 工作原理

Claude Code 会将会话事件写入 `~/.claude/projects/` 下的 JSONL 文件。气泡每 2 秒读取这些文件的尾部，对比：

- 最近一条 **`api_error`**（网络错误 + 重试次数）
- 最近一条 **成功的 `assistant` 响应**

如果最后一条错误比最后一条成功更新，说明该会话正在重试。

所有时间戳均以**本机时区**显示。

> **注意：** 本工具依赖 Claude Code 内部的 JSONL 日志格式，该格式非公开 API，可能随版本更新变化。

## 安装

### 快速安装（让 AI 帮你装）

把下面这段话粘贴到 Claude Code 里，让它自动完成所有操作：

> 安装 https://github.com/limin112/claudebubble ，克隆仓库，安装依赖（`pip3 install pyobjc-framework-Cocoa`），把脚本复制到 `~/.claude/claude-net-bubble.py`，并在 `~/.claude/settings.json` 中添加 `SessionStart` 钩子，让它随 Claude Code 自动启动。

### 手动安装

#### 前置条件

- macOS
- Python 3.9+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

#### 安装步骤

```bash
# 安装 macOS Python 桥接库
pip3 install pyobjc-framework-Cocoa

# 克隆仓库并复制脚本
git clone https://github.com/limin112/claudebubble.git /tmp/claudebubble
cp /tmp/claudebubble/claude-net-bubble.py ~/.claude/claude-net-bubble.py
```

#### 手动运行

```bash
nohup python3 ~/.claude/claude-net-bubble.py &
```

#### 随 Claude Code 自动启动（推荐）

在 `~/.claude/settings.json` 中添加 `SessionStart` 钩子：

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

首次启动 Claude Code 时会自动运行气泡，之后的会话复用同一个进程。

#### 停止

```bash
pkill -f claude-net-bubble.py
```

## 配置项

编辑 `claude-net-bubble.py` 顶部的常量：

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `BUBBLE_SIZE` | `64` | 气泡直径（像素） |
| `SPLASH_SIZE` | `260` | 启动动画气泡大小 |
| `CHECK_INTERVAL` | `2.0` | 状态检查间隔（秒） |
| `ACTIVE_WINDOW_SECS` | `600` | 会话活跃窗口期（秒） |
| `SPLASH_HOLD_SECS` | `3.5` | 启动动画停留时长（秒） |

## 许可证

MIT

---

[中文说明](#claude-code-network-bubble-中文说明) | [English](#claude-code-network-bubble)

# Claude Code Network Bubble

A floating desktop bubble for macOS that monitors your Claude Code sessions' network health in real time.

![macOS](https://img.shields.io/badge/platform-macOS-blue)
![Python 3](https://img.shields.io/badge/python-3.9+-green)

## What it does

A pixel-art crab mascot floats on your desktop and shows network status with visual indicators:

| OK | Warn | Error |
|:-:|:-:|:-:|
| ![OK](screenshot-ok.png) | ![Warn](screenshot-warn.png) | ![Error](screenshot-error.png) |
| Green checkmark | Yellow dot + whip (slow) + particles | Red dot + whip (fast) + particles |

- **OK** - All sessions healthy
- **Warn** - Some sessions experiencing network errors
- **Error** - All sessions retrying

### Interactions

| Action | Result |
|--------|--------|
| **Hover** | Tooltip showing per-session status |
| **Drag** | Move the bubble anywhere on screen |
| **Click** | Detailed panel with animated status illustrations and network event log |
| **Right-click** | Context menu (details / quit) |

### Startup animation

On launch, a large crab appears at the center of the screen with an overlay explaining the status rules. During the hold phase, it cycles through all three states (OK, Warn, Error) so you can see what each looks like. After a few seconds it shrinks and flies to the corner.

### Detail panel

Click the crab to open the detail panel, which includes:
- **Status Rules** section with three animated mini-crab illustrations
- **Clickable crab preview** (top-right) to cycle through states interactively
- **Sessions** list with per-session network event logs

### Multi-session support

Automatically monitors **all active Claude Code sessions** (modified within the last 10 minutes). If you have multiple Claude Code windows open, the bubble tracks them all.

## How it works

Claude Code writes session events to JSONL transcript files at `~/.claude/projects/`. The bubble reads the tail of these files every 2 seconds and compares:

- The **last `api_error`** entry (network failure + retry attempt)
- The **last successful `assistant` response**

If the last error is newer than the last success, that session is actively retrying.

All timestamps are displayed in your **local timezone**.

> **Note:** This relies on Claude Code's internal JSONL transcript format, which is not a public API and may change between versions.

## Install

### Quick install (let AI do it)

Paste the following into Claude Code and let it handle everything:

> Install https://github.com/limin112/claudebubble — clone the repo, install dependencies (`pip3 install pyobjc-framework-Cocoa`), copy the script to `~/.claude/claude-net-bubble.py`, and add a `SessionStart` hook to `~/.claude/settings.json` so it auto-starts with every Claude Code session.

### Manual install

#### Prerequisites

- macOS
- Python 3.9+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

#### Setup

```bash
# Install the macOS Python bridge
pip3 install pyobjc-framework-Cocoa

# Clone the repo and copy the script
git clone https://github.com/limin112/claudebubble.git /tmp/claudebubble
cp /tmp/claudebubble/claude-net-bubble.py ~/.claude/claude-net-bubble.py
```

#### Run manually

```bash
# Run in background
nohup python3 ~/.claude/claude-net-bubble.py &
```

#### Auto-start with Claude Code (recommended)

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

#### Stop

```bash
pkill -f claude-net-bubble.py
```

## Configuration

Edit the constants at the top of `claude-net-bubble.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `BUBBLE_SIZE` | `64` | Bubble diameter in pixels |
| `SPLASH_SIZE` | `260` | Startup splash bubble size |
| `CHECK_INTERVAL` | `2.0` | Seconds between status checks |
| `ACTIVE_WINDOW_SECS` | `600` | Consider sessions active if modified within this window (seconds) |
| `SPLASH_HOLD_SECS` | `3.5` | How long the startup splash stays before shrinking |

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
