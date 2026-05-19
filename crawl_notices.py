"""
기업마당 공고 전문 크롤러
GitHub Actions에서 매주 수요일 오전 10시(KST) 자동 실행
→ notices_db.xlsx의 공고 URL 크롤링
→ 전문 내용 → notices_detail.xlsx로 드라이브 저장
"""

import os, json, io, time, re
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ── 설정 ──────────────────────────────────────────────
DRIVE_FOLDER_ID = "1iWGYjaoslqST45ggDlg-IPMLaUHCYmV_"
NOTICES_FILE    = "notices_db.xlsx"
DETAIL_FILE     = "notices_detail.xlsx"
SCOPES = [
    'https://www.googleapis.com/auth/drive',
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.bizinfo.go.kr/",
}

# ── 구글 인증 ─────────────────────────────────────────
def get_creds():
    """GitHub Secrets 또는 로컬 token.json에서 인증"""
    token_json = os.environ.get('GOOGLE_TOKEN_JSON', '')
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        raise Exception("인증 정보 없음: GOOGLE_TOKEN_JSON 환경변수 또는 token.json 필요")
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds

def gapi(method, url, creds, **kwargs):
    headers = kwargs.pop('headers', {})
    headers['Authorization'] = f'Bearer {creds.token}'
    return requests.request(method, url, headers=headers, **kwargs)

# ── 드라이브 유틸 ─────────────────────────────────────
def drive_file_id(creds, filename):
    params = {
        'q': f"name='{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed=false",
        'fields': 'files(id,name)',
        'orderBy': 'modifiedTime desc',
    }
    resp = gapi('GET', 'https://www.googleapis.com/drive/v3/files', creds, params=params)
    files = resp.json().get('files', [])
    return files[0]['id'] if files else None

def drive_download(creds, filename):
    fid = drive_file_id(creds, filename)
    if not fid: return None
    resp = gapi('GET', f'https://www.googleapis.com/drive/v3/files/{fid}', creds, params={'alt':'media'})
    return resp.content if resp.ok else None

def drive_upload(creds, filename, content_bytes, mime):
    fid  = drive_file_id(creds, filename)
    bnd  = b"----MIMEBoundary"; crlf = b"\r\n"
    ct   = "multipart/related; boundary=----MIMEBoundary"
    if fid:
        meta = json.dumps({"name": filename}).encode()
    else:
        meta = json.dumps({"name": filename, "parents": [DRIVE_FOLDER_ID]}).encode()
    body  = b"--" + bnd + crlf
    body += b"Content-Type: application/json; charset=UTF-8" + crlf + crlf
    body += meta + crlf
    body += b"--" + bnd + crlf
    body += mime.encode() + crlf + crlf
    body += content_bytes + crlf
    body += b"--" + bnd + b"--"
    if fid:
        resp = gapi('PATCH', f'https://www.googleapis.com/upload/drive/v3/files/{fid}',
                    creds, params={'uploadType':'multipart'}, data=body, headers={'Content-Type':ct})
    else:
        resp = gapi('POST', 'https://www.googleapis.com/upload/drive/v3/files',
                    creds, params={'uploadType':'multipart'}, data=body, headers={'Content-Type':ct})
    return resp.ok

