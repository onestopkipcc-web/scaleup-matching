"""
원스톱 스케일업 — 공고 매칭 시스템
구글 드라이브 연동 + 엑셀 저장 + 키워드 설정 + 페이지 안내
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
DRIVE_FOLDER_ID = "1iWGYjaoslqST45ggDlg-IPMLaUHCYmV_"
API_KEY         = "Nt604D"
BASE_URL        = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"

# 모든 파일 xlsx
COMPANIES_FILE  = "companies_db.xlsx"
NOTICES_FILE    = "notices_db.xlsx"
HISTORY_FILE    = "send_history.xlsx"
KEYWORDS_FILE   = "keywords.json"
CALID_FILE      = "calendar_id.txt"
CATCAL_FILE     = "category_calendars.json"
INDCAL_FILE     = "individual_calendars.json"

DEFAULT_HIGH = ["혁신제품","혁신조달","G-PASS","혁신기업","해외조달","공공구매","조달청"]
DEFAULT_MID  = ["해외판로","수출바우처","수출지원","해외진출","글로벌","스케일업","판로개척","해외마케팅"]

REALM_CODE = {
    "금융":"01","기술개발":"02","인력":"03","수출":"04",
    "내수":"05","창업":"06","경영":"07","기타":"09",
}

TEST_RECIPIENTS = ["fbwlgns819@naver.com","fbwlgns819@kip.re.kr"]

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
        creds = Credentials.from_authorized_user_info(json.loads(st.secrets['google']['token']), SCOPES)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        st.error("인증 파일이 없습니다."); st.stop()
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return (build('gmail','v1',credentials=creds),
            build('calendar','v3',credentials=creds),
            build('drive','v3',credentials=creds))

# ── 드라이브 유틸 ─────────────────────────────────────
def drive_file_id(drive, filename):
    try:
        res = drive.files().list(
            q=f"name='{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed=false",
            fields="files(id,name)", orderBy="modifiedTime desc"
        ).execute()
        files = res.get('files',[])
        return files[0]['id'] if files else None
    except: return None

def drive_download(drive, filename):
    try:
        fid = drive_file_id(drive, filename)
        return drive.files().get_media(fileId=fid).execute() if fid else None
    except: return None

def drive_upload(drive, filename, content_bytes, mime):
    from googleapiclient.http import MediaIoBaseUpload
    try:
        fid   = drive_file_id(drive, filename)
        media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype=mime)
        if fid: drive.files().update(fileId=fid, media_body=media).execute()
        else:   drive.files().create(body={'name':filename,'parents':[DRIVE_FOLDER_ID]}, media_body=media).execute()
        return True
    except Exception as e:
        st.warning(f"드라이브 저장 실패 ({filename}): {e}"); return False

def load_excel(drive, filename):
    content = drive_download(drive, filename)
    if content:
        try: return pd.read_excel(io.BytesIO(content), dtype=str).fillna("")
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
    for ci,col in enumerate(df.columns,1):
        w = max(len(str(col))*2, 14)
        ws.column_dimensions[get_column_letter(ci)].width = w
        c = ws.cell(row=1,column=ci,value=col)
        c.fill=PatternFill("solid",start_color=hcolor,end_color=hcolor)
        c.font=Font(name="맑은 고딕",bold=True,color="FFFFFF",size=10)
        c.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
        c.border=bdr
    ws.row_dimensions[1].height=24
    star_colors={"★★★":"FFF2CC","★★":"E2EFDA"}
    rev_colors ={"○":"D5E8D4","✕":"FFE6E6"}
    for ri,row in enumerate(df.itertuples(index=False),2):
        vals=list(row); bg="FFFFFF"
        if star_col and star_col in df.columns:
            bg=star_colors.get(vals[df.columns.tolist().index(star_col)],"FFFFFF")
        ws.row_dimensions[ri].height=18
        for ci,val in enumerate(vals,1):
            cname=df.columns[ci-1]
            cell_bg=rev_colors.get(str(val),bg) if cname=="담당자검토" else bg
            c=ws.cell(row=ri,column=ci,value=val)
            c.fill=PatternFill("solid",start_color=cell_bg,end_color=cell_bg)
            c.font=Font(name="맑은 고딕",size=9)
            c.alignment=Alignment(horizontal="left",vertical="center")
            c.border=bdr
    buf=io.BytesIO(); wb.save(buf)
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
        json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'), "application/json")

def load_text(drive, filename):
    content = drive_download(drive, filename)
    return content.decode('utf-8').strip() if content else ""

def load_keywords(drive):
    kw = load_json(drive, KEYWORDS_FILE)
    return kw.get("HIGH", DEFAULT_HIGH), kw.get("MID", DEFAULT_MID)

# ── 매칭 스코어링 ─────────────────────────────────────
def strip_html(html):
    return re.sub(r'<[^>]+>', ' ', html or '').strip()

def parse_deadline(s):
    try:
        end = s.split('~')[-1].strip()
        return datetime.strptime(re.sub(r'\.', '-', end), "%Y-%m-%d")
    except: return None

def score_notice(notice, row, already_sent, HIGH, MID):
    pid = notice.get('pblancId','')
    if (row['기업명'], pid) in already_sent: return None
    dl = notice.get('마감일','')
    if dl and dl < datetime.today().strftime("%Y-%m-%d"): return None
    if str(row.get('수출실적',''))=='아니오' and '수출' in str(notice.get('분야','')): return None
    text=" ".join([str(notice.get(k,'')) for k in ['공고명','사업개요','해시태그','주관기관','지원대상']])
    mh=[kw for kw in HIGH if kw in text]
    mm=[kw for kw in MID  if kw in text]
    ss=len(mh)*3+len(mm)*2
    raw=",".join([str(row.get(k,'')) for k in ['기술키워드','제품분야','키워드보완']])
    co=[kw for kw in [k.strip() for k in raw.split(',') if k.strip() and k.strip()!='nan'] if kw in text]
    cs=len(co)*2
    cn=str(row.get('수출국가',''))
    xs=2 if (cn and cn!='nan' and cn in text) else 0
    total=ss+cs+xs
    if not(mh or mm or co): return None
    stars="★★★" if (mh or total>=6) else ("★★" if (mm or co) else None)
    if not stars: return None
    return {"기업명":row['기업명'],"관련도":stars,"점수":total,
            "공고ID":pid,"공고명":notice.get('공고명',''),
            "주관기관":notice.get('주관기관',''),"접수기간":notice.get('접수기간',''),
            "마감일":dl,"사업개요":str(notice.get('사업개요',''))[:150]+"...",
            "시스템매칭":", ".join(mh+mm),"기업키워드매칭":", ".join(co),
            "공고링크":notice.get('공고링크',''),"담당자검토":"","검토의견":""}

# ── 안내 박스 컴포넌트 ────────────────────────────────
def info_box(title, desc, how_to_modify=None):
    """페이지 상단 안내 박스"""
    with st.expander(f"ℹ️ {title} — 클릭해서 안내 보기", expanded=False):
        st.markdown(desc)
        if how_to_modify:
            st.divider()
            st.markdown("**✏️ 수정하려면**")
            st.markdown(how_to_modify)

# ── CSS ──────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"]{background:#f8f9fa;}
.stButton button{border-radius:6px;}
</style>
""", unsafe_allow_html=True)

