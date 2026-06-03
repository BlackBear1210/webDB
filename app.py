# ════════════════════════════════════════════════════════════════════
#  FitQR - 스마트 짐 운동 트래커  (웹DB 기말 프로젝트)
# --------------------------------------------------------------------
#  - 기술스택 : Flask(파이썬) + SQLite(DB) + Jinja2(HTML 템플릿)
#  - 핵심기능 : ① QR 운동기록 ② 건강진단 ③ 추천 루틴/식단 ④ 보상쿠폰
#  - 파일구조 : app.py(이 파일=메인) / templates(화면) / static(CSS·JS·이미지)
#  - 코드순서 : DB설정 → 0단계(DB) → 1~5단계 라우트 → 실행
# ════════════════════════════════════════════════════════════════════

# ── 외부 라이브러리 불러오기 ──
from flask import Flask, request, redirect, render_template, session, url_for, send_file
import sqlite3              # SQLite DB 사용
from datetime import datetime  # 날짜/시간 기록용
import qrcode              # QR 이미지 생성 (3단계)
import io                  # QR을 파일 저장 없이 메모리에서 다루기 위함
import random             # 보상 쿠폰 무작위 지급 (5단계)
import os                 # DB 파일 경로를 절대경로로 잡기 위함

# ── Flask 앱 생성 ──
app = Flask(__name__)
app.secret_key = 'fitqr_secret_2026'   # session(로그인 상태)을 암호화하는 비밀키 (필수)

# DB 파일은 이 app.py와 같은 폴더에 둔다 (실행 위치와 상관없이 항상 같은 DB 사용)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fitqr.db')

# ─── DB 연결 함수 ──────────────────────────────────────
# fitqr.db 파일에 연결하고, 명령을 내릴 cursor(커서)를 같이 돌려준다.
# 모든 라우트에서 conn, cursor = get_db() 형태로 재사용한다.
def get_db():
    conn = sqlite3.connect(DB_PATH)      # DB 파일 연결 (없으면 자동 생성)
    cursor = conn.cursor()               # SQL 명령을 실행할 커서
    return conn, cursor

