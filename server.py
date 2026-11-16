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
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Test:
    title: str
    duration: str
    questions: tuple
    results: tuple


FULL_TEST_ID = "appliance-full-v1"
FULL_QUESTIONS = (
    ("周末起床发现今天没有安排，你最想？", ("约人吃顿热乎的早午餐", "开窗吹风，等兴致来了再出门", "从冰箱翻点存货，慢慢吃", "顺手洗个衣服，让家里清爽一点")),
    ("下班路上突然下雨，你会？", ("找家亮着灯的店，点杯热饮", "等雨小一点，走条没试过的路", "到家换上舒服的衣服，安静待会儿", "回家先把湿透的鞋袜和雨伞收拾好")),
    ("朋友临时来串门，你先做什么？", ("抓把零食端出来，坐下就聊", "推开窗，把喜欢的歌放起来", "看看家里有没有对方爱吃的东西", "腾个地方放包，再把桌子擦一遍")),
    ("你最想把哪一种声音带回家？", ("厨房里食物刚出炉的轻响", "树叶被风吹动的沙沙声", "深夜只剩下小声的雨滴", "洗完衣服后机器发出的提示音")),
    ("朋友情绪低落，给你发了条消息。你会？", ("马上回消息，问要不要吃点东西聊聊", "约对方出去走一圈，换换环境", "先听完，记着过两天再问问近况", "问清楚哪件事最烦，看看能帮上什么")),
    ("聚会冷场了，你通常会？", ("讲一件今天发生的好笑小事", "提议大家换个位置或换个游戏", "跟旁边也没说话的人聊两句", "问大家接下来想干嘛，找个都能参与的活动")),
    ("约好的出游计划泡汤了，你更容易说？", ("那就改成吃饭吧，出来见个面也很好", "正好，附近有没有没去过的地方？", "没关系，我们想去的地方先留着，下次再约", "我查一下其他场次，看看还能不能赶上")),
    ("给亲近的人准备礼物，你更可能选？", ("当天做的小点心，趁热送过去", "一张说走就走的展览门票", "对方随口说过想要的小物件", "能解决一个日常小麻烦的实用品")),
    ("忙乱的一天结束了，你怎么让自己缓下来？", ("吃一顿喜欢的饭，给今天画个句号", "出去吹吹风，手机调静音", "留点独处时间，看一集熟悉的剧", "收好桌面，把明天需要做的事写下来")),
    ("朋友突然说想办个周末小聚，你最愿意负责？", ("招呼大家，顺手带点好吃的", "找一家新店，或者想个有趣的主题", "问问大家有没有忌口和偏好", "确定时间和地点，提前订好位置")),
    ("一整天只能留出十分钟给自己，你会选？", ("泡杯喜欢的热饮，慢慢喝完", "望一会儿窗外，什么安排都先放下", "把想记住的一件小事记下来", "处理掉一件一直压在心上的小事")),
    ("你希望朋友散场后怎么形容你？", ("跟你在一起，很快就能聊开", "跟你在一起，连改计划也挺好玩", "你记得那些别人没注意的小事", "有你在，大家总能把事情安排妥当")),
)
FULL_RESULTS = (
    ("烤面包机", "你常常用很具体的小事表达关心。一杯热饮、一句马上回的消息，都能让人感觉被接住。忙起来也给自己留一份热乎的。"),
    ("小风扇", "你会给僵住的场面一点松动的空间。换条路、换首歌，或者先出去走十分钟，常常就是你的办法。今天也可以留一段无安排的时间。"),
    ("小冰箱", "你会把朋友随口提到的小事放在心上。你给人的安心感往往来自这些不声不响的细节。偶尔也可以直接说说你想要什么。"),
    ("洗衣机", "你擅长把乱成一团的事情理出顺序。朋友在纠结下一步时，你往往已经想好了一个可以试的办法。做完一件事，也记得歇一会儿。"),
)
TESTS = {
    TEST_ID: Test(f"{TEST_NAME} · 速测版", "3 题 · 约 1 分钟", QUESTIONS, RESULTS),
    FULL_TEST_ID: Test(f"{TEST_NAME} · 完整版", "12 题 · 约 5 分钟", FULL_QUESTIONS, FULL_RESULTS),
}
ASSETS = {
    "/style.css": "text/css; charset=utf-8",
    "/quiz.js": "text/javascript; charset=utf-8",
    "/homepage-plush-concept.png": "image/png",
    **dict.fromkeys(("/friend-role.html", "/observation.html", "/chat-match.html"), "text/html; charset=utf-8"),
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

    def page(self, title, content, status=HTTPStatus.OK, headers=(), wide=False):
        layout = "workflow workflow-wide" if wide else "workflow"
        markup = f"""<!doctype html><html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · 开心测试局</title><link rel="stylesheet" href="/style.css"></head>
<body><header class="wrap nav"><a href="/" class="brand"><span class="art logo" aria-hidden="true"></span>开心测试局</a>
<nav aria-label="主导航"><a href="/#discover">更多测试</a><a href="/admin">发码后台</a></nav></header>
<main class="wrap {layout}"><h1>{escape(title)}</h1>{content}</main></body></html>"""
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
                'href="appliance.html"', 'href="/code/topic"',
            )
            self.respond(html.encode())
        elif path == "/appliance.html":
            self.redirect("/code/topic")
        elif path == "/code/topic":
            self.appliance_topic()
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

    def appliance_topic(self):
        html = (ROOT / "appliance.html").read_text().replace("<head>", '<head><base href="/">', 1)
        visitor = self.visitor_token()
        if visitor:
            with closing(connect()) as db:
                participant = db.execute("""
                    SELECT p.id, p.code, p.show_on_board, c.test_id
                    FROM participants p JOIN codes c ON c.code = p.code
                    JOIN attempts a ON a.participant_id = p.id
                    WHERE p.browser_token = ? AND a.completed_at IS NOT NULL
                    ORDER BY a.completed_at DESC, a.rowid DESC LIMIT 1
                """, (visitor,)).fetchone()
                test = TESTS.get(participant["test_id"]) if participant else None
                if test:
                    entries = leaderboard(db, participant["code"])
                    board = self.render_board(entries, participant["id"], participant["show_on_board"], test.results,
                                              caption="最近参加的测试码 · ")
                    html = re.sub(r"<aside class=\"topic-box topic-board\".*?</aside>", lambda _: board, html, count=1, flags=re.S)
        self.respond(html.encode())

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
            self.create_code(field("label").strip(), field("test_id") or TEST_ID)
        elif path == "/admin/revoke":
            with closing(connect()) as db, db:
                db.execute("UPDATE codes SET revoked_at = ? WHERE code = ? AND revoked_at IS NULL", (int(time.time()), field("code")))
            self.redirect("/admin")
        elif path == "/code/start":
            self.start_test(normalize_code(field("code")), normalize_nickname(field("nickname")), field("rank") == "yes")
        elif path == "/code/submit":
            self.complete_test(field("attempt"), form)
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

    def create_code(self, label, test_id):
        if test_id not in TESTS:
            return self.page("无法生成测试码", '<p>请选择有效的测试版本。<a href="/admin">返回发码后台</a></p>', HTTPStatus.BAD_REQUEST)
        if len(label) > 80:
            return self.page("备注最多 80 个字符", '<p><a href="/admin">返回发码后台</a></p>', HTTPStatus.BAD_REQUEST)
        with closing(connect()) as db, db:
            db.execute("INSERT INTO codes (code, test_id, label, created_at) VALUES (?, ?, ?, ?)",
                       (issue_code(), test_id, label, int(time.time())))
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
            test = TESTS.get(row["test_id"])
            title = test.title if test else "未知测试版本"
            note = f'<p>备注 · {escape(row["label"])}</p>' if row["label"] else ""
            items.append(f"""<li class="sheet"><strong><code>{code}</code></strong>
<p>{escape(title)} · {status}</p>{note}
<p>到期时间 {deadline} · 完成 {row["completions"]} 次</p>{action}</li>""")
        entries = "".join(items) or "<li>还没有生成测试码。</li>"
        options = []
        for test_id, test in TESTS.items():
            selected = " selected" if test_id == FULL_TEST_ID else ""
            options.append(f'<option value="{test_id}"{selected}>{escape(test.title)}（{test.duration}）</option>')
        self.page("测试码管理", f"""<form method="post" action="/admin/codes" class="sheet">
<label>测试版本 <select name="test_id" required>{''.join(options)}</select></label>
<p>首次使用起 30 天内有效，可多人重复使用。</p>
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
            row = db.execute("SELECT * FROM codes WHERE code = ?", (code,)).fetchone()
            error = active_error(row, now)
            if error:
                return self.code_page(error[1], error[0], code, nickname, ranked)
            test = TESTS.get(row["test_id"])
            if test is None:
                return self.code_page("这个测试版本目前不可用。", HTTPStatus.GONE, code, nickname, ranked)
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
        self.test_page(attempt, cookie, test)

    def test_page(self, attempt, cookie, test):
        fields = []
        sections = {0: "日常习惯", 4: "朋友相处", 8: "忙完怎么放松"} if test is TESTS[FULL_TEST_ID] else {}
        for index, (prompt, options) in enumerate(test.questions):
            if index in sections:
                fields.append(f'<h2 class="quiz-section">{sections[index]}</h2>')
            choices = []
            for offset in range(len(options)):
                value = (offset + index) % len(options) if sections else offset
                choices.append(f'<label class="quiz-option"><input type="radio" name="q{index}" value="{value}" required> {escape(options[value])}</label>')
            fields.append(f"<fieldset><legend>{index + 1}. {escape(prompt)}</legend>{''.join(choices)}</fieldset>")
        self.page(test.title, f"""<p>{test.duration}。每题选择最接近你的一项。</p>
<form method="post" action="/code/submit" class="sheet">
<input type="hidden" name="attempt" value="{escape(attempt)}">{''.join(fields)}
<button class="primary">查看结果</button></form>""", headers=(cookie,))

    def complete_test(self, token, form):
        now = int(time.time())
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT a.*, c.test_id, c.expires_at, c.revoked_at, p.browser_token, p.show_on_board FROM attempts a
                JOIN codes c ON a.code = c.code LEFT JOIN participants p ON p.id = a.participant_id
                WHERE a.token = ?""", (token,)).fetchone()
            error = active_error(row, now)
            if error is None:
                test = TESTS.get(row["test_id"])
                if test is None:
                    error = HTTPStatus.GONE, "这个测试版本目前不可用。"
                elif row["participant_id"] is not None and row["browser_token"] != self.visitor_token():
                    error = HTTPStatus.FORBIDDEN, "请回到开始测试的浏览器，或重新输入测试码。"
                elif row["completed_at"] is not None:
                    result = row["result_index"]
                elif now - row["started_at"] >= ATTEMPT_DURATION:
                    error = HTTPStatus.GONE, "这次答题已超时，请重新输入测试码。"
                else:
                    answers = [form.get(f"q{index}", []) for index in range(len(test.questions))]
                    valid = all(len(picks) == 1 and picks[0] in {str(value) for value in range(len(options))}
                                for picks, (_, options) in zip(answers, test.questions))
                    if valid:
                        # In a tie, prefer the response to the latest question among the tied types.
                        ordered = reversed(answers) if row["test_id"] == FULL_TEST_ID else answers
                        result = Counter(int(picks[0]) for picks in ordered).most_common(1)[0][0]
                        db.execute("UPDATE attempts SET completed_at = ?, result_index = ? WHERE token = ?",
                                   (time.time_ns(), result, token))
                    else:
                        error = HTTPStatus.BAD_REQUEST, "请完成所有题目后再提交。"
            entries = leaderboard(db, row["code"]) if error is None else []
        if error:
            return self.code_page(error[1], error[0])
        title, description = test.results[result]
        board = self.render_board(entries, row["participant_id"], row["show_on_board"], test.results)
        self.page(f"你像一台{title}", f"""<div class="topic-grid result-grid">
<section class="topic-box"><h2>你的测试结果</h2><p>{escape(description)}</p>
<div class="topic-actions"><a class="primary" href="/code">再测一次</a>
<a class="text-link" href="/code/topic">返回测试专题</a></div></section>{board}</div>""", wide=True)

    def render_board(self, entries, participant, visible, results, caption=""):
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
            title = escape(results[entry["result_index"]][0])
            listing.append(f'<li class="board-row"><span>{rank}</span><div><strong>{name}</strong><small>最近结果 · {title}</small></div><span>{entry["finishes"]} 次</span></li>')
        detail = "<p>还没有人选择上榜。</p>"
        if listing:
            detail = f'<ol class="board-list">{"".join(listing)}</ol>'
        private = "<p>你这次选择不在榜上展示。</p>" if participant and not visible else ""
        return f"""<section class="topic-box topic-board" aria-labelledby="board-title"><h2 id="board-title">同码排行榜</h2>
<p>{escape(caption)}按完成次数排列，次数相同并列，最多展示 25 人。</p>{private}{detail}</section>"""


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
