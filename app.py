"""
원스톱 스케일업 — 공고 매칭 시스템 _UJH
"""
import streamlit as st
import pandas as pd
import requests
import re, os, json, io, subprocess
from datetime import datetime, timedelta

# Playwright 브라우저 자동 설치 (Streamlit Cloud 대응)
@st.cache_resource
def install_playwright():
    try:
        subprocess.run(["playwright", "install", "chromium"], 
                      capture_output=True, timeout=120)
    except Exception:
        pass

install_playwright()

st.set_page_config(
    page_title="원스톱 스케일업_UJH",
    page_icon="📢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 비밀번호 인증 ─────────────────────────────────────
def check_password():
    if st.session_state.get("authenticated"):
        return True
    st.markdown("""
    <div style="max-width:400px;margin:80px auto;text-align:center">
      <h2 style="color:#1F4E79">📢 원스톱 스케일업</h2>
      <p style="color:#666;margin-bottom:24px">혁신제품지원센터 공고 매칭 시스템</p>
    </div>
    """, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        pw = st.text_input("비밀번호", type="password", placeholder="비밀번호 입력")
        if st.button("로그인", use_container_width=True, type="primary"):
            correct = st.secrets.get("password", "scaleup2026")
            if pw == correct:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("비밀번호 오류")
    return False

if not check_password():
    st.stop()

# ── 상수 ──────────────────────────────────────────────
DRIVE_FOLDER_ID  = "1iWGYjaoslqST45ggDlg-IPMLaUHCYmV_"
LOGO_URL = "https://raw.githubusercontent.com/onestopkipcc-web/scaleup-matching/main/logo.png"
API_KEY          = "Nt604D"
BASE_URL         = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
SELECTED_FILE    = "선정기업_명단.xlsx"   # ← 핵심 변경
NOTICES_FILE     = "notices_db.xlsx"
HISTORY_FILE     = "send_history.xlsx"
KEYWORDS_FILE    = "keywords.json"
DETAIL_FILE      = "notices_detail.xlsx"  # 크롤링 전문 DB
CALID_FILE       = "calendar_id.txt"
CATCAL_FILE      = "category_calendars.json"
INDCAL_FILE      = "individual_calendars.json"

# ── 키워드 두 축 구조 ────────────────────────────────
# 대상: 해외조달시장 진출 희망 조달 기업 (혁신제품 지정 여부 무관)

# 축1: 지원대상 (누구를 위한 공고인가)
TARGET_KW = {
    "조달기업특화": [
        # 조달 자격·인증
        "조달청","G-PASS","혁신제품","MAS","우선구매",
        "공공조달","해외조달","나라장터","조달우수","혁신조달",
        "혁신기업","혁신바우처","혁신성장","공공기관",
        "벤처나라","우수제품","성능인증","우수조달",
        "다수공급자계약","조달등록","조달기업","공공구매",
        "혁신제품지정","공공판로","정부조달","조달시장",
        # 해외조달
        "해외조달시장","UN조달","해외공공조달","글로벌조달",
        "조달한류","공공혁신",
    ],
    "수출기업특화": [
        # 수출 단계별
        "수출기업","수출유망","수출강소","글로벌강소","수출초보",
        "수출성장","수출실적기업","수출유망중소기업","수출유망기업",
        "내수기업","수출전환","첫수출","수출입문",
        # 기관·제도
        "FTA","무역","KOTRA","해외개척","무역보험","한국무역",
        "무역협회","수출보험","수출금융","수출보증",
        # 수출 목적지
        "글로벌","해외","수출","신흥시장","新남방","신북방",
    ],
    "중소벤처일반": [
        # 기업 유형
        "중소기업","중소·중견","벤처기업","이노비즈","메인비즈",
        "강소기업","스타기업","유망기업","월드클래스","히든챔피언",
        "중견기업","소기업","예비창업","창업기업","스타트업",
        "소상공인 제외","초기기업","시드","시리즈",
        # 성장 단계
        "성장기업","스케일업","Scale-up","유니콘","예비유니콘",
        "아기유니콘","팁스","tips","도약","도전",
    ],
}
# 축2: 사업성격 (어떤 종류의 지원인가)
TYPE_KW = {
    "공공조달": [
        "조달청","혁신조달","시범구매","우선구매","해외조달",
        "공공구매","MAS등록","나라장터","조달시장","공공기관납품",
        "조달등록","혁신구매","공공혁신","정부구매","공공기관구매",
        "조달지원","혁신제품구매","혁신시장","조달우수제품",
        "공공판로","공공기관","납품실적","조달실적",
    ],
    "해외진출": [
        "해외판로","수출바우처","해외마케팅","판로개척","해외진출",
        "수출지원","해외시장","수출컨소시엄","해외무역",
        "수출인큐베이터","해외거점","글로벌진출","해외진출지원",
        "해외시장개척","수출역량","해외수출","수출활성화",
        "해외판로개척","수출플랫폼","해외기업","바이어발굴",
        "해외네트워크","글로벌파트너","수출상담","무역사절단",
    ],
    "마케팅홍보": [
        "전시회","박람회","해외전시","전시참가","무역박람회",
        "홍보","브랜드","온라인마케팅","해외홍보","쇼룸",
        "국제전시","CES","MWC","전시출품","참가기업모집",
        "홍보영상","광고","SNS마케팅","디지털마케팅",
        "브랜드개발","CI","BI","패키지","디자인개발",
        "카탈로그","홍보물","콘텐츠","제품홍보",
    ],
    "인증특허": [
        "인증","특허","지식재산","KC인증","CE인증","ISO",
        "해외인증","IP","상표등록","국제인증","품질인증",
        "FDA","UL","해외규격","국제규격","인증취득",
        "특허출원","실용신안","디자인등록","상표권",
        "지식재산권","IP보호","기술보호","특허분석",
        "성능인증","NEP","NET","GR인증","녹색인증",
    ],
    "기술개발": [
        "기술개발","R&D","기술사업화","연구개발","기술혁신",
        "기술이전","실증","사업화","기술혁신개발","과제",
        "연구과제","개발과제","정부R&D","국가R&D",
        "기술혁신","제품개발","시제품","프로토타입",
        "실증사업","규제샌드박스","실증특례","혁신실증",
        "공동연구","산학연","기술협력","연구기관",
    ],
    "금융융자": [
        "융자","보증","정책자금","이차보전","경영안정",
        "투자","펀드","자금지원","신용보증",
        "저리융자","장기융자","운전자금","시설자금",
        "R&D자금","수출금융","무역금융","수출보험",
        "벤처투자","엔젤투자","크라우드펀딩","매칭펀드",
        "기술보증","신용대출","대출지원","금리우대",
    ],
    "내수판로": [
        "온라인몰","플랫폼","유통","알리바바","바이코리아",
        "내수판로","홈쇼핑","라이브커머스","B2B",
        "쿠팡","네이버쇼핑","카카오","오픈마켓","G마켓",
        "판로확대","국내판로","내수시장","유통채널",
        "대형마트","백화점","편의점","납품","구매상담",
        "온라인판매","이커머스","전자상거래",
    ],
    "인력채용": [
        "청년채용","고용","인재","채용","일자리","취업",
        "청년","인턴","현장실습","고용장려","채용지원",
        "인력양성","전문인력","R&D인력","핵심인력",
        "산업인력","기술인력","직무교육","재직자",
    ],
}

# 축3: 제품분야 역방향 매칭 (WALLA 15개 카테고리 → 공고 키워드)
# 기업이 선택한 제품분야 → 공고에 이 키워드가 있으면 업종 적합성 가산
INDUSTRY_KW = {
    "바이오·의료": [
        "바이오","의료","의료기기","헬스케어","제약","헬스","생명공학","의약",
        "진단","치료","의료용","임상","체외진단","의약품","바이오텍",
        "의료AI","디지털헬스","원격의료","웨어러블의료",
    ],
    "미래차·모빌리티": [
        "미래차","모빌리티","전기차","자율주행","수소차","친환경차","UAM",
        "퍼스널모빌리티","전동화","충전인프라","배터리","이차전지",
        "자동차부품","차량","운송","교통수단","커넥티드카",
    ],
    "환경·에너지 기술": [
        "환경","에너지","탄소중립","친환경","온실가스","신재생","태양광",
        "수소","폐기물","재활용","탄소","녹색","저탄소","청정",
        "에너지효율","ESG","탄소저감","기후","풍력","연료전지",
        "환경오염","수처리","대기","토양정화","친환경소재",
    ],
    "스마트 제조·산업·기계": [
        "스마트제조","스마트공장","제조혁신","산업기계","자동화","로봇",
        "공정혁신","MES","제조","기계","장비","설비","부품","소재",
        "정밀기계","산업용","제조업","공정","생산","품질관리",
        "CNC","공작기계","산업로봇","협동로봇","용접","도금",
    ],
    "스마트 건설": [
        "스마트건설","건설","건축","BIM","모듈러","건설기술","건설자재","플랜트",
        "건설장비","건설안전","건축자재","인프라건설","토목","시공",
        "건물","구조물","시설물","유지보수","안전진단","건설IT",
    ],
    "도시·교통 인프라": [
        "스마트시티","도시","교통","인프라","철도","도로","물류","스마트교통",
        "도시개발","대중교통","지하철","버스","항만","공항",
        "물류센터","SCM","공급망","유통인프라","스마트물류",
    ],
    "방산·국방 기술": [
        "방산","국방","방위","군수","보안","방위산업","군","방어",
        "국방기술","방위기술","무기","군용","군사","사이버보안",
        "정보보안","보안솔루션","네트워크보안","물리보안",
    ],
    "정보통신 기술": [
        "ICT","정보통신","소프트웨어","앱","플랫폼","클라우드","SaaS","통신",
        "SW","IT","시스템","솔루션","네트워크","서버","데이터센터",
        "사물인터넷","IoT","5G","통신망","디지털","스마트",
        "보안","ERP","CRM","그룹웨어","SI",
    ],
    "AI·데이터 기술": [
        "AI","인공지능","빅데이터","데이터","머신러닝","딥러닝","디지털전환","DX",
        "자연어처리","컴퓨터비전","생성형AI","ChatGPT","LLM",
        "데이터분석","데이터플랫폼","MLOps","AI솔루션","지능형",
        "예측","추천","자동화AI","AI서비스",
    ],
    "농축산·수산·식품": [
        "농업","농식품","식품","수산","축산","스마트팜","농산물","푸드테크",
        "농기계","농촌","원예","작물","가공식품","식품안전",
        "수산물","수산양식","해양수산","축산물","낙농",
    ],
    "우주·항공·해양": [
        "우주","항공","드론","해양","선박","해운","위성",
        "UAM","도심항공","항공기","항공부품","발사체",
        "해양플랜트","해양기술","조선","선박부품","해양수산",
    ],
    "핀테크·금융 IT": [
        "핀테크","금융","결제","블록체인","암호화폐","보험테크",
        "디지털금융","오픈뱅킹","간편결제","송금","대출플랫폼",
        "자산관리","투자플랫폼","금융데이터","RegTech",
    ],
    "전기·전자": [
        "전기","전자","반도체","디스플레이","배터리","전력","회로","센서",
        "전장","전기부품","전자부품","LED","OLED","PCB",
        "전력반도체","시스템반도체","전력변환","전기설비",
        "계측기","검사장비","시험장비",
    ],
    "교육·HR테크": [
        "에듀테크","교육","HR","인재","학습","이러닝","채용플랫폼",
        "온라인교육","직무교육","기업교육","학습관리","LMS",
        "인적자원","인사관리","채용","HRD","HRM",
    ],
}

# 별점 판정 함수용 flat 리스트 (설정 탭 표시용)
DEFAULT_HIGH = (
    TARGET_KW["조달기업특화"] +
    TYPE_KW["공공조달"]
)
DEFAULT_MID = (
    TARGET_KW["수출기업특화"] +
    TYPE_KW["해외진출"] +
    TYPE_KW["마케팅홍보"]
)
REALM_CODE   = {
    "금융":"01","기술개발":"02","인력":"03","수출":"04",
    "내수":"05","창업":"06","경영":"07","기타":"09",
}
# 테스트 수신자 — 설정 탭에서 변경 가능 (session_state 우선)
_DEFAULT_TEST_RECIPIENTS = ["fbwlgns819@naver.com","fbwlgns819@kip.re.kr"]

def get_test_recipients():
    saved = st.session_state.get('test_recipients_str','')
    if saved:
        return [e.strip() for e in saved.split(',') if e.strip()]
    return _DEFAULT_TEST_RECIPIENTS

# ── 구글 인증 ─────────────────────────────────────────
# ── 구글 인증 (requests 기반, httplib2 미사용) ──────────
def get_creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GRequest
    SCOPES = [
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/drive',
    ]
    if 'g_creds' in st.session_state:
        creds = st.session_state['g_creds']
        if creds and not creds.expired:
            return creds
    if 'google' in st.secrets:
        creds = Credentials.from_authorized_user_info(
            json.loads(st.secrets['google']['token']), SCOPES)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        return None
    if creds and creds.expired and creds.refresh_token:
        try: creds.refresh(GRequest())
        except: return None
    st.session_state['g_creds'] = creds
    return creds

def gapi(method, url, **kwargs):
    """인증된 구글 API 요청 (requests 직접 호출)"""
    creds = get_creds()
    if not creds:
        raise Exception("인증 실패")
    headers = kwargs.pop('headers', {})
    headers['Authorization'] = f'Bearer {creds.token}'
    return requests.request(method, url, headers=headers, **kwargs)

# ── gmail API (requests 기반) ──────────────────────────
def gmail_send(raw_b64):
    resp = gapi('POST',
        'https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
        json={'raw': raw_b64})
    resp.raise_for_status()
    return resp.json()

# ── calendar API (requests 기반) ───────────────────────
def cal_list_events(cal_id, private_prop=None):
    params = {'maxResults': 10}
    if private_prop:
        params['privateExtendedProperty'] = private_prop
    resp = gapi('GET',
        f'https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events',
        params=params)
    return resp.json() if resp.ok else {'items': []}

def cal_insert_event(cal_id, body):
    resp = gapi('POST',
        f'https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events',
        json=body)
    return resp.json() if resp.ok else {}

# ── drive API (requests 기반) ──────────────────────────
def drive_list_files(name, folder_id):
    params = {
        'q': f"name='{name}' and '{folder_id}' in parents and trashed=false",
        'fields': 'files(id,name)',
        'orderBy': 'modifiedTime desc',
    }
    resp = gapi('GET', 'https://www.googleapis.com/drive/v3/files', params=params)
    return resp.json().get('files', []) if resp.ok else []

def drive_download_file(file_id):
    resp = gapi('GET',
        f'https://www.googleapis.com/drive/v3/files/{file_id}',
        params={'alt': 'media'})
    return resp.content if resp.ok else None

def drive_upload_file(name, folder_id, content_bytes, mime, file_id=None):
    bnd  = b"----MIMEBoundary"
    crlf = b"\r\n"
    ct   = "multipart/related; boundary=----MIMEBoundary"

    if file_id:
        # 기존 파일 업데이트: parents 제외, 내용만 교체
        meta = json.dumps({"name": name}).encode()
        body = b"--" + bnd + crlf
        body += b"Content-Type: application/json; charset=UTF-8" + crlf + crlf
        body += meta + crlf
        body += b"--" + bnd + crlf
        body += b"Content-Type: " + mime.encode() + crlf + crlf
        body += content_bytes + crlf
        body += b"--" + bnd + b"--"
        resp = gapi("PATCH",
            f"https://www.googleapis.com/upload/drive/v3/files/{file_id}",
            params={"uploadType": "multipart"},
            data=body,
            headers={"Content-Type": ct})
    else:
        # 신규 파일 생성: parents 포함
        meta = json.dumps({"name": name, "parents": [folder_id]}).encode()
        body = b"--" + bnd + crlf
        body += b"Content-Type: application/json; charset=UTF-8" + crlf + crlf
        body += meta + crlf
        body += b"--" + bnd + crlf
        body += b"Content-Type: " + mime.encode() + crlf + crlf
        body += content_bytes + crlf
        body += b"--" + bnd + b"--"
        resp = gapi("POST",
            "https://www.googleapis.com/upload/drive/v3/files",
            params={"uploadType": "multipart"},
            data=body,
            headers={"Content-Type": ct})

    if not resp.ok:
        raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return True

def get_services(): return None, None, None
def _get_drive():   return 'drive'
def _get_gmail():   return 'gmail'
def _get_cal():     return 'cal' 

# ── 드라이브 유틸 ─────────────────────────────────────
def drive_file_id(drive, filename):
    files = drive_list_files(filename, DRIVE_FOLDER_ID)
    return files[0]['id'] if files else None

def drive_download(drive, filename):
    fid = drive_file_id(drive, filename)
    return drive_download_file(fid) if fid else None

def drive_upload(drive, filename, content_bytes, mime):
    try:
        fid = drive_file_id(drive, filename)
        result = drive_upload_file(filename, DRIVE_FOLDER_ID, content_bytes, mime, fid)
        return result
    except Exception as e:
        st.error(f"드라이브 저장 실패 ({filename}): {e}")
        return False

def load_excel(drive, filename):
    content = drive_download(drive, filename)
    if content:
        try:
            df = pd.read_excel(io.BytesIO(content), dtype=str).fillna("")
            # 선정기업 명단인데 '기업명' 컬럼이 없으면
            # 1행이 필수/운영관리 구분행 → header=1로 재시도
            if filename == SELECTED_FILE and '기업명' not in df.columns:
                df = pd.read_excel(io.BytesIO(content), header=1, dtype=str).fillna("")
            return df
        except: return pd.DataFrame()
    return pd.DataFrame()

def save_excel(drive, df, filename, sheet="데이터", hcolor="1F4E79", star_col=None):
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook(); ws = wb.active
    ws.title = sheet; ws.sheet_view.showGridLines = False
    s   = Side(style="thin", color="BFBFBF")
    bdr = Border(left=s, right=s, top=s, bottom=s)
    for ci, col in enumerate(df.columns, 1):
        ws.column_dimensions[get_column_letter(ci)].width = max(len(str(col))*2, 14)
        c = ws.cell(row=1, column=ci, value=col)
        c.fill=PatternFill("solid",start_color=hcolor,end_color=hcolor)
        c.font=Font(name="맑은 고딕",bold=True,color="FFFFFF",size=10)
        c.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
        c.border=bdr
    ws.row_dimensions[1].height = 24
    star_colors = {"★★★":"FFF2CC","★★":"E2EFDA"}
    rev_colors  = {"○":"D5E8D4","✕":"FFE6E6"}
    for ri, row in enumerate(df.itertuples(index=False), 2):
        vals = list(row)
        bg   = "FFFFFF"
        if star_col and star_col in df.columns:
            bg = star_colors.get(vals[df.columns.tolist().index(star_col)], "FFFFFF")
        ws.row_dimensions[ri].height = 18
        for ci, val in enumerate(vals, 1):
            cname    = df.columns[ci-1]
            cell_bg  = rev_colors.get(str(val), bg) if cname=="담당자검토" else bg
            c = ws.cell(row=ri, column=ci, value=val)
            c.fill=PatternFill("solid",start_color=cell_bg,end_color=cell_bg)
            c.font=Font(name="맑은 고딕",size=9)
            c.alignment=Alignment(horizontal="left",vertical="center")
            c.border=bdr
    buf = io.BytesIO(); wb.save(buf)
    return drive_upload(drive, filename, buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

def load_json(drive, filename):
    content = drive_download(drive, filename)
    if content:
        try: return json.loads(content.decode('utf-8'))
        except: return {}
    return {}

def save_json(drive, data, filename):
    return drive_upload(drive, filename,
        json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'),
        "application/json")

def load_text(drive, filename):
    content = drive_download(drive, filename)
    return content.decode('utf-8').strip() if content else ""

def load_keywords(drive):
    kw = load_json(drive, KEYWORDS_FILE)
    global TARGET_KW, TYPE_KW
    if "TARGET_KW" in kw: TARGET_KW = kw["TARGET_KW"]
    if "TYPE_KW"   in kw: TYPE_KW   = kw["TYPE_KW"]
    return kw.get("HIGH", DEFAULT_HIGH), kw.get("MID", DEFAULT_MID)

# ── 유틸 ─────────────────────────────────────────────
def strip_html(html):
    return re.sub(r'<[^>]+>', ' ', html or '').strip()

def parse_deadline(s):
    try:
        end = s.split('~')[-1].strip()
        return datetime.strptime(re.sub(r'\.', '-', end), "%Y-%m-%d")
    except: return None

def score_notice(notice, row, already_sent, HIGH, MID):
    pid = notice.get('pblancId', '')
    if (row['기업명'], pid) in already_sent: return None
    dl = notice.get('마감일', '')
    if dl and dl < datetime.today().strftime("%Y-%m-%d"): return None
    if str(row.get('수출실적',''))=='아니오' and '수출' in str(notice.get('분야','')): return None

    text = " ".join([str(notice.get(k,'')) for k in ['공고명','사업개요','전문내용','해시태그','주관기관','지원대상']])

    # ── TRL 필터: 8-9단계 기업은 R&D 공고 제외 ──────
    trl = str(row.get('TRL단계',''))
    if any(t in trl for t in ['8','9']):
        if any(kw in text for kw in ['R&D','연구개발','기술개발과제','기초연구','원천기술']):
            return None

    # ── 소재지 필터: 지역 공고 판단 ─────────────────
    location = str(row.get('소재지',''))
    location_score = 0
    notice_region_tag = ''   # 공고에서 감지된 지역명 (검토 화면 표시용)

    REGIONS = ['서울','부산','대구','인천','광주','대전','울산','세종',
               '경기','강원','충북','충남','전북','전남','경북','경남','제주']
    REGION_ALIAS = {
        '서울': ['서울','수도권'],
        '경기': ['경기','수도권'],
        '인천': ['인천','수도권'],
        '부산': ['부산'],
        '대구': ['대구'],
        '광주': ['광주'],
        '대전': ['대전','충청'],
        '울산': ['울산'],
        '세종': ['세종'],
        '강원': ['강원'],
        '충북': ['충북','충청'],
        '충남': ['충남','충청'],
        '전북': ['전북','전라'],
        '전남': ['전남','전라'],
        '경북': ['경북'],
        '경남': ['경남'],
        '제주': ['제주'],
    }

    if location and location != 'nan':
        notice_name = str(notice.get('공고명',''))
        notice_full  = " ".join([
            notice_name,
            str(notice.get('사업개요','')),
            str(notice.get('지원대상','')),
            str(notice.get('해시태그','')),
        ])
        co_region = next((r for r in REGIONS if r in location), None)

        import re as _re

        # ① 공고명 [] 패턴 최우선 (신뢰도 최고)
        #    예: [경기] 중소기업 수출지원, [서울·경기] 스케일업 지원
        bracket_match = _re.search('[[]([^]]+)[]]', notice_name)
        if bracket_match:
            bracket_text = bracket_match.group(1)
            bracket_regions = [r for r in REGIONS if r in bracket_text]
            if bracket_regions:
                notice_region_tag = f"[{bracket_text}]"
                if co_region:
                    aliases = REGION_ALIAS.get(co_region, [co_region])
                    if any(a in bracket_text for a in aliases):
                        location_score = 3   # 일치 → 가산
                    else:
                        location_score = -5  # 불일치 → 강한 감산
            # [] 안에 지역명 없으면 공고 유형 태그 → 소재지 무관

        # ② 주관기관이 지방자치단체이면 해당 지역 공고
        #    예: 충청남도, 경기도청, 서울특별시 → 지역 제한
        elif co_region:
            organizer = str(notice.get('주관기관',''))
            org_regions = [r for r in REGIONS if r in organizer]
            if org_regions:
                notice_region_tag = f"주관기관({organizer})"
                aliases = REGION_ALIAS.get(co_region, [co_region])
                if any(a in organizer for a in aliases):
                    location_score = 2
                else:
                    location_score = -3

        # ③ 사업개요에 "○○ 소재 기업" 명시 패턴
        #    "전국"이 포함되면 지역 제한 없음으로 처리
        elif co_region:
            summary = str(notice.get('사업개요',''))
            if '전국' not in summary and '전 지역' not in summary:
                sojaepat = _re.findall(r'([가-힣]{2,4}(?:도|시|군|구))\s*소재', summary)
                if sojaepat:
                    notice_region_tag = ", ".join(sojaepat[:2])
                    aliases = REGION_ALIAS.get(co_region, [co_region])
                    if any(any(a in s for a in aliases) for s in sojaepat):
                        location_score = 2
                    else:
                        location_score = -3

        # 지역 제한 없는 공고 → 중립 (0점)

    # ── 축1: 지원대상 매칭 ────────────────────────────
    matched_target = {}
    for cat, kws in TARGET_KW.items():
        hits = [kw for kw in kws if kw in text]
        if hits: matched_target[cat] = hits

    # ── 축2: 사업성격 매칭 ────────────────────────────
    matched_type = {}
    for cat, kws in TYPE_KW.items():
        hits = [kw for kw in kws if kw in text]
        if hits: matched_type[cat] = hits

    # ── 기업 키워드 + 핵심수요태그 매칭 ────────────────
    raw = ",".join([str(row.get(k,'')) for k in ['기술키워드','제품분야','키워드보완','핵심수요태그']])
    co_kws = [k.strip() for k in raw.split(',') if k.strip() and k.strip()!='nan']
    matched_co = [kw for kw in co_kws if kw in text]

    # 핵심수요태그는 가중치 높게
    demand_tags = [t.strip() for t in str(row.get('핵심수요태그','')).split(',') if t.strip() and t.strip()!='nan']
    matched_demand = [kw for kw in demand_tags if kw in text]

    # ── 축3: 제품분야 역방향 매칭 ────────────────────
    # 기업 제품분야 → 해당 업종 키워드가 공고에 있으면 업종 적합성 확인
    co_industry    = str(row.get('제품분야',''))
    matched_industry = []
    for ind_cat, ind_kws in INDUSTRY_KW.items():
        # 기업이 이 카테고리를 선택했는지 확인
        if any(cat_part in co_industry for cat_part in ind_cat.split('·')):
            # 공고에 해당 업종 키워드가 있으면 매칭
            hits = [kw for kw in ind_kws if kw in text]
            matched_industry.extend(hits)
    # 역방향 매칭 점수 (업종 적합성 가산)
    ind_score = min(len(matched_industry) * 2, 6)  # 최대 6점 상한

    # ── 수출국가 가산 ─────────────────────────────────
    cn = str(row.get('수출국가',''))
    xs = 2 if (cn and cn!='nan' and cn in text) else 0

    # ── 역매칭: 특정 업종 명시 공고에서 기업 키워드 없으면 제외 ──
    INDUSTRY_SPECIFIC = [
        '농식품','농업','식품','농산물','수산','임업',
        '의료','바이오','제약','화장품','뷰티',
        '건설','건축','토목','부동산',
        '관광','숙박','외식','요식업',
        '섬유','패션','의류',
    ]
    for ind_kw in INDUSTRY_SPECIFIC:
        if ind_kw in text and not any(
            ind_kw in kw or kw in ind_kw for kw in co_kws + demand_tags
        ):
            return None

    # ── 별점 판정 (두 축 교차 + 기업 키워드) ────────
    has_procurement   = '공공조달'   in matched_type
    has_overseas      = '해외진출'   in matched_type
    has_marketing     = '마케팅홍보' in matched_type
    has_cert          = '인증특허'   in matched_type
    has_tech          = '기술개발'   in matched_type
    has_finance       = '금융융자'   in matched_type
    has_domestic      = '내수판로'   in matched_type

    has_procurement_target = '조달기업특화' in matched_target
    has_export_target      = '수출기업특화' in matched_target
    has_general_target     = '중소벤처일반' in matched_target

    has_co_match    = bool(matched_co or matched_demand)
    has_demand_hit  = bool(matched_demand)  # 핵심수요태그 직접 매칭

    stars = None  # 초기화

    # ★★★ 판정
    if has_demand_hit:
        # 핵심수요태그 직접 매칭 → 무조건 ★★★
        stars = "★★★"
    elif has_procurement_target and has_procurement:
        # 조달기업 대상 + 공공조달 사업
        stars = "★★★"
    elif has_procurement_target and has_overseas:
        # 조달기업 대상 + 해외진출 사업
        stars = "★★★"
    elif has_export_target and has_overseas:
        # 수출기업 대상 + 해외진출 사업
        stars = "★★★"
    elif has_co_match and has_procurement:
        # 기업 키워드 매칭 + 공공조달
        stars = "★★★"

    # ★★ 판정
    elif has_procurement_target and (has_tech or has_cert or has_marketing):
        stars = "★★"
    elif has_export_target and (has_marketing or has_cert or has_domestic):
        stars = "★★"
    elif has_co_match and (has_overseas or has_marketing or has_cert):
        stars = "★★"
    elif has_co_match and matched_target:
        stars = "★★"
    elif has_general_target and (has_procurement or has_overseas):
        stars = "★★"
    elif has_general_target and has_co_match:
        stars = "★★"

    # 매칭 없음
    if not stars:
        return None

    # ── 점수 계산 (정렬용) ────────────────────────────
    score = (
        len(sum(matched_target.values(), [])) * 3 +
        len(sum(matched_type.values(),   [])) * 2 +
        len(matched_co) * 2 +
        len(matched_demand) * 3 +  # 핵심수요태그 높은 가중치
        ind_score +                 # 제품분야 역방향 매칭
        xs + location_score
    )
    if stars == "★★★": score += 5
    if score <= 0: return None

    # ── 매칭 근거 텍스트 ──────────────────────────────
    target_str = " / ".join([f"{k}({','.join(v)})" for k,v in matched_target.items()])
    type_str   = " / ".join([f"{k}({','.join(v)})" for k,v in matched_type.items()])

    return {
        "기업명":       row['기업명'],
        "관련도":       stars,
        "점수":         score,
        "공고ID":       pid,
        "공고명":       notice.get('공고명',''),
        "주관기관":     notice.get('주관기관',''),
        "접수기간":     notice.get('접수기간',''),
        "지원대상":     notice.get('지원대상',''),
        "마감일":       dl,
        "사업개요":     str(notice.get('사업개요',''))[:200]+"...",
        "지원대상매칭": target_str,
        "사업성격매칭": type_str,
        "기업키워드매칭": ", ".join(matched_co),
        "핵심수요매칭":   ", ".join(matched_demand),
        "업종역방향매칭": ", ".join(matched_industry[:5]),
        "소재지점수":     location_score,
        "공고지역":     notice_region_tag,
        "매칭근거":     _build_reason(stars, matched_target, matched_type, matched_co,
                                matched_demand, location_score, matched_industry),
        "공고링크":     notice.get('공고링크',''),
        "공고유형":     "맞춤",   # 매칭 실행 시 공통/맞춤 재분류됨
        "담당자검토":   "",
        "검토의견":     "",
    }

# Claude API 비용 상수 (claude-sonnet-4-5 기준)
CLAUDE_INPUT_COST  = 3.0 / 1_000_000   # $3 per 1M input tokens
CLAUDE_OUTPUT_COST = 15.0 / 1_000_000  # $15 per 1M output tokens
USD_TO_KRW         = 1380

def estimate_cost(n_notices):
    """n건 분석 시 예상 비용 계산"""
    avg_input  = 800   # 토큰 (기업정보 300 + 공고내용 500)
    avg_output = 300   # 토큰 (JSON 응답)
    total_usd  = n_notices * (avg_input * CLAUDE_INPUT_COST + avg_output * CLAUDE_OUTPUT_COST)
    total_krw  = total_usd * USD_TO_KRW
    return total_usd, total_krw

def claude_analyze(company_info, notice_info):
    """Claude API로 공고-기업 적합성 분석"""
    api_key = ""
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except:
        try:
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        except:
            pass

    if not api_key:
        try:
            available = list(st.secrets.keys())
        except:
            available = []
        return {"error": f"API 키 없음 — Secrets 키 목록: {available}"}

    # 전문 내용 우선 활용
    notice_content = (
        notice_info.get('전문내용','') or
        notice_info.get('사업개요','')
    )[:1500]

    prompt = f"""당신은 정부 지원사업 매칭 전문가입니다.
아래 기업 정보와 공고를 보고 이 기업이 이 공고에 지원하는 게 적합한지 판단하세요.

## 기업 정보
- 기업명: {company_info.get('기업명','')}
- 소재지: {company_info.get('소재지','')}
- 기업유형: {company_info.get('기업유형','')}
- 관심분야: {company_info.get('관심사업분야','')}
- 제품/기술 분야: {company_info.get('제품분야','')}
- 기술키워드: {company_info.get('기술키워드','')}
- 핵심수요: {company_info.get('핵심수요태그','')}
- 희망서비스: {company_info.get('희망서비스요약','')}
- 수출실적: {company_info.get('수출실적','')} | 수출국가: {company_info.get('수출국가','')}
- TRL단계: {company_info.get('TRL단계','')}
- 매출규모: {company_info.get('매출규모','')}

## 공고 정보
- 공고명: {notice_info.get('공고명','')}
- 주관기관: {notice_info.get('주관기관','')}
- 지원대상: {notice_info.get('지원대상','')}
- 지원금액: {notice_info.get('지원금액','')}
- 선정규모: {notice_info.get('선정규모','')}
- 지역제한: {notice_info.get('공고지역','') or '전국'}
- 공고내용: {notice_content}

## 판단 항목 (각각 구체적으로)
1. 업종일치: 기업 제품/기술이 이 공고가 원하는 업종/분야와 맞는가
2. 자격충족: 지원 자격(기업유형·매출·수출실적 등) 충족 가능성
3. 지역적합: 소재지와 공고 지역이 맞는가
4. 수요일치: 기업이 원하는 지원(핵심수요태그)과 공고 내용이 맞는가
5. 경쟁력: 이 기업이 선정될 가능성이 있는가

JSON 형식으로만 답하세요:
{{
  "추천여부": "추천 또는 검토 또는 비추천",
  "적합도": "높음 또는 보통 또는 낮음",
  "한줄요약": "15자 이내 핵심",
  "업종일치": "O 또는 X 또는 △",
  "자격충족": "O 또는 X 또는 △",
  "지역적합": "O 또는 X 또는 △",
  "수요일치": "O 또는 X 또는 △",
  "판단근거": "3~4문장으로 구체적 근거 (기업의 어떤 특성이 공고의 어떤 조건과 맞거나 안 맞는지)",
  "주의사항": "신청 전 반드시 확인할 사항 (없으면 없음)"
}}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-5",
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        if resp.ok:
            text = resp.json()['content'][0]['text']
            import re as _re
            json_match = _re.search(r'[{].*[}]', text, _re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"error": "응답 파싱 실패", "raw": text[:200]}
        else:
            try:
                err_detail = resp.json().get('error', {}).get('message', resp.text[:300])
            except:
                err_detail = resp.text[:300]
            return {"error": f"API 오류 {resp.status_code}: {err_detail}"}
    except Exception as e:
        return {"error": str(e)}

def _build_reason(stars, matched_target, matched_type, matched_co,
                  matched_demand=[], location_score=0, matched_industry=[]):
    parts = []
    if '조달기업특화' in matched_target:
        parts.append("조달기업 대상")
    if '수출기업특화' in matched_target:
        parts.append("수출기업 대상")
    if '공공조달' in matched_type:
        parts.append("공공조달 연계")
    if '해외진출' in matched_type:
        parts.append("해외진출 지원")
    if '마케팅홍보' in matched_type:
        parts.append("마케팅·홍보")
    if '인증특허' in matched_type:
        parts.append("인증·특허 지원")
    if '기술개발' in matched_type:
        parts.append("기술개발 지원")
    if '금융융자' in matched_type:
        parts.append("금융·융자 지원")
    if matched_demand:
        parts.append(f"수요태그({', '.join(matched_demand[:2])})")
    if matched_industry:
        parts.append(f"업종일치({', '.join(matched_industry[:2])})")
    if matched_co and not matched_demand:
        parts.append(f"키워드({', '.join(matched_co[:2])})")
    if location_score > 0:
        parts.append("✓ 동일지역")
    elif location_score < 0:
        parts.append("△ 타지역")
    return " + ".join(parts) if parts else "키워드 매칭"

# ── 안내 박스 ─────────────────────────────────────────
def info_box(title, desc, how_to=None):
    with st.expander(f"ℹ️ {title}", expanded=False):
        st.markdown(desc)
        if how_to:
            st.divider()
            st.markdown("**✏️ 수정 방법**")
            st.markdown(how_to)

# ── CSS (툴팁 제거 포함) ──────────────────────────────
st.markdown("""
<style>
/* ── 전체 배경·텍스트 ── */
.stApp {background:#0F1923;}
.stApp, .stApp * {color:#E8EDF2;}
p, li, span, div, label {color:#E8EDF2 !important; font-size:14px;}
h1 {color:#FFFFFF !important; font-size:28px !important; font-weight:700 !important;}
h2 {color:#FFFFFF !important; font-size:18px !important; font-weight:700 !important;}
h3 {color:#FFFFFF !important; font-size:16px !important; font-weight:600 !important;}

/* ── 사이드바 ── */
[data-testid="stSidebar"] {background:#0A1628 !important;}
[data-testid="stSidebar"] * {color:#E8EDF2 !important;}
[data-testid="stSidebarNav"] {display:none;}

/* ── 메트릭 ── */
[data-testid="stMetricLabel"] {color:#A0AEC0 !important; font-size:12px !important;}
[data-testid="stMetricValue"] {color:#FFFFFF !important; font-weight:700; font-size:24px !important;}
[data-testid="stMetricDelta"] {font-size:12px !important;}

/* ── 버튼 ── */
.stButton button {
    border-radius:6px;
    background:#1F4E79;
    color:#FFFFFF !important;
    border:none;
    font-size:14px !important;
    font-weight:600 !important;
    padding:6px 16px !important;
}
.stButton button:hover {background:#2E75B6;}
button[kind="primary"] {background:#4A9EFF !important; color:#0F1923 !important; font-weight:700;}
button[kind="primary"]:hover {background:#63B3FF !important;}

/* ── 입력창 ── */
.stTextInput input, .stTextArea textarea {
    background:#1A2940 !important;
    color:#E8EDF2 !important;
    border:1px solid #2D4A6E !important;
    border-radius:6px;
}
.stSelectbox div[data-baseweb="select"] {
    background:#1A2940 !important;
    border:1px solid #2D4A6E !important;
}
.stSelectbox div[data-baseweb="select"] * {color:#E8EDF2 !important;}

/* ── 슬라이더 ── */
.stSlider * {color:#E8EDF2 !important;}

/* ── 체크박스 ── */
.stCheckbox label, .stCheckbox span, .stCheckbox p {color:#E8EDF2 !important;}
[data-testid="stCheckbox"] label {color:#E8EDF2 !important;}

/* ── 토글 ── */
.stToggle label {color:#E8EDF2 !important;}

/* ── 탭 ── */
.stTabs [data-baseweb="tab"] {color:#A0AEC0 !important;}
.stTabs [aria-selected="true"] {color:#4A9EFF !important; border-bottom:2px solid #4A9EFF;}

/* ── expander ── */
.streamlit-expanderHeader {color:#E8EDF2 !important; background:#1A2940 !important;}
.streamlit-expanderContent {background:#131F2E !important;}

/* ── 데이터프레임 ── */
.stDataFrame {background:#1A2940 !important;}
.stDataFrame * {color:#E8EDF2 !important;}

/* ── 구분선 ── */
hr {border-color:#2D4A6E !important;}

/* ── 강조 ── */
strong {color:#4A9EFF !important;}
code {color:#63FFA8 !important; background:#1A2940 !important; font-size:13px !important;}
.stCaption, [data-testid="stCaptionContainer"] {color:#A0AEC0 !important; font-size:12px !important;}

/* ── 폰트 크기 통일 ── */
.stTextInput input    {font-size:14px !important;}
.stTextArea textarea  {font-size:14px !important;}
.stSelectbox *        {font-size:14px !important;}
.stMultiSelect *      {font-size:14px !important;}
.stSlider *           {font-size:13px !important;}
.stRadio label        {font-size:14px !important;}
.stCheckbox label     {font-size:14px !important;}
.stExpander summary   {font-size:14px !important;}
.stTabs [data-baseweb="tab"] {font-size:14px !important;}
.stDataFrame          {font-size:13px !important;}
[data-testid="stSidebar"] .stRadio label {font-size:14px !important;}

/* ── info_box 안내 텍스트 ── */
.streamlit-expanderContent p  {font-size:13px !important; line-height:1.7;}
.streamlit-expanderContent li {font-size:13px !important; line-height:1.7;}
.streamlit-expanderHeader p   {font-size:13px !important;}

/* ── 알림 박스 ── */
.stSuccess {background:#0D2B1A !important; border-left:4px solid #63FFA8 !important;}
.stWarning {background:#2B1D0A !important; border-left:4px solid #FFC863 !important;}
.stError   {background:#2B0A0A !important; border-left:4px solid #FF6363 !important;}
.stInfo    {background:#0A1A2B !important; border-left:4px solid #4A9EFF !important;}

/* ── 사이드바 강제 항상 노출 ── */
[data-testid="stSidebarCollapseButton"] {display:none !important;}
[data-testid="collapsedControl"]        {display:none !important;}
section[data-testid="stSidebar"] {
    display: block !important;
    transform: translateX(0) !important;
    min-width: 244px !important;
    visibility: visible !important;
}
section[data-testid="stSidebar"][aria-expanded="false"] {
    display: block !important;
    transform: translateX(0) !important;
    margin-left: 0 !important;
}

/* ── 툴팁·도움말 완전 제거 ── */
.stTooltipIcon {display:none !important;}
div[data-testid="stStatusWidget"] {display:none !important;}
#MainMenu {visibility:hidden;}
footer    {visibility:hidden;}
header    {visibility:hidden;}
</style>
""", unsafe_allow_html=True)

# ── 사이드바 ──────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📢 원스톱 스케일업")
    st.caption("혁신제품지원센터")
    st.divider()
    page = st.radio("메뉴", [
        "대시보드", "기업 관리", "공고 수집",
        "매칭 결과", "발송 관리",
        "발송 이력", "성과 집계", "설정", "시스템 명세"
    ], label_visibility="collapsed")
    st.divider()
    test_mode = st.toggle("테스트 모드", value=True)
    if test_mode: st.warning("테스트 메일 발송")
    else:         st.success("실제 기업 발송")

# 구글 서비스 — 필요할 때 get_creds()로 직접 인증


# ══════════════════════════════════════════════════════
# 대시보드
# ══════════════════════════════════════════════════════
if page == "대시보드":
    drive = _get_drive()
    st.title("대시보드")
    info_box("운영 흐름",
        """
**운영 사이클 (격주)**
1. **공고 수집** (월) — bizinfo API 전체 공고 수집 → notices_db.xlsx 갱신
2. **매칭 실행** (화) — 선정기업 × 공고 교차 매칭 → 후보 목록 추출
3. **담당자 검토** (화~수) — ○/✕ 클릭으로 발송 여부 결정
4. **발송** (목) — 승인 건만 메일 + 캘린더 자동 처리
5. **성과 집계** (분기) — 신청·선정 결과 입력 및 보고

**드라이브 연동** — 모든 데이터 구글 드라이브 자동 저장, 팀 공유
        """)

    drive = _get_drive()
    with st.spinner("드라이브 데이터 로딩 중..."):
        df_c = load_excel(drive, SELECTED_FILE)
        df_n = load_excel(drive, NOTICES_FILE)
        df_h = load_excel(drive, HISTORY_FILE)

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("선정 기업",  f"{len(df_c)}개사")
    c2.metric("수집 공고",  f"{len(df_n):,}건")
    c3.metric("발송 이력",  f"{len(df_h)}건")
    c4.metric("운영 모드",  "테스트" if test_mode else "실제")

    st.divider()
    st.subheader("이번 주 진행 단계")
    cols = st.columns(5)
    steps = [
        ("① 공고 수집",   "✅" if not df_n.empty else "⬜"),
        ("② 매칭 실행",   "🔵"),
        ("③ 담당자 검토", "⬜"),
        ("④ 발송",        "⬜"),
        ("⑤ 이력 기록",   "⬜"),
    ]
    for col,(name,icon) in zip(cols,steps):
        col.markdown(f"**{name}**\n\n{icon}")

    st.divider()
    st.subheader("드라이브 파일 현황")
    fcols = st.columns(6)
    for col,(fname,label) in zip(fcols,{
        SELECTED_FILE:"선정기업 명단", NOTICES_FILE:"공고 DB",
        DETAIL_FILE:"공고 전문 DB",
        HISTORY_FILE:"발송 이력", CALID_FILE:"캘린더 ID", KEYWORDS_FILE:"키워드"
    }.items()):
        fid = drive_file_id(drive, fname)
        col.metric(label, "✅" if fid else "❌")

    # ── 차트 섹션 ──────────────────────────────────────
    st.divider()
    st.subheader("📊 현황 분석")

    tab_c1, tab_c2, tab_c3, tab_c4 = st.tabs([
        "분야별 공고", "기업 관심분야", "매칭 점수", "발송 추이"
    ])

    # ① 분야별 공고 현황
    with tab_c1:
        if df_n.empty:
            st.info("공고 수집 후 확인 가능")
        elif '분야' in df_n.columns:
            realm_count = df_n['분야'].value_counts().reset_index()
            realm_count.columns = ['분야', '공고 수']
            realm_count = realm_count[realm_count['분야'] != ''].head(10)
            st.bar_chart(realm_count.set_index('분야'), height=300)
            st.caption(f"총 {len(df_n):,}건 / {len(realm_count)}개 분야")
        else:
            st.info("분야 컬럼 없음 — 공고 재수집 필요")

    # ② 기업 관심분야 분포
    with tab_c2:
        if df_c.empty:
            st.info("선정기업 명단 업로드 후 확인 가능")
        elif '관심사업분야' in df_c.columns:
            all_interests = []
            for val in df_c['관심사업분야']:
                for item in str(val).split(','):
                    item = item.strip()
                    if item and item != 'nan':
                        all_interests.append(item)
            interest_count = pd.Series(all_interests).value_counts().reset_index()
            interest_count.columns = ['관심분야', '기업 수']
            st.bar_chart(interest_count.set_index('관심분야'), height=280)
            st.dataframe(interest_count, use_container_width=True, hide_index=True)
        else:
            st.info("관심사업분야 컬럼 없음")

    # ③ 매칭 점수 분포
    with tab_c3:
        results = st.session_state.get('match_results', [])
        if not results:
            st.info("매칭 실행 후 확인 가능")
        else:
            df_r = pd.DataFrame(results)
            if '관련도' in df_r.columns:
                star_count = df_r['관련도'].value_counts().reset_index()
                star_count.columns = ['관련도', '건수']
                total_r = len(df_r)
                c1,c2 = st.columns(2)
                with c1:
                    st.bar_chart(star_count.set_index('관련도'), height=220)
                with c2:
                    for _, row in star_count.iterrows():
                        st.metric(row['관련도'], f"{row['건수']}건",
                                  f"{row['건수']/total_r*100:.1f}%")
            if '기업명' in df_r.columns:
                st.divider()
                co_count = df_r.groupby('기업명').size().reset_index(name='매칭 건수')
                co_count = co_count.sort_values('매칭 건수', ascending=False)
                st.dataframe(co_count, use_container_width=True, hide_index=True)

    # ④ 발송 추이
    with tab_c4:
        if df_h.empty:
            st.info("발송 이력 쌓이면 확인 가능")
        else:
            if '발송일' in df_h.columns:
                df_h2 = df_h.copy()
                df_h2['발송일'] = pd.to_datetime(df_h2['발송일'], errors='coerce')
                df_h2['월'] = df_h2['발송일'].dt.to_period('M').astype(str)
                monthly = df_h2.groupby('월').size().reset_index(name='발송 건수')
                st.line_chart(monthly.set_index('월'), height=220)
            if '신청여부' in df_h.columns and '선정결과' in df_h.columns:
                st.divider()
                c1,c2,c3 = st.columns(3)
                total_h  = len(df_h)
                applied  = (df_h['신청여부']=='Y').sum()
                selected = (df_h['선정결과']=='선정').sum()
                c1.metric("총 발송", f"{total_h}건")
                c2.metric("신청 건", f"{applied}건",
                          f"{applied/total_h*100:.1f}%" if total_h else "")
                c3.metric("선정 건", f"{selected}건",
                          f"{selected/applied*100:.1f}%" if applied else "")


# ══════════════════════════════════════════════════════
# 기업 관리
# ══════════════════════════════════════════════════════
elif page == "기업 관리":
    drive = _get_drive()
    st.title("기업 관리")
    info_box("기업 관리",
        """
`선정기업_명단.xlsx` 기반 기업 정보 관리

**주요 기능**
- **파일 업로드** — 선정기업 명단 xlsx 업로드 → 드라이브 자동 저장
- **키워드 보완** — 기술키워드 부족 시 담당자 직접 추가 → 매칭 정확도 향상
- **수신거부** — 체크 시 이후 매칭·발송에서 자동 제외
- **구글계정** — 개별 캘린더 공유 시 활용

**매칭 반영 필드** → `기술키워드` + `제품분야` + `키워드보완` 합산
        """,
        "키워드 추가 → 기업 항목 열기 → '키워드 보완' 입력 → 저장")

    with st.spinner("드라이브에서 선정기업 명단 로딩 중..."):
        df_c = load_excel(drive, SELECTED_FILE)

    if df_c.empty:
        st.warning("드라이브에 선정기업 명단이 없음")
        st.info("선정기업_명단.xlsx 파일 업로드 → 드라이브 자동 저장")
        uploaded = st.file_uploader("선정기업_명단.xlsx 업로드", type=["xlsx"])
        if uploaded:
            df_new = pd.read_excel(uploaded, dtype=str).fillna("")
            for col in ['키워드보완','수신거부','메모','구글계정']:
                if col not in df_new.columns: df_new[col] = ''
            with st.spinner("드라이브 저장 중..."):
                if save_excel(drive, df_new, SELECTED_FILE, "선정기업명단", "1F4E79"):
                    st.success(f"{len(df_new)}개사 저장 완료!"); st.rerun()
    else:
        for col in ['키워드보완','수신거부','메모','구글계정']:
            if col not in df_c.columns: df_c[col] = ''

        c1,c2,c3 = st.columns(3)
        c1.metric("선정 기업",   f"{len(df_c)}개사")
        c2.metric("수신거부",    f"{(df_c['수신거부']=='Y').sum()}개사")
        c3.metric("키워드 보완", f"{(df_c['키워드보완']!='').sum()}개사")
        st.divider()

        # 파일 교체 버튼
        with st.expander("📁 선정기업 명단 파일 교체"):
            uploaded = st.file_uploader("새 파일 업로드", type=["xlsx"], key="replace")
            if uploaded:
                df_new = pd.read_excel(uploaded, dtype=str).fillna("")
                for col in ['키워드보완','수신거부','메모','구글계정']:
                    if col not in df_new.columns: df_new[col] = ''
                if save_excel(drive, df_new, SELECTED_FILE, "선정기업명단", "1F4E79"):
                    st.success("교체 완료!"); st.rerun()

        # 컬럼명 확인 및 안내
        if '기업명' not in df_c.columns:
            st.error(f"'기업명' 컬럼을 찾을 수 없음 — 현재 컬럼: {', '.join(df_c.columns.tolist())}")
            st.info("선정기업_명단.xlsx의 첫 번째 컬럼명이 '기업명'인지 확인하세요.")
            st.stop()

        search = st.text_input("🔍 기업명 검색")
        df_show = df_c[df_c['기업명'].str.contains(search, na=False)] if search else df_c

        for idx, row in df_show.iterrows():
            unsub = str(row.get('수신거부','')) == 'Y'
            icon  = "🚫" if unsub else "🏢"
            with st.expander(f"{icon} **{row.get('기업명','')}**  |  {row.get('사업자등록번호','')}  |  {row.get('관심사업분야','')}"):
                c1,c2 = st.columns(2)
                with c1:
                    st.markdown(f"**소재지:** {row.get('소재지','')}")
                    st.markdown(f"**이메일:** {row.get('이메일','')}")
                    st.markdown(f"**관심분야:** {row.get('관심사업분야','')}")
                    st.markdown(f"**수출:** {row.get('수출실적','')} / {row.get('수출국가','')}")
                    st.markdown(f"**TRL단계:** {row.get('TRL단계','')}")
                with c2:
                    st.markdown(f"**제품분야:** {row.get('제품분야','')}")
                    st.markdown(f"**기술키워드:** {row.get('기술키워드','')}")
                    st.markdown(f"**핵심수요태그:** {row.get('핵심수요태그','')}")
                    st.markdown(f"**사업자번호:** {row.get('사업자등록번호','')}")

                extra_kw = st.text_input("키워드 보완", value=row.get('키워드보완',''),
                    key=f"kw_{idx}", placeholder="예: 스마트팜, IoT")
                google_acc = st.text_input("구글계정", value=row.get('구글계정',''),
                    key=f"ga_{idx}", placeholder="example@gmail.com")
                unsub_cb = st.checkbox("수신거부", value=unsub, key=f"unsub_{idx}")
                memo     = st.text_input("메모", value=row.get('메모',''), key=f"memo_{idx}")

                if st.button("💾 저장", key=f"save_{idx}"):
                    df_c.at[idx,'키워드보완']   = extra_kw
                    df_c.at[idx,'구글계정']     = google_acc
                    df_c.at[idx,'수신거부']     = 'Y' if unsub_cb else ''
                    df_c.at[idx,'메모']         = memo
                    with st.spinner("드라이브 저장 중..."):
                        if save_excel(drive, df_c, SELECTED_FILE, "선정기업명단", "1F4E79"):
                            st.success(f"{row['기업명']} 저장 완료!")


# ══════════════════════════════════════════════════════
# 공고 수집
# ══════════════════════════════════════════════════════
elif page == "공고 수집":
    drive = _get_drive()
    st.title("공고 수집")
    info_box("공고 수집",
        """
기업마당 API → 전체 공고 수집 → `notices_db.xlsx` 누적 저장

**수집 방식**
- 금융·기술개발·인력·수출·내수·창업·경영·기타 **8개 분야 전체** 수집
- `pblancId` 기준 **중복 저장 방지** (기존 공고 스킵)
- 내용 수정된 공고 **자동 업데이트**
- 마감일 자동 파싱 (비정형 마감일은 공란 처리)

**권장 수집 주기** — 주 1회 (매주 월요일)
        """,
        "수집 분야 변경 → 화면의 '수집 분야 선택' 옵션에서 체크박스로 선택")

    drive = _get_drive()
    with st.spinner("드라이브에서 공고 DB 로딩 중..."):
        df_n = load_excel(drive, NOTICES_FILE)

    if not df_n.empty:
        c1,c2,c3 = st.columns(3)
        # 방금 수집한 경우 세션 값 우선 표시
        db_count = st.session_state.get('notices_count', len(df_n))
        c1.metric("현재 DB", f"{db_count:,}건")
        c2.metric("마지막 수집일", df_n['수집일'].max() if '수집일' in df_n.columns else "—")
        c3.metric("마감일 파싱 성공",
                  f"{(df_n['마감일']!='').sum()}건" if '마감일' in df_n.columns else "—")

    st.divider()

    # 분야 선택 옵션
    REALM_OPTIONS = {
        "금융":     "01",
        "기술개발": "02",
        "인력":     "03",
        "수출":     "04",
        "내수":     "05",
        "창업":     "06",
        "경영":     "07",
        "기타":     "09",
    }

    with st.expander("⚙️ 수집 분야 선택 (기본: 전체)", expanded=False):
        st.caption("원칙은 전체 수집 — 특정 분야만 빠르게 확인할 때 선택")
        col1, col2, col3, col4 = st.columns(4)
        selected_realms = {}
        for i, (name, code) in enumerate(REALM_OPTIONS.items()):
            col = [col1, col2, col3, col4][i % 4]
            selected_realms[code] = col.checkbox(name, value=True, key=f"realm_{code}")

        selected_codes = [code for code, checked in selected_realms.items() if checked]
        if not selected_codes:
            st.warning("최소 1개 이상 선택 필요")
            selected_codes = list(REALM_OPTIONS.values())

        st.caption(f"선택된 분야: **{len(selected_codes)}개** / {', '.join([k for k,v in REALM_OPTIONS.items() if v in selected_codes])}")

    if st.button("🔄 지금 수집 실행", type="primary"):
        REALM_CODES = selected_codes
        all_items, seen = [], set()
        prog = st.progress(0); log_area = st.empty(); logs = []
        realm_name_map = {v:k for k,v in REALM_OPTIONS.items()}

        import time as _time
        for idx, code in enumerate(REALM_CODES):
            params = {"crtfcKey":API_KEY,"dataType":"json","searchCnt":"0","searchLclasId":code}
            realm_name = realm_name_map.get(code, code)
            success = False
            for retry in range(3):  # 최대 3회 재시도
                try:
                    _time.sleep(0.8 if retry == 0 else 2)  # 첫 요청 0.8초, 재시도 2초 대기
                    resp  = requests.get(BASE_URL, params=params, timeout=40)
                    items = resp.json().get('jsonArray', [])
                    for item in items:
                        pid = item.get('pblancId','')
                        if pid and pid not in seen:
                            seen.add(pid); all_items.append(item)
                    logs.append(f"✅ {realm_name}: {len(items)}건")
                    success = True
                    break
                except Exception as e:
                    if retry < 2:
                        logs.append(f"⚠️ {realm_name}: 재시도 중... ({retry+1}/3)")
                    else:
                        logs.append(f"❌ {realm_name}: 수집 실패 ({e})")
                log_area.code("\n".join(logs))
            prog.progress((idx+1)/len(REALM_CODES)); log_area.code("\n".join(logs))

        def to_row(item):
            def pdl(s):
                try: return datetime.strptime(re.sub(r'\.', '-', s.split('~')[-1].strip()), "%Y-%m-%d").strftime("%Y-%m-%d")
                except: return ""
            return {"pblancId":item.get('pblancId',''),"공고명":item.get('pblancNm',''),
                    "주관기관":item.get('jrsdInsttNm',''),"분야":item.get('pldirSportRealmLclasCodeNm',''),
                    "세부분야":item.get('pldirSportRealmMlsfcCodeNm',''),
                    "접수기간":item.get('reqstBeginEndDe',''),"마감일":pdl(item.get('reqstBeginEndDe','')),
                    "지원대상":item.get('trgetNm',''),
                    "사업개요":strip_html(item.get('bsnsSumryCn','')),  # API 전체 반환값 저장
                    "해시태그":item.get('hashtags',''),"공고링크":item.get('pblancUrl',''),
                    "전문내용":"",  # 크롤링 후 채워짐
                    "수정일":item.get('updtPnttm',''),"수집일":datetime.today().strftime("%Y-%m-%d")}

        today = datetime.today().strftime("%Y-%m-%d")
        ex_map = {r['pblancId']:r.get('수정일','') for _,r in df_n.iterrows()} if not df_n.empty else {}
        new_rows, upd_rows = [], []
        dup_count = 0
        for item in all_items:
            pid = item.get('pblancId','')
            if not pid: continue
            row = to_row(item)
            if pid not in ex_map:
                new_rows.append(row)
            elif ex_map[pid] != item.get('updtPnttm',''):
                upd_rows.append(row)
            else:
                dup_count += 1

        if not df_n.empty:
            upd_ids  = {r['pblancId'] for r in upd_rows}
            df_base  = df_n[~df_n['pblancId'].isin(upd_ids)].copy()
            # 기존 공고도 수집일 오늘로 갱신 (마지막 수집일 반영)
            df_base['수집일'] = today
            df_final = pd.concat([df_base, pd.DataFrame(new_rows+upd_rows)], ignore_index=True)
        else:
            df_final = pd.DataFrame(new_rows)

        summary = "\n".join(logs) + f"\n\n📊 결과 요약\n  신규: {len(new_rows)}건 / 업데이트: {len(upd_rows)}건 / 중복유지: {dup_count}건 / 총 DB: {len(df_final):,}건"
        log_area.code(summary)

        with st.spinner("드라이브 저장 중..."):
            save_ok = save_excel(drive, df_final, NOTICES_FILE, "공고DB", "00897B")

        prog.progress(1.0)
        if save_ok:
            st.session_state['notices_count'] = len(df_final)
            st.session_state['notices_new']   = len(new_rows)
            st.session_state['notices_upd']   = len(upd_rows)
            st.session_state['pending_crawl'] = True  # 크롤링 필요 플래그
            st.success(
                f"✅ 수집 완료 — 총 {len(df_final):,}건 "
                f"(신규 {len(new_rows)} / 업데이트 {len(upd_rows)} / 중복유지 {dup_count})"
            )
            st.rerun()
        else:
            st.error("❌ 드라이브 저장 실패 — 설정 메뉴에서 드라이브 연동 확인 필요")
            st.info(f"수집은 완료: 총 {len(df_final):,}건 (신규 {len(new_rows)} / 업데이트 {len(upd_rows)} / 중복 {dup_count})")

    if not df_n.empty:
        st.divider()
        st.subheader("공고 DB 미리보기 (최근 20건)")
        cols = [c for c in ["공고명","주관기관","분야","접수기간","마감일"] if c in df_n.columns]
        st.dataframe(df_n[cols].head(20), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📄 공고 전문 크롤링")

    with st.spinner("전문 DB 현황 확인 중..."):
        df_detail = load_excel(drive, DETAIL_FILE)

    today_str = datetime.today().strftime('%Y-%m-%d')
    FRESHNESS_DAYS = 7  # 7일 이내 크롤링 = 최신

    if not df_detail.empty and '크롤링일' in df_detail.columns:
        df_detail['크롤링일'] = df_detail['크롤링일'].astype(str)
        fresh   = df_detail[df_detail['크롤링일'] >= (datetime.today() - timedelta(days=FRESHNESS_DAYS)).strftime('%Y-%m-%d')]
        stale   = df_detail[df_detail['크롤링일'] <  (datetime.today() - timedelta(days=FRESHNESS_DAYS)).strftime('%Y-%m-%d')]
        ok_pids = set(df_detail[df_detail['크롤링성공']=='Y']['pblancId'].tolist())
    else:
        fresh = stale = pd.DataFrame(); ok_pids = set()

    # 최신화 필요 공고 계산
    if not df_n.empty:
        active_pids = set(df_n[
            (df_n['마감일'] == '') | (df_n['마감일'] >= today_str)
        ]['pblancId'].tolist())
        need_crawl_pids = active_pids - ok_pids
    else:
        active_pids = need_crawl_pids = set()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전문 수집", f"{len(ok_pids):,}건")
    c2.metric("7일 이내 최신", f"{len(fresh):,}건")
    c3.metric("갱신 필요", f"{len(stale):,}건")
    c4.metric("미수집 (활성공고)", f"{len(need_crawl_pids):,}건")

    if st.session_state.get('pending_crawl'):
        st.info(f"💡 공고 수집 완료 — 전문 크롤링을 실행하면 매칭 정확도가 높아져요.")

    col_a, col_b = st.columns([2,1])
    with col_a:
        st.caption(f"7일 이내 수집된 전문은 재수집 안 함. 미수집 {len(need_crawl_pids)}건 + 갱신필요 {len(stale)}건 대상.")
    with col_b:
        crawl_toggle = st.toggle("크롤링 실행", value=bool(st.session_state.get('pending_crawl')), key="crawl_toggle")

    if crawl_toggle:
        st.warning("⚠️ 수동 크롤링 — 공고 수에 따라 수십 분 소요될 수 있습니다. 설정한 건수마다 자동 중간 저장되어, 중간에 끊겨도 이미 처리한 건은 보존됩니다. 끊기면 그냥 다시 실행하면 미수집분부터 이어집니다.")

        col1, col2, col3 = st.columns(3)
        with col1:
            crawl_limit = st.number_input(
                "최대 크롤링 건수 (0 = 전체)",
                min_value=0, max_value=2000, value=50,
                help="테스트 시 50건 권장, 전체는 0 입력"
            )
        with col2:
            crawl_delay = st.selectbox(
                "요청 간격",
                ["빠름 (0.5초)", "보통 (1.2초)", "느림 (2초)"],
                index=1
            )
            delay_map = {"빠름 (0.5초)": 0.5, "보통 (1.2초)": 1.2, "느림 (2초)": 2.0}
            delay_sec = delay_map[crawl_delay]
        with col3:
            batch_size = st.number_input(
                "중간 저장 단위 (건)",
                min_value=10, max_value=200, value=30,
                help="이 건수마다 드라이브에 저장 → 중간에 끊겨도 이전 작업 보존"
            )

        if st.button("🕷️ 지금 크롤링 실행", type="primary", key="crawl_btn"):
            import time as _time
            from bs4 import BeautifulSoup

            today = datetime.today().strftime('%Y-%m-%d')

            def clean_notice_text(raw_text):
                """bizinfo 공고 본문에서 사이트 네비게이션/추천목록/평점위젯/첨부파일 영역을
                제거하고 실제 사업개요+신청자격+지원내용 영역만 남긴다.
                (실측 검증: 평균 1723자 -> 805자로 잡음 약 50% 제거, 핵심 정보는 보존)"""
                text = re.sub(r'본문\s*바로가기.*?화면크기', ' ', raw_text, flags=re.DOTALL)
                end_markers = [
                    r'이\s*공고를\s*열람한\s*사용자',  # 관련 공고 추천 영역 시작
                    r'NO\.\s*1\b',                      # 추천 목록 항목 시작
                    r'정보에\s*만족하셨나요',            # 평점 위젯
                    r'본문출력파일',                    # 첨부파일 목록 시작
                ]
                cut_idx = len(text)
                for pat in end_markers:
                    m = re.search(pat, text)
                    if m:
                        cut_idx = min(cut_idx, m.start())
                text = text[:cut_idx]
                text = re.sub(r'\s+', ' ', text).strip()
                return text

            import re

            # 크롤링 대상 필터
            # 날짜 기반 최신화: 미수집 + 7일 초과 갱신필요 + 마감 안 지난 것
            stale_pids = set(stale['pblancId'].tolist()) if not stale.empty else set()
            fresh_pids = set(fresh[fresh['크롤링성공']=='Y']['pblancId'].tolist()) if not fresh.empty else set()
            df_target = df_n[
                (~df_n['pblancId'].isin(fresh_pids)) &  # 최신 성공 건 제외
                ((df_n['마감일'] == '') | (df_n['마감일'] >= today))
            ].copy()

            if crawl_limit > 0:
                df_target = df_target.head(crawl_limit)

            st.info(f"크롤링 대상: {len(df_target)}건 (총 {-(-len(df_target)//batch_size)}개 배치, {batch_size}건씩 저장)")
            prog = st.progress(0); log_area = st.empty(); batch_status = st.empty()
            logs = []; new_records = []; success = fail = 0
            total_saved = 0

            HEADERS = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "ko-KR,ko;q=0.9",
                "Referer": "https://www.bizinfo.go.kr/",
            }

            def save_batch(records_to_save):
                """new_records를 notices_detail.xlsx에 누적 저장. 매번 드라이브에서 최신본을 다시 읽어 합친다."""
                if not records_to_save:
                    return True
                with st.spinner(f"드라이브 저장 중... (누적 {total_saved + len(records_to_save)}건)"):
                    df_latest = load_excel(drive, DETAIL_FILE)  # 다른 배치/실행과 충돌 방지 위해 매번 최신본 로드
                    df_new_batch = pd.DataFrame(records_to_save)
                    df_merged = pd.concat([df_latest, df_new_batch], ignore_index=True) if not df_latest.empty else df_new_batch
                    # pblancId 중복 시 가장 마지막(최신) 레코드만 유지
                    if 'pblancId' in df_merged.columns:
                        df_merged = df_merged.drop_duplicates('pblancId', keep='last')
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w:
                        df_merged.to_excel(w, index=False)
                    return drive_upload(drive, DETAIL_FILE, buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            for i, (_, row) in enumerate(df_target.iterrows()):
                url = row.get('공고링크','')
                pid = row.get('pblancId','')
                name = row.get('공고명','')[:25]
                if not url or not pid: continue

                try:
                    _time.sleep(delay_sec)
                    resp = requests.get(url, headers=HEADERS, timeout=20)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, 'html.parser')
                        full_text = ""
                        for sel in ['.view-content','.detail-content','#bizSumryCn',
                                    '.bbs-view-content','#content','.board-view']:
                            el = soup.select_one(sel)
                            if el:
                                full_text = el.get_text(separator=' ', strip=True)
                                if len(full_text) > 200: break
                        if len(full_text) < 100:
                            body = soup.find('body')
                            if body:
                                for tag in body.find_all(['nav','header','footer','script','style']):
                                    tag.decompose()
                                full_text = body.get_text(separator=' ', strip=True)

                        full_text = clean_notice_text(full_text)

                        amount = ""
                        for pat in [
                            r'(?:지원|보조|사업비?)\s{0,3}(?:금액|한도)[^0-9]{0,10}([0-9][0-9,]*\s{0,2}(?:백만원|천만원|만원|억원))',
                            r'(?:총|최대)\s{0,3}([0-9][0-9,]*\s{0,2}(?:백만원|천만원|만원|억원))\s{0,3}(?:이내|한도|지원)',
                            r'([0-9][0-9,]*\s{0,2}(?:백만원|천만원|만원|억원))\s{0,3}이내\s{0,3}지원',
                        ]:
                            m = re.search(pat, full_text)
                            if m: amount = m.group(0)[:30]; break
                        scale = ""
                        for pat in [
                            r'([0-9]+)\s{0,2}개\s{0,3}(?:사|업체|기업)\s{0,4}(?:내외|이내|선정|모집)',
                            r'선정\s{0,4}(?:규모|예정)[^0-9]{0,10}([0-9]+)\s{0,2}(?:개|개사|개업체)',
                            r'모집\s{0,4}(?:규모|인원)[^0-9]{0,10}([0-9]+)\s{0,2}(?:개|개사|개업체|명)',
                        ]:
                            m = re.search(pat, full_text)
                            if m: scale = m.group(0)[:30]; break

                        # HTTP 200이어도 본문이 충분히 확보되지 않으면 실패로 처리
                        MIN_TEXT_LEN = 200
                        ok = len(full_text) >= MIN_TEXT_LEN
                        if ok:
                            new_records.append({'pblancId':pid,'전문내용':full_text[:4000],
                                               '지원금액':amount,'선정규모':scale,'크롤링방법':'requests',
                                               '크롤링일':today,'크롤링성공':'Y'})
                            success += 1
                            logs.append(f"✅ {name} ({len(full_text)}자)")
                        else:
                            # 진단용: 원인 파악을 위해 raw HTML 일부와 body 길이를 남긴다
                            # (정상 매칭에는 쓰이지 않도록 크롤링성공=N 유지, 단 내용으로 원인 추정 가능)
                            raw_title = soup.title.string.strip() if soup.title and soup.title.string else ''
                            diag = f"[진단] raw_html_len={len(resp.text)} title='{raw_title[:50]}' body_text_len={len(full_text)} raw_snippet={resp.text[:200]!r}"
                            new_records.append({'pblancId':pid,'전문내용':diag[:1000],
                                               '지원금액':'','선정규모':'','크롤링방법':'requests-diag',
                                               '크롤링일':today,'크롤링성공':'N'})
                            fail += 1
                            logs.append(f"❌ {name} (본문 {len(full_text)}자, html {len(resp.text)}자, title='{raw_title[:20]}')")
                    else:
                        new_records.append({'pblancId':pid,'전문내용':f"[진단] HTTP {resp.status_code}",'지원금액':'',
                                           '선정규모':'','크롤링방법':'requests','크롤링일':today,'크롤링성공':'N'})
                        fail += 1
                        logs.append(f"❌ {name} (HTTP {resp.status_code})")
                except Exception as e:
                    new_records.append({'pblancId':pid,'전문내용':f"[진단] 예외: {str(e)[:100]}",'지원금액':'',
                                       '선정규모':'','크롤링방법':'requests','크롤링일':today,'크롤링성공':'N'})
                    fail += 1
                    logs.append(f"❌ {name} ({str(e)[:30]})")

                prog.progress((i+1)/len(df_target))
                log_area.code("\n".join(logs[-10:]))

                # ── 배치 단위 중간 저장 ──────────────────
                if len(new_records) >= batch_size:
                    if save_batch(new_records):
                        total_saved += len(new_records)
                        batch_status.success(f"💾 중간 저장 완료 — 누적 {total_saved}건 ({i+1}/{len(df_target)} 진행)")
                        new_records = []  # 저장된 건 비우고 다음 배치 시작
                    else:
                        batch_status.error("⚠️ 중간 저장 실패 — 다음 배치에서 재시도")

            # 잔여분(배치 크기 미만으로 남은 마지막 묶음) 저장
            if new_records:
                if save_batch(new_records):
                    total_saved += len(new_records)
                    st.success(f"✅ 크롤링 완료 — 성공 {success}건 / 실패 {fail}건 / 총 저장 {total_saved}건 → notices_detail.xlsx")
                    st.rerun()
                else:
                    st.error(f"드라이브 저장 실패 — 단, 이전 배치 {total_saved}건은 이미 저장되어 있습니다.")
            elif total_saved > 0:
                st.success(f"✅ 크롤링 완료 — 성공 {success}건 / 실패 {fail}건 / 총 저장 {total_saved}건 → notices_detail.xlsx")
                st.rerun()
            else:
                st.info("새로 크롤링할 공고 없음")


# ══════════════════════════════════════════════════════
# 매칭 결과
# ══════════════════════════════════════════════════════
elif page == "매칭 결과":
    drive = _get_drive()
    st.title("매칭 결과")
    info_box("매칭 결과",
        """
선정기업 × 공고 DB 교차 매칭 → 담당자 검토 → 발송 승인

**매칭 로직**
- 전체 공고 대상 매칭 (분야 필터 없음 → 숨겨진 적합 공고도 발굴)
- 키워드 4개 축으로 적합성 판단 → 점수 높은 순 정렬
- 이미 발송한 공고 자동 제외 (send_history 참조)
- 마감 지난 공고 자동 제외
- 수신거부 기업 자동 제외
- 키워드 스코어링 → 점수 높은 순 정렬 → 기업당 최대 N건 추출

**검토 방법** — ○ 승인 / ✕ 제외 클릭 → 공고 원문 링크로 내용 확인 후 판단
★★★ 위주 먼저 검토 권장
        """,
        "기업당 건수 → 슬라이더 조정 / 키워드 → 설정 메뉴에서 변경")

    tab1, tab2 = st.tabs(["매칭 실행", "검토 & 승인"])

    with tab1:
        # ── Step 표시 ────────────────────────────────
        st.markdown("""
        <div style="display:flex;gap:8px;margin-bottom:20px;">
          <div style="background:#4A9EFF;color:#fff;border-radius:20px;padding:6px 14px;font-size:12px;font-weight:700;">Step 1 · 1차 매칭</div>
          <div style="color:#A0AEC0;font-size:12px;padding:6px 4px;">→</div>
          <div style="background:#1A2940;color:#A0AEC0;border-radius:20px;padding:6px 14px;font-size:12px;">Step 2 · 전문 크롤링</div>
          <div style="color:#A0AEC0;font-size:12px;padding:6px 4px;">→</div>
          <div style="background:#1A2940;color:#A0AEC0;border-radius:20px;padding:6px 14px;font-size:12px;">Step 3 · 최종 매칭</div>
          <div style="color:#A0AEC0;font-size:12px;padding:6px 4px;">→</div>
          <div style="background:#1A2940;color:#A0AEC0;border-radius:20px;padding:6px 14px;font-size:12px;">Step 4 · 검토 & 발송</div>
        </div>
        """, unsafe_allow_html=True)

        # ── Step 1: 1차 매칭 ─────────────────────────
        st.subheader("Step 1 — 1차 매칭")
        st.caption("API 사업개요 기반으로 후보 공고를 추출합니다. 기업당 20건 후보 → 크롤링 후 최종 10~12건으로 압축")

        col1, col2 = st.columns(2)
        with col1:
            max_per = st.slider("기업당 최대 추천 건수 (최종)", 5, 20, 12)
        with col2:
            candidate_per = st.slider("기업당 1차 후보 건수 (크롤링 대상)", 10, 30, 20)

        st.markdown("**발송 대상 그룹**")
        target_group = st.radio(
            "발송 대상 그룹", ["선정 50개사", "예비 20개사", "전체 70개사"],
            horizontal=True, label_visibility="collapsed", key="match_target_group"
        )

        if st.button("🔍 1차 매칭 실행", type="primary"):
            with st.spinner("드라이브 데이터 로딩 중..."):
                df_c    = load_excel(drive, SELECTED_FILE)
                df_n    = load_excel(drive, NOTICES_FILE)
                df_h    = load_excel(drive, HISTORY_FILE)
                HIGH, MID = load_keywords(drive)
                detail_map = {}
                notice_detail_count = 0
            if df_n.empty: st.error("notices_db 없음 → 공고 수집 먼저"); st.stop()
            if df_c.empty: st.error("선정기업 명단 없음 → 기업 관리에서 업로드"); st.stop()
            if '선정구분' in df_c.columns:
                if target_group == "선정 50개사":
                    df_c = df_c[df_c['선정구분'] == '선정']
                elif target_group == "예비 20개사":
                    df_c = df_c[df_c['선정구분'] == '예비']
                # "전체 70개사"는 필터 없음
            else:
                st.warning("선정기업 명단에 '선정구분' 컬럼이 없어 전체 기업으로 매칭합니다.")
            if df_c.empty:
                st.error(f"'{target_group}' 대상 기업이 없습니다."); st.stop()
            if '수신거부' in df_c.columns: df_c = df_c[df_c['수신거부']!='Y']
            already_sent = set(zip(df_h['기업명'], df_h['pblancId'])) if not df_h.empty else set()
            all_results  = []; prog = st.progress(0)
            notice_recommend_count = {}  # 공고별 추천 횟수 추적

            for idx,(_,row) in enumerate(df_c.iterrows()):
                scored = [r for _,n in df_n.iterrows()
                          if (r:=score_notice(n.to_dict(),row,already_sent,HIGH,MID))]

                # 다양성 점수 적용: 이미 많이 추천된 공고는 점수 하향
                for r in scored:
                    pid = r.get('공고ID','')
                    cnt = notice_recommend_count.get(pid, 0)
                    if cnt >= 5:
                        r['점수'] -= 6   # 5개사 이상 추천 → 강한 페널티
                    elif cnt >= 3:
                        r['점수'] -= 3   # 3개사 이상 추천 → 중간 페널티

                scored.sort(key=lambda x:-x['점수'])
                top = scored[:max_per]

                # 추천 횟수 업데이트
                for r in top:
                    pid = r.get('공고ID','')
                    notice_recommend_count[pid] = notice_recommend_count.get(pid,0) + 1
                    # 공통 여부 태깅 (나중에 메일 구성에 활용)
                    r['_recommend_count'] = notice_recommend_count[pid]

                all_results.extend(top)
                prog.progress((idx+1)/len(df_c))

            # 최종적으로 공통/맞춤 태그 부여
            for r in all_results:
                pid = r.get('공고ID','')
                cnt = notice_recommend_count.get(pid, 1)
                r['공고유형'] = '공통' if cnt >= 4 else '맞춤' 
            st.session_state['match_results'] = all_results
            st.session_state['df_companies_cache'] = df_c
            st.session_state['step1_done'] = True
            # 크롤링 대상 URL 수집
            candidate_pids = list({r.get('공고ID','') for r in all_results})
            candidate_urls = {}
            for _, n in df_n.iterrows():
                if n.get('pblancId','') in candidate_pids:
                    candidate_urls[n['pblancId']] = n.get('공고링크','')
            st.session_state['candidate_urls'] = candidate_urls
            st.success(f"✅ 1차 매칭 완료 — 총 {len(all_results)}건 / 크롤링 대상 {len(candidate_pids)}건")
            st.info("아래 Step 2에서 후보 공고 전문을 크롤링하세요.")

        # ── Step 2: 전문 반영 최종 매칭 (크롤링은 공고수집 탭에서) ──
        st.divider()
        st.subheader("Step 2 — 전문 반영 최종 매칭")
        st.caption("공고 수집 탭에서 전문 크롤링 완료 후 실행하세요.")

        if False:  # 하위 호환용 더미
            if st.button("dummy", key="step2_crawl"):
                from bs4 import BeautifulSoup
                import time as _time, re as _re

                HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                           "Accept-Language": "ko-KR,ko;q=0.9", "Referer": "https://www.bizinfo.go.kr/"}
                today = datetime.today().strftime('%Y-%m-%d')
                prog = st.progress(0); log_area = st.empty(); logs = []
                new_records = []; success = fail = 0

                for i, (pid, url) in enumerate(need_crawl.items()):
                    try:
                        from playwright.sync_api import sync_playwright
                        with sync_playwright() as p:
                            browser = p.chromium.launch(headless=True)
                            page = browser.new_page(user_agent=HEADERS["User-Agent"])
                            page.goto(url, timeout=20000, wait_until="networkidle")
                            _time.sleep(1)
                            full_text = ""
                            for sel in ['#bizSumryCn','.view_con','.view-content','.bbs_view_con','#content']:
                                try:
                                    el = page.query_selector(sel)
                                    if el:
                                        t = el.inner_text()
                                        if len(t) > 200: full_text = t; break
                                except: continue
                            if len(full_text) < 200:
                                full_text = page.inner_text('body')
                            browser.close()
                        amount, scale = "", ""
                        for pat in [r'지원.{0,4}(?:금액|한도)[^0-9]*([0-9][0-9,백천억만원 ]+)']:
                            m = _re.search(pat, full_text)
                            if m: amount = m.group(0)[:40]; break
                        for pat in [r'([0-9]+).{0,3}개.{0,5}(?:사|업체|기업)']:
                            m = _re.search(pat, full_text)
                            if m: scale = m.group(0)[:40]; break
                        ok = len(full_text) > 200
                        new_records.append({'pblancId':pid,'전문내용':full_text[:3000],
                            '지원금액':amount,'선정규모':scale,'크롤링방법':'Playwright',
                            '크롤링일':today,'크롤링성공':'Y' if ok else 'N'})
                        if ok: success+=1; logs.append(f"✅ {pid[:20]} ({len(full_text)}자)")
                        else: fail+=1; logs.append(f"❌ {pid[:20]}")
                    except Exception as e:
                        fail+=1; logs.append(f"❌ {pid[:20]} ({str(e)[:30]})")
                        new_records.append({'pblancId':pid,'전문내용':'','지원금액':'','선정규모':'',
                            '크롤링방법':'FAIL','크롤링일':today,'크롤링성공':'N'})
                    prog.progress((i+1)/len(need_crawl))
                    log_area.code("\n".join(logs[-8:]))
                    _time.sleep(1.0)

                if new_records:
                    df_new = pd.DataFrame(new_records)
                    df_out = pd.concat([df_detail, df_new], ignore_index=True) if not df_detail.empty else df_new
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w: df_out.to_excel(w, index=False)
                    if drive_upload(drive, DETAIL_FILE, buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
                        st.success(f"✅ 크롤링 완료 — 성공 {success}건 / 실패 {fail}건")
                        st.session_state['step2_done'] = True
                        st.rerun()
                    else: st.error("드라이브 저장 실패")

        # ── Step 3: 전문 반영 최종 매칭 ──────────────
        st.divider()
        st.subheader("Step 2 — 전문 반영 최종 매칭")

        if not st.session_state.get('match_results'):
            st.caption("Step 1 매칭 먼저 실행하세요.")
        else:
            df_detail_cur = load_excel(drive, DETAIL_FILE)
            detail_ok = len(df_detail_cur[df_detail_cur['크롤링성공']=='Y']) if not df_detail_cur.empty and '크롤링성공' in df_detail_cur.columns else 0
            st.metric("전문 수집 완료", f"{detail_ok}건")

            if st.button("🔗 전문 반영 최종 매칭", type="primary", key="step3_btn"):
                with st.spinner("전문 DB 반영 중..."):
                    df_n2   = load_excel(drive, NOTICES_FILE)
                    df_c2   = load_excel(drive, SELECTED_FILE)
                    df_h2   = load_excel(drive, HISTORY_FILE)
                    df_det2 = load_excel(drive, DETAIL_FILE)
                    HIGH, MID = load_keywords(drive)

                    detail_map = {}
                    if not df_det2.empty and 'pblancId' in df_det2.columns:
                        # 중복 제거 (성공 건 우선, 최신 건 유지)
                        df_det2 = df_det2.sort_values('크롤링성공', ascending=False)
                        df_det2 = df_det2.drop_duplicates(subset='pblancId', keep='first')
                        detail_map = df_det2.set_index('pblancId').to_dict('index')

                if df_c2.empty or df_n2.empty:
                    st.error("기업 또는 공고 데이터 없음"); st.stop()

                if '수신거부' in df_c2.columns: df_c2 = df_c2[df_c2['수신거부']!='Y']
                already_sent = set(zip(df_h2['기업명'], df_h2['pblancId'])) if not df_h2.empty else set()
                all_results = []; prog = st.progress(0)
                notice_recommend_count = {}

                for idx,(_,row) in enumerate(df_c2.iterrows()):
                    def enrich(n_dict):
                        pid = n_dict.get('pblancId','')
                        if pid in detail_map:
                            d = detail_map[pid]
                            if d.get('전문내용','') and len(str(d.get('전문내용',''))) > len(str(n_dict.get('사업개요',''))):
                                n_dict['사업개요'] = str(d.get('전문내용',''))
                                n_dict['전문내용'] = str(d.get('전문내용',''))
                            n_dict['지원금액'] = d.get('지원금액','')
                            n_dict['선정규모'] = d.get('선정규모','')
                        return n_dict

                    scored = [r for _,n in df_n2.iterrows()
                              if (r:=score_notice(enrich(n.to_dict()),row,already_sent,HIGH,MID))]
                    for r in scored:
                        pid = r.get('공고ID','')
                        cnt = notice_recommend_count.get(pid,0)
                        if cnt >= 5: r['점수'] -= 6
                        elif cnt >= 3: r['점수'] -= 3
                    scored.sort(key=lambda x:-x['점수'])
                    top = scored[:max_per]
                    for r in top:
                        pid = r.get('공고ID','')
                        notice_recommend_count[pid] = notice_recommend_count.get(pid,0)+1
                        r['_recommend_count'] = notice_recommend_count[pid]
                    all_results.extend(top)
                    prog.progress((idx+1)/len(df_c2))

                for r in all_results:
                    r['공고유형'] = '공통' if notice_recommend_count.get(r.get('공고ID',''),1) >= 4 else '맞춤'

                st.session_state['match_results'] = all_results
                st.session_state['df_companies_cache'] = df_c2
                used = sum(1 for r in all_results if r.get('전문내용',''))
                st.success(f"✅ 최종 매칭 완료 — 총 {len(all_results)}건 (전문 활용 {used}건) → '검토 & 승인' 탭으로 이동")
                st.session_state['step2_done'] = True

    with tab2:
        results = st.session_state.get('match_results', [])
        if not results:
            st.info("매칭 실행 탭에서 먼저 실행 필요")
        else:
            df_show = pd.DataFrame(results)
            c1,c2   = st.columns(2)
            with c1: filter_stars = st.multiselect("관련도", ["★★★","★★"], default=["★★★","★★"])
            with c2: filter_co    = st.selectbox("기업", ["전체"]+sorted(df_show['기업명'].unique().tolist()))
            filtered = df_show[df_show['관련도'].isin(filter_stars)]
            if filter_co != "전체": filtered = filtered[filtered['기업명']==filter_co]
            if 'review_state'  not in st.session_state: st.session_state['review_state']  = {}
            if 'ai_analysis'   not in st.session_state: st.session_state['ai_analysis']   = {}
            if 'custom_deadline' not in st.session_state: st.session_state['custom_deadline'] = {}

            ap = sum(1 for v in st.session_state['review_state'].values() if v=="○")
            rj = sum(1 for v in st.session_state['review_state'].values() if v=="✕")
            ai_done = len(st.session_state['ai_analysis'])

            col_stat1, col_stat2 = st.columns([3,1])
            with col_stat1:
                st.caption(
                    f"총 {len(filtered)}건  |  ✅ 승인 {ap}건  |  ❌ 제외 {rj}건"
                    f"  |  🤖 AI분석 {ai_done}건"
                )
            with col_stat2:
                with st.expander("🤖 전체 AI 분석"):
                    usd, krw = estimate_cost(len(filtered))
                    st.caption(f"⚠️ {len(filtered)}건 전체 분석")
                    st.caption(f"예상 비용: ${usd:.3f} (약 {krw:.0f}원)")
                    confirm = st.text_input("확인코드 입력 (분석실행)",
                        key="bulk_ai_confirm", placeholder="분석실행")
                    if st.button("전체 분석 시작", key="bulk_ai_btn", type="primary"):
                        if confirm == "분석실행":
                            prog_ai = st.progress(0, text="AI 분석 중...")
                            for ai_i, (_, ai_row) in enumerate(filtered.iterrows()):
                                ai_key = f"{ai_row['기업명']}_{ai_row.get('공고ID','')}"
                                if ai_key not in st.session_state['ai_analysis']:
                                    co_info = {}
                                    if 'df_companies_cache' in st.session_state:
                                        df_co = st.session_state['df_companies_cache']
                                        co_rows = df_co[df_co['기업명']==ai_row['기업명']]
                                        if not co_rows.empty:
                                            co_info = co_rows.iloc[0].to_dict()
                                    co_info['기업명'] = ai_row['기업명']
                                    result = claude_analyze(co_info, ai_row.to_dict())
                                    st.session_state['ai_analysis'][ai_key] = result
                                prog_ai.progress(
                                    (ai_i+1)/len(filtered),
                                    text=f"AI 분석 중... {ai_i+1}/{len(filtered)}"
                                )
                            st.success(f"전체 분석 완료 — {len(filtered)}건")
                            st.rerun()
                        else:
                            st.error("확인코드가 틀렸습니다 ('분석실행' 입력)")

            st.divider()
            # (custom_deadline 위에서 초기화됨)

            for i,(idx,row) in enumerate(filtered.iterrows()):
                key      = f"{row['기업명']}_{row.get('공고ID','')}"
                current  = st.session_state['review_state'].get(key,"")
                icon     = "🟡" if not current else ("✅" if current=="○" else "❌")
                deadline = row.get('마감일','')
                is_irregular = not deadline or deadline.strip() == ''
                deadline_display = f"⚠️ 비정형" if is_irregular else deadline

                # 매칭 근거 한 줄 표시
                reason = row.get('매칭근거','')

                loc_icon = ""
                if row.get('공고지역',''):
                    _ls = str(row.get('소재지점수','0'))
                    _lv = int(_ls) if _ls.lstrip('-').isdigit() else 0
                    loc_icon = " ✅" if _lv > 0 else (" ⚠️" if _lv < 0 else "")
                with st.expander(
                    f"{icon} **{row['기업명']}**  |  {row.get('관련도','')}  |  "
                    f"{row.get('공고명','')[:28]}{loc_icon}  |  {reason[:22]}"
                ):
                    # ── 상단: 기업 vs 공고 나란히 ──────────────
                    left, right = st.columns(2)
                    with left:
                        st.markdown("**🏢 기업 정보**")
                        co_info = {}
                        if 'df_companies_cache' in st.session_state:
                            df_co = st.session_state['df_companies_cache']
                            co_rows = df_co[df_co['기업명']==row['기업명']]
                            if not co_rows.empty:
                                co_info = co_rows.iloc[0].to_dict()

                        # 소재지 + 공고 지역 비교
                        co_loc      = co_info.get('소재지','—')
                        notice_loc  = row.get('공고지역','')
                        loc_score   = int(str(row.get('소재지점수','0')).strip()) if str(row.get('소재지점수','0')).lstrip('-').strip().isdigit() else 0

                        if notice_loc:
                            if loc_score > 0:
                                loc_tag = "🟢 일치"
                            elif loc_score < 0:
                                loc_tag = "🔴 불일치"
                            else:
                                loc_tag = ""
                            st.markdown(f"- **소재지:** {co_loc} &nbsp; {loc_tag}")
                        else:
                            st.markdown(f"- **소재지:** {co_loc}")

                        st.markdown(f"- **관심분야:** {co_info.get('관심사업분야','—')}")
                        st.markdown(f"- **기술키워드:** {co_info.get('기술키워드','—')}")
                        st.markdown(f"- **제품분야:** {co_info.get('제품분야','—')}")
                        st.markdown(f"- **수출실적:** {co_info.get('수출실적','—')} / {co_info.get('수출국가','—')}")
                        if co_info.get('TRL단계'):
                            st.markdown(f"- **TRL:** {co_info.get('TRL단계')}")
                        if co_info.get('핵심수요태그'):
                            st.markdown(f"- **핵심수요:** {co_info.get('핵심수요태그')}")
                        if co_info.get('키워드보완'):
                            st.markdown(f"- **보완키워드:** {co_info.get('키워드보완')}")

                    with right:
                        st.markdown("**📋 공고 정보**")
                        # 공고 지역 + 기업 소재지 비교
                        if notice_loc:
                            if loc_score > 0:
                                region_tag = f"🟢 `{notice_loc}` (귀사 소재지 포함)"
                            elif loc_score < 0:
                                region_tag = f"🔴 `{notice_loc}` (귀사 소재지 미포함)"
                            else:
                                region_tag = f"`{notice_loc}`"
                            st.markdown(f"- **지역제한:** {region_tag}")
                        else:
                            st.markdown(f"- **지역제한:** 전국 공고")
                        st.markdown(f"- **주관기관:** {row.get('주관기관','—')}")
                        if row.get('지원금액',''):
                            st.markdown(f"- **지원금액:** {row.get('지원금액','')}")
                        if row.get('선정규모',''):
                            st.markdown(f"- **선정규모:** {row.get('선정규모','')}")
                        st.markdown(f"- **지원대상:** {row.get('지원대상','—')}")
                        st.markdown(f"- **접수기간:** {row.get('접수기간','—')}")
                        st.markdown(f"- **마감일:** {deadline_display}")
                        if row.get('공고링크',''):
                            st.markdown(f"[🔗 공고 원문 보기]({row.get('공고링크','')})")

                    st.divider()

                    # ── 매칭 근거 ──────────────────────────────
                    st.markdown("**🔍 매칭 근거**")
                    rc1, rc2, rc3, rc4 = st.columns(4)
                    with rc1:
                        st.caption("지원대상")
                        v = row.get('지원대상매칭','—')
                        st.markdown(f"`{v}`" if v and v!='—' else "—")
                    with rc2:
                        st.caption("사업성격")
                        v = row.get('사업성격매칭','—')
                        st.markdown(f"`{v}`" if v and v!='—' else "—")
                    with rc3:
                        st.caption("업종 역방향")
                        v = row.get('업종역방향매칭','—')
                        st.markdown(f"`{v}`" if v and v!='—' else "—")
                    with rc4:
                        st.caption("기업키워드·수요")
                        v1 = row.get('핵심수요매칭','')
                        v2 = row.get('기업키워드매칭','')
                        v  = v1 or v2 or '—'
                        st.markdown(f"`{v}`" if v and v!='—' else "—")

                    # ── 사업개요 ───────────────────────────────
                    st.divider()
                    st.caption("사업개요")
                    st.markdown(row.get('사업개요',''))

                    # ── 비정형 마감일 입력 ─────────────────────
                    if is_irregular:
                        st.divider()
                        st.caption("📅 비정형 마감일 — 공고 원문 확인 후 직접 입력")
                        custom_dl = st.text_input(
                            "마감일 (YYYY-MM-DD)",
                            value=st.session_state['custom_deadline'].get(key,''),
                            key=f"dl_{key}_{i}",
                            placeholder="예: 2026-06-30"
                        )
                        if custom_dl:
                            st.session_state['custom_deadline'][key] = custom_dl
                            for r in results:
                                if f"{r['기업명']}_{r.get('공고ID','')}" == key:
                                    r['마감일'] = custom_dl; break

                    # ── AI 분석 + 승인/제외 버튼 ──────────────
                    st.divider()
                    bc1, bc2, bc3, bc4 = st.columns([1,1,1.2,2])
                    with bc1:
                        if st.button("○ 승인", key=f"o_{key}_{i}", type="primary"):
                            st.session_state['review_state'][key]="○"; st.rerun()
                    with bc2:
                        if st.button("✕ 제외", key=f"x_{key}_{i}"):
                            st.session_state['review_state'][key]="✕"; st.rerun()
                    with bc3:
                        _usd, _krw = estimate_cost(1)
                        if st.button(f"🤖 AI 분석 (~{_krw:.0f}원)", key=f"ai_{key}_{i}"):
                            if 'ai_analysis' not in st.session_state:
                                st.session_state['ai_analysis'] = {}
                            with st.spinner("Claude 분석 중..."):
                                co_info = {}
                                if 'df_companies_cache' in st.session_state:
                                    df_co = st.session_state['df_companies_cache']
                                    co_rows = df_co[df_co['기업명']==row['기업명']]
                                    if not co_rows.empty:
                                        co_info = co_rows.iloc[0].to_dict()
                                co_info['기업명'] = row['기업명']
                                result = claude_analyze(co_info, row.to_dict())
                                st.session_state['ai_analysis'][key] = result
                            st.rerun()

                    # AI 분석 결과 표시
                    ai_result = st.session_state.get('ai_analysis', {}).get(key)
                    if ai_result:
                        if 'error' in ai_result:
                            st.error(f"분석 오류: {ai_result['error']}")
                        else:
                            rec       = ai_result.get('추천여부','')
                            fit       = ai_result.get('적합도','')
                            rec_color = {"추천":"🟢","검토":"🟡","비추천":"🔴"}.get(rec,"⚪")
                            fit_color = {"높음":"#63FFA8","보통":"#FFC863","낮음":"#FF6363"}.get(fit,"#E8EDF2")
                            icon_map  = {"O":"✅","X":"❌","△":"⚠️"}

                            checks = {
                                "업종일치": ai_result.get('업종일치','—'),
                                "자격충족": ai_result.get('자격충족','—'),
                                "지역적합": ai_result.get('지역적합','—'),
                                "수요일치": ai_result.get('수요일치','—'),
                            }
                            check_html = "".join([
                                f"<span style='margin-right:12px;font-size:12px;'>"
                                f"{icon_map.get(v,'—')} {k}</span>"
                                for k,v in checks.items()
                            ])

                            st.markdown(f"""
<div style="background:rgba(74,158,255,0.08);border:1px solid rgba(74,158,255,0.2);
            border-radius:8px;padding:14px 16px;margin-top:8px;">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
    <span style="font-size:11px;font-weight:700;color:#4A9EFF;letter-spacing:1px;">🤖 CLAUDE 분석</span>
    <span style="font-size:13px;font-weight:700;color:{fit_color};">{rec_color} {rec}</span>
    <span style="font-size:12px;color:rgba(255,255,255,0.5);">적합도: {fit}</span>
  </div>
  <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:#E8EDF2;">
    {ai_result.get('한줄요약','')}
  </p>
  <div style="margin-bottom:10px;">{check_html}</div>
  <p style="margin:0 0 6px;font-size:12px;color:rgba(255,255,255,0.65);line-height:1.7;">
    {ai_result.get('판단근거', ai_result.get('적합이유',''))}
  </p>
  {"<p style=\'margin:8px 0 0;font-size:11px;color:#FFC863;\'>⚠️ " + ai_result.get('주의사항','') + "</p>" if ai_result.get('주의사항','') not in ['없음','','nan'] else ''}
</div>
                            """, unsafe_allow_html=True)
            st.divider()
            c1,c2 = st.columns(2)
            with c1:
                if st.button("✅ 검토 완료 저장", type="primary"):
                    for r in results:
                        r['담당자검토'] = st.session_state['review_state'].get(f"{r['기업명']}_{r.get('공고ID','')}","")
                    st.session_state['match_results'] = results
                    st.success(f"저장 완료 — 승인 {ap}건 → '발송 관리' 메뉴로 이동")
            with c2:
                if st.button("📥 매칭결과 엑셀 저장"):
                    fname = f"매칭결과_{datetime.today().strftime('%Y%m%d')}.xlsx"
                    with st.spinner("드라이브 저장 중..."):
                        save_excel(drive, pd.DataFrame(results), fname, "매칭결과", "C55A11", star_col="관련도")
                    st.success(f"드라이브에 {fname} 저장 완료")


# ══════════════════════════════════════════════════════
# 발송 관리
# ══════════════════════════════════════════════════════
elif page == "발송 관리":
    drive = _get_drive()
    st.title("발송 관리")
    info_box("발송 관리",
        """
담당자 승인(○) 건 → 기업별 HTML 메일 발송 + 캘린더 D-day 등록

**발송 방식**
- HTML 메일 — 공고명 클릭 가능한 링크 포함, 네이버·회사메일 호환
- 캘린더 등록 — 마감 당일·D-7·D-3 이벤트 자동 등록
  - 공통 캘린더: 전체 선정기업 공유
  - 개별 캘린더: 해당 기업 전용 (생성된 경우)
- 발송 이력 — send_history.xlsx 자동 기록 → 다음 매칭 시 중복 제외

**테스트 모드** — 사이드바 토글 ON 시 본인 메일로만 발송
실제 발송 전 테스트 모드로 먼저 확인 권장
        """,
        "발신자 이름·서명 변경 → `app.py` HTML 템플릿 수정")

    results  = st.session_state.get('match_results', [])
    approved = [r for r in results if r.get('담당자검토')=='○']
    matched_group = st.session_state.get('match_target_group', '미확인')

    if not approved:
        st.warning("승인된 공고 없음 — '매칭 결과'에서 검토 완료 후 진행")
    else:
        st.info(f"📌 현재 매칭 대상 그룹: **{matched_group}** (다른 그룹 발송 시 '매칭 결과'에서 그룹 변경 후 재매칭 필요)")
        companies = list(set(r['기업명'] for r in approved))
        c1,c2,c3  = st.columns(3)
        c1.metric("승인 건수", f"{len(approved)}건")
        c2.metric("대상 기업", f"{len(companies)}개사")
        c3.metric("발송 모드", "테스트" if test_mode else "실제")
        if test_mode: st.warning("⚠️ 테스트 모드 — 본인 메일로만 발송")
        else:         st.success("✅ 실제 모드 — 기업 담당자 이메일로 발송")

        st.divider()
        st.subheader("발송 미리보기")
        preview_co      = st.selectbox("기업 선택", companies)
        preview_notices = [r for r in approved if r['기업명']==preview_co]
        with st.expander(f"📧 {preview_co} 메일 미리보기"):
            custom_n = [n for n in preview_notices if n.get('공고유형','맞춤')=='맞춤']
            common_n = [n for n in preview_notices if n.get('공고유형','맞춤')=='공통']
            if custom_n:
                st.caption("**🎯 맞춤 공고**")
                for i,n in enumerate(custom_n,1):
                    st.markdown(f"**{i}. {n.get('관련도','')} [{n.get('공고명','')}]({n.get('공고링크','#')})**")
                    st.caption(f"주관: {n.get('주관기관','')}  |  기간: {n.get('접수기간','')}")
            if common_n:
                st.divider()
                st.caption("**📌 공통 공고 (이런 공고도 있어요)**")
                for i,n in enumerate(common_n,1):
                    st.markdown(f"{i}. [{n.get('공고명','')}]({n.get('공고링크','#')})")
                    st.caption(f"주관: {n.get('주관기관','')}  |  기간: {n.get('접수기간','')}")

        st.divider()
        if st.button("📤 발송 실행", type="primary"):
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            import base64

            cal_id        = load_text(drive, CALID_FILE)
            ind_cals      = load_json(drive, INDCAL_FILE)
            CALENDAR_LINK = f"https://calendar.google.com/calendar?cid={cal_id}" if cal_id else ""
            df_c_cur      = load_excel(drive, SELECTED_FILE)

            history_records = []; prog = st.progress(0); log = st.empty(); logs = []
            grouped = {}
            for r in approved: grouped.setdefault(r['기업명'],[]).append(r)

            for idx,(company,notices) in enumerate(grouped.items()):
                # 공고 분류: 맞춤(기업 전용) / 공통(여러 기업 공통)
                notices_custom = [n for n in notices if n.get('공고유형','맞춤') == '맞춤']
                notices_common = [n for n in notices if n.get('공고유형','맞춤') == '공통']
                # 맞춤 내에서 별점 구분
                notices_sss = [n for n in notices_custom if n.get('관련도','')=='★★★']
                notices_ss  = [n for n in notices_custom if n.get('관련도','')=='★★']

                def notice_card_simple(n, idx):
                    """공통 공고용 심플 카드 (작고 간결하게)"""
                    dl_raw = n.get('마감일','')
                    if not dl_raw and '~' in n.get('접수기간',''):
                        dl_raw = n.get('접수기간','').split('~')[-1].strip()
                    return f"""
                    <table width="100%" cellpadding="0" cellspacing="0"
                           style="margin-bottom:6px;">
                      <tr>
                        <td style="padding:10px 14px;
                                   background:rgba(255,255,255,0.02);
                                   border:1px solid rgba(255,255,255,0.05);
                                   border-radius:6px;">
                          <a href="{n.get('공고링크','#')}"
                             style="font-size:13px;font-weight:500;color:rgba(255,255,255,0.6);
                                    text-decoration:none;display:block;">
                            {n.get('공고명','')}
                          </a>
                          <p style="margin:3px 0 0;font-size:11px;color:rgba(255,255,255,0.25);">
                            {n.get('주관기관','')} &nbsp;·&nbsp; 마감 {dl_raw}
                          </p>
                        </td>
                      </tr>
                    </table>"""

                def notice_card(n, idx):
                    star = n.get('관련도','')
                    dl_raw = n.get('마감일','')
                    if not dl_raw and '~' in n.get('접수기간',''):
                        dl_raw = n.get('접수기간','').split('~')[-1].strip()
                    return f"""
                    <table width="100%" cellpadding="0" cellspacing="0"
                           style="margin-bottom:10px;background:rgba(255,255,255,0.04);
                                  border:1px solid rgba(255,255,255,0.07);
                                  border-radius:10px;overflow:hidden;">
                      <tr>
                        <td style="padding:16px 18px;">
                          <a href="{n.get('공고링크','#')}"
                             style="font-size:14px;font-weight:700;color:#E8EDF2;
                                    text-decoration:none;line-height:1.5;display:block;">
                            {n.get('공고명','')}
                          </a>
                          <p style="margin:6px 0 0;font-size:12px;color:rgba(255,255,255,0.35);">
                            {n.get('주관기관','')}
                            &nbsp;·&nbsp;
                            마감 {dl_raw}
                          </p>
                        </td>
                        <td width="70" align="center" valign="middle"
                            style="padding:16px 12px;
                                   border-left:1px solid rgba(255,255,255,0.06);">
                          <a href="{n.get('공고링크','#')}"
                             style="display:inline-block;font-size:12px;font-weight:600;
                                    color:#4A9EFF;text-decoration:none;white-space:nowrap;">
                            보기 →
                          </a>
                        </td>
                      </tr>
                    </table>"""

                rows_html = ""

                # ── 맞춤 공고 섹션 ──────────────────────
                if notices_sss:
                    rows_html += """
                    <p style="margin:0 0 10px;font-size:10px;font-weight:700;
                               color:#FFC863;letter-spacing:2px;text-transform:uppercase;">
                      ★★★ &nbsp;직접 연계 추천
                    </p>"""
                    for i,n in enumerate(notices_sss): rows_html += notice_card(n, i)
                    rows_html += """<div style="height:20px;"></div>"""

                if notices_ss:
                    rows_html += """
                    <p style="margin:0 0 10px;font-size:10px;font-weight:700;
                               color:#4A9EFF;letter-spacing:2px;text-transform:uppercase;">
                      ★★ &nbsp;참고 추천
                    </p>"""
                    for i,n in enumerate(notices_ss): rows_html += notice_card(n, i)

                # ── 공통 공고 섹션 (이런 공고도 있어요) ──
                if notices_common:
                    rows_html += """<div style="height:24px;"></div>"""
                    rows_html += """
                    <div style="border-top:1px solid rgba(255,255,255,0.08);
                                padding-top:16px;margin-top:4px;">
                      <p style="margin:0 0 10px;font-size:10px;font-weight:700;
                                 color:rgba(255,255,255,0.35);letter-spacing:2px;
                                 text-transform:uppercase;">
                        📌 &nbsp;이런 공고도 있어요
                      </p>"""
                    for i,n in enumerate(notices_common):
                        rows_html += notice_card_simple(n, i)
                    rows_html += "</div>"

                ind_link=""
                if company in ind_cals and ind_cals[company].get('calendar_id'):
                    ind_link=f"""<div style="margin-top:8px">
                      <a href="https://calendar.google.com/calendar?cid={ind_cals[company]['calendar_id']}"
                         style="color:#2E75B6;font-size:13px">📅 {company} 전용 캘린더 구독</a></div>"""

                cal_sec=f"""
                <div style="background:rgba(74,158,255,0.08);border-radius:10px;
                            padding:16px 18px;border:1px solid rgba(74,158,255,0.2);">
                  <p style="margin:0 0 4px;color:#4A9EFF;font-weight:700;font-size:11px;
                             letter-spacing:1.5px;text-transform:uppercase;">
                    📅 마감일 알림 캘린더
                  </p>
                  <p style="margin:0 0 12px;font-size:12px;color:rgba(255,255,255,0.4);">
                    D-7 · D-3 자동 알림을 받아보세요.
                  </p>
                  {"<a href='"+CALENDAR_LINK+"' style='display:inline-block;background:#4A9EFF;color:#0A1628;padding:8px 18px;border-radius:6px;text-decoration:none;font-size:12px;font-weight:700;'>구독하기 →</a>" if CALENDAR_LINK else ""}
                  {ind_link}
                </div>""" if (CALENDAR_LINK or ind_link) else ""

                today_str = datetime.today().strftime('%Y.%m.%d')
                html=f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#F2F4F7;
             font-family:'Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0"
       style="background:#F2F4F7;padding:36px 0 52px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0">

  <!-- ── 로고 헤더 (흰 배경) ── -->
  <tr>
    <td style="background:#ffffff;border-radius:14px 14px 0 0;
               padding:20px 28px;border-bottom:1px solid #E8ECF0;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td valign="middle">
            <img src="{LOGO_URL}"
                 alt="혁신제품지원센터"
                 width="160" height="auto"
                 style="display:block;height:auto;max-height:36px;
                        object-fit:contain;object-position:left;">
          </td>
          <td align="right" valign="middle">
            <p style="margin:0;font-size:11px;color:#A0ADB8;letter-spacing:0.3px;">
              {today_str}
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- ── 다크 메인 카드 ── -->
  <tr>
    <td style="background:#0F1D2E;
               box-shadow:0 8px 32px rgba(0,0,0,0.18);">

      <!-- 헤더존 -->
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding:30px 28px 24px;
                     background:linear-gradient(150deg,#0D1B2A 0%,#132B47 100%);
                     border-bottom:1px solid rgba(255,255,255,0.06);">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td>
                  <p style="margin:0 0 2px;font-size:10px;font-weight:700;
                             letter-spacing:2.5px;color:rgba(255,255,255,0.3);
                             text-transform:uppercase;">
                    Scale-Up Program
                  </p>
                  <h1 style="margin:6px 0 4px;font-size:26px;font-weight:800;
                             color:#FFFFFF;letter-spacing:-0.6px;line-height:1.2;">
                    원스톱 스케일업
                  </h1>
                  <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.38);">
                    맞춤 지원사업 공고 안내
                  </p>
                </td>
                <td align="right" valign="middle" width="72">
                  <div style="background:rgba(74,158,255,0.12);
                              border:1px solid rgba(74,158,255,0.28);
                              border-radius:12px;padding:10px 0;width:60px;
                              text-align:center;">
                    <p style="margin:0;font-size:22px;font-weight:800;color:#4A9EFF;
                               line-height:1;">{len(notices)}</p>
                    <p style="margin:3px 0 0;font-size:9px;letter-spacing:1.2px;
                               color:rgba(74,158,255,0.6);text-transform:uppercase;">picks</p>
                  </div>
                </td>
              </tr>
            </table>
            <!-- 기업명 카드 -->
            <div style="margin-top:20px;padding:14px 18px;
                        background:rgba(255,255,255,0.05);
                        border-radius:8px;border-left:3px solid #4A9EFF;">
              <p style="margin:0 0 3px;font-size:15px;font-weight:700;color:#FFFFFF;">
                {company}
                <span style="font-size:13px;font-weight:400;
                             color:rgba(255,255,255,0.45);margin-left:4px;">담당자님</span>
              </p>
              <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.38);line-height:1.6;">
                기술 키워드 분석을 통해 선별된 공고를 안내드립니다.
              </p>
            </div>
          </td>
        </tr>

        <!-- 공고 목록 -->
        <tr>
          <td style="padding:24px 28px 20px;background:#0F1D2E;">
            {rows_html}
          </td>
        </tr>

        <!-- 캘린더 -->
        {f'''<tr><td style="padding:0 28px 24px;background:#0F1D2E;">{cal_sec}</td></tr>''' if cal_sec else ''}
      </table>
    </td>
  </tr>

  <!-- ── 흰 푸터 ── -->
  <tr>
    <td style="background:#ffffff;border-radius:0 0 14px 14px;
               padding:18px 28px;border-top:1px solid #E8ECF0;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <p style="margin:0;font-size:12px;color:#8A96A3;line-height:1.9;">
              혁신제품지원센터 원스톱 스케일업 운영팀<br>
              <a href="mailto:onestop.kipcc@gmail.com"
                 style="color:#1F4E79;text-decoration:none;font-weight:600;">
                onestop.kipcc@gmail.com
              </a>
            </p>
          </td>
          <td align="right" valign="middle">
            <p style="margin:0;font-size:10px;color:#C5CDD6;letter-spacing:0.5px;">
              수신 동의 기업 대상 발송
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body></html>"""

                co_email=""
                if not df_c_cur.empty and '이메일' in df_c_cur.columns:
                    m = df_c_cur[df_c_cur['기업명']==company]
                    if not m.empty: co_email = m.iloc[0].get('이메일','')

                recipients = get_test_recipients() if test_mode else ([co_email] if co_email else [])
                for to in recipients:
                    msg = MIMEMultipart('alternative')
                    msg['From']    = "onestop.kipcc@gmail.com"
                    msg['To']      = to
                    msg['Subject'] = f"[원스톱 스케일업] 맞춤 지원공고 {len(notices)}건 안내 — {company}"
                    msg.attach(MIMEText(html,'html','utf-8'))
                    gmail_send(base64.urlsafe_b64encode(msg.as_bytes()).decode())

                for n in notices:
                    dl  = parse_deadline(n.get('접수기간','')); pid = n.get('공고ID','')
                    if not dl or not pid: continue
                    desc  = f"주관기관: {n.get('주관기관','')}\n공고링크: {n.get('공고링크','')}\n안내기업: {company}"
                    cids  = [cal_id] if cal_id else []
                    if company in ind_cals and ind_cals[company].get('calendar_id'):
                        cids.append(ind_cals[company]['calendar_id'])
                    for cid in cids:
                        try:
                            if cal_list_events(cid, f"pblancId={pid}").get('items'): continue
                        except: pass
                        for days,label in [(0,"마감"),(7,"D-7"),(3,"D-3")]:
                            d = (dl-timedelta(days=days)).strftime('%Y-%m-%d')
                            cal_insert_event(cid, {
                                'summary':f"[{label}] {n.get('공고명','')}",
                                'description':desc,
                                'start':{'date':d,'timeZone':'Asia/Seoul'},
                                'end':  {'date':d,'timeZone':'Asia/Seoul'},
                                'extendedProperties':{'private':{'pblancId':pid}},
                            })

                for n in notices:
                    history_records.append({"기업명":company,"pblancId":n.get('공고ID',''),
                        "공고명":n.get('공고명',''),"발송일":datetime.today().strftime("%Y-%m-%d"),
                        "매칭점수":n.get('점수',''),"담당자검토":"○",
                        "검토의견":n.get('검토의견',''),"신청여부":"","선정결과":""})

                logs.append(f"✅ {company} — {len(notices)}건 발송 완료")
                log.code("\n".join(logs)); prog.progress((idx+1)/len(grouped))

            with st.spinner("발송 이력 드라이브 저장 중..."):
                df_h   = load_excel(drive, HISTORY_FILE)
                df_new = pd.DataFrame(history_records)
                df_fin = pd.concat([df_h,df_new],ignore_index=True) if not df_h.empty else df_new
                save_excel(drive, df_fin, HISTORY_FILE, "발송이력", "375623")

            prog.progress(1.0)
            st.success(f"발송 완료 — {len(history_records)}건 → send_history.xlsx 저장")
            st.session_state['match_results']=[]; st.session_state['review_state']={}


# ══════════════════════════════════════════════════════
# 발송 이력
# ══════════════════════════════════════════════════════
elif page == "발송 이력":
    drive = _get_drive()
    st.title("발송 이력")
    info_box("발송 이력",
        """
발송 완료 건 기록 + 성과 추적

**자동 기록** — 기업명·공고명·발송일·매칭점수
**담당자 직접 입력** — 신청여부(Y/N)·선정결과(선정/미선정/대기)

**중복 발송 방지** — 이 이력 기반으로 이미 발송한 공고는 다음 매칭에서 자동 제외
재발송 필요 시 해당 행 삭제 후 저장
        """,
        "특정 행 삭제 → 표에서 행 선택 후 Delete → '드라이브 저장' 클릭")

    with st.spinner("드라이브 이력 로딩 중..."):
        df_h = load_excel(drive, HISTORY_FILE)

    if df_h.empty:
        st.info("발송 이력 없음")
    else:
        c1,c2,c3 = st.columns(3)
        c1.metric("총 발송", len(df_h))
        c2.metric("신청 건", (df_h['신청여부']=='Y').sum() if '신청여부' in df_h.columns else 0)
        c3.metric("선정 건", (df_h['선정결과']=='선정').sum() if '선정결과' in df_h.columns else 0)
        st.divider()

        edited = st.data_editor(df_h, use_container_width=True, hide_index=True,
            column_config={
                "신청여부":st.column_config.SelectboxColumn("신청여부",options=["","Y","N"]),
                "선정결과":st.column_config.SelectboxColumn("선정결과",options=["","선정","미선정","대기"]),
            })
        if st.button("💾 드라이브 저장"):
            with st.spinner("저장 중..."):
                save_excel(drive, edited, HISTORY_FILE, "발송이력", "375623")
            st.success("저장 완료")

        st.divider()
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as w: df_h.to_excel(w, index=False)
        st.download_button("📥 엑셀 다운로드", buf.getvalue(), HISTORY_FILE,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ══════════════════════════════════════════════════════
# 성과 집계
# ══════════════════════════════════════════════════════
elif page == "성과 집계":
    drive = _get_drive()
    st.title("성과 집계")
    info_box("성과 집계",
        """
발송 이력 기반 사업 성과 집계

**집계 항목** — 총 발송·신청·선정 건수, 신청 전환율, 기업별 현황
**활용** — 분기 보고서 작성 시 수치 참고
**신청여부·선정결과 입력** — '발송 이력' 메뉴에서 직접 입력
        """)

    with st.spinner("드라이브 이력 로딩 중..."):
        df_h = load_excel(drive, HISTORY_FILE)

    if df_h.empty:
        st.info("발송 이력 없음")
    else:
        total    = len(df_h)
        applied  = (df_h['신청여부']=='Y').sum() if '신청여부' in df_h.columns else 0
        selected = (df_h['선정결과']=='선정').sum() if '선정결과' in df_h.columns else 0
        rate     = f"{applied/total*100:.1f}%" if total else "0%"

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("총 발송",    f"{total}건")
        c2.metric("신청 건",    f"{applied}건")
        c3.metric("선정 건",    f"{selected}건")
        c4.metric("신청 전환율", rate)

        if '기업명' in df_h.columns:
            st.divider(); st.subheader("기업별 현황")
            summary = df_h.groupby('기업명').agg(
                발송건수=('공고명','count'),
                신청건수=('신청여부',lambda x:(x=='Y').sum()),
                선정건수=('선정결과',lambda x:(x=='선정').sum()),
            ).reset_index()
            st.dataframe(summary, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════════
elif page == "설정":
    drive = _get_drive()
    st.title("설정")
    info_box("설정",
        """
시스템 전반 설정 관리

**키워드 설정** — 매칭에 사용되는 ★★★/★★ 키워드 추가·삭제 → 저장 시 즉시 반영
**드라이브 연동** — 각 파일 존재 여부 확인
**인증 상태** — 구글 인증 정상 여부 확인

**코드 수정이 필요한 항목**
테스트 수신 이메일(`TEST_RECIPIENTS`), 발신자 이메일, 드라이브 폴더 ID
→ `app.py` 수정 후 깃허브 push → Streamlit Cloud 자동 재배포
        """)

    # 테스트 메일 설정
    st.subheader("📧 테스트 수신 이메일")
    st.caption("테스트 모드 ON 시 기업 대신 아래 이메일로 발송 — 쉼표로 구분하여 여러 개 입력 가능")

    current_recipients = st.session_state.get(
        'test_recipients_str',
        ', '.join(_DEFAULT_TEST_RECIPIENTS)
    )
    new_recipients = st.text_input(
        "테스트 수신 이메일",
        value=current_recipients,
        placeholder="email1@example.com, email2@example.com",
        label_visibility="collapsed"
    )
    if st.button("💾 테스트 이메일 저장", key="save_test_email"):
        st.session_state['test_recipients_str'] = new_recipients
        parsed = [e.strip() for e in new_recipients.split(',') if e.strip()]
        st.success(f"저장 완료 — {len(parsed)}개: {', '.join(parsed)}")

    st.divider()
    st.subheader("🔐 인증 상태")
    if 'google' in st.secrets: st.success("✅ Streamlit Secrets 인증 설정됨")
    elif os.path.exists('token.json'): st.success("✅ 로컬 token.json 인증 설정됨")
    else: st.error("❌ 인증 파일 없음")

    st.divider()
    st.subheader("📁 드라이브 연동 현황")
    st.markdown(f"[📂 드라이브 폴더 열기](https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID})")
    files_check = {
        SELECTED_FILE:"선정기업 명단", NOTICES_FILE:"공고 DB",
        HISTORY_FILE:"발송 이력",     CALID_FILE:"공통 캘린더 ID",
        KEYWORDS_FILE:"키워드 설정",  CATCAL_FILE:"분야별 캘린더",
        INDCAL_FILE:"기업별 캘린더",
    }
    for fname,label in files_check.items():
        fid = drive_file_id(drive, fname)
        st.write(f"{'✅' if fid else '❌'} {label} ({fname})")

    st.divider()
    st.subheader("🔑 키워드 설정")
    st.caption("수정 후 저장 → keywords.json 드라이브 업데이트 → 다음 매칭부터 반영")

    with st.spinner("키워드 로딩 중..."):
        HIGH, MID = load_keywords(drive)

    st.caption("💡 두 축(지원대상 × 사업성격) 교차로 별점 판정 — 아래에서 각 축 키워드 수정")

    kw_data = load_json(drive, KEYWORDS_FILE)
    tab_k1, tab_k2 = st.tabs(["축1 — 지원대상", "축2 — 사업성격"])

    with tab_k1:
        st.caption("공고가 어떤 기업을 대상으로 하는지 판단 — 대상과 사업성격이 교차될 때 별점 결정")
        current_target = kw_data.get("TARGET_KW", TARGET_KW)
        t_inputs = {}
        label_map1 = {
            "조달기업특화": "조달기업특화 ★★★ (G-PASS·조달청·해외조달 대상 공고)",
            "수출기업특화": "수출기업특화 ★★★ (수출·글로벌 대상 공고)",
            "중소벤처일반": "중소벤처일반 ★★ (일반 중소·벤처 대상 공고)",
        }
        for cat, kws in current_target.items():
            st.markdown(f"**{label_map1.get(cat, cat)}**")
            t_inputs[cat] = st.text_area(
                f"{cat} 키워드", value=", ".join(kws), height=70,
                key=f"tkw_{cat}", label_visibility="collapsed"
            )

    with tab_k2:
        st.caption("공고가 어떤 종류의 지원인지 판단 — 지원대상과 교차하여 별점 결정")
        current_type = kw_data.get("TYPE_KW", TYPE_KW)
        ty_inputs = {}
        label_map2 = {
            "공공조달":   "공공조달 ★★★ (조달청·시범구매·MAS)",
            "해외진출":   "해외진출 ★★★ (수출바우처·해외판로)",
            "마케팅홍보": "마케팅·홍보 ★★ (전시회·박람회·홍보)",
            "인증특허":   "인증·특허 ★★ (해외인증·IP)",
            "기술개발":   "기술개발 ★★ (R&D·기술사업화)",
            "금융융자":   "금융·융자 ★★ (정책자금·보증)",
            "내수판로":   "내수판로 ★★ (온라인몰·유통)",
        }
        col1, col2 = st.columns(2)
        cats = list(current_type.items())
        for i, (cat, kws) in enumerate(cats):
            with (col1 if i % 2 == 0 else col2):
                st.markdown(f"**{label_map2.get(cat, cat)}**")
                ty_inputs[cat] = st.text_area(
                    f"{cat} 키워드", value=", ".join(kws), height=70,
                    key=f"tykw_{cat}", label_visibility="collapsed"
                )

    st.divider()
    st.caption("""
    **별점 판정 기준**
    ★★★: 핵심수요태그 직접 매칭 / 조달기업+공공조달 / 조달기업+해외진출 / 수출기업+해외진출 / 기업키워드+공공조달
    ★★:  기업키워드+사업성격 / 조달·수출기업+마케팅·인증 / 중소벤처+조달·해외진출
    """)
    if st.button("💾 키워드 저장 → 드라이브", type="primary"):
        new_target = {cat: [k.strip() for k in v.replace("\n",",").split(",") if k.strip()]
                      for cat, v in t_inputs.items()}
        new_type   = {cat: [k.strip() for k in v.replace("\n",",").split(",") if k.strip()]
                      for cat, v in ty_inputs.items()}
        save_data  = {
            "TARGET_KW": new_target,
            "TYPE_KW":   new_type,
            "HIGH": sum(new_target.values(), [])[:15],
            "MID":  sum(new_type.values(), [])[:15],
        }
        with st.spinner("드라이브 저장 중..."):
            if save_json(drive, save_data, KEYWORDS_FILE):
                st.success("저장 완료 — 다음 매칭부터 반영")
            else:
                st.error("저장 실패")


# ══════════════════════════════════════════════════════
# 시스템 명세
# ══════════════════════════════════════════════════════
elif page == "시스템 명세":
    st.title("시스템 명세")
    st.caption("원스톱 스케일업 공고 매칭 시스템 — 구조 및 운영 가이드")

    tab1, tab2, tab3, tab4 = st.tabs(["전체 흐름", "매칭 로직", "키워드 구조", "파일 구조"])

    # ── 탭1: 전체 흐름 ──────────────────────────────
    with tab1:
        st.subheader("운영 사이클")
        st.markdown("""
**주간 운영 흐름 (격주 발송 기준)**

| 단계 | 시점 | 담당 | 내용 |
|------|------|------|------|
| ① 공고 수집 | 매주 월요일 | 자동 | bizinfo API → 8개 분야 전체 수집 → notices_db.xlsx 갱신 |
| ② 전문 크롤링 | 매주 수요일 | 자동 | GitHub Actions → 공고 원문 크롤링 → notices_detail.xlsx 저장 |
| ③ 매칭 실행 | 매주 수요일 | 수동 | 앱에서 매칭 실행 → 전문 내용 + 키워드 스코어링 |
| ④ 담당자 검토 | 격주 수~목 | 수동 | ○/✕ 클릭, AI 분석 버튼 활용, 소재지·업종 확인 |
| ⑤ 발송 | 격주 목요일 | 자동 | 맞춤공고 + 공통공고 HTML 메일 + 캘린더 D-day 등록 |
| ⑥ 성과 입력 | 분기 1회 | 수동 | 신청여부·선정결과 발송 이력에 입력 |
        """)

        st.divider()
        st.subheader("시스템 구조도")
        st.markdown("""
```
WALLA 신청서
    ↓ walla_to_selected.py (로컬 1회)
선정기업_명단.xlsx → 구글 드라이브

bizinfo API (매주 월요일, Streamlit 앱)
    ↓
notices_db.xlsx → 구글 드라이브

기업마당 크롤링 (매주 수요일, GitHub Actions 자동)
    ↓
notices_detail.xlsx → 구글 드라이브

[Streamlit 웹앱] scaleup-matching.streamlit.app
    ↓ 매칭 실행 (전문 내용 활용)
    ↓ 담당자 검토 + AI 분석
    ↓
Gmail API → 기업별 HTML 메일 (맞춤 + 공통 공고)
Calendar API → D-7·D-3·마감 캘린더 등록
```
        """)

        st.divider()
        st.subheader("GitHub Actions 크롤링")
        st.markdown("""
**자동 실행 일정**: 매주 수요일 오전 10시 (KST)

**설정 방법**
1. GitHub 저장소 → Settings → Secrets → `GOOGLE_TOKEN_JSON` 추가
2. token.json 파일 내용을 그대로 붙여넣기
3. 이후 매주 수요일 자동 실행

**수동 실행**
GitHub 저장소 → Actions 탭 → `공고 전문 크롤링` → Run workflow
        """)

        st.divider()
        st.subheader("캘린더 구조")
        st.markdown("""
| 유형 | 대상 | 내용 |
|------|------|------|
| 공통 캘린더 1개 | 운영팀 + 전체 기업 | 전체 공고 마감 D-7·D-3 |
| 분야별 캘린더 4개 | 운영팀 내부 | 기술개발/수출/경영금융/혁신제품 |
| 기업별 개별 캘린더 | 해당 기업만 | 해당 기업 맞춤 공고만 |
        """)

    # ── 탭2: 매칭 로직 ──────────────────────────────
    with tab2:
        st.subheader("매칭 3단계 구조")
        st.markdown("""
**Step 1 — 1차 필터 (자동 제외)**
- 마감일 지난 공고
- 수신거부 기업
- 이미 발송한 공고 (send_history 중복 체크)
- 수출실적 없는데 수출 전용 공고
- TRL 8~9인데 기초 R&D 공고
- 업종 불일치 (농식품·의료·건설 등 특정 업종 명시 + 기업 키워드 미매칭)

**Step 2 — 매칭 스코어링 (4개 축)**

| 축 | 내용 | 점수 |
|----|------|------|
| 축1 지원대상 | 조달기업특화·수출기업특화·중소벤처일반 키워드 | +3점/개 |
| 축2 사업성격 | 공공조달·해외진출·마케팅·인증·기술개발·금융·내수·인력 | +2점/개 |
| 축3 역방향매칭 | WALLA 15개 제품분야 → 공고 업종 키워드 매칭 | 최대 +6점 |
| 기업키워드 | 기술키워드+제품분야+키워드보완+핵심수요태그 | +2~3점/개 |
| 소재지 | 공고 지역 일치/불일치 | +2~3 / -3~5 |
| 수출국가 | 기업 주요 수출국 = 공고 대상 국가 | +2점 |

**Step 3 — 별점 판정**

| 별점 | 조건 |
|------|------|
| ★★★ | 핵심수요태그 직접매칭 / 조달기업+공공조달 / 조달기업+해외진출 / 수출기업+해외진출 / 기업키워드+공공조달 |
| ★★ | 기업키워드+사업성격 / 조달·수출기업+마케팅·인증 / 중소벤처+조달·해외진출 |
        """)

        st.divider()
        st.subheader("소재지 판단 우선순위")
        st.markdown("""
| 순위 | 방법 | 예시 | 신뢰도 |
|------|------|------|--------|
| 1순위 | 공고명 [] 패턴 | [경기] 중소기업 수출지원 | 최고 |
| 2순위 | 주관기관이 지자체 | 충청남도, 경기도청 | 높음 |
| 3순위 | 사업개요 "○○ 소재 기업" | "충남 소재 중소기업 대상" | 중간 |
| - | 그 외 전체 텍스트 | 사용 안 함 (오탐 방지) | - |
        """)

    # ── 탭3: 키워드 구조 ────────────────────────────
    with tab3:
        st.subheader("축1 — 지원대상 키워드")
        for cat, kws in TARGET_KW.items():
            with st.expander(f"**{cat}** ({len(kws)}개)"):
                st.markdown(", ".join(f"`{k}`" for k in kws))

        st.divider()
        st.subheader("축2 — 사업성격 키워드")
        for cat, kws in TYPE_KW.items():
            with st.expander(f"**{cat}** ({len(kws)}개)"):
                st.markdown(", ".join(f"`{k}`" for k in kws))

        st.divider()
        st.subheader("축3 — 제품분야 역방향 키워드 (WALLA 15개 카테고리)")
        for cat, kws in INDUSTRY_KW.items():
            with st.expander(f"**{cat}** ({len(kws)}개)"):
                st.markdown(", ".join(f"`{k}`" for k in kws))

        # 총 키워드 수 집계
        total = (sum(len(v) for v in TARGET_KW.values()) +
                 sum(len(v) for v in TYPE_KW.values()) +
                 sum(len(v) for v in INDUSTRY_KW.values()))
        st.info(f"전체 키워드 총 {total}개")

    # ── 탭4: 파일 구조 ──────────────────────────────
    with tab4:
        st.subheader("드라이브 파일")
        st.markdown("""
| 파일명 | 역할 | 생성 방법 |
|--------|------|-----------|
| 선정기업_명단.xlsx | 기업 DB | walla_to_selected.py 로컬 실행 |
| notices_db.xlsx | 공고 DB | 공고 수집 버튼 (매주 월요일) |
| **notices_detail.xlsx** | **공고 전문 DB** | **GitHub Actions 자동 (매주 수요일)** |
| send_history.xlsx | 발송 이력 | 발송 실행 시 자동 기록 |
| keywords.json | 매칭 키워드 | 설정 탭에서 저장 시 자동 생성 |
| calendar_id.txt | 공통 캘린더 ID | create_common_calendar.py 실행 |
| individual_calendars.json | 기업별 캘린더 | create_individual_calendars.py 실행 |
        """)

        st.divider()
        st.subheader("깃허브 파일")
        st.markdown("""
| 파일명 | 역할 |
|--------|------|
| app.py | Streamlit 웹앱 메인 |
| requirements.txt | 라이브러리 목록 |
| **crawl_notices.py** | **공고 전문 크롤러 (GitHub Actions 자동 실행)** |
| **walla_to_selected.py** | **WALLA → 선정기업 명단 변환 (선정 후 1회)** |
| .github/workflows/crawl.yml | GitHub Actions 스케줄러 |
| create_individual_calendars.py | 기업별 캘린더 생성 (선정 후) |
| auth_test.py | 구글 인증 (최초 1회) |
| logo.png | 혁신제품지원센터 CI |
        """)

        st.divider()
        st.subheader("선정기업 명단 컬럼")
        st.markdown("""
| 컬럼 | 구분 | 매칭 활용 |
|------|------|-----------|
| 기업명 | 필수 | 기준키 |
| 소재지 | 필수 | 지역 필터 |
| 이메일 | 필수 | 발송 대상 |
| 관심사업분야 | 필수 | 분야 필터 |
| 기술키워드 | 필수 | 키워드 매칭 |
| 제품분야 | 필수 | 역방향 매칭 |
| 수출실적 | 필수 | 수출 공고 필터 |
| 수출국가 | 필수 | 국가 매칭 |
| TRL단계 | 매칭고도화 | R&D 공고 필터 |
| 핵심수요태그 | 매칭고도화 | 최우선 매칭 (+3점) |
| 매출규모 | 매칭고도화 | (추후 활용) |
| 키워드보완 | 운영관리 | 보완 키워드 |
| 수신거부 | 운영관리 | 발송 제외 |
        """)
