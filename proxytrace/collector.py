"""采集守护进程：轮询 /connections，按连接 id 做字节增量累加，定期写入 SQLite。

既可作为独立进程运行（python run.py collect，用信号停止），
也可由 app 模式以线程方式驱动（传入 stop_event）。
"""

import datetime
import os
import signal
import threading
import time

from .config import load_config, resolve_db_path
from .mihomo import MihomoClient
from .storage import Storage

# 这些「节点」名视为非代理出口（直连/拒绝等）
DIRECT_NODES = {"DIRECT", "REJECT", "REJECT-DROP", "REJECT-NO-DROP", "DROP", "PASS", "COMPATIBLE"}

# 持有互斥量句柄，防止被 GC 释放
_mutex_handle = None


def _today():
    return datetime.datetime.now().strftime("%Y-%m-%d")


def acquire_single_instance(name="ProxyTraceCollector"):
    """Windows 命名互斥量实现单实例；返回 False 表示已有实例在运行。"""
    global _mutex_handle
    if os.name != "nt":
        return True
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return False
    _mutex_handle = handle
    return True


def _extract(conn):
    """从一条连接里取出 (host, process, node, policy, proxied)。"""
    md = conn.get("metadata") or {}
    host = md.get("host") or md.get("sniffHost") or md.get("destinationIP") or "(unknown)"
    process = md.get("process") or "(unknown)"
    chains = conn.get("chains") or []
    if chains:
        node = chains[0]
        policy = chains[-1]
    else:
        node, policy = "(unknown)", ""
    proxied = 0 if node in DIRECT_NODES else 1
    return host, process, node, policy, proxied


def _flush(storage, agg):
    rows = [
        (date, host, process, node, policy, proxied, up, down, cn)
        for (date, host, process, node, policy, proxied), (up, down, cn) in agg.items()
    ]
    storage.upsert_batch(rows)


def run(stop_event=None, single_instance=True):
    """采集主循环。

    stop_event: threading.Event，置位即优雅停止。为 None 时自建并注册系统信号
                （仅适合在主线程作为独立进程运行）。
    single_instance: 是否用互斥量保证单实例（app 模式由端口保证，可传 False）。
    """
    cfg = load_config()
    db_path = resolve_db_path(cfg)

    if single_instance and acquire_single_instance() is False:
        print("[collector] 已有一个采集实例在运行，本次退出。")
        return

    if stop_event is None:
        stop_event = threading.Event()
        def _on_signal(signum, frame):
            stop_event.set()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _on_signal)
            except (ValueError, OSError):
                pass

    poll_interval = float(cfg.get("poll_interval", 1.0))
    flush_interval = float(cfg.get("flush_interval", 5.0))
    retention_days = int(cfg.get("retention_days", 0))

    storage = Storage(db_path)
    if retention_days > 0:
        cutoff = (datetime.date.today() - datetime.timedelta(days=retention_days)).strftime("%Y-%m-%d")
        storage.prune(cutoff)

    client = MihomoClient(cfg)

    prev = {}   # 连接 id -> (上次 upload, 上次 download)
    agg = {}    # (date, host, process, node, policy, proxied) -> [up, down, conns]

    print(f"[collector] 启动 | 传输={client.transport} | 数据库={db_path}")
    connected = False
    last_flush = time.time()

    while not stop_event.is_set():
        loop_start = time.time()
        try:
            data = client.get_connections()
            if not connected:
                print("[collector] 已连接 Clash 内核，开始记账……")
                connected = True
        except Exception as e:
            if connected:
                print(f"[collector] 与 Clash 内核断开（{e}），重试中……")
            connected = False
            prev = {}  # 内核可能重启，清空以免产生错误增量
            stop_event.wait(max(poll_interval, 2.0))
            continue

        date = _today()
        seen = {}
        for c in data.get("connections") or []:
            cid = c.get("id")
            if not cid:
                continue
            up = int(c.get("upload", 0) or 0)
            down = int(c.get("download", 0) or 0)
            seen[cid] = (up, down)
            p = prev.get(cid)
            if p is None:
                d_up, d_down, is_new = up, down, True
            else:
                d_up = up - p[0]
                d_down = down - p[1]
                if d_up < 0:
                    d_up = up
                if d_down < 0:
                    d_down = down
                is_new = False
            if not is_new and d_up == 0 and d_down == 0:
                continue
            host, process, node, policy, proxied = _extract(c)
            key = (date, host, process, node, policy, proxied)
            a = agg.get(key)
            if a is None:
                a = [0, 0, 0]
                agg[key] = a
            a[0] += d_up
            a[1] += d_down
            if is_new:
                a[2] += 1
        prev = seen  # 仅保留当前快照中的连接，关闭的连接其最后增量已计入

        now = time.time()
        if agg and now - last_flush >= flush_interval:
            _flush(storage, agg)
            agg = {}
            last_flush = now

        sleep_for = poll_interval - (time.time() - loop_start)
        if sleep_for > 0:
            stop_event.wait(sleep_for)

    if agg:
        _flush(storage, agg)
    storage.close()
    print("[collector] 已停止。")
