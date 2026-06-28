"""本地网页面板：http.server 提供单页 HTML + JSON 接口，从 SQLite 只读查询。

可独立运行（python run.py dashboard），也可由 app 模式调用（带停止回调）。
"""

import datetime
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .config import load_config, resolve_db_path
from .storage import Storage

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ProxyTrace · 代理流量去向</title>
<style>
  :root { --bg:#0f1419; --card:#1a2230; --line:#2a3343; --fg:#e6edf3; --mut:#8b97a7;
          --bar:#3b82f6; --accent:#60a5fa; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font-family:"Microsoft YaHei","Segoe UI",system-ui,sans-serif; font-size:14px; }
  header { padding:16px 24px; border-bottom:1px solid var(--line);
           display:flex; align-items:center; justify-content:space-between; }
  h1 { margin:0; font-size:18px; font-weight:600; }
  h1 small { color:var(--mut); font-weight:400; font-size:13px; margin-left:8px; }
  .stopbtn { background:#3a1f24; color:#fda4af; border:1px solid #5b2a32;
             border-radius:6px; padding:7px 14px; cursor:pointer; font-size:13px; }
  .stopbtn:hover { background:#4a262c; }
  .wrap { padding:18px 24px; max-width:1100px; margin:0 auto; }
  .controls { display:flex; flex-wrap:wrap; gap:14px; align-items:center;
              background:var(--card); border:1px solid var(--line); border-radius:10px;
              padding:14px 16px; margin-bottom:16px; }
  .controls label { color:var(--mut); margin-right:6px; }
  select, input[type=date], input[type=number] {
    background:#0d1117; color:var(--fg); border:1px solid var(--line);
    border-radius:6px; padding:6px 8px; font-size:14px; }
  .seg { display:inline-flex; border:1px solid var(--line); border-radius:6px; overflow:hidden; }
  .seg button { background:#0d1117; color:var(--mut); border:0; padding:6px 12px;
                cursor:pointer; font-size:14px; }
  .seg button.active { background:var(--accent); color:#001; font-weight:600; }
  .summary { display:flex; flex-wrap:wrap; gap:18px; margin-bottom:14px; color:var(--mut); }
  .summary b { color:var(--fg); }
  table { width:100%; border-collapse:collapse; background:var(--card);
          border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  th, td { padding:9px 12px; text-align:left; border-bottom:1px solid var(--line); }
  th { color:var(--mut); font-weight:500; font-size:12px; }
  tr:last-child td { border-bottom:0; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .key { font-weight:600; max-width:320px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .barcell { width:30%; }
  .bar { height:16px; background:var(--bar); border-radius:3px; min-width:2px; }
  .tag { font-size:11px; padding:1px 7px; border-radius:10px; white-space:nowrap; }
  .tag.proxy { background:rgba(59,130,246,.18); color:#93c5fd; }
  .tag.direct { background:rgba(34,197,94,.16); color:#86efac; }
  .node { color:var(--mut); font-size:12px; }
  .empty { color:var(--mut); padding:30px; text-align:center; }
  .rank { color:var(--mut); width:30px; }
  .overlay { position:fixed; inset:0; background:rgba(10,14,20,.92); display:none;
             align-items:center; justify-content:center; text-align:center; font-size:18px; }
</style>
</head>
<body>
<header>
  <h1>ProxyTrace <small>代理流量都去了哪些网站</small></h1>
  <button class="stopbtn" id="stop">⏻ 停止采集并退出</button>
</header>
<div class="wrap">
  <div class="controls">
    <span><label>日期</label><input type="date" id="date"></span>
    <span><label>维度</label>
      <span class="seg" id="dim">
        <button data-v="host" class="active">域名</button>
        <button data-v="process">软件</button>
        <button data-v="node">节点</button>
        <button data-v="policy">策略组</button>
      </span>
    </span>
    <span><label>范围</label>
      <span class="seg" id="proxied">
        <button data-v="all" class="active">全部</button>
        <button data-v="1">仅代理</button>
        <button data-v="0">仅直连</button>
      </span>
    </span>
    <span><label>显示前</label><input type="number" id="top" value="30" min="5" max="500" style="width:70px"> 项</span>
  </div>

  <div class="summary" id="summary"></div>
  <div id="result"></div>
</div>
<div class="overlay" id="overlay">已停止采集，程序已退出。<br>可以关闭此页面了。</div>

<script>
const $ = (s) => document.querySelector(s);
let dim = "host", proxied = "all";

function fmt(n) {
  n = Number(n || 0);
  const u = ["B","KB","MB","GB","TB","PB"]; let i = 0;
  while (n >= 1024 && i < u.length-1) { n /= 1024; i++; }
  return (i === 0 ? n.toFixed(0) : n.toFixed(2)) + " " + u[i];
}
function pct(a, b) { return b > 0 ? (a/b*100).toFixed(1) + "%" : "0%"; }

async function loadDates() {
  try {
    const r = await fetch("/api/dates"); const j = await r.json();
    const d = $("#date");
    const today = new Date().toLocaleDateString("sv");  // YYYY-MM-DD 本地
    if (!d.value) d.value = (j.dates && j.dates.length) ? j.dates[0] : today;
  } catch (e) {}
}

async function load() {
  const date = $("#date").value;
  const top = $("#top").value || 30;
  try {
    const r = await fetch(`/api/top?date=${date}&dim=${dim}&top=${top}&proxied=${proxied}`);
    render(await r.json());
  } catch (e) {
    $("#result").innerHTML = `<div class="empty">读取数据失败，程序可能已停止。</div>`;
  }
}

function render(j) {
  const s = j.summary || {};
  const grand = (s.proxied_total||0) + (s.direct_total||0);
  $("#summary").innerHTML =
    `当日总流量 <b>${fmt(grand)}</b>` +
    ` ·  代理 <b>${fmt(s.proxied_total)}</b> (${pct(s.proxied_total, grand)})` +
    ` ·  直连 <b>${fmt(s.direct_total)}</b>` +
    ` ·  下行 <b>${fmt(s.download)}</b> 上行 <b>${fmt(s.upload)}</b>` +
    ` ·  涉及域名 <b>${s.hosts||0}</b> 个`;

  const rows = j.rows || [];
  if (!rows.length) {
    $("#result").innerHTML = `<div class="empty">该日暂无数据。<br>请确认采集程序正在运行，并稍候产生流量后刷新。</div>`;
    return;
  }
  const max = rows[0].total || 1;
  const dimName = {host:"域名", process:"软件", node:"节点", policy:"策略组"}[dim];
  let html = `<table><thead><tr>
      <th class="rank">#</th><th>${dimName}</th><th class="barcell">流量占比</th>
      <th class="num">下行</th><th class="num">上行</th><th class="num">合计</th>
      <th>出口/类型</th></tr></thead><tbody>`;
  rows.forEach((r, i) => {
    const w = Math.max(2, Math.round((r.total / max) * 100));
    const isProxy = (r.proxied_bytes||0) >= (r.direct_bytes||0) && (r.proxied_bytes||0) > 0;
    const tag = (dim === "node")
      ? ""
      : (isProxy ? `<span class="tag proxy">代理</span>` : `<span class="tag direct">直连</span>`);
    const node = (dim === "node") ? "" : `<span class="node">${escapeHtml(r.node||"")}</span> `;
    html += `<tr>
      <td class="rank">${i+1}</td>
      <td class="key" title="${escapeHtml(r.key||"")}">${escapeHtml(r.key||"")}</td>
      <td class="barcell"><div class="bar" style="width:${w}%"></div></td>
      <td class="num">${fmt(r.download)}</td>
      <td class="num">${fmt(r.upload)}</td>
      <td class="num"><b>${fmt(r.total)}</b></td>
      <td>${node}${tag}</td>
    </tr>`;
  });
  html += `</tbody></table>`;
  $("#result").innerHTML = html;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

function bindSeg(id, setter) {
  document.querySelectorAll(`#${id} button`).forEach(b => {
    b.onclick = () => {
      document.querySelectorAll(`#${id} button`).forEach(x => x.classList.remove("active"));
      b.classList.add("active");
      setter(b.dataset.v);
      load();
    };
  });
}

bindSeg("dim", v => dim = v);
bindSeg("proxied", v => proxied = v);
$("#date").addEventListener("change", load);
$("#top").addEventListener("change", load);
$("#stop").addEventListener("click", async () => {
  if (!confirm("确定要停止采集并退出程序吗？\n停止后将不再记录流量，网页也会失效。")) return;
  try { await fetch("/api/shutdown"); } catch (e) {}
  $("#overlay").style.display = "flex";
});

(async () => { await loadDates(); await load(); })();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 静默，避免刷屏

    def _send(self, body: bytes, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        db_path = self.server.db_path

        if u.path in ("/", "/index.html"):
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return

        if u.path == "/api/shutdown":
            self._json({"ok": True})
            cb = getattr(self.server, "on_shutdown", None)
            if cb:
                try:
                    cb()
                except Exception:
                    pass
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        if u.path == "/api/dates":
            st = Storage(db_path)
            try:
                self._json({"dates": st.available_dates()})
            finally:
                st.close()
            return

        if u.path == "/api/top":
            q = parse_qs(u.query)
            date = (q.get("date") or [datetime.date.today().strftime("%Y-%m-%d")])[0]
            dim = (q.get("dim") or ["host"])[0]
            try:
                top = int((q.get("top") or ["30"])[0])
            except ValueError:
                top = 30
            pr = (q.get("proxied") or ["all"])[0]
            proxied = True if pr == "1" else (False if pr == "0" else None)
            st = Storage(db_path)
            try:
                rows = st.query_top(date, date, dim=dim, top_n=top, proxied=proxied)
                summary = st.query_summary(date, date)
            finally:
                st.close()
            self._json({"rows": rows, "summary": summary})
            return

        self._json({"error": "not found"}, 404)


class TraceServer(ThreadingHTTPServer):
    daemon_threads = True
    # 关闭地址复用：Windows 上 SO_REUSEADDR 会让重复实例也能绑定同一端口而不报错，
    # 关掉后第二个实例 bind 会抛 OSError，从而被识别为「已在运行」。
    allow_reuse_address = False

    def __init__(self, addr, db_path, on_shutdown=None):
        super().__init__(addr, Handler)
        self.db_path = db_path
        self.on_shutdown = on_shutdown


def create_server(cfg, on_shutdown=None):
    """创建面板服务器；若端口被占用会抛 OSError（表示已有实例在运行）。"""
    db_path = resolve_db_path(cfg)
    port = int(cfg.get("dashboard_port", 8788))
    return TraceServer(("127.0.0.1", port), db_path, on_shutdown)


def run_server(server, open_browser=False):
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"[dashboard] 面板地址：{url}")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] 正在停止……")
    finally:
        server.server_close()


def run(argv=None):
    cfg = load_config()
    server = create_server(cfg)
    run_server(server, open_browser=False)
