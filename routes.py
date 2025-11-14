import json
from urllib.parse import urlparse, parse_qs
from typing import Callable, Dict, Tuple, Any, Optional

from module import DB, UserManager, ArticleManager, Article

import os

db = DB()
user_mgr = UserManager(db)
article_mgr = ArticleManager(db)

RouteResult = Tuple[int, Dict[str, str], bytes]  # status, headers, body

def json_response(obj: Any, status: int = 200) -> RouteResult:
    body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    return status, {'Content-Type': 'application/json; charset=utf-8'}, body

def text_response(text: str, status: int = 200) -> RouteResult:
    return status, {'Content-Type': 'text/plain; charset=utf-8'}, text.encode('utf-8')

def html_response(html: str, status: int = 200, headers: Dict[str, str] | None = None) -> RouteResult:
    body = html.encode('utf-8')
    hdrs = {
        'Content-Type': 'text/html; charset=utf-8',
        'Content-Length': str(len(body)),
        'Access-Control-Allow-Origin': '*'
    }
    if headers:
        hdrs.update(headers)
    return status, hdrs, body

def match_pattern(path: str, pattern: str) -> Optional[Dict[str, str]]:
    """简单路径匹配，支持 /api/articles/<id> 形式"""
    p_parts = [p for p in path.split('/') if p != '']
    t_parts = [p for p in pattern.split('/') if p != '']
    if len(p_parts) != len(t_parts):
        return None
    params = {}
    for pp, tp in zip(p_parts, t_parts):
        if tp.startswith('<') and tp.endswith('>'):
            key = tp[1:-1]
            params[key] = pp
        elif pp != tp:
            return None
    return params

# 路由表： 每一项为 (HTTP_METHOD, pattern) -> handler(func)
# Handler 入参: (method, path, query_dict, headers_dict, body_bytes)
RouteHandler = Callable[[str, str, Dict[str, Any], Dict[str, str], bytes], RouteResult]
routes: Dict[Tuple[str, str], RouteHandler] = {}

def route(method: str, pattern: str):
    def _decor(fn: RouteHandler):
        routes[(method.upper(), pattern)] = fn
        return fn
    return _decor

@route('GET', '/')
def index_handler(method, path, query, headers, body):
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            content = f.read()
        return html_response(content, status=200)
    except Exception as e:
        return json_response({'error': 'Could not load index.html'}, status=500)
# ---- Handlers ----

@route('GET', '/api/metrics')
def metrics_handler(method, path, query, headers, body):
    # 简单示例：在线数用 users 表与文章数做近似演示
    try:
        users = db.query("SELECT COUNT(*) as c FROM users")[0]['c']
    except Exception:
        users = 0
    try:
        posts = db.query("SELECT COUNT(*) as c FROM articles WHERE status='published'")[0]['c']
    except Exception:
        posts = 0
    data = {'online': users, 'daily': posts}
    return json_response(data)

@route('GET', '/api/articles')
def list_articles(method, path, query, headers, body):
    search = query.get('search', [''])[0] if 'search' in query else ''
    sort_by = query.get('sort', ['relevance'])[0] if 'sort' in query else 'relevance'
    limit = int(query.get('limit', ['20'])[0])
    offset = int(query.get('offset', ['0'])[0])
    arts = article_mgr.search.query(keyword=search or None, sort_by=sort_by, limit=limit, offset=offset)
    return json_response([a.to_dict() for a in arts])

@route('GET', '/api/articles/<id>')
def get_article(method, path, query, headers, body):
    params = match_pattern(path, '/api/articles/<id>')
    aid = int(params['id'])
    a = article_mgr.get_article(aid)
    if not a:
        return json_response({'error': 'not found'}, status=404)
    return json_response(a.to_dict())

@route('POST', '/api/articles')
def create_article(method, path, query, headers, body):
    try:
        payload = json.loads(body.decode('utf-8') or '{}')
        title = payload.get('title') or '未命名'
        content = payload.get('content', '')
        owner = payload.get('owner', 'guest')
        art = article_mgr.create_article(owner, title, content)
        return json_response(art.to_dict(), status=201)
    except Exception as e:
        return json_response({'error': str(e)}, status=400)

