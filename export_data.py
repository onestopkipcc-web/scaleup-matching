# -*- coding: utf-8 -*-
"""매칭·발송 데이터를 바탕화면 폴더로 내보낸다 — 드라이브는 읽기만 한다.

드라이브의 match_state / review_state / send_progress 는 매 회차 덮어써서
지난 회차 기록이 남지 않는다. 이 스크립트로 회차별 스냅샷을 떠두면
"그때 뭘 왜 보냈나"를 나중에 복원할 수 있다.
내보낸 폴더를 그대로 NAS 공유 폴더에 복사해 쓰면 된다.

실행 (프로젝트 폴더에서, token.json 필요):
    python export_data.py            # 선정기업·공고수집·누적
    python export_data.py --round    # 위 + 이번 회차 폴더까지
    python export_data.py --out "D:\\다른경로"
"""
import os, io, re, json, sys, argparse
from datetime import datetime

import requests
import pandas as pd
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

DRIVE_FOLDER_ID    = "1iWGYjaoslqST45ggDlg-IPMLaUHCYmV_"
CLICK_LOG_SHEET_ID = "1-gYegpHysgSvF1TgQB7Rfh3rs_tNfrE4NS3F1xLef0o"
SCOPES             = ['https://www.googleapis.com/auth/drive']
OUT_DEFAULT        = r"C:\Users\fbwlg\Desktop\26년도\2. 원스톱\0. 원스톱 스케일업 맞춤형공고"

AI_FIELDS = ['추천여부', '적합도', '한줄요약', '업종일치', '자격충족',
             '지역적합', '수요일치', '판단근거', '주의사항']


# ── 인증·다운로드 (crawl_notices.py 와 같은 경로, 읽기 전용) ──
def get_creds():
    tj = os.environ.get('GOOGLE_TOKEN_JSON', '')
    if tj:
        creds = Credentials.from_authorized_user_info(json.loads(tj), SCOPES)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        sys.exit("인증 정보 없음 — 프로젝트 폴더에서 실행하세요 (token.json 필요)")
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def gapi(creds, method, url, **kw):
    h = kw.pop('headers', {})
    h['Authorization'] = f'Bearer {creds.token}'
    return requests.request(method, url, headers=h, timeout=300, **kw)


def drive_get(creds, filename):
    r = gapi(creds, 'GET', 'https://www.googleapis.com/drive/v3/files',
             params={'q': f"name='{filename}' and '{DRIVE_FOLDER_ID}' in parents "
                          f"and trashed=false",
                     'fields': 'files(id,name,modifiedTime)',
                     'orderBy': 'modifiedTime desc'})
    files = r.json().get('files', []) if r.ok else []
    if not files:
        return None, None
    f = files[0]
    r2 = gapi(creds, 'GET', f"https://www.googleapis.com/drive/v3/files/{f['id']}",
              params={'alt': 'media'})
    return (r2.content if r2.ok else None), f.get('modifiedTime', '')[:10]


def read_excel(creds, name):
    raw, mt = drive_get(creds, name)
    if not raw:
        return pd.DataFrame(), None
    try:
        return pd.read_excel(io.BytesIO(raw), dtype=str).fillna(''), mt
    except Exception:
        return pd.DataFrame(), mt


def read_json(creds, name):
    raw, mt = drive_get(creds, name)
    if not raw:
        return {}, None
    try:
        return json.loads(raw.decode('utf-8')), mt
    except Exception:
        return {}, mt


