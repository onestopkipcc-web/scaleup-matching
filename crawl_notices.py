"""
기업마당 공고 전문 크롤러 (Playwright 버전)
GitHub Actions에서 매일 09:30(KST) 자동 실행
- 브라우저 1회 기동 후 재사용 (건당 launch 제거)
- 배치 저장 (중단돼도 진행분 보존)
- 시간 예산 초과 시 안전 종료 → 다음 실행이 이어서 처리
"""
import os, json, io, time, re
import requests
import pandas as pd
from datetime import datetime

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

DRIVE_FOLDER_ID = "1iWGYjaoslqST45ggDlg-IPMLaUHCYmV_"
NOTICES_FILE    = "notices_db.xlsx"
DETAIL_FILE     = "notices_detail.xlsx"
SCOPES          = ['https://www.googleapis.com/auth/drive']

# ── 운영 파라미터 (환경변수로 조정 가능) ──────────────
def _env_int(key, default):
    """빈 문자열/미설정/오타 모두 안전하게 처리."""
    raw = os.environ.get(key, '')
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default

CRAWL_LIMIT   = _env_int('CRAWL_LIMIT', 0)      # 0 = 전체
BATCH_SIZE    = _env_int('BATCH_SIZE', 25)      # N건마다 드라이브 저장
TIME_BUDGET_M = _env_int('TIME_BUDGET_MIN', 90) # 이 시간 넘으면 안전 종료
PAGE_DELAY    = float(os.environ.get('PAGE_DELAY', '0.5') or 0.5)

START_TS = time.time()

def budget_exceeded():
    return (time.time() - START_TS) > TIME_BUDGET_M * 60

# ── 구글 인증 ─────────────────────────────────────────
def get_creds():
    token_json = os.environ.get('GOOGLE_TOKEN_JSON', '')
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        raise Exception("인증 정보 없음 (GOOGLE_TOKEN_JSON 미설정)")
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds

def gapi(method, url, creds, **kwargs):
    headers = kwargs.pop('headers', {})
    headers['Authorization'] = f'Bearer {creds.token}'
    return requests.request(method, url, headers=headers, timeout=60, **kwargs)

def drive_file_id(creds, filename):
    params = {'q': f"name='{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed=false",
              'fields': 'files(id,name)', 'orderBy': 'modifiedTime desc'}
    resp = gapi('GET', 'https://www.googleapis.com/drive/v3/files', creds, params=params)
    files = resp.json().get('files', []) if resp.ok else []
    return files[0].get('id') if files else None

def drive_download(creds, filename):
    fid = drive_file_id(creds, filename)
    if not fid: return None
    resp = gapi('GET', f'https://www.googleapis.com/drive/v3/files/{fid}',
                creds, params={'alt': 'media'})
    return resp.content if resp.ok else None

def drive_upload(creds, filename, content_bytes):
    mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    fid  = drive_file_id(creds, filename)
    bnd  = b"----MIMEBoundary"; crlf = b"\r\n"
    ct   = "multipart/related; boundary=----MIMEBoundary"
    meta = json.dumps({"name": filename} if fid else
                      {"name": filename, "parents": [DRIVE_FOLDER_ID]}).encode()
    body  = b"--" + bnd + crlf + b"Content-Type: application/json; charset=UTF-8" + crlf + crlf
    body += meta + crlf + b"--" + bnd + crlf + mime.encode() + crlf + crlf
    body += content_bytes + crlf + b"--" + bnd + b"--"
    url    = (f'https://www.googleapis.com/upload/drive/v3/files/{fid}'
              if fid else 'https://www.googleapis.com/upload/drive/v3/files')
    resp   = gapi('PATCH' if fid else 'POST', url, creds,
                  params={'uploadType': 'multipart'},
                  data=body, headers={'Content-Type': ct})
    if not resp.ok:
        print(f"    드라이브 업로드 실패: {resp.status_code} {resp.text[:200]}")
    return resp.ok

# ── 텍스트에서 지원금액·규모 추출 ────────────────────
def extract_meta(text):
    amount, scale = "", ""
    for pat in [r'지원.{0,4}(?:금액|한도)[^0-9]*([0-9][0-9,백천억만원 ]+)',
                r'최대.{0,3}([0-9][0-9,백천억만원 ]+)', r'([0-9]+억\s*원)']:
        m = re.search(pat, text)
        if m: amount = m.group(0)[:40]; break
    for pat in [r'([0-9]+).{0,3}개.{0,5}(?:사|업체|기업).{0,6}(?:내외|이내|선정)',
                r'선정.{0,6}(?:규모|예정)[^0-9]*([0-9]+)', r'([0-9]+)\s*개사']:
        m = re.search(pat, text)
        if m: scale = m.group(0)[:40]; break
    return amount, scale

SELECTORS = [
    '#bizSumryCn', '.biz_sumry_cn',
    '.view_con', '.view-con', '.view_content',
    '.bbs_view_con', '.detail_content',
    '#viewContent', 'article .content',
    '.inner_content', '#content .view',
]

def fail_record(pid, why=''):
    return {'pblancId': pid, '전문내용': '', '지원금액': '', '선정규모': '',
            '크롤링방법': 'FAIL',
            '크롤링일': datetime.today().strftime('%Y-%m-%d'),
            '크롤링성공': 'N'}

