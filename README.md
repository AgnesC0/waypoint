# Waypoint

**You shouldn't have to remember which terminal contains your current work. Waypoint remembers it for you.**

A lightweight floating HUD that shows your open terminal workspaces, what you were doing in each one, and lets you jump back instantly.

<!-- Demo GIF -->

---

## What it does

- Detects open workspaces by shell cwd — shows only terminals that are currently open
- Identifies the active Terminal tab on macOS via tty; window-level on Windows
- Displays session duration and relative recency per workspace
- Infers a resume hint from local signals (git diff, last commit, or foreground command)
- Click any row to bring that terminal to focus
- No daemon, no Electron, no background service

> Never reads commands, keystrokes, terminal output, or file contents.

---

## Quick Start

```bash
git clone https://github.com/Agneschen99/waypoint.git ~/waypoint
cd ~/waypoint
pip install -r requirements.txt
python main.py
```

Add your projects to `config.yaml`:

```yaml
projects:
  - name: My App
    path: ~/code/my-app
```

> **macOS:** Grant **Automation** permission on first run.
> If the prompt doesn't appear: `osascript -e 'tell application "Terminal" to get name of windows'`

---

## Configuration

```yaml
projects:
  - name: My App          # display name in the HUD
    path: ~/code/my-app   # any subdirectory also matches

poll_interval: 2          # seconds between scans
opacity: 0.88             # 0.0–1.0
position: bottom-right    # top-left | top-right | bottom-left | bottom-right
```

Drag the HUD to any corner. Right-click for opacity options.

---

## Resume Hints

Waypoint infers a lightweight hint per workspace from safe local signals, in priority order:

1. Manual hint (CLI)
2. Semantic diff — function/class names from the working-tree diff
3. Last commit subject
4. Specific foreground command (e.g. `pytest auth_test.py`)

```
Waypoint        · 42m
↳ improve semantic hint generation

My App          · 3m
↳ auth refactor
```

```bash
python main.py hint "redesigning onboarding flow"   # set
python main.py hint --clear                          # clear
python main.py hint                                  # read
python main.py status                                # debug detection state
```

---

## Auto-launch

```bash
echo 'source ~/waypoint/waypoint_launch.sh' >> ~/.zshrc
```

Safe to source from multiple tabs — only one instance runs per session.

---

## Roadmap

- iTerm2 support
- Menu bar mode
- Session persistence across restarts
- Per-project active-time statistics

---

## License

MIT