# ── 사이드바 ──────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📢 원스톱 스케일업")
    st.caption("공고 매칭 시스템")
    st.divider()
    page = st.radio("메뉴",[
        "🏠 대시보드","👥 기업 관리","🔄 공고 수집",
        "🔗 매칭 결과","📤 발송 관리",
        "📋 발송 이력","📊 성과 집계","⚙️ 설정"
    ], label_visibility="collapsed")
    st.divider()
    test_mode = st.toggle("테스트 모드", value=True)
    st.warning("테스트 메일로 발송") if test_mode else st.success("실제 기업으로 발송")

try:
    gmail, cal, drive = get_services()
except Exception as e:
    st.error(f"구글 인증 오류: {e}"); st.stop()


# ══════════════════════════════════════════════════════
# 🏠 대시보드
# ══════════════════════════════════════════════════════
if page == "🏠 대시보드":
    st.title("대시보드")

    info_box(
        "대시보드란?",
        """
전체 시스템 현황을 한눈에 확인하는 화면입니다.

**운영 사이클 (격주 기준)**
1. 🔄 **공고 수집** (월요일) — bizinfo API에서 전체 공고 자동 수집
2. 🔗 **매칭 실행** (화요일) — 기업별 맞춤 공고 자동 추출
3. 👤 **담당자 검토** (화~수) — ○/✕ 클릭으로 최종 발송 여부 결정
4. 📤 **발송** (목요일) — 승인 건만 메일 + 캘린더 자동 처리
5. 📊 **성과 집계** (분기) — 신청·선정 결과 입력 및 보고

**드라이브 연동**
모든 데이터는 구글 드라이브 폴더에 자동 저장되어 팀원 모두가 공유합니다.
        """,
        "운영 주기를 바꾸고 싶으면 팀 내 합의 후 진행하세요. 코드 수정 없이 운영됩니다."
    )

    with st.spinner("드라이브에서 데이터 로딩 중..."):
        df_c = load_excel(drive, COMPANIES_FILE)
        df_n = load_excel(drive, NOTICES_FILE)
        df_h = load_excel(drive, HISTORY_FILE)

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
    fcols = st.columns(5)
    for col,(fname,label) in zip(fcols,{
        COMPANIES_FILE:"기업 DB", NOTICES_FILE:"공고 DB",
        HISTORY_FILE:"발송 이력", CALID_FILE:"캘린더 ID", KEYWORDS_FILE:"키워드"
    }.items()):
        fid = drive_file_id(drive, fname)
        col.metric(label, "✅" if fid else "❌")