def crawl_one(page, url, pid):
    """페이지 객체를 재사용 — 브라우저를 매번 띄우지 않는다."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass  # networkidle 미도달해도 본문은 있을 수 있음

        full_text = ""
        for sel in SELECTORS:
            try:
                el = page.query_selector(sel)
                if el:
                    text = el.inner_text()
                    if len(text) > 200:
                        full_text = text
                        break
            except Exception:
                continue
        if len(full_text) < 200:
            try:
                full_text = page.inner_text('body')
            except Exception:
                pass

        if len(full_text) > 200:
            amount, scale = extract_meta(full_text)
            return {'pblancId': pid, '전문내용': full_text[:3000],
                    '지원금액': amount, '선정규모': scale,
                    '크롤링방법': 'Playwright',
                    '크롤링일': datetime.today().strftime('%Y-%m-%d'),
                    '크롤링성공': 'Y'}
        return fail_record(pid, 'short')
    except Exception as e:
        print(f"    오류: {str(e)[:120]}")
        return fail_record(pid, 'exc')

def merge_and_upload(creds, df_detail, records):
    """기존 DB에 병합 후 업로드. 성공 시 갱신된 df_detail 반환."""
    if not records:
        return df_detail
    df_new = pd.DataFrame(records)
    if not df_detail.empty:
        new_pids = set(df_new['pblancId'].tolist())
        df_out = pd.concat([df_detail[~df_detail['pblancId'].isin(new_pids)], df_new],
                           ignore_index=True)
    else:
        df_out = df_new
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df_out.to_excel(w, index=False)
    if drive_upload(creds, DETAIL_FILE, buf.getvalue()):
        print(f"  💾 중간 저장 — 누적 {len(df_out):,}건")
        return df_out
    print("  ⚠️ 중간 저장 실패 (다음 배치에서 재시도)")
    return df_detail

# ── 메인 ─────────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 크롤링 시작 "
          f"(limit={CRAWL_LIMIT or '전체'}, batch={BATCH_SIZE}, budget={TIME_BUDGET_M}분)")
    creds = get_creds()
    print("✅ 구글 인증 완료")

    content = drive_download(creds, NOTICES_FILE)
    if not content:
        print("❌ notices_db.xlsx 없음"); return

    df_n = pd.read_excel(io.BytesIO(content), dtype=str).fillna('')
    print(f"✅ 공고 DB: {len(df_n):,}건")

    detail_content = drive_download(creds, DETAIL_FILE)
    if detail_content:
        df_detail = pd.read_excel(io.BytesIO(detail_content), dtype=str).fillna('')
        already = set(df_detail[df_detail['크롤링성공'] == 'Y']['pblancId'].tolist())
        print(f"✅ 기존 전문 DB: {len(df_detail):,}건 (성공 {len(already):,}건)")
    else:
        df_detail = pd.DataFrame()
        already = set()

    today = datetime.today().strftime('%Y-%m-%d')
    df_target = df_n[
        (~df_n['pblancId'].isin(already)) &
        ((df_n['마감일'] == '') | (df_n['마감일'] >= today))
    ].copy()

    # 마감 임박 순 — 마감 지나 못 긁는 사태 방지
    if '마감일' in df_target.columns:
        df_target['_d'] = df_target['마감일'].replace('', '9999-99-99')
        df_target = df_target.sort_values('_d').drop(columns=['_d'])

    if CRAWL_LIMIT > 0:
        df_target = df_target.head(CRAWL_LIMIT)

    print(f"📋 크롤링 대상: {len(df_target):,}건")
    if df_target.empty:
        print("✅ 새로 크롤링할 공고 없음"); return

    from playwright.sync_api import sync_playwright
    records = []; success = fail = done = 0
    stopped_early = False

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page.set_default_timeout(20000)
        try:
            page.goto("https://www.bizinfo.go.kr/", timeout=20000)  # 세션 1회만
        except Exception:
            pass

        for i, (_, row) in enumerate(df_target.iterrows()):
            if budget_exceeded():
                print(f"\n⏰ 시간 예산 {TIME_BUDGET_M}분 초과 — 안전 종료 "
                      f"(남은 {len(df_target)-i:,}건은 다음 실행에서 처리)")
                stopped_early = True
                break

            url = row.get('공고링크', ''); pid = row.get('pblancId', '')
            name = str(row.get('공고명', ''))[:30]
            if not url or not pid:
                continue

            res = crawl_one(page, url, pid)
            records.append(res); done += 1
            if res['크롤링성공'] == 'Y':
                success += 1
                print(f"  [{i+1}/{len(df_target)}] ✅ {name} ({len(res['전문내용'])}자)")
            else:
                fail += 1
                print(f"  [{i+1}/{len(df_target)}] ❌ {name}")

            if len(records) >= BATCH_SIZE:
                df_detail = merge_and_upload(creds, df_detail, records)
                records = []

            time.sleep(PAGE_DELAY)

        browser.close()

    if records:
        df_detail = merge_and_upload(creds, df_detail, records)

    elapsed = (time.time() - START_TS) / 60
    print(f"\n{'⏸️ 부분 완료' if stopped_early else '✅ 완료'} — "
          f"처리 {done:,}건 (성공 {success:,} / 실패 {fail:,}) / {elapsed:.1f}분")

if __name__ == "__main__":
    main()
