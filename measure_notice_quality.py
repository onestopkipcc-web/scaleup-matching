# -*- coding: utf-8 -*-
"""공고 데이터 품질 진단 — 드라이브를 읽기만 한다 (쓰기·업로드 없음).

매칭·AI 분석의 입력이 실제로 쓸 만한지 숫자로 확인한다.
작업5(AI 구조 개선)의 우선순위를 정할 때 쓴 지표를 그대로 다시 잴 수 있게 정리한 것.

실행 (프로젝트 폴더에서, token.json 필요):
    python measure_notice_quality.py            # 드라이브 데이터만 (빠름)
    python measure_notice_quality.py --files 20 # 공고문 파일 20건 내려받아 파싱까지

보는 지표
  1. 전문 DB 현황 · 길이 분포 · 크롤러 상한 절단율
  2. 자격 조건(지원대상·신청자격·제외대상)이 본문에 실제로 있는가
  3. 본문 중 사이트 네비게이션·푸터가 차지하는 비중
     (app.py 의 clean_notice_text() 를 그대로 떼어 써서 앱과 결과가 어긋나지 않는다)
  4. score_notice() 의 단어 기반 하드필터가 접수 중 공고 몇 건에 닿는가
  5. (--files) 공고문 파일 보유율 · 포맷 분포 · 자격 조건 포함률
"""
import os, io, re, ast, json, sys, time, zipfile, random, argparse
from collections import Counter
from datetime import datetime

import requests
import pandas as pd
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

DRIVE_FOLDER_ID = "1iWGYjaoslqST45ggDlg-IPMLaUHCYmV_"
NOTICES_FILE    = "notices_db.xlsx"
DETAIL_FILE     = "notices_detail.xlsx"
SCOPES          = ['https://www.googleapis.com/auth/drive']
APP_FILE        = "app.py"
CROP_AT         = 3000      # crawl_notices.py 의 전문 저장 상한
API_KEY         = "Nt604D"
API_URL         = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
REALMS          = ["01", "02", "03", "04", "05", "06", "07", "09"]
UA              = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

SEC_RE  = re.compile(r'지원\s*대상|신청\s*자격|참가\s*자격|지원\s*자격|'
                     r'제외\s*대상|지원\s*제외|신청\s*제외|지원\s*조건')
RD_RE   = re.compile(r'R&D|연구개발|기술개발과제|기초연구|원천기술')
COMM_RE = re.compile(r'사업화|상용화|판로|마케팅|수출')


# ── 인증·다운로드 (crawl_notices.py 와 같은 경로, 읽기 전용) ──
def get_creds():
    token_json = os.environ.get('GOOGLE_TOKEN_JSON', '')
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        sys.exit("인증 정보 없음 — 프로젝트 폴더에서 실행하세요 (token.json 필요)")
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def drive_download(creds, filename):
    h = {'Authorization': f'Bearer {creds.token}'}
    r = requests.get('https://www.googleapis.com/drive/v3/files', headers=h, timeout=120,
                     params={'q': f"name='{filename}' and '{DRIVE_FOLDER_ID}' in parents "
                                  f"and trashed=false",
                             'fields': 'files(id,name,size,modifiedTime)',
                             'orderBy': 'modifiedTime desc'})
    files = r.json().get('files', []) if r.ok else []
    if not files:
        return None, None
    f = files[0]
    r2 = requests.get(f"https://www.googleapis.com/drive/v3/files/{f['id']}",
                      headers=h, params={'alt': 'media'}, timeout=300)
    return (r2.content if r2.ok else None), f


def load_clean_notice_text():
    """app.py 의 clean_notice_text() 를 그대로 떼어 온다.
    앱은 Streamlit 이라 import 할 수 없어 소스만 잘라 실행한다 —
    앱에서 정리 규칙을 고치면 이 진단도 따라 바뀐다."""
    src = io.open(APP_FILE, encoding='utf-8').read()
    tree = ast.parse(src)
    lines = src.split('\n')
    g = {'re': re}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, 'id', '').startswith('_RE_NOTICE_') for t in node.targets):
            exec(compile('\n'.join(lines[node.lineno - 1:node.end_lineno]),
                         '<app.py>', 'exec'), g)
    fn = next(x for x in tree.body
              if isinstance(x, ast.FunctionDef) and x.name == 'clean_notice_text')
    exec(compile('\n'.join(lines[fn.lineno - 1:fn.end_lineno]), '<app.py>', 'exec'), g)
    return g['clean_notice_text']


def pct(a, b):
    return f"{a/b*100:5.1f}%" if b else "    —"


def head(title):
    print("\n" + "=" * 66)
    print(title)
    print("=" * 66)


