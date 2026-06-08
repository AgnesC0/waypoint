# Waypoint

A floating macOS HUD that remembers which terminal window belongs to which project. Click to return — no hunting, no cycling.

```
waypoint

Waypoint
CogPass Light
```

Hover to reveal the path. Nothing else is shown.

---

## Quick start

**1. Clone & install**
```bash
git clone https://github.com/Agneschen99/waypoint.git ~/waypoint
cd ~/waypoint && pip install -r requirements.txt
```

**2. Configure `config.yaml`**
```yaml
projects:
  - name: My Project
    path: ~/code/my-project   # any subdirectory also matches

poll_interval: 2       # seconds between scans
opacity: 0.88
position: bottom-right # top-left | top-right | bottom-left | bottom-right
```

**3. Run**
```bash
python main.py
```

> 💡 On first run, macOS will prompt for **Automation** permission so Waypoint can read terminal state via AppleScript. If the prompt doesn't appear: `osascript -e 'tell application "Terminal" to get name of windows'`

---

## Auto-launch

```bash
echo 'source ~/waypoint/waypoint_launch.sh' >> ~/.zshrc
```

Opens one Waypoint instance per login session — safe to call from multiple tabs.

---

## Roadmap

- [ ] iTerm2 support
- [ ] Menu bar mode
- [ ] Session persistence across restarts
- [ ] Per-project active-time counter

---

## License

MIT
