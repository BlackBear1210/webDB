# 🏋️ FitQR — 스마트 짐 운동 트래커 (v2)

> 웹DB 프로그래밍 기말 프로젝트
> **이 문서는 실제 코드(`app.py` · `templates/` · `static/`)를 기준으로 작성됨.**
> 코드와 설계문서가 다를 경우 **코드가 1순위**다. (구 `개발일지.md`의 v1 — 건강진단/식단/질환규칙 — 기능은 폐기되어 현재 코드에 없음)

---

## 0. 한 줄 컨셉

운동기구 회사와 제휴했다고 가정. 헬스장 **머신의 QR을 웹캠으로 스캔하면** 그 운동의
사용법(준비/수행/팁)이 화면에 뜨고, 운동하면 **센서가 reps/세트/휴식을 자동 카운트**해서 저장된다(시뮬레이션).
머신이 없는 운동(바벨스쿼트·데드리프트·푸시업 등)은 **전신거울 카메라가 동작을 인식**하는 것으로 가정해 동일한 카운트 UI를 쓴다.
회원가입 정보로 **30일 루틴**을 자동 생성하고, 리포트는 **캘린더**로 본다.
루틴을 **95% 이상 완료하면 제휴사 할인 쿠폰**을 지급한다.

> ⚠️ 실제 하드웨어는 만들지 않고 웹으로 **시뮬레이션**한다.
> - "QR 스캔" = 머신별 URL `/machine/<id>/` (웹캠으로 QR 인식)
> - "센서 자동 카운트" = 운동화면 JS의 [+1 Rep] 버튼 + 휴식 N초 무동작 시 세트 자동확정
> - "휴식 자동 세트 완료" = 마지막 Rep 후 `REST_SEC`(8초) 무동작이면 그 세트 확정

---

## 1. 기술 스택 / 폴더 구조

- **Flask + SQLite + Jinja2 (+ 카운트용 JS)**
- QR 이미지 생성: `qrcode` (없어도 앱은 동작, 생성 라우트만 404)
- 웹캠 QR 인식: `static/html5-qrcode.min.js` (CDN 아닌 **로컬 저장** → 오프라인 시연 가능)

```
fitqr/
  ├── app.py                 # 메인 (DB 스키마 + 시드 + 전체 라우트)  ★ 단일 파일
  ├── fitqr.db               # SQLite DB (실행 시 자동 생성)
  ├── templates/
  │   ├── base.html          # 공통 레이아웃 + 하단 5탭
  │   ├── login.html / register.html
  │   ├── routine_home.html  # 탭1: 루틴 홈(계획 30일)
  │   ├── routine_train.html # 루틴 훈련 서브탭(부위별 종목)
  │   ├── routine_day.html   # 그날 상세
  │   ├── exercise_detail.html / exercises.html
  │   ├── machine.html       # QR 진입(머신 정보)
  │   ├── qrcodes.html       # 머신 QR 모아보기(시연/인쇄)
  │   ├── scan.html          # 웹캠 QR 스캔  ★
  │   ├── workout.html       # 운동 진행(종목 목록)
  │   ├── use.html           # 종목 사용(Rep 카운트)
  │   ├── workout_done.html  # 운동 요약
  │   ├── custom.html        # 탭2: 커스텀 루틴
  │   ├── report.html / report_day.html  # 탭4: 리포트
  │   ├── me.html / me_edit.html / rewards.html  # 탭5: 내 정보/보상함
  │   └── admin/  dashboard.html · exercises.html · coupons.html · users.html
  └── static/
      ├── style.css
      └── html5-qrcode.min.js   (375KB)
```

---

## 2. DB 설계 (SQLite, 테이블 11개)

`init_db()` 가 `CREATE TABLE IF NOT EXISTS` 로 생성하고, 비어 있으면 시드를 채운다.
모든 FK는 `PRAGMA foreign_keys = ON` 으로 활성화.