# ── 1~4: 드라이브 데이터 진단 ─────────────────────────
def run_drive(creds):
    det, dmeta = drive_download(creds, DETAIL_FILE)
    if not det:
        sys.exit(f"{DETAIL_FILE} 을 읽지 못했습니다.")
    ntc, nmeta = drive_download(creds, NOTICES_FILE)
    df = pd.read_excel(io.BytesIO(det), dtype=str).fillna('')
    dn = pd.read_excel(io.BytesIO(ntc), dtype=str).fillna('') if ntc else pd.DataFrame()
    print(f"{DETAIL_FILE}  {int(dmeta.get('size',0)):,}B · 수정 {dmeta.get('modifiedTime','')[:10]}")
    if ntc:
        print(f"{NOTICES_FILE}      {int(nmeta.get('size',0)):,}B · 수정 {nmeta.get('modifiedTime','')[:10]}")

    df['_len'] = df['전문내용'].astype(str).str.len()
    body = df[(df.get('크롤링성공', '') == 'Y') & (df['_len'] >= 200)].copy()

    head("1. 전문 DB 현황 · 절단율")
    print(f"  전체 {len(df):,}행 · 크롤링성공 {int((df.get('크롤링성공','')=='Y').sum()):,}건 "
          f"· 전문 200자 이상 {len(body):,}건")
    cut = int((body['_len'] >= CROP_AT).sum())
    print(f"  크롤러 상한({CROP_AT:,}자) 절단   {cut:,}건  {pct(cut, len(body))}"
          "   ← 0이면 상한 상향 불필요")
    print(f"  최대 {int(body['_len'].max()):,}자 · 중앙값 {int(body['_len'].median()):,}자 "
          f"· 평균 {int(body['_len'].mean()):,}자")
    print("  분위: " + " · ".join(
        f"{int(q*100)}%={int(body['_len'].quantile(q)):,}" for q in (.25, .5, .75, .9)))

    head("2. 자격 조건이 본문에 있는가")
    txt = body['전문내용'].astype(str)
    hs = txt.str.contains(SEC_RE)
    att = txt.str.contains(r'첨부|붙임|공고문\s*다운|hwp|pdf|다운로드', regex=True, case=False)
    print(f"  자격 섹션 포함        {int(hs.sum()):,}건  {pct(int(hs.sum()), len(body))}")
    print(f"  첨부파일을 가리킴      {int(att.sum()):,}건  {pct(int(att.sum()), len(body))}")
    only = int(((~hs) & att).sum())
    print(f"  자격 없고 첨부만       {only:,}건  {pct(only, len(body))}"
          "   ← 본문만으로는 자격을 알 수 없는 공고")
    pos = txt.apply(lambda t: (lambda m: m.start() if m else -1)(SEC_RE.search(t)))
    if int(hs.sum()):
        fp = pos[hs.values]
        print(f"  첫 자격어 위치 중앙값  {int(fp.median()):,}자 "
              f"· 1,500자 이후 {int((fp >= 1500).sum()):,}건")

    head("3. 본문 중 네비게이션·푸터 비중 (app.py clean_notice_text 기준)")
    clean = load_clean_notice_text()
    cl = txt.map(clean)
    a, b = txt.str.len().sum(), cl.str.len().sum()
    print(f"  원문 {a:,}자 → 정리 후 {b:,}자   절감 {(1-b/a)*100:4.1f}%")
    print(f"  중앙값 {int(txt.str.len().median()):,} → {int(cl.str.len().median()):,}자")
    print(f"  정리 후 200자 미만     {int((cl.str.len() < 200).sum()):,}건  (0이어야 정상)")
    lost = sum(1 for o, c in zip(txt, cl) if SEC_RE.search(o) and not SEC_RE.search(c))
    print(f"  자격어를 잃은 건        {lost:,}건  (대부분 공고명에만 있던 경우 — 공고명은 별도 전달)")

    if dn.empty:
        return
    head("4. 단어 기반 하드필터의 사정거리 (접수 중 공고)")
    dn['pblancId'] = dn['pblancId'].astype(str).str.strip()
    body['pblancId'] = body['pblancId'].astype(str).str.strip()
    today = datetime.today().strftime('%Y-%m-%d')
    live = dn[(dn['마감일'] == '') | (dn['마감일'] >= today)]
    _d = body[['pblancId', '전문내용']].rename(columns={'전문내용': '_full'})
    m = live.merge(_d, on='pblancId', how='left').fillna('')
    m['_t'] = (m['공고명'] + ' ' + m['사업개요'] + ' ' + m['_full'] + ' '
               + m['해시태그'] + ' ' + m['주관기관'] + ' ' + m['지원대상'])
    N = len(m)
    print(f"  접수 중 공고 {N:,}건 · 전문 보유 {int((m['_full'].str.len()>=200).sum()):,}건")
    rows = [
        ("예비창업 전용 단어", m['_t'].str.contains(r'예비창업자|창업팀|예비\s*창업', regex=True)),
        ("'창업 N년 이내'",    m['_t'].str.contains(r'창업\s*\d+년\s*이내', regex=True)),
        ("R&D 계열 단어",      m['_t'].str.contains(RD_RE)),
        ("'매출 N억 이하'",    m['_t'].str.contains(r'매출액?\s*\d+억\s*원?\s*이하', regex=True)),
    ]
    for label, s in rows:
        print(f"  {label:<20} {int(s.sum()):>5,}건  {pct(int(s.sum()), N)}")
    rd = m['_t'].str.contains(RD_RE)
    mix = int((rd & m['_t'].str.contains(COMM_RE)).sum())
    print(f"    └ R&D 중 사업화 겸용 {mix:>5,}건  {pct(mix, N)}"
          "   ← 감점만 주고 살리는 구간 (v0929-8)")