@route('PUT', '/api/articles/<id>')
def edit_article(method, path, query, headers, body):
    try:
        params = match_pattern(path, '/api/articles/<id>')
        aid = int(params['id'])
        payload = json.loads(body.decode('utf-8') or '{}')
        owner = payload.get('owner', 'guest')
        title = payload.get('title')
        content = payload.get('content')
        art = article_mgr.edit_article(aid, owner, title=title, content=content)
        return json_response(art.to_dict())
    except PermissionError as pe:
        return json_response({'error': str(pe)}, status=403)
    except Exception as e:
        return json_response({'error': str(e)}, status=400)

@route('POST', '/api/articles/<id>/publish')
def publish_article(method, path, query, headers, body):
    try:
        params = match_pattern(path, '/api/articles/<id>/publish')
        aid = int(params['id'])
        payload = json.loads(body.decode('utf-8') or '{}')
        owner = payload.get('owner', 'guest')
        art = article_mgr.publish_article(aid, owner)
        return json_response(art.to_dict())
    except PermissionError as pe:
        return json_response({'error': str(pe)}, status=403)
    except Exception as e:
        return json_response({'error': str(e)}, status=400)

@route('POST', '/api/articles/<id>/like')
def like_article(method, path, query, headers, body):
    try:
        params = match_pattern(path, '/api/articles/<id>/like')
        aid = int(params['id'])
        payload = json.loads(body.decode('utf-8') or '{}')
        user = payload.get('user', 'guest')
        article_mgr.like_article(aid, user)
        return json_response({'ok': True})
    except Exception as e:
        return json_response({'error': str(e)}, status=400)

@route('POST', '/api/login')
def login_handler(method, path, query, headers, body):
    try:
        payload = json.loads(body.decode('utf-8') or '{}')
        name = payload.get('name') or payload.get('username')
        pwd = payload.get('pwd') or payload.get('password')
        if not name or not pwd:
            return json_response({'error': 'missing credentials'}, status=400)
        ok = user_mgr.authenticate(name, pwd)
        return json_response({'ok': ok})
    except Exception as e:
        return json_response({'error': str(e)}, status=400)

@route('POST', '/api/register')
def register_handler(method, path, query, headers, body):
    try:
        payload = json.loads(body.decode('utf-8') or '{}')
        name = payload.get('name')
        pwd = payload.get('pwd')
        if not name or not pwd:
            return json_response({'error': 'missing fields'}, status=400)
        user = user_mgr.register(name, pwd)
        return json_response(user.to_dict(), status=201)
    except Exception as e:
        return json_response({'error': str(e)}, status=400)

@route('GET', '/api/user/<name>')
def get_user(method, path, query, headers, body):
    params = match_pattern(path, '/api/user/<name>')
    name = params['name']
    u = user_mgr.get_user(name)
    if not u:
        return json_response({'error': 'not found'}, status=404)
    return json_response(u.to_dict())

@route('GET', '/api/user/<name>/articles')
def user_articles(method, path, query, headers, body):
    params = match_pattern(path, '/api/user/<name>/articles')
    name = params['name']
    rows = db.query("SELECT * FROM articles WHERE owner = ? ORDER BY created_at DESC", (name,))
    arts = [Article(title=r['title'], content=r['content'], owner=r['owner'],
                    priority=r['priority'], status=r['status'], aid=r['id'],
                    created_at=r['created_at'], updated_at=r['updated_at'], likes=r['likes']).to_dict() for r in rows]
    return json_response(arts)

# ---- Dispatcher used by your http server ----
def dispatch_request(method: str, raw_path: str, headers: Dict[str, str], body: bytes) -> RouteResult:
    """主分发函数。raw_path 可包含查询串。"""
    u = urlparse(raw_path)
    path = u.path
    query = parse_qs(u.query)
    # 精确匹配或带参数模式匹配
    # 优先查找 exact
    key = (method.upper(), path)
    if key in routes:
        return routes[key](method, path, query, headers, body)
    # 模式匹配
    for (m, pattern), handler in routes.items():
        if m != method.upper():
            continue
        params = match_pattern(path, pattern)
        if params is not None:
            return handler(method, path, query, headers, body)
    return json_response({'error': 'not found'}, status=404)