# ─── DB 초기화 (테이블 12개 + 시드 데이터) ─────────────
def init_db():
    conn, cursor = get_db()

    # 1. 회원
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        login_id    TEXT UNIQUE,
        password    TEXT,
        name        TEXT,
        gender      TEXT,
        age         INTEGER,
        height      REAL,
        weight      REAL,
        role        TEXT DEFAULT 'user'
    )''')

    # 2. 건강 프로필 (회원과 1:1)
    cursor.execute('''CREATE TABLE IF NOT EXISTS health_profile (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER UNIQUE,
        squat_1rm       REAL DEFAULT 0,
        bench_1rm       REAL DEFAULT 0,
        deadlift_1rm    REAL DEFAULT 0,
        diseases        TEXT DEFAULT '',
        surgery_history TEXT DEFAULT '',
        sleep_hours     REAL DEFAULT 7,
        activity_level  TEXT DEFAULT '보통',
        goal            TEXT DEFAULT '근성장',
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # 3. 운동 기구
    cursor.execute('''CREATE TABLE IF NOT EXISTS machines (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT,
        body_part       TEXT,
        min_valid_rom   INTEGER DEFAULT 10,
        description     TEXT,
        qr_url          TEXT
    )''')

    # 4. 운동 세션 (기구별 운동 기록 헤더)
    cursor.execute('''CREATE TABLE IF NOT EXISTS workout_session (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        machine_id  INTEGER,
        weight      REAL,
        target_sets INTEGER DEFAULT 3,
        started_at  TEXT,
        ended_at    TEXT,
        status      TEXT DEFAULT '진행중',
        FOREIGN KEY (user_id)    REFERENCES users(id),
        FOREIGN KEY (machine_id) REFERENCES machines(id)
    )''')

    # 5. 세트별 기록
    cursor.execute('''CREATE TABLE IF NOT EXISTS set_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  INTEGER,
        set_number  INTEGER,
        reps        INTEGER DEFAULT 0,
        weight      REAL,
        is_valid    INTEGER DEFAULT 1,
        FOREIGN KEY (session_id) REFERENCES workout_session(id)
    )''')

    # 6. 추천용 운동 마스터
    cursor.execute('''CREATE TABLE IF NOT EXISTS exercise_master (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT,
        body_part       TEXT,
        type            TEXT DEFAULT '일반',
        target_disease  TEXT DEFAULT '',
        goal            TEXT DEFAULT '',
        description     TEXT DEFAULT ''
    )''')

    # 7. 추천 루틴 헤더
    cursor.execute('''CREATE TABLE IF NOT EXISTS routine (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER,
        goal            TEXT,
        created_at      TEXT,
        status          TEXT DEFAULT '진행중',
        completion_rate REAL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # 8. 루틴 구성 운동 (루틴과 1:N)
    cursor.execute('''CREATE TABLE IF NOT EXISTS routine_item (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        routine_id      INTEGER,
        exercise_id     INTEGER,
        target_sets     INTEGER DEFAULT 3,
        target_reps     INTEGER DEFAULT 10,
        target_weight   REAL DEFAULT 0,
        is_done         INTEGER DEFAULT 0,
        FOREIGN KEY (routine_id)  REFERENCES routine(id),
        FOREIGN KEY (exercise_id) REFERENCES exercise_master(id)
    )''')

    # 9. 추천 식단 헤더
    cursor.execute('''CREATE TABLE IF NOT EXISTS diet_plan (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        goal        TEXT,
        target_kcal INTEGER,
        protein_g   REAL,
        carb_g      REAL,
        fat_g       REAL,
        created_at  TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # 10. 식단 구성 메뉴 (식단과 1:N)
    cursor.execute('''CREATE TABLE IF NOT EXISTS diet_item (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        diet_plan_id INTEGER,
        meal_time   TEXT,
        menu        TEXT,
        kcal        INTEGER,
        protein_g   REAL,
        FOREIGN KEY (diet_plan_id) REFERENCES diet_plan(id)
    )''')

    # 11. 할인 쿠폰 마스터
    cursor.execute('''CREATE TABLE IF NOT EXISTS coupons (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        partner_name TEXT,
        category     TEXT,
        code         TEXT,
        discount     TEXT,
        condition    TEXT,
        total_qty    INTEGER DEFAULT 100
    )''')

    # 12. 지급된 쿠폰 (회원과 1:N)
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_coupon (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        coupon_id   INTEGER,
        issued_at   TEXT,
        is_used     INTEGER DEFAULT 0,
        FOREIGN KEY (user_id)   REFERENCES users(id),
        FOREIGN KEY (coupon_id) REFERENCES coupons(id)
    )''')

    conn.commit()

    # ── 시드 데이터 ─────────────────────────────────────

    # 관리자 계정 자동 생성 (최초 1회)
    cursor.execute('SELECT COUNT(*) FROM users')
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO users (login_id, password, name, gender, age, height, weight, role) VALUES (?,?,?,?,?,?,?,?)",
            ('admin', '1234', '관리자', '남', 25, 175.0, 75.0, 'admin')
        )

    # 운동 기구 시드 (최초 1회)
    cursor.execute('SELECT COUNT(*) FROM machines')
    if cursor.fetchone()[0] == 0:
        machines_seed = [
            ('랫풀다운',    '등',   15, '광배근을 발달시키는 기구. 바를 가슴 위까지 당기세요.'),
            ('체스트프레스', '가슴',  10, '대흉근을 발달시키는 기구. 팔꿈치를 90도로 유지하세요.'),
            ('레그프레스',   '하체',  20, '대퇴사두근/햄스트링을 발달시키는 기구.'),
            ('숄더프레스',   '어깨',  10, '삼각근을 발달시키는 기구.'),
            ('케이블로우',   '등',   15, '중하부 등 근육을 발달시키는 기구.'),
            ('레그컬',      '하체',  20, '햄스트링을 발달시키는 기구.'),
            ('펙덱플라이',   '가슴',  10, '대흉근 안쪽을 발달시키는 기구.'),
            ('트라이셉스',   '팔',   10, '삼두근을 발달시키는 기구.'),
        ]
        for m in machines_seed:
            cursor.execute(
                'INSERT INTO machines (name, body_part, min_valid_rom, description) VALUES (?,?,?,?)',
                m
            )
        # QR URL 업데이트 (나중에 실제 배포 주소로 변경)
        cursor.execute('UPDATE machines SET qr_url = "/machine/" || id')

    # 운동 마스터 시드 (최초 1회)
    cursor.execute('SELECT COUNT(*) FROM exercise_master')
    if cursor.fetchone()[0] == 0:
        exercises_seed = [
            # (name, body_part, type, target_disease, goal, description)
            # 일반 - 살빼기
            ('버피테스트',    '전신', '일반', '', '살빼기',  '전신 유산소 운동'),
            ('케틀벨스윙',    '전신', '일반', '', '살빼기',  '심폐지구력 향상'),
            ('점핑잭',        '전신', '일반', '', '살빼기',  '간단한 유산소 운동'),
            ('마운틴클라이머', '코어', '일반', '', '살빼기',  '코어+유산소'),
            ('줄넘기',        '전신', '일반', '', '살빼기',  '유산소 운동'),
            # 일반 - 근성장
            ('벤치프레스',    '가슴', '일반', '', '근성장',  '가슴 근육 발달'),
            ('스쿼트',        '하체', '일반', '', '근성장',  '하체 근육 발달'),
            ('데드리프트',    '등',   '일반', '', '근성장',  '전신 근력 향상'),
            ('바벨로우',      '등',   '일반', '', '근성장',  '등 근육 발달'),
            ('오버헤드프레스', '어깨', '일반', '', '근성장',  '어깨 근육 발달'),
            # 일반 - 벌크업
            ('바벨스쿼트',    '하체', '일반', '', '벌크업',  '고중량 하체 운동'),
            ('딥스',          '가슴', '일반', '', '벌크업',  '가슴/삼두 복합 운동'),
            ('바벨컬',        '팔',   '일반', '', '벌크업',  '이두근 발달'),
            ('풀업',          '등',   '일반', '', '벌크업',  '등+이두 복합 운동'),
            ('인클라인프레스', '가슴', '일반', '', '벌크업',  '상부 가슴 발달'),
            # 재활 - 허리
            ('맥켄지운동',    '허리', '재활', '허리디스크', '', '허리 신전 재활 운동'),
            ('버드독',        '코어', '재활', '허리디스크', '', '척추 안정화 운동'),
            ('데드버그',      '코어', '재활', '허리디스크', '', '코어 안정화 운동'),
            ('고양이소운동',  '허리', '재활', '허리디스크', '', '허리 유연성 향상'),
            # 재활 - 무릎
            ('레그레이즈',    '하체', '재활', '무릎', '', '무릎 재활 운동'),
            ('직다리올리기',  '하체', '재활', '무릎', '', '대퇴사두근 강화'),
            ('클램쉘',        '엉덩이','재활','무릎', '', '엉덩이 근육 강화'),
            # 재활 - 어깨
            ('밴드외회전',    '어깨', '재활', '어깨', '', '회전근개 강화'),
            ('월슬라이드',    '어깨', '재활', '어깨', '', '어깨 가동범위 회복'),
            ('펜듈럼운동',    '어깨', '재활', '어깨', '', '어깨 재활 기본 운동'),
        ]
        for e in exercises_seed:
            cursor.execute(
                'INSERT INTO exercise_master (name, body_part, type, target_disease, goal, description) VALUES (?,?,?,?,?,?)',
                e
            )

    # 쿠폰 시드 (최초 1회)
    cursor.execute('SELECT COUNT(*) FROM coupons')
    if cursor.fetchone()[0] == 0:
        coupons_seed = [
            ('마이프로틴',   '프로틴',   'FITQR-MYP20', '20% 할인', '루틴 100% 완료', 50),
            ('나이키',       '운동용품', 'FITQR-NK15',  '15% 할인', '루틴 100% 완료', 50),
            ('언더아머',     '운동용품', 'FITQR-UA10',  '10% 할인', '루틴 100% 완료', 50),
            ('GNC',          '프로틴',   'FITQR-GNC25', '25% 할인', '루틴 100% 완료', 30),
            ('뉴발란스',     '운동용품', 'FITQR-NB10',  '10% 할인', '루틴 100% 완료', 50),
        ]
        for c in coupons_seed:
            cursor.execute(
                'INSERT INTO coupons (partner_name, category, code, discount, condition, total_qty) VALUES (?,?,?,?,?,?)',
                c
            )

    conn.commit()
    conn.close()
    print("[FitQR] DB init done (12 tables + seed data)")

init_db()


# ════════════════════════════════════════════════════════════════════
#  📌 컬럼 인덱스 참고표  (★ 코드 읽을 때 꼭 보세요)
# --------------------------------------------------------------------
#  cursor.fetchone() 은 한 줄을 (값1, 값2, ...) 튜플로 돌려준다.
#  그래서 user[0], ws[1] 처럼 "번호"로 값을 꺼낸다. 번호 = 아래 순서.
#
#  users          : 0=id 1=login_id 2=password 3=name 4=gender
#                   5=age 6=height 7=weight 8=role
#  health_profile : 0=id 1=user_id 2=squat 3=bench 4=deadlift
#                   5=diseases 6=surgery_history 7=sleep_hours 8=activity_level 9=goal
#  machines       : 0=id 1=name 2=body_part 3=min_valid_rom 4=description 5=qr_url
#  workout_session: 0=id 1=user_id 2=machine_id 3=weight 4=target_sets
#                   5=started_at 6=ended_at 7=status
#  set_log        : 0=id 1=session_id 2=set_number 3=reps 4=weight 5=is_valid
#  exercise_master: 0=id 1=name 2=body_part 3=type 4=target_disease 5=goal 6=description
#  routine        : 0=id 1=user_id 2=goal 3=created_at 4=status 5=completion_rate
#  routine_item   : 0=id 1=routine_id 2=exercise_id 3=target_sets 4=target_reps
#                   5=target_weight 6=is_done
#  diet_plan      : 0=id 1=user_id 2=goal 3=target_kcal 4=protein_g 5=carb_g 6=fat_g 7=created_at
#  diet_item      : 0=id 1=diet_plan_id 2=meal_time 3=menu 4=kcal 5=protein_g
#  coupons        : 0=id 1=partner_name 2=category 3=code 4=discount 5=condition 6=total_qty
#  user_coupon    : 0=id 1=user_id 2=coupon_id 3=issued_at 4=is_used
# ════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════
#  1단계 : 회원가입 / 로그인 / 로그아웃
#  - session(브라우저별 저장공간)에 로그인 정보를 담아 상태를 유지한다.
#  - 로그인 안 한 사용자는 모든 페이지에서 /login/ 으로 쫓아낸다.
# ════════════════════════════════════════════════════════════════════

# ─── 메인 (대시보드) ───────────────────────────────────
# 로그인 후 보이는 첫 화면. 기능 메뉴(운동/기록/추천/보상)로 가는 입구.
@app.route('/')
def index():
    # 로그인 안 했으면(=session에 user_id 없으면) 로그인 페이지로
    if 'user_id' not in session:
        return redirect('/login/')
    return render_template('index.html')


# ─── 회원가입 ──────────────────────────────────────────
# GET  → 빈 가입 폼 보여주기
# POST → 입력값 받아서 users 테이블에 저장
@app.route('/register/', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':   # 폼 제출(가입 버튼)일 때
        # 입력값 꺼내기 (request.form['이름'] = 폼의 name 속성)
        login_id = request.form['login_id']
        password = request.form['password']
        name     = request.form['name']
        gender   = request.form['gender']
        # 숫자 항목은 빈 값이 들어와도 오류 안 나도록 안전 변환
        age    = int(request.form['age'])    if request.form.get('age')    else 0
        height = float(request.form['height']) if request.form.get('height') else 0
        weight = float(request.form['weight']) if request.form.get('weight') else 0

        conn, cursor = get_db()

        # 아이디 중복 확인
        cursor.execute('SELECT * FROM users WHERE login_id = ?', (login_id,))
        if cursor.fetchone():
            conn.close()
            return render_template('register.html',
                                   error='이미 존재하는 아이디입니다.', success='')

        # 회원 등록
        cursor.execute(
            '''INSERT INTO users (login_id, password, name, gender, age, height, weight, role)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'user')''',
            (login_id, password, name, gender, age, height, weight)
        )
        conn.commit()
        conn.close()

        return render_template('register.html',
                               error='', success='회원가입을 축하합니다! 로그인 해주세요.')

    # GET → 빈 폼
    return render_template('register.html', error='', success='')


# ─── 로그인 ────────────────────────────────────────────
@app.route('/login/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_id = request.form['login_id']
        password = request.form['password']

        conn, cursor = get_db()
        cursor.execute('SELECT * FROM users WHERE login_id = ? AND password = ?',
                       (login_id, password))
        user = cursor.fetchone()
        conn.close()

        if user:
            # user 인덱스: 0=id 1=login_id 2=password 3=name 4=gender
            #             5=age 6=height 7=weight 8=role
            session['user_id']  = user[0]
            session['login_id'] = user[1]
            session['name']     = user[3]
            session['role']     = user[8]
            return redirect('/')
        else:
            return render_template('login.html',
                                   error='아이디 또는 비밀번호가 틀렸습니다.')

    # GET → 빈 폼
    return render_template('login.html', error='')


# ─── 로그아웃 ──────────────────────────────────────────
@app.route('/logout/')
def logout():
    session.clear()
    return redirect('/login/')


# ════════════════════════════════════════════════════════════════════
#  2단계 : QR 운동 흐름  (이 프로젝트의 핵심)
#  흐름 : 기구목록 → 기구선택(QR진입) → 무게설정 → 운동시작(세션생성)
#         → Rep 카운트 → 세트완료(저장) → 종목종료 → 요약
#  테이블: workout_session(운동 1회) , set_log(그 안의 세트들)
# ════════════════════════════════════════════════════════════════════

# ─── 기구 목록 (QR 스캔 대신 클릭으로도 진입 가능) ─────
@app.route('/machines/')
def machines():
    if 'user_id' not in session:
        return redirect('/login/')
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM machines ORDER BY id')
    machine_list = cursor.fetchall()
    conn.close()
    return render_template('machines.html', machines=machine_list)


# ─── 기구 상세 (QR 스캔 진입점) ───────────────────────
@app.route('/machine/<int:id>/')
def machine(id):
    if 'user_id' not in session:
        return redirect('/login/')
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM machines WHERE id = ?', (id,))
    m = cursor.fetchone()
    conn.close()
    if not m:                       # 없는 기구 번호로 접근하면 목록으로
        return redirect('/machines/')
    return render_template('machine.html', m=m)


# ─── 운동 시작 (세션 생성) ────────────────────────────
@app.route('/machine/<int:id>/start/', methods=['POST'])
def machine_start(id):
    if 'user_id' not in session:
        return redirect('/login/')
    weight      = float(request.form['weight'])    if request.form.get('weight')    else 0
    target_sets = int(request.form['target_sets']) if request.form.get('target_sets') else 3
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn, cursor = get_db()
    cursor.execute(
        '''INSERT INTO workout_session (user_id, machine_id, weight, target_sets, started_at, status)
           VALUES (?, ?, ?, ?, ?, '진행중')''',
        (session['user_id'], id, weight, target_sets, now)
    )
    session_id = cursor.lastrowid   # 방금 만든 세션 번호
    conn.commit()
    conn.close()
    return redirect(f'/workout/{session_id}/')


# ─── 운동 진행 화면 (Rep 카운트) ──────────────────────
@app.route('/workout/<int:session_id>/')
def workout(session_id):
    if 'user_id' not in session:
        return redirect('/login/')
    conn, cursor = get_db()
    cursor.execute('''SELECT ws.*, m.name, m.body_part, m.min_valid_rom
                      FROM workout_session ws
                      JOIN machines m ON ws.machine_id = m.id
                      WHERE ws.id = ?''', (session_id,))
    ws = cursor.fetchone()
    # 없는 세션이거나 남의 세션이면 차단
    if not ws or ws[1] != session['user_id']:
        conn.close()
        return redirect('/machines/')
    # 이미 끝난 운동이면 요약으로
    if ws[7] == '완료':
        conn.close()
        return redirect(f'/workout/{session_id}/done/')
    # 지금까지 완료한 세트들
    cursor.execute('SELECT * FROM set_log WHERE session_id = ? ORDER BY set_number', (session_id,))
    sets = cursor.fetchall()
    conn.close()
    next_set = len(sets) + 1
    return render_template('workout.html', ws=ws, sets=sets, next_set=next_set)


# ─── 세트 완료 (set_log 저장) ─────────────────────────
@app.route('/workout/<int:session_id>/set/', methods=['POST'])
def workout_set(session_id):
    if 'user_id' not in session:
        return redirect('/login/')
    reps = int(request.form['reps']) if request.form.get('reps') else 0

    conn, cursor = get_db()
    cursor.execute('SELECT * FROM workout_session WHERE id = ?', (session_id,))
    ws = cursor.fetchone()
    if not ws or ws[1] != session['user_id']:
        conn.close()
        return redirect('/machines/')

    cursor.execute('SELECT COUNT(*) FROM set_log WHERE session_id = ?', (session_id,))
    set_number = cursor.fetchone()[0] + 1
    is_valid = 1 if reps > 0 else 0   # 유효 횟수가 있으면 정상 세트

    cursor.execute(
        '''INSERT INTO set_log (session_id, set_number, reps, weight, is_valid)
           VALUES (?, ?, ?, ?, ?)''',
        (session_id, set_number, reps, ws[3], is_valid)   # ws[3]=weight
    )
    conn.commit()
    conn.close()
    return redirect(f'/workout/{session_id}/')


# ─── 종목 종료 (세션 완료 처리) ───────────────────────
@app.route('/workout/<int:session_id>/end/', methods=['POST'])
def workout_end(session_id):
    if 'user_id' not in session:
        return redirect('/login/')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn, cursor = get_db()
    cursor.execute('SELECT * FROM workout_session WHERE id = ?', (session_id,))
    ws = cursor.fetchone()
    if not ws or ws[1] != session['user_id']:
        conn.close()
        return redirect('/machines/')
    cursor.execute("UPDATE workout_session SET status='완료', ended_at=? WHERE id=?",
                   (now, session_id))
    conn.commit()
    conn.close()
    return redirect(f'/workout/{session_id}/done/')


# ─── 운동 종료 요약 ───────────────────────────────────
@app.route('/workout/<int:session_id>/done/')
def workout_done(session_id):
    if 'user_id' not in session:
        return redirect('/login/')
    conn, cursor = get_db()
    cursor.execute('''SELECT ws.*, m.name, m.body_part
                      FROM workout_session ws
                      JOIN machines m ON ws.machine_id = m.id
                      WHERE ws.id = ?''', (session_id,))
    ws = cursor.fetchone()
    if not ws or ws[1] != session['user_id']:
        conn.close()
        return redirect('/machines/')
    cursor.execute('SELECT * FROM set_log WHERE session_id = ? ORDER BY set_number', (session_id,))
    sets = cursor.fetchall()
    conn.close()
    total_reps = sum(s[3] for s in sets)   # s[3]=reps
    return render_template('workout_done.html', ws=ws, sets=sets, total_reps=total_reps)


# ════════════════════════════════════════════════════════════════════
#  3단계 : 운동 기록 조회 + QR 이미지 생성 + 웹캠 스캔
#  - history     : 내가 한 운동을 모아서 통계와 함께 보여줌
#  - machine_qr  : 기구 URL을 QR 이미지(PNG)로 즉석 생성 (도메인 자동)
#  - scan        : 노트북 웹캠으로 그 QR을 읽어 운동화면으로 이동
# ════════════════════════════════════════════════════════════════════

# ─── 운동 기록 조회 ───────────────────────────────────
@app.route('/history/')
def history():
    if 'user_id' not in session:
        return redirect('/login/')
    conn, cursor = get_db()

    # 내 운동 세션 목록 (기구명 JOIN + 세트수/총횟수 집계)
    cursor.execute('''
        SELECT ws.id, m.name, m.body_part, ws.weight,
               ws.started_at, ws.status,
               (SELECT COUNT(*) FROM set_log WHERE session_id = ws.id),
               (SELECT COALESCE(SUM(reps), 0) FROM set_log WHERE session_id = ws.id)
        FROM workout_session ws
        JOIN machines m ON ws.machine_id = m.id
        WHERE ws.user_id = ?
        ORDER BY ws.id DESC
    ''', (session['user_id'],))
    sessions = cursor.fetchall()

    # 요약 통계
    cursor.execute('SELECT COUNT(*) FROM workout_session WHERE user_id = ?', (session['user_id'],))
    total_sessions = cursor.fetchone()[0]
    cursor.execute('''SELECT COALESCE(SUM(sl.reps), 0)
                      FROM set_log sl JOIN workout_session ws ON sl.session_id = ws.id
                      WHERE ws.user_id = ?''', (session['user_id'],))
    total_reps = cursor.fetchone()[0]
    conn.close()

    return render_template('history.html',
                           sessions=sessions,
                           total_sessions=total_sessions,
                           total_reps=total_reps)


# ─── QR 이미지 동적 생성 (도메인 자동) ────────────────
@app.route('/machine/<int:id>/qr.png')
def machine_qr(id):
    # 현재 호스트 기준으로 기구 URL 자동 생성 (로컬/배포 자동 대응)
    url = url_for('machine', id=id, _external=True)
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


# ─── 기구 QR 모아보기 (인쇄/시연용) ───────────────────
@app.route('/qrcodes/')
def qrcodes():
    if 'user_id' not in session:
        return redirect('/login/')
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM machines ORDER BY id')
    machine_list = cursor.fetchall()
    conn.close()
    return render_template('qrcodes.html', machines=machine_list)


# ─── 웹캠 QR 스캔 ──────────────────────────────────────
@app.route('/scan/')
def scan():
    if 'user_id' not in session:
        return redirect('/login/')
    return render_template('scan.html')


# ════════════════════════════════════════════════════════════════════
#  4단계 : 건강 진단 + 추천 루틴/식단  (규칙 기반 = AI 아님, 공식+조건문)
#  흐름 : 진단입력(profile) → 추천생성(generate) → 결과보기(recommend)
#  로직 : 지병/수술 있으면 → 재활 루틴 / 없으면 → 목표별 일반 루틴
#         + 키·몸무게·나이로 칼로리 계산해서 식단 생성
# ════════════════════════════════════════════════════════════════════

# ─── 추천 엔진 헬퍼 함수 3개 (라우트에서 호출) ────────

def pick_rehab_exercises(cursor, condition):
    """지병/수술 내용(condition)에 맞는 재활 운동 선택"""
    cursor.execute("SELECT * FROM exercise_master WHERE type = '재활'")
    all_rehab = cursor.fetchall()
    picked = []
    for e in all_rehab:
        target = e[4]   # target_disease
        if (('허리' in condition and '허리' in target) or
            ('무릎' in condition and '무릎' in target) or
            ('어깨' in condition and '어깨' in target)):
            picked.append(e)
    if not picked:          # 매칭되는 게 없으면 기본 재활 운동
        picked = all_rehab[:4]
    return picked[:5]


def build_meals(goal, kcal, protein):
    """목표·칼로리에 맞춘 끼니별 식단 구성"""
    ratios = [('아침', 0.25), ('점심', 0.35), ('저녁', 0.30), ('간식', 0.10)]
    menus = {
        '살빼기': ['닭가슴살 샐러드 + 삶은 계란', '현미밥 + 생선구이 + 나물',
                  '두부김치 + 야채쌈', '그릭요거트 + 견과류'],
        '근성장': ['오트밀 + 바나나 + 계란', '닭가슴살 + 고구마 + 브로콜리',
                  '소고기 + 현미밥 + 샐러드', '프로틴 쉐이크'],
        '벌크업': ['계란 5개 + 토스트 + 우유', '제육볶음 + 공기밥 2 + 된장국',
                  '연어 스테이크 + 파스타', '프로틴 쉐이크 + 바나나 2개'],
    }.get(goal, ['오트밀 + 계란', '닭가슴살 + 밥 + 야채', '소고기 + 샐러드', '프로틴 쉐이크'])

    meals = []
    for (meal_time, ratio), menu in zip(ratios, menus):
        meals.append((meal_time, menu, int(round(kcal * ratio)), int(round(protein * ratio))))
    return meals


def calc_diet(user, profile):
    """BMR(Mifflin-St Jeor) → TDEE → 목표별 칼로리/매크로 계산"""
    gender = user[4]
    age    = user[5] or 25
    height = user[6] or 170
    weight = user[7] or 70
    activity = profile[8]
    goal     = profile[9]

    # 기초대사량 (Mifflin-St Jeor)
    bmr = 10 * weight + 6.25 * height - 5 * age + (5 if gender == '남' else -161)
    # 활동량 계수
    factor = {'좌식': 1.2, '보통': 1.55, '활발': 1.725}.get(activity, 1.55)
    tdee = bmr * factor
    # 목표별 가감
    adjust = {'살빼기': -400, '근성장': 0, '벌크업': 400}.get(goal, 0)
    kcal = int(round(tdee + adjust))

    # 매크로 (단백질·지방·탄수)
    protein = int(round(weight * (2.0 if goal == '살빼기' else 1.6)))
    fat     = int(round(kcal * 0.25 / 9))
    carb    = int(round((kcal - protein * 4 - fat * 9) / 4))
    if carb < 0:
        carb = 0

    return {'kcal': kcal, 'protein': protein, 'carb': carb, 'fat': fat,
            'meals': build_meals(goal, kcal, protein)}


# ─── 건강 진단 입력 ───────────────────────────────────
@app.route('/profile/', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()

    if request.method == 'POST':
        squat    = float(request.form['squat'])    if request.form.get('squat')    else 0
        bench    = float(request.form['bench'])    if request.form.get('bench')    else 0
        deadlift = float(request.form['deadlift']) if request.form.get('deadlift') else 0
        diseases        = request.form.get('diseases', '')
        surgery_history = request.form.get('surgery_history', '')
        sleep_hours     = float(request.form['sleep_hours']) if request.form.get('sleep_hours') else 7
        activity_level  = request.form.get('activity_level', '보통')
        goal            = request.form.get('goal', '근성장')

        # upsert: 있으면 UPDATE, 없으면 INSERT
        cursor.execute('SELECT id FROM health_profile WHERE user_id = ?', (uid,))
        if cursor.fetchone():
            cursor.execute('''UPDATE health_profile SET
                squat_1rm=?, bench_1rm=?, deadlift_1rm=?, diseases=?, surgery_history=?,
                sleep_hours=?, activity_level=?, goal=? WHERE user_id=?''',
                (squat, bench, deadlift, diseases, surgery_history,
                 sleep_hours, activity_level, goal, uid))
        else:
            cursor.execute('''INSERT INTO health_profile
                (user_id, squat_1rm, bench_1rm, deadlift_1rm, diseases, surgery_history,
                 sleep_hours, activity_level, goal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (uid, squat, bench, deadlift, diseases, surgery_history,
                 sleep_hours, activity_level, goal))
        conn.commit()
        conn.close()
        return redirect('/recommend/')

    cursor.execute('SELECT * FROM health_profile WHERE user_id = ?', (uid,))
    p = cursor.fetchone()
    conn.close()
    return render_template('profile.html', p=p)


# ─── 추천 결과 보기 ───────────────────────────────────
@app.route('/recommend/')
def recommend():
    if 'user_id' not in session:
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()

    cursor.execute('SELECT * FROM health_profile WHERE user_id = ?', (uid,))
    p = cursor.fetchone()
    if not p:                          # 진단 먼저 받게
        conn.close()
        return redirect('/profile/')

    # 최신 루틴 + 구성 운동
    cursor.execute('SELECT * FROM routine WHERE user_id = ? ORDER BY id DESC LIMIT 1', (uid,))
    routine = cursor.fetchone()
    routine_items = []
    if routine:
        cursor.execute('''SELECT ri.*, em.name, em.body_part, em.type, em.description
                          FROM routine_item ri JOIN exercise_master em ON ri.exercise_id = em.id
                          WHERE ri.routine_id = ? ORDER BY ri.id''', (routine[0],))
        routine_items = cursor.fetchall()

    # 최신 식단 + 끼니
    cursor.execute('SELECT * FROM diet_plan WHERE user_id = ? ORDER BY id DESC LIMIT 1', (uid,))
    diet = cursor.fetchone()
    diet_items = []
    if diet:
        cursor.execute('SELECT * FROM diet_item WHERE diet_plan_id = ? ORDER BY id', (diet[0],))
        diet_items = cursor.fetchall()
    conn.close()

    is_rehab = bool((p[5] or '').strip() or (p[6] or '').strip())
    return render_template('recommend.html', p=p,
                           routine=routine, routine_items=routine_items,
                           diet=diet, diet_items=diet_items, is_rehab=is_rehab)


# ─── 추천 생성 (루틴 + 식단) ──────────────────────────
@app.route('/recommend/generate/', methods=['POST'])
def recommend_generate():
    if 'user_id' not in session:
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()

    cursor.execute('SELECT * FROM users WHERE id = ?', (uid,))
    user = cursor.fetchone()
    cursor.execute('SELECT * FROM health_profile WHERE user_id = ?', (uid,))
    p = cursor.fetchone()
    if not p:
        conn.close()
        return redirect('/profile/')

    # 기존 추천 삭제 (활성 추천 1개만 유지)
    cursor.execute('SELECT id FROM routine WHERE user_id = ?', (uid,))
    for (rid,) in cursor.fetchall():
        cursor.execute('DELETE FROM routine_item WHERE routine_id = ?', (rid,))
    cursor.execute('DELETE FROM routine WHERE user_id = ?', (uid,))
    cursor.execute('SELECT id FROM diet_plan WHERE user_id = ?', (uid,))
    for (did,) in cursor.fetchall():
        cursor.execute('DELETE FROM diet_item WHERE diet_plan_id = ?', (did,))
    cursor.execute('DELETE FROM diet_plan WHERE user_id = ?', (uid,))

    goal = p[9]
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # ── 루틴 생성: 재활 vs 일반 ──
    condition = ((p[5] or '') + ' ' + (p[6] or '')).strip()
    if condition:   # 지병/수술 이력 있음 → 재활 루틴
        exercises = pick_rehab_exercises(cursor, condition)
        reps, sets = 12, 3
    else:           # 건강함 → 목표별 일반 루틴
        cursor.execute("SELECT * FROM exercise_master WHERE type = '일반' AND goal = ?", (goal,))
        exercises = cursor.fetchall()[:5]
        reps = {'살빼기': 15, '근성장': 10, '벌크업': 6}.get(goal, 10)
        sets = 3

    cursor.execute('''INSERT INTO routine (user_id, goal, created_at, status, completion_rate)
                      VALUES (?, ?, ?, '진행중', 0)''', (uid, goal, now))
    rid = cursor.lastrowid
    for e in exercises:
        cursor.execute('''INSERT INTO routine_item
            (routine_id, exercise_id, target_sets, target_reps, target_weight, is_done)
            VALUES (?, ?, ?, ?, 0, 0)''', (rid, e[0], sets, reps))

    # ── 식단 생성 ──
    d = calc_diet(user, p)
    cursor.execute('''INSERT INTO diet_plan (user_id, goal, target_kcal, protein_g, carb_g, fat_g, created_at)
                      VALUES (?, ?, ?, ?, ?, ?, ?)''',
                   (uid, goal, d['kcal'], d['protein'], d['carb'], d['fat'], now))
    did = cursor.lastrowid
    for meal in d['meals']:
        cursor.execute('''INSERT INTO diet_item (diet_plan_id, meal_time, menu, kcal, protein_g)
                          VALUES (?, ?, ?, ?, ?)''', (did, meal[0], meal[1], meal[2], meal[3]))

    conn.commit()
    conn.close()
    return redirect('/recommend/')


# ════════════════════════════════════════════════════════════════════
#  5단계 : 루틴 완료 → 보상 쿠폰 지급  (동기부여 + 발표 하이라이트)
#  흐름 : 추천 운동을 하나씩 [완료] → 완료율 100% 도달 시 쿠폰 자동 지급
#  테이블: coupons(쿠폰 종류·재고) , user_coupon(누가 무슨 쿠폰 받았는지)
# ════════════════════════════════════════════════════════════════════

# ─── 루틴 운동 1개 완료 처리 ──────────────────────────
# 운동 옆 [완료] 버튼을 누르면 호출. 완료율을 다시 계산하고,
# 100%가 되는 순간 보상 쿠폰을 1개 지급한다.
@app.route('/routine/item/<int:item_id>/done/', methods=['POST'])
def routine_item_done(item_id):
    if 'user_id' not in session:
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()

    # 이 항목이 내 루틴인지 확인
    cursor.execute('''SELECT ri.id, ri.routine_id, r.user_id, r.status
                      FROM routine_item ri JOIN routine r ON ri.routine_id = r.id
                      WHERE ri.id = ?''', (item_id,))
    row = cursor.fetchone()
    if not row or row[2] != uid:
        conn.close()
        return redirect('/recommend/')
    routine_id = row[1]
    routine_status = row[3]

    # 완료 처리
    cursor.execute('UPDATE routine_item SET is_done = 1 WHERE id = ?', (item_id,))

    # 완료율 재계산
    cursor.execute('SELECT COUNT(*) FROM routine_item WHERE routine_id = ?', (routine_id,))
    total = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM routine_item WHERE routine_id = ? AND is_done = 1', (routine_id,))
    done = cursor.fetchone()[0]
    rate = round(done / total * 100) if total else 0
    cursor.execute('UPDATE routine SET completion_rate = ? WHERE id = ?', (rate, routine_id))

    # 100% 달성 + 아직 보상 안 줬으면 → 쿠폰 지급 🎁
    new_reward = False
    if rate == 100 and routine_status != '완료':
        cursor.execute("UPDATE routine SET status = '완료' WHERE id = ?", (routine_id,))
        cursor.execute('SELECT * FROM coupons WHERE total_qty > 0')
        available = cursor.fetchall()
        if available:
            c = random.choice(available)            # 남은 쿠폰 중 무작위 지급
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute('''INSERT INTO user_coupon (user_id, coupon_id, issued_at, is_used)
                              VALUES (?, ?, ?, 0)''', (uid, c[0], now))
            session['new_reward'] = cursor.lastrowid
            cursor.execute('UPDATE coupons SET total_qty = total_qty - 1 WHERE id = ?', (c[0],))
            new_reward = True

    conn.commit()
    conn.close()
    # 보상 받았으면 보상함으로 (축하 화면), 아니면 추천으로
    return redirect('/my-rewards/' if new_reward else '/recommend/')


# ─── 내 보상함 ────────────────────────────────────────
@app.route('/my-rewards/')
def my_rewards():
    if 'user_id' not in session:
        return redirect('/login/')
    uid = session['user_id']
    conn, cursor = get_db()
    cursor.execute('''SELECT uc.id, c.partner_name, c.category, c.code, c.discount, uc.issued_at, uc.is_used
                      FROM user_coupon uc JOIN coupons c ON uc.coupon_id = c.id
                      WHERE uc.user_id = ? ORDER BY uc.id DESC''', (uid,))
    coupons = cursor.fetchall()
    conn.close()
    new_reward = session.pop('new_reward', None)   # 방금 받은 쿠폰 강조용 (1회성)
    return render_template('my_rewards.html', coupons=coupons, new_reward=new_reward)


# ════════════════════════════════════════════════════════════════════
#  관리자 페이지  (role='admin' 인 사람만 접근 가능)
#  - 통계 / 회원관리 / 기구관리(CRUD) / 쿠폰관리(CRUD)
#  - 모든 라우트 맨 앞에서 "로그인 + 관리자"를 이중 확인한다.
#    (주소창에 /admin/ 직접 입력해도 일반 회원은 못 들어오게)
# ════════════════════════════════════════════════════════════════════

# ─── 관리자 통계 대시보드 ─────────────────────────────
@app.route('/admin/')
def admin():
    if 'user_id' not in session:          # 로그인 안 했으면 로그인으로
        return redirect('/login/')
    if session.get('role') != 'admin':    # 관리자 아니면 메인으로 (이중 차단)
        return redirect('/')

    conn, cursor = get_db()
    # 전체 집계 (COUNT)
    cursor.execute('SELECT COUNT(*) FROM users');           user_count    = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM machines');        machine_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM workout_session'); session_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM routine');         routine_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM user_coupon');     coupon_count  = cursor.fetchone()[0]

    # 인기 기구 TOP 5 (운동 세션 많은 순) — LEFT JOIN + GROUP BY
    cursor.execute('''SELECT m.name, m.body_part, COUNT(ws.id) AS cnt
                      FROM machines m
                      LEFT JOIN workout_session ws ON ws.machine_id = m.id
                      GROUP BY m.id ORDER BY cnt DESC LIMIT 5''')
    popular = cursor.fetchall()
    conn.close()

    return render_template('admin/dashboard.html',
                           user_count=user_count, machine_count=machine_count,
                           session_count=session_count, routine_count=routine_count,
                           coupon_count=coupon_count, popular=popular)