def save(df, path, sheets=None):
    """엑셀로 저장. sheets 가 주어지면 {시트명: df} 로 여러 장."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with pd.ExcelWriter(path, engine='openpyxl') as w:
        if sheets:
            for nm, d in sheets.items():
                (d if not d.empty else pd.DataFrame({'(내용 없음)': []})
                 ).to_excel(w, index=False, sheet_name=nm[:31])
        else:
            (df if not df.empty else pd.DataFrame({'(내용 없음)': []})
             ).to_excel(w, index=False, sheet_name='데이터')
    print(f"    저장  {os.path.relpath(path, OUT)}  ({len(df):,}행)"
          if sheets is None else
          f"    저장  {os.path.relpath(path, OUT)}  (시트 {len(sheets)}장)")


def build_diag(results, ai, rv):
    """사이드바 '진단용 결과 추출'과 같은 두 시트를 만든다."""
    if not results:
        return pd.DataFrame(), pd.DataFrame()
    d = pd.DataFrame(results).fillna('')
    key = lambda r: f"{r.get('기업명','')}_{r.get('공고ID','')}"
    for f in AI_FIELDS:
        d['AI_' + f] = d.apply(lambda r: (ai.get(key(r), {}) or {}).get(f, ''), axis=1)
    stat = {'○': '승인', '✕': '제외'}
    d['검토상태'] = d.apply(lambda r: stat.get(rv.get(key(r), ''), '미검토'), axis=1)

    def agg(g):
        s, rec, st = g['관련도'].astype(str), g['AI_추천여부'], g['검토상태']
        return pd.Series({'매칭건수': len(g), '★★★': (s == '★★★').sum(),
                          '★★': (s == '★★').sum(),
                          'AI추천': (rec == '추천').sum(), 'AI검토': (rec == '검토').sum(),
                          'AI비추천': (rec == '비추천').sum(), 'AI미분석': (rec == '').sum(),
                          '승인': (st == '승인').sum(), '제외': (st == '제외').sum(),
                          '미검토': (st == '미검토').sum()})
    summary = d.groupby('기업명').apply(agg, include_groups=False).reset_index()
    return summary, d


def main():
    ap = argparse.ArgumentParser(description="매칭·발송 데이터 내보내기 (읽기 전용)")
    ap.add_argument('--out', default=OUT_DEFAULT, help="내보낼 폴더")
    ap.add_argument('--round', action='store_true', help="이번 회차 폴더까지 만든다")
    args = ap.parse_args()

    global OUT
    OUT = args.out
    os.makedirs(OUT, exist_ok=True)
    creds = get_creds()
    today = datetime.today().strftime('%Y%m%d')
    print(f"내보낼 곳: {OUT}\n드라이브에서 읽는 중 (쓰기 없음)\n")

    # ── 01 선정기업 ──
    print("01_선정기업")
    df_c, mt = read_excel(creds, "선정기업_명단.xlsx")
    if not df_c.empty:
        save(df_c, os.path.join(OUT, "01_선정기업", f"선정기업_명단_{mt or today}.xlsx"))
    else:
        print("    선정기업_명단.xlsx 없음")

    # ── 02 공고수집 ──
    print("02_공고수집")
    for name, label in (("notices_db.xlsx", "공고목록"), ("notices_detail.xlsx", "공고전문")):
        df, mt = read_excel(creds, name)
        if not df.empty:
            save(df, os.path.join(OUT, "02_공고수집", f"{label}_{mt or today}.xlsx"))

    # ── 04 누적 ──
    print("04_누적")
    df_h, _ = read_excel(creds, "send_history.xlsx")
    if not df_h.empty:
        save(df_h, os.path.join(OUT, "04_누적", "발송이력_전체.xlsx"))
    dec, _ = read_json(creds, "decision_log.json")
    rows = dec.get('rows', []) if isinstance(dec, dict) else (dec or [])
    if rows:
        d = pd.DataFrame(rows)
        sheets = {'전체': d}
        if '회차ID' in d.columns:
            sheets['회차별요약'] = d.groupby('회차ID').agg(
                매칭건수=('공고ID', 'count'),
                승인=('최종결정', lambda s: (s == '승인').sum()),
                제외=('최종결정', lambda s: (s == '제외').sum()),
                발송=('발송여부', lambda s: s.isin(['Y', '참고']).sum()),
                클릭=('클릭여부', lambda s: (s == 'Y').sum())).reset_index()
        save(d, os.path.join(OUT, "04_누적", "판단기록.xlsx"), sheets=sheets)
    # 클릭 로그 (구글 시트)
    try:
        r = gapi(creds, 'GET', "https://sheets.googleapis.com/v4/spreadsheets/"
                               f"{CLICK_LOG_SHEET_ID}/values/A:D")
        vals = r.json().get('values', []) if r.ok else []
        if len(vals) >= 2:
            hdr = vals[0]
            body = [v + [''] * (len(hdr) - len(v)) for v in vals[1:]]
            save(pd.DataFrame(body, columns=hdr),
                 os.path.join(OUT, "04_누적", "클릭추적_로그.xlsx"))
    except Exception as e:
        print(f"    클릭 로그 건너뜀: {str(e)[:60]}")

    # ── 03 회차 ──
    if args.round:
        ms, _ = read_json(creds, "match_state.json")
        results = ms.get('match_results', []) or []
        rid = ms.get('round_id') or today
        rv_f, _ = read_json(creds, "review_state.json")
        rv = rv_f.get('review_state', {}) or {}
        ai = ms.get('ai_analysis', {}) or {}
        sp, _ = read_json(creds, "send_progress.json")

        # 매칭 산출물은 매칭 회차 폴더에
        print(f"03_회차 / {rid}  (매칭)")
        if not results and not rv:
            # 발송이 끝나면 매칭 상태가 비워지고 새 회차 ID만 잡힌다. 그대로 두면
            # 내용 없는 폴더가 회차마다 쌓여 어느 게 실제 회차인지 헷갈린다.
            print("    매칭 결과·승인 상태가 모두 비어 있음 — 폴더를 만들지 않습니다")
        else:
            rdir = os.path.join(OUT, "03_회차", str(rid))
            os.makedirs(rdir, exist_ok=True)
            if results:
                summary, detail = build_diag(results, ai, rv)
                save(detail, os.path.join(rdir, "매칭결과.xlsx"))
                save(detail, os.path.join(rdir, "진단.xlsx"),
                     sheets={'기업별요약': summary, '매칭상세': detail})
            else:
                print("    매칭 결과가 비어 있음 — 승인 상태만 저장합니다")
            with open(os.path.join(rdir, "승인상태.json"), 'w', encoding='utf-8') as fp:
                json.dump({'round_id': rid, 'review_state': rv,
                           'decision_src': rv_f.get('decision_src', {})},
                          fp, ensure_ascii=False, indent=2)
            print(f"    저장  03_회차/{rid}/승인상태.json  ({len(rv):,}건)")

        # 발송 산출물은 '발송이 일어난 회차' 폴더에 넣는다.
        # send_progress 는 매칭 회차보다 뒤처질 수 있다(이번 회차는 아직 발송 전).
        if sp:
            s_rid = sp.get('round_id') or rid
            sdir = os.path.join(OUT, "03_회차", str(s_rid))
            os.makedirs(sdir, exist_ok=True)
            if s_rid != rid:
                print(f"03_회차 / {s_rid}  (발송 — 매칭 회차와 다름)")
            with open(os.path.join(sdir, "발송진행.json"), 'w', encoding='utf-8') as fp:
                json.dump(sp, fp, ensure_ascii=False, indent=2)
            print(f"    저장  03_회차/{s_rid}/발송진행.json  ({len(sp.get('sent',{})):,}개사)")
            # 그 회차에 실제로 나간 날짜로만 이력을 거른다
            sent_days = sorted({str(v.get('at', ''))[:10]
                                for v in sp.get('sent', {}).values() if v.get('at')})
            if sent_days and not df_h.empty and '발송일' in df_h.columns:
                cur = df_h[df_h['발송일'].isin(sent_days)]
                if not cur.empty:
                    save(cur, os.path.join(sdir, f"발송이력_{sent_days[-1]}.xlsx"))

    # ── README ──
    with open(os.path.join(OUT, "00_README.txt"), 'w', encoding='utf-8') as fp:
        fp.write(f"""원스톱 스케일업 맞춤형공고 — 데이터 보관

이 폴더는 구글드라이브(스케일업_매칭시스템)의 운영 데이터를 복사해 둔 것입니다.
export_data.py 로 만들며, 그대로 NAS 공유 폴더에 복사해 쓰면 됩니다.

01_선정기업/   선정기업 명단 (선정 50 / 예비 20)
02_공고수집/   기업마당에서 수집한 공고 목록과 공고 전문
03_회차/       회차별 스냅샷 — 매칭 결과, AI 판정, 승인·제외 상태, 발송 이력
               (드라이브 원본은 매 회차 덮어쓰므로 여기에만 남습니다)
04_누적/       발송 이력 전체, 판단 기록(회차별 결정·클릭·반응), 클릭 추적 로그

마지막 내보낸 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}
""")
    print(f"\n완료 — {OUT}")
    print("드라이브에는 아무것도 쓰지 않았습니다.")


if __name__ == '__main__':
    main()
