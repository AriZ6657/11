import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = 'forum_blog.db'


class Guest:
    """匿名用户：可浏览、点赞（如允许）。"""
    name = 'guest'
    password = ''
    priority = 0


class User:
    def __init__(self, name: str, password: str, priority: int = 1, uid: Optional[int] = None):
        self.id = uid
        self.name = name
        self.password = password
        self.priority = priority

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'priority': self.priority}


class Article:
    def __init__(self, title: str, content: str, owner: str, priority: int = 0,
                 status: str = 'draft', aid: Optional[int] = None,
                 created_at: Optional[str] = None, updated_at: Optional[str] = None, likes: int = 0):
        self.id = aid
        self.title = title
        self.content = content
        self.owner = owner
        self.priority = priority
        self.status = status  # draft / published
        self.created_at = created_at
        self.updated_at = updated_at or self.created_at
        self.likes = likes

    def to_dict(self):
        return {
            'id': self.id, 'title': self.title, 'content': self.content,
            'owner': self.owner, 'priority': self.priority, 'status': self.status,
            'created_at': self.created_at, 'updated_at': self.updated_at, 'likes': self.likes
        }


class DB:
    """轻量封装 sqlite 连接与初始化"""
    def __init__(self, path=DB_PATH):
        self.path = path
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 1
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            owner TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft',
            likes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            article_id INTEGER,
            PRIMARY KEY (user_id, article_id)
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            user_id INTEGER,
            article_id INTEGER,
            PRIMARY KEY (user_id, article_id)
        );
        """)
        # ensure guest user exists
        cur.execute("INSERT OR IGNORE INTO users(name,password,priority) VALUES(?, ?, ?)", ('guest', '', 0))
        self.conn.commit()

    def execute(self, sql: str, params: tuple = ()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        self.conn.commit()
        return cur

    def query(self, sql: str, params: tuple = ()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


class UserManager:
    def __init__(self, db: Optional[DB] = None):
        self.db = db or DB()

    def register(self, name: str, password: str, priority: int = 1) -> User:
        if not name or not password:
            raise ValueError("用户名或密码不能为空")
        try:
            self.db.execute("INSERT INTO users(name,password,priority) VALUES(?,?,?)", (name, password, priority))
        except sqlite3.IntegrityError:
            raise ValueError("User already exists")
        row = self.db.query("SELECT * FROM users WHERE name = ?", (name,))[0]
        return User(name=row['name'], password=row['password'], priority=row['priority'], uid=row['id'])

    def authenticate(self, name: str, password: str) -> bool:
        rows = self.db.query("SELECT * FROM users WHERE name = ? AND password = ?", (name, password))
        return len(rows) > 0

    def get_user(self, name: str) -> Optional[User]:
        rows = self.db.query("SELECT * FROM users WHERE name = ?", (name,))
        if not rows:
            return None
        r = rows[0]
        return User(name=r['name'], password=r['password'], priority=r['priority'], uid=r['id'])

    def list_users(self) -> List[Dict[str, Any]]:
        rows = self.db.query("SELECT id,name,priority FROM users")
        return [dict(r) for r in rows]


class ArticleManager:
    def __init__(self, db: Optional[DB] = None):
        self.db = db or DB()
        self.search = ArticleSearchSubManager(self.db)

    def create_article(self, owner: str, title: str, content: str, priority: int = 0) -> Article:
        now = datetime.utcnow().isoformat()
        cur = self.db.execute(
            "INSERT INTO articles(title,content,owner,priority,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (title, content, owner, priority, 'draft', now, now)
        )
        aid = cur.lastrowid
        row = self.db.query("SELECT * FROM articles WHERE id = ?", (aid,))[0]
        return Article(title=row['title'], content=row['content'], owner=row['owner'], priority=row['priority'],
                       status=row['status'], aid=row['id'], created_at=row['created_at'], updated_at=row['updated_at'],
                       likes=row['likes'])

    def edit_article(self, article_id: int, owner: str, title: Optional[str] = None, content: Optional[str] = None) -> Article:
        row = self.db.query("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not row:
            raise ValueError("Article not found")
        r = row[0]
        if r['owner'] != owner:
            raise PermissionError("Only owner can edit")
        new_title = title if title is not None else r['title']
        new_content = content if content is not None else r['content']
        now = datetime.utcnow().isoformat()
        self.db.execute("UPDATE articles SET title=?, content=?, updated_at=? WHERE id=?", (new_title, new_content, now, article_id))
        r2 = self.db.query("SELECT * FROM articles WHERE id = ?", (article_id,))[0]
        return Article(title=r2['title'], content=r2['content'], owner=r2['owner'], priority=r2['priority'],
                       status=r2['status'], aid=r2['id'], created_at=r2['created_at'], updated_at=r2['updated_at'],
                       likes=r2['likes'])

    def publish_article(self, article_id: int, owner: str) -> Article:
        row = self.db.query("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not row:
            raise ValueError("Article not found")
        if row[0]['owner'] != owner:
            raise PermissionError("Only owner can publish")
        now = datetime.utcnow().isoformat()
        self.db.execute("UPDATE articles SET status='published', updated_at=? WHERE id=?", (now, article_id))
        r = self.db.query("SELECT * FROM articles WHERE id = ?", (article_id,))[0]
        return Article(title=r['title'], content=r['content'], owner=r['owner'], priority=r['priority'],
                       status=r['status'], aid=r['id'], created_at=r['created_at'], updated_at=r['updated_at'], likes=r['likes'])

    def like_article(self, article_id: int, user_name: str) -> None:
        user = self.db.query("SELECT id FROM users WHERE name = ?", (user_name,))
        if not user:
            raise ValueError("User not found")
        uid = user[0]['id']
        # ignore duplicate likes
        try:
            self.db.execute("INSERT INTO likes(user_id, article_id) VALUES(?,?)", (uid, article_id))
            self.db.execute("UPDATE articles SET likes = likes + 1 WHERE id = ?", (article_id,))
        except sqlite3.IntegrityError:
            pass

    def favorite_article(self, article_id: int, user_name: str) -> None:
        user = self.db.query("SELECT id FROM users WHERE name = ?", (user_name,))
        if not user:
            raise ValueError("User not found")
        uid = user[0]['id']
        try:
            self.db.execute("INSERT INTO favorites(user_id, article_id) VALUES(?,?)", (uid, article_id))
        except sqlite3.IntegrityError:
            pass

    def get_article(self, article_id: int) -> Optional[Article]:
        rows = self.db.query("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not rows:
            return None
        r = rows[0]
        return Article(title=r['title'], content=r['content'], owner=r['owner'], priority=r['priority'],
                       status=r['status'], aid=r['id'], created_at=r['created_at'], updated_at=r['updated_at'], likes=r['likes'])

    def list_published(self, limit: int = 20, offset: int = 0) -> List[Article]:
        rows = self.db.query("SELECT * FROM articles WHERE status='published' ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
        return [Article(title=r['title'], content=r['content'], owner=r['owner'], priority=r['priority'],
                        status=r['status'], aid=r['id'], created_at=r['created_at'], updated_at=r['updated_at'], likes=r['likes']) for r in rows]


class ArticleSearchSubManager:
    """子管理器：搜索/排序/分页等查询功能"""
    def __init__(self, db: DB):
        self.db = db

    def query(self, keyword: Optional[str] = None, sort_by: str = 'relevance', limit: int = 20, offset: int = 0) -> List[Article]:
        # 支持按 relevance(匹配度)、likes、date、priority 排序
        sql_base = "SELECT *, " \
                   "(CASE WHEN title LIKE ? THEN 2 WHEN content LIKE ? THEN 1 ELSE 0 END) AS relevance " \
                   "FROM articles WHERE status='published' "
        params = (f'%{keyword}%', f'%{keyword}%') if keyword else ('%%', '%%')
        order_clause = "ORDER BY relevance DESC, created_at DESC"
        if sort_by == 'likes':
            order_clause = "ORDER BY likes DESC, created_at DESC"
        elif sort_by == 'date':
            order_clause = "ORDER BY created_at DESC"
        elif sort_by == 'priority':
            order_clause = "ORDER BY priority DESC, created_at DESC"
        sql = f"{sql_base} {order_clause} LIMIT ? OFFSET ?"
        rows = self.db.query(sql, params + (limit, offset))
        return [Article(title=r['title'], content=r['content'], owner=r['owner'], priority=r['priority'],
                        status=r['status'], aid=r['id'], created_at=r['created_at'], updated_at=r['updated_at'], likes=r['likes']) for r in rows]