# ── 공고 크롤링 ───────────────────────────────────────
def crawl_notice(url, pid):
    """공고 원문 페이지에서 전문 추출"""
    try:
        session = requests.Session()
        session.get("https://www.bizinfo.go.kr/", headers=HEADERS, timeout=10)
        resp = session.get(url, headers=HEADERS, timeout=20)

        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, 'html.parser')

        # 전문 텍스트 추출 (다양한 선택자 시도)
        full_text = ""
        for selector in ['.view-content', '.detail-content', '#bizSumryCn',
                         '.bbs-view-content', '.content', '#content',
                         '.board-view', 'article', '.view-area']:
            el = soup.select_one(selector)
            if el:
                full_text = el.get_text(separator='\n', strip=True)
                if len(full_text) > 200:
                    break

        # 전문이 없으면 body 전체에서 추출
        if len(full_text) < 100:
            body = soup.find('body')
            if body:
                # 네비게이션, 헤더 제거
                for tag in body.find_all(['nav','header','footer','script','style']):
                    tag.decompose()
                full_text = body.get_text(separator='\n', strip=True)

        # 지원금액 패턴 추출
        amount = ""
        amount_patterns = [
            r'지원\s*(?:금액|한도)[^\d]*(\d[\d,억만원\s]+)',
            r'최대\s*(\d[\d,억만원\s]+)',
            r'(\d+억[원\s])',
        ]
        for pat in amount_patterns:
            m = re.search(pat, full_text)
            if m:
                amount = m.group(0)[:30]
                break

        # 선정규모 패턴 추출
        scale = ""
        scale_patterns = [
            r'(\d+)\s*개\s*(?:사|업체|기업)\s*(?:내외|이내|선정)',
            r'선정\s*(?:규모|예정)[^\d]*(\d+)',
        ]
        for pat in scale_patterns:
            m = re.search(pat, full_text)
            if m:
                scale = m.group(0)[:30]
                break

        return {
            'pblancId':  pid,
            '전문내용':  full_text[:3000],  # 최대 3000자
            '지원금액':  amount,
            '선정규모':  scale,
            '크롤링일':  datetime.today().strftime('%Y-%m-%d'),
            '크롤링성공': 'Y',
        }

    except Exception as e:
        print(f"  크롤링 실패 ({pid}): {e}")
        return {
            'pblancId':  pid,
            '전문내용':  '',
            '지원금액':  '',
            '선정규모':  '',
            '크롤링일':  datetime.today().strftime('%Y-%m-%d'),
            '크롤링성공': 'N',
        }

# ── 메인 ─────────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 크롤링 시작")

    # 인증
    creds = get_creds()
    print("✅ 구글 인증 완료")

    # notices_db 다운로드
    content = drive_download(creds, NOTICES_FILE)
    if not content:
        print("❌ notices_db.xlsx 없음")
        return

    df_n = pd.read_excel(io.BytesIO(content), dtype=str).fillna('')
    print(f"✅ 공고 DB 로드: {len(df_n):,}건")

    # 기존 크롤링 결과 로드
    detail_content = drive_download(creds, DETAIL_FILE)
    if detail_content:
        df_detail = pd.read_excel(io.BytesIO(detail_content), dtype=str).fillna('')
        already_crawled = set(df_detail['pblancId'].tolist())
        print(f"✅ 기존 크롤링 결과: {len(df_detail):,}건")
    else:
        df_detail = pd.DataFrame()
        already_crawled = set()

    # 크롤링 대상 필터링 (미수집 + 마감 안 지난 공고)
    today = datetime.today().strftime('%Y-%m-%d')
    df_target = df_n[
        (~df_n['pblancId'].isin(already_crawled)) &
        ((df_n['마감일'] == '') | (df_n['마감일'] >= today))
    ].copy()

    print(f"📋 크롤링 대상: {len(df_target)}건 (전체 {len(df_n)}건 중 미수집·유효)")

    if df_target.empty:
        print("✅ 새로 크롤링할 공고 없음")
        return

    # 크롤링 실행
    new_records = []
    success, fail = 0, 0

    for i, (_, row) in enumerate(df_target.iterrows()):
        url = row.get('공고링크', '')
        pid = row.get('pblancId', '')
        if not url or not pid:
            continue

        print(f"  [{i+1}/{len(df_target)}] {row.get('공고명','')[:30]}...", end=' ')
        result = crawl_notice(url, pid)

        if result:
            new_records.append(result)
            if result['크롤링성공'] == 'Y':
                success += 1; print("✅")
            else:
                fail += 1; print("❌")
        else:
            fail += 1; print("❌")

        # 서버 부하 방지
        time.sleep(1.2)

    # 결과 저장
    if new_records:
        df_new = pd.DataFrame(new_records)
        if not df_detail.empty:
            df_out = pd.concat([df_detail, df_new], ignore_index=True)
        else:
            df_out = df_new

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as w:
            df_out.to_excel(w, index=False)

        if drive_upload(creds, DETAIL_FILE, buf.getvalue(),
                        'Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'):
            print(f"\n✅ 저장 완료: {DETAIL_FILE} ({len(df_out):,}건)")
        else:
            print("\n❌ 드라이브 저장 실패")

    print(f"\n완료 — 성공: {success} / 실패: {fail}")

if __name__ == "__main__":
    main()
