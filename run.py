"""ProxyTrace 统一入口。

常用（小白）：
  双击 启动.vbs   后台启动采集 + 网页面板，并自动打开浏览器
  双击 停止.vbs   停止采集并关闭网页

命令行：
  python run.py app           一体化运行（采集 + 网页面板，前台）
  python run.py stop          停止后台运行的 app
  python run.py report [...]   查看报表（默认今天 top20，详见 --help）
  python run.py collect        只启动采集（前台；Ctrl+C 停止）
  python run.py dashboard      只启动网页面板（前台）
  python run.py test           测试与 Clash 内核的连接
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _setup_output():
    """统一输出编码；在 pythonw（无控制台）下把输出重定向到日志文件。"""
    if sys.stdout is None or sys.stderr is None:
        logdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        try:
            os.makedirs(logdir, exist_ok=True)
            f = open(os.path.join(logdir, "proxytrace.log"), "a", encoding="utf-8", buffering=1)
            if sys.stdout is None:
                sys.stdout = f
            if sys.stderr is None:
                sys.stderr = f
        except Exception:
            pass
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _stop():
    from proxytrace.app import pid_file
    import signal
    pf = pid_file()
    if not os.path.exists(pf):
        print("未发现正在运行的 app（无 PID 文件）。")
        return
    try:
        with open(pf, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except Exception as e:
        print(f"读取 PID 失败：{e}")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"已停止 app（PID {pid}）。")
    except ProcessLookupError:
        print("该进程已不存在。")
    except Exception as e:
        print(f"停止失败：{e}")
    try:
        os.remove(pf)
    except Exception:
        pass


def _test_connection():
    from proxytrace.config import load_config
    from proxytrace.mihomo import MihomoClient
    client = MihomoClient(load_config())
    print("传输方式：", client.transport)
    try:
        print("内核版本：", client.get_version().get("version"))
        data = client.get_connections()
        conns = data.get("connections") or []
        print(f"当前活跃连接：{len(conns)} 条 | "
              f"累计下行 {data.get('downloadTotal')} B | 累计上行 {data.get('uploadTotal')} B")
        for c in conns[:8]:
            md = c.get("metadata") or {}
            host = md.get("host") or md.get("destinationIP")
            node = (c.get("chains") or ["?"])[0]
            print(f"  · {host}  ←  {md.get('process')}  via {node}")
        print("\n连接正常 ✔  可以双击 启动.vbs 开始记账。")
    except Exception as e:
        print(f"\n连接失败：{e}")
        print("请确认 Clash Verge Rev 正在运行；若用 TCP 方式，请在 config.json 配置 controller_url/secret。")


def main():
    _setup_output()
    args = sys.argv[1:]
    cmd = args[0].lower() if args else "help"
    rest = args[1:]

    if cmd == "app":
        from proxytrace import app
        app.run()
    elif cmd == "stop":
        _stop()
    elif cmd == "collect":
        from proxytrace import collector
        collector.run()
    elif cmd == "dashboard":
        from proxytrace import dashboard
        dashboard.run(rest)
    elif cmd == "report":
        from proxytrace import report
        report.run(rest)
    elif cmd in ("test", "version"):
        _test_connection()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