# ─── 회원 관리 (조회) ─────────────────────────────────
@app.route('/admin/users/')
def admin_users():
    if 'user_id' not in session: return redirect('/login/')
    if session.get('role') != 'admin': return redirect('/')
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM users ORDER BY id')
    users = cursor.fetchall()
    conn.close()
    return render_template('admin/users.html', users=users)


# ─── 회원 삭제 ────────────────────────────────────────
@app.route('/admin/users/<int:id>/delete/')
def admin_user_delete(id):
    if 'user_id' not in session: return redirect('/login/')
    if session.get('role') != 'admin': return redirect('/')
    # 자기 자신은 삭제 금지 (로그인 깨짐 방지)
    if id == session['user_id']:
        return redirect('/admin/users/')
    conn, cursor = get_db()
    cursor.execute('DELETE FROM users WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect('/admin/users/')


# ─── 회원 권한 변경 (user ↔ admin 토글) ───────────────
@app.route('/admin/users/<int:id>/role/')
def admin_user_role(id):
    if 'user_id' not in session: return redirect('/login/')
    if session.get('role') != 'admin': return redirect('/')
    conn, cursor = get_db()
    cursor.execute('SELECT role FROM users WHERE id = ?', (id,))
    row = cursor.fetchone()
    if row:
        new_role = 'admin' if row[0] == 'user' else 'user'   # 반대로 뒤집기
        cursor.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, id))
        conn.commit()
    conn.close()
    return redirect('/admin/users/')


