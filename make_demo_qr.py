# ════════════════════════════════════════════════════════════════════
#  발표용 QR 이미지 생성기
# --------------------------------------------------------------------
#  부위별 대표 머신 1개씩 골라, 세트·횟수·무게가 "미리 박힌" QR PNG를 만든다.
#  이 QR을 웹캠으로 스캔하면 use 화면에 세트가 자동으로 채워지고
#  사용자는 [사용 종료]/[운동 종료]만 누르면 된다. (발표 시연용)
#
#  실행:  python make_demo_qr.py
#  결과:  static/demoqr/<부위>_<머신명>.png  +  index.html(미리보기)
#
#  참고: 스캔 화면(scan.html)은 QR 내용에서 경로(/machine/<id>/)와
#        숫자 파라미터(sets/reps/weight)만 추출하므로, QR 안의 호스트
#        주소(localhost 등)는 무엇이든 상관없다.
# ════════════════════════════════════════════════════════════════════
import os
import sqlite3
import qrcode

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'fitqr.db')
OUT_DIR = os.path.join(BASE_DIR, 'static', 'demoqr')
BASE_URL = os.environ.get('FITQR_BASE', 'http://localhost:5000')  # 호스트는 무관

# 부위별 (세트, 횟수, 무게kg) — 현실적인 값
PLAN = {
    '가슴':   (4, 12, 40),
    '등':     (4, 12, 45),
    '어깨':   (4, 12, 25),
    '팔':     (4, 15, 25),
    '복근':   (3, 15, 30),
    '엉덩이': (4, 12, 60),
    '다리':   (4, 12, 120),
    '전신':   (3, 15, 30),
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    made = []
    # 머신(QR) 1개 + 거울(QR) 1개씩 부위별로 생성
    #  스캔 화면은 /machine/<id>/ 경로만 보므로 머신/거울 모두 같은 경로를 쓴다.
    #  (거울 종목도 /machine/<id>/ 라우트가 그대로 처리 → use 화면에서 '거울 동작 인식'으로 표시)
    KINDS = [(1, '머신'), (0, '거울')]
    for part, (sets, reps, weight) in PLAN.items():
        for is_machine, kind in KINDS:
            # 부위별 대표 종목 1개 선택 (머신 / 거울)
            cur.execute('''SELECT id, name FROM exercise
                           WHERE body_part=? AND is_machine=? ORDER BY id LIMIT 1''',
                        (part, is_machine))
            row = cur.fetchone()
            if not row:
                print(f'[skip] {part} {kind}: 해당 종목 없음')
                continue
            eid, name = row
            url = f'{BASE_URL}/machine/{eid}/?scanned=1&sets={sets}&reps={reps}&weight={weight}'
            img = qrcode.make(url)
            safe = name.replace(' ', '').replace('/', '')
            fname = f'{kind}_{part}_{safe}.png'
            img.save(os.path.join(OUT_DIR, fname))
            made.append((f'{part}({kind})', name, sets, reps, weight, fname, url))
            print(f'[ok] {part:4s} {kind} → {name} ({sets}x{reps}x{weight}kg)  {fname}')

    conn.close()

    # 한눈에 보는 미리보기 HTML (인쇄/캡처용)
    html = ['<!doctype html><meta charset="utf-8"><title>FitQR 발표용 QR</title>',
            '<style>body{font-family:sans-serif;background:#f4f5f7;padding:20px}',
            '.g{display:flex;flex-wrap:wrap;gap:16px}',
            '.c{background:#fff;border-radius:12px;padding:14px;width:200px;text-align:center;'
            'box-shadow:0 2px 8px rgba(0,0,0,.08)}',
            '.c img{width:170px;height:170px}.c b{display:block;margin-top:8px}',
            '.c small{color:#666}</style>',
            '<h2>🏋️ FitQR 발표용 QR (부위별)</h2>',
            '<p>웹캠으로 스캔하면 세트가 자동 입력됩니다.</p><div class="g">']
    for part, name, sets, reps, weight, fname, url in made:
        html.append(
            f'<div class="c"><img src="{fname}"><b>{part} · {name}</b>'
            f'<small>{sets}세트 × {reps}회 · {weight}kg</small></div>')
    html.append('</div>')
    with open(os.path.join(OUT_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(html))

    print(f'\n총 {len(made)}개 생성 → {OUT_DIR}')
    print('미리보기: static/demoqr/index.html 을 브라우저로 열면 한눈에 보입니다.')


if __name__ == '__main__':
    main()
