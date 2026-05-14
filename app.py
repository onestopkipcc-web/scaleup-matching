"""
원스톱 스케일업 — 공고 매칭 시스템
구글 드라이브 연동 + 엑셀 저장 + 키워드 설정 저장
"""
import streamlit as st
import pandas as pd
import requests
import re, os, json, io
from datetime import datetime, timedelta

st.set_page_config(
    page_title="원스톱 스케일업",
    page_icon="📢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 상수 ──────────────────────────────────────────────
DRIVE_FOLDER_ID  = "1iWGYjaoslqST45ggDlg-IPMLaUHCYmV_"
API_KEY          = "Nt604D"
BASE_URL         = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
COMPANIES_FILE   = "companies_db.xlsx"
NOTICES_FILE     = "notices_db.xlsx"
HISTORY_FILE     = "send_history.xlsx"
KEYWORDS_FILE    = "keywords.json"
CALID_FILE       = "calendar_id.txt"
CATCAL_FILE      = "category_calendars.json"
INDCAL_FILE      = "individual_calendars.json"

# 기본 키워드 (keywords.json 없을 때 사용)
DEFAULT_HIGH = ["혁신제품","혁신조달","G-PASS","혁신기업","해외조달","공공구매","조달청"]
DEFAULT_MID  = ["해외판로","수출바우처","수출지원","해외진출","글로벌","스케일업","판로개척","해외마케팅"]

REALM_CODE = {
    "금융":"01","기술개발":"02","인력":"03","수출":"04",
    "내수":"05","창업":"06","경영":"07","기타":"09",
}

# ── 구글 인증 ─────────────────────────────────────────
@st.cache_resource
def get_services():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    SCOPES = [
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/drive',
    ]

    if 'google' in st.secrets:
        token_data = json.loads(st.secrets['google']['token'])
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        st.error("인증 파일이 없습니다."); st.stop()

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return (
        build('gmail',    'v1', credentials=creds),
        build('calendar', 'v3', credentials=creds),
        build('drive',    'v3', credentials=creds),
    )

# ── 드라이브 유틸 ─────────────────────────────────────
def drive_file_id(drive, filename):
    try:
        res = drive.files().list(
            q=f"name='{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed=false",
            fields="files(id,name)", orderBy="modifiedTime desc"
        ).execute()
        files = res.get('files', [])
        return files[0]['id'] if files else None
    except: return None

def drive_download_bytes(drive, filename):
    try:
        fid = drive_file_id(drive, filename)
        return drive.files().get_media(fileId=fid).execute() if fid else None
    except: return None

def drive_upload_bytes(drive, filename, content_bytes, mime):
    from googleapiclient.http import MediaIoBaseUpload
    try:
        fid   = drive_file_id(drive, filename)
        media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype=mime)
        if fid:
            drive.files().update(fileId=fid, media_body=media).execute()
        else:
            drive.files().create(
                body={'name': filename, 'parents': [DRIVE_FOLDER_ID]},
                media_body=media
            ).execute()
        return True
    except Exception as e:
        st.warning(f"드라이브 저장 실패 ({filename}): {e}"); return False

# ── 엑셀 드라이브 저장/로드 ───────────────────────────
def load_excel_from_drive(drive, filename):
    content = drive_download_bytes(drive, filename)
    if content:
        try:
            return pd.read_excel(io.BytesIO(content), dtype=str).fillna("")
        except: return pd.DataFrame()
    return pd.DataFrame()

