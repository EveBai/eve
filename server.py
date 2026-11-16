"""Local preview of the test-code workflow. Run with python3 server.py."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import sys
import time
import unicodedata
from collections import Counter, deque
from contextlib import closing
from datetime import datetime
from getpass import getpass
from html import escape
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore, Lock
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
VALIDITY = 30 * 24 * 60 * 60
ATTEMPT_DURATION = 2 * 60 * 60
TEST_NAME = "你的灵魂是哪种家电"
TEST_ID = "appliance-v1"
QUESTIONS = (
    ("周末突然空出一整个下午，你会？", ("约人吃点热乎的", "找个舒服的地方吹风", "窝着慢慢看收藏夹")),
    ("朋友来找你吐槽时，你更容易？", ("先接住情绪，再约一顿饭", "换个角度，帮对方透口气", "安静听完，再把细节记在心里")),
    ("如果要送朋友一份小礼物，你会选？", ("新出炉的点心", "一张散步路线图", "一盒替对方挑好的小零食")),
)
RESULTS = (
    ("烤面包机", "你喜欢把平凡的日子烘成香喷喷的小事。"),
    ("小风扇", "你擅长给忙乱的日子留一点透气的空间。"),
    ("小冰箱", "你习惯默默留一格空间，装下朋友喜欢的小事。"),
)
ASSETS = {
    "/style.css": "text/css; charset=utf-8",
    "/quiz.js": "text/javascript; charset=utf-8",
    "/homepage-plush-concept.png": "image/png",
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS codes (
    code TEXT PRIMARY KEY,
    test_id TEXT NOT NULL,
    label TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER,
    revoked_at INTEGER
);
CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL REFERENCES codes(code),
    nickname TEXT NOT NULL,
    nickname_key TEXT NOT NULL,
    browser_token TEXT NOT NULL,
    show_on_board INTEGER NOT NULL,
    UNIQUE(code, nickname_key),
    UNIQUE(code, browser_token)
);
CREATE TABLE IF NOT EXISTS attempts (
    token TEXT PRIMARY KEY,
    code TEXT NOT NULL REFERENCES codes(code),
    started_at INTEGER NOT NULL,
    completed_at INTEGER,
    result_index INTEGER,
    participant_id INTEGER REFERENCES participants(id)
);
CREATE INDEX IF NOT EXISTS attempts_by_code ON attempts(code, completed_at);
"""


def connect():
    db = sqlite3.connect(os.environ.get("QUIZ_DB", ROOT / ".quiz-data" / "quiz.sqlite3"))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize_db(db):
    db.executescript(SCHEMA)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(attempts)")}
    if "participant_id" not in columns:
        db.execute("ALTER TABLE attempts ADD COLUMN participant_id INTEGER REFERENCES participants(id)")
    db.execute("CREATE INDEX IF NOT EXISTS attempts_by_participant ON attempts(participant_id, completed_at)")