# ══════════════════════════════════════════════════════
# 👥 기업 관리
# ══════════════════════════════════════════════════════
elif page == "👥 기업 관리":
    st.title("기업 관리")

    info_box(
        "기업 관리란?",
        """
WALLA 신청서 데이터를 기반으로 기업 DB를 관리하는 화면입니다.

**주요 기능**
- **WALLA xlsx 업로드** — 신청서를 업로드하면 자동으로 기업 DB로 변환됩니다
- **키워드 보완** — 기업이 입력한 키워드가 짧거나 부족할 때 담당자가 직접 추가
- **수신거부 처리** — 체크하면 이후 매칭·발송에서 자동 제외됩니다
- **메모** — 기업별 담당자 메모 기록

**매칭에 영향을 주는 필드**
`기술키워드` + `제품분야` + `키워드보완` 세 개를 합산하여 공고와 매칭합니다.
키워드가 짧은 기업은 **키워드 보완**에 추가 단어를 넣어주세요.
        """,
        """
- **키워드 추가** → 기업 항목 열기 → '키워드 보완' 입력 → 저장
- **수신거부** → 해당 기업 체크박스 체크 → 저장
- **WALLA 신청 추가** → 새 xlsx 업로드 (기존 DB에 추가됩니다)
        """
    )

    with st.spinner("드라이브에서 기업 DB 로딩 중..."):
        df_c = load_excel(drive, COMPANIES_FILE)

    if df_c.empty:
        st.warning("드라이브에 기업 DB가 없습니다.")
        st.info("WALLA xlsx 파일을 업로드하면 자동으로 변환·저장됩니다.")
        uploaded = st.file_uploader("WALLA xlsx 업로드", type=["xlsx"])
        if uploaded:
            col_map={
                '기업명':       '(기본정보) 기업명을 입력해 주시기 바랍니다.',
                '이메일':       '(기본정보) 담당자 이메일을 입력해 주시기 바랍니다.',
                '관심사업분야': '(수요파악) 관심있는 정부 사업 분야를 선택하여 주시기 바랍니다.(최대 2개 선택 가능)',
                '기술키워드':   '(수요파악) 귀사 제품의 주요 기술/분야 키워드를 입력하여 주시기 바랍니다.',
                '제품분야':     '(기본정보) 귀사의 제품/기술 분야를 선택하여 주시기 바랍니다.(최대 3개선택 가능)',
                '수출실적':     '(기업현황) 최근 3년간 수출 실적 여부를 선택하여 주시기 바랍니다.',
                '수출국가':     '① 주요 수출 국가를 입력하여 주시기 바랍니다.',
            }
            raw=pd.read_excel(uploaded)
            df_new=pd.DataFrame({k:raw[v] for k,v in col_map.items() if v in raw.columns}).fillna("")
            df_new['키워드보완']=''; df_new['수신거부']=''; df_new['메모']=''
            with st.spinner("드라이브에 저장 중..."):
                if save_excel(drive, df_new, COMPANIES_FILE, "기업DB", "1F4E79"):
                    st.success(f"{len(df_new)}개사 저장 완료!"); st.rerun()
    else:
        for col in ['키워드보완','수신거부','메모']:
            if col not in df_c.columns: df_c[col]=''

        c1,c2,c3=st.columns(3)
        c1.metric("전체 기업",   f"{len(df_c)}개사")
        c2.metric("수신거부",    f"{(df_c['수신거부']=='Y').sum()}개사")
        c3.metric("키워드 보완", f"{(df_c['키워드보완']!='').sum()}개사")
        st.divider()

        search=st.text_input("🔍 기업명 검색")
        df_show=df_c[df_c['기업명'].str.contains(search)] if search else df_c

        for idx,row in df_show.iterrows():
            unsub=row.get('수신거부','')=='Y'
            icon="🚫" if unsub else "🏢"
            with st.expander(f"{icon} **{row['기업명']}**  |  {row.get('관심사업분야','')}"):
                c1,c2=st.columns(2)
                with c1:
                    st.markdown(f"**이메일:** {row.get('이메일','')}")
                    st.markdown(f"**관심분야:** {row.get('관심사업분야','')}")
                    st.markdown(f"**수출:** {row.get('수출실적','')} / {row.get('수출국가','')}")
                with c2:
                    st.markdown(f"**제품분야:** {row.get('제품분야','')}")
                    st.markdown(f"**기술키워드:** {row.get('기술키워드','')}")
                extra_kw=st.text_input("키워드 보완",value=row.get('키워드보완',''),
                    key=f"kw_{idx}",placeholder="예: 스마트팜, IoT, 농업기술")
                unsub_cb=st.checkbox("수신거부",value=unsub,key=f"unsub_{idx}")
                memo=st.text_input("메모",value=row.get('메모',''),key=f"memo_{idx}")
                if st.button("💾 저장",key=f"save_{idx}"):
                    df_c.at[idx,'키워드보완']=extra_kw
                    df_c.at[idx,'수신거부']='Y' if unsub_cb else ''
                    df_c.at[idx,'메모']=memo
                    with st.spinner("드라이브 저장 중..."):
                        if save_excel(drive, df_c, COMPANIES_FILE, "기업DB", "1F4E79"):
                            st.success(f"{row['기업명']} 저장 완료!")


