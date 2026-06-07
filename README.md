# Waypoint

![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)

> A workspace memory system for macOS. Click to return to where you were.

---

## The problem

After an hour of switching between projects, you have four terminal windows open and can't remember which one belongs to which project. You cycle through them. You lose 30 seconds. Every time.

Waypoint solves this.

---

## What it does

Waypoint runs as a small floating window in the corner of your screen. When you `cd` into a project and start `claude`, Waypoint notices and displays the project name. Click the name to bring that terminal window to the front — immediately, with no confirmation dialogs.

```
waypoint

Project Alpha
Project Beta
```

Hover to see where each workspace is located:

```
waypoint

Project Alpha
~/code/project-alpha

Project Beta
~/work/project-beta
```

That's it. Nothing else is shown.

---

## Features

- **Automatic detection** — registers workspaces as you work, no setup during normal use
- **Click to focus** — one click brings the right terminal window to front
- **Path-based matching** — tells projects apart by directory, not keyword guessing
- **Minimal by design** — project names only; path appears on hover
- **Monochrome** — no colors, no icons, no dashboard
- **Always visible** — floats above all windows, drag anywhere, configurable opacity
- **Auto-launch** — optional shell hook starts Waypoint with every new terminal tab

---

## Quick start

### 1. Prerequisites

- macOS 12 Ventura or later
- Python 3.10 or later (`python3 --version`)
- Claude Code CLI (`claude --version`)

### 2. Clone

```bash
git clone https://github.com/Agneschen99/waypoint.git ~/waypoint
cd ~/waypoint
```

### 3. Install

```bash
pip install -r requirements.txt
```

### 4. Configure your projects

Edit `config.yaml`:

```yaml
projects:
  - name: My Project
    path: ~/code/my-project
```

The `path` is matched against the working directory of each terminal session. Any subdirectory also counts, so `~/code/my-project/src` matches `~/code/my-project`.

### 5. Grant permissions

On first run, macOS will ask for **Automation** permission so Waypoint can read terminal window state via AppleScript.

**System Settings → Privacy & Security → Automation → Terminal → Terminal.app ✓**

If the prompt never appears, trigger it manually:

```bash
osascript -e 'tell application "Terminal" to get name of windows'
```

### 6. Run

```bash
python main.py
```

Open a new terminal, navigate to a configured project directory, and run `claude`. Waypoint will show the project name within a few seconds.

---

## Auto-launch

To start Waypoint automatically with every new terminal tab:

```bash
echo 'source ~/waypoint/waypoint_launch.sh' >> ~/.zshrc
```

The script checks for an existing instance before launching, so opening multiple tabs will not create duplicate windows.

---

## config.yaml reference

```yaml
poll_interval: 2        # seconds between scans (default: 2)
opacity: 0.88           # window opacity, 0.0–1.0 (default: 0.88)
position: bottom-right  # starting corner (default: bottom-right)
                        # options: top-left | top-right | bottom-left | bottom-right

projects:
  - name: My Project    # displayed in the HUD
    path: ~/code/my-project  # matched against terminal working directory
```

**How matching works:** Waypoint resolves all paths to their real absolute form (expanding `~`, following symlinks) and checks whether the shell's current working directory equals the project path or is a subdirectory of it.

---

## Supported environments

| | Status |
|---|---|
| Terminal.app | ✅ full support |
| iTerm2 | 🔜 roadmap |
| macOS 12 Ventura and later | ✅ |
| Claude Code CLI | ✅ detected as the active session |
| Any shell (zsh, bash, fish) | ✅ |

---

## Roadmap

- [ ] **iTerm2 support** — window focus via iTerm2's AppleScript dictionary
- [ ] **Menu bar mode** — live in the macOS menu bar rather than a floating window
- [ ] **Session persistence** — remember last-seen workspaces across restarts
- [ ] **Workspace timer** — optional per-project active-time counter
- [ ] **Cognitive scheduling integration** — `Detector` is a dependency-free module designed to be embedded in larger context-switching or task-management systems

---

## Design principles

Waypoint is a **workspace memory system**, not a process monitor.

The user should never think about PIDs, tty devices, window IDs, or AppleScript. They think about one thing: *which project do I want to return to?*

Every UI element was evaluated against one question: does this help the user instantly recognise and resume a workspace? If not, it was removed.

---

## Contributing

Open an issue before significant changes. PRs are welcome.

---

## License

[MIT](https://opensource.org/licenses/MIT)