def save_excel_to_drive(drive, df, filename, sheet_name="데이터",
                         header_color="1F4E79", star_col=None):
    """DataFrame → 스타일 엑셀 → 드라이브 저장"""
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.sheet_view.showGridLines = False

    s   = Side(style="thin", color="BFBFBF")
    bdr = Border(left=s, right=s, top=s, bottom=s)

    # 헤더
    for ci, col in enumerate(df.columns, 1):
        c = ws.cell(row=1, column=ci, value=col)
        c.fill      = PatternFill("solid", start_color=header_color, end_color=header_color)
        c.font      = Font(name="맑은 고딕", bold=True, color="FFFFFF", size=10)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border    = bdr
        ws.column_dimensions[get_column_letter(ci)].width = max(len(str(col))*2, 14)
    ws.row_dimensions[1].height = 24

    # 데이터
    star_colors = {"★★★":"FFF2CC", "★★":"E2EFDA"}
    review_colors = {"○":"D5E8D4", "✕":"FFE6E6"}

    for ri, row in enumerate(df.itertuples(index=False), 2):
        row_vals = list(row)
        # 별점 행 색상
        bg = "FFFFFF"
        if star_col and star_col in df.columns:
            star_val = row_vals[df.columns.tolist().index(star_col)]
            bg = star_colors.get(star_val, "FFFFFF")

        ws.row_dimensions[ri].height = 18
        for ci, val in enumerate(row_vals, 1):
            col_name = df.columns[ci-1]
            # 담당자검토 컬럼 색상
            if col_name == "담당자검토":
                cell_bg = review_colors.get(str(val), "E8F4FD")
            else:
                cell_bg = bg
            c = ws.cell(row=ri, column=ci, value=val)
            c.fill      = PatternFill("solid", start_color=cell_bg, end_color=cell_bg)
            c.font      = Font(name="맑은 고딕", size=9)
            c.alignment = Alignment(horizontal="left", vertical="center")
            c.border    = bdr

    buf = io.BytesIO()
    wb.save(buf)
    return drive_upload_bytes(
        drive, filename, buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ── JSON 드라이브 저장/로드 ───────────────────────────
def load_json_from_drive(drive, filename):
    content = drive_download_bytes(drive, filename)
    if content:
        try: return json.loads(content.decode('utf-8'))
        except: return {}
    return {}

def save_json_to_drive(drive, data, filename):
    content = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    return drive_upload_bytes(drive, filename, content, "application/json")

def load_text_from_drive(drive, filename):
    content = drive_download_bytes(drive, filename)
    return content.decode('utf-8').strip() if content else ""

# ── 키워드 로드 ───────────────────────────────────────
def load_keywords(drive):
    kw = load_json_from_drive(drive, KEYWORDS_FILE)
    return (
        kw.get("HIGH", DEFAULT_HIGH),
        kw.get("MID",  DEFAULT_MID),
    )

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
    deadline = notice.get('마감일', '')
    if deadline and deadline < datetime.today().strftime("%Y-%m-%d"): return None
    if str(row.get('수출실적','')) == '아니오' and '수출' in str(notice.get('분야','')): return None

    text = " ".join([str(notice.get(k,'')) for k in ['공고명','사업개요','해시태그','주관기관','지원대상']])
    matched_high = [kw for kw in HIGH if kw in text]
    matched_mid  = [kw for kw in MID  if kw in text]
    sys_score    = len(matched_high)*3 + len(matched_mid)*2

    raw_kw   = ",".join([str(row.get(k,'')) for k in ['기술키워드','제품분야','키워드보완']])
    co_kws   = [k.strip() for k in raw_kw.split(',') if k.strip() and k.strip()!='nan']
    matched_co = [kw for kw in co_kws if kw in text]
    co_score   = len(matched_co)*2

    country = str(row.get('수출국가',''))
    c_score = 2 if (country and country!='nan' and country in text) else 0

    total = sys_score + co_score + c_score
    if not (matched_high or matched_mid or matched_co): return None
    if matched_high or total >= 6: stars = "★★★"
    elif matched_mid or matched_co: stars = "★★"
    else: return None

    return {
        "기업명":         row['기업명'],
        "관련도":         stars,
        "점수":           total,
        "공고ID":         pid,
        "공고명":         notice.get('공고명',''),
        "주관기관":       notice.get('주관기관',''),
        "접수기간":       notice.get('접수기간',''),
        "마감일":         deadline,
        "사업개요":       str(notice.get('사업개요',''))[:150]+"...",
        "시스템매칭":     ", ".join(matched_high+matched_mid),
        "기업키워드매칭": ", ".join(matched_co),
        "공고링크":       notice.get('공고링크',''),
        "담당자검토":     "",
        "검토의견":       "",
    }

# ── CSS ──────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"] {background:#f8f9fa;}
.stButton button {border-radius:6px;}
</style>
""", unsafe_allow_html=True)

# ── 사이드바 ──────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📢 원스톱 스케일업")
    st.caption("공고 매칭 시스템")
    st.divider()
    page = st.radio("메뉴", [
        "🏠 대시보드", "👥 기업 관리", "🔄 공고 수집",
        "🔗 매칭 결과", "📤 발송 관리",
        "📋 발송 이력", "📊 성과 집계", "⚙️ 설정"
    ], label_visibility="collapsed")
    st.divider()
    test_mode = st.toggle("테스트 모드", value=True)
    st.warning("테스트 메일로 발송") if test_mode else st.success("실제 기업으로 발송")

TEST_RECIPIENTS = ["fbwlgns819@naver.com", "fbwlgns819@kip.re.kr"]

# ── 서비스 초기화 ─────────────────────────────────────
try:
    gmail, cal, drive = get_services()
except Exception as e:
    st.error(f"구글 인증 오류: {e}"); st.stop()


# ══════════════════════════════════════════════════════
# 대시보드
# ══════════════════════════════════════════════════════
if page == "🏠 대시보드":
    st.title("대시보드")
    with st.spinner("드라이브에서 데이터 로딩 중..."):
        df_c = load_excel_from_drive(drive, COMPANIES_FILE)
        df_n = load_excel_from_drive(drive, NOTICES_FILE)
        df_h = load_excel_from_drive(drive, HISTORY_FILE)

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("등록 기업",  f"{len(df_c)}개사")
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
    st.subheader("📁 드라이브 파일 현황")
    files_check = {
        COMPANIES_FILE: "기업 DB",
        NOTICES_FILE:   "공고 DB",
        HISTORY_FILE:   "발송 이력",
        CALID_FILE:     "캘린더 ID",
        KEYWORDS_FILE:  "키워드 설정",
    }
    fcols = st.columns(len(files_check))
    for col,(fname,label) in zip(fcols, files_check.items()):
        fid = drive_file_id(drive, fname)
        col.metric(label, "✅" if fid else "❌")


# ══════════════════════════════════════════════════════
# 기업 관리
# ══════════════════════════════════════════════════════
elif page == "👥 기업 관리":
    st.title("기업 관리")
    st.caption("기업 정보 조회·수정·수신거부 → 드라이브 자동 저장")

    with st.spinner("드라이브에서 기업 DB 로딩 중..."):
        df_c = load_excel_from_drive(drive, COMPANIES_FILE)

    if df_c.empty:
        st.warning("드라이브에 기업 DB가 없습니다.")
        st.info("WALLA xlsx 파일을 업로드하면 자동으로 변환·저장됩니다.")
        uploaded = st.file_uploader("WALLA xlsx 업로드", type=["xlsx"])
        if uploaded:
            col_map = {
                '기업명':       '(기본정보) 기업명을 입력해 주시기 바랍니다.',
                '이메일':       '(기본정보) 담당자 이메일을 입력해 주시기 바랍니다.',
                '관심사업분야': '(수요파악) 관심있는 정부 사업 분야를 선택하여 주시기 바랍니다.(최대 2개 선택 가능)',
                '기술키워드':   '(수요파악) 귀사 제품의 주요 기술/분야 키워드를 입력하여 주시기 바랍니다.',
                '제품분야':     '(기본정보) 귀사의 제품/기술 분야를 선택하여 주시기 바랍니다.(최대 3개선택 가능)',
                '수출실적':     '(기업현황) 최근 3년간 수출 실적 여부를 선택하여 주시기 바랍니다.',
                '수출국가':     '① 주요 수출 국가를 입력하여 주시기 바랍니다.',
            }
            raw    = pd.read_excel(uploaded)
            df_new = pd.DataFrame({k: raw[v] for k,v in col_map.items() if v in raw.columns}).fillna("")
            df_new['키워드보완'] = ''
            df_new['수신거부']   = ''
            df_new['메모']       = ''
            with st.spinner("드라이브에 저장 중..."):
                if save_excel_to_drive(drive, df_new, COMPANIES_FILE, "기업DB", "1F4E79"):
                    st.success(f"{len(df_new)}개사 저장 완료!"); st.rerun()
    else:
        c1,c2,c3 = st.columns(3)
        c1.metric("전체 기업", f"{len(df_c)}개사")
        c2.metric("수신거부",  f"{(df_c.get('수신거부',pd.Series())=='Y').sum()}개사")
        c3.metric("키워드 보완", f"{(df_c.get('키워드보완',pd.Series())!='').sum()}개사")
        st.divider()

        for col in ['키워드보완','수신거부','메모']:
            if col not in df_c.columns: df_c[col] = ''

        search = st.text_input("🔍 기업명 검색")
        df_show = df_c[df_c['기업명'].str.contains(search)] if search else df_c

        for idx, row in df_show.iterrows():
            unsub = row.get('수신거부','') == 'Y'
            icon  = "🚫" if unsub else "🏢"
            with st.expander(f"{icon} **{row['기업명']}**  |  {row.get('관심사업분야','')}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**이메일:** {row.get('이메일','')}")
                    st.markdown(f"**관심분야:** {row.get('관심사업분야','')}")
                    st.markdown(f"**수출:** {row.get('수출실적','')} / {row.get('수출국가','')}")
                with col2:
                    st.markdown(f"**제품분야:** {row.get('제품분야','')}")
                    st.markdown(f"**기술키워드:** {row.get('기술키워드','')}")

                extra_kw = st.text_input("키워드 보완", value=row.get('키워드보완',''),
                                          key=f"kw_{idx}", placeholder="예: 스마트팜, IoT")
                unsub_cb = st.checkbox("수신거부", value=unsub, key=f"unsub_{idx}")
                memo     = st.text_input("메모", value=row.get('메모',''), key=f"memo_{idx}")

                if st.button("💾 저장", key=f"save_{idx}"):
                    df_c.at[idx,'키워드보완'] = extra_kw
                    df_c.at[idx,'수신거부']   = 'Y' if unsub_cb else ''
                    df_c.at[idx,'메모']       = memo
                    with st.spinner("드라이브 저장 중..."):
                        if save_excel_to_drive(drive, df_c, COMPANIES_FILE, "기업DB", "1F4E79"):
                            st.success(f"{row['기업명']} 저장 완료!")


# ══════════════════════════════════════════════════════
# 공고 수집
# ══════════════════════════════════════════════════════
elif page == "🔄 공고 수집":
    st.title("공고 수집")
    st.caption("bizinfo API 수집 → 드라이브 notices_db.xlsx 자동 저장")

    with st.spinner("드라이브에서 공고 DB 로딩 중..."):
        df_n = load_excel_from_drive(drive, NOTICES_FILE)

    if not df_n.empty:
        c1,c2,c3 = st.columns(3)
        c1.metric("현재 DB", f"{len(df_n):,}건")
        c2.metric("마지막 수집일", df_n['수집일'].max() if '수집일' in df_n.columns else "—")
        c3.metric("마감일 파싱 성공",
                  f"{(df_n['마감일']!='').sum()}건" if '마감일' in df_n.columns else "—")

    st.divider()
    if st.button("🔄 지금 수집 실행", type="primary"):
        REALM_CODES = ["01","02","03","04","05","06","07","09"]
        all_items, seen = [], set()
        prog = st.progress(0); log_area = st.empty(); logs = []

        for idx, code in enumerate(REALM_CODES):
            params = {"crtfcKey":API_KEY,"dataType":"json","searchCnt":"0","searchLclasId":code}
            try:
                items = requests.get(BASE_URL, params=params, timeout=30).json().get('jsonArray',[])
                for item in items:
                    pid = item.get('pblancId','')
                    if pid and pid not in seen:
                        seen.add(pid); all_items.append(item)
                logs.append(f"✅ 분야코드 {code}: {len(items)}건")
            except Exception as e:
                logs.append(f"❌ 분야코드 {code}: {e}")
            prog.progress((idx+1)/len(REALM_CODES))
            log_area.code("\n".join(logs))

        def to_row(item):
            def pdl(s):
                try: return datetime.strptime(re.sub(r'\.', '-', s.split('~')[-1].strip()), "%Y-%m-%d").strftime("%Y-%m-%d")
                except: return ""
            return {"pblancId":item.get('pblancId',''),"공고명":item.get('pblancNm',''),
                    "주관기관":item.get('jrsdInsttNm',''),"분야":item.get('pldirSportRealmLclasCodeNm',''),
                    "세부분야":item.get('pldirSportRealmMlsfcCodeNm',''),
                    "접수기간":item.get('reqstBeginEndDe',''),"마감일":pdl(item.get('reqstBeginEndDe','')),
                    "지원대상":item.get('trgetNm',''),
                    "사업개요":strip_html(item.get('bsnsSumryCn',''))[:500],
                    "해시태그":item.get('hashtags',''),"공고링크":item.get('pblancUrl',''),
                    "수정일":item.get('updtPnttm',''),"수집일":datetime.today().strftime("%Y-%m-%d")}

        ex_map = {r['pblancId']:r.get('수정일','') for _,r in df_n.iterrows()} if not df_n.empty else {}
        new_rows, upd_rows = [], []
        for item in all_items:
            pid = item.get('pblancId','')
            if not pid: continue
            row = to_row(item)
            if pid not in ex_map: new_rows.append(row)
            elif ex_map[pid] != item.get('updtPnttm',''): upd_rows.append(row)

        if not df_n.empty:
            upd_ids  = {r['pblancId'] for r in upd_rows}
            df_final = pd.concat([df_n[~df_n['pblancId'].isin(upd_ids)],
                                   pd.DataFrame(new_rows+upd_rows)], ignore_index=True)
        else:
            df_final = pd.DataFrame(new_rows)

        with st.spinner("드라이브에 저장 중..."):
            save_excel_to_drive(drive, df_final, NOTICES_FILE, "공고DB", "00897B")

        prog.progress(1.0)
        st.success(f"수집 완료! 총 {len(df_final):,}건 (신규 {len(new_rows)} / 업데이트 {len(upd_rows)}) → 드라이브 저장")
        st.rerun()

    if not df_n.empty:
        st.divider()
        st.subheader("공고 DB 미리보기")
        cols = [c for c in ["공고명","주관기관","분야","접수기간","마감일"] if c in df_n.columns]
        st.dataframe(df_n[cols].head(20), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════
# 매칭 결과
# ══════════════════════════════════════════════════════
elif page == "🔗 매칭 결과":
    st.title("매칭 결과")
    tab1, tab2 = st.tabs(["매칭 실행", "검토 & 승인"])

    with tab1:
        st.subheader("매칭 실행")
        max_per = st.slider("기업당 최대 추천 건수", 3, 10, 5)

        if st.button("🔗 매칭 실행", type="primary"):
            with st.spinner("드라이브에서 데이터 로딩 중..."):
                df_c  = load_excel_from_drive(drive, COMPANIES_FILE)
                df_n  = load_excel_from_drive(drive, NOTICES_FILE)
                df_h  = load_excel_from_drive(drive, HISTORY_FILE)
                HIGH, MID = load_keywords(drive)

            if df_n.empty: st.error("notices_db 없음 → 공고 수집 먼저"); st.stop()
            if df_c.empty: st.error("기업 DB 없음 → 기업 관리에서 업로드"); st.stop()

            if '수신거부' in df_c.columns:
                df_c = df_c[df_c['수신거부'] != 'Y']

            already_sent = set(zip(df_h['기업명'], df_h['pblancId'])) if not df_h.empty else set()
            all_results  = []
            prog = st.progress(0)

            for idx,(_, row) in enumerate(df_c.iterrows()):
                interest    = row.get('관심사업분야','')
                realm_names = [k for k,v in REALM_CODE.items() if v in [rv for rk,rv in REALM_CODE.items() if rk in interest]]
                filtered    = df_n[df_n['분야'].isin(realm_names)] if '분야' in df_n.columns else df_n
                scored      = [r for _,n in filtered.iterrows() if (r:=score_notice(n.to_dict(), row, already_sent, HIGH, MID))]
                scored.sort(key=lambda x:-x['점수'])
                all_results.extend(scored[:max_per])
                prog.progress((idx+1)/len(df_c))

            st.session_state['match_results'] = all_results
            st.success(f"매칭 완료! 총 {len(all_results)}건 → '검토 & 승인' 탭으로 이동하세요.")

    with tab2:
        st.subheader("담당자 검토")
        results = st.session_state.get('match_results', [])

        if not results:
            st.info("매칭 실행 탭에서 먼저 실행하세요.")
        else:
            df_show = pd.DataFrame(results)
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                filter_stars = st.multiselect("관련도", ["★★★","★★"], default=["★★★","★★"])
            with col_f2:
                filter_co = st.selectbox("기업", ["전체"]+sorted(df_show['기업명'].unique().tolist()))

            filtered = df_show[df_show['관련도'].isin(filter_stars)]
            if filter_co != "전체":
                filtered = filtered[filtered['기업명']==filter_co]

            if 'review_state' not in st.session_state:
                st.session_state['review_state'] = {}

            ap = sum(1 for v in st.session_state['review_state'].values() if v=="○")
            rj = sum(1 for v in st.session_state['review_state'].values() if v=="✕")
            st.caption(f"총 {len(filtered)}건  |  ✅ 승인 {ap}건  |  ❌ 제외 {rj}건")
            st.divider()

            for i,(idx,row) in enumerate(filtered.iterrows()):
                key     = f"{row['기업명']}_{row.get('공고ID','')}"
                current = st.session_state['review_state'].get(key,"")
                icon    = "🟡" if not current else ("✅" if current=="○" else "❌")

                with st.expander(f"{icon} **{row['기업명']}**  |  {row.get('관련도','')}  |  {row.get('공고명','')[:35]}"):
                    c1,c2 = st.columns([3,1])
                    with c1:
                        st.markdown(f"**주관기관:** {row.get('주관기관','')}  |  **마감:** {row.get('마감일','')}")
                        st.markdown(f"**사업개요:** {row.get('사업개요','')}")
                        st.markdown(f"**매칭키워드:** {row.get('시스템매칭','')} / {row.get('기업키워드매칭','')}")
                        if row.get('공고링크',''):
                            st.markdown(f"[🔗 공고 원문 보기]({row.get('공고링크','')})")
                    with c2:
                        if st.button("○ 승인", key=f"o_{key}_{i}", type="primary"):
                            st.session_state['review_state'][key] = "○"; st.rerun()
                        if st.button("✕ 제외", key=f"x_{key}_{i}"):
                            st.session_state['review_state'][key] = "✕"; st.rerun()

            st.divider()
            c1,c2 = st.columns(2)
            with c1:
                if st.button("✅ 검토 완료 저장", type="primary"):
                    for r in results:
                        key = f"{r['기업명']}_{r.get('공고ID','')}"
                        r['담당자검토'] = st.session_state['review_state'].get(key,"")
                    st.session_state['match_results'] = results
                    st.success(f"저장됨. 승인 {ap}건 → '발송 관리' 메뉴로 이동하세요.")
            with c2:
                # 매칭결과 엑셀 드라이브 저장
                if st.button("📥 매칭결과 엑셀 저장"):
                    df_save = pd.DataFrame(results)
                    fname   = f"매칭결과_{datetime.today().strftime('%Y%m%d')}.xlsx"
                    with st.spinner("드라이브 저장 중..."):
                        save_excel_to_drive(drive, df_save, fname, "매칭결과", "C55A11", star_col="관련도")
                    st.success(f"드라이브에 {fname} 저장됨!")


# ══════════════════════════════════════════════════════
# 발송 관리
# ══════════════════════════════════════════════════════
elif page == "📤 발송 관리":
    st.title("발송 관리")
    results  = st.session_state.get('match_results', [])
    approved = [r for r in results if r.get('담당자검토')=='○']

    if not approved:
        st.warning("승인된 공고가 없습니다. '매칭 결과'에서 검토를 완료하세요.")
    else:
        companies = list(set(r['기업명'] for r in approved))
        c1,c2,c3  = st.columns(3)
        c1.metric("승인 건수", f"{len(approved)}건")
        c2.metric("대상 기업", f"{len(companies)}개사")
        c3.metric("발송 모드", "테스트" if test_mode else "실제")

        if test_mode: st.warning("⚠️ 테스트 모드: 본인 메일로만 발송됩니다.")
        else:         st.success("✅ 실제 모드: 기업 담당자 이메일로 발송됩니다.")

        st.divider()
        st.subheader("발송 미리보기")
        preview_co      = st.selectbox("기업 선택", companies)
        preview_notices = [r for r in approved if r['기업명']==preview_co]

        with st.expander(f"📧 {preview_co} 메일 미리보기"):
            for i,n in enumerate(preview_notices,1):
                st.markdown(f"**{i}. {n.get('관련도','')} [{n.get('공고명','')}]({n.get('공고링크','#')})**")
                st.markdown(f"주관: {n.get('주관기관','')}  |  기간: {n.get('접수기간','')}")
                st.caption(n.get('사업개요','')); st.divider()

        st.divider()
        if st.button("📤 발송 실행", type="primary"):
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            import base64

            cal_id        = load_text_from_drive(drive, CALID_FILE)
            ind_cals      = load_json_from_drive(drive, INDCAL_FILE)
            CALENDAR_LINK = f"https://calendar.google.com/calendar?cid={cal_id}" if cal_id else ""
            df_c_cur      = load_excel_from_drive(drive, COMPANIES_FILE)

            history_records = []
            prog = st.progress(0); log = st.empty(); logs = []

            grouped = {}
            for r in approved: grouped.setdefault(r['기업명'],[]).append(r)

            for idx,(company,notices) in enumerate(grouped.items()):
                rows_html=""
                for i,n in enumerate(notices,1):
                    rows_html+=f"""<tr>
                      <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;color:#1F4E79">{i}. {n.get('관련도','')}</td>
                      <td style="padding:8px;border-bottom:1px solid #eee">
                        <a href="{n.get('공고링크','#')}" style="color:#2E75B6;text-decoration:none">{n.get('공고명','')}</a>
                      </td>
                      <td style="padding:8px;border-bottom:1px solid #eee;color:#666">{n.get('주관기관','')}</td>
                      <td style="padding:8px;border-bottom:1px solid #eee;color:#666">{n.get('접수기간','')}</td>
                    </tr>"""

                ind_link = ""
                if company in ind_cals and ind_cals[company].get('calendar_id'):
                    ind_link = f"""<div style="margin-top:8px">
                      <a href="https://calendar.google.com/calendar?cid={ind_cals[company]['calendar_id']}"
                         style="color:#2E75B6;font-size:13px">📅 {company} 전용 캘린더 구독</a></div>"""

                cal_sec = f"""<div style="background:#EBF3FB;border-radius:6px;padding:14px;margin-top:16px">
                  <p style="margin:0 0 8px;color:#1F4E79;font-weight:bold;font-size:13px">📅 공고 마감일 캘린더</p>
                  {"<a href='"+CALENDAR_LINK+"' style='background:#1F4E79;color:#fff;padding:8px 16px;border-radius:4px;text-decoration:none;font-size:13px;display:inline-block'>공통 캘린더 구독</a>" if CALENDAR_LINK else ""}
                  {ind_link}
                </div>""" if (CALENDAR_LINK or ind_link) else ""

                html=f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;background:#f5f5f5">
                <table width="600" align="center" style="background:#fff;border-radius:8px;overflow:hidden;margin:20px auto">
                  <tr><td style="background:#1F4E79;padding:24px 32px">
                    <p style="margin:0;color:#fff;font-size:12px;opacity:.8">혁신제품지원센터</p>
                    <h2 style="margin:4px 0 0;color:#fff;font-size:18px">원스톱 스케일업 프로그램</h2>
                  </td></tr>
                  <tr><td style="padding:24px 32px">
                    <p>안녕하세요, <strong>{company}</strong> 담당자님.</p>
                    <p>귀사 관심 분야 관련 지원사업 공고 <strong>{len(notices)}건</strong>을 안내드립니다.</p>
                    <table width="100%" style="border:1px solid #e0e0e0;border-radius:6px;overflow:hidden;margin-top:12px">
                      <tr style="background:#2E75B6">
                        <td style="padding:8px;color:#fff;font-size:12px;font-weight:bold">순위</td>
                        <td style="padding:8px;color:#fff;font-size:12px;font-weight:bold">공고명</td>
                        <td style="padding:8px;color:#fff;font-size:12px;font-weight:bold">주관기관</td>
                        <td style="padding:8px;color:#fff;font-size:12px;font-weight:bold">접수기간</td>
                      </tr>{rows_html}
                    </table>{cal_sec}
                  </td></tr>
                  <tr><td style="background:#f9f9f9;padding:14px 32px;font-size:12px;color:#888;border-top:1px solid #eee">
                    혁신제품지원센터 원스톱 스케일업 운영팀 | onestop.kipcc@gmail.com
                  </td></tr>
                </table></body></html>"""

                co_email = ""
                if not df_c_cur.empty and '이메일' in df_c_cur.columns:
                    m = df_c_cur[df_c_cur['기업명']==company]
                    if not m.empty: co_email = m.iloc[0].get('이메일','')

                recipients = TEST_RECIPIENTS if test_mode else ([co_email] if co_email else [])
                for to in recipients:
                    msg = MIMEMultipart('alternative')
                    msg['From']    = "onestop.kipcc@gmail.com"
                    msg['To']      = to
                    msg['Subject'] = f"[원스톱 스케일업] 맞춤 지원공고 {len(notices)}건 안내 — {company}"
                    msg.attach(MIMEText(html,'html','utf-8'))
                    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
                    gmail.users().messages().send(userId='me',body={'raw':raw}).execute()

                # 캘린더 등록
                for n in notices:
                    dl  = parse_deadline(n.get('접수기간',''))
                    pid = n.get('공고ID','')
                    if not dl or not pid: continue
                    desc  = f"주관기관: {n.get('주관기관','')}\n공고링크: {n.get('공고링크','')}\n안내기업: {company}"
                    cids  = [cal_id] if cal_id else []
                    if company in ind_cals and ind_cals[company].get('calendar_id'):
                        cids.append(ind_cals[company]['calendar_id'])
                    for cid in cids:
                        try:
                            ex = cal.events().list(calendarId=cid, privateExtendedProperty=f"pblancId={pid}").execute()
                            if ex.get('items'): continue
                        except: pass
                        for days,label in [(0,"마감"),(7,"D-7"),(3,"D-3")]:
                            d = (dl-timedelta(days=days)).strftime('%Y-%m-%d')
                            cal.events().insert(calendarId=cid, body={
                                'summary':f"[{label}] {n.get('공고명','')}",
                                'description':desc,
                                'start':{'date':d,'timeZone':'Asia/Seoul'},
                                'end':  {'date':d,'timeZone':'Asia/Seoul'},
                                'extendedProperties':{'private':{'pblancId':pid}},
                            }).execute()

                for n in notices:
                    history_records.append({
                        "기업명":company,"pblancId":n.get('공고ID',''),
                        "공고명":n.get('공고명',''),"발송일":datetime.today().strftime("%Y-%m-%d"),
                        "매칭점수":n.get('점수',''),"담당자검토":"○",
                        "검토의견":n.get('검토의견',''),"신청여부":"","선정결과":"",
                    })

                logs.append(f"✅ {company} — {len(notices)}건 발송 완료")
                log.code("\n".join(logs))
                prog.progress((idx+1)/len(grouped))

            with st.spinner("발송 이력 드라이브 저장 중..."):
                df_h   = load_excel_from_drive(drive, HISTORY_FILE)
                df_new = pd.DataFrame(history_records)
                df_fin = pd.concat([df_h,df_new],ignore_index=True) if not df_h.empty else df_new
                save_excel_to_drive(drive, df_fin, HISTORY_FILE, "발송이력", "375623")

            prog.progress(1.0)
            st.success(f"발송 완료! {len(history_records)}건 → 드라이브 저장됨")
            st.session_state['match_results'] = []
            st.session_state['review_state']  = {}


# ══════════════════════════════════════════════════════
# 발송 이력
# ══════════════════════════════════════════════════════
elif page == "📋 발송 이력":
    st.title("발송 이력")
    with st.spinner("드라이브에서 로딩 중..."):
        df_h = load_excel_from_drive(drive, HISTORY_FILE)

    if df_h.empty:
        st.info("발송 이력이 없습니다.")
    else:
        c1,c2,c3 = st.columns(3)
        c1.metric("총 발송", len(df_h))
        c2.metric("신청 건", (df_h['신청여부']=='Y').sum() if '신청여부' in df_h.columns else 0)
        c3.metric("선정 건", (df_h['선정결과']=='선정').sum() if '선정결과' in df_h.columns else 0)

        st.divider()
        edited = st.data_editor(
            df_h, use_container_width=True, hide_index=True,
            column_config={
                "신청여부": st.column_config.SelectboxColumn("신청여부", options=["","Y","N"]),
                "선정결과": st.column_config.SelectboxColumn("선정결과", options=["","선정","미선정","대기"]),
            }
        )
        if st.button("💾 드라이브 저장"):
            with st.spinner("저장 중..."):
                save_excel_to_drive(drive, edited, HISTORY_FILE, "발송이력", "375623")
            st.success("저장 완료!")

        st.divider()
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as w:
            df_h.to_excel(w, index=False)
        st.download_button("📥 엑셀 다운로드", buf.getvalue(), HISTORY_FILE,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ══════════════════════════════════════════════════════
# 성과 집계
# ══════════════════════════════════════════════════════
elif page == "📊 성과 집계":
    st.title("성과 집계")
    with st.spinner("드라이브에서 로딩 중..."):
        df_h = load_excel_from_drive(drive, HISTORY_FILE)

    if df_h.empty:
        st.info("발송 이력이 없습니다.")
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
                신청건수=('신청여부', lambda x:(x=='Y').sum()),
                선정건수=('선정결과', lambda x:(x=='선정').sum()),
            ).reset_index()
            st.dataframe(summary, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════════
elif page == "⚙️ 설정":
    st.title("설정")

    # 인증 상태
    st.subheader("🔐 인증 상태")
    if 'google' in st.secrets:
        st.success("✅ Streamlit Secrets 인증 설정됨")
    elif os.path.exists('token.json'):
        st.success("✅ 로컬 token.json 인증 설정됨")
    else:
        st.error("❌ 인증 파일 없음")

    st.divider()

    # 드라이브 연동
    st.subheader("📁 드라이브 연동 현황")
    st.code(f"폴더 ID: {DRIVE_FOLDER_ID}")
    st.markdown(f"[📂 드라이브 폴더 열기](https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID})")
    files_check = {
        COMPANIES_FILE: "기업 DB",
        NOTICES_FILE:   "공고 DB",
        HISTORY_FILE:   "발송 이력",
        CALID_FILE:     "공통 캘린더 ID",
        KEYWORDS_FILE:  "키워드 설정",
        CATCAL_FILE:    "분야별 캘린더",
        INDCAL_FILE:    "기업별 캘린더",
    }
    for fname,label in files_check.items():
        fid = drive_file_id(drive, fname)
        st.write(f"{'✅' if fid else '❌'} {label} ({fname})")

    st.divider()

    # 키워드 설정 (드라이브 저장)
    st.subheader("🔑 키워드 설정")
    st.caption("수정 후 저장하면 다음 매칭 실행부터 바로 반영됩니다.")

    with st.spinner("키워드 로딩 중..."):
        HIGH, MID = load_keywords(drive)

    high_input = st.text_area(
        "★★★ 직접 연계 키워드 (쉼표 구분)",
        value=", ".join(HIGH), height=80
    )
    mid_input = st.text_area(
        "★★ 간접 연계 키워드 (쉼표 구분)",
        value=", ".join(MID), height=80
    )

    if st.button("💾 키워드 저장 → 드라이브", type="primary"):
        new_high = [k.strip() for k in high_input.split(',') if k.strip()]
        new_mid  = [k.strip() for k in mid_input.split(',')  if k.strip()]
        kw_data  = {"HIGH": new_high, "MID": new_mid}
        with st.spinner("드라이브에 저장 중..."):
            if save_json_to_drive(drive, kw_data, KEYWORDS_FILE):
                st.success(f"키워드 저장 완료! ★★★ {len(new_high)}개 / ★★ {len(new_mid)}개")
            else:
                st.error("저장 실패")
