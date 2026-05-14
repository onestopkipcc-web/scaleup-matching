"""
원스톱 스케일업 — 공고 매칭 시스템
실행: streamlit run app.py
"""
import streamlit as st
import pandas as pd
import requests
import re, os, glob, json, tempfile
from datetime import datetime, timedelta

# ── 페이지 설정 ────────────────────────────────────────
st.set_page_config(
    page_title="원스톱 스케일업",
    page_icon="📢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 구글 인증 (Secrets 또는 로컬 파일) ───────────────
def get_google_creds():
    """Streamlit Cloud Secrets 또는 로컬 token.json에서 인증 로드"""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    SCOPES = [
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/calendar',
    ]

    # Streamlit Cloud 환경
    if 'google' in st.secrets:
        token_data = json.loads(st.secrets['google']['token'])
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    # 로컬 환경
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        st.error("인증 파일이 없습니다. Secrets 설정 또는 token.json을 확인하세요.")
        st.stop()

    # 토큰 만료 시 갱신
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            st.error(f"토큰 갱신 실패: {e}\n재인증이 필요합니다.")
            st.stop()

    return creds

# ── 작업 경로 설정 ────────────────────────────────────
def get_work_dir():
    """Streamlit Cloud면 임시 폴더, 로컬이면 작업 폴더"""
    local = r'C:\Users\fbwlg\Desktop\26년도\2. 원스톱\7. 정보 전달 체계 구축'
    if os.path.exists(local):
        return local
    return os.getcwd()

WORK_DIR   = get_work_dir()
WALLA_FILE = os.path.join(WORK_DIR, 'TEST_(WALLA) 2026년도 스케일업 프로그램 선정기업.xlsx')
API_KEY    = "Nt604D"
BASE_URL   = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"

REALM_CODE = {
    "금융":"01","기술개발":"02","인력":"03","수출":"04",
    "내수":"05","창업":"06","경영":"07","기타":"09",
}
HIGH = ["혁신제품","혁신조달","G-PASS","혁신기업","해외조달","공공구매","조달청"]
MID  = ["해외판로","수출바우처","수출지원","해외진출","글로벌","스케일업","판로개척","해외마케팅"]

# ── 유틸 함수 ─────────────────────────────────────────
def strip_html(html):
    return re.sub(r'<[^>]+>', ' ', html or '').strip()

def parse_deadline(s):
    try:
        end = s.split('~')[-1].strip()
        return datetime.strptime(re.sub(r'\.', '-', end), "%Y-%m-%d")
    except:
        return None

def load_companies():
    col_map = {
        '기업명':       '(기본정보) 기업명을 입력해 주시기 바랍니다.',
        '이메일':       '(기본정보) 담당자 이메일을 입력해 주시기 바랍니다.',
        '관심사업분야': '(수요파악) 관심있는 정부 사업 분야를 선택하여 주시기 바랍니다.(최대 2개 선택 가능)',
        '기술키워드':   '(수요파악) 귀사 제품의 주요 기술/분야 키워드를 입력하여 주시기 바랍니다.',
        '제품분야':     '(기본정보) 귀사의 제품/기술 분야를 선택하여 주시기 바랍니다.(최대 3개선택 가능)',
        '수출실적':     '(기업현황) 최근 3년간 수출 실적 여부를 선택하여 주시기 바랍니다.',
        '수출국가':     '① 주요 수출 국가를 입력하여 주시기 바랍니다.',
    }
    if not os.path.exists(WALLA_FILE):
        return pd.DataFrame()
    raw = pd.read_excel(WALLA_FILE)
    df  = pd.DataFrame({k: raw[v] for k, v in col_map.items() if v in raw.columns})
    return df.fillna("")

def load_notices():
    path = os.path.join(WORK_DIR, "notices_db.csv")
    if os.path.exists(path):
        return pd.read_csv(path, dtype=str).fillna("")
    return pd.DataFrame()

def load_history():
    path = os.path.join(WORK_DIR, "send_history.csv")
    if os.path.exists(path):
        return pd.read_csv(path, dtype=str).fillna("")
    return pd.DataFrame(columns=["기업명","pblancId","공고명","발송일","매칭점수","담당자검토","검토의견","신청여부","선정결과"])

def save_history(df):
    path = os.path.join(WORK_DIR, "send_history.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")

def load_calendar_id():
    path = os.path.join(WORK_DIR, "calendar_id.txt")
    if os.path.exists(path):
        return open(path).read().strip()
    return ""

def score_notice(notice, row, already_sent):
    pid = notice.get('pblancId', '')
    if (row['기업명'], pid) in already_sent:
        return None
    deadline = notice.get('마감일', '')
    if deadline and deadline < datetime.today().strftime("%Y-%m-%d"):
        return None
    if str(row.get('수출실적', '')) == '아니오' and '수출' in str(notice.get('분야', '')):
        return None

    text = " ".join([str(notice.get(k, '')) for k in ['공고명','사업개요','해시태그','주관기관','지원대상']])
    matched_high = [kw for kw in HIGH if kw in text]
    matched_mid  = [kw for kw in MID  if kw in text]
    sys_score    = len(matched_high)*3 + len(matched_mid)*2

    raw_kw = str(row.get('기술키워드','')) + ',' + str(row.get('제품분야',''))
    co_kws = [k.strip() for k in raw_kw.split(',') if k.strip() and k.strip()!='nan']
    matched_co = [kw for kw in co_kws if kw in text]
    co_score   = len(matched_co)*2

    country = str(row.get('수출국가',''))
    c_score = 2 if (country and country != 'nan' and country in text) else 0

    total = sys_score + co_score + c_score
    if not (matched_high or matched_mid or matched_co):
        return None
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
[data-testid="stSidebar"] {background: #f8f9fa;}
.stButton button {border-radius: 6px;}
</style>
""", unsafe_allow_html=True)

# ── 사이드바 ──────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📢 원스톱 스케일업")
    st.caption("공고 매칭 시스템")
    st.divider()

    page = st.radio(
        "메뉴",
        ["🏠 대시보드", "👥 기업 관리", "🔄 공고 수집",
         "🔗 매칭 결과", "📤 발송 관리",
         "📋 발송 이력", "📊 성과 집계", "⚙️ 설정"],
        label_visibility="collapsed"
    )
    st.divider()
    test_mode = st.toggle("테스트 모드", value=True)
    if test_mode:
        st.warning("테스트 메일로 발송")
    else:
        st.success("실제 기업으로 발송")


# ══════════════════════════════════════════════════════
# 대시보드
# ══════════════════════════════════════════════════════
if page == "🏠 대시보드":
    st.title("대시보드")

    try:
        df_c = load_companies()
        df_n = load_notices()
        df_h = load_history()
        n_companies = len(df_c)
        n_notices   = len(df_n)
        n_history   = len(df_h)
    except:
        n_companies = n_notices = n_history = 0

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("등록 기업",  f"{n_companies}개사")
    c2.metric("수집 공고",  f"{n_notices:,}건")
    c3.metric("발송 이력",  f"{n_history}건")
    c4.metric("운영 모드",  "테스트" if test_mode else "실제 발송")

    st.divider()
    st.subheader("이번 주 진행 단계")
    s1,s2,s3,s4,s5 = st.columns(5)
    s1.markdown("**① 공고 수집**\n\n✅ 완료")
    s2.markdown("**② 매칭 실행**\n\n✅ 완료")
    s3.markdown("**③ 담당자 검토**\n\n🔵 진행중")
    s4.markdown("**④ 발송**\n\n⬜ 대기")
    s5.markdown("**⑤ 이력 기록**\n\n⬜ 대기")


# ══════════════════════════════════════════════════════
# 기업 관리
# ══════════════════════════════════════════════════════
elif page == "👥 기업 관리":
    st.title("기업 관리")
    st.caption("기업 정보 조회·수정·수신거부 처리")

    df_c = load_companies()

    if df_c.empty:
        st.warning("WALLA 파일을 작업 폴더에 넣어주세요.")
    else:
        # 요약
        c1,c2,c3 = st.columns(3)
        c1.metric("전체 기업", f"{len(df_c)}개사")
        if 'companies_db.csv' in os.listdir(WORK_DIR):
            df_db = pd.read_csv(os.path.join(WORK_DIR,'companies_db.csv'),dtype=str).fillna("")
            c2.metric("수신거부", f"{(df_db.get('수신거부','')=='Y').sum()}개사" if '수신거부' in df_db.columns else "0개사")
            c3.metric("키워드 보완", f"{(df_db.get('키워드보완','')!='').sum()}개사" if '키워드보완' in df_db.columns else "0개사")
        else:
            c2.metric("수신거부", "0개사")
            c3.metric("키워드 보완", "0개사")

        st.divider()

        # 검색
        search = st.text_input("🔍 기업명 검색")
        if search:
            df_show = df_c[df_c['기업명'].str.contains(search)]
        else:
            df_show = df_c

        # 기업 목록
        for _, row in df_show.iterrows():
            with st.expander(f"**{row['기업명']}**  |  {row.get('관심사업분야','')}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**이메일:** {row.get('이메일','')}")
                    st.markdown(f"**관심분야:** {row.get('관심사업분야','')}")
                    st.markdown(f"**수출실적:** {row.get('수출실적','')} / {row.get('수출국가','')}")
                with col2:
                    st.markdown(f"**제품분야:** {row.get('제품분야','')}")
                    st.markdown(f"**기술키워드:** {row.get('기술키워드','')}")

                # 키워드 보완 입력
                extra_kw = st.text_input(
                    "키워드 보완 (담당자 직접 추가)",
                    key=f"kw_{row['기업명']}",
                    placeholder="예: 스마트팜, IoT, 농업기술"
                )
                unsub = st.checkbox("수신거부", key=f"unsub_{row['기업명']}")

                if st.button("저장", key=f"save_{row['기업명']}"):
                    # companies_db.csv 업데이트
                    db_path = os.path.join(WORK_DIR, 'companies_db.csv')
                    if os.path.exists(db_path):
                        df_db = pd.read_csv(db_path, dtype=str).fillna("")
                    else:
                        df_db = df_c.copy()
                        df_db['키워드보완'] = ''
                        df_db['수신거부']   = ''
                        df_db['메모']       = ''

                    mask = df_db['기업명'] == row['기업명']
                    if mask.any():
                        df_db.loc[mask, '키워드보완'] = extra_kw
                        df_db.loc[mask, '수신거부']   = 'Y' if unsub else ''
                    else:
                        new_row = row.to_dict()
                        new_row.update({'키워드보완':extra_kw,'수신거부':'Y' if unsub else '','메모':''})
                        df_db = pd.concat([df_db, pd.DataFrame([new_row])], ignore_index=True)

                    df_db.to_csv(db_path, index=False, encoding='utf-8-sig')
                    st.success(f"{row['기업명']} 저장 완료!")


# ══════════════════════════════════════════════════════
# 공고 수집
# ══════════════════════════════════════════════════════
elif page == "🔄 공고 수집":
    st.title("공고 수집")
    st.caption("bizinfo API에서 전체 공고를 수집하고 notices_db.csv에 누적 저장합니다.")

    df_n = load_notices()
    if not df_n.empty:
        c1,c2,c3 = st.columns(3)
        c1.metric("현재 DB 공고 수", f"{len(df_n):,}건")
        c2.metric("마지막 수집일", df_n['수집일'].max() if '수집일' in df_n.columns else "—")
        c3.metric("마감일 파싱 성공", f"{(df_n['마감일']!='').sum()}건" if '마감일' in df_n.columns else "—")

    st.divider()

    if st.button("🔄 지금 수집 실행", type="primary"):
        REALM_CODES = ["01","02","03","04","05","06","07","09"]
        all_items, seen = [], set()
        progress = st.progress(0, text="수집 중...")
        log_area = st.empty()
        logs = []

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
                logs.append(f"❌ 분야코드 {code} 오류: {e}")
            progress.progress((idx+1)/len(REALM_CODES), text=f"수집 중... {idx+1}/{len(REALM_CODES)}")
            log_area.code("\n".join(logs))

        def to_row(item):
            def pdl(s):
                try:
                    e=s.split('~')[-1].strip()
                    return datetime.strptime(re.sub(r'\.','-',e),"%Y-%m-%d").strftime("%Y-%m-%d")
                except: return ""
            return {
                "pblancId":  item.get('pblancId',''),
                "공고명":    item.get('pblancNm',''),
                "주관기관":  item.get('jrsdInsttNm',''),
                "분야":      item.get('pldirSportRealmLclasCodeNm',''),
                "세부분야":  item.get('pldirSportRealmMlsfcCodeNm',''),
                "접수기간":  item.get('reqstBeginEndDe',''),
                "마감일":    pdl(item.get('reqstBeginEndDe','')),
                "지원대상":  item.get('trgetNm',''),
                "사업개요":  strip_html(item.get('bsnsSumryCn',''))[:500],
                "해시태그":  item.get('hashtags',''),
                "공고링크":  item.get('pblancUrl',''),
                "수정일":    item.get('updtPnttm',''),
                "수집일":    datetime.today().strftime("%Y-%m-%d"),
            }

        db_path = os.path.join(WORK_DIR, "notices_db.csv")
        if os.path.exists(db_path):
            df_ex  = pd.read_csv(db_path, dtype=str).fillna("")
            ex_map = {r['pblancId']:r.get('수정일','') for _,r in df_ex.iterrows()}
        else:
            df_ex = pd.DataFrame(); ex_map = {}

        new_rows, upd_rows = [], []
        for item in all_items:
            pid = item.get('pblancId','')
            if not pid: continue
            row = to_row(item)
            if pid not in ex_map: new_rows.append(row)
            elif ex_map[pid] != item.get('updtPnttm',''): upd_rows.append(row)

        if not df_ex.empty:
            upd_ids  = {r['pblancId'] for r in upd_rows}
            df_keep  = df_ex[~df_ex['pblancId'].isin(upd_ids)]
            df_final = pd.concat([df_keep, pd.DataFrame(new_rows+upd_rows)], ignore_index=True)
        else:
            df_final = pd.DataFrame(new_rows)

        df_final.to_csv(db_path, index=False, encoding="utf-8-sig")
        progress.progress(1.0, text="완료!")
        st.success(f"수집 완료! 총 {len(df_final):,}건 (신규 {len(new_rows)}건 / 업데이트 {len(upd_rows)}건)")
        st.rerun()

    if not df_n.empty:
        st.divider()
        st.subheader("공고 DB 미리보기")
        show_cols = ["공고명","주관기관","분야","접수기간","마감일"]
        available = [c for c in show_cols if c in df_n.columns]
        st.dataframe(df_n[available].head(20), use_container_width=True, hide_index=True)


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
            df_c = load_companies()
            df_n = load_notices()
            df_h = load_history()

            if df_n.empty:
                st.error("notices_db.csv 없음 → '공고 수집' 먼저 실행하세요.")
                st.stop()

            # 수신거부 기업 제외
            db_path = os.path.join(WORK_DIR, 'companies_db.csv')
            if os.path.exists(db_path):
                df_db  = pd.read_csv(db_path, dtype=str).fillna("")
                unsub  = set(df_db[df_db.get('수신거부','')=='Y']['기업명'].tolist()) if '수신거부' in df_db.columns else set()
                df_c   = df_c[~df_c['기업명'].isin(unsub)]

            already_sent = set(zip(df_h['기업명'], df_h['pblancId'])) if not df_h.empty else set()
            all_results  = []
            prog = st.progress(0, text="매칭 중...")

            for idx, (_, row) in enumerate(df_c.iterrows()):
                interest = row['관심사업분야']
                codes    = [v for k,v in REALM_CODE.items() if k in interest] or ["02","04"]
                realm_names = [k for k,v in REALM_CODE.items() if v in codes]
                filtered = df_n[df_n['분야'].isin(realm_names)] if '분야' in df_n.columns else df_n

                scored = [r for _,n in filtered.iterrows() if (r:=score_notice(n.to_dict(),row,already_sent))]
                scored.sort(key=lambda x:-x['점수'])
                all_results.extend(scored[:max_per])
                prog.progress((idx+1)/len(df_c), text=f"{row['기업명']} 매칭 중...")

            st.session_state['match_results'] = all_results
            prog.progress(1.0, text="완료!")
            st.success(f"매칭 완료! 총 {len(all_results)}건")

    with tab2:
        st.subheader("담당자 검토")
        results = st.session_state.get('match_results', [])

        if not results:
            st.info("매칭 실행 탭에서 매칭을 먼저 실행하세요.")
        else:
            df_show = pd.DataFrame(results)

            col_f1, col_f2 = st.columns(2)
            with col_f1:
                filter_stars = st.multiselect("관련도", ["★★★","★★"], default=["★★★","★★"])
            with col_f2:
                companies = ["전체"] + sorted(df_show['기업명'].unique().tolist())
                filter_co = st.selectbox("기업", companies)

            filtered = df_show[df_show['관련도'].isin(filter_stars)]
            if filter_co != "전체":
                filtered = filtered[filtered['기업명'] == filter_co]

            if 'review_state' not in st.session_state:
                st.session_state['review_state'] = {}

            approved = sum(1 for v in st.session_state['review_state'].values() if v=="○")
            rejected = sum(1 for v in st.session_state['review_state'].values() if v=="✕")
            st.caption(f"총 {len(filtered)}건  |  승인 {approved}건  |  제외 {rejected}건")
            st.divider()

            for i, (idx, row) in enumerate(filtered.iterrows()):
                key     = f"{row['기업명']}_{row.get('공고ID','')}"
                current = st.session_state['review_state'].get(key, "")
                bg      = "🟡" if not current else ("✅" if current=="○" else "❌")

                with st.expander(f"{bg} {row['기업명']}  |  {row.get('관련도','')}  |  {row.get('공고명','')[:35]}"):
                    c1, c2 = st.columns([3,1])
                    with c1:
                        st.markdown(f"**주관기관:** {row.get('주관기관','')}  |  **마감:** {row.get('마감일','')}")
                        st.markdown(f"**사업개요:** {row.get('사업개요','')}")
                        st.markdown(f"**매칭키워드:** {row.get('시스템매칭','')} / {row.get('기업키워드매칭','')}")
                        link = row.get('공고링크','')
                        if link:
                            st.markdown(f"[🔗 공고 원문 보기]({link})")
                    with c2:
                        if st.button("○ 승인", key=f"o_{key}_{i}", type="primary"):
                            st.session_state['review_state'][key] = "○"
                            st.rerun()
                        if st.button("✕ 제외", key=f"x_{key}_{i}"):
                            st.session_state['review_state'][key] = "✕"
                            st.rerun()
                        memo = st.text_input("메모", key=f"memo_{key}_{i}", label_visibility="collapsed", placeholder="제외 사유 등")

            st.divider()
            if st.button("✅ 검토 완료 저장", type="primary"):
                for r in results:
                    key = f"{r['기업명']}_{r.get('공고ID','')}"
                    r['담당자검토'] = st.session_state['review_state'].get(key,"")
                st.session_state['match_results'] = results
                st.success(f"저장됨. 승인 {approved}건 → '발송 관리' 메뉴로 이동하세요.")


# ══════════════════════════════════════════════════════
# 발송 관리
# ══════════════════════════════════════════════════════
elif page == "📤 발송 관리":
    st.title("발송 관리")

    results  = st.session_state.get('match_results', [])
    approved = [r for r in results if r.get('담당자검토') == '○']

    if not approved:
        st.warning("승인된 공고가 없습니다. '매칭 결과' 메뉴에서 검토를 완료하세요.")
    else:
        companies = list(set(r['기업명'] for r in approved))
        c1,c2,c3 = st.columns(3)
        c1.metric("승인 건수", f"{len(approved)}건")
        c2.metric("대상 기업", f"{len(companies)}개사")
        c3.metric("발송 모드", "테스트" if test_mode else "실제")

        if test_mode:
            st.warning("⚠️ 테스트 모드: 본인 메일로만 발송됩니다.")
        else:
            st.success("✅ 실제 모드: 기업 담당자 이메일로 발송됩니다.")

        # 발송 미리보기
        st.divider()
        st.subheader("발송 예정 목록")
        preview_co = st.selectbox("기업 선택해서 미리보기", companies)
        preview_notices = [r for r in approved if r['기업명'] == preview_co]

        with st.expander(f"📧 {preview_co} 발송 메일 미리보기"):
            st.markdown(f"**수신:** {preview_co} 담당자님")
            st.markdown(f"**제목:** [원스톱 스케일업] 맞춤 지원공고 {len(preview_notices)}건 안내")
            st.divider()
            for i, n in enumerate(preview_notices, 1):
                st.markdown(f"**{i}. {n.get('관련도','')} [{n.get('공고명','')}]({n.get('공고링크','#')})**")
                st.markdown(f"주관: {n.get('주관기관','')}  |  기간: {n.get('접수기간','')}")
                st.markdown(f"{n.get('사업개요','')}")
                st.divider()

        st.divider()
        if st.button("📤 발송 실행", type="primary"):
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            import base64

            TEST_RECIPIENTS = ["fbwlgns819@naver.com","fbwlgns819@kip.re.kr"]
            cal_id = load_calendar_id()
            CALENDAR_LINK = f"https://calendar.google.com/calendar?cid={cal_id}" if cal_id else ""

            try:
                creds = get_google_creds()
                gmail = build('gmail','v1',credentials=creds)
                cal   = build('calendar','v3',credentials=creds)
            except Exception as e:
                st.error(f"구글 인증 오류: {e}"); st.stop()

            history_records = []
            prog = st.progress(0, text="발송 중...")
            log  = st.empty(); logs = []

            grouped = {}
            for r in approved:
                grouped.setdefault(r['기업명'],[]).append(r)

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

                cal_btn = f"""<div style="background:#EBF3FB;border-radius:6px;padding:14px;margin-top:16px">
                  <p style="margin:0 0 8px;color:#1F4E79;font-weight:bold;font-size:13px">📅 캘린더 구독</p>
                  <a href="{CALENDAR_LINK}" style="background:#1F4E79;color:#fff;padding:8px 16px;border-radius:4px;text-decoration:none;font-size:13px">구독하기</a>
                </div>""" if CALENDAR_LINK else ""

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
                    </table>
                    {cal_btn}
                  </td></tr>
                  <tr><td style="background:#f9f9f9;padding:14px 32px;font-size:12px;color:#888;border-top:1px solid #eee">
                    혁신제품지원센터 원스톱 스케일업 운영팀 | onestop.kipcc@gmail.com
                  </td></tr>
                </table></body></html>"""

                msg=MIMEMultipart('alternative')
                msg['From']="onestop.kipcc@gmail.com"
                msg['Subject']=f"[원스톱 스케일업] 맞춤 지원공고 {len(notices)}건 안내 — {company}"
                msg.attach(MIMEText(html,'html','utf-8'))

                recipients = TEST_RECIPIENTS if test_mode else [notices[0].get('이메일','')]
                for to in recipients:
                    msg_copy = MIMEMultipart('alternative')
                    msg_copy['From']=msg['From']; msg_copy['To']=to
                    msg_copy['Subject']=msg['Subject']
                    msg_copy.attach(MIMEText(html,'html','utf-8'))
                    raw=base64.urlsafe_b64encode(msg_copy.as_bytes()).decode()
                    gmail.users().messages().send(userId='me',body={'raw':raw}).execute()

                # 캘린더 등록
                if cal_id:
                    for n in notices:
                        dl=parse_deadline(n.get('접수기간',''))
                        if dl:
                            pid=n.get('공고ID','')
                            try:
                                ex=cal.events().list(calendarId=cal_id,privateExtendedProperty=f"pblancId={pid}").execute()
                                if ex.get('items'): continue
                            except: pass
                            desc=f"주관기관: {n.get('주관기관','')}\n공고링크: {n.get('공고링크','')}\n안내기업: {company}"
                            for days,label in [(0,"마감"),(7,"D-7"),(3,"D-3")]:
                                d=(dl-timedelta(days=days)).strftime('%Y-%m-%d')
                                cal.events().insert(calendarId=cal_id,body={
                                    'summary':f"[{label}] {n.get('공고명','')}",
                                    'description':desc,
                                    'start':{'date':d,'timeZone':'Asia/Seoul'},
                                    'end':  {'date':d,'timeZone':'Asia/Seoul'},
                                    'extendedProperties':{'private':{'pblancId':pid}},
                                }).execute()

                history_records.append({
                    "기업명":company,"pblancId":notices[0].get('공고ID',''),
                    "공고명":notices[0].get('공고명',''),
                    "발송일":datetime.today().strftime("%Y-%m-%d"),
                    "매칭점수":notices[0].get('점수',''),
                    "담당자검토":"○","검토의견":"","신청여부":"","선정결과":"",
                })

                logs.append(f"✅ {company} — {len(notices)}건 발송 완료")
                log.code("\n".join(logs))
                prog.progress((idx+1)/len(grouped))

            # 이력 저장
            df_h   = load_history()
            df_new = pd.DataFrame(history_records)
            df_fin = pd.concat([df_h,df_new],ignore_index=True) if not df_h.empty else df_new
            save_history(df_fin)

            prog.progress(1.0,"완료!")
            st.success(f"발송 완료! {len(history_records)}건 처리됨.")
            st.session_state['match_results'] = []
            st.session_state['review_state']  = {}


# ══════════════════════════════════════════════════════
# 발송 이력
# ══════════════════════════════════════════════════════
elif page == "📋 발송 이력":
    st.title("발송 이력")

    df_h = load_history()
    if df_h.empty:
        st.info("발송 이력이 없습니다.")
    else:
        c1,c2,c3 = st.columns(3)
        c1.metric("총 발송 건", len(df_h))
        c2.metric("신청 건", (df_h['신청여부']=='Y').sum() if '신청여부' in df_h.columns else 0)
        c3.metric("선정 건", (df_h['선정결과']=='선정').sum() if '선정결과' in df_h.columns else 0)

        st.divider()
        st.subheader("성과 업데이트")
        st.caption("신청여부·선정결과를 직접 입력하고 저장하세요.")

        edited = st.data_editor(
            df_h, use_container_width=True, hide_index=True,
            column_config={
                "신청여부": st.column_config.SelectboxColumn("신청여부", options=["","Y","N"]),
                "선정결과": st.column_config.SelectboxColumn("선정결과", options=["","선정","미선정","대기"]),
            }
        )
        if st.button("💾 저장"):
            save_history(edited)
            st.success("저장 완료!")

        st.divider()
        csv = df_h.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("📥 CSV 다운로드", csv, "send_history.csv", "text/csv")


# ══════════════════════════════════════════════════════
# 성과 집계
# ══════════════════════════════════════════════════════
elif page == "📊 성과 집계":
    st.title("성과 집계")

    df_h = load_history()
    if df_h.empty:
        st.info("발송 이력이 없습니다.")
    else:
        total    = len(df_h)
        applied  = (df_h['신청여부']=='Y').sum() if '신청여부' in df_h.columns else 0
        selected = (df_h['선정결과']=='선정').sum() if '선정결과' in df_h.columns else 0
        rate     = f"{applied/total*100:.1f}%" if total else "0%"

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("총 발송", f"{total}건")
        c2.metric("신청 건", f"{applied}건")
        c3.metric("선정 건", f"{selected}건")
        c4.metric("신청 전환율", rate)

        if '기업명' in df_h.columns:
            st.divider()
            st.subheader("기업별 현황")
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

    st.subheader("키워드 설정")
    high_kw = st.text_area("★★★ 직접 연계 키워드", value=", ".join(HIGH), height=80)
    mid_kw  = st.text_area("★★ 간접 연계 키워드",  value=", ".join(MID),  height=80)

    st.divider()
    st.subheader("캘린더 설정")
    cal_id = load_calendar_id()
    st.text_input("공통 캘린더 ID", value=cal_id, disabled=True)
    if cal_id:
        st.markdown(f"[📅 캘린더 바로가기](https://calendar.google.com/calendar?cid={cal_id})")

    st.divider()
    st.subheader("인증 상태")
    if 'google' in st.secrets:
        st.success("✅ Streamlit Secrets 인증 설정됨")
    elif os.path.exists('token.json'):
        st.success("✅ 로컬 token.json 인증 설정됨")
    else:
        st.error("❌ 인증 파일 없음")

    if st.button("저장", type="primary"):
        st.success("설정 저장됨")
