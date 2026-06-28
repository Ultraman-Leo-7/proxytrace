r"""mihomo / Clash 控制接口客户端。

支持两种传输：
  - pipe：Windows 命名管道（Clash Verge Rev 默认只走 \\.\pipe\verge-mihomo），
          用 ctypes 调 kernel32 直接收发 HTTP/1.1（含 chunked 解码）。
  - tcp ：开启了 external-controller 的场景，走标准 http.client。
"""

import json
import os

# ------------------------- HTTP 解析（与传输无关） -------------------------

def build_request(method, path, host="localhost", secret=""):
    headers = [
        f"{method} {path} HTTP/1.1",
        f"Host: {host}",
        "Accept: */*",
        "User-Agent: ProxyTrace/1.0",
    ]
    if secret:
        headers.append(f"Authorization: Bearer {secret}")
    headers.append("Connection: close")
    headers.append("")
    headers.append("")
    return "\r\n".join(headers).encode("utf-8")


def dechunk(body: bytes) -> bytes:
    """解析 Transfer-Encoding: chunked 的响应体。"""
    out = bytearray()
    i = 0
    n = len(body)
    while i < n:
        nl = body.find(b"\r\n", i)
        if nl == -1:
            break
        size_field = body[i:nl].split(b";")[0].strip()
        try:
            size = int(size_field, 16)
        except ValueError:
            break
        if size == 0:
            break
        start = nl + 2
        out += body[start:start + size]
        i = start + size + 2  # 跳过该块数据及其后的 CRLF
    return bytes(out)


def parse_http_response(raw: bytes):
    """返回 (status:int, headers:dict, body:bytes)。"""
    sep = raw.find(b"\r\n\r\n")
    if sep == -1:
        raise ValueError("HTTP 响应不完整（找不到头部分隔符）")
    head = raw[:sep].decode("iso-8859-1")
    body = raw[sep + 4:]
    lines = head.split("\r\n")
    status_line = lines[0].split(" ", 2)
    status = int(status_line[1]) if len(status_line) >= 2 and status_line[1].isdigit() else 0
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    te = headers.get("transfer-encoding", "").lower()
    if "chunked" in te:
        body = dechunk(body)
    elif "content-length" in headers:
        try:
            body = body[:int(headers["content-length"])]
        except ValueError:
            pass
    return status, headers, body


# ------------------------- Windows 命名管道传输 -------------------------

_PIPE_READY = os.name == "nt"

if _PIPE_READY:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _OPEN_EXISTING = 3
    _ERROR_PIPE_BUSY = 231
    _ERROR_BROKEN_PIPE = 109
    _ERROR_PIPE_NOT_CONNECTED = 233
    _ERROR_MORE_DATA = 234
    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _CreateFileW.restype = wintypes.HANDLE

    _ReadFile = _kernel32.ReadFile
    _ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    _ReadFile.restype = wintypes.BOOL

    _WriteFile = _kernel32.WriteFile
    _WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                           ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    _WriteFile.restype = wintypes.BOOL

    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL

    _WaitNamedPipeW = _kernel32.WaitNamedPipeW
    _WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    _WaitNamedPipeW.restype = wintypes.BOOL

    def pipe_request(pipe_name, raw_request: bytes, timeout_ms=3000) -> bytes:
        path = r"\\.\pipe" + "\\" + pipe_name
        handle = _CreateFileW(path, _GENERIC_READ | _GENERIC_WRITE, 0, None,
                              _OPEN_EXISTING, 0, None)
        if handle == _INVALID_HANDLE_VALUE:
            err = ctypes.get_last_error()
            if err == _ERROR_PIPE_BUSY:
                if not _WaitNamedPipeW(path, timeout_ms):
                    raise ConnectionError(f"命名管道忙且等待超时: {path}")
                handle = _CreateFileW(path, _GENERIC_READ | _GENERIC_WRITE, 0, None,
                                      _OPEN_EXISTING, 0, None)
                if handle == _INVALID_HANDLE_VALUE:
                    raise ConnectionError(f"无法打开命名管道 {path}（错误码 {ctypes.get_last_error()}）")
            else:
                raise ConnectionError(f"无法打开命名管道 {path}（错误码 {err}）")
        try:
            # 写入完整请求
            written = wintypes.DWORD(0)
            offset = 0
            total = len(raw_request)
            while offset < total:
                chunk = raw_request[offset:]
                if not _WriteFile(handle, chunk, len(chunk), ctypes.byref(written), None):
                    raise ConnectionError(f"写命名管道失败（错误码 {ctypes.get_last_error()}）")
                offset += written.value
            # 读取直到对端（Connection: close）关闭管道
            buf = bytearray()
            size = 65536
            readbuf = ctypes.create_string_buffer(size)
            nread = wintypes.DWORD(0)
            while True:
                ok = _ReadFile(handle, readbuf, size, ctypes.byref(nread), None)
                if not ok:
                    err = ctypes.get_last_error()
                    if err in (_ERROR_BROKEN_PIPE, _ERROR_PIPE_NOT_CONNECTED, 0):
                        break  # 正常 EOF
                    if err == _ERROR_MORE_DATA:
                        buf += readbuf.raw[:nread.value]
                        continue
                    raise ConnectionError(f"读命名管道失败（错误码 {err}）")
                if nread.value == 0:
                    break
                buf += readbuf.raw[:nread.value]
            return bytes(buf)
        finally:
            _CloseHandle(handle)


# ------------------------- 客户端 -------------------------

class MihomoClient:
    def __init__(self, cfg):
        transport = cfg.get("transport", "auto")
        if transport == "auto":
            transport = "pipe" if os.name == "nt" else "tcp"
        self.transport = transport
        self.pipe_name = cfg.get("pipe_name", "verge-mihomo")
        self.controller_url = cfg.get("controller_url", "http://127.0.0.1:9090")
        self.secret = cfg.get("secret", "")

    def _get_pipe(self, path):
        raw = pipe_request(self.pipe_name, build_request("GET", path, secret=self.secret))
        return parse_http_response(raw)

    def _get_tcp(self, path):
        import http.client
        from urllib.parse import urlparse
        u = urlparse(self.controller_url)
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=5)
        headers = {}
        if self.secret:
            headers["Authorization"] = f"Bearer {self.secret}"
        try:
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def get(self, path):
        if self.transport == "pipe":
            return self._get_pipe(path)
        return self._get_tcp(path)

    def get_json(self, path):
        status, _headers, body = self.get(path)
        if status != 200:
            raise ConnectionError(f"接口 {path} 返回状态 {status}")
        return json.loads(body.decode("utf-8"))

    def get_version(self):
        return self.get_json("/version")

    def get_connections(self):
        return self.get_json("/connections")