# ─── 기구 관리 (조회 + 등록폼) ────────────────────────
@app.route('/admin/machines/')
def admin_machines():
    if 'user_id' not in session: return redirect('/login/')
    if session.get('role') != 'admin': return redirect('/')
    conn, cursor = get_db()
    cursor.execute('SELECT * FROM machines ORDER BY id')
    machines = cursor.fetchall()
    conn.close()
    return render_template('admin/machines.html', machines=machines)


# ─── 기구 등록 (CREATE) ───────────────────────────────
@app.route('/admin/machines/add/', methods=['POST'])
def admin_machine_add():
    if 'user_id' not in session: return redirect('/login/')
    if session.get('role') != 'admin': return redirect('/')
    name      = request.form['name']
    body_part = request.form['body_part']
    min_rom   = int(request.form['min_valid_rom']) if request.form.get('min_valid_rom') else 10
    desc      = request.form.get('description', '')

    conn, cursor = get_db()
    cursor.execute('INSERT INTO machines (name, body_part, min_valid_rom, description) VALUES (?,?,?,?)',
                   (name, body_part, min_rom, desc))
    mid = cursor.lastrowid
    cursor.execute('UPDATE machines SET qr_url = ? WHERE id = ?', (f'/machine/{mid}/', mid))
    conn.commit()
    conn.close()
    return redirect('/admin/machines/')


