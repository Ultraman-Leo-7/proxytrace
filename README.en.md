# ProxyTrace · Per-domain proxy traffic accounting

[简体中文](README.md) | English

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg) ![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg) ![Platform](https://img.shields.io/badge/Platform-Windows-0078D6.svg)

See exactly **which websites your proxy traffic goes to, which app used it, and via which node** — so you can route the heavy hitters through a different node or bypass the proxy entirely and save bandwidth.

Built for **Clash Verge Rev** (mihomo core). **Zero third-party dependencies** — just Python 3.8+.

> ⚠️ Windows only (it talks to the Clash core over a Windows named pipe).

![ProxyTrace dashboard](docs/screenshot.png)

> Demo data above. Your real data lives only in `data/traffic.db` on your machine and is never uploaded.

---

## Requirements

- Windows 10 / 11
- Python 3.8+ (from [python.org](https://www.python.org/downloads/); check **Add Python to PATH** during install)
- A running **Clash Verge Rev** (mihomo core)

## Install

```bash
git clone https://github.com/Ultraman-Leo-7/proxytrace.git
```

Or **Code → Download ZIP** and unzip. Any folder works — the scripts resolve their own path.

---

## Quick start (double-click, no terminal)

1. **Double-click `启动.vbs`** (Start) — begins collecting in the background and opens the web dashboard automatically (no console window).
2. Pick a date in the dashboard to see which sites your proxy traffic went to that day and how much each used.
3. **Done?** Click "⏻ Stop & exit" at the top-right of the page, or **double-click `停止.vbs`** (Stop). Collection stops and the page goes offline.

It keeps recording in the background until you stop it. Double-clicking `启动.vbs` again while it's running just reopens the page — it won't double-count.

---

## What problem it solves

Clash Verge Rev's built-in "Connections" page is **real-time and in-memory only**: closed connections are capped at 500 and everything resets on restart / profile switch — **no history, no daily totals**. Existing projects are either live dashboards or Prometheus exporters that only export totals (they deliberately avoid per-domain labels due to cardinality); DNS-based tools (AdGuard) only count domain hits without byte sizes and miss proxied domains under fake-ip.

ProxyTrace attaches a "bookkeeper" to Clash: every second it reads a connection snapshot, accumulates byte deltas per connection, and stores them in local SQLite keyed by **date + domain + process + node**.

---

## How it works

- Reads mihomo's `/connections` API over the Windows named pipe `\\.\pipe\verge-mihomo` (Clash Verge Rev exposes only the pipe, not a TCP port — handled here, **no Clash config changes needed**).
- Each connection's `upload`/`download` grows monotonically. The collector remembers each connection id's last byte counts and only adds the **delta** each round; closed connections drop out of the snapshot with their last delta already counted. After a core restart / profile switch, ids are new and treated as new connections.
- Domain comes from `metadata.host` (accurate even in fake-ip mode), falling back to `sniffHost` → destination IP. Exit node is the proxy chain's `chains[0]`; plain direct shows `DIRECT`.

> **About "(unknown)" process**: mihomo can't attribute a process for some connections, grouped as `(unknown)`. The traffic is still counted accurately — only the originating app is unknown.
>
> **Accuracy**: connections shorter than one poll interval (1s default) may be undercounted, but heavy traffic is long-lived (downloads / video / sync), so the impact is negligible. Long connections spanning midnight are split per day correctly.

---

## Autostart (optional)

**Option A — script**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1
```
Creates a Startup-folder shortcut to `启动.vbs`. Undo: `scripts\uninstall-autostart.ps1`.

**Option B — manual**: press `Win + R`, type `shell:startup`, then drop a shortcut to `启动.vbs` into that folder.

---

## CLI reports

```powershell
cd <project folder>
python run.py report                  # today's top 20 by domain
python run.py report --date 2026-06-19
python run.py report --days 7         # last 7 days combined
python run.py report --by process     # by app
python run.py report --by node        # by exit node
python run.py report --proxied-only
python run.py report --top 50
```

Other commands: `python run.py test` (check connection), `python run.py app` (run collector + dashboard in foreground), `python run.py stop`.

---

## Configuration (`config.json`, auto-generated)

| Key | Default | Notes |
|---|---|---|
| `transport` | `auto` | `auto` → named pipe on Windows; also `pipe` / `tcp` |
| `pipe_name` | `verge-mihomo` | named pipe name |
| `controller_url` | `http://127.0.0.1:9090` | used when `transport=tcp` |
| `secret` | `""` | external-controller secret (not needed for the pipe) |
| `poll_interval` | `1.0` | poll seconds |
| `flush_interval` | `5.0` | DB write interval (s) |
| `db_path` | `data/traffic.db` | database path |
| `dashboard_port` | `8788` | dashboard port |
| `retention_days` | `0` | keep N days, `0` = forever |

> Using the **mihomo core** or another client with external-controller enabled? Set `transport` to `tcp` and fill in `controller_url` / `secret`.

---

## Troubleshooting

- **`启动.vbs` does nothing / page won't open**: run `python run.py test` to check the Clash core connection; make sure Clash Verge Rev is running. Background logs are at `data\proxytrace.log`.
- **Empty report / page**: collector isn't running, or it just started. Double-click `启动.vbs` and wait a bit.
- **Is it running?** Look for `pythonw.exe` in Task Manager, or check `data\proxytrace.pid`.
- **Stop completely**: double-click `停止.vbs` (or the dashboard's stop button).

---

## License

[MIT](LICENSE)
