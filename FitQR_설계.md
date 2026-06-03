# 🏋️ FitQR — 스마트 짐 운동 트래커 (설계 v2)

> 웹DB 프로그래밍 기말 프로젝트
> 기술 스택: **Flask + SQLite + Jinja2 (+ 카운트/웹캠스캔용 JS)**
> ⚠️ 이 문서는 **실제 코드(`app.py` · `templates/` · `static/`) 기준으로 현행화**됨. 코드와 다르면 코드가 1순위.
> v1(건강진단+식단+질환규칙+가동범위 카운트)은 **완전히 폐기**되었고 현재 코드에 없음.

---

## 0. 한 줄 컨셉

운동기구 회사와 제휴했다고 가정. 헬스장 **머신의 QR을 웹캠으로 스캔하면** 그 운동의
사용법·정보가 화면에 뜨고, 운동하면 **센서가 reps/세트/휴식을 자동 카운트**해서 저장된다(시뮬레이션).
머신이 없는 운동(바벨스쿼트·데드리프트·푸시업 등)은 **전신거울 카메라가 동작을 인식**하는 것으로 가정해 동일한 카운트 UI를 쓴다.
(무게는 센서가 인식 못 하므로 사용자가 직접 입력)
회원가입 정보로 **30일 루틴**을 자동 생성하고, 리포트는 **캘린더**로 본다.
루틴을 **95% 이상 완료하면 제휴사 할인 쿠폰**을 지급한다.

> ⚠️ 실제 하드웨어는 만들지 않고 웹으로 **시뮬레이션**한다.
> - "QR 스캔" = 머신별 URL `/machine/<id>/` (웹캠으로 QR 인식)
> - "센서 자동 카운트" = 운동화면 JS의 [+1 Rep] 버튼
> - "거울 동작 인식" = 위와 동일한 카운트 UI(비머신 종목에도 동일 흐름 적용)
> - "휴식 자동 세트 완료" = 마지막 Rep 후 `REST_SEC`(8초) 무동작이면 그 세트 확정

---

## 1. 화면 구조 (하단 5탭)

지쿠형 모바일 앱 형태. 하단 고정 탭 5개. (`base.html` 의 `active` 변수로 현재 탭 강조)

| # | 탭 | 라우트 | 역할 |
|---|---|---|---|
| 1 | **루틴**(홈) | `/` | 30일 루틴 계획. 훈련 서브탭은 `/routine/exercises/` |
| 2 | **커스텀** | `/custom/` | 나만의 루틴 생성(종목+세트×횟수). 완료 시 리포트 반영 |
| 3 | **운동** | `/exercises/` | 전체 종목 카탈로그. 이름검색 + 부위/머신여부 필터, 터치 시 상세 |
| 4 | **리포트** | `/report/` | 캘린더 + 부위 히트맵 + 최근기록 + 내 무게 차트 |
| 5 | **내 정보** | `/me/` | 가입 정보 조회/수정 + 보상함 |

- 회원가입 완료 → **30일 루틴 자동 생성 + 자동 로그인** → 루틴 탭(홈).
- 모든 탭은 로그인 필수. 미로그인 시 `/login/` 으로.

---

## 2. DB 설계 (SQLite, 테이블 11개)

`init_db()` 가 `CREATE TABLE IF NOT EXISTS` 로 생성, 비어 있으면 시드. FK는 `PRAGMA foreign_keys = ON`.

### 2-1. 회원
```
users
  id PK · login_id UNIQUE · password · name
  gender              -- 남 / 여
  goal                -- 강해지기 / 근육량늘리기 / 체중감량
  focus_part          -- 집중 부위(복수 선택 시 쉼표 저장, 없으면 '전신')
  height · weight · target_weight
  fitness_level       -- 초급 / 중급 / 상급
  squat_1rm · bench_1rm · deadlift_1rm   -- 모르면 0
  frequency           -- 주당 운동일수 1~7
  start_weekday       -- 0=월 … 6=일
  created_at · role   -- user / admin
```

