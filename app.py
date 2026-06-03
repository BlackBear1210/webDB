# ════════════════════════════════════════════════════════════════════
#  FitQR v2 - 스마트 짐 운동 트래커  (웹DB 기말 프로젝트)
# --------------------------------------------------------------------
#  컨셉 : 머신 QR 스캔 → 정보/영상 → 센서 자동 카운트(시뮬) → 기록
#         머신 없는 운동은 전신거울 카메라 동작인식(시뮬)으로 카운트
#  화면 : 하단 5탭 (루틴 / 커스텀 / 운동 / 리포트 / 내 정보)
#  스택 : Flask + SQLite + Jinja2 (+ 카운트용 JS)
#  구조 : DB설정 → init_db(11테이블+시드) → 라우트 → 실행
# ════════════════════════════════════════════════════════════════════

from flask import (Flask, request, redirect, render_template,
                   session, url_for, send_file)
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime, timedelta, date
import calendar as pycal
import json
import io
import os
import random
import secrets
import hmac
import time

try:
    import qrcode            # QR 이미지 생성 (없어도 앱은 동작)
    HAS_QR = True
except Exception:
    HAS_QR = False

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'fitqr.db')


def load_secret_key():
    """secret_key를 코드에 하드코딩하지 않는다(세션 쿠키 위조 방지).
    우선순위: 환경변수 SECRET_KEY  >  로컬 .secret_key 파일  >  새로 무작위 생성 후 파일 저장.
    .secret_key 는 .gitignore 로 깃에 올리지 않으므로 키가 코드/저장소에 노출되지 않는다."""
    env = os.environ.get('SECRET_KEY')
    if env:
        return env
    key_path = os.path.join(BASE_DIR, '.secret_key')
    if os.path.exists(key_path):
        with open(key_path) as f:
            saved = f.read().strip()
        if saved:
            return saved
    key = secrets.token_hex(32)              # 64자리 예측 불가능한 무작위 키
    with open(key_path, 'w') as f:
        f.write(key)
    return key


app.secret_key = load_secret_key()

# ── HTTPS 강제 여부 (배포 시 환경변수 FORCE_HTTPS=1) ──
# 로컬 개발(http)에서는 끄고, 배포(HTTPS)에서만 켠다. 켜면 쿠키도 Secure 로.
FORCE_HTTPS = os.environ.get('FORCE_HTTPS') == '1'

# ── 세션 쿠키 보안 플래그 ──
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,       # JS에서 document.cookie 로 세션 읽기 차단(XSS 세션 탈취 방지)
    SESSION_COOKIE_SAMESITE='Lax',      # 타 사이트發 요청에는 쿠키 미전송 → CSRF 1차 완화
    SESSION_COOKIE_SECURE=FORCE_HTTPS,  # HTTPS 배포(FORCE_HTTPS=1)에서만 쿠키를 https로만 전송
)

WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일']
BODY_PARTS = ['가슴', '등', '어깨', '팔', '복근', '엉덩이', '다리', '전신']
GOALS = ['강해지기', '근육량늘리기', '체중감량']
LEVELS = ['초급', '중급', '상급']
REST_SEC = 8                 # 휴식 N초 무동작이면 세트 자동확정 (시뮬)

# ── 로그인 무차별 대입(brute-force) 방어용 (인메모리) ──
LOGIN_MAX_FAILS = 5          # 이만큼 연속 실패하면
LOGIN_WINDOW_SEC = 300       # 최근 5분 안에
LOGIN_LOCK_SEC = 300         # 5분 잠금
_login_fails = {}            # ip -> [실패 timestamp, ...]
# 사용자 존재 여부에 따른 응답 시간 차(타이밍 enumeration)를 없애기 위한 더미 해시
_DUMMY_HASH = generate_password_hash('fitqr_dummy_password')


def login_blocked(ip):
    """최근 window 내 실패가 임계치 이상이면 True(잠금)."""
    now = time.time()
    fails = [t for t in _login_fails.get(ip, []) if now - t < LOGIN_WINDOW_SEC]
    _login_fails[ip] = fails
    return len(fails) >= LOGIN_MAX_FAILS


def record_login_fail(ip):
    _login_fails.setdefault(ip, []).append(time.time())


def clear_login_fails(ip):
    _login_fails.pop(ip, None)


# 배포(FORCE_HTTPS=1) 시 http 접속을 https로 돌려보낸다.
# PythonAnywhere 등 프록시 뒤에서는 원래 프로토콜이 X-Forwarded-Proto 헤더에 담겨온다.
@app.before_request
def enforce_https():
    if FORCE_HTTPS:
        proto = request.headers.get('X-Forwarded-Proto', 'http')
        if proto != 'https' and not request.is_secure:
            return redirect(request.url.replace('http://', 'https://', 1), code=301)


# 로그인 페이지가 브라우저에 캐시되어 계정 전환 후에도 옛 화면이 보이는 것을 방지.
# (계정 바꿨는데 이전 사용자 정보가 보이는 현상 차단)
@app.after_request
def add_no_cache(resp):
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    # 클릭재킹 방지 + MIME 스니핑 방지
    resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    # HTTPS 배포 시 브라우저가 항상 https로 접속하도록 강제(HSTS)
    if FORCE_HTTPS:
        resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return resp


# ════════════════════════════════════════════════════════════════════
#  CSRF 보호 (의존성 없이 직접 구현)
#  - 세션에 무작위 토큰을 두고, 모든 POST 요청에 같은 토큰이 오는지 검증.
#  - 템플릿(base.html)은 {{ csrf_token() }} 으로 토큰을 받아 모든 POST 폼에 자동 주입.
# ════════════════════════════════════════════════════════════════════
def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(16)
    return session['_csrf_token']


@app.context_processor
def inject_csrf():
    return {'csrf_token': generate_csrf_token}     # 템플릿에서 호출 가능


@app.before_request
def csrf_protect():
    if request.method == 'POST':
        sent = request.form.get('_csrf', '')
        real = session.get('_csrf_token', '')
        # 타이밍 공격 방지를 위해 compare_digest 사용
        if not real or not hmac.compare_digest(str(sent), str(real)):
            return ('CSRF 검증 실패: 페이지를 새로고침한 뒤 다시 시도하세요.', 400)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('PRAGMA foreign_keys = ON')
    return conn, cursor


def is_hashed(pw):
    """werkzeug 해시 형식인지 확인(해시는 'pbkdf2:' 또는 'scrypt:' 로 시작)."""
    return bool(pw) and pw.startswith(('pbkdf2:', 'scrypt:'))


