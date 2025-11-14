import socket
import threading
import traceback
import time
from datetime import datetime

HOST = '0.0.0.0'
PORT = 8080
RECV_BUFFER = 8192
KEEPALIVE_TIMEOUT = 5  # seconds for idle keep-alive connections

class HTTPRequest:
    def __init__(self, method, path, version, headers, body):
        self.method = method
        self.path = path
        self.version = version
        self.headers = headers
        self.body = body

def recv_until(sock, delimiter=b'\r\n\r\n', timeout=None):
    sock.settimeout(timeout)
    data = b''
    try:
        while delimiter not in data:
            part = sock.recv(RECV_BUFFER)
            if not part:
                break
            data += part
    except socket.timeout:
        pass
    finally:
        sock.settimeout(None)
    return data

def recv_exact(sock, size):
    data = b''
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise ConnectionError("connection closed while reading body")
        data += part
    return data

def parse_headers(header_bytes):
    lines = header_bytes.decode('iso-8859-1').split('\r\n')
    request_line = lines[0]
    parts = request_line.split(' ', 2)
    if len(parts) != 3:
        raise ValueError("Invalid request line")
    method, path, version = parts
    headers = {}
    for line in lines[1:]:
        if not line:
            continue
        if ':' not in line:
            continue
        k, v = line.split(':', 1)
        headers[k.strip().lower()] = v.strip()
    return method, path, version, headers

def read_chunked_body(sock, initial=b''):
    # initial may contain part of the chunked body after headers
    data = initial
    body = b''
    while True:
        # read up to CRLF line containing chunk-size
        while b'\r\n' not in data:
            part = sock.recv(RECV_BUFFER)
            if not part:
                raise ConnectionError("connection closed during chunk size")
            data += part
        line, _, data = data.partition(b'\r\n')
        chunk_size = int(line.split(b';')[0].strip(), 16)
        if chunk_size == 0:
            # consume trailing header CRLF if present
            # possibly there are trailer headers (ignored here)
            # read until '\r\n\r\n' or at least the final '\r\n'
            # consume remaining CRLF
            if len(data) < 2:
                data += recv_exact(sock, 2 - len(data))
            # read and ignore trailers (we'll stop at blank line)
            if b'\r\n\r\n' in data:
                # done
                pass
            else:
                # try to read rest (conservative)
                try:
                    more = recv_until(sock, b'\r\n\r\n', timeout=0.5)
                except Exception:
                    more = b''
            break
        # ensure we have chunk_size bytes + trailing CRLF
        while len(data) < chunk_size + 2:
            part = sock.recv(RECV_BUFFER)
            if not part:
                raise ConnectionError("connection closed during chunk data")
            data += part
        chunk = data[:chunk_size]
        body += chunk
        data = data[chunk_size+2:]  # skip chunk and trailing CRLF
    return body

def read_request(sock):
    # Read headers
    raw = recv_until(sock, b'\r\n\r\n', timeout=KEEPALIVE_TIMEOUT)
    if not raw:
        return None
    header_part, _, rest = raw.partition(b'\r\n\r\n')
    try:
        method, path, version, headers = parse_headers(header_part)
    except Exception:
        raise ValueError("Malformed request")
    # Host header required in HTTP/1.1
    if version.upper() == 'HTTP/1.1' and 'host' not in headers:
        raise ValueError("Host header required for HTTP/1.1")

    body = b''
    # Handle Expect: 100-continue
    if headers.get('expect') == '100-continue':
        sock.sendall(b'HTTP/1.1 100 Continue\r\n\r\n')

    if 'content-length' in headers:
        try:
            cl = int(headers['content-length'])
        except:
            cl = 0
        # rest may contain part of the body
        if rest:
            rest_body = rest
            to_read = cl - len(rest_body)
            if to_read > 0:
                rest_body += recv_exact(sock, to_read)
            body = rest_body[:cl]
        else:
            if cl > 0:
                body = recv_exact(sock, cl)
    elif headers.get('transfer-encoding') == 'chunked':
        body = read_chunked_body(sock, initial=rest)
    else:
        # No body expected for most GET/HEAD; leave body empty
        body = b''
    return HTTPRequest(method, path, version, headers, body)

# 常见状态码原因短表（用于自动补全 reason）
_STATUS_REASONS = {
    200: 'OK', 201: 'Created', 204: 'No Content', 301: 'Moved Permanently',
    302: 'Found', 400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden',
    404: 'Not Found', 405: 'Method Not Allowed', 500: 'Internal Server Error'
}

def build_response(status_code=200, reason=None, headers=None, body=b'', version='HTTP/1.1'):
    """
    构造完整的 HTTP 响应（bytes）。
    - body 可为 bytes 或 str。
    - headers 为 dict，可包含 Content-Type / Connection 等（函数会补全必要头）。
    - 返回已经编码好的响应字节，可直接 conn.sendall(resp).
    """
    if headers is None:
        headers = {}

    # body 转 bytes
    if isinstance(body, str):
        body = body.encode('utf-8')

    # 自动填充常用头
    headers = dict(headers)  # 复制一份避免修改外部
    headers.setdefault('Date', datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT'))
    headers.setdefault('Server', 'SimplePythonHTTP/1.1')
    # 不强制覆盖用户传入的 Content-Type，但若未提供则默认 html
    headers.setdefault('Content-Type', 'text/html; charset=utf-8')
    # 支持前端 fetch 调试的简单 CORS（生产按需修改）
    headers.setdefault('Access-Control-Allow-Origin', '*')

    # Content-Length（若没有 Transfer-Encoding: chunked）
    if 'Transfer-Encoding' not in {k.title(): v for k, v in headers.items()}:
        headers['Content-Length'] = str(len(body))

    # 状态行 reason 推断
    if reason is None:
        reason = _STATUS_REASONS.get(int(status_code), 'OK')

    # 构造头部文本
    header_lines = ''.join(f'{k}: {v}\r\n' for k, v in headers.items())
    status_line = f'{version} {status_code} {reason}\r\n'
    resp = status_line + header_lines + '\r\n'
    return resp.encode('iso-8859-1') + body



def server(handle_connection, host=HOST, port=PORT):
    print(f"Listening on {host}:{port} (HTTP/1.1 compatible)")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(128)
    try:
        while True:
            conn, addr = s.accept()
            t = threading.Thread(target=handle_connection, args=(conn, addr), daemon=True)
            t.start()
    finally:
        s.close()
