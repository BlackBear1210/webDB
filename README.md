# 🏋️ FitQR — 스마트 헬스장 운동 트래커

## 프로젝트 제목

**FitQR** : QR 코드 기반 헬스장 운동 기록 웹 서비스

---

## 주제 설명

FitQR은 헬스장 머신(기구) 및 전신거울에 부착된 **QR 코드를 스캔**하여 운동 세트·횟수·무게를 자동으로 기록하는 웹 서비스입니다.  
QR 스캔이 어려운 경우 **수동 입력 모드**를 지원하며, 사용자 맞춤 **30일 루틴 자동 생성**, 운동 완료 시 **쿠폰 보상** 지급, 리포트 페이지의 **캘린더·볼륨 통계**까지 제공합니다.

---

## 주요 기능

### 사용자 기능 (CRUD)

| 기능 | 설명 |
|------|------|
| 회원가입 / 로그인 | 아이디·비밀번호 기반 인증, 비밀번호 해시 저장(bcrypt) |
| 30일 루틴 자동 생성 | 목표·집중 부위·빈도를 반영해 가입 즉시 생성 |
| 커스텀 루틴 CRUD | 사용자가 직접 종목·세트·횟수 설정 |
| QR 스캔 운동 기록 | 머신·거울 QR 스캔 → 자동 reps 카운트 + 세트 자동 완료 |
| 수동 운동 기록 | 무게·횟수 직접 입력, 세트 종료 직접 조작 |
| 발표용 QR 자동 입력 | 사전 입력값(세트·횟수·무게)이 박힌 QR 스캔 시 세트 자동 채움 |
| 운동 리포트 | 월간 캘린더, 부위별 볼륨 히트맵, 체중 변화 그래프 |
| 내 정보 수정 | 체중·목표·집중 부위·1RM 등 수정 |
| 쿠폰 보상 | 루틴 95% 이상 달성 시 파트너 쿠폰 자동 지급 |

### 관리자 기능

| 기능 | URL |
|------|-----|
| 대시보드 (통계 요약) | `/admin/` |
| 운동 종목 추가 / 삭제 | `/admin/exercises/` |
| 쿠폰 추가 / 삭제 | `/admin/coupons/` |
| 회원 목록 / 삭제 | `/admin/users/` |

---

## DB 구조

| 테이블 | 주요 컬럼 | 설명 |
|--------|-----------|------|
| `users` | id, login_id, password, goal, focus_part, fitness_level | 회원 정보 |
| `exercise` | id, name, body_part, is_machine, difficulty, prep, execution, tips | 운동 종목 마스터 |
| `routine` | id, user_id, status, reward_given | 30일 루틴 헤더 |
| `routine_day` | id, routine_id, day_no, body_part, is_unlocked, is_completed | 루틴 각 날 |
| `routine_day_item` | id, routine_day_id, exercise_id, target_sets, target_reps | 하루 계획 종목 |
| `workout` | id, user_id, source, title, started_at, ended_at, total_volume | 운동 세션 |
| `machine_use` | id, workout_id, exercise_id, weight, started_at, ended_at | 종목 사용 단위 |
| `set_log` | id, machine_use_id, set_number, reps, weight | 세트별 기록 |
| `custom_routine` | id, user_id, name | 커스텀 루틴 |
| `custom_routine_item` | id, custom_id, exercise_id, target_sets, target_reps | 커스텀 종목 |
| `weight_log` | id, user_id, weight, logged_at | 체중 기록 |
| `coupons` | id, partner_name, code, discount, total_qty | 쿠폰 상품 목록 |
| `user_coupon` | id, user_id, coupon_id, issued_at, is_used | 쿠폰 발급 이력 |

---

## 느낀 점

- **QR 보안 처리**가 생각보다 까다로웠다. QR 내용에서 임의 URL로 이동하면 오픈 리다이렉트 취약점이 생기기 때문에, 정규식으로 `/machine/<숫자>/` 경로만 추출해 내부 상대경로로만 이동하도록 직접 구현했다.
- Flask의 **세션 쿠키 위조** 문제를 처음 알게 됐다. secret_key를 코드에 하드코딩하면 안 된다는 것을 배웠고, `.secret_key` 파일에 무작위로 생성해 저장하는 방식으로 해결했다.
- CSRF 방지를 별도 라이브러리 없이 **직접 구현**해보면서, POST 요청마다 숨겨진 토큰을 검증하는 원리를 실제로 이해할 수 있었다.
- **DB 정규화**의 중요성을 느꼈다. 처음에는 테이블을 단순하게 설계했다가, 루틴·커스텀·단독 운동 세 가지 출처를 하나의 `workout` 테이블로 통합하면서 `source` 컬럼과 외래키로 관계를 정리하는 과정이 어려웠다.
- JavaScript로 **QR 스캔 + 자동 카운트 + 휴식 타이머**를 동시에 처리하는 로직을 짜면서, 비동기 이벤트와 인터벌 타이머를 올바르게 관리하는 방법을 배웠다.

---

## 기술 스택

- **Backend**: Python 3, Flask, SQLite3
- **Frontend**: HTML5, CSS3, Vanilla JS
- **QR 스캔**: html5-qrcode.js
- **QR 생성**: qrcode (Python)
- **보안**: werkzeug PBKDF2 해시, CSRF 토큰, 세션 쿠키 보호, 로그인 브루트포스 방어

## 실행 방법

```bash
pip install flask qrcode werkzeug
python app.py
# http://localhost:5000 접속
# 관리자 계정: admin / 1234
```