def to_float(v, default=0.0):
    """숫자 아닌 값/빈 값이 와도 500 안 나게 안전 변환."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def to_int(v, default=0):
    try:
        return int(float(v))     # '3.0' 같은 입력도 허용
    except (TypeError, ValueError):
        return default


# ════════════════════════════════════════════════════════════════════
#  DB 초기화 (테이블 11개 + 시드)
# ════════════════════════════════════════════════════════════════════
def init_db():
    conn, cursor = get_db()

    # 1. 회원
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        login_id      TEXT UNIQUE,
        password      TEXT,
        name          TEXT,
        gender        TEXT,
        goal          TEXT,
        focus_part    TEXT,
        height        REAL,
        weight        REAL,
        target_weight REAL,
        fitness_level TEXT,
        squat_1rm     REAL DEFAULT 0,
        bench_1rm     REAL DEFAULT 0,
        deadlift_1rm  REAL DEFAULT 0,
        frequency     INTEGER DEFAULT 3,
        start_weekday INTEGER DEFAULT 0,
        created_at    TEXT,
        role          TEXT DEFAULT 'user'
    )''')

    # 2. 운동 종목 (머신/비머신 통합)
    cursor.execute('''CREATE TABLE IF NOT EXISTS exercise (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        name             TEXT,
        body_part        TEXT,
        primary_target   TEXT,
        secondary_target TEXT,
        equipment        TEXT,
        is_machine       INTEGER DEFAULT 1,
        difficulty       TEXT DEFAULT '초급',
        prep             TEXT DEFAULT '',
        execution        TEXT DEFAULT '',
        tips             TEXT DEFAULT '',
        video_url        TEXT DEFAULT ''
    )''')

    # 3. 30일 루틴 헤더
    cursor.execute('''CREATE TABLE IF NOT EXISTS routine (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER,
        created_at   TEXT,
        status       TEXT DEFAULT '진행중',
        reward_given INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # 4. 루틴의 각 날 (1~30)
    cursor.execute('''CREATE TABLE IF NOT EXISTS routine_day (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        routine_id   INTEGER,
        day_no       INTEGER,
        weekday      INTEGER,
        is_rest      INTEGER DEFAULT 0,
        body_part    TEXT DEFAULT '',
        is_unlocked  INTEGER DEFAULT 0,
        is_completed INTEGER DEFAULT 0,
        completed_at TEXT,
        FOREIGN KEY (routine_id) REFERENCES routine(id)
    )''')

    # 5. 그날의 운동 종목
    cursor.execute('''CREATE TABLE IF NOT EXISTS routine_day_item (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        routine_day_id INTEGER,
        exercise_id   INTEGER,
        target_sets   INTEGER DEFAULT 3,
        target_reps   INTEGER DEFAULT 12,
        seq           INTEGER DEFAULT 0,
        FOREIGN KEY (routine_day_id) REFERENCES routine_day(id),
        FOREIGN KEY (exercise_id)    REFERENCES exercise(id)
    )''')

    # 6. 운동 세션 ("운동 종료" 단위)
    cursor.execute('''CREATE TABLE IF NOT EXISTS workout (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id        INTEGER,
        source         TEXT DEFAULT '단독',
        routine_day_id INTEGER,
        custom_id      INTEGER,
        title          TEXT DEFAULT '',
        started_at     TEXT,
        ended_at       TEXT,
        status         TEXT DEFAULT '진행중',
        duration_sec   INTEGER DEFAULT 0,
        total_volume   REAL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # 7. 종목 사용 ("사용 종료" 단위)
    cursor.execute('''CREATE TABLE IF NOT EXISTS machine_use (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        workout_id  INTEGER,
        exercise_id INTEGER,
        weight      REAL DEFAULT 0,
        started_at  TEXT,
        ended_at    TEXT,
        FOREIGN KEY (workout_id)  REFERENCES workout(id),
        FOREIGN KEY (exercise_id) REFERENCES exercise(id)
    )''')

    # 8. 세트별 기록
    cursor.execute('''CREATE TABLE IF NOT EXISTS set_log (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_use_id INTEGER,
        set_number    INTEGER,
        reps          INTEGER DEFAULT 0,
        weight        REAL DEFAULT 0,
        FOREIGN KEY (machine_use_id) REFERENCES machine_use(id)
    )''')

    # 9. 커스텀 루틴
    cursor.execute('''CREATE TABLE IF NOT EXISTS custom_routine (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER,
        name       TEXT,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS custom_routine_item (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        custom_id   INTEGER,
        exercise_id INTEGER,
        target_sets INTEGER DEFAULT 3,
        target_reps INTEGER DEFAULT 12,
        seq         INTEGER DEFAULT 0,
        FOREIGN KEY (custom_id)   REFERENCES custom_routine(id),
        FOREIGN KEY (exercise_id) REFERENCES exercise(id)
    )''')

    # 10. 내 무게 기록
    cursor.execute('''CREATE TABLE IF NOT EXISTS weight_log (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id   INTEGER,
        weight    REAL,
        logged_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # 11. 쿠폰 + 지급쿠폰
    cursor.execute('''CREATE TABLE IF NOT EXISTS coupons (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        partner_name TEXT,
        category     TEXT,
        code         TEXT,
        discount     TEXT,
        condition    TEXT,
        total_qty    INTEGER DEFAULT 100
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_coupon (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id   INTEGER,
        coupon_id INTEGER,
        issued_at TEXT,
        is_used   INTEGER DEFAULT 0,
        FOREIGN KEY (user_id)   REFERENCES users(id),
        FOREIGN KEY (coupon_id) REFERENCES coupons(id)
    )''')

    conn.commit()

    # ── 시드 ──
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 관리자 계정 (⚠️ 시연용 기본 계정 admin/1234 — 실제 배포 시 반드시 비밀번호 변경)
    cursor.execute('SELECT COUNT(*) FROM users')
    if cursor.fetchone()[0] == 0:
        cursor.execute('''INSERT INTO users
            (login_id, password, name, gender, goal, focus_part, height, weight,
             target_weight, fitness_level, frequency, start_weekday, created_at, role)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            ('admin', generate_password_hash('1234'), '관리자', '남', '근육량늘리기',
             '전신', 175, 75, 73, '상급', 5, 0, now, 'admin'))

    # 운동 종목 시드
    cursor.execute('SELECT COUNT(*) FROM exercise')
    if cursor.fetchone()[0] == 0:
        seed_exercises(cursor)

    # 쿠폰 시드
    cursor.execute('SELECT COUNT(*) FROM coupons')
    if cursor.fetchone()[0] == 0:
        coupons_seed = [
            ('마이프로틴', '프로틴',  'FITQR-MYP10', '10% 할인', '루틴 95% 이상 완료', 50),
            ('GNC',       '프로틴',  'FITQR-GNC15', '15% 할인', '루틴 95% 이상 완료', 30),
            ('나이키',     '운동장비', 'FITQR-NK05',  '5% 할인',  '루틴 95% 이상 완료', 50),
            ('언더아머',   '운동장비', 'FITQR-UA07',  '7% 할인',  '루틴 95% 이상 완료', 50),
            ('데카트론',   '운동장비', 'FITQR-DK05',  '5% 할인',  '루틴 95% 이상 완료', 50),
        ]
        cursor.executemany(
            '''INSERT INTO coupons (partner_name, category, code, discount, condition, total_qty)
               VALUES (?,?,?,?,?,?)''', coupons_seed)

    # 기존 DB에 평문으로 저장된 비밀번호 → 해시로 1회 마이그레이션
    # (해시는 'pbkdf2:'/'scrypt:' 로 시작하므로, 그렇지 않으면 평문으로 간주)
    cursor.execute('SELECT id, password FROM users')
    for uid, pw in cursor.fetchall():
        if pw and not is_hashed(pw):
            cursor.execute('UPDATE users SET password=? WHERE id=?',
                           (generate_password_hash(pw), uid))

    conn.commit()
    conn.close()
    print("[FitQR] DB ready (11 tables + seed)")


def seed_exercises(cursor):
    """부위별 머신 5종+ 와 비머신(거울) 대표 종목을 채운다."""
    # (name, body_part, primary, secondary, equipment, is_machine, difficulty, prep, execution, tips)
    M = 1   # 머신
    F = 0   # 비머신(거울 카메라)
    data = [
        # ── 가슴 머신 5 ──
        ('체스트프레스 머신', '가슴', '대흉근', '삼두근/전면삼각근', '머신', M, '초급',
         '등받이에 등을 붙이고 손잡이가 가슴 높이에 오게 시트를 조절한다.',
         '손잡이를 앞으로 밀어 팔을 펴고, 천천히 가슴까지 당겨 돌아온다.',
         '팔꿈치를 너무 뒤로 빼지 말고 어깨가 들리지 않게 한다.'),
        ('펙덱 플라이 머신', '가슴', '대흉근(안쪽)', '전면삼각근', '머신', M, '초급',
         '팔꿈치 패드가 어깨 높이에 오게 시트를 맞추고 가볍게 팔을 벌린다.',
         '두 패드를 가슴 앞에서 모았다가 천천히 벌린다.',
         '가슴을 모은다는 느낌으로 수축 1초 유지한다.'),
        ('인클라인 체스트프레스 머신', '가슴', '상부 대흉근', '삼두근/어깨', '머신', M, '중급',
         '등받이를 약 30도로 세우고 손잡이를 윗가슴 높이에 맞춘다.',
         '윗가슴을 밀어 올리듯 팔을 펴고 천천히 돌아온다.',
         '윗가슴 자극을 위해 손잡이 경로를 위쪽으로 가져간다.'),
        ('디클라인 체스트프레스 머신', '가슴', '하부 대흉근', '삼두근', '머신', M, '중급',
         '시트를 낮춰 손잡이가 아랫가슴 높이에 오게 한다.',
         '아랫가슴을 밀어내듯 팔을 펴고 천천히 당겨온다.',
         '반동 없이 하부 가슴 수축에 집중한다.'),
        ('케이블 크로스오버', '가슴', '대흉근', '전면삼각근', '케이블', M, '중급',
         '양쪽 도르래를 높게 걸고 한 발 앞으로 나가 살짝 기댄다.',
         '양손을 가슴 앞 아래로 모았다가 천천히 벌린다.',
         '팔꿈치 각도를 고정해 가슴으로만 모은다.'),
        # ── 등 머신 5 ──
        ('랫풀다운', '등', '광배근', '이두근/후면삼각근', '머신', M, '초급',
         '허벅지 패드를 고정하고 바를 어깨너비보다 넓게 잡는다.',
         '바를 가슴 위쪽까지 당기고 천천히 위로 돌려보낸다.',
         '어깨를 아래로 내리며 등으로 당긴다.'),
        ('시티드 케이블 로우', '등', '광배근/승모근 중부', '이두근', '케이블', M, '초급',
         '발판에 발을 대고 무릎을 살짝 굽혀 손잡이를 잡는다.',
         '손잡이를 배꼽 쪽으로 당겨 등을 모으고 천천히 편다.',
         '상체 반동을 줄이고 견갑을 조인다.'),
        ('티바로우 머신', '등', '등 두께(중부)', '이두근', '머신', M, '중급',
         '가슴 패드에 상체를 기대고 손잡이를 잡는다.',
         '손잡이를 몸쪽으로 당겨 등을 조이고 천천히 편다.',
         '팔이 아니라 등으로 당기는 느낌을 유지한다.'),
        ('백 익스텐션 머신', '등', '척추기립근', '둔근/햄스트링', '머신', M, '초급',
         '발과 골반을 패드에 고정하고 상체를 세운다.',
         '상체를 천천히 숙였다가 척추기립근 힘으로 세운다.',
         '과신전하지 말고 일직선까지만 올린다.'),
        ('어시스트 풀업 머신', '등', '광배근', '이두근', '머신', M, '중급',
         '무릎 패드에 무릎을 올리고 바를 넓게 잡는다.',
         '몸을 끌어올려 턱이 바 근처까지 오게 하고 천천히 내린다.',
         '보조 무게가 클수록 쉬워진다(점차 줄여간다).'),
        # ── 어깨 머신 5 ──
        ('숄더프레스 머신', '어깨', '삼각근', '삼두근/승모근', '머신', M, '초급',
         '등받이에 기대 손잡이가 어깨 높이에 오게 맞춘다.',
         '손잡이를 머리 위로 밀어 올리고 천천히 내린다.',
         '허리를 과하게 젖히지 않는다.'),
        ('레터럴 레이즈 머신', '어깨', '측면삼각근', '승모근', '머신', M, '초급',
         '팔을 패드에 대고 어깨가 회전축에 오게 앉는다.',
         '팔을 옆으로 들어 어깨 높이까지 올리고 천천히 내린다.',
         '어깨를 으쓱하지 말고 측면 삼각근만 사용한다.'),
        ('리어델트 플라이 머신', '어깨', '후면삼각근', '능형근', '머신', M, '중급',
         '가슴 패드에 기대 손잡이를 앞에서 잡는다.',
         '팔을 뒤로 벌려 후면 어깨를 조이고 천천히 돌아온다.',
         '팔꿈치를 약간 굽힌 채 후면 삼각근에 집중한다.'),
        ('케이블 프론트 레이즈', '어깨', '전면삼각근', '', '케이블', M, '중급',
         '낮은 도르래에 손잡이를 걸고 허벅지 앞에서 잡는다.',
         '팔을 앞으로 들어 어깨 높이까지 올리고 천천히 내린다.',
         '반동 없이 전면 삼각근으로만 들어 올린다.'),
        ('케이블 페이스풀', '어깨', '후면삼각근/승모근', '회전근개', '케이블', M, '중급',
         '얼굴 높이 도르래에 로프를 걸고 양손으로 잡는다.',
         '로프를 얼굴 쪽으로 당기며 팔꿈치를 벌린다.',
         '견갑을 모으고 손을 귀 옆으로 가져간다.'),
        # ── 팔 머신 5 ──
        ('케이블 푸쉬다운', '팔', '삼두근', '', '케이블', M, '초급',
         '높은 도르래에 바를 걸고 팔꿈치를 옆구리에 붙인다.',
         '바를 아래로 밀어 팔을 펴고 천천히 올린다.',
         '팔꿈치를 고정하고 삼두로만 편다.'),
        ('바이셉스 컬 머신', '팔', '이두근', '전완근', '머신', M, '초급',
         '팔을 패드에 올리고 손잡이를 잡는다.',
         '손잡이를 들어 이두를 수축하고 천천히 편다.',
         '반동 없이 이두 수축에 집중한다.'),
        ('트라이셉스 익스텐션 머신', '팔', '삼두근', '', '머신', M, '중급',
         '시트에 앉아 팔꿈치를 패드에 고정한다.',
         '손잡이를 밀어 팔을 펴고 천천히 굽힌다.',
         '팔꿈치 위치를 고정한 채 삼두로만 편다.'),
        ('프리처 컬 머신', '팔', '이두근', '전완근', '머신', M, '중급',
         '팔 윗부분을 경사 패드에 올리고 손잡이를 잡는다.',
         '손잡이를 들어 이두를 끝까지 수축하고 천천히 편다.',
         '팔을 완전히 펴되 팔꿈치 부상에 주의한다.'),
        ('어시스트 딥스 머신', '팔', '삼두근', '가슴/어깨', '머신', M, '중급',
         '무릎 패드에 올라가 평행봉을 잡는다.',
         '몸을 내렸다가 삼두 힘으로 밀어 올린다.',
         '상체를 세울수록 삼두 자극이 커진다.'),
        # ── 복근 머신 5 ──
        ('앱크런치 머신', '복근', '복직근', '', '머신', M, '초급',
         '패드를 잡고 등받이에 기댄다.',
         '상체를 말아 복근을 수축하고 천천히 편다.',
         '목이 아니라 복근으로 몸을 만다.'),
        ('케이블 크런치', '복근', '복직근', '', '케이블', M, '중급',
         '높은 도르래에 로프를 걸고 무릎 꿇어 로프를 머리 옆에 둔다.',
         '복근을 말아 상체를 숙이고 천천히 편다.',
         '엉덩이는 고정하고 복근만 수축한다.'),
        ('토르소 로테이션 머신', '복근', '복사근', '', '머신', M, '초급',
         '시트에 앉아 상체를 패드에 고정한다.',
         '몸통을 좌우로 회전하며 복사근을 수축한다.',
         '허리를 비틀지 말고 복사근으로 회전한다.'),
        ('로터리 토르소 머신', '복근', '복사근', '', '머신', M, '중급',
         '하체를 고정하고 상체 패드를 잡는다.',
         '몸통을 한쪽으로 회전했다 천천히 돌아온다.',
         '천천히 통제된 속도로 회전한다.'),
        ('앱코스터 머신', '복근', '복직근(하부)', '고관절굴곡근', '머신', M, '초급',
         '팔을 패드에 걸고 무릎을 든다.',
         '무릎을 가슴쪽으로 말아 올리고 천천히 내린다.',
         '반동 없이 하복부로 끌어올린다.'),
        # ── 엉덩이 머신 5 ──
        ('힙 쓰러스트 머신', '엉덩이', '대둔근', '햄스트링', '머신', M, '초급',
         '패드를 골반 위에 올리고 등을 받침에 댄다.',
         '엉덩이를 밀어 올려 골반을 펴고 천천히 내린다.',
         '맨 위에서 둔근을 1초 조인다.'),
        ('글루트 킥백 머신', '엉덩이', '대둔근', '햄스트링', '머신', M, '초급',
         '패드에 한 발을 대고 상체를 기댄다.',
         '발을 뒤로 밀어 둔근을 수축하고 천천히 돌아온다.',
         '허리를 젖히지 말고 둔근으로만 민다.'),
        ('힙 어브덕션 머신', '엉덩이', '중둔근', '', '머신', M, '초급',
         '시트에 앉아 무릎 바깥을 패드에 댄다.',
         '다리를 바깥으로 벌려 둔근을 수축하고 천천히 모은다.',
         '상체를 약간 숙이면 자극이 커진다.'),
        ('케이블 킥백', '엉덩이', '대둔근', '', '케이블', M, '중급',
         '발목에 스트랩을 걸고 도르래를 낮게 둔다.',
         '다리를 뒤로 차올려 둔근을 수축하고 천천히 돌아온다.',
         '무릎을 펴고 둔근에 집중한다.'),
        ('스미스머신 힙 쓰러스트', '엉덩이', '대둔근', '햄스트링', '스미스머신', M, '중급',
         '바를 골반 위에 올리고 등 위쪽을 벤치에 댄다.',
         '엉덩이를 밀어 올려 골반을 펴고 천천히 내린다.',
         '발 위치를 조절해 둔근 자극을 극대화한다.'),
        # ── 다리 머신 5 ──
        ('레그프레스 머신', '다리', '대퇴사두근', '둔근/햄스트링', '머신', M, '초급',
         '발판에 어깨너비로 발을 올리고 등을 시트에 붙인다.',
         '무릎을 굽혀 내렸다가 발판을 밀어 편다.',
         '무릎을 완전히 잠그지 않는다.'),
        ('레그 익스텐션 머신', '다리', '대퇴사두근', '', '머신', M, '초급',
         '발목 패드를 정강이 앞에 맞추고 앉는다.',
         '무릎을 펴 다리를 들어 올리고 천천히 내린다.',
         '맨 위에서 사두를 1초 조인다.'),
        ('레그컬 머신', '다리', '햄스트링', '', '머신', M, '초급',
         '발목 패드를 종아리 뒤에 맞추고 엎드리거나 앉는다.',
         '무릎을 굽혀 패드를 당기고 천천히 편다.',
         '엉덩이가 들리지 않게 한다.'),
        ('핵스쿼트 머신', '다리', '대퇴사두근', '둔근', '머신', M, '중급',
         '어깨 패드 아래 들어가 발을 어깨너비로 둔다.',
         '무릎을 굽혀 앉았다가 밀어 일어선다.',
         '허리를 패드에 밀착해 유지한다.'),
        ('카프레이즈 머신', '다리', '비복근', '가자미근', '머신', M, '초급',
         '어깨 패드를 올리고 발 앞꿈치를 발판에 둔다.',
         '발끝으로 밀어 종아리를 들고 천천히 내린다.',
         '가동범위를 끝까지 사용한다.'),
        # ── 전신(유산소) 머신 5 ──
        ('로잉 머신', '전신', '등/다리', '심폐지구력', '머신', M, '초급',
         '발을 고정하고 손잡이를 잡아 무릎을 굽힌다.',
         '다리로 밀고 등으로 당겨 몸을 펴고 돌아온다.',
         '다리→몸통→팔 순서로 힘을 전달한다.'),
        ('어썰트 바이크', '전신', '전신', '심폐지구력', '머신', M, '초급',
         '안장 높이를 맞추고 손잡이를 잡는다.',
         '팔과 다리를 동시에 밀고 당기며 페달을 돌린다.',
         '일정한 호흡과 페이스를 유지한다.'),
        ('일립티컬', '전신', '전신', '심폐지구력', '머신', M, '초급',
         '발판에 올라 손잡이를 잡는다.',
         '팔다리를 자연스럽게 교차하며 타원을 그린다.',
         '상체를 세우고 코어를 가볍게 유지한다.'),
        ('트레드밀', '전신', '하체', '심폐지구력', '머신', M, '초급',
         '안전클립을 옷에 걸고 속도를 천천히 올린다.',
         '시선은 앞을 보고 자연스럽게 걷거나 뛴다.',
         '경사를 주면 강도를 높일 수 있다.'),
        ('스텝밀', '전신', '하체/둔근', '심폐지구력', '머신', M, '중급',
         '손잡이를 가볍게 잡고 속도를 맞춘다.',
         '계단을 오르듯 일정한 리듬으로 밟는다.',
         '손잡이에 체중을 싣지 않는다.'),
        # ── 비머신(거울 카메라) 대표 종목 ──
        ('바벨 스쿼트', '다리', '대퇴사두근', '둔근/햄스트링', '바벨/랙', F, '중급',
         '바를 승모근 위에 올리고 어깨너비로 선다.',
         '엉덩이를 뒤로 빼며 앉았다가 일어선다.',
         '무릎이 발끝 방향을 향하게 한다.'),
        ('데드리프트', '등', '척추기립근/둔근', '햄스트링/광배근', '바벨', F, '상급',
         '바를 정강이 앞에 두고 허리를 펴 잡는다.',
         '바를 몸에 붙여 들어 올리고 골반을 펴 선다.',
         '허리를 둥글게 말지 않는다.'),
        ('턱걸이(풀업) 머신', '등', '광배근', '이두근/후면삼각근', '풀업 머신', M, '상급',
         '풀업 머신 바를 어깨너비보다 넓게 잡고 매달린다.',
         '몸을 끌어올려 턱이 바 위로 오게 하고 천천히 내린다.',
         '반동 없이 등으로 당기고, 보조 풀업 머신이면 무게로 난이도를 조절한다.'),
        ('푸시업', '가슴', '대흉근', '삼두근/어깨', '맨몸', F, '초급',
         '손을 어깨너비로 짚고 몸을 일직선으로 만든다.',
         '가슴이 바닥에 닿을 듯 내렸다가 밀어 올린다.',
         '엉덩이가 처지거나 솟지 않게 한다.'),
        ('런지', '다리', '대퇴사두근/둔근', '햄스트링', '맨몸/덤벨', F, '초급',
         '한 발을 앞으로 내딛고 상체를 세운다.',
         '뒷무릎이 바닥 가까이 내려가게 앉았다 일어선다.',
         '앞무릎이 발끝을 넘지 않게 한다.'),
        ('플랭크', '복근', '복직근/코어', '척추기립근', '맨몸', F, '초급',
         '팔꿈치와 발끝으로 몸을 일직선으로 받친다.',
         '자세를 유지하며 버틴다(시간=reps로 환산).',
         '허리가 꺼지지 않게 코어를 조인다.'),
        ('바벨 벤치프레스', '가슴', '대흉근', '삼두근/전면삼각근', '바벨/플랫벤치', F, '중급',
         '벤치에 누워 바를 어깨너비보다 약간 넓게 잡는다.',
         '바를 가슴까지 내렸다가 밀어 올린다.',
         '견갑을 모으고 발로 바닥을 민다.'),
        ('오버헤드프레스', '어깨', '삼각근', '삼두근', '바벨', F, '중급',
         '바를 쇄골 위에 두고 어깨너비로 잡는다.',
         '바를 머리 위로 밀어 올리고 천천히 내린다.',
         '복근과 둔근을 조여 허리를 보호한다.'),
        ('바벨 로우', '등', '광배근/중부등', '이두근', '바벨', F, '중급',
         '상체를 숙여 바를 어깨너비로 잡는다.',
         '바를 배꼽 쪽으로 당겨 등을 조이고 내린다.',
         '허리를 곧게 유지한다.'),
        ('덤벨 컬', '팔', '이두근', '전완근', '덤벨', F, '초급',
         '덤벨을 양손에 들고 팔을 펴 선다.',
         '덤벨을 들어 이두를 수축하고 천천히 내린다.',
         '팔꿈치를 고정하고 반동을 쓰지 않는다.'),
        ('사이드 레터럴 레이즈', '어깨', '측면삼각근', '', '덤벨', F, '초급',
         '덤벨을 양 옆에 들고 선다.',
         '팔을 옆으로 들어 어깨 높이까지 올리고 내린다.',
         '새끼손가락을 약간 위로 기울인다.'),
        ('버피', '전신', '전신', '심폐지구력', '맨몸', F, '중급',
         '선 자세에서 시작한다.',
         '앉아 손 짚고 다리를 뒤로 뻗었다가 점프해 일어선다.',
         '빠르되 착지 충격을 줄인다.'),
    ]
    cursor.executemany(
        '''INSERT INTO exercise
           (name, body_part, primary_target, secondary_target, equipment,
            is_machine, difficulty, prep, execution, tips)
           VALUES (?,?,?,?,?,?,?,?,?,?)''', data)


# ════════════════════════════════════════════════════════════════════
#  30일 루틴 생성 로직
# ════════════════════════════════════════════════════════════════════
FREQ_OFFSETS = {
    1: [0], 2: [0, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4],
    5: [0, 1, 2, 3, 4], 6: [0, 1, 2, 3, 4, 5], 7: [0, 1, 2, 3, 4, 5, 6],
}
SETS_BY_LEVEL = {'초급': 3, '중급': 4, '상급': 5}
COUNT_BY_LEVEL = {'초급': 3, '중급': 4, '상급': 5}
REPS_BY_GOAL = {'강해지기': 6, '근육량늘리기': 12, '체중감량': 15}


def build_part_cycle(focus_part):
    """집중 부위(복수, 쉼표구분 가능)를 우선 배치한 부위 순환 리스트."""
    base = ['가슴', '등', '다리', '어깨', '팔', '엉덩이', '복근']
    # '가슴,등' 같은 문자열 또는 단일값 모두 허용
    focus = [x.strip() for x in (focus_part or '').split(',') if x.strip()]
    focus = [f for f in focus if f in base]   # '전신'/유효하지 않은 값 제거
    if not focus:
        return base
    # 선택한 부위를 앞쪽에 우선 배치하고, 나머지 부위는 뒤에 붙여 다양성 유지
    return focus + [p for p in base if p not in focus]


def create_routine_for_user(cursor, user):
    """가입 직후 30일 루틴 생성. user = users row 튜플."""
    uid = user[0]
    focus_part = user[6]
    fitness_level = user[10] or '초급'
    frequency = user[14] or 3
    start_weekday = user[15] or 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute('INSERT INTO routine (user_id, created_at, status) VALUES (?,?,?)',
                   (uid, now, '진행중'))
    rid = cursor.lastrowid

    offsets = FREQ_OFFSETS.get(frequency, [0, 2, 4])
    cycle = build_part_cycle(focus_part)
    sets = SETS_BY_LEVEL.get(fitness_level, 3)
    count = COUNT_BY_LEVEL.get(fitness_level, 3)
    reps = REPS_BY_GOAL.get(user[5], 12)

    # 30개 운동일의 요일 시퀀스 생성
    weekday_seq = []
    week = 0
    while len(weekday_seq) < 30:
        for off in offsets:
            weekday_seq.append((start_weekday + off) % 7)
            if len(weekday_seq) >= 30:
                break
        week += 1

    for i in range(30):
        day_no = i + 1
        weekday = weekday_seq[i]
        body_part = cycle[i % len(cycle)]
        cursor.execute('''INSERT INTO routine_day
            (routine_id, day_no, weekday, is_rest, body_part, is_unlocked, is_completed)
            VALUES (?,?,?,0,?,?,0)''',
            (rid, day_no, weekday, body_part, 1 if day_no == 1 else 0))
        rday_id = cursor.lastrowid

        # 그날 부위 종목 선택 (머신 우선, 부족하면 같은 부위 비머신, 그래도 없으면 전신)
        cursor.execute('''SELECT id FROM exercise WHERE body_part = ?
                          ORDER BY is_machine DESC, id''', (body_part,))
        ex_ids = [r[0] for r in cursor.fetchall()]
        if len(ex_ids) < count:
            cursor.execute("SELECT id FROM exercise WHERE body_part = '전신' ORDER BY id")
            ex_ids += [r[0] for r in cursor.fetchall()]
        random.shuffle(ex_ids)
        chosen = ex_ids[:count] if ex_ids else []
        for seq, eid in enumerate(chosen):
            cursor.execute('''INSERT INTO routine_day_item
                (routine_day_id, exercise_id, target_sets, target_reps, seq)
                VALUES (?,?,?,?,?)''', (rday_id, eid, sets, reps, seq))
    return rid


# ════════════════════════════════════════════════════════════════════
#  공통 헬퍼
# ════════════════════════════════════════════════════════════════════
def require_login():
    """세션에 user_id가 있고, 실제 DB에 해당 유저가 존재하면 True.
    DB 리셋 후 브라우저 쿠키가 남아 있는 경우 등에서 자동으로 세션을 지운다."""
    if 'user_id' not in session:
        return False
    conn, cursor = get_db()
    cursor.execute('SELECT id FROM users WHERE id=?', (session['user_id'],))
    exists = cursor.fetchone() is not None
    conn.close()
    if not exists:
        session.clear()   # 유령 세션 제거
    return exists


def require_admin():
    """관리자 여부를 세션 값만 믿지 않고 DB에서 직접 확인(세션 쿠키 위조 대비 심층 방어).
    설령 secret_key 가 새어 role=admin 쿠키를 위조해도, 실제 DB role 이 user 면 차단된다."""
    if 'user_id' not in session:
        return False
    conn, cursor = get_db()
    cursor.execute('SELECT role FROM users WHERE id=?', (session['user_id'],))
    row = cursor.fetchone()
    conn.close()
    return bool(row) and row[0] == 'admin'


def current_routine(cursor, uid):
    cursor.execute('SELECT * FROM routine WHERE user_id=? ORDER BY id DESC LIMIT 1', (uid,))
    return cursor.fetchone()


def routine_progress(cursor, routine_id):
    cursor.execute('SELECT COUNT(*) FROM routine_day WHERE routine_id=?', (routine_id,))
    total = cursor.fetchone()[0] or 30
    cursor.execute('SELECT COUNT(*) FROM routine_day WHERE routine_id=? AND is_completed=1',
                   (routine_id,))
    done = cursor.fetchone()[0]
    return done, total, round(done / total * 100) if total else 0


def get_active_workout(cursor, uid):
    """진행중 workout 1개를 돌려준다(없으면 None)."""
    cursor.execute('''SELECT * FROM workout WHERE user_id=? AND status='진행중'
                      ORDER BY id DESC LIMIT 1''', (uid,))
    return cursor.fetchone()


def recalc_workout(cursor, workout_id):
    """workout 의 총 볼륨/시간 재계산."""
    cursor.execute('''SELECT COALESCE(SUM(sl.reps*sl.weight),0)
                      FROM set_log sl
                      JOIN machine_use mu ON sl.machine_use_id=mu.id
                      WHERE mu.workout_id=?''', (workout_id,))
    vol = cursor.fetchone()[0] or 0
    cursor.execute('UPDATE workout SET total_volume=? WHERE id=?', (vol, workout_id))
    return vol


# ════════════════════════════════════════════════════════════════════
#  회원가입 / 로그인
# ════════════════════════════════════════════════════════════════════
@app.route('/register/', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        f = request.form
        login_id = f.get('login_id', '').strip()
        password = f.get('password', '')
        name     = f.get('name', '').strip()
        if not login_id or not password or not name:
            return render_template('register.html', error='아이디·비밀번호·이름은 필수입니다.',
                                   body_parts=BODY_PARTS, goals=GOALS, levels=LEVELS,
                                   weekdays=WEEKDAYS)
        gender   = f.get('gender', '남')
        goal     = f.get('goal', '근육량늘리기')
        # 집중 부위: 복수 선택 → 중복 제거 후 쉼표로 저장 (없으면 전신)
        focus = ','.join(dict.fromkeys([x for x in f.getlist('focus_part') if x])) or '전신'
        height   = to_float(f.get('height'), 170)
        weight   = to_float(f.get('weight'), 70)
        target   = to_float(f.get('target_weight'), weight)
        level    = f.get('fitness_level', '초급')
        squat    = to_float(f.get('squat_1rm'), 0)
        bench    = to_float(f.get('bench_1rm'), 0)
        dead     = to_float(f.get('deadlift_1rm'), 0)
        freq     = min(max(to_int(f.get('frequency'), 3), 1), 7)   # 1~7 범위 강제
        start_wd = min(max(to_int(f.get('start_weekday'), 0), 0), 6)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn, cursor = get_db()
        cursor.execute('SELECT id FROM users WHERE login_id=?', (login_id,))
        if cursor.fetchone():
            conn.close()
            return render_template('register.html', error='이미 존재하는 아이디입니다.',
                                   body_parts=BODY_PARTS, goals=GOALS, levels=LEVELS,
                                   weekdays=WEEKDAYS)
        cursor.execute('''INSERT INTO users
            (login_id, password, name, gender, goal, focus_part, height, weight,
             target_weight, fitness_level, squat_1rm, bench_1rm, deadlift_1rm,
             frequency, start_weekday, created_at, role)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'user')''',
            (login_id, generate_password_hash(password), name, gender, goal, focus,
             height, weight, target, level, squat, bench, dead, freq, start_wd, now))
        uid = cursor.lastrowid
        # 첫 체중 기록
        cursor.execute('INSERT INTO weight_log (user_id, weight, logged_at) VALUES (?,?,?)',
                       (uid, weight, now))
        # 30일 루틴 생성
        cursor.execute('SELECT * FROM users WHERE id=?', (uid,))
        create_routine_for_user(cursor, cursor.fetchone())
        conn.commit()
        conn.close()
        # 자동 로그인
        session['user_id'] = uid
        session['name'] = name
        session['role'] = 'user'
        return redirect('/')

    return render_template('register.html', error='', body_parts=BODY_PARTS,
                           goals=GOALS, levels=LEVELS, weekdays=WEEKDAYS)


@app.route('/login/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        ip = request.remote_addr or '?'
        # 무차별 대입 방어: 같은 IP에서 최근 5분 5회 이상 실패면 잠금
        if login_blocked(ip):
            return render_template(
                'login.html',
                error='로그인 시도가 너무 많습니다. 잠시 후(약 5분 뒤) 다시 시도하세요.')

        login_id = request.form.get('login_id', '')
        password = request.form.get('password', '')
        conn, cursor = get_db()
        cursor.execute('SELECT * FROM users WHERE login_id=?', (login_id,))
        user = cursor.fetchone()

        # 비밀번호 검증: 해시면 check_password_hash, (혹시 남은) 평문이면 직접 비교 후 해시로 승급
        ok = False
        if user:
            stored = user[2]
            if is_hashed(stored):
                ok = check_password_hash(stored, password)
            elif stored == password:       # 레거시 평문 → 일치하면 해시로 업그레이드
                ok = True
                cursor.execute('UPDATE users SET password=? WHERE id=?',
                               (generate_password_hash(password), user[0]))
                conn.commit()
        else:
            # 사용자가 없어도 더미 해시를 검증해 응답 시간을 맞춤(아이디 존재 여부 타이밍 노출 방지)
            check_password_hash(_DUMMY_HASH, password)
        conn.close()

        if ok:
            clear_login_fails(ip)          # 성공 시 실패 카운트 초기화
            session.clear()                # 이전 계정 흔적 제거 후 새로 설정
            session['user_id'] = user[0]
            session['name'] = user[3]
            session['role'] = user[17]
            return redirect('/')
        # 실패: 카운트 기록 + (성공/실패 동일한) 일반적 메시지(아이디 존재 여부 노출 안 함)
        record_login_fail(ip)
        return render_template('login.html', error='아이디 또는 비밀번호가 틀렸습니다.')
    return render_template('login.html', error='')


@app.route('/logout/')
def logout():
    session.clear()
    return redirect('/login/')


# ════════════════════════════════════════════════════════════════════
#  탭1: 루틴 (홈) — 계획 / 훈련
# ════════════════════════════════════════════════════════════════════
@app.route('/')
def index():
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    routine = current_routine(cursor, uid)
    if not routine:                      # 안전망: 루틴 없으면 생성
        cursor.execute('SELECT * FROM users WHERE id=?', (uid,))
        create_routine_for_user(cursor, cursor.fetchone())
        conn.commit()
        routine = current_routine(cursor, uid)
    cursor.execute('''SELECT id, day_no, weekday, body_part, is_unlocked, is_completed
                      FROM routine_day WHERE routine_id=? ORDER BY day_no''', (routine[0],))
    days = cursor.fetchall()
    done, total, rate = routine_progress(cursor, routine[0])
    conn.close()
    return render_template('routine_home.html', days=days, weekdays=WEEKDAYS,
                           done=done, total=total, rate=rate, active='routine')


@app.route('/routine/exercises/')
def routine_exercises():
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    routine = current_routine(cursor, uid)
    cursor.execute('''SELECT DISTINCT e.id, e.name, e.body_part, e.is_machine, e.difficulty
                      FROM routine_day_item rdi
                      JOIN routine_day rd ON rdi.routine_day_id=rd.id
                      JOIN exercise e ON rdi.exercise_id=e.id
                      WHERE rd.routine_id=?
                      ORDER BY e.body_part, e.name''', (routine[0],))
    rows = cursor.fetchall()
    conn.close()
    # 부위별 그룹화
    groups = {}
    for r in rows:
        groups.setdefault(r[2], []).append(r)
    return render_template('routine_train.html', groups=groups, active='routine')


@app.route('/routine/day/<int:day_no>/')
def routine_day(day_no):
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    routine = current_routine(cursor, uid)
    cursor.execute('SELECT * FROM routine_day WHERE routine_id=? AND day_no=?',
                   (routine[0], day_no))
    rday = cursor.fetchone()
    if not rday:
        conn.close()
        return redirect('/')
    cursor.execute('''SELECT rdi.id, e.id, e.name, e.body_part, e.is_machine,
                             e.primary_target, e.difficulty, rdi.target_sets, rdi.target_reps
                      FROM routine_day_item rdi
                      JOIN exercise e ON rdi.exercise_id=e.id
                      WHERE rdi.routine_day_id=? ORDER BY rdi.seq''', (rday[0],))
    items = cursor.fetchall()
    conn.close()
    return render_template('routine_day.html', rday=rday, items=items,
                           weekdays=WEEKDAYS, active='routine')


# ════════════════════════════════════════════════════════════════════
#  종목 상세 + 머신 QR
# ════════════════════════════════════════════════════════════════════
@app.route('/exercise/<int:eid>/')
def exercise_detail(eid):
    if not require_login():
        return redirect('/login/')
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM exercise WHERE id=?', (eid,))
    e = cursor.fetchone()
    active = get_active_workout(cursor, session['user_id'])
    conn.close()
    if not e:
        return redirect('/exercises/')
    return render_template('exercise_detail.html', e=e,
                           active_workout=active[0] if active else None, active='exercises')


@app.route('/machine/<int:eid>/')
def machine(eid):
    """QR 스캔 진입점 (머신 종목 정보)."""
    if not require_login():
        return redirect('/login/')
    # QR 스캔에서 넘어올 때 ?wid=<workout_id>, ?scanned=1 이 붙어옴
    wid = request.args.get('wid', '')
    scanned = request.args.get('scanned') == '1'   # 실제 QR 스캔으로 들어왔는지
    # 발표용 QR이면 사전입력 세트/횟수/무게가 함께 옴
    d_sets = to_int(request.args.get('sets'), 0)
    d_reps = to_int(request.args.get('reps'), 0)
    d_weight = to_float(request.args.get('weight'), 0)
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM exercise WHERE id=?', (eid,))
    e = cursor.fetchone()
    if not wid:
        active = get_active_workout(cursor, session['user_id'])
        wid = active[0] if active else ''
    conn.close()
    if not e:
        return redirect('/exercises/')
    return render_template('machine.html', e=e, wid=wid, scanned=scanned,
                           d_sets=d_sets, d_reps=d_reps, d_weight=d_weight,
                           active='exercises')


@app.route('/machine/<int:eid>/qr.png')
def machine_qr(eid):
    if not HAS_QR:
        return ('qrcode 미설치', 404)
    url = url_for('machine', eid=eid, _external=True)
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


# ─── 머신 QR 모아보기 (시연/인쇄용) ────────────────────
@app.route('/qrcodes/')
def qrcodes():
    if not require_login():
        return redirect('/login/')
    bp = request.args.get('bp', '')
    mc = request.args.get('mc', '')      # '1' 머신만 / '0' 거울만 / '' 전체
    conn, cursor = get_db()
    sql = 'SELECT id, name, body_part, is_machine FROM exercise WHERE 1=1'
    params = []
    if bp:
        sql += ' AND body_part=?'
        params.append(bp)
    if mc in ('0', '1'):
        sql += ' AND is_machine=?'
        params.append(int(mc))
    sql += ' ORDER BY body_part, is_machine DESC, id'
    cursor.execute(sql, params)
    machines = cursor.fetchall()
    conn.close()
    return render_template('qrcodes.html', machines=machines,
                           body_parts=BODY_PARTS, bp=bp, mc=mc)


# ─── 웹캠 QR 스캔 ────────────────────────────────────
@app.route('/scan/')
def scan():
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    active = get_active_workout(cursor, uid)
    # 진행 중 운동 요약 (몇 개 머신 완료했는지)
    done_count = 0
    workout_title = ''
    if active:
        cursor.execute('SELECT COUNT(*) FROM machine_use WHERE workout_id=? AND ended_at IS NOT NULL', (active[0],))
        done_count = cursor.fetchone()[0]
        workout_title = active[5]
    conn.close()
    wid = active[0] if active else ''
    return render_template('scan.html', wid=wid,
                           workout_title=workout_title, done_count=done_count)


# ════════════════════════════════════════════════════════════════════
#  운동 흐름 : workout(운동) > machine_use(사용) > set_log(세트)
# ════════════════════════════════════════════════════════════════════
def _get_or_create_routine_workout(uid, day_no):
    """루틴 day_no 에 대한 진행중 workout을 가져오거나 새로 생성. (wid, rday) 반환."""
    conn, cursor = get_db()
    routine = current_routine(cursor, uid)
    cursor.execute('SELECT * FROM routine_day WHERE routine_id=? AND day_no=?',
                   (routine[0], day_no))
    rday = cursor.fetchone()
    if not rday or not rday[6]:          # 없거나 잠김
        conn.close()
        return None, None
    active = get_active_workout(cursor, uid)
    if active:
        conn.close()
        return active[0], rday
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    title = f'{day_no}일차 - {rday[5]}'
    cursor.execute('''INSERT INTO workout
        (user_id, source, routine_day_id, title, started_at, status)
        VALUES (?,?,?,?,?, '진행중')''', (uid, '루틴', rday[0], title, now))
    wid = cursor.lastrowid
    conn.commit()
    conn.close()
    return wid, rday


# QR 스캔 화면으로 (운동 세션 생성 후 /scan/ 으로)
@app.route('/routine/day/<int:day_no>/scan/', methods=['POST'])
def routine_day_scan(day_no):
    if not require_login():
        return redirect('/login/')
    wid, rday = _get_or_create_routine_workout(session['user_id'], day_no)
    if not wid:
        return redirect('/')
    return redirect('/scan/')


# 운동 진행 화면 직접 보기 (기록 확인용으로 남김)
@app.route('/routine/day/<int:day_no>/start/', methods=['POST'])
def routine_day_start(day_no):
    if not require_login():
        return redirect('/login/')
    wid, rday = _get_or_create_routine_workout(session['user_id'], day_no)
    if not wid:
        return redirect('/')
    return redirect(f'/workout/{wid}/')


@app.route('/workout/<int:wid>/')
def workout(wid):
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM workout WHERE id=?', (wid,))
    w = cursor.fetchone()
    if not w or w[1] != uid:
        conn.close()
        return redirect('/')
    if w[8] == '완료':
        conn.close()
        return redirect(f'/workout/{wid}/done/')

    # 계획된 종목 (루틴/커스텀)  · workout: 0id 1user 2source 3routine_day_id 4custom_id 5title 6start 7end 8status
    planned = []
    if w[3]:   # routine_day_id
        cursor.execute('''SELECT e.id, e.name, e.body_part, e.is_machine,
                                 rdi.target_sets, rdi.target_reps
                          FROM routine_day_item rdi JOIN exercise e ON rdi.exercise_id=e.id
                          WHERE rdi.routine_day_id=? ORDER BY rdi.seq''', (w[3],))
        planned = cursor.fetchall()
    elif w[4]:  # custom_id
        cursor.execute('''SELECT e.id, e.name, e.body_part, e.is_machine,
                                 ci.target_sets, ci.target_reps
                          FROM custom_routine_item ci JOIN exercise e ON ci.exercise_id=e.id
                          WHERE ci.custom_id=? ORDER BY ci.seq''', (w[4],))
        planned = cursor.fetchall()

    # 이미 한 종목 사용들 + 세트 집계
    cursor.execute('''SELECT mu.id, e.name, e.is_machine, mu.weight, mu.ended_at,
                             (SELECT COUNT(*) FROM set_log WHERE machine_use_id=mu.id),
                             (SELECT COALESCE(SUM(reps),0) FROM set_log WHERE machine_use_id=mu.id)
                      FROM machine_use mu JOIN exercise e ON mu.exercise_id=e.id
                      WHERE mu.workout_id=? ORDER BY mu.id''', (wid,))
    uses = cursor.fetchall()
    conn.close()
    return render_template('workout.html', w=w, planned=planned, uses=uses, active='routine')


# 계획된 종목 "시작" → QR 스캔 vs 수동 시작 선택 화면
@app.route('/use/choose/<int:eid>/')
def use_choose(eid):
    if not require_login():
        return redirect('/login/')
    wid = request.args.get('wid', '')
    conn, cursor = get_db()
    cursor.execute('SELECT id, name, body_part, is_machine FROM exercise WHERE id=?', (eid,))
    e = cursor.fetchone()
    conn.close()
    if not e:
        return redirect('/exercises/')
    return render_template('use_choose.html', e=e, wid=wid, active='routine')


@app.route('/use/start/', methods=['POST'])
def use_start():
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    eid = to_int(request.form.get('exercise_id'), 0)
    if not eid:
        return redirect('/exercises/')
    wid = request.form.get('workout_id')
    conn, cursor = get_db()

    # workout 확보 (없으면 단독 운동 생성)
    w = None
    if wid:
        cursor.execute('SELECT * FROM workout WHERE id=? AND user_id=?', (wid, uid))
        w = cursor.fetchone()
    if not w or w[8] == '완료':
        w = get_active_workout(cursor, uid)
    if not w:
        cursor.execute('SELECT name FROM exercise WHERE id=?', (eid,))
        en = cursor.fetchone()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''INSERT INTO workout (user_id, source, title, started_at, status)
                          VALUES (?,?,?,?, '진행중')''',
                       (uid, '단독', (en[0] if en else '운동'), now))
        wid = cursor.lastrowid
    else:
        wid = w[0]

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''INSERT INTO machine_use (workout_id, exercise_id, started_at)
                      VALUES (?,?,?)''', (wid, eid, now))
    use_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # 진입 모드 결정
    #  - 발표용 QR(사전입력 sets/reps 포함) → demo 모드: 세트가 미리 채워짐
    #  - mode=manual → 수동 모드: 무게/횟수 직접 입력 + 세트 직접 종료(자동 휴식 없음)
    #  - 그 외(QR 스캔/일반) → auto 모드: +1 Rep + 휴식 자동 세트완료
    mode = request.form.get('mode', 'auto')
    psets = to_int(request.form.get('sets'), 0)
    preps = to_int(request.form.get('reps'), 0)
    pweight = to_float(request.form.get('weight'), 0)
    if psets and preps:
        q = f'?demo=1&sets={psets}&reps={preps}&weight={pweight}'
    elif mode == 'manual':
        q = '?mode=manual'
    else:
        q = ''
    return redirect(f'/use/{use_id}/{q}')


@app.route('/use/<int:use_id>/')
def use_screen(use_id):
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    # mu.*(0~5) | 6 e.name 7 is_machine 8 primary_target 9 body_part | 10 w.user_id 11 w.id
    cursor.execute('''SELECT mu.*, e.name, e.is_machine, e.primary_target, e.body_part,
                             w.user_id, w.id
                      FROM machine_use mu
                      JOIN exercise e ON mu.exercise_id=e.id
                      JOIN workout w ON mu.workout_id=w.id
                      WHERE mu.id=?''', (use_id,))
    row = cursor.fetchone()
    if not row or row[10] != uid:
        conn.close()
        return redirect('/')
    wid = row[11]
    eid = row[2]                          # mu.exercise_id
    # 계획 세트/횟수(있으면) 가져오기
    target_sets, target_reps = 3, 12
    cursor.execute('SELECT routine_day_id, custom_id FROM workout WHERE id=?', (wid,))
    wsrc = cursor.fetchone()
    if wsrc and wsrc[0]:
        cursor.execute('''SELECT target_sets, target_reps FROM routine_day_item
                          WHERE routine_day_id=? AND exercise_id=? LIMIT 1''', (wsrc[0], eid))
        t = cursor.fetchone()
        if t:
            target_sets, target_reps = t
    elif wsrc and wsrc[1]:
        cursor.execute('''SELECT target_sets, target_reps FROM custom_routine_item
                          WHERE custom_id=? AND exercise_id=? LIMIT 1''', (wsrc[1], eid))
        t = cursor.fetchone()
        if t:
            target_sets, target_reps = t
    conn.close()

    # 진입 모드: demo(발표용 사전입력) / manual(수동) / auto(QR 자동)
    if request.args.get('demo') == '1':
        mode = 'demo'
    elif request.args.get('mode') == 'manual':
        mode = 'manual'
    else:
        mode = 'auto'
    demo_sets = to_int(request.args.get('sets'), 0)
    demo_reps = to_int(request.args.get('reps'), 0)
    demo_weight = to_float(request.args.get('weight'), 0)

    return render_template('use.html', use=row, workout_id=wid,
                           target_sets=target_sets, target_reps=target_reps,
                           rest_sec=REST_SEC, mode=mode,
                           demo_sets=demo_sets, demo_reps=demo_reps,
                           demo_weight=demo_weight, active='routine')


@app.route('/use/<int:use_id>/end/', methods=['POST'])
def use_end(use_id):
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    cursor.execute('''SELECT mu.id, mu.workout_id, w.user_id
                      FROM machine_use mu JOIN workout w ON mu.workout_id=w.id
                      WHERE mu.id=?''', (use_id,))
    row = cursor.fetchone()
    if not row or row[2] != uid:
        conn.close()
        return redirect('/')
    wid = row[1]
    weight = to_float(request.form.get('weight'), 0)
    # sets_json = [{"reps":12,"weight":40}, ...]
    try:
        sets = json.loads(request.form.get('sets_json', '[]'))
        if not isinstance(sets, list):
            sets = []
    except Exception:
        sets = []
    cursor.execute('UPDATE machine_use SET weight=? WHERE id=?', (weight, use_id))
    n = 0
    for s in sets:
        if not isinstance(s, dict):
            continue
        reps = to_int(s.get('reps'), 0)
        w = to_float(s.get('weight'), weight) or weight
        if reps <= 0:
            continue
        n += 1
        cursor.execute('''INSERT INTO set_log (machine_use_id, set_number, reps, weight)
                          VALUES (?,?,?,?)''', (use_id, n, reps, w))
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('UPDATE machine_use SET ended_at=? WHERE id=?', (now, use_id))
    recalc_workout(cursor, wid)

    # 사용 화면에서 [운동 종료]를 누른 경우: 이어서 운동 전체 종료
    if request.form.get('then_end') == '1':
        reward = _finalize_workout(cursor, uid, wid)
        conn.commit()
        conn.close()
        if reward:
            session['new_reward'] = reward
        return redirect(f'/workout/{wid}/done/')
    conn.commit()
    conn.close()
    # [사용 종료] → 스캔 화면으로 돌아가서 다음 머신 QR 스캔
    return redirect('/scan/')


def _finalize_workout(cursor, uid, wid):
    """workout 완료 처리(시간·볼륨·루틴 해금·보상). 지급 쿠폰 id 또는 None."""
    cursor.execute('SELECT * FROM workout WHERE id=?', (wid,))
    w = cursor.fetchone()
    if not w or w[1] != uid or w[8] == '완료':
        return None
    now = datetime.now()
    now_s = now.strftime('%Y-%m-%d %H:%M:%S')
    try:
        started = datetime.strptime(w[6], '%Y-%m-%d %H:%M:%S')
        dur = int((now - started).total_seconds())
    except Exception:
        dur = 0
    vol = recalc_workout(cursor, wid)
    cursor.execute('''UPDATE workout SET status='완료', ended_at=?, duration_sec=?, total_volume=?
                      WHERE id=?''', (now_s, dur, vol, wid))
    reward = None
    if w[3]:                              # routine_day_id
        cursor.execute('UPDATE routine_day SET is_completed=1, completed_at=? WHERE id=?',
                       (now_s, w[3]))
        cursor.execute('SELECT routine_id, day_no FROM routine_day WHERE id=?', (w[3],))
        rd = cursor.fetchone()
        if rd:
            cursor.execute('''UPDATE routine_day SET is_unlocked=1
                              WHERE routine_id=? AND day_no=?''', (rd[0], rd[1] + 1))
            reward = check_reward(cursor, uid, rd[0])
    return reward


@app.route('/workout/<int:wid>/end/', methods=['POST'])
def workout_end(wid):
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    cursor.execute('SELECT id FROM workout WHERE id=? AND user_id=?', (wid, uid))
    if not cursor.fetchone():
        conn.close()
        return redirect('/')
    reward = _finalize_workout(cursor, uid, wid)
    conn.commit()
    conn.close()
    if reward:
        session['new_reward'] = reward
    return redirect(f'/workout/{wid}/done/')


def check_reward(cursor, uid, routine_id):
    """루틴 95% 이상 + 미지급이면 쿠폰 1개 지급. 지급한 user_coupon id 반환."""
    done, total, rate = routine_progress(cursor, routine_id)
    if rate < 95:
        return None
    cursor.execute('SELECT reward_given FROM routine WHERE id=?', (routine_id,))
    rg = cursor.fetchone()
    if rg and rg[0]:
        return None
    cursor.execute('SELECT * FROM coupons WHERE total_qty>0')
    avail = cursor.fetchall()
    if not avail:
        return None
    c = random.choice(avail)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''INSERT INTO user_coupon (user_id, coupon_id, issued_at, is_used)
                      VALUES (?,?,?,0)''', (uid, c[0], now))
    ucid = cursor.lastrowid
    cursor.execute('UPDATE coupons SET total_qty=total_qty-1 WHERE id=?', (c[0],))
    cursor.execute("UPDATE routine SET reward_given=1, status='완료' WHERE id=?", (routine_id,))
    return ucid


@app.route('/workout/<int:wid>/done/')
def workout_done(wid):
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM workout WHERE id=?', (wid,))
    w = cursor.fetchone()
    if not w or w[1] != uid:
        conn.close()
        return redirect('/')
    uses = use_summary(cursor, wid)
    conn.close()
    new_reward = session.pop('new_reward', None)
    return render_template('workout_done.html', w=w, uses=uses,
                           new_reward=new_reward, active='routine')


def use_summary(cursor, wid):
    """workout 의 종목별 세트 요약 리스트."""
    cursor.execute('''SELECT mu.id, e.name, e.is_machine, mu.weight
                      FROM machine_use mu JOIN exercise e ON mu.exercise_id=e.id
                      WHERE mu.workout_id=? ORDER BY mu.id''', (wid,))
    uses = []
    for mu in cursor.fetchall():
        cursor.execute('''SELECT set_number, reps, weight FROM set_log
                          WHERE machine_use_id=? ORDER BY set_number''', (mu[0],))
        sets = cursor.fetchall()
        vol = sum(s[1] * s[2] for s in sets)
        uses.append({'name': mu[1], 'is_machine': mu[2], 'weight': mu[3],
                     'sets': sets, 'volume': vol})
    return uses


# ════════════════════════════════════════════════════════════════════
#  탭3: 운동 카탈로그
# ════════════════════════════════════════════════════════════════════
@app.route('/exercises/')
def exercises():
    if not require_login():
        return redirect('/login/')
    q = request.args.get('q', '').strip()
    bp = request.args.get('bp', '')
    mc = request.args.get('mc', '')      # '1' 머신만 / '0' 비머신만
    conn, cursor = get_db()
    sql = 'SELECT id, name, body_part, primary_target, equipment, is_machine, difficulty FROM exercise WHERE 1=1'
    params = []
    if q:
        sql += ' AND name LIKE ?'; params.append(f'%{q}%')
    if bp:
        sql += ' AND body_part=?'; params.append(bp)
    if mc in ('0', '1'):
        sql += ' AND is_machine=?'; params.append(int(mc))
    sql += ' ORDER BY body_part, is_machine DESC, name'
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    return render_template('exercises.html', rows=rows, q=q, bp=bp, mc=mc,
                           body_parts=BODY_PARTS, active='exercises')


# ════════════════════════════════════════════════════════════════════
#  탭2: 커스텀 루틴
# ════════════════════════════════════════════════════════════════════
@app.route('/custom/')
def custom():
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM custom_routine WHERE user_id=? ORDER BY id DESC', (uid,))
    routines = []
    for cr in cursor.fetchall():
        cursor.execute('''SELECT e.name, ci.target_sets, ci.target_reps
                          FROM custom_routine_item ci JOIN exercise e ON ci.exercise_id=e.id
                          WHERE ci.custom_id=? ORDER BY ci.seq''', (cr[0],))
        routines.append({'id': cr[0], 'name': cr[2], 'exlist': cursor.fetchall()})
    cursor.execute('SELECT id, name, body_part, is_machine FROM exercise ORDER BY body_part, name')
    all_ex = cursor.fetchall()
    conn.close()
    return render_template('custom.html', routines=routines, all_ex=all_ex,
                           body_parts=BODY_PARTS, active='custom')


@app.route('/custom/create/', methods=['POST'])
def custom_create():
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    name = request.form.get('name', '').strip() or '나의 커스텀 루틴'
    ex_ids = request.form.getlist('exercise_id')
    sets_l = request.form.getlist('sets')
    reps_l = request.form.getlist('reps')
    if not ex_ids:
        return redirect('/custom/')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn, cursor = get_db()
    cursor.execute('INSERT INTO custom_routine (user_id, name, created_at) VALUES (?,?,?)',
                   (uid, name, now))
    cid = cursor.lastrowid
    seq = 0
    for i, eid in enumerate(ex_ids):
        eid_n = to_int(eid, 0)
        if not eid_n:
            continue
        s = to_int(sets_l[i], 3) if i < len(sets_l) else 3
        r = to_int(reps_l[i], 12) if i < len(reps_l) else 12
        cursor.execute('''INSERT INTO custom_routine_item
            (custom_id, exercise_id, target_sets, target_reps, seq)
            VALUES (?,?,?,?,?)''', (cid, eid_n, s, r, seq))
        seq += 1
    conn.commit()
    conn.close()
    return redirect('/custom/')


@app.route('/custom/<int:cid>/delete/', methods=['POST'])
def custom_delete(cid):
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    cursor.execute('SELECT user_id FROM custom_routine WHERE id=?', (cid,))
    r = cursor.fetchone()
    if r and r[0] == uid:
        cursor.execute('DELETE FROM custom_routine_item WHERE custom_id=?', (cid,))
        cursor.execute('DELETE FROM custom_routine WHERE id=?', (cid,))
        conn.commit()
    conn.close()
    return redirect('/custom/')


@app.route('/custom/<int:cid>/start/', methods=['POST'])
def custom_start(cid):
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM custom_routine WHERE id=? AND user_id=?', (cid, uid))
    cr = cursor.fetchone()
    if not cr:
        conn.close()
        return redirect('/custom/')
    active = get_active_workout(cursor, uid)
    if active:
        conn.close()
        return redirect(f'/workout/{active[0]}/')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''INSERT INTO workout (user_id, source, custom_id, title, started_at, status)
                      VALUES (?,?,?,?,?, '진행중')''', (uid, '커스텀', cid, cr[2], now))
    wid = cursor.lastrowid
    conn.commit()
    conn.close()
    return redirect(f'/workout/{wid}/')


# ════════════════════════════════════════════════════════════════════
#  탭4: 리포트 (캘린더 + 통계 + 무게)
# ════════════════════════════════════════════════════════════════════
@app.route('/report/')
def report():
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    ym = request.args.get('ym', '')
    today = date.today()
    if ym:
        try:
            y, m = map(int, ym.split('-'))
        except Exception:
            y, m = today.year, today.month
    else:
        y, m = today.year, today.month

    conn, cursor = get_db()
    # 이번달 운동한 날 집합
    first = date(y, m, 1)
    last_day = pycal.monthrange(y, m)[1]
    cursor.execute('''SELECT DISTINCT substr(ended_at,1,10) FROM workout
                      WHERE user_id=? AND status='완료'
                        AND ended_at>=? AND ended_at<?''',
                   (uid, f'{y:04d}-{m:02d}-01', f'{y:04d}-{m:02d}-{last_day:02d} 99'))
    workout_dates = {r[0] for r in cursor.fetchall() if r[0]}

    # 달력 그리드 (월요일 시작)
    cal = pycal.Calendar(firstweekday=0)
    weeks = cal.monthdayscalendar(y, m)

    # 총 통계
    cursor.execute("SELECT COUNT(*) FROM workout WHERE user_id=? AND status='완료'", (uid,))
    total_workouts = cursor.fetchone()[0]
    cursor.execute("SELECT COALESCE(SUM(total_volume),0), COALESCE(SUM(duration_sec),0) FROM workout WHERE user_id=? AND status='완료'", (uid,))
    tv, td = cursor.fetchone()

    # 이번주 부위 히트맵 (최근 7일 부위별 볼륨)
    week_ago = (today - timedelta(days=6)).strftime('%Y-%m-%d')
    cursor.execute('''SELECT e.body_part, COALESCE(SUM(sl.reps*sl.weight),0)
                      FROM set_log sl
                      JOIN machine_use mu ON sl.machine_use_id=mu.id
                      JOIN workout w ON mu.workout_id=w.id
                      JOIN exercise e ON mu.exercise_id=e.id
                      WHERE w.user_id=? AND w.status='완료' AND substr(w.ended_at,1,10)>=?
                      GROUP BY e.body_part''', (uid, week_ago))
    heat = {r[0]: r[1] for r in cursor.fetchall()}
    heat_max = max(heat.values()) if heat else 0

    # 최근 운동 기록 5개
    cursor.execute('''SELECT id, title, ended_at, duration_sec, total_volume
                      FROM workout WHERE user_id=? AND status='완료'
                      ORDER BY id DESC LIMIT 5''', (uid,))
    recent = cursor.fetchall()

    # 내 무게 (최근 30일)
    cursor.execute('''SELECT weight, logged_at FROM weight_log
                      WHERE user_id=? ORDER BY id DESC LIMIT 30''', (uid,))
    wlogs = cursor.fetchall()[::-1]
    cur_weight = wlogs[-1][0] if wlogs else None
    conn.close()

    # 무게 차트 좌표 계산
    chart = build_weight_chart(wlogs)

    prev_ym = (first - timedelta(days=1)).strftime('%Y-%m')
    nxt = (date(y, m, last_day) + timedelta(days=1))
    next_ym = nxt.strftime('%Y-%m')

    return render_template('report.html', y=y, m=m, weeks=weeks,
                           workout_dates=workout_dates, today=today.strftime('%Y-%m-%d'),
                           total_workouts=total_workouts, total_volume=round(tv),
                           total_min=td // 60, heat=heat, heat_max=heat_max,
                           body_parts=BODY_PARTS, recent=recent, chart=chart,
                           cur_weight=cur_weight, prev_ym=prev_ym, next_ym=next_ym,
                           weekdays=WEEKDAYS, active='report')


def build_weight_chart(wlogs):
    """weight_log → SVG 폴리라인 좌표."""
    if not wlogs:
        return None
    vals = [w[0] for w in wlogs]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi = lo + 1
    W, H, pad = 300, 120, 10
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = pad + (W - 2 * pad) * (i / (n - 1) if n > 1 else 0.5)
        yv = H - pad - (H - 2 * pad) * (v - lo) / (hi - lo)
        pts.append((round(x, 1), round(yv, 1)))
    return {'points': ' '.join(f'{x},{y}' for x, y in pts),
            'dots': pts, 'lo': lo, 'hi': hi, 'W': W, 'H': H,
            'first': wlogs[0][1][5:10], 'last': wlogs[-1][1][5:10]}


@app.route('/report/day/<date_str>/')
def report_day(date_str):
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    cursor.execute('''SELECT id, title, source, started_at, ended_at, duration_sec, total_volume
                      FROM workout WHERE user_id=? AND status='완료'
                        AND substr(ended_at,1,10)=? ORDER BY id''', (uid, date_str))
    workouts = []
    for w in cursor.fetchall():
        workouts.append({'w': w, 'uses': use_summary(cursor, w[0])})
    conn.close()
    return render_template('report_day.html', date_str=date_str, workouts=workouts,
                           active='report')


@app.route('/report/weight/', methods=['POST'])
def report_weight():
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    weight = to_float(request.form.get('weight'), 0) or None
    if weight:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn, cursor = get_db()
        cursor.execute('INSERT INTO weight_log (user_id, weight, logged_at) VALUES (?,?,?)',
                       (uid, weight, now))
        cursor.execute('UPDATE users SET weight=? WHERE id=?', (weight, uid))
        conn.commit()
        conn.close()
    return redirect('/report/')


# ════════════════════════════════════════════════════════════════════
#  탭5: 내 정보 / 보상함
# ════════════════════════════════════════════════════════════════════
@app.route('/me/')
def me():
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM users WHERE id=?', (uid,))
    u = cursor.fetchone()
    routine = current_routine(cursor, uid)
    done, total, rate = routine_progress(cursor, routine[0]) if routine else (0, 30, 0)
    cursor.execute('SELECT COUNT(*) FROM user_coupon WHERE user_id=?', (uid,))
    coupon_cnt = cursor.fetchone()[0]
    conn.close()
    return render_template('me.html', u=u, weekdays=WEEKDAYS, rate=rate,
                           done=done, total=total, coupon_cnt=coupon_cnt, active='me')


@app.route('/me/edit/', methods=['GET', 'POST'])
def me_edit():
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    if request.method == 'POST':
        f = request.form
        focus = ','.join(dict.fromkeys([x for x in f.getlist('focus_part') if x])) or '전신'
        cursor.execute('''UPDATE users SET name=?, gender=?, goal=?, focus_part=?,
            height=?, weight=?, target_weight=?, fitness_level=?,
            squat_1rm=?, bench_1rm=?, deadlift_1rm=?, frequency=?, start_weekday=?
            WHERE id=?''',
            (f.get('name'), f.get('gender'), f.get('goal'), focus,
             to_float(f.get('height'), 0),
             to_float(f.get('weight'), 0),
             to_float(f.get('target_weight'), 0),
             f.get('fitness_level'),
             to_float(f.get('squat_1rm'), 0),
             to_float(f.get('bench_1rm'), 0),
             to_float(f.get('deadlift_1rm'), 0),
             min(max(to_int(f.get('frequency'), 3), 1), 7),
             min(max(to_int(f.get('start_weekday'), 0), 0), 6), uid))
        conn.commit()
        conn.close()
        session['name'] = f.get('name')
        return redirect('/me/')
    cursor.execute('SELECT * FROM users WHERE id=?', (uid,))
    u = cursor.fetchone()
    conn.close()
    return render_template('me_edit.html', u=u, body_parts=BODY_PARTS, goals=GOALS,
                           levels=LEVELS, weekdays=WEEKDAYS, active='me')


@app.route('/me/rewards/')
def rewards():
    if not require_login():
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    cursor.execute('''SELECT uc.id, c.partner_name, c.category, c.code, c.discount,
                             uc.issued_at, uc.is_used
                      FROM user_coupon uc JOIN coupons c ON uc.coupon_id=c.id
                      WHERE uc.user_id=? ORDER BY uc.id DESC''', (uid,))
    coupons = cursor.fetchall()
    conn.close()
    return render_template('rewards.html', coupons=coupons, active='me')


# ════════════════════════════════════════════════════════════════════
#  관리자 (슬림) : 통계 / 운동종목 / 쿠폰 / 회원
# ════════════════════════════════════════════════════════════════════
def admin_guard():
    if not require_login():
        return redirect('/login/')
    if not require_admin():
        return redirect('/')
    return None


@app.route('/admin/')
def admin():
    g = admin_guard()
    if g:
        return g
    conn, cursor = get_db()
    cursor.execute('SELECT COUNT(*) FROM users'); uc = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM exercise'); ec = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM workout WHERE status='완료'"); wc = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM user_coupon'); cc = cursor.fetchone()[0]
    cursor.execute('''SELECT e.name, e.body_part, COUNT(mu.id) c
                      FROM exercise e LEFT JOIN machine_use mu ON mu.exercise_id=e.id
                      GROUP BY e.id ORDER BY c DESC LIMIT 5''')
    popular = cursor.fetchall()
    conn.close()
    return render_template('admin/dashboard.html', uc=uc, ec=ec, wc=wc, cc=cc,
                           popular=popular)


@app.route('/admin/exercises/')
def admin_exercises():
    g = admin_guard()
    if g:
        return g
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM exercise ORDER BY body_part, is_machine DESC, id')
    rows = cursor.fetchall()
    conn.close()
    return render_template('admin/exercises.html', rows=rows,
                           body_parts=BODY_PARTS, levels=LEVELS)


@app.route('/admin/exercises/add/', methods=['POST'])
def admin_exercise_add():
    g = admin_guard()
    if g:
        return g
    f = request.form
    conn, cursor = get_db()
    cursor.execute('''INSERT INTO exercise
        (name, body_part, primary_target, secondary_target, equipment,
         is_machine, difficulty, prep, execution, tips)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (f.get('name'), f.get('body_part'), f.get('primary_target', ''),
         f.get('secondary_target', ''), f.get('equipment', ''),
         1 if to_int(f.get('is_machine'), 1) else 0, f.get('difficulty', '초급'),
         f.get('prep', ''), f.get('execution', ''), f.get('tips', '')))
    conn.commit()
    conn.close()
    return redirect('/admin/exercises/')


@app.route('/admin/exercises/<int:eid>/delete/', methods=['POST'])
def admin_exercise_delete(eid):
    g = admin_guard()
    if g:
        return g
    conn, cursor = get_db()
    cursor.execute('DELETE FROM exercise WHERE id=?', (eid,))
    conn.commit()
    conn.close()
    return redirect('/admin/exercises/')


@app.route('/admin/coupons/')
def admin_coupons():
    g = admin_guard()
    if g:
        return g
    conn, cursor = get_db()
    cursor.execute('''SELECT c.*, (SELECT COUNT(*) FROM user_coupon WHERE coupon_id=c.id)
                      FROM coupons c ORDER BY c.id''')
    coupons = cursor.fetchall()
    conn.close()
    return render_template('admin/coupons.html', coupons=coupons)


@app.route('/admin/coupons/add/', methods=['POST'])
def admin_coupon_add():
    g = admin_guard()
    if g:
        return g
    f = request.form
    conn, cursor = get_db()
    cursor.execute('''INSERT INTO coupons (partner_name, category, code, discount, condition, total_qty)
                      VALUES (?,?,?,?,?,?)''',
        (f.get('partner_name'), f.get('category', '프로틴'), f.get('code'),
         f.get('discount'), f.get('condition', '루틴 95% 이상 완료'),
         to_int(f.get('total_qty'), 50)))
    conn.commit()
    conn.close()
    return redirect('/admin/coupons/')


@app.route('/admin/coupons/<int:cid>/delete/', methods=['POST'])
def admin_coupon_delete(cid):
    g = admin_guard()
    if g:
        return g
    conn, cursor = get_db()
    cursor.execute('DELETE FROM coupons WHERE id=?', (cid,))
    conn.commit()
    conn.close()
    return redirect('/admin/coupons/')


@app.route('/admin/users/')
def admin_users():
    g = admin_guard()
    if g:
        return g
    conn, cursor = get_db()
    cursor.execute('''SELECT id, login_id, name, gender, goal, fitness_level, role FROM users
                      ORDER BY id''')
    users = cursor.fetchall()
    conn.close()
    return render_template('admin/users.html', users=users)


@app.route('/admin/users/<int:uid>/delete/', methods=['POST'])
def admin_user_delete(uid):
    g = admin_guard()
    if g:
        return g
    if uid == session['user_id']:
        return redirect('/admin/users/')
    conn, cursor = get_db()
    cursor.execute('DELETE FROM users WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    return redirect('/admin/users/')


# ─── 실행 ───
init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