### 2-2. 운동 종목 마스터 (머신/비머신 통합)
```
exercise
  id PK · name · body_part
  primary_target · secondary_target · equipment
  is_machine          -- 1=머신(QR 스캔) / 0=비머신(거울 카메라)
  difficulty          -- 초급 / 중급 / 상급
  prep · execution · tips     -- 준비/수행/팁
  video_url           -- 현재 빈 값(추후)
```
> 부위(가슴/등/어깨/팔/복근/엉덩이/다리/전신)별 머신 5종+, 비머신 대표 종목(바벨스쿼트·데드리프트·푸시업·런지·플랭크·벤치프레스 등).

### 2-3. 30일 루틴
```
routine                 -- 회원당 30일 루틴 헤더
  id PK · user_id FK · created_at
  status                -- 진행중 / 완료
  reward_given          -- 95% 보상 지급 여부(0/1)

routine_day             -- 1~30일 각 날
  id PK · routine_id FK
  day_no                -- 1~30
  weekday               -- 0~6
  is_rest               -- 컬럼 존재(현재 생성 시 항상 0, 휴식일 미사용)
  body_part             -- 그날 타겟 부위
  is_unlocked           -- 앞 날 완료 시 해금(1일차 기본 해금)
  is_completed · completed_at

routine_day_item        -- 그날의 운동 종목
  id PK · routine_day_id FK · exercise_id FK
  target_sets · target_reps · seq
```
> **해금 규칙**: `day_no=N` 은 `N-1` 완료 시 `is_unlocked=1`. 1일차는 가입 즉시 해금.
> **종목 수·세트**: 레벨(SETS/COUNT_BY_LEVEL: 초3·중4·상5), reps는 목표(REPS_BY_GOAL: 강해지기6·근육량12·체중감량15)에 따라.
> 운동일 30개를 생성하며 별도 휴식일 카드는 만들지 않는다.

### 2-4. 운동 기록 (3계층: workout > machine_use > set_log)
```
workout                 -- "운동 종료" 1단위 (하루 여러 개 가능)
  id PK · user_id FK
  source                -- 루틴 / 커스텀 / 단독
  routine_day_id FK · custom_id FK   -- 시작 출처(아니면 NULL)
  title · started_at · ended_at
  status                -- 진행중 / 완료
  duration_sec · total_volume        -- 시간(초) · 총 볼륨 Σ(reps×weight)

machine_use             -- "사용 종료" 1단위 (한 종목 사용)
  id PK · workout_id FK · exercise_id FK
  weight · started_at · ended_at

set_log                 -- 세트 1개
  id PK · machine_use_id FK
  set_number · reps · weight
```

### 2-5. 커스텀 루틴
```
custom_routine        : id PK · user_id FK · name · created_at
custom_routine_item   : id PK · custom_id FK · exercise_id FK · target_sets · target_reps · seq
```

### 2-6. 내 무게 기록 (리포트 차트용)
```
weight_log : id PK · user_id FK · weight · logged_at
```

### 2-7. 보상 쿠폰 (제휴사)
```
coupons       : id PK · partner_name · category · code · discount · condition · total_qty
user_coupon   : id PK · user_id FK · coupon_id FK · issued_at · is_used
```

---

## 3. 핵심 흐름

### ① 회원가입
입력: 아이디/비번/이름, 성별, 목표, 집중 부위(복수), 키/현재체중/목표체중,
피트니스 레벨, 1RM(모르면 0), 주당 빈도(1~7), 시작 요일.
- 가입 → users INSERT → 첫 체중 `weight_log` 기록 → **30일 루틴 자동 생성** → **자동 로그인** → 홈.
- (※ v1의 목표체중 diff% 건강 경고는 현재 코드에 없음)

### ② 루틴 탭 (홈)
- **계획**: 1~30일 카드(요일·부위). 잠긴 날 🔒(앞 날 완료해야 해금), 완료한 날 ✓.
- 날짜 터치 → 그날 상세(`/routine/day/<n>/`): 종목 리스트 → 종목 터치 시 상세(준비/수행/팁).
- **[운동 시작]**(POST `/routine/day/<n>/scan/`) → workout 생성 후 **`/scan/`(웹캠 스캔)** 으로.
- **훈련 서브탭**(`/routine/exercises/`): 루틴에 포함된 모든 종목을 부위별로 한눈에.