# ══════════════════════════════════════════════════════
# 🔄 공고 수집
# ══════════════════════════════════════════════════════
elif page == "🔄 공고 수집":
    st.title("공고 수집")

    info_box(
        "공고 수집이란?",
        """
기업마당(bizinfo.go.kr) 공공 API를 통해 전체 지원사업 공고를 수집하고
드라이브의 `notices_db.xlsx`에 누적 저장하는 화면입니다.

**수집 방식**
- 금융·기술개발·인력·수출·내수·창업·경영·기타 **8개 분야 전체** 수집
- `pblancId` 기준으로 **중복 저장 방지** (이미 있는 공고는 스킵)
- 기존 공고 중 내용이 **수정된 것은 자동 업데이트**
- 마감일을 자동 파싱하여 저장 (비정형 마감일은 빈칸 처리)

**수집 주기**
주 1회 실행을 권장합니다 (매주 월요일).
수집된 공고는 매칭 실행 시 자동으로 활용됩니다.
        """,
        """
- **수집 분야 변경** → `app.py`의 `REALM_CODES` 리스트 수정
- **수집 건수 제한** → API 파라미터 `searchCnt` 값 조정 (0=전체)
- **사업개요 저장 길이** → `to_row()` 함수의 `[:500]` 숫자 변경
        """
    )

    with st.spinner("드라이브에서 공고 DB 로딩 중..."):
        df_n = load_excel(drive, NOTICES_FILE)

    if not df_n.empty:
        c1,c2,c3=st.columns(3)
        c1.metric("현재 DB", f"{len(df_n):,}건")
        c2.metric("마지막 수집일", df_n['수집일'].max() if '수집일' in df_n.columns else "—")
        c3.metric("마감일 파싱 성공",
                  f"{(df_n['마감일']!='').sum()}건" if '마감일' in df_n.columns else "—")

    st.divider()
    if st.button("🔄 지금 수집 실행", type="primary"):
        REALM_CODES=["01","02","03","04","05","06","07","09"]
        all_items,seen=[],set()
        prog=st.progress(0,text="수집 중..."); log_area=st.empty(); logs=[]

        for idx,code in enumerate(REALM_CODES):
            params={"crtfcKey":API_KEY,"dataType":"json","searchCnt":"0","searchLclasId":code}
            try:
                items=requests.get(BASE_URL,params=params,timeout=30).json().get('jsonArray',[])
                for item in items:
                    pid=item.get('pblancId','')
                    if pid and pid not in seen: seen.add(pid); all_items.append(item)
                logs.append(f"✅ 분야코드 {code}: {len(items)}건")
            except Exception as e:
                logs.append(f"❌ 분야코드 {code}: {e}")
            prog.progress((idx+1)/len(REALM_CODES)); log_area.code("\n".join(logs))

        def to_row(item):
            def pdl(s):
                try: return datetime.strptime(re.sub(r'\.', '-', s.split('~')[-1].strip()),"%Y-%m-%d").strftime("%Y-%m-%d")
                except: return ""
            return {"pblancId":item.get('pblancId',''),"공고명":item.get('pblancNm',''),
                    "주관기관":item.get('jrsdInsttNm',''),"분야":item.get('pldirSportRealmLclasCodeNm',''),
                    "세부분야":item.get('pldirSportRealmMlsfcCodeNm',''),
                    "접수기간":item.get('reqstBeginEndDe',''),"마감일":pdl(item.get('reqstBeginEndDe','')),
                    "지원대상":item.get('trgetNm',''),
                    "사업개요":strip_html(item.get('bsnsSumryCn',''))[:500],  # 최대 500자
                    "해시태그":item.get('hashtags',''),"공고링크":item.get('pblancUrl',''),
                    "수정일":item.get('updtPnttm',''),"수집일":datetime.today().strftime("%Y-%m-%d")}

        ex_map={r['pblancId']:r.get('수정일','') for _,r in df_n.iterrows()} if not df_n.empty else {}
        new_rows,upd_rows=[],[]
        for item in all_items:
            pid=item.get('pblancId','')
            if not pid: continue
            row=to_row(item)
            if pid not in ex_map: new_rows.append(row)
            elif ex_map[pid]!=item.get('updtPnttm',''): upd_rows.append(row)

        if not df_n.empty:
            upd_ids={r['pblancId'] for r in upd_rows}
            df_final=pd.concat([df_n[~df_n['pblancId'].isin(upd_ids)],
                                 pd.DataFrame(new_rows+upd_rows)],ignore_index=True)
        else:
            df_final=pd.DataFrame(new_rows)

        with st.spinner("드라이브에 엑셀로 저장 중..."):
            save_excel(drive, df_final, NOTICES_FILE, "공고DB", "00897B")

        prog.progress(1.0,text="완료!")
        st.success(f"수집 완료! 총 {len(df_final):,}건 (신규 {len(new_rows)} / 업데이트 {len(upd_rows)}) → notices_db.xlsx 저장")
        st.rerun()

    if not df_n.empty:
        st.divider()
        st.subheader("공고 DB 미리보기 (최근 20건)")
        cols=[c for c in ["공고명","주관기관","분야","접수기간","마감일"] if c in df_n.columns]
        st.dataframe(df_n[cols].head(20), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════
# 🔗 매칭 결과
# ══════════════════════════════════════════════════════
elif page == "🔗 매칭 결과":
    st.title("매칭 결과")

    info_box(
        "매칭이란?",
        """
기업 DB와 공고 DB를 교차하여 기업별 맞춤 공고를 자동으로 추출하는 화면입니다.

**매칭 로직**
1. 기업의 **관심사업분야** → API 분야코드로 변환 → 해당 분야 공고만 필터
2. 이미 발송한 공고는 **자동 제외** (send_history 참조)
3. **마감일이 지난 공고 자동 제외**
4. **수신거부 기업 자동 제외**
5. 키워드 스코어링 (★★★ +3점 / ★★ +2점 / 기업키워드 +2점 / 수출국가 +2점)
6. 점수 높은 순으로 기업당 최대 N건 추출

**검토 탭**
매칭 결과를 보고 ○(승인) / ✕(제외)를 클릭합니다.
공고 원문 링크를 눌러 실제 내용을 확인한 후 판단하세요.
★★★ 위주로 먼저 검토하는 것을 권장합니다.
        """,
        """
- **기업당 최대 건수** → 슬라이더로 조정 (기본 5건)
- **키워드 추가·수정** → '설정' 메뉴에서 변경 후 저장
- **기업 키워드 보완** → '기업 관리' 메뉴에서 개별 기업 수정
        """
    )

    tab1,tab2=st.tabs(["매칭 실행","검토 & 승인"])

    with tab1:
        max_per=st.slider("기업당 최대 추천 건수",3,10,5)
        if st.button("🔗 매칭 실행",type="primary"):
            with st.spinner("드라이브에서 데이터 로딩 중..."):
                df_c=load_excel(drive,COMPANIES_FILE)
                df_n=load_excel(drive,NOTICES_FILE)
                df_h=load_excel(drive,HISTORY_FILE)
                HIGH,MID=load_keywords(drive)
            if df_n.empty: st.error("notices_db 없음 → 공고 수집 먼저"); st.stop()
            if df_c.empty: st.error("기업 DB 없음 → 기업 관리에서 업로드"); st.stop()
            if '수신거부' in df_c.columns: df_c=df_c[df_c['수신거부']!='Y']
            already_sent=set(zip(df_h['기업명'],df_h['pblancId'])) if not df_h.empty else set()
            all_results=[]; prog=st.progress(0)
            for idx,(_,row) in enumerate(df_c.iterrows()):
                interest=row.get('관심사업분야','')
                realm_names=[k for k,v in REALM_CODE.items() if v in [rv for rk,rv in REALM_CODE.items() if rk in interest]]
                filtered=df_n[df_n['분야'].isin(realm_names)] if '분야' in df_n.columns else df_n
                scored=[r for _,n in filtered.iterrows() if (r:=score_notice(n.to_dict(),row,already_sent,HIGH,MID))]
                scored.sort(key=lambda x:-x['점수'])
                all_results.extend(scored[:max_per])
                prog.progress((idx+1)/len(df_c))
            st.session_state['match_results']=all_results
            st.success(f"매칭 완료! 총 {len(all_results)}건 → '검토 & 승인' 탭으로 이동하세요.")

    with tab2:
        results=st.session_state.get('match_results',[])
        if not results:
            st.info("매칭 실행 탭에서 먼저 실행하세요.")
        else:
            df_show=pd.DataFrame(results)
            c1,c2=st.columns(2)
            with c1: filter_stars=st.multiselect("관련도",["★★★","★★"],default=["★★★","★★"])
            with c2: filter_co=st.selectbox("기업",["전체"]+sorted(df_show['기업명'].unique().tolist()))
            filtered=df_show[df_show['관련도'].isin(filter_stars)]
            if filter_co!="전체": filtered=filtered[filtered['기업명']==filter_co]
            if 'review_state' not in st.session_state: st.session_state['review_state']={}
            ap=sum(1 for v in st.session_state['review_state'].values() if v=="○")
            rj=sum(1 for v in st.session_state['review_state'].values() if v=="✕")
            st.caption(f"총 {len(filtered)}건  |  ✅ 승인 {ap}건  |  ❌ 제외 {rj}건")
            st.divider()
            for i,(idx,row) in enumerate(filtered.iterrows()):
                key=f"{row['기업명']}_{row.get('공고ID','')}"
                current=st.session_state['review_state'].get(key,"")
                icon="🟡" if not current else ("✅" if current=="○" else "❌")
                with st.expander(f"{icon} **{row['기업명']}**  |  {row.get('관련도','')}  |  {row.get('공고명','')[:35]}"):
                    c1,c2=st.columns([3,1])
                    with c1:
                        st.markdown(f"**주관기관:** {row.get('주관기관','')}  |  **마감:** {row.get('마감일','')}")
                        st.markdown(f"**사업개요:** {row.get('사업개요','')}")
                        st.markdown(f"**매칭키워드:** `{row.get('시스템매칭','')}` / `{row.get('기업키워드매칭','')}`")
                        if row.get('공고링크',''): st.markdown(f"[🔗 공고 원문 보기]({row.get('공고링크','')})")
                    with c2:
                        if st.button("○ 승인",key=f"o_{key}_{i}",type="primary"):
                            st.session_state['review_state'][key]="○"; st.rerun()
                        if st.button("✕ 제외",key=f"x_{key}_{i}"):
                            st.session_state['review_state'][key]="✕"; st.rerun()
            st.divider()
            c1,c2=st.columns(2)
            with c1:
                if st.button("✅ 검토 완료 저장",type="primary"):
                    for r in results:
                        r['담당자검토']=st.session_state['review_state'].get(f"{r['기업명']}_{r.get('공고ID','')}","")
                    st.session_state['match_results']=results
                    st.success(f"저장됨. 승인 {ap}건 → '발송 관리' 메뉴로 이동하세요.")
            with c2:
                if st.button("📥 매칭결과 엑셀 저장"):
                    fname=f"매칭결과_{datetime.today().strftime('%Y%m%d')}.xlsx"
                    with st.spinner("드라이브 저장 중..."):
                        save_excel(drive,pd.DataFrame(results),fname,"매칭결과","C55A11",star_col="관련도")
                    st.success(f"드라이브에 {fname} 저장됨!")


# ══════════════════════════════════════════════════════
# 📤 발송 관리
# ══════════════════════════════════════════════════════
elif page == "📤 발송 관리":
    st.title("발송 관리")

    info_box(
        "발송 관리란?",
        """
담당자가 승인(○)한 공고를 기업별로 묶어서 자동 발송하는 화면입니다.

**발송 방식**
- **HTML 메일** — 공고명이 클릭 가능한 링크로 포함, 네이버·회사메일 모두 호환
- **캘린더 등록** — 마감일 기준 D-7·D-3·당일 이벤트 자동 등록
  - 공통 캘린더: 전체 선정기업 공유용
  - 개별 캘린더: 해당 기업만 볼 수 있는 맞춤 캘린더 (생성된 경우)
- **이력 기록** — 발송 완료 건을 send_history.xlsx에 자동 저장

**테스트 모드**
사이드바의 '테스트 모드' 토글이 켜져 있으면 실제 기업이 아닌
담당자 본인 메일(fbwlgns819@naver.com 등)로만 발송됩니다.
실제 발송 전 반드시 테스트 모드로 먼저 확인하세요.
        """,
        """
- **테스트 수신 이메일 변경** → `app.py`의 `TEST_RECIPIENTS` 리스트 수정
- **발신자 이름·서명 변경** → `app.py` 발송 섹션의 HTML 템플릿 수정
- **캘린더 미사용** → `calendar_id.txt`가 드라이브에 없으면 자동 스킵
        """
    )

    results=st.session_state.get('match_results',[])
    approved=[r for r in results if r.get('담당자검토')=='○']

    if not approved:
        st.warning("승인된 공고가 없습니다. '매칭 결과'에서 검토를 완료하세요.")
    else:
        companies=list(set(r['기업명'] for r in approved))
        c1,c2,c3=st.columns(3)
        c1.metric("승인 건수",f"{len(approved)}건")
        c2.metric("대상 기업",f"{len(companies)}개사")
        c3.metric("발송 모드","테스트" if test_mode else "실제")
        if test_mode: st.warning("⚠️ 테스트 모드: 본인 메일로만 발송됩니다.")
        else:         st.success("✅ 실제 모드: 기업 담당자 이메일로 발송됩니다.")

        st.divider()
        st.subheader("발송 미리보기")
        preview_co=st.selectbox("기업 선택",companies)
        preview_notices=[r for r in approved if r['기업명']==preview_co]
        with st.expander(f"📧 {preview_co} 메일 미리보기"):
            for i,n in enumerate(preview_notices,1):
                st.markdown(f"**{i}. {n.get('관련도','')} [{n.get('공고명','')}]({n.get('공고링크','#')})**")
                st.markdown(f"주관: {n.get('주관기관','')}  |  기간: {n.get('접수기간','')}")
                st.caption(n.get('사업개요','')); st.divider()

        st.divider()
        if st.button("📤 발송 실행",type="primary"):
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            import base64

            cal_id=load_text(drive,CALID_FILE)
            ind_cals=load_json(drive,INDCAL_FILE)
            CALENDAR_LINK=f"https://calendar.google.com/calendar?cid={cal_id}" if cal_id else ""
            df_c_cur=load_excel(drive,COMPANIES_FILE)

            history_records=[]; prog=st.progress(0); log=st.empty(); logs=[]
            grouped={}
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

                ind_link=""
                if company in ind_cals and ind_cals[company].get('calendar_id'):
                    ind_link=f"""<div style="margin-top:8px">
                      <a href="https://calendar.google.com/calendar?cid={ind_cals[company]['calendar_id']}"
                         style="color:#2E75B6;font-size:13px">📅 {company} 전용 캘린더 구독</a></div>"""

                cal_sec=f"""<div style="background:#EBF3FB;border-radius:6px;padding:14px;margin-top:16px">
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

                co_email=""
                if not df_c_cur.empty and '이메일' in df_c_cur.columns:
                    m=df_c_cur[df_c_cur['기업명']==company]
                    if not m.empty: co_email=m.iloc[0].get('이메일','')

                recipients=TEST_RECIPIENTS if test_mode else ([co_email] if co_email else [])
                for to in recipients:
                    msg=MIMEMultipart('alternative')
                    msg['From']="onestop.kipcc@gmail.com"; msg['To']=to
                    msg['Subject']=f"[원스톱 스케일업] 맞춤 지원공고 {len(notices)}건 안내 — {company}"
                    msg.attach(MIMEText(html,'html','utf-8'))
                    gmail.users().messages().send(userId='me',body={'raw':base64.urlsafe_b64encode(msg.as_bytes()).decode()}).execute()

                for n in notices:
                    dl=parse_deadline(n.get('접수기간','')); pid=n.get('공고ID','')
                    if not dl or not pid: continue
                    desc=f"주관기관: {n.get('주관기관','')}\n공고링크: {n.get('공고링크','')}\n안내기업: {company}"
                    cids=[cal_id] if cal_id else []
                    if company in ind_cals and ind_cals[company].get('calendar_id'):
                        cids.append(ind_cals[company]['calendar_id'])
                    for cid in cids:
                        try:
                            if cal.events().list(calendarId=cid,privateExtendedProperty=f"pblancId={pid}").execute().get('items'): continue
                        except: pass
                        for days,label in [(0,"마감"),(7,"D-7"),(3,"D-3")]:
                            d=(dl-timedelta(days=days)).strftime('%Y-%m-%d')
                            cal.events().insert(calendarId=cid,body={
                                'summary':f"[{label}] {n.get('공고명','')}",
                                'description':desc,
                                'start':{'date':d,'timeZone':'Asia/Seoul'},
                                'end':  {'date':d,'timeZone':'Asia/Seoul'},
                                'extendedProperties':{'private':{'pblancId':pid}},
                            }).execute()

                for n in notices:
                    history_records.append({"기업명":company,"pblancId":n.get('공고ID',''),
                        "공고명":n.get('공고명',''),"발송일":datetime.today().strftime("%Y-%m-%d"),
                        "매칭점수":n.get('점수',''),"담당자검토":"○",
                        "검토의견":n.get('검토의견',''),"신청여부":"","선정결과":""})

                logs.append(f"✅ {company} — {len(notices)}건 발송 완료")
                log.code("\n".join(logs)); prog.progress((idx+1)/len(grouped))

            with st.spinner("발송 이력 드라이브 저장 중..."):
                df_h=load_excel(drive,HISTORY_FILE)
                df_new=pd.DataFrame(history_records)
                df_fin=pd.concat([df_h,df_new],ignore_index=True) if not df_h.empty else df_new
                save_excel(drive,df_fin,HISTORY_FILE,"발송이력","375623")

            prog.progress(1.0)
            st.success(f"발송 완료! {len(history_records)}건 → send_history.xlsx 저장됨")
            st.session_state['match_results']=[]; st.session_state['review_state']={}


# ══════════════════════════════════════════════════════
# 📋 발송 이력
# ══════════════════════════════════════════════════════
elif page == "📋 발송 이력":
    st.title("발송 이력")

    info_box(
        "발송 이력이란?",
        """
발송이 완료된 모든 건을 기록하고 성과를 추적하는 화면입니다.

**자동 기록 항목**
기업명, 공고명, 발송일, 매칭점수, 담당자검토 여부

**담당자가 직접 입력하는 항목**
- **신청여부** — 기업이 실제로 지원사업에 신청했는지 (Y/N)
- **선정결과** — 선정 / 미선정 / 대기

**중복 발송 방지**
이 이력을 기반으로 이미 발송한 공고는 다음 매칭에서 자동 제외됩니다.
특정 공고를 재발송하고 싶으면 해당 행을 삭제 후 저장하세요.
        """,
        """
- **신청여부·선정결과 입력** → 표에서 직접 클릭 후 '드라이브 저장' 버튼
- **특정 행 삭제** → 표에서 행 선택 후 Delete 키 → '드라이브 저장'
- **전체 초기화** → 드라이브에서 send_history.xlsx 삭제 (주의!)
        """
    )

    with st.spinner("드라이브에서 이력 로딩 중..."):
        df_h=load_excel(drive,HISTORY_FILE)

    if df_h.empty:
        st.info("발송 이력이 없습니다.")
    else:
        c1,c2,c3=st.columns(3)
        c1.metric("총 발송",len(df_h))
        c2.metric("신청 건",(df_h['신청여부']=='Y').sum() if '신청여부' in df_h.columns else 0)
        c3.metric("선정 건",(df_h['선정결과']=='선정').sum() if '선정결과' in df_h.columns else 0)
        st.divider()

        edited=st.data_editor(df_h,use_container_width=True,hide_index=True,
            column_config={
                "신청여부":st.column_config.SelectboxColumn("신청여부",options=["","Y","N"]),
                "선정결과":st.column_config.SelectboxColumn("선정결과",options=["","선정","미선정","대기"]),
            })
        if st.button("💾 드라이브 저장"):
            with st.spinner("저장 중..."):
                save_excel(drive,edited,HISTORY_FILE,"발송이력","375623")
            st.success("저장 완료!")
        st.divider()
        buf=io.BytesIO()
        with pd.ExcelWriter(buf,engine='openpyxl') as w: df_h.to_excel(w,index=False)
        st.download_button("📥 엑셀 다운로드",buf.getvalue(),HISTORY_FILE,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ══════════════════════════════════════════════════════
# 📊 성과 집계
# ══════════════════════════════════════════════════════
elif page == "📊 성과 집계":
    st.title("성과 집계")

    info_box(
        "성과 집계란?",
        """
발송 이력 데이터를 기반으로 사업 성과를 집계하는 화면입니다.

**집계 항목**
- 총 발송 건수, 신청 건수, 선정 건수
- 신청 전환율 (신청 건 / 발송 건)
- 기업별 현황 (발송·신청·선정 건수)

**활용 방법**
분기 보고서 작성 시 이 화면의 수치를 참고하세요.
신청여부·선정결과는 '발송 이력' 메뉴에서 직접 입력합니다.
        """,
        "집계 기준을 바꾸고 싶으면 개발자에게 문의하거나 app.py의 성과 집계 섹션을 수정하세요."
    )

    with st.spinner("드라이브에서 이력 로딩 중..."):
        df_h=load_excel(drive,HISTORY_FILE)

    if df_h.empty:
        st.info("발송 이력이 없습니다.")
    else:
        total=len(df_h)
        applied=(df_h['신청여부']=='Y').sum() if '신청여부' in df_h.columns else 0
        selected=(df_h['선정결과']=='선정').sum() if '선정결과' in df_h.columns else 0
        rate=f"{applied/total*100:.1f}%" if total else "0%"

        c1,c2,c3,c4=st.columns(4)
        c1.metric("총 발송",f"{total}건")
        c2.metric("신청 건",f"{applied}건")
        c3.metric("선정 건",f"{selected}건")
        c4.metric("신청 전환율",rate)

        if '기업명' in df_h.columns:
            st.divider(); st.subheader("기업별 현황")
            summary=df_h.groupby('기업명').agg(
                발송건수=('공고명','count'),
                신청건수=('신청여부',lambda x:(x=='Y').sum()),
                선정건수=('선정결과',lambda x:(x=='선정').sum()),
            ).reset_index()
            st.dataframe(summary,use_container_width=True,hide_index=True)


# ══════════════════════════════════════════════════════
# ⚙️ 설정
# ══════════════════════════════════════════════════════
elif page == "⚙️ 설정":
    st.title("설정")

    info_box(
        "설정이란?",
        """
시스템 전반의 설정을 관리하는 화면입니다.

**주요 설정 항목**
- **키워드 설정** — 매칭에 사용되는 ★★★/★★ 키워드 추가·삭제
- **드라이브 연동 현황** — 각 파일이 드라이브에 있는지 확인
- **인증 상태** — 구글 인증이 정상인지 확인

**키워드 설정 방법**
키워드를 추가하거나 삭제하고 '저장' 버튼을 누르면
드라이브의 keywords.json에 저장되어 다음 매칭부터 바로 반영됩니다.

**코드를 수정해야 하는 것들**
- 테스트 수신 이메일 변경 → `TEST_RECIPIENTS`
- 발신자 이메일 변경 → HTML 템플릿의 `onestop.kipcc@gmail.com`
- 드라이브 폴더 ID 변경 → `DRIVE_FOLDER_ID`
        """,
        """
코드 수정이 필요한 경우:
1. 깃허브에서 `app.py` 파일 열기
2. 해당 부분 수정 후 Commit
3. Streamlit Cloud 자동 재배포 (1~2분)
        """
    )

    # 인증 상태
    st.subheader("🔐 인증 상태")
    if 'google' in st.secrets: st.success("✅ Streamlit Secrets 인증 설정됨")
    elif os.path.exists('token.json'): st.success("✅ 로컬 token.json 인증 설정됨")
    else: st.error("❌ 인증 파일 없음")

    st.divider()

    # 드라이브 현황
    st.subheader("📁 드라이브 연동 현황")
    st.markdown(f"[📂 드라이브 폴더 열기](https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID})")
    files_check={
        COMPANIES_FILE:"기업 DB (companies_db.xlsx)",
        NOTICES_FILE:  "공고 DB (notices_db.xlsx)",
        HISTORY_FILE:  "발송 이력 (send_history.xlsx)",
        CALID_FILE:    "공통 캘린더 ID (calendar_id.txt)",
        KEYWORDS_FILE: "키워드 설정 (keywords.json)",
        CATCAL_FILE:   "분야별 캘린더 (category_calendars.json)",
        INDCAL_FILE:   "기업별 캘린더 (individual_calendars.json)",
    }
    for fname,label in files_check.items():
        fid=drive_file_id(drive,fname)
        st.write(f"{'✅' if fid else '❌'} {label}")

    st.divider()

    # 키워드 설정
    st.subheader("🔑 키워드 설정")
    st.caption("수정 후 저장하면 다음 매칭 실행부터 바로 반영됩니다.")

    with st.spinner("키워드 로딩 중..."):
        HIGH,MID=load_keywords(drive)

    col1,col2=st.columns(2)
    with col1:
        st.markdown("**★★★ 직접 연계** (+3점)")
        st.caption("이 키워드가 공고에 있으면 무조건 추천 목록 포함")
        high_input=st.text_area("",value="\n".join(HIGH),height=180,
            label_visibility="collapsed",key="high_kw",
            placeholder="한 줄에 키워드 하나씩 입력")
    with col2:
        st.markdown("**★★ 간접 연계** (+2점)")
        st.caption("이 키워드가 있으면 추천 후보로 포함")
        mid_input=st.text_area("",value="\n".join(MID),height=180,
            label_visibility="collapsed",key="mid_kw",
            placeholder="한 줄에 키워드 하나씩 입력")

    st.caption("💡 팁: 너무 일반적인 단어(중소기업, 수출 등)는 오탐이 많으니 신중하게 추가하세요.")

    if st.button("💾 키워드 저장 → 드라이브",type="primary"):
        new_high=[k.strip() for k in high_input.split('\n') if k.strip()]
        new_mid =[k.strip() for k in mid_input.split('\n')  if k.strip()]
        with st.spinner("드라이브에 저장 중..."):
            if save_json(drive,{"HIGH":new_high,"MID":new_mid},KEYWORDS_FILE):
                st.success(f"저장 완료! ★★★ {len(new_high)}개 / ★★ {len(new_mid)}개")
            else:
                st.error("저장 실패")
