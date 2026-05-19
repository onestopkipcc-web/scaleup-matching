"""
기업마당 공고 전문 크롤러
GitHub Actions에서 매주 수요일 오전 10시(KST) 자동 실행

전략:
1. bizinfo API detail 엔드포인트 시도 (pblancId 파라미터)
2. API 실패 시 HTML 크롤링 (여러 선택자 시도)
3. 둘 다 실패 시 실패 기록
"""

import os, json, io, time, re
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

DRIVE_FOLDER_ID = "1iWGYjaoslqST45ggDlg-IPMLaUHCYmV_"
NOTICES_FILE    = "notices_db.xlsx"
DETAIL_FILE     = "notices_detail.xlsx"
API_KEY         = "Nt604D"
API_URL         = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
SCOPES          = ['https://www.googleapis.com/auth/drive']

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.bizinfo.go.kr/",
    "Connection": "keep-alive",
}

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
    files = resp.json().get('files', [])
    return files[0]['id'] if files else None

def drive_download(creds, filename):
    fid = drive_file_id(creds, filename)
    if not fid: return None
    resp = gapi('GET', f'https://www.googleapis.com/drive/v3/files/{fid}', creds, params={'alt':'media'})
    return resp.content if resp.ok else None

def drive_upload(creds, filename, content_bytes):
    mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    fid  = drive_file_id(creds, filename)
    bnd  = b"----MIMEBoundary"; crlf = b"\r\n"
    ct   = "multipart/related; boundary=----MIMEBoundary"
    meta = json.dumps({"name": filename} if fid else {"name": filename, "parents": [DRIVE_FOLDER_ID]}).encode()
    body  = b"--" + bnd + crlf + b"Content-Type: application/json; charset=UTF-8" + crlf + crlf
    body += meta + crlf + b"--" + bnd + crlf + mime.encode() + crlf + crlf
    body += content_bytes + crlf + b"--" + bnd + b"--"
    url   = f'https://www.googleapis.com/upload/drive/v3/files/{fid}' if fid else \
            'https://www.googleapis.com/upload/drive/v3/files'
    method = 'PATCH' if fid else 'POST'
    resp  = gapi(method, url, creds, params={'uploadType':'multipart'},
                 data=body, headers={'Content-Type': ct})
    return resp.ok

def extract_numbers(text):
    """지원금액·선정규모 추출"""
    amount, scale = "", ""
    # 지원금액
    for pat in [
        r'지원.{0,4}(?:금액|한도)[^0-9]*([0-9][0-9,백천억만원 ]+)',
        r'최대.{0,3}([0-9][0-9,백천억만원 ]+)',
        r'([0-9]+억\s*원)',
    ]:
        m = re.search(pat, text)
        if m: amount = m.group(0)[:40]; break
    # 선정규모
    for pat in [
        r'([0-9]+).{0,3}개.{0,5}(?:사|업체|기업).{0,6}(?:내외|이내|선정)',
        r'선정.{0,6}(?:규모|예정)[^0-9]*([0-9]+)',
        r'([0-9]+)\s*개사',
    ]:
        m = re.search(pat, text)
        if m: scale = m.group(0)[:40]; break
    return amount, scale

def fetch_via_api(pid):
    """방법 1: API로 단건 상세 조회"""
    try:
        # 방법 1-A: pblancId 직접 파라미터
        params = {"crtfcKey": API_KEY, "dataType": "json", "pblancId": pid}
        resp = requests.get(API_URL, params=params, timeout=15)
        if resp.ok:
            data = resp.json()
            items = data.get('jsonArray', [])
            if items:
                item = items[0]
                text = item.get('bsnsSumryCn', '')
                if text and len(text) > 100:
                    return text, True

        # 방법 1-B: 공고명으로 검색 후 매칭
        # (API가 단건 조회를 지원하지 않을 경우 대비)
        return "", False
    except:
        return "", False

def fetch_via_html(url, pid):
    """방법 2: HTML 크롤링"""
    try:
        session = requests.Session()
        # 메인 페이지 먼저 방문 (쿠키 획득)
        session.get("https://www.bizinfo.go.kr/", headers=HEADERS, timeout=10)
        time.sleep(0.5)

        resp = session.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return "", False

        soup = BeautifulSoup(resp.text, 'html.parser')

        # 스크립트·스타일 제거
        for tag in soup.find_all(['script','style','nav','header','footer']):
            tag.decompose()

        full_text = ""

        # 선택자 우선순위 시도
        selectors = [
            '#bizSumryCn', '.biz_sumry_cn', '.bizSumryCn',
            '.view_con', '.view-con', '.view_content', '.view-content',
            '.bbs_view_con', '.bbs-view-con',
            '.detail_content', '.detail-content',
            '.board_view', '.board-view',
            '#viewContent', '.viewContent',
            'article', 'main',
            '#content .inner', '#content',
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator=' ', strip=True)
                if len(text) > 200:
                    full_text = text
                    break

        # 선택자 실패 시 body 전체에서 추출
        if len(full_text) < 100:
            body = soup.find('body')
            if body:
                full_text = body.get_text(separator=' ', strip=True)
                # 너무 짧으면 JS 렌더링 문제로 판단
                if len(full_text) < 200:
                    return "", False

        return full_text[:3000], True
    except Exception as e:
        return "", False

def crawl_notice(url, pid):
    """API → HTML 순서로 전문 취득"""
    # 방법 1: API 시도
    text, ok = fetch_via_api(pid)
    method_used = "API"

    # 방법 2: HTML 크롤링
    if not ok or len(text) < 100:
        text, ok = fetch_via_html(url, pid)
        method_used = "HTML"

    amount, scale = extract_numbers(text) if text else ("", "")

    return {
        'pblancId':   pid,
        '전문내용':   text[:3000] if text else '',
        '지원금액':   amount,
        '선정규모':   scale,
        '크롤링방법': method_used,
        '크롤링일':   datetime.today().strftime('%Y-%m-%d'),
        '크롤링성공': 'Y' if (ok and len(text) > 100) else 'N',
    }

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
        already_crawled = set(df_detail['pblancId'].tolist())
        print(f"✅ 기존 전문 DB: {len(df_detail):,}건")
    else:
        df_detail = pd.DataFrame()
        already_crawled = set()

    today = datetime.today().strftime('%Y-%m-%d')
    df_target = df_n[
        (~df_n['pblancId'].isin(already_crawled)) &
        ((df_n['마감일'] == '') | (df_n['마감일'] >= today))
    ].copy()

    # 환경변수로 최대 건수 제한 (GitHub Actions: 전체, 수동: 50)
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

        result = crawl_notice(url, pid)
        new_records.append(result)

        if result['크롤링성공'] == 'Y':
            success += 1
            print(f"  [{i+1}/{len(df_target)}] ✅ {name} ({result['크롤링방법']}, {len(result['전문내용'])}자)")
        else:
            fail += 1
            print(f"  [{i+1}/{len(df_target)}] ❌ {name}")

        time.sleep(1.2)

    if new_records:
        df_new = pd.DataFrame(new_records)
        df_out = pd.concat([df_detail, df_new], ignore_index=True) if not df_detail.empty else df_new

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as w:
            df_out.to_excel(w, index=False)

        if drive_upload(creds, DETAIL_FILE, buf.getvalue()):
            print(f"\n✅ 저장 완료: {len(df_out):,}건 (성공 {success} / 실패 {fail})")
        else:
            print("\n❌ 드라이브 저장 실패")

if __name__ == "__main__":
    main()
