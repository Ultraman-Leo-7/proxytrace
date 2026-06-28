"""命令行报表：按域名/软件/节点/策略组查看某天或某区间的代理流量。"""

import argparse
import datetime
import unicodedata

from .config import load_config, resolve_db_path
from .storage import Storage

_LABELS = {"host": "域名", "process": "软件", "node": "节点", "policy": "策略组"}


def human(n):
    n = float(n or 0)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{int(n)} {units[i]}" if i == 0 else f"{n:.2f} {units[i]}"


def _wlen(s):
    """字符串显示宽度（中文/全角算 2）。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def _truncate(s, width):
    s = str(s)
    if _wlen(s) <= width:
        return s
    out = ""
    w = 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in "WF" else 1
        if w + cw > width - 1:
            return out + "…"
        out += c
        w += cw
    return out


def _pad(s, width, align="left"):
    s = str(s)
    gap = max(0, width - _wlen(s))
    return s + " " * gap if align == "left" else " " * gap + s


def _date_range(args):
    today = datetime.date.today()
    if args.date:
        return args.date, args.date
    if args.from_ and args.to:
        return args.from_, args.to
    if args.days and args.days > 1:
        start = today - datetime.timedelta(days=args.days - 1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    return today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def run(argv=None):
    ap = argparse.ArgumentParser(prog="report", description="代理流量报表")
    ap.add_argument("--date", help="指定日期 YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=1, help="最近 N 天（默认 1=今天）")
    ap.add_argument("--from", dest="from_", help="起始日期 YYYY-MM-DD")
    ap.add_argument("--to", help="结束日期 YYYY-MM-DD")
    ap.add_argument("--top", type=int, default=20, help="显示前 N 项（默认 20）")
    ap.add_argument("--by", choices=list(_LABELS), default="host", help="统计维度")
    ap.add_argument("--proxied-only", action="store_true", help="只看走代理的流量")
    ap.add_argument("--direct-only", action="store_true", help="只看直连流量")
    args = ap.parse_args(argv)

    cfg = load_config()
    storage = Storage(resolve_db_path(cfg))
    try:
        d_from, d_to = _date_range(args)
        proxied = True if args.proxied_only else (False if args.direct_only else None)
        rows = storage.query_top(d_from, d_to, dim=args.by, top_n=args.top, proxied=proxied)
        summary = storage.query_summary(d_from, d_to)
    finally:
        storage.close()

    label = _LABELS[args.by]
    rng = d_from if d_from == d_to else f"{d_from} ~ {d_to}"
    flt = "（仅代理）" if proxied is True else ("（仅直连）" if proxied is False else "")
    kw = 30  # 维度列宽

    print()
    print(f"  代理流量报表  [{rng}]  维度：按{label}{flt}")
    print("  " + "-" * 78)
    if not rows:
        print("  （该时间段暂无数据；请确认采集程序 collect 已在后台运行）")
    else:
        print("  " + _pad("#", 3) + " " + _pad(label, kw) + " "
              + _pad("下行", 11, "right") + " " + _pad("上行", 11, "right") + " "
              + _pad("合计", 11, "right") + "  出口节点")
        for i, r in enumerate(rows, 1):
            print("  " + _pad(str(i), 3) + " " + _pad(_truncate(r["key"], kw), kw) + " "
                  + _pad(human(r["download"]), 11, "right") + " "
                  + _pad(human(r["upload"]), 11, "right") + " "
                  + _pad(human(r["total"]), 11, "right") + "  "
                  + _truncate(r["node"], 24))
    print("  " + "-" * 78)
    ptotal, dtotal = summary["proxied_total"], summary["direct_total"]
    grand = ptotal + dtotal
    pct = (ptotal / grand * 100) if grand else 0.0
    print(f"  代理合计：{human(ptotal)}    直连合计：{human(dtotal)}    "
          f"代理占比：{pct:.1f}%    涉及域名：{summary['hosts']} 个")
    print()
