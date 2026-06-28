"""SQLite 存储：建表（WAL）、批量 UPSERT、按维度查询、保留期清理。"""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS traffic (
  date     TEXT    NOT NULL,
  host     TEXT    NOT NULL,
  process  TEXT    NOT NULL,
  node     TEXT    NOT NULL,
  policy   TEXT    NOT NULL DEFAULT '',
  proxied  INTEGER NOT NULL DEFAULT 0,
  upload   INTEGER NOT NULL DEFAULT 0,
  download INTEGER NOT NULL DEFAULT 0,
  conns    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (date, host, process, node)
);
CREATE INDEX IF NOT EXISTS idx_traffic_date ON traffic(date);
"""

_COLS = ["date", "host", "process", "node", "policy", "proxied", "upload", "download", "conns"]
_DIMS = ("host", "process", "node", "policy")


class Storage:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert_batch(self, rows):
        """rows: 可迭代的 (date, host, process, node, policy, proxied, upload, download, conns)。"""
        rows = list(rows)
        if not rows:
            return
        self.conn.executemany(
            """
            INSERT INTO traffic (date, host, process, node, policy, proxied, upload, download, conns)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, host, process, node) DO UPDATE SET
              upload   = upload   + excluded.upload,
              download = download + excluded.download,
              conns    = conns    + excluded.conns,
              policy   = excluded.policy,
              proxied  = excluded.proxied
            """,
            rows,
        )
        self.conn.commit()

    def _fetch_rows(self, date_from, date_to, proxied=None):
        where = ["date >= ?", "date <= ?"]
        params = [date_from, date_to]
        if proxied is True:
            where.append("proxied = 1")
        elif proxied is False:
            where.append("proxied = 0")
        sql = ("SELECT date, host, process, node, policy, proxied, upload, download, conns "
               "FROM traffic WHERE " + " AND ".join(where))
        return self.conn.execute(sql, params).fetchall()

    def query_top(self, date_from, date_to, dim="host", top_n=20, proxied=None):
        """按某维度聚合并返回 top N（在内存聚合，便于附带代表性出口节点）。"""
        if dim not in _DIMS:
            dim = "host"
        key_idx = _COLS.index(dim)
        agg = {}          # key -> dict
        node_bytes = {}   # key -> {node: total}
        for r in self._fetch_rows(date_from, date_to, proxied):
            key = r[key_idx]
            up, down, cn, is_proxied, node = r[6], r[7], r[8], r[5], r[3]
            a = agg.get(key)
            if a is None:
                a = {"key": key, "upload": 0, "download": 0, "conns": 0,
                     "proxied_bytes": 0, "direct_bytes": 0}
                agg[key] = a
            a["upload"] += up
            a["download"] += down
            a["conns"] += cn
            if is_proxied:
                a["proxied_bytes"] += up + down
            else:
                a["direct_bytes"] += up + down
            nb = node_bytes.setdefault(key, {})
            nb[node] = nb.get(node, 0) + up + down
        out = []
        for key, a in agg.items():
            nb = node_bytes.get(key)
            rep_node = max(nb.items(), key=lambda kv: kv[1])[0] if nb else ""
            out.append({
                "key": key,
                "upload": a["upload"],
                "download": a["download"],
                "total": a["upload"] + a["download"],
                "conns": a["conns"],
                "node": rep_node,
                "proxied_bytes": a["proxied_bytes"],
                "direct_bytes": a["direct_bytes"],
            })
        out.sort(key=lambda x: x["total"], reverse=True)
        return out[:top_n] if top_n else out

    def query_summary(self, date_from, date_to):
        r = self.conn.execute(
            """
            SELECT
              COALESCE(SUM(CASE WHEN proxied=1 THEN download+upload ELSE 0 END), 0),
              COALESCE(SUM(CASE WHEN proxied=0 THEN download+upload ELSE 0 END), 0),
              COALESCE(SUM(download), 0),
              COALESCE(SUM(upload), 0),
              COUNT(DISTINCT host)
            FROM traffic WHERE date >= ? AND date <= ?
            """,
            (date_from, date_to),
        ).fetchone()
        return {
            "proxied_total": r[0],
            "direct_total": r[1],
            "download": r[2],
            "upload": r[3],
            "hosts": r[4],
        }

    def available_dates(self):
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT date FROM traffic ORDER BY date DESC").fetchall()]

    def prune(self, before_date):
        self.conn.execute("DELETE FROM traffic WHERE date < ?", (before_date,))
        self.conn.commit()

    def close(self):
        self.conn.close()