### ③ QR 스캔 → 운동 → 카운트 (핵심)
```
[운동 시작] → workout(진행중) 생성 → /scan/
   → 웹캠으로 머신 QR 인식 → /machine/<id>/?wid=<workout_id>
   → [이 머신으로 운동] (POST /use/start/) → machine_use 생성 → /use/<use_id>/
       · 무게 입력
       · [+1 Rep] reps++ (센서/거울 감지 시뮬)
       · 마지막 Rep 후 REST_SEC(8초) 무동작 → 현재 세트 자동 확정(JS에서 sets 배열 누적)
   → [사용 종료] (POST /use/<id>/end/)            → set_log 일괄 저장 → /scan/ (다음 머신)
   → [운동 종료] (POST /use/<id>/end/ then_end=1   또는  /workout/<wid>/end/)
                 → 시간·볼륨 계산, status=완료 → 루틴이면 그날 완료+다음날 해금+보상 체크
                 → /workout/<wid>/done/ (요약)
```
> Rep마다 서버를 호출하지 않고 **세트 배열(`sets_json`)을 [사용 종료] 시 한 번에 POST** → 왕복 최소화.
> 비머신 종목도 동일한 `machine_use` 흐름으로 카운트한다(별도 거울 전용 라우트 없음).

#### 운동 시작 2-경로 & 카운트 3-모드
계획된 종목 [시작] → **선택 화면 `/use/choose/<eid>/`** (바로 운동 진입하지 않음):
- **[📷 QR 스캔하기]** → `/scan/` → 머신 QR 인식 → `machine_use` 생성 → **auto 모드**(자동 카운트+휴식).
- **[✍️ 수동으로 시작하기]** → `/use/start/`(`mode=manual`) → **manual 모드**: 무게·횟수 직접 입력, 세트 종료 직접(자동 휴식 없음). QR 훼손 대비.
- **발표용 QR**(사전입력 sets/reps/weight) 스캔 → **demo 모드**: 세트 자동 채움 → [사용 종료]/[운동 종료]만.

`use_start`가 `mode`/`sets`/`reps`/`weight`로 모드를 판별(`?mode=manual` / `?demo=1&…`). `use.html`이 모드별 UI 분기.

#### 발표용 QR 생성 (`make_demo_qr.py`)
부위별 대표 머신 + 현실 세트/무게를 QR에 박아 `static/demoqr/`에 PNG로 저장(8개) + 미리보기 `index.html`.
`scan.html`은 `/machine/<숫자>/`와 숫자 파라미터만 추출하므로 QR의 호스트는 무관·보안 유지.

#### 머신 페이지 배너
`/machine/<id>/`는 실제 스캔(`?scanned=1`)일 때만 "✅ QR 인식 완료" 표시, 클릭 진입은 "머신 정보".

### ④ 리포트 탭
- **캘린더**(이번 달): 완료한 날 표시, 날짜 터치 → 그날 상세(`/report/day/<date>/`, workout 단위 구분).
- **부위 히트맵**: 최근 7일 부위별 볼륨(`set_log` 집계).
- **최근 기록 5개** + **총 통계**(운동 수·시간·볼륨).
- **내 무게**: `weight_log` 최근 30일 → SVG 라인차트(`build_weight_chart`) + [기록] 버튼.

### ⑤ 운동 탭 (카탈로그)
이름 검색 + 부위/머신여부 필터(`/exercises/?q=&bp=&mc=`). 터치 → 종목 상세.

### ⑥ 커스텀 탭
종목을 담아 세트×횟수 지정 → 저장(`/custom/create/`). [시작](`/custom/<id>/start/`) 하면
`workout(source=커스텀)` 으로 ③ 흐름 진행, 완료 시 리포트 반영. 삭제도 가능.

### ⑦ 보상
```
루틴 진행률 = 완료한 routine_day / 전체 × 100
≥ 95% 이고 reward_given=0 →
   재고 있는 쿠폰 1개 무작위 지급(user_coupon INSERT, 재고 -1, reward_given=1, status=완료)
   session['new_reward'] 로 요약 화면에서 1회성 축하 표시
```

---

## 4. 라우트 맵 (실제 구현)

