from http import server, read_request, build_response, KEEPALIVE_TIMEOUT
import traceback
import json
from module import *

from routes import dispatch_request

def handle_connection(conn, addr):
    conn.settimeout(KEEPALIVE_TIMEOUT)
    try:
        while True:
            try:
                req = read_request(conn)
            except ValueError as e:
                resp = build_response(400, 'Bad Request', body=str(e))
                conn.sendall(resp)
                break
            except ConnectionError:
                break
            except Exception:
                traceback.print_exc()
                resp = build_response(500, 'Internal Server Error', body='Internal Server Error')
                try:
                    conn.sendall(resp)
                except:
                    pass
                break

            if req is None:
                break

            # Simple handling: echo path and method and headers; respond with 200
            status, head, body = dispatch_request(req.method, req.path, req.headers, req.body)
            headers = {}
            # Connection handling: if client requested close, honor it
            connection_hdr = req.headers.get('connection', '').lower()
            if req.version.upper() == 'HTTP/1.1':
                # default keep-alive unless client asks close
                if connection_hdr == 'close':
                    headers['Connection'] = 'close'
                    keep_alive = False
                else:
                    headers['Connection'] = 'keep-alive'
                    keep_alive = True
            else:
                # HTTP/1.0 default close unless client asks Keep-Alive
                if connection_hdr == 'keep-alive':
                    headers['Connection'] = 'keep-alive'
                    keep_alive = True
                else:
                    headers['Connection'] = 'close'
                    keep_alive = False
            
            headers.update(head)

            resp = build_response(status,'OK', headers=headers, body=body, version='HTTP/1.1')
            conn.sendall(resp)

            if not keep_alive:
                break
            # loop back and read next request on same connection
    finally:
        try:
            conn.close()
        except:
            pass

if __name__ == '__main__':
    
    HOST = '127.0.0.1'
    PORT = 8080

    server(handle_connection, host=HOST, port=PORT)