# ─── 기구 수정 (UPDATE) ───────────────────────────────
@app.route('/admin/machines/<int:id>/edit/', methods=['GET', 'POST'])
def admin_machine_edit(id):
    if 'user_id' not in session: return redirect('/login/')
    if session.get('role') != 'admin': return redirect('/')
    conn, cursor = get_db()

    if request.method == 'POST':   # 수정 저장
        name      = request.form['name']
        body_part = request.form['body_part']
        min_rom   = int(request.form['min_valid_rom']) if request.form.get('min_valid_rom') else 10
        desc      = request.form.get('description', '')
        cursor.execute('''UPDATE machines SET name=?, body_part=?, min_valid_rom=?, description=?
                          WHERE id=?''', (name, body_part, min_rom, desc, id))
        conn.commit()
        conn.close()
        return redirect('/admin/machines/')

    # GET → 기존 값 채운 수정 폼
    cursor.execute('SELECT * FROM machines WHERE id = ?', (id,))
    m = cursor.fetchone()
    conn.close()
    if not m:
        return redirect('/admin/machines/')
    return render_template('admin/machine_edit.html', m=m)


# ─── 기구 삭제 (DELETE) ───────────────────────────────
@app.route('/admin/machines/<int:id>/delete/')
def admin_machine_delete(id):
    if 'user_id' not in session: return redirect('/login/')
    if session.get('role') != 'admin': return redirect('/')
    conn, cursor = get_db()
    cursor.execute('DELETE FROM machines WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect('/admin/machines/')


# ─── 쿠폰 관리 (조회 + 등록폼) ────────────────────────
@app.route('/admin/coupons/')
def admin_coupons():
    if 'user_id' not in session: return redirect('/login/')
    if session.get('role') != 'admin': return redirect('/')
    conn, cursor = get_db()
    # 쿠폰별 지급 횟수도 같이 집계
    cursor.execute('''SELECT c.*, (SELECT COUNT(*) FROM user_coupon WHERE coupon_id = c.id)
                      FROM coupons c ORDER BY c.id''')
    coupons = cursor.fetchall()
    conn.close()
    return render_template('admin/coupons.html', coupons=coupons)


# ─── 쿠폰 등록 (CREATE) ───────────────────────────────
@app.route('/admin/coupons/add/', methods=['POST'])
def admin_coupon_add():
    if 'user_id' not in session: return redirect('/login/')
    if session.get('role') != 'admin': return redirect('/')
    partner  = request.form['partner_name']
    category = request.form['category']
    code     = request.form['code']
    discount = request.form['discount']
    qty      = int(request.form['total_qty']) if request.form.get('total_qty') else 50

    conn, cursor = get_db()
    cursor.execute('''INSERT INTO coupons (partner_name, category, code, discount, condition, total_qty)
                      VALUES (?, ?, ?, ?, '루틴 100% 완료', ?)''',
                   (partner, category, code, discount, qty))
    conn.commit()
    conn.close()
    return redirect('/admin/coupons/')


# ─── 쿠폰 삭제 (DELETE) ───────────────────────────────
@app.route('/admin/coupons/<int:id>/delete/')
def admin_coupon_delete(id):
    if 'user_id' not in session: return redirect('/login/')
    if session.get('role') != 'admin': return redirect('/')
    conn, cursor = get_db()
    cursor.execute('DELETE FROM coupons WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect('/admin/coupons/')


# ─── 실행 ──────────────────────────────────────────────
# 로컬에서 `python app.py` 로 직접 실행할 때만 서버가 켜진다.
# 배포(PythonAnywhere)에서는 WSGI가 위의 app 객체만 가져다 쓰므로
# 이 블록은 실행되지 않는다. (배포 시 따로 주석처리할 필요 없음)
if __name__ == '__main__':
    app.run(debug=True)