| # | 테이블 | 역할 / 핵심 컬럼 |
|---|--------|------------------|
| 1 | **users** | 회원. login_id(UNIQUE)/password/name/gender/goal/focus_part/height/weight/target_weight/fitness_level/squat·bench·deadlift_1rm/frequency/start_weekday/role |
| 2 | **exercise** | 운동 종목(머신/비머신 통합). name/body_part/primary_target/secondary_target/equipment/**is_machine**(1=머신,0=거울)/difficulty/prep/execution/tips/video_url |
| 3 | **routine** | 회원당 30일 루틴 헤더. user_id/status(진행중·완료)/**reward_given** |
| 4 | **routine_day** | 루틴의 1~30일. day_no/weekday/is_rest/body_part/**is_unlocked**(해금)/is_completed/completed_at |
| 5 | **routine_day_item** | 그날의 운동 종목. routine_day_id/exercise_id/target_sets/target_reps/seq |
| 6 | **workout** | "운동 종료" 1단위. user_id/source(루틴·커스텀·단독)/routine_day_id/custom_id/title/started_at/ended_at/status/duration_sec/total_volume |
| 7 | **machine_use** | "사용 종료" 1단위(한 종목 사용). workout_id/exercise_id/weight/started_at/ended_at |
| 8 | **set_log** | 세트 1개. machine_use_id/set_number/reps/weight |
| 9 | **custom_routine** / **custom_routine_item** | 사용자 커스텀 루틴 헤더+항목 |
| 10 | **weight_log** | 내 체중 기록(리포트 차트용). user_id/weight/logged_at |
| 11 | **coupons** / **user_coupon** | 쿠폰 마스터 + 지급 내역(N:M 중간테이블) |

> **운동 기록 3계층**: `workout`(운동) → `machine_use`(종목 사용) → `set_log`(세트).
> **해금 규칙**: `day_no=N` 은 `N-1` 완료 시 `is_unlocked=1`. 1일차는 가입 즉시 해금.

### 시드 데이터
- **관리자 계정** `admin / 1234` (role=admin)
- **운동 종목**: 부위별 머신 5종+(가슴·등·어깨·팔·복근·엉덩이·다리·전신) + 비머신 대표 종목(바벨스쿼트·데드리프트·푸시업·런지·플랭크 등) → `seed_exercises()`
- **쿠폰 5종**: 마이프로틴 10%, GNC 15%, 나이키 5%, 언더아머 7%, 데카트론 5%

---

## 3. 30일 루틴 자동 생성 로직 (`create_routine_for_user`)

가입 직후(또는 홈 진입 시 루틴이 없으면) 호출.

```
빈도(frequency)  → 주간 운동 요일 오프셋   FREQ_OFFSETS  (예: 3회 → [0,2,4])
집중부위(focus)  → 부위 순환 리스트        build_part_cycle (선택 부위를 앞에 배치)
레벨(level)      → 세트 수 / 종목 수        SETS_BY_LEVEL · COUNT_BY_LEVEL (초3·중4·상5)
목표(goal)       → 목표 reps               REPS_BY_GOAL (강해지기6·근육량12·체중감량15)
```

- 30일치 각 날에 (요일, 부위) 배정 → `routine_day` INSERT
- 각 날 부위에 맞는 종목을 **머신 우선**으로 뽑고(부족하면 전신 보충) 셔플 후 `count`개 선택 → `routine_day_item` INSERT
- 1일차만 `is_unlocked=1`

---

## 4. 핵심 흐름 — QR 스캔 → 운동 → 카운트 → 기록

```
[루틴 그날 상세] /routine/day/<n>/
   └ [운동 시작] (POST /routine/day/<n>/scan/)
        → workout 생성(source=루틴, status=진행중) → /scan/ 으로

[웹캠 QR 스캔] /scan/
   → 머신 QR 인식 → /machine/<eid>/?wid=<workout_id> 로 이동

[머신 정보] /machine/<eid>/
   → 종목 준비/수행/팁 표시 → [이 머신으로 운동] (POST /use/start/)
        → machine_use 생성 → /use/<use_id>/

[종목 사용(카운트)] /use/<use_id>/
   → 무게 입력, [+1 Rep] 버튼으로 reps 누적 (센서/거울 시뮬)
   → 마지막 Rep 후 REST_SEC(8초) 무동작 → 현재 세트 자동 확정
   → 세트 배열을 JSON으로 모아서 한 번에 전송
   ├ [사용 종료]  (POST /use/<id>/end/)            → set_log 저장 → /scan/ (다음 머신 스캔)
   └ [운동 종료]  (POST /use/<id>/end/ then_end=1) → 사용 저장 + 운동 전체 종료

[운동 종료] /workout/<wid>/end/  또는 위 then_end
   → _finalize_workout(): 시간·볼륨 계산, status=완료
   → 루틴이면 그날 is_completed=1 + 다음 날 해금 + 보상 체크
   → /workout/<wid>/done/ (요약)
```

> **설계 선택**: Rep마다 서버 요청하지 않고, **세트 배열을 [사용 종료] 시 한 번에 POST**(`sets_json`) → 왕복 최소화·안정성↑.
> `use_end` 는 `then_end=1` 파라미터로 "사용만 종료" vs "이어서 운동 전체 종료"를 구분한다.

### 운동 시작 2-경로 & 카운트 3-모드 (★ 핵심 UX)
**계획된 종목의 [시작]**을 누르면 바로 운동 화면으로 가지 않고 **선택 화면(`/use/choose/<eid>/`)**으로 간다.
머신 종목은 두 경로, 머신 없는 종목은 수동만 제공:

| 경로 | 진입 | 카운트 모드(`use.html`) | 설명 |
|------|------|------------------------|------|
| **QR 스캔** | [📷 QR 스캔하기] → `/scan/` → 머신 QR 인식 → `/machine/<id>/?scanned=1` → [이 머신으로 운동] | **auto** | 머신 센서가 reps·세트·휴식을 자동 기록(`+1 Rep` + 휴식 8초 자동 세트완료). 정확한 운동 내역 |
| **수동** | [✍️ 수동으로 시작하기] → `/use/start/`(`mode=manual`) | **manual** | QR 훼손 등으로 인식 불가 시. 무게·횟수 직접 입력, **세트 종료도 직접**(자동 휴식 없음) |
| **발표용 QR** | 사전입력 QR 스캔 → `/machine/<id>/?scanned=1&sets=&reps=&weight=` → [이 머신으로 운동] | **demo** | 세트가 **자동으로 미리 채워짐**. 사용자는 [사용 종료]/[운동 종료]만 누름 (시연용) |

> `use_start`가 폼의 `mode`/`sets`/`reps`/`weight`로 진입 모드를 판별 → `/use/<id>/?mode=manual` 또는 `?demo=1&sets=…` 로 리다이렉트.
> `use.html`은 `mode`(auto/manual/demo)에 따라 카운트 UI를 분기. demo는 로드 시 `sets` 배열을 미리 채운다.
> **보안**: `scan.html`은 QR 내용에서 `/machine/<숫자>/` 와 **숫자 파라미터(sets/reps/weight)만** 정규식 추출 → 내부 경로로만 이동(임의 URL 차단 유지).

### 발표용 QR 이미지 생성 (`make_demo_qr.py`)
- 부위별 대표 머신 1개씩, 현실적인 세트/횟수/무게를 **QR에 미리 박아** PNG로 저장.
- 출력: `static/demoqr/<부위>_<머신명>.png` (8개) + `index.html`(한눈에 보기/인쇄용).
- 실행: `python make_demo_qr.py`. QR은 경로·숫자 파라미터만 쓰이므로 **인코딩된 호스트 주소는 무관**.
- 부위별 값: 가슴4×12×40 · 등4×12×45 · 어깨4×12×25 · 팔4×15×25 · 복근3×15×30 · 엉덩이4×12×60 · 다리4×12×120 · 전신3×15×30.

### 머신 페이지 "QR 인식 완료" 배너 (진입 경로 구분)
`/machine/<id>/`는 **실제 스캔(`?scanned=1`)으로 들어왔을 때만** "✅ QR 인식 완료" 배너를 표시. 운동 카탈로그·종목 상세에서 **클릭**으로 들어오면 "머신 정보"로 표시(스캔 안 했는데 "스캔됨" 뜨던 혼동 제거).

### 보상 (`check_reward`)
루틴 진행률 = 완료한 `routine_day` / 전체 × 100.
**95% 이상 + `reward_given=0`** 이면 재고 있는 쿠폰 1개를 무작위 지급(재고 -1, `reward_given=1`, status=완료).
지급된 `user_coupon.id`를 `session['new_reward']`에 담아 요약 화면에서 1회성 축하 표시.

---

## 5. 웹캠 QR 스캔 구현 (`scan.html`) ★ 최근 변경

### 변경 전
`Html5QrcodeScanner`(고수준 위젯) 사용 → "카메라" 탭과 **"이미지 파일 스캔" 탭**이 함께 떴고,
사용자가 권한 요청 버튼을 눌러야 카메라가 시작되어 "웹캠 연동이 안 된 것처럼" 보였다.

### 변경 후 (현재 코드)
`Html5Qrcode`(저수준 API)로 교체해 **페이지 진입 시 후면 카메라를 자동으로 켜고 바로 인식**.

- `html5Qr.start({ facingMode: 'environment' }, config, onScanSuccess, …)` 로 즉시 시작
- 실패 시 `Html5Qrcode.getCameras()` 로 사용 가능한 카메라 목록을 받아 마지막 카메라로 재시도
- 실패하면 **에러 메시지 + [다시 시도] 버튼** 표시 (`showCamError`)
- `navigator.mediaDevices.getUserMedia` 미지원 환경 사전 차단
- **파일 업로드 UI 완전 제거**
- QR 디코드 결과에서 `/machine/(\d+)/` 패턴을 추출 → 현재 origin 기준으로 이동(`?wid=` 유지)
- 인식 성공 시 `scanned` 플래그로 중복 이동 방지, `html5Qr.stop()` 후 해당 머신으로 이동

### ⚠️ 카메라 동작 조건 (중요)
브라우저 카메라(`getUserMedia`)는 **보안 컨텍스트에서만** 작동:
- ✅ `http://localhost` / `http://127.0.0.1`
- ✅ `https://...`
- ❌ `http://192.168.x.x` 같은 **일반 http + IP** (폰/다른 기기에서 IP로 접속 시 카메라 차단)
- 발표/시연은 localhost 에서 하면 별도 배포 없이 웹캠 동작.

---

## 6. 라우트 맵 (실제 구현)

### 사용자
| 기능 | 라우트 | 메서드 |
|---|---|---|
| 회원가입 | `/register/` | GET/POST |
| 로그인 / 로그아웃 | `/login/` · `/logout/` | GET/POST · GET |
| 루틴 홈(계획 30일) | `/` | GET |
| 루틴 훈련 서브탭 | `/routine/exercises/` | GET |
| 루틴 그날 상세 | `/routine/day/<day_no>/` | GET |
| 운동 시작 → 스캔 | `/routine/day/<day_no>/scan/` | POST |
| 운동 진행 화면 직접 | `/routine/day/<day_no>/start/` | POST |
| 종목 상세 | `/exercise/<eid>/` | GET |
| 머신 QR 진입 | `/machine/<eid>/` | GET |
| 머신 QR 이미지 | `/machine/<eid>/qr.png` | GET |
| 머신 QR 모아보기 | `/qrcodes/` | GET |
| 웹캠 QR 스캔 | `/scan/` | GET |
| 운동 시작 방법 선택(QR/수동) | `/use/choose/<eid>/` | GET |
| 종목 사용 시작 | `/use/start/` (mode/sets/reps/weight) | POST |
| 종목 사용(카운트) 화면 | `/use/<use_id>/` | GET |
| 사용 종료 / 운동 종료 | `/use/<use_id>/end/` | POST |
| 운동 종료 | `/workout/<wid>/end/` | POST |
| 운동 진행 화면 | `/workout/<wid>/` | GET |
| 운동 요약 | `/workout/<wid>/done/` | GET |
| 운동 카탈로그(검색/필터) | `/exercises/` | GET |
| 커스텀 목록 / 생성 / 삭제 / 시작 | `/custom/` · `/custom/create/` · `/custom/<cid>/delete/` · `/custom/<cid>/start/` | GET/POST |
| 리포트(캘린더+통계+무게) | `/report/` | GET |
| 리포트 특정일 | `/report/day/<date_str>/` | GET |
| 무게 기록 | `/report/weight/` | POST |
| 내 정보 조회 / 수정 | `/me/` · `/me/edit/` | GET/POST |
| 보상함 | `/me/rewards/` | GET |

### 관리자 (`/admin`, role=admin) — `admin_guard()` 이중 차단
| 기능 | 라우트 |
|---|---|
| 대시보드(회원·종목·운동·쿠폰 수 + 인기 종목 TOP5) | `/admin/` |
| 운동 종목 관리(목록/추가/삭제) | `/admin/exercises/` · `/add/` · `/<eid>/delete/` |
| 쿠폰 관리(목록/추가/삭제) | `/admin/coupons/` · `/add/` · `/<cid>/delete/` |
| 회원 관리(목록/삭제, 본인 삭제 방지) | `/admin/users/` · `/<uid>/delete/` |

---

## 7. 안정성/보안 처리

### 기본 방어 (처음부터 적용)
- **`require_login()`**: 세션 user_id가 실제 DB에 존재하는지 확인 → DB 리셋 후 남은 유령 세션 자동 정리.
- **소유권 검증**: workout/machine_use 등 모든 조회에서 `user_id` 일치 확인 → 남의 데이터 접근 차단(IDOR 방지).
- **no-cache 헤더**(`after_request`): 계정 전환 후 이전 사용자 화면이 캐시로 보이는 현상 방지.
- **로그인 시 `session.clear()`** 후 재설정 → 계정 흔적 제거.
- **숫자 입력 안전 변환**: 빈 값이 와도 기본값으로 처리(서버 안 터짐).
- **파라미터 바인딩(`?`)**: SQL 인젝션 방지(LIKE 검색 포함 전 쿼리).
- **Jinja2 자동 이스케이프**: `|safe`/`render_template_string` 미사용 → 기본 XSS 방어.
- **관리자 이중 차단(`admin_guard`)** + 본인 계정 삭제 방지.

### 🔐 보안 점검 후 수정 완료 (2026-06-04)
| # | 문제 | 위험 | 수정 내용 |
|---|------|------|-----------|
| 1 | **secret_key 하드코딩**(`'fitqr_secret_2026_v2'`) | 키가 코드/깃에 노출+추측 가능 → 공격자가 **세션 쿠키 위조**로 `role=admin` 세션을 만들어 관리자 권한 탈취 | `load_secret_key()` 도입: **환경변수 `SECRET_KEY` > 로컬 `.secret_key` 파일 > 자동 무작위 생성**(`secrets.token_hex(32)`). 키를 코드에서 분리하고 `.secret_key`는 `.gitignore` 처리 |
| 2 | **권한을 세션 값만 신뢰** | 쿠키 위조 시 곧바로 관리자 통과 | `require_admin()`을 **DB에서 실제 role 재확인**하도록 강화(심층 방어). secret_key가 새어도 DB role이 user면 차단 |
| 3 | **비밀번호 평문 저장** | DB 유출 시 모든 회원 비번 그대로 노출(타 서비스 비번 재사용 피해) | `werkzeug.security` 해시 적용. 가입/시드는 `generate_password_hash`, 로그인은 `check_password_hash`. **`init_db()`에서 기존 평문 비번 1회 자동 마이그레이션** + 로그인 시 레거시 평문 발견하면 해시로 자동 승급 → 기존 DB도 안 깨짐 |
| 4 | **CSRF 토큰 없음** | 공격자 사이트가 자동 폼 제출로 관리자 몰래 회원/종목/쿠폰 삭제 등 유발 | **의존성 없이 직접 구현**: 세션에 무작위 토큰(`secrets.token_hex(16)`) → `context_processor`로 `csrf_token()` 노출 → **20개 모든 POST 폼 HTML에 `_csrf` 숨은 필드를 서버사이드로 직접 삽입(JS 무관)** + `base.html` 스크립트가 누락 폼 자동 보완(안전망) → `before_request`에서 모든 POST 검증(`hmac.compare_digest`, 불일치 시 400) |
| 5 | **세션 쿠키 보안 플래그** | HTTP 도청·JS 세션 탈취·CSRF | `SESSION_COOKIE_HTTPONLY=True`(JS 접근 차단), `SESSION_COOKIE_SAMESITE='Lax'`(타 사이트 요청에 쿠키 미전송→CSRF 완화), `SESSION_COOKIE_SECURE=FORCE_HTTPS`(배포 시 자동 Secure) |
| 6 | **로그인 무차별 대입(brute-force)** | 비번 자동 추측 가능 | **인메모리 IP별 실패 카운트**: 최근 5분(`LOGIN_WINDOW_SEC`) 내 5회(`LOGIN_MAX_FAILS`) 실패 시 잠금 메시지. 성공 시 카운트 초기화 (`login_blocked`/`record_login_fail`/`clear_login_fails`) |
| 7 | **스캔 QR 오픈리다이렉트/DOM XSS** | 악성 QR(`javascript:`·외부URL)을 스캔하면 스크립트 실행/피싱 이동 | `scan.html`에서 **`/machine/<숫자>/` 패턴만 추출해 내부 상대경로로만 이동**. 패턴 없으면 이동 안 하고 계속 스캔. `new URL()`/`decodedText` 직접 이동 폴백 제거 + `encodeURIComponent` |
| 8 | **사용자명 열거(enumeration)** | 아이디 존재 여부 식별 | 로그인 실패 메시지를 **존재/비번틀림 동일**하게 통일 + **사용자 없을 때도 더미 해시 검증**으로 응답 시간 차이(타이밍 enumeration) 제거 |
| 9 | **HTTPS 미적용** | 평문 전송 도청 | **환경변수 `FORCE_HTTPS=1`**(배포)에서 http→https 301 리다이렉트(`X-Forwarded-Proto` 인식) + `Strict-Transport-Security`(HSTS) + 쿠키 Secure. 로컬(미설정)은 영향 없음 |
| 10 | **입력 변환 시 500** | 숫자 칸에 문자 입력 시 `ValueError`로 500(정보 노출) | `to_float`/`to_int` 안전 변환 헬퍼로 전 입력(회원가입·내정보·세트·무게·관리자·커스텀) 교체. 빈도/요일은 범위(1~7,0~6) 강제, sets_json 타입 검증 |
| — | (공통) **보안 헤더** | 클릭재킹·MIME 스니핑 | 모든 응답에 `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff` |

> **secret_key란?** Flask 세션은 서버가 아니라 **쿠키(클라이언트)에 저장**되고, 그 무결성을 `secret_key`로 만든 HMAC 서명으로만 보장한다. 키가 노출되면 누구나 유효한 세션(=role=admin)을 위조할 수 있어 사실상 인증이 무력화된다. → 키를 코드에서 분리 + DB 권한 재확인으로 이중 방어.
> **비번 해시**: `generate_password_hash('1234')` → `scrypt:32768:8:1$...` 형태로 저장. 원문 복원 불가, 검증은 `check_password_hash(stored, 입력)`. `is_hashed(pw)`(=`pbkdf2:`/`scrypt:` 시작)로 해시/평문 판별.
> **CSRF 동작**: 토큰을 **각 폼 HTML에 서버사이드로 직접 박아** JS 없이도 항상 포함(배포 안정성). `base.html` JS는 토큰 없는 폼만 보완하는 안전망(중복 주입 안 함). AJAX 없이 전부 일반 폼 제출(`form.submit()` 포함). 토큰은 `_csrf` 숨은 필드로 전송.
> **brute-force 방어**: 단순/무의존 인메모리 방식. 단일 프로세스(시연·PythonAnywhere 무료) 기준. 다중 워커 배포 시엔 공유 저장소(Redis 등) 기반으로 바꿔야 정확. (현재 규모엔 충분)

> 🚀 **배포 체크리스트(2가지만)**: ① `app.run(debug=True)`→`debug=False` ② 환경변수 **`FORCE_HTTPS=1`** 설정 → http→https 리다이렉트·HSTS·쿠키 Secure가 자동 적용됨. (secret_key는 `SECRET_KEY` 환경변수로 주거나 `.secret_key` 자동 생성)

### ✅ 점검 결과 — 원래부터 안전한 부분 (발표 어필 포인트)
- **SQL 인젝션 안전**: 모든 쿼리가 `?` 파라미터 바인딩. LIKE 검색도 `params.append(f'%{q}%')`로 값만 바인딩 → 인젝션 불가.
- **XSS 기본 방어**: Jinja2 자동 이스케이프 사용. `|safe`·`render_template_string`·`eval`/`exec` 미사용.
- **소유권 검증(IDOR 방지)**: workout/machine_use/use 등에서 `user_id` 일치 확인 후 처리 → 남의 데이터 접근 차단.
- **관리자 이중 차단**(`admin_guard`: 로그인 + role) + **본인 계정 삭제 방지**.
- **유령 세션 정리**(`require_login`이 DB 존재 확인) + **로그인 시 `session.clear()`**.

### ⚠️ 남은 권장 사항 (미적용)
| 우선 | 항목 | 해결책 / 결정 |
|------|------|--------|
| 높음 | **`debug=True` 실행** | 배포 시 `debug=False` — **결정: 개발 중 유지, 배포 시점에 끄기**(2026-06-04) |
| 중간 | **기본 계정 admin/1234** | **결정: 시연 편의상 1234 유지(시연용 명시)**(2026-06-04). 코드에 시연용 주석. 배포 시 비번 변경 권장 |
| 낮음 | **brute-force 다중 워커 대응** | 다중 프로세스 배포 시 Redis 등 공유 카운터로 전환(현재 단일 프로세스엔 불필요) |

---

## 8. 상수 (app.py 상단)

| 상수 | 값 |
|---|---|
| `WEEKDAYS` | 월~일 |
| `BODY_PARTS` | 가슴/등/어깨/팔/복근/엉덩이/다리/전신 |
| `GOALS` | 강해지기 / 근육량늘리기 / 체중감량 |
| `LEVELS` | 초급 / 중급 / 상급 |
| `REST_SEC` | 8 (휴식 무동작 → 세트 자동확정 초) |

---

## 9. 기본 계정

| 구분 | 아이디 | 비번 |
|------|--------|------|
| 관리자 | admin | 1234 |
| 일반 회원 | 직접 가입 (가입 시 30일 루틴 자동 생성 + 자동 로그인) | |

---

## 10. 실행

```bash
python app.py        # http://localhost:5000  (debug=True, port=5000)
```
`init_db()` 가 모듈 로드 시 자동 실행되어 테이블/시드를 준비한다.
```

