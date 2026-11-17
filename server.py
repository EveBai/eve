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
FRIEND_TEST_ID = "friend-role-v1"
SITE_CODE = "site-once"
FRIEND_QUESTIONS = (
    ('群里有人说「周末出来玩」，你更可能？', ('先抛一个有意思的话题，把大家喊出来', '问问最近很忙的朋友有没有空', '发个投票，把时间地点确定下来', '提议大家带一件家里最离谱的东西')),
    ('聚会刚开始，大家有点拘谨。你会？', ('讲个好笑的近况，让大家接着聊', '找一个落单的朋友聊几句', '拿出准备好的小游戏', '顺手给桌上的零食起一堆奇怪名字')),
    ('原本订的店临时不开门，你会？', ('笑着提议大家先玩个猜谜', '先确认大家饿不饿、累不累', '开始看附近还有哪些地方能去', '把等位变成一场拍照挑战')),
    ('拍合照的时候，你最常做什么？', ('倒数三秒，负责喊大家笑', '确认每个人都进了镜头', '找光线、支手机，把照片拍好', '带头比一个奇怪的姿势')),
    ('聚会散场后，你更可能发什么？', ('今晚最好笑的那一幕', '一句「到家了吗」', '拍好的照片和下次见面的时间', '一张只有现场的人才看得懂的图')),
)
FRIEND_RESULTS = (
    ('气氛点火员', '你常常用一句话把大家带进状态。你的热情让朋友更容易放开玩。'),
    ('贴心观察员', '你很容易留意到谁刚刚没接上话。朋友和你在一起，安静也不会尴尬。'),
    ('路线规划员', '你擅长把「改天一起玩」变成一场真的聚会。朋友可以放心把下一步交给你。'),
    ('意外惊喜担当', '你总能带来一点计划外的乐趣。朋友想起这场聚会时，也许会先想起你的奇怪点子。'),
)
TESTS = {
    TEST_ID: Test(f"{TEST_NAME} · 速测版", "3 题 · 约 1 分钟", QUESTIONS, RESULTS),
    FRIEND_TEST_ID: Test("你在朋友局里的隐藏角色", "5 题 · 约 2 分钟", FRIEND_QUESTIONS, FRIEND_RESULTS),
    FULL_TEST_ID: Test(f"{TEST_NAME} · 完整版", "12 题 · 约 5 分钟", FULL_QUESTIONS, FULL_RESULTS),
}
ASSETS = {
    "/style.css": "text/css; charset=utf-8",
    "/quiz.js": "text/javascript; charset=utf-8",
    "/homepage-plush-concept.png": "image/png",
    "/appliance-results.jpg": "image/jpeg",
    "/share.js": "text/javascript; charset=utf-8",
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
CREATE TABLE IF NOT EXISTS code_batches (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    public_claim INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS one_use_codes (
    code TEXT PRIMARY KEY REFERENCES codes(code),
    batch_id TEXT NOT NULL REFERENCES code_batches(id),
    claimed_by TEXT,
    used_at INTEGER,
    UNIQUE(batch_id, claimed_by)
);
CREATE TABLE IF NOT EXISTS result_shares (
    slug TEXT PRIMARY KEY,
    attempt_token TEXT NOT NULL UNIQUE REFERENCES attempts(token)
);
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
    if "chosen_test" not in columns:
        db.execute("ALTER TABLE attempts ADD COLUMN chosen_test TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS attempts_by_participant ON attempts(participant_id, completed_at)")
    db.execute("CREATE INDEX IF NOT EXISTS attempts_by_test ON attempts(chosen_test, completed_at)")


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


def test_leaderboard(db, test_id):
    return db.execute("""
        SELECT p.id, p.nickname, a.result_index,
               ROW_NUMBER() OVER (ORDER BY a.completed_at, a.rowid) AS position
        FROM attempts a JOIN participants p ON p.id = a.participant_id
        WHERE a.chosen_test = ? AND a.completed_at IS NOT NULL AND p.show_on_board = 1
        ORDER BY a.completed_at DESC, a.rowid DESC LIMIT 25
    """, (test_id,)).fetchall()


def result_distribution(db, test_id):
    rows = db.execute("""
        WITH completions AS (
            SELECT a.result_index, ROW_NUMBER() OVER (
                PARTITION BY COALESCE(p.browser_token, a.token)
                ORDER BY a.completed_at DESC, a.rowid DESC
            ) AS latest
            FROM attempts a JOIN codes c ON c.code = a.code
            LEFT JOIN participants p ON p.id = a.participant_id
            WHERE COALESCE(a.chosen_test, c.test_id) = ? AND a.completed_at IS NOT NULL
        )
        SELECT result_index, COUNT(*) AS total FROM completions WHERE latest = 1 GROUP BY result_index
    """, (test_id,)).fetchall()
    counts = dict.fromkeys(range(len(TESTS[test_id].results)), 0)
    for row in rows:
        if row["result_index"] in counts:
            counts[row["result_index"]] = row["total"]
    return counts


def percent(count, total):
    value = count * 100 / total
    if count and value < 0.1:
        return "<0.1%"
    if count < total and value > 99.9:
        return ">99.9%"
    return f"{value:.1f}".removesuffix(".0") + "%"


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

    def page(self, title, content, status=HTTPStatus.OK, headers=(), wide=False, preview=None):
        layout = "workflow workflow-wide" if wide else "workflow"
        meta = ""
        if preview:
            description, image = preview
            base = f"{'https' if self.server.cloud else 'http'}://{self.headers.get('Host', '')}"
            meta = f'''<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:image" content="{escape(base + image)}"><script defer src="/share.js"></script>'''
        markup = f"""<!doctype html><html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · 开心测试局</title><link rel="stylesheet" href="/style.css">{meta}</head>
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
        url = urlsplit(self.path)
        path = url.path
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
            selected = parse_qs(url.query).get("test", [FULL_TEST_ID])[0]
            self.code_page(selected=selected)
        elif path.startswith("/code/claim/"):
            self.claim_page(path.removeprefix("/code/claim/"))
        elif path.startswith("/share/"):
            self.share_page(path.removeprefix("/share/"))
        elif path == "/healthz":
            self.respond(b"ok\n", content_type="text/plain; charset=utf-8")
        else:
            self.page("找不到页面", '<p><a href="/">返回首页</a></p>', HTTPStatus.NOT_FOUND)

    def appliance_topic(self):
        html = (ROOT / "appliance.html").read_text().replace("<head>", '<head><base href="/">', 1)
        visitor = self.visitor_token()
        with closing(connect()) as db:
            participant = None
            if visitor:
                participant = db.execute("""
                    SELECT COALESCE(a.chosen_test, c.test_id) AS test_id, a.result_index
                    FROM participants p JOIN codes c ON c.code = p.code
                    JOIN attempts a ON a.participant_id = p.id
                    WHERE p.browser_token = ? AND a.completed_at IS NOT NULL
                      AND COALESCE(a.chosen_test, c.test_id) IN (?, ?)
                    ORDER BY a.completed_at DESC, a.rowid DESC LIMIT 1
                """, (visitor, TEST_ID, FULL_TEST_ID)).fetchone()
            test_id = participant["test_id"] if participant else FULL_TEST_ID
            counts = result_distribution(db, test_id)
        graph = self.render_distribution(TESTS[test_id], counts, participant["result_index"] if participant else None)
        html = re.sub(r"<aside class=\"topic-box topic-board\".*?</aside>", lambda _: graph, html, count=1, flags=re.S)
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
            self.create_batch(field("label").strip(), field("quantity"), field("public_claim") == "yes")
        elif path == "/admin/revoke":
            with closing(connect()) as db, db:
                db.execute("UPDATE codes SET revoked_at = ? WHERE code = ? AND revoked_at IS NULL", (int(time.time()), field("code")))
            self.redirect("/admin")
        elif path == "/code/start":
            self.start_test(normalize_code(field("code")), normalize_nickname(field("nickname")),
                            field("rank") == "yes", field("selected_test"))
        elif path == "/code/submit":
            self.complete_test(field("attempt"), form)
        elif path == "/code/share":
            self.create_share(field("attempt"))
        elif path.startswith("/code/claim/"):
            self.claim_code(path.removeprefix("/code/claim/"))
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

    def create_batch(self, label, quantity, public_claim):
        count = int(quantity) if re.fullmatch(r"[0-9]{1,3}", quantity) else 0
        if count != 1 and not 50 <= count <= 100:
            return self.page("请选择生成 1 个或 50–100 个码", '<p><a href="/admin">返回发码后台</a></p>', HTTPStatus.BAD_REQUEST)
        if len(label) > 80:
            return self.page("备注最多 80 个字符", '<p><a href="/admin">返回发码后台</a></p>', HTTPStatus.BAD_REQUEST)
        batch = secrets.token_urlsafe(16)
        now = int(time.time())
        codes = [issue_code() for _ in range(count)]
        with closing(connect()) as db, db:
            db.execute("INSERT INTO code_batches VALUES (?, ?, ?)", (batch, label, public_claim))
            db.executemany("INSERT INTO codes (code, test_id, label, created_at) VALUES (?, ?, ?, ?)",
                           ((code, SITE_CODE, label, now) for code in codes))
            db.executemany("INSERT INTO one_use_codes (code, batch_id) VALUES (?, ?)", ((code, batch) for code in codes))
        self.redirect("/admin")

    def claim_page(self, batch):
        visitor = self.visitor_token()
        with closing(connect()) as db:
            exists = db.execute("SELECT 1 FROM code_batches WHERE id = ? AND public_claim = 1", (batch,)).fetchone()
            if not exists:
                return self.page("找不到领取页面", '<p><a href="/">返回首页</a></p>', HTTPStatus.NOT_FOUND)
            claimed = db.execute("""SELECT c.*, u.used_at FROM one_use_codes u JOIN codes c ON c.code = u.code
                WHERE u.batch_id = ? AND u.claimed_by = ?""",
                                 (batch, visitor)).fetchone() if visitor else None
        if claimed:
            if claimed["used_at"] is not None:
                return self.page("你已经用过本批测试码", '<p><a href="/#discover">浏览更多测试</a></p>')
            error = active_error(claimed, int(time.time()))
            if error:
                return self.page(error[1], '<p><a href="/#discover">浏览更多测试</a></p>', error[0])
            return self.code_page("这是你领取的全站通用码，选一个测试开始。", code=claimed["code"])
        cookie = self.cookie("quiz_visitor", visitor or secrets.token_urlsafe(32), "/code", 7776000)
        self.page("领取一次性测试码", f"""<section class="sheet"><p>每个浏览器在本批可以领取一个码，任选一个已上线的测试，交卷后即用完。</p>
<form method="post" action="/code/claim/{escape(batch)}"><button class="primary">领取测试码</button></form></section>""", headers=(cookie,))

    def claim_code(self, batch):
        visitor = self.visitor_token() or secrets.token_urlsafe(32)
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM code_batches WHERE id = ? AND public_claim = 1", (batch,)).fetchone():
                return self.page("找不到领取页面", "", HTTPStatus.NOT_FOUND)
            existing = db.execute("SELECT 1 FROM one_use_codes WHERE batch_id = ? AND claimed_by = ?", (batch, visitor)).fetchone()
            if not existing:
                available = db.execute("""SELECT u.code FROM one_use_codes u JOIN codes c ON u.code = c.code
                    WHERE u.batch_id = ? AND u.claimed_by IS NULL AND u.used_at IS NULL AND c.revoked_at IS NULL
                      AND (c.expires_at IS NULL OR c.expires_at > ?) ORDER BY u.rowid LIMIT 1""", (batch, int(time.time()))).fetchone()
                if not available:
                    return self.page("本批测试码已领完", '<p><a href="/#discover">看看其他测试</a></p>', HTTPStatus.GONE)
                db.execute("UPDATE one_use_codes SET claimed_by = ? WHERE code = ?", (visitor, available["code"]))
        self.redirect(f"/code/claim/{batch}", (self.cookie("quiz_visitor", visitor, "/code", 7776000),))

    def admin_page(self):
        with closing(connect()) as db:
            rows = db.execute("""
                SELECT c.*, u.claimed_by, u.used_at, (SELECT count(*) FROM attempts a
                    WHERE a.code = c.code AND a.completed_at IS NOT NULL) AS completions
                FROM codes c LEFT JOIN one_use_codes u ON u.code = c.code ORDER BY c.rowid DESC LIMIT 200
            """).fetchall()
            batches = db.execute("""SELECT b.*, count(*) AS total, count(u.claimed_by) AS claimed, count(u.used_at) AS used
                FROM code_batches b JOIN one_use_codes u ON u.batch_id = b.id
                GROUP BY b.id ORDER BY b.rowid DESC LIMIT 30""").fetchall()
        now = int(time.time())
        items = []
        for row in rows:
            code = escape(row["code"])
            status = ("已用完" if row["used_at"] is not None else
                      "已停用" if row["revoked_at"] is not None else
                      "已领取" if row["expires_at"] is None and row["claimed_by"] else
                      "未激活" if row["expires_at"] is None else
                      "已过期" if row["expires_at"] <= now else "可使用")
            action = ""
            if status in {"未激活", "已领取", "可使用"}:
                action = f"""<form method="post" action="/admin/revoke">
<input type="hidden" name="code" value="{code}"><button class="back">停用</button></form>"""
            deadline = timestamp(row["expires_at"]) if row["expires_at"] is not None else "首次使用后开始计时"
            test = TESTS.get(row["test_id"])
            title = "全站通用 · 仅可使用一次" if row["test_id"] == SITE_CODE else test.title if test else "未知测试版本"
            note = f'<p>备注 · {escape(row["label"])}</p>' if row["label"] else ""
            items.append(f"""<li class="sheet"><strong><code>{code}</code></strong>
<p>{escape(title)} · {status}</p>{note}
<p>到期时间 {deadline} · 完成 {row["completions"]} 次</p>{action}</li>""")
        entries = "".join(items) or "<li>还没有生成测试码。</li>"
        summaries = []
        for batch in batches:
            link = f'<a class="text-link" href="/code/claim/{batch["id"]}">打开领取页并复制链接</a>' if batch["public_claim"] else ""
            summaries.append(f'<li class="sheet"><strong>{escape(batch["label"] or "全站测试码")}</strong><p>共 {batch["total"]} 个 · 已领 {batch["claimed"]} · 已用 {batch["used"]}</p>{link}</li>')
        self.page("测试码管理", f"""<form method="post" action="/admin/codes" class="sheet">
<p>新码适用于任意已上线的测试，成功交卷一次后即失效。</p>
<label>生成数量 <input name="quantity" type="number" inputmode="numeric" min="1" max="100" value="50" required></label>
<p class="form-hint">每批 50–100 个，也可单独生成 1 个。</p>
<label>发放备注 <input type="text" name="label" maxlength="80" placeholder="例如 周五朋友局"></label>
<label class="rank-choice"><input type="checkbox" name="public_claim" value="yes" checked>生成访客自助领取链接</label>
<button class="primary">生成测试码</button></form>
<h2>最近生成的批次</h2><ul class="code-list">{''.join(summaries) or '<li>还没有生成批次。</li>'}</ul>
<h2>最近 200 个测试码</h2><ul class="code-list">{entries}</ul>
<form method="post" action="/admin/logout"><button class="back">退出后台</button></form>""")

    def code_page(self, message="", status=HTTPStatus.OK, code="", nickname="", ranked=False, selected=FULL_TEST_ID):
        checked = " checked" if ranked else ""
        options = "".join(f'<option value="{key}"{" selected" if key == selected else ""}>{escape(test.title)}</option>'
                          for key, test in TESTS.items())
        self.page("输入测试码", f"""<p role="status">{escape(message)}</p>
<form method="post" action="/code/start" class="sheet">
<label>测试码 <input name="code" value="{escape(code)}" autocomplete="off" spellcheck="false" required maxlength="40"></label>
<label>选择测试 <select name="selected_test">{options}</select></label>
<p class="form-hint">全站通用码按这里的选择开始。早先发放的专用码会打开它绑定的测试。</p>
<label>昵称 <input name="nickname" value="{escape(nickname)}" autocomplete="nickname" required maxlength="20"></label>
<p class="form-hint">1–20 个字符。同一浏览器重测时，请继续使用原昵称。</p>
<label class="rank-choice"><input type="checkbox" name="rank" value="yes"{checked}>
在排行榜显示我的昵称和结果</label>
<button class="primary">解锁并开始</button></form>""", status)

    def start_test(self, code, nickname, ranked, selected):
        if not 1 <= len(nickname) <= 20 or any(unicodedata.category(char) == "Cc" for char in nickname):
            return self.code_page("请输入 1–20 个字符的昵称。", HTTPStatus.BAD_REQUEST, code, nickname, ranked)
        now = int(time.time())
        attempt = secrets.token_urlsafe(32)
        visitor = self.visitor_token() or secrets.token_urlsafe(32)
        nickname_key = nickname.casefold()
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT c.*, u.claimed_by, u.used_at FROM codes c LEFT JOIN one_use_codes u ON u.code = c.code WHERE c.code = ?", (code,)).fetchone()
            error = active_error(row, now)
            if error:
                return self.code_page(error[1], error[0], code, nickname, ranked)
            site = row["test_id"] == SITE_CODE
            if site and row["used_at"] is not None:
                return self.code_page("这个测试码已经使用过了。", HTTPStatus.GONE, nickname=nickname, selected=selected)
            if site and row["claimed_by"] and row["claimed_by"] != visitor:
                return self.code_page("这个码已在其他浏览器领取。", HTTPStatus.FORBIDDEN, nickname=nickname, selected=selected)
            test = TESTS.get(selected if site else row["test_id"])
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
            db.execute("INSERT INTO attempts (token, code, started_at, participant_id, chosen_test) VALUES (?, ?, ?, ?, ?)",
                       (attempt, code, now, participant, selected if site else None))
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
            row = db.execute("""SELECT a.*, COALESCE(a.chosen_test, c.test_id) AS test_id, c.expires_at, c.revoked_at,
                p.browser_token, p.show_on_board, u.claimed_by, u.used_at FROM attempts a
                JOIN codes c ON a.code = c.code LEFT JOIN participants p ON p.id = a.participant_id
                LEFT JOIN one_use_codes u ON u.code = a.code
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
                elif row["used_at"] is not None:
                    error = HTTPStatus.GONE, "这个测试码已经使用过了。"
                elif row["claimed_by"] and row["claimed_by"] != self.visitor_token():
                    error = HTTPStatus.FORBIDDEN, "这个码已在其他浏览器领取。"
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
                        if row["chosen_test"]:
                            db.execute("UPDATE one_use_codes SET used_at = ? WHERE code = ?", (now, row["code"]))
                    else:
                        error = HTTPStatus.BAD_REQUEST, "请完成所有题目后再提交。"
            site = row is not None and row["chosen_test"] is not None
            entries = []
            if error is None:
                entries = test_leaderboard(db, row["test_id"]) if site else leaderboard(db, row["code"])
                distribution = result_distribution(db, row["test_id"])
        if error:
            return self.code_page(error[1], error[0])
        title, description = test.results[result]
        board = self.render_board(entries, row, test, site=site)
        graph = self.render_distribution(test, distribution, result)
        heading = f"你是{title}" if test is TESTS[FRIEND_TEST_ID] else f"你像一台{title}"
        topic = "/friend-role.html" if test is TESTS[FRIEND_TEST_ID] else "/code/topic"
        share = f'<form method="post" action="/code/share"><input type="hidden" name="attempt" value="{escape(token)}"><button class="primary">生成分享页</button></form>' if row["participant_id"] else ""
        notice = "这次测试已完成，一次性测试码已用完。" if site else ""
        card = self.result_card(test, result, description, share, topic, notice, self.rarity(distribution, result))
        participants = f'<details class="participant-details"><summary>查看参与者榜单</summary>{board}</details>'
        self.page(heading, f'<div class="topic-grid result-grid">{card}<div>{graph}{participants}</div></div>', wide=True)

    def result_card(self, test, result, description, action, topic, notice="", rarity=""):
        illustration = self.result_image(test, result)
        note = f'<p class="result-note">{escape(notice)}</p>' if notice else ""
        return f"""<section class="result-card">{illustration}<div class="result-copy">
<h2>{escape(test.title)}</h2>{rarity}<p class="result-description">{escape(description)}</p>{note}
<div class="topic-actions">{action}<a class="text-link" href="{topic}">返回测试专题</a></div></div></section>"""

    def rarity(self, counts, result):
        total = sum(counts.values())
        if not total:
            return ""
        share = escape(percent(counts[result], total))
        return f'<p class="rarity"><strong>{share}</strong><span>的已测访客和你结果相同<small>{counts[result]} / {total} 份结果</small></span></p>'

    def render_distribution(self, test, counts, result):
        total = sum(counts.values())
        if not total:
            return '<section class="topic-box topic-board"><h2>结果分布</h2><p>有交卷记录后就会显示占比。</p></section>'
        ordered = sorted(counts, key=lambda key: -counts[key])
        items = []
        previous_count = None
        rank = 0
        for position, index in enumerate(ordered, 1):
            count = counts[index]
            if count != previous_count:
                rank = position
                previous_count = count
            name = escape(test.results[index][0])
            label = f"第 {rank} 名" if count else "暂无"
            highlight = ' class="is-yours"' if index == result else ""
            yours = ' <small class="board-you">你的结果</small>' if index == result else ""
            items.append(f'''<li{highlight}>
<div class="distribution-label">{self.result_image(test, index, icon=True)}<div><small>{label}</small><strong>{name}{yours}</strong></div>
<div class="distribution-value"><strong>{escape(percent(count, total))}</strong><small>{count} 份</small></div></div>
<meter min="0" max="{total}" value="{count}" aria-label="{name}的占比"></meter></li>''')
        note = "样本较少，占比会随新结果变化。" if total < 20 else ""
        version = "完整版" if test is TESTS[FULL_TEST_ID] else "速测版" if test is TESTS[TEST_ID] else "朋友局"
        return f'''<section class="topic-box topic-board distribution" aria-labelledby="distribution-title">
<h2 id="distribution-title">结果分布</h2><p>{version} · {total} 份结果 · 每个浏览器取最近一次。{note}</p>
<ol>{''.join(items)}</ol></section>'''

    def result_image(self, test, result, icon=False):
        style = "role-art result-role" if test is TESTS[FRIEND_TEST_ID] else f"appliance-picture appliance-{result}"
        kind = "rank-icon" if icon else "result-image"
        return f'<span class="{kind} {style}" aria-hidden="true"></span>'

    def create_share(self, token):
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT 1 FROM attempts a JOIN participants p ON p.id = a.participant_id
                WHERE a.token = ? AND a.completed_at IS NOT NULL AND p.browser_token = ?""", (token, self.visitor_token())).fetchone()
            if not row:
                return self.page("找不到可分享的结果", '<p><a href="/code">输入测试码</a></p>', HTTPStatus.NOT_FOUND)
            db.execute("INSERT OR IGNORE INTO result_shares VALUES (?, ?)", (secrets.token_urlsafe(18), token))
            slug = db.execute("SELECT slug FROM result_shares WHERE attempt_token = ?", (token,)).fetchone()["slug"]
        self.redirect(f"/share/{slug}")

    def share_page(self, slug):
        friend_roles = {"friend-spark": 0, "friend-anchor": 1, "friend-guide": 2, "friend-wildcard": 3}
        if slug in friend_roles:
            test, result = TESTS[FRIEND_TEST_ID], friend_roles[slug]
        else:
            with closing(connect()) as db:
                row = db.execute("""SELECT COALESCE(a.chosen_test, c.test_id) AS test_id, a.result_index
                    FROM result_shares s JOIN attempts a ON a.token = s.attempt_token JOIN codes c ON c.code = a.code
                    WHERE s.slug = ? AND a.completed_at IS NOT NULL""", (slug,)).fetchone()
            test = TESTS.get(row["test_id"]) if row else None
            if not test:
                return self.page("找不到这个分享结果", '<p><a href="/">返回首页</a></p>', HTTPStatus.NOT_FOUND)
            result = row["result_index"]
        title, description = test.results[result]
        friend = test is TESTS[FRIEND_TEST_ID]
        heading = f"我是{title}" if friend else f"我像一台{title}"
        topic = "/friend-role.html" if friend else "/code/topic"
        action = '<button class="primary" type="button" id="copy-share">复制分享链接</button><span id="share-status" role="status"></span>'
        card = self.result_card(test, result, description, action, topic)
        image = "/homepage-plush-concept.png" if friend else "/appliance-results.jpg"
        self.page(heading, card, preview=(description, image))

    def render_board(self, entries, participant, test, caption="", site=False):
        listing = []
        rank = 0
        previous = None
        for position, entry in enumerate(entries, 1):
            if site:
                rank = entry["position"]
            elif entry["finishes"] != previous:
                rank = position
                previous = entry["finishes"]
            name = escape(entry["nickname"])
            if entry["id"] == participant["participant_id"]:
                name += ' <small class="board-you">你</small>'
            title = escape(test.results[entry["result_index"]][0])
            icon = self.result_image(test, entry["result_index"], icon=True)
            count = "" if site else f'<span>{entry["finishes"]} 次</span>'
            listing.append(f'<li class="board-row"><span>{rank}</span><div class="board-profile">{icon}<div><strong>{name}</strong><small>{title}</small></div></div>{count}</li>')
        detail = "<p>还没有人选择上榜。</p>"
        if listing:
            detail = f'<ol class="board-list">{"".join(listing)}</ol>'
        private = "<p>你这次选择不在榜上展示。</p>" if participant["participant_id"] and not participant["show_on_board"] else ""
        title = "测试排行榜" if site else "同码排行榜"
        order = "展示最近 25 条公开结果，数字是上榜顺序。" if site else "按完成次数排列，次数相同并列，最多展示 25 人。"
        return f"""<section class="topic-box topic-board" aria-labelledby="board-title"><h2 id="board-title">{title}</h2>
<p>{escape(caption)}{order}</p>{private}{detail}</section>"""


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
