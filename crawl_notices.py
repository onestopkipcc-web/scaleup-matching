"""
기업마당 공고 전문 크롤러 (Playwright 버전)
GitHub Actions에서 매주 수요일 오전 10시(KST) 자동 실행
실제 브라우저로 JS 렌더링 페이지 파싱
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

# ── 구글 인증 ─────────────────────────────────────────
def get_creds():
    token_json = os.environ.get('GOOGLE_TOKEN_JSON', '')
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        raise Exception("인증 정보 없음")
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds

def gapi(method, url, creds, **kwargs):
    headers = kwargs.pop('headers', {})
    headers['Authorization'] = f'Bearer {creds.token}'
    return requests.request(method, url, headers=headers, **kwargs)

def drive_file_id(creds, filename):
    params = {'q': f"name='{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed=false",
              'fields': 'files(id,name)', 'orderBy': 'modifiedTime desc'}
    resp = gapi('GET', 'https://www.googleapis.com/drive/v3/files', creds, params=params)
    return resp.json().get('files', [{}])[0].get('id') if resp.ok else None

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

# ── Playwright로 JS 렌더링 페이지 파싱 ───────────────
def crawl_with_playwright(url, pid):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page.goto("https://www.bizinfo.go.kr/", timeout=15000)
            page.goto(url, timeout=20000, wait_until="networkidle")
            time.sleep(1.5)  # 추가 렌더링 대기

            # 전문 내용 추출 (다양한 선택자 시도)
            full_text = ""
            selectors = [
                '#bizSumryCn', '.biz_sumry_cn',
                '.view_con', '.view-con', '.view_content',
                '.bbs_view_con', '.detail_content',
                '#viewContent', 'article .content',
                '.inner_content', '#content .view',
            ]
            for sel in selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        text = el.inner_text()
                        if len(text) > 200:
                            full_text = text
                            break
                except:
                    continue

            # 선택자 실패 시 body 전체
            if len(full_text) < 200:
                try:
                    full_text = page.inner_text('body')
                except:
                    pass

            browser.close()

            if len(full_text) > 200:
                amount, scale = extract_meta(full_text)
                return {
                    'pblancId': pid, '전문내용': full_text[:3000],
                    '지원금액': amount, '선정규모': scale,
                    '크롤링방법': 'Playwright',
                    '크롤링일': datetime.today().strftime('%Y-%m-%d'),
                    '크롤링성공': 'Y',
                }
    except Exception as e:
        print(f"    Playwright 오류: {e}")

    return {
        'pblancId': pid, '전문내용': '', '지원금액': '', '선정규모': '',
        '크롤링방법': 'FAIL',
        '크롤링일': datetime.today().strftime('%Y-%m-%d'),
        '크롤링성공': 'N',
    }

# ── 메인 ─────────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 크롤링 시작")
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
        # 성공한 것만 already_crawled로 처리 (실패는 재시도)
        already_crawled = set(df_detail[df_detail['크롤링성공']=='Y']['pblancId'].tolist())
        print(f"✅ 기존 전문 DB: {len(df_detail):,}건 (성공 {len(already_crawled)}건)")
    else:
        df_detail = pd.DataFrame()
        already_crawled = set()

    today = datetime.today().strftime('%Y-%m-%d')
    df_target = df_n[
        (~df_n['pblancId'].isin(already_crawled)) &
        ((df_n['마감일'] == '') | (df_n['마감일'] >= today))
    ].copy()

    limit = int(os.environ.get('CRAWL_LIMIT', 0))
    if limit > 0:
        df_target = df_target.head(limit)

    print(f"📋 크롤링 대상: {len(df_target)}건")
    if df_target.empty:
        print("✅ 새로 크롤링할 공고 없음"); return

    new_records = []
    success = fail = 0

    for i, (_, row) in enumerate(df_target.iterrows()):
        url = row.get('공고링크', '')
        pid = row.get('pblancId', '')
        name = row.get('공고명', '')[:30]
        if not url or not pid: continue

        result = crawl_with_playwright(url, pid)
        new_records.append(result)

        if result['크롤링성공'] == 'Y':
            success += 1
            print(f"  [{i+1}/{len(df_target)}] ✅ {name} ({len(result['전문내용'])}자)")
        else:
            fail += 1
            print(f"  [{i+1}/{len(df_target)}] ❌ {name}")

        time.sleep(1.0)

    # 기존 실패 건 교체 + 신규 추가
    if new_records:
        df_new = pd.DataFrame(new_records)
        if not df_detail.empty:
            new_pids = set(df_new['pblancId'].tolist())
            df_out = pd.concat(
                [df_detail[~df_detail['pblancId'].isin(new_pids)], df_new],
                ignore_index=True
            )
        else:
            df_out = df_new

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as w:
            df_out.to_excel(w, index=False)

        if drive_upload(creds, DETAIL_FILE, buf.getvalue()):
            print(f"\n✅ 저장 완료 — 총 {len(df_out):,}건 (성공 {success} / 실패 {fail})")
        else:
            print("\n❌ 드라이브 저장 실패")

if __name__ == "__main__":
    main()