### 사용자
| 기능 | 라우트 | 메서드 |
|---|---|---|
| 회원가입 | `/register/` | GET/POST |
| 로그인 / 로그아웃 | `/login/` · `/logout/` | GET/POST · GET |
| 루틴 홈(계획) | `/` | GET |
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
| 종목 사용(카운트) | `/use/<use_id>/` | GET |
| 사용 종료 / 운동 종료 | `/use/<use_id>/end/` | POST |
| 운동 종료 | `/workout/<wid>/end/` | POST |
| 운동 진행 화면 | `/workout/<wid>/` | GET |
| 운동 요약 | `/workout/<wid>/done/` | GET |
| 운동 카탈로그 | `/exercises/` | GET |
| 커스텀 목록/생성/삭제/시작 | `/custom/` · `/custom/create/` · `/custom/<cid>/delete/` · `/custom/<cid>/start/` | GET/POST |
| 리포트 | `/report/` | GET |
| 리포트 특정일 | `/report/day/<date_str>/` | GET |
| 무게 기록 | `/report/weight/` | POST |
| 내 정보 조회/수정 | `/me/` · `/me/edit/` | GET/POST |
| 보상함 | `/me/rewards/` | GET |

### 관리자 (`/admin`, role=admin) — `admin_guard()` 이중 차단
| 기능 | 라우트 |
|---|---|
| 대시보드(회원·종목·완료운동·쿠폰 수 + 인기 종목 TOP5) | `/admin/` |
| 운동 종목 관리(목록/추가/삭제) | `/admin/exercises/` · `/add/` · `/<eid>/delete/` |
| 쿠폰 관리(목록/추가/삭제) | `/admin/coupons/` · `/add/` · `/<cid>/delete/` |
| 회원 관리(목록/삭제, 본인 삭제 방지) | `/admin/users/` · `/<uid>/delete/` |

---

## 5. 카운트 시뮬레이션 구현 방식

실제 센서가 없으므로 **운동화면(JS)** 이 세트/Rep를 누적하고,
**[사용 종료]** 시 세트 배열을 서버에 **한 번에 POST**(`sets_json`)한다.

- [+1 Rep] = 센서/거울 1회 감지 시뮬
- 휴식타이머: 마지막 Rep 후 `REST_SEC`(8초) → 현재 세트 확정, 다음 Rep에 새 세트
- 화면에 현재 세트/누적 reps/볼륨 실시간 표시, 무게는 입력칸
- 서버는 `set_log` 저장 후 `recalc_workout()` 으로 총 볼륨 재계산

### 웹캠 QR 스캔 (`scan.html`)
- `Html5Qrcode`(저수준) 사용 → **진입 시 후면 카메라 자동 시작**, 파일 업로드 UI 없음.
- 실패 시 `getCameras()`로 재시도, 그래도 안 되면 에러 + [다시 시도] 버튼.
- 인식한 QR에서 `/machine/(\d+)/` 추출 → 현재 origin 기준 이동(`?wid=` 유지).
- 라이브러리는 `static/html5-qrcode.min.js`(로컬) → 오프라인 시연 가능.
- ⚠️ 카메라는 `localhost`/`127.0.0.1`/`https` 에서만 동작(일반 http+IP 불가).

---

## 6. 시드 데이터

- **관리자 계정** `admin / 1234` (role=admin).
- **운동 종목**: 부위별 머신 5종+ (가슴/등/어깨/팔/복근/엉덩이/다리/전신) + 비머신 대표 종목
  (바벨스쿼트·데드리프트·푸시업·런지·플랭크·벤치프레스·오버헤드프레스·바벨로우·덤벨컬·버피 등).
  각 종목에 주/서브타겟·장비·난이도·준비/수행/팁 채움.
- **쿠폰 5종**: 마이프로틴 10%, GNC 15%, 나이키 5%, 언더아머 7%, 데카트론 5%.

---

## 7. 안정성/보안 처리