# ── 5: 공고문 파일 ────────────────────────────────────
def run_files(n_sample):
    head(f"5. 공고문 파일 (API printFlpthNm) — 무작위 {n_sample}건")
    items, seen = [], set()
    for code in REALMS:
        try:
            r = requests.get(API_URL, timeout=60, params={
                "crtfcKey": API_KEY, "dataType": "json",
                "searchCnt": "0", "searchLclasId": code})
            for it in r.json().get('jsonArray', []):
                p = it.get('pblancId', '')
                if p and p not in seen:
                    seen.add(p); items.append(it)
            time.sleep(0.7)
        except Exception as e:
            print(f"  {code} 수집 실패: {str(e)[:60]}")
    if not items:
        print("  API 응답 없음 (해외 IP 차단일 수 있습니다 — 로컬에서 실행하세요)")
        return
    withpdf = [x for x in items if str(x.get('printFlpthNm', '')).startswith('http')]
    print(f"  접수 중 공고 {len(items):,}건 · 공고문 파일 보유 {len(withpdf):,}건 "
          f"{pct(len(withpdf), len(items))}")
    if not withpdf:
        return

    def sniff(b):
        if b[:5] == b'%PDF-':      return 'PDF'
        if b[:4] == b'PK\x03\x04': return 'HWPX/ZIP'
        if b[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1': return 'HWP 5.x (OLE)'
        return '기타'

    def hwpx_text(raw):
        out = []
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for nm in z.namelist():
                if nm.startswith('Contents/section') and nm.endswith('.xml'):
                    out.append(re.sub(r'<[^>]+>', ' ', z.read(nm).decode('utf-8', 'ignore')))
        return re.sub(r'\s+', ' ', ' '.join(out)).strip()

    random.seed(11)
    fmt, okc, lens, sec = Counter(), Counter(), {}, Counter()
    for it in random.sample(withpdf, min(n_sample, len(withpdf))):
        try:
            raw = requests.get(it['printFlpthNm'], headers=UA, timeout=90).content
        except Exception:
            fmt['다운로드 실패'] += 1; continue
        if len(raw) < 500:
            fmt['빈 응답'] += 1; continue
        k = sniff(raw); fmt[k] += 1
        t = ''
        try:
            if k == 'PDF':
                import pdfplumber
                with pdfplumber.open(io.BytesIO(raw)) as pdf:
                    t = "\n".join((p.extract_text() or '') for p in pdf.pages[:15])
            elif k == 'HWPX/ZIP':
                t = hwpx_text(raw)
        except Exception:
            t = ''
        if len(t) > 300:
            okc[k] += 1
            lens.setdefault(k, []).append(len(t))
            sec[k] += bool(SEC_RE.search(t))
        time.sleep(0.3)

    tot = sum(fmt.values())
    print("\n  포맷 분포")
    for k, c in fmt.most_common():
        print(f"    {k:<16} {c:>3}건 {pct(c, tot)}   파싱 성공 {okc.get(k,0)}/{c}")
    print("\n  추출 품질")
    for k, arr in lens.items():
        arr.sort()
        print(f"    {k:<16} 중앙값 {arr[len(arr)//2]:,}자 · 자격 섹션 {sec[k]}/{len(arr)}건")
    print("\n  (참고: 웹 본문은 중앙값 약 900자 · 자격 섹션 포함 약 22%)")


def main():
    ap = argparse.ArgumentParser(description="공고 데이터 품질 진단 (읽기 전용)")
    ap.add_argument('--files', type=int, default=0, metavar='N',
                    help='공고문 파일 N건을 내려받아 포맷·파싱까지 확인 (기본 0=건너뜀)')
    args = ap.parse_args()

    creds = get_creds()
    print("구글 인증 완료 · 드라이브에서 읽는 중 (쓰기 없음)\n")
    run_drive(creds)
    if args.files:
        run_files(args.files)
    print("\n이 스크립트는 드라이브에 아무것도 쓰지 않았습니다.")


if __name__ == '__main__':
    main()
