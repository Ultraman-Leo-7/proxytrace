"""配置读写：首次运行自动生成 config.json，并提供默认值。"""

import json
import os

DEFAULTS = {
    "transport": "auto",                          # auto | pipe | tcp
    "pipe_name": "verge-mihomo",                   # Windows 命名管道名（Clash Verge Rev）
    "controller_url": "http://127.0.0.1:9090",     # transport=tcp 时使用
    "secret": "",                                  # external-controller 密钥（管道无需）
    "poll_interval": 1.0,                          # 轮询 /connections 的间隔（秒）
    "flush_interval": 5.0,                          # 内存聚合写入数据库的间隔（秒）
    "db_path": "data/traffic.db",                  # SQLite 路径（相对项目根目录）
    "dashboard_port": 8788,                        # 网页面板端口
    "retention_days": 0,                           # 数据保留天数，0=永久
}


def project_root():
    """项目根目录（proxytrace/ 的上一级）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_path():
    return os.path.join(project_root(), "config.json")


def load_config():
    """读取配置；缺失的键用默认值补齐，文件不存在则写入默认配置。"""
    path = config_path()
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user = json.load(f)
            for k in DEFAULTS:
                if k in user:
                    cfg[k] = user[k]
        except Exception as e:
            print(f"[config] 读取 config.json 失败，改用默认值: {e}")
    else:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULTS, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[config] 写入默认 config.json 失败: {e}")
    return cfg


def resolve_db_path(cfg):
    """把 db_path 解析为绝对路径并确保目录存在。"""
    db_path = cfg.get("db_path", DEFAULTS["db_path"])
    if not os.path.isabs(db_path):
        db_path = os.path.join(project_root(), db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return db_path
