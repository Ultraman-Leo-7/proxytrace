"""一体化入口：在同一个进程里同时运行「采集」+「网页面板」。

  - 双击 启动.vbs 即以 pythonw 隐藏方式运行本模块（无终端黑窗）。
  - 启动后自动打开浏览器；采集与面板都在后台持续工作。
  - 重复启动会自动检测到已有实例（端口被占），转而打开网页后退出。
  - 通过网页上的「停止」按钮、或双击 停止.vbs 即可整体退出。
"""

import os
import threading
import webbrowser

from .config import load_config, resolve_db_path, project_root
from . import collector, dashboard


def pid_file():
    return os.path.join(project_root(), "data", "proxytrace.pid")


def _write_pid():
    try:
        with open(pid_file(), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def _remove_pid():
    try:
        os.remove(pid_file())
    except Exception:
        pass


def run():
    cfg = load_config()
    resolve_db_path(cfg)  # 确保 data 目录存在
    port = int(cfg.get("dashboard_port", 8788))

    # 单实例守卫（命名互斥量，Windows 上可靠）：已在运行则只打开网页后退出，
    # 避免重复采集。进程退出时互斥量由系统自动释放。
    if collector.acquire_single_instance() is False:
        print("[app] 已有实例在运行，打开网页面板。")
        webbrowser.open(f"http://127.0.0.1:{port}")
        return

    stop_event = threading.Event()

    # 端口绑定（已关闭地址复用）作为双保险：万一互斥量没拦住，bind 失败也会退出
    try:
        server = dashboard.create_server(cfg, on_shutdown=stop_event.set)
    except OSError:
        print("[app] 端口已被占用，直接打开网页面板。")
        webbrowser.open(f"http://127.0.0.1:{port}")
        return

    _write_pid()

    # 采集线程（单实例由端口保证，这里不再走互斥量）
    t = threading.Thread(
        target=collector.run,
        kwargs={"stop_event": stop_event, "single_instance": False},
        daemon=True,
    )
    t.start()
    print("[app] 采集 + 网页面板已启动。")

    try:
        dashboard.run_server(server, open_browser=True)
    finally:
        stop_event.set()
        _remove_pid()
        print("[app] 已退出。")