def timestamp(value):
    if value is None:
        return "—"
    return datetime.fromtimestamp(value, ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")


def active_error(row, now):
    if row is None:
        return HTTPStatus.NOT_FOUND, "没有找到这个测试码。"
    if row["revoked_at"] is not None:
        return HTTPStatus.FORBIDDEN, "这个测试码已停用。"
    if row["expires_at"] is not None and row["expires_at"] <= now:
        return HTTPStatus.GONE, "这个测试码已到期。"
    return None


def issue_code():
    value = secrets.token_hex(10).upper()
    return "-".join(value[i:i + 5] for i in range(0, len(value), 5))


def normalize_code(value):
    normalized = re.sub(r"[\s-]+", "", value).upper()
    if not re.fullmatch(r"[0-9A-F]{20}", normalized):
        return ""
    return "-".join(normalized[i:i + 5] for i in range(0, 20, 5))


def normalize_nickname(value):
    return " ".join(unicodedata.normalize("NFKC", value).split())


def leaderboard(db, code):
    return db.execute("""
        SELECT p.id, p.nickname, count(*) AS finishes,
            (SELECT latest.result_index FROM attempts latest
             WHERE latest.participant_id = p.id AND latest.completed_at IS NOT NULL
             ORDER BY latest.completed_at DESC, latest.rowid DESC LIMIT 1) AS result_index
        FROM participants p JOIN attempts a ON a.participant_id = p.id
        WHERE p.code = ? AND p.show_on_board = 1 AND a.completed_at IS NOT NULL
        GROUP BY p.id
        ORDER BY finishes DESC, p.id ASC LIMIT 25
    """, (code,)).fetchall()


class QuizServer(ThreadingHTTPServer):
    def __init__(self, address, handler):
        self.workers = BoundedSemaphore(32)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.workers.release()


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def respond(self, body, status=HTTPStatus.OK, content_type="text/html; charset=utf-8", headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; form-action 'self'")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def page(self, title, content, status=HTTPStatus.OK, headers=()):
        markup = f"""<!doctype html><html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · 开心测试局</title><link rel="stylesheet" href="/style.css"></head>
<body><header class="wrap nav"><a href="/" class="brand">开心测试局</a>
<nav aria-label="主导航"><a href="/code">输入测试码</a><a href="/admin">发码后台</a></nav></header>
<main class="wrap workflow"><h1>{escape(title)}</h1>{content}</main></body></html>"""
        self.respond(markup.encode(), status, headers=headers)

    def redirect(self, location, headers=()):
        self.respond(b"", HTTPStatus.SEE_OTHER, headers=(("Location", location), *headers))

    def admin_session(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
            token = cookies["quiz_admin"].value
            expiry, nonce, signature = token.split(".")
            expected = hmac.digest(self.server.signing_key, f"{expiry}.{nonce}".encode(), "sha256").hex()
            return int(expiry) > time.time() and hmac.compare_digest(expected, signature)
        except (KeyError, ValueError):
            return False

    def login_cookie(self):
        expiry = int(time.time()) + 4 * 60 * 60
        payload = f"{expiry}.{secrets.token_hex(16)}"
        signature = hmac.digest(self.server.signing_key, payload.encode(), "sha256").hex()
        return self.cookie("quiz_admin", f"{payload}.{signature}", "/admin", 14400)

    def cookie(self, name, value, path, age):
        secure = "; Secure" if self.server.cloud else ""
        return ("Set-Cookie", f"{name}={value}; Max-Age={age}; Path={path}; HttpOnly; SameSite=Strict{secure}")

    def visitor_token(self):
        cookies = SimpleCookie()
        cookies.load(self.headers.get("Cookie", ""))
        visitor = cookies.get("quiz_visitor")
        if visitor and re.fullmatch(r"[A-Za-z0-9_-]{43}", visitor.value):
            return visitor.value
        return ""

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            html = (ROOT / "index.html").read_text().replace(
                '<a href="#discover">发现测试</a>',
                '<a href="#discover">发现测试</a><a href="/code">输入测试码</a>',
            ).replace(
                '<p>是热情的烤面包机，还是淡定的小风扇？</p><small>筹备中</small>',
                '<p>是热情的烤面包机，还是淡定的小风扇？</p><a class="primary" href="/code">测试码解锁</a>',
            )
            self.respond(html.encode())
        elif path in ASSETS:
            self.respond((ROOT / path[1:]).read_bytes(), content_type=ASSETS[path])
        elif path == "/admin":
            if self.server.password_hash is None:
                self.page("后台暂未开放", "<p>管理员需要先配置登录密码。</p>", HTTPStatus.SERVICE_UNAVAILABLE)
            elif self.admin_session():
                self.admin_page()
            else:
                self.login_page()
        elif path == "/code":
            self.code_page()
        elif path == "/healthz":
            self.respond(b"ok\n", content_type="text/plain; charset=utf-8")
        else:
            self.page("找不到页面", '<p><a href="/">返回首页</a></p>', HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlsplit(self.path).path
        if self.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}:
            return self.page("请在本站提交表单", "", HTTPStatus.FORBIDDEN)
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{self.headers.get('Host')}", f"https://{self.headers.get('Host')}"}:
            return self.page("请在本站提交表单", "", HTTPStatus.FORBIDDEN)
        if path.startswith("/admin/") and path != "/admin/login" and not self.admin_session():
            return self.login_page("请先登录后台。", HTTPStatus.UNAUTHORIZED)
        length = self.headers.get("Content-Length", "")
        if not length.isdecimal() or len(length) > 4 or int(length) > 4096:
            return self.page("请求内容过长或不可读", "", HTTPStatus.BAD_REQUEST)
        if self.headers.get_content_type() != "application/x-www-form-urlencoded":
            return self.page("无法读取表单", "", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            form = parse_qs(self.rfile.read(int(length)).decode(), max_num_fields=20)
        except (ValueError, UnicodeError):
            return self.page("无法读取表单", "", HTTPStatus.BAD_REQUEST)

        def field(name):
            return form.get(name, [""])[0]

        if path == "/admin/login":
            self.login(field("password"))
        elif path == "/admin/logout":
            self.redirect("/admin", (self.cookie("quiz_admin", "", "/admin", 0),))
        elif path == "/admin/codes":
            self.create_code(field("label").strip())
        elif path == "/admin/revoke":
            with closing(connect()) as db, db:
                db.execute("UPDATE codes SET revoked_at = ? WHERE code = ? AND revoked_at IS NULL", (int(time.time()), field("code")))
            self.redirect("/admin")
        elif path == "/code/start":
            self.start_test(normalize_code(field("code")), normalize_nickname(field("nickname")), field("rank") == "yes")
        elif path == "/code/submit":
            self.complete_test(field("attempt"), [field(f"q{i}") for i in range(len(QUESTIONS))])
        else:
            self.page("找不到页面", "", HTTPStatus.NOT_FOUND)

    def login_page(self, message="", status=HTTPStatus.OK):
        self.page("管理员登录", f"""<p role="status">{escape(message)}</p>
<form method="post" action="/admin/login" class="sheet">
<label>管理员密码 <input type="password" name="password" autocomplete="current-password" required></label>
<button class="primary">登录</button></form>""", status)

    def login(self, password):
        if self.server.password_hash is None:
            return self.page("后台暂未开放", "<p>管理员需要先配置登录密码。</p>", HTTPStatus.SERVICE_UNAVAILABLE)
        now = time.monotonic()
        with self.server.login_lock:
            failures = self.server.login_failures
            while failures and failures[0] <= now - 60:
                failures.popleft()
            if len(failures) >= 8:
                return self.login_page("登录尝试过多，请一分钟后再试。", HTTPStatus.TOO_MANY_REQUESTS)
            if not hmac.compare_digest(hashlib.sha256(password.encode()).digest(), self.server.password_hash):
                failures.append(now)
                return self.login_page("管理员密码不正确。", HTTPStatus.UNAUTHORIZED)
        self.redirect("/admin", (self.login_cookie(),))

    def create_code(self, label):
        if len(label) > 80:
            return self.page("备注最多 80 个字符", '<p><a href="/admin">返回发码后台</a></p>', HTTPStatus.BAD_REQUEST)
        with closing(connect()) as db, db:
            db.execute("INSERT INTO codes (code, test_id, label, created_at) VALUES (?, ?, ?, ?)",
                       (issue_code(), TEST_ID, label, int(time.time())))
        self.redirect("/admin")

    def admin_page(self):
        with closing(connect()) as db:
            rows = db.execute("""
                SELECT c.*, (SELECT count(*) FROM attempts a
                    WHERE a.code = c.code AND a.completed_at IS NOT NULL) AS completions
                FROM codes c ORDER BY c.rowid DESC
            """).fetchall()
        now = int(time.time())
        items = []
        for row in rows:
            code = escape(row["code"])
            status = ("已停用" if row["revoked_at"] is not None else
                      "未激活" if row["expires_at"] is None else
                      "已过期" if row["expires_at"] <= now else "可使用")
            action = ""
            if status in {"未激活", "可使用"}:
                action = f"""<form method="post" action="/admin/revoke">
<input type="hidden" name="code" value="{code}"><button class="back">停用</button></form>"""
            deadline = timestamp(row["expires_at"]) if row["expires_at"] is not None else "首次使用后开始计时"
            items.append(f"""<li class="sheet"><strong><code>{code}</code></strong>
<p>{escape(row["label"] or TEST_NAME)} · {status}</p>
<p>到期时间 {deadline} · 完成 {row["completions"]} 次</p>{action}</li>""")
        entries = "".join(items) or "<li>还没有生成测试码。</li>"
        self.page("测试码管理", f"""<form method="post" action="/admin/codes" class="sheet">
<p>指定测试 · {TEST_NAME}</p><p>首次使用起 30 天内有效，可多人重复使用。</p>
<label>发放备注 <input type="text" name="label" maxlength="80" placeholder="例如 周五朋友局"></label>
<button class="primary">生成测试码</button></form>
<h2>已发测试码</h2><ul class="code-list">{entries}</ul>
<form method="post" action="/admin/logout"><button class="back">退出后台</button></form>""")

    def code_page(self, message="", status=HTTPStatus.OK, code="", nickname="", ranked=False):
        checked = " checked" if ranked else ""
        self.page("输入测试码", f"""<p role="status">{escape(message)}</p>
<form method="post" action="/code/start" class="sheet">
<label>测试码 <input name="code" value="{escape(code)}" autocomplete="off" spellcheck="false" required maxlength="40"></label>
<label>昵称 <input name="nickname" value="{escape(nickname)}" autocomplete="nickname" required maxlength="20"></label>
<p class="form-hint">1–20 个字符。同一浏览器重测时，请继续使用原昵称。</p>
<label class="rank-choice"><input type="checkbox" name="rank" value="yes"{checked}>
在同码排行榜显示我的昵称和最新结果</label>
<button class="primary">解锁并开始</button></form>""", status)

    def start_test(self, code, nickname, ranked):
        if not 1 <= len(nickname) <= 20 or any(unicodedata.category(char) == "Cc" for char in nickname):
            return self.code_page("请输入 1–20 个字符的昵称。", HTTPStatus.BAD_REQUEST, code, nickname, ranked)
        now = int(time.time())
        attempt = secrets.token_urlsafe(32)
        visitor = self.visitor_token() or secrets.token_urlsafe(32)
        nickname_key = nickname.casefold()
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM codes WHERE code = ? AND test_id = ?", (code, TEST_ID)).fetchone()
            error = active_error(row, now)
            if error:
                return self.code_page(error[1], error[0], code, nickname, ranked)
            owner = db.execute("SELECT * FROM participants WHERE code = ? AND browser_token = ?", (code, visitor)).fetchone()
            if owner and owner["nickname_key"] != nickname_key:
                return self.code_page(f"请继续使用原昵称「{owner['nickname']}」。", HTTPStatus.CONFLICT, code, nickname, ranked)
            if owner:
                participant = owner["id"]
                db.execute("UPDATE participants SET show_on_board = ? WHERE id = ?", (ranked, participant))
            else:
                existing = db.execute("SELECT 1 FROM participants WHERE code = ? AND nickname_key = ?", (code, nickname_key)).fetchone()
                if existing:
                    return self.code_page("这个昵称已被使用，请换一个。", HTTPStatus.CONFLICT, code, nickname, ranked)
                participant = db.execute("""INSERT INTO participants (code, nickname, nickname_key, browser_token, show_on_board)
                    VALUES (?, ?, ?, ?, ?)""", (code, nickname, nickname_key, visitor, ranked)).lastrowid
            if row["expires_at"] is None:
                db.execute("UPDATE codes SET expires_at = ? WHERE code = ?", (now + VALIDITY, code))
            db.execute("INSERT INTO attempts (token, code, started_at, participant_id) VALUES (?, ?, ?, ?)",
                       (attempt, code, now, participant))
        cookie = self.cookie("quiz_visitor", visitor, "/code", 7776000)
        self.test_page(attempt, cookie)

    def test_page(self, attempt, cookie):
        fields = []
        for index, (prompt, options) in enumerate(QUESTIONS):
            choices = "".join(f'<label class="quiz-option"><input type="radio" name="q{index}" value="{n}" required> {escape(option)}</label>' for n, option in enumerate(options))
            fields.append(f"<fieldset><legend>{escape(prompt)}</legend>{choices}</fieldset>")
        self.page(TEST_NAME, f"""<form method="post" action="/code/submit" class="sheet">
<input type="hidden" name="attempt" value="{escape(attempt)}">{''.join(fields)}
<button class="primary">查看结果</button></form>""", headers=(cookie,))

    def complete_test(self, token, answers):
        if any(answer not in {"0", "1", "2"} for answer in answers):
            return self.code_page("请重新开始测试并完成所有题目。", HTTPStatus.BAD_REQUEST)
        now = int(time.time())
        proposed = Counter(map(int, answers)).most_common(1)[0][0]
        result = proposed
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT a.*, c.expires_at, c.revoked_at, p.browser_token, p.show_on_board FROM attempts a
                JOIN codes c ON a.code = c.code LEFT JOIN participants p ON p.id = a.participant_id
                WHERE a.token = ? AND c.test_id = ?""", (token, TEST_ID)).fetchone()
            error = active_error(row, now)
            if error is None:
                if row["participant_id"] is not None and row["browser_token"] != self.visitor_token():
                    error = HTTPStatus.FORBIDDEN, "请回到开始测试的浏览器，或重新输入测试码。"
                elif row["completed_at"] is not None:
                    result = row["result_index"]
                elif now - row["started_at"] >= ATTEMPT_DURATION:
                    error = HTTPStatus.GONE, "这次答题已超时，请重新输入测试码。"
                else:
                    db.execute("UPDATE attempts SET completed_at = ?, result_index = ? WHERE token = ?",
                               (time.time_ns(), result, token))
            entries = leaderboard(db, row["code"]) if error is None else []
        if error:
            return self.code_page(error[1], error[0])
        title, description = RESULTS[result]
        board = self.render_board(entries, row["participant_id"], row["show_on_board"])
        self.page(f"你像一台{title}", f"""<div class="sheet"><p>{escape(description)}</p>
<a class="primary" href="/code">再测一次</a></div>{board}""")

    def render_board(self, entries, participant, visible):
        listing = []
        rank = 0
        previous = None
        for position, entry in enumerate(entries, 1):
            if entry["finishes"] != previous:
                rank = position
                previous = entry["finishes"]
            name = escape(entry["nickname"])
            if entry["id"] == participant:
                name += ' <small class="board-you">你</small>'
            title = escape(RESULTS[entry["result_index"]][0])
            listing.append(f'<li class="board-row"><span>{rank}</span><div><strong>{name}</strong><small>最近结果 · {title}</small></div><span>{entry["finishes"]} 次</span></li>')
        detail = "<p>还没有人选择上榜。</p>"
        if listing:
            detail = f'<ol class="board-list">{"".join(listing)}</ol>'
        private = "<p>你这次选择不在榜上展示。</p>" if participant and not visible else ""
        return f"""<section class="sheet" aria-labelledby="board-title"><h2 id="board-title">同码排行榜</h2>
<p>按完成次数排列，次数相同并列，最多展示 25 人。</p>{private}{detail}</section>"""


def main():
    cloud = os.environ.get("QUIZ_CLOUD") == "1"
    password = os.environ.get("QUIZ_ADMIN_PASSWORD")
    if cloud:
        password_file = Path(os.environ.get("QUIZ_ADMIN_PASSWORD_FILE", "/run/secrets/quiz-admin/password"))
        if password_file.is_file():
            password = password_file.read_text().rstrip("\r\n")
        if not password or len(password) < 20:
            password = None
    else:
        if password is None and sys.stdin.isatty():
            password = getpass("为本次预览设置管理员密码（至少 12 个字符）：")
        if not password or len(password) < 12:
            sys.exit("请设置至少 12 个字符的管理员密码。")
    db_path = Path(os.environ.get("QUIZ_DB", ROOT / ".quiz-data" / "quiz.sqlite3"))
    db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if cloud and os.getuid() == 0:
        os.chown(db_path.parent, 10001, 10001)
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    with closing(connect()) as db, db:
        initialize_db(db)
    address = "0.0.0.0" if cloud else "127.0.0.1"
    with QuizServer((address, int(os.environ.get("PORT", "8080"))), Handler) as server:
        server.cloud = cloud
        server.signing_key = hmac.digest(password.encode(), b"happy-quiz/admin-session/v1", "sha256") if cloud and password else secrets.token_bytes(32)
        server.password_hash = hashlib.sha256(password.encode()).digest() if password else None
        server.login_lock = Lock()
        server.login_failures = deque()
        print(f"Listening on {address}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