- `require_login()`: 세션 user_id가 실제 DB에 존재하는지 확인 → 유령 세션 자동 정리.
- 모든 조회에 소유권(`user_id`) 검증 → 남의/없는 자원 접근 차단(IDOR 방지).
- `after_request` no-cache 헤더 → 계정 전환 후 캐시 화면 방지.
- 로그인 시 `session.clear()` 후 재설정.
- 숫자 입력 안전 변환, 파라미터 바인딩(`?`)으로 SQL 인젝션 방지(LIKE 포함).
- Jinja2 자동 이스케이프 → 기본 XSS 방어(`|safe` 미사용).
- 관리자: `admin_guard()` 이중 차단 + 본인 계정 삭제 방지.

### 🔐 보안 점검 후 수정 (2026-06-04)
- **secret_key 코드 분리**: 하드코딩(`'fitqr_secret_2026_v2'`) 제거 → `load_secret_key()`(환경변수 `SECRET_KEY` > `.secret_key` 파일 > `secrets.token_hex(32)` 자동생성). `.secret_key`는 `.gitignore`. → **세션 쿠키 위조로 인한 관리자 권한 탈취 차단.**
- **`require_admin()` DB 재확인**: 세션 role만 믿지 않고 DB의 실제 role 확인(심층 방어).
- **비밀번호 해시**: `werkzeug.security`(`generate/check_password_hash`)로 저장·검증. `init_db()`에서 기존 평문 비번 1회 자동 마이그레이션 + 로그인 시 레거시 평문 자동 승급 → 기존 DB 호환. → **DB 유출 시 비번 노출 차단.**
- **CSRF 보호**: 의존성 없이 직접 구현 — 세션 토큰(`secrets.token_hex(16)`) + `context_processor`(`csrf_token()`) + **20개 모든 POST 폼 HTML에 `_csrf` 서버사이드 직접 삽입(JS 무관)** + `base.html` JS 안전망 + `before_request`에서 전 POST 검증(`hmac.compare_digest`).
- **세션 쿠키 플래그**: `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE='Lax'`, `SECURE=FORCE_HTTPS`(배포 자동).
- **로그인 brute-force**: 인메모리 IP별 실패 카운트(최근 5분 5회 실패 시 잠금). 단일 프로세스 기준.
- **스캔 QR 오픈리다이렉트/DOM XSS 차단**: `scan.html`이 `/machine/<숫자>/`만 추출해 내부 경로로만 이동(임의 URL·`javascript:` 차단).
- **사용자명 enumeration 차단**: 로그인 실패 메시지 통일 + 사용자 없을 때도 더미 해시 검증(타이밍 동일).
- **HTTPS**: 환경변수 `FORCE_HTTPS=1`(배포)에서 http→https 301 + HSTS + 쿠키 Secure.
- **입력 안전 변환**: `to_float`/`to_int`로 전 입력 교체(숫자칸 문자 입력 시 500 방지).
- **보안 헤더**: 전 응답에 `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff`.
- **기본 관리자 계정**: 결정 — 시연 편의상 admin/1234 유지(코드에 시연용 주석, 배포 시 변경 권장).

> ✅ **원래 안전**: SQL 인젝션(전 쿼리 `?` 바인딩), XSS(Jinja2 자동 이스케이프), IDOR(소유권 검증).
> 🚀 **배포 체크리스트**: ① `debug=False` ② 환경변수 `FORCE_HTTPS=1`. (상세는 `fitQR.md` §7 표 참고)

---

## 8. 상수 (app.py)

| 상수 | 값 |
|---|---|
| `WEEKDAYS` | 월~일 |
| `BODY_PARTS` | 가슴/등/어깨/팔/복근/엉덩이/다리/전신 |
| `GOALS` | 강해지기 / 근육량늘리기 / 체중감량 |
| `LEVELS` | 초급 / 중급 / 상급 |
| `REST_SEC` | 8 |
| `FREQ_OFFSETS` | 빈도별 주간 운동 요일 |
| `SETS_BY_LEVEL` / `COUNT_BY_LEVEL` | 초3·중4·상5 |
| `REPS_BY_GOAL` | 강해지기6·근육량12·체중감량15 |

---

## 9. 실행

```bash
python app.py     # http://localhost:5000  (debug=True, port=5000)
```
`init_db()` 가 모듈 로드 시 자동 실행되어 11테이블 + 시드를 준비한다.

| 구분 | 아이디 | 비번 |
|------|--------|------|
| 관리자 | admin | 1234 |
| 일반 회원 | 직접 가입 | |
