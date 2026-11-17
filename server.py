"""Local preview of the test-code workflow. Run with python3 server.py."""
import os
import re
import secrets
import sqlite3
import time
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from html import escape
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
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
    **dict.fromkeys(("/observation.html", "/chat-match.html"), "text/html; charset=utf-8"),
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
<nav aria-label="主导航"><a href="/#discover">更多测试</a></nav></header>
<main class="wrap {layout}"><h1>{escape(title)}</h1>{content}</main></body></html>"""
        self.respond(markup.encode(), status, headers=headers)

    def redirect(self, location, headers=()):
        self.respond(b"", HTTPStatus.SEE_OTHER, headers=(("Location", location), *headers))

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
            home = (ROOT / "index.html").read_text().replace(
                '<button type="button" id="history">我的记录</button>',
                '<a href="/code/history">我的记录</a>',
            )
            self.respond(home.encode())
        elif path == "/friend-role.html":
            html = (ROOT / "friend-role.html").read_text().replace(
                '<button class="primary" type="button" id="start">开始免费测试</button>',
                self.start_button(FRIEND_TEST_ID, "开始免费测试"),
            )
            self.respond(html.encode())
        elif path == "/appliance.html":
            self.redirect("/code/topic")
        elif path == "/code/topic":
            self.appliance_topic()
        elif path == "/code/history":
            self.history_page()
        elif path in ASSETS:
            self.respond((ROOT / path[1:]).read_bytes(), content_type=ASSETS[path])
        elif path in {"/admin", "/code"} or path.startswith("/code/claim/"):
            self.redirect("/#discover")
        elif path.startswith("/share/"):
            self.share_page(path.removeprefix("/share/"))
        elif path == "/healthz":
            self.respond(b"ok\n", content_type="text/plain; charset=utf-8")
        else:
            self.page("找不到页面", '<p><a href="/">返回首页</a></p>', HTTPStatus.NOT_FOUND)

    def history_page(self):
        with closing(connect()) as db:
            rows = db.execute("""SELECT COALESCE(a.chosen_test, c.test_id) AS test_id, a.result_index
                FROM attempts a JOIN codes c ON c.code = a.code JOIN participants p ON p.id = a.participant_id
                WHERE p.browser_token = ? AND a.completed_at IS NOT NULL
                ORDER BY a.completed_at DESC, a.rowid DESC LIMIT 20""", (self.visitor_token(),)).fetchall()
        items = []
        for row in rows:
            test = TESTS.get(row["test_id"])
            if test is not None:
                title = test.results[row["result_index"]][0]
                items.append(f'<li class="topic-box"><strong>{escape(title)}</strong><p>{escape(test.title)}</p></li>')
        listing = f'<ul class="code-list">{"".join(items)}</ul>' if items else '<p>完成测试后，这里会显示当前浏览器的结果。</p>'
        self.page("我的测试记录", f'{listing}<p><a class="primary" href="/#discover">看看更多测试</a></p>')

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

        if path == "/code/start":
            self.start_test(field("selected_test"))
        elif path == "/code/submit":
            self.complete_test(field("attempt"), form)
        elif path == "/code/share":
            self.create_share(field("attempt"))
        else:
            self.page("找不到页面", '<p><a href="/#discover">浏览免费测试</a></p>', HTTPStatus.NOT_FOUND)

    def start_button(self, test_id, label):
        return f'''<form method="post" action="/code/start" class="start-form">
<input type="hidden" name="selected_test" value="{test_id}"><button class="primary">{escape(label)}</button></form>'''

    def start_test(self, test_id):
        test = TESTS.get(test_id)
        if test is None:
            return self.page("请选择测试", '<p><a href="/#discover">浏览免费测试</a></p>', HTTPStatus.BAD_REQUEST)
        now = int(time.time())
        attempt = secrets.token_urlsafe(32)
        visitor = self.visitor_token() or secrets.token_urlsafe(32)
        # A fixed storage key keeps historical records and foreign-key links intact.
        storage_key = f"free:{test_id}"
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO codes (code, test_id, label, created_at) VALUES (?, ?, ?, ?)",
                       (storage_key, test_id, "", now))
            db.execute("""INSERT OR IGNORE INTO participants (code, nickname, nickname_key, browser_token, show_on_board)
                VALUES (?, ?, ?, ?, 0)""", (storage_key, "", visitor, visitor))
            participant = db.execute("SELECT id FROM participants WHERE code = ? AND browser_token = ?",
                                     (storage_key, visitor)).fetchone()["id"]
            db.execute("INSERT INTO attempts (token, code, started_at, participant_id) VALUES (?, ?, ?, ?)",
                       (attempt, storage_key, now, participant))
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
            row = db.execute("""SELECT a.*, COALESCE(a.chosen_test, c.test_id) AS test_id, p.browser_token FROM attempts a
                JOIN codes c ON a.code = c.code LEFT JOIN participants p ON p.id = a.participant_id
                WHERE a.token = ? AND p.browser_token = ?""", (token, self.visitor_token())).fetchone()
            test = TESTS.get(row["test_id"]) if row else None
            if not test:
                return self.page("找不到答题记录", '<p><a href="/#discover">重新开始免费测试</a></p>', HTTPStatus.NOT_FOUND)
            result = row["result_index"]
            if row["completed_at"] is None:
                if not row["code"].startswith("free:") or now - row["started_at"] >= ATTEMPT_DURATION:
                    return self.page("请重新开始测试", '<p><a href="/#discover">重新开始免费测试</a></p>', HTTPStatus.GONE)
                answers = [form.get(f"q{index}", []) for index in range(len(test.questions))]
                valid = all(len(picks) == 1 and picks[0] in {str(value) for value in range(len(options))}
                            for picks, (_, options) in zip(answers, test.questions))
                if not valid:
                    return self.page("请完成所有题目后再提交", '<p>返回上一页即可继续答题。</p>', HTTPStatus.BAD_REQUEST)
                ordered = reversed(answers) if row["test_id"] == FULL_TEST_ID else answers
                result = Counter(int(picks[0]) for picks in ordered).most_common(1)[0][0]
                db.execute("UPDATE attempts SET completed_at = ?, result_index = ? WHERE token = ?",
                           (time.time_ns(), result, token))
            distribution = result_distribution(db, row["test_id"])
        _, description = test.results[result]
        title = test.results[result][0]
        heading = f"你是{title}" if test is TESTS[FRIEND_TEST_ID] else f"你像一台{title}"
        topic = "/friend-role.html" if test is TESTS[FRIEND_TEST_ID] else "/code/topic"
        share = f'<form method="post" action="/code/share"><input type="hidden" name="attempt" value="{escape(token)}"><button class="primary">生成分享页</button></form>'
        card = self.result_card(test, result, description, share, topic, self.rarity(distribution, result))
        graph = self.render_distribution(test, distribution, result)
        self.page(heading, f'<div class="topic-grid result-grid">{card}<div>{graph}</div></div>', wide=True)

    def result_card(self, test, result, description, action, topic, rarity=""):
        illustration = self.result_image(test, result)
        return f"""<section class="result-card">{illustration}<div class="result-copy">
<h2>{escape(test.title)}</h2>{rarity}<p class="result-description">{escape(description)}</p>
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
                return self.page("找不到可分享的结果", '<p><a href="/#discover">浏览免费测试</a></p>', HTTPStatus.NOT_FOUND)
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



def main():
    cloud = os.environ.get("QUIZ_CLOUD") == "1"
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
        print(f"Listening on {address}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
