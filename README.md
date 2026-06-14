# Waypoint

A floating window that remembers where you left off across coding projects.

(GIF)

## Why

When working across multiple terminals and AI coding sessions, it's easy to forget:

- Which project am I in?
- What was I doing?
- Which terminal should I return to?

Waypoint keeps that context visible.

## Features

- Auto detects active projects
- Shows last working hint
- One-click jump back
- Marks recently ended sessions

## Demo

(GIF)

## Install

```
git clone https://github.com/AgnesC0/waypoint
cd waypoint
pip install -r requirements.txt
python main.py
```

## Config

`config.yaml` is optional. Without it, any directory with an active terminal session appears automatically. Add entries to give projects friendly display names:

```yaml
projects:
  - name: My App
    path: ~/code/my-app
```

## Privacy

Runs locally by default. No telemetry unless explicitly enabled.

If you want to opt in to anonymous install counting, add to `config.yaml`:

```yaml
telemetry:
  enabled: true
  endpoint: https://your-collection-endpoint
```

The complete payload is five fields: a random UUID (generated on first opt-in, no link to any account or machine identifier), event type, date, platform, and schema version. Workspace names, paths, code, git data, session content, and terminal commands are never sent.

## Roadmap

- [ ] Better context recovery
- [ ] Multi-monitor
- [ ] Team mode
