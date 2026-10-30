"""
원스톱 스케일업 — 공고 매칭 시스템 _UJH
"""
import streamlit as st
import pandas as pd
import requests
import re, os, json, io, subprocess
from datetime import datetime, timedelta
from google.auth.transport.requests import Request as GRequest

def install_playwright():
    """Chromium 설치 — 세션당 1회만 실행. (Streamlit Cloud는 sudo 불가 →
    시스템 라이브러리는 packages.txt로 사전 설치 필요)"""
    if st.session_state.get('_pw_ready'):
        return True, ""
    import pathlib
    # 이미 설치돼 있으면 스킵 (컨테이너 재시작 전까지 유지)
    cache = pathlib.Path.home() / ".cache" / "ms-playwright"
    if cache.exists() and any(cache.glob("chromium-*")):
        st.session_state['_pw_ready'] = True
        return True, ""
    try:
        r = subprocess.run(["playwright", "install", "chromium"],
                           capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            st.session_state['_pw_ready'] = True
            return True, ""
        return False, (r.stderr or r.stdout or "")[-500:]
    except FileNotFoundError:
        return False, "playwright 명령을 찾을 수 없습니다 (패키지 미설치)."
    except subprocess.TimeoutExpired:
        return False, "Chromium 설치 시간 초과(300초)."
    except Exception as e:
        return False, str(e)[:300]


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
    <div style="max-width:380px;margin:100px auto;text-align:center;">
      <div style="width:52px;height:52px;background:#0A1F15;
                  border:1px solid #A7F3D0;border-radius:14px;
                  display:flex;align-items:center;justify-content:center;
                  margin:0 auto 20px;font-size:24px;box-shadow:0 2px 8px rgba(16,185,129,0.15);">📢</div>
      <h2 style="color:#F0F0F0;font-size:22px;font-weight:700;margin:0 0 6px;
                 font-family:'Inter','Apple SD Gothic Neo',sans-serif;">원스톱 스케일업</h2>
      <p style="color:#888888;font-size:13px;margin:0 0 32px;
                font-family:'Inter','Apple SD Gothic Neo',sans-serif;">혁신제품지원센터 공고 매칭 시스템</p>
    </div>
    """, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        pw = st.text_input("비밀번호", type="password",
                           placeholder="비밀번호 입력", label_visibility="collapsed")
        if st.button("로그인", use_container_width=True, type="primary"):
            # 비밀번호로 역할이 갈린다. 실무자는 회차 운영에 필요한 화면만 본다.
            # 기능을 지운 게 아니라 메뉴에 안 올릴 뿐이고, 담당자는 전부 본다.
            admin_pw = st.secrets.get("password", "dbwlgns")
            staff_pw = st.secrets.get("password_staff", "")
            if pw == admin_pw:
                st.session_state["authenticated"] = True
                st.session_state["role"] = "admin"
                st.rerun()
            elif staff_pw and pw == staff_pw:
                st.session_state["authenticated"] = True
                st.session_state["role"] = "staff"
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다")
        # 배포본에서 비밀번호가 왜 안 맞는지 알아내는 유일한 창구.
        # 주소 끝에 ?diag=1 을 붙이면 '어떤 키가 들어와 있나'만 보여준다.
        # 값도 길이도 찍지 않는다 — 있다/없다 뿐이다. 공개 저장소이므로
        # 이 코드가 노출돼도 새로 드러나는 것이 없어야 한다.
        try:
            if st.query_params.get("diag") == "1":
                _keys = sorted(st.secrets.keys())
                st.caption("설정에 들어온 키: " + (", ".join(_keys) or "(없음)"))
                st.caption("password 있음: "
                           + ("예" if str(st.secrets.get("password", "")) else "아니오")
                           + " · password_staff 있음: "
                           + ("예" if str(st.secrets.get("password_staff", "")) else "아니오"))
        except Exception as _de:
            st.caption(f"설정을 읽지 못했습니다 — {type(_de).__name__}")
    return False

if not check_password():
    st.stop()

# ── 상수 ──────────────────────────────────────────────
DRIVE_FOLDER_ID  = "1iWGYjaoslqST45ggDlg-IPMLaUHCYmV_"
LOGO_URL = "https://raw.githubusercontent.com/onestopkipcc-web/scaleup-matching/main/logo.png"
# 공고 마감일을 모아두는 내부 운영용 캘린더.
# 기업에게는 구독 링크를 보내지 않는다 — 구독한 캘린더는 알림이 가지 않는다.
# 기업에게 가는 알림은 메일에 첨부하는 .ics 가 맡는다. build_ics 참고.
COMMON_CAL_ID = "9078a49950a47b46ddb3511040886f3a016b75ca17169ec1113e5692b7327375@group.calendar.google.com"

# 기업에게 보내는 캘린더 주소.
# 예전 주소는 /u/6 이 들어 있었다 — 담당자 브라우저의 7번째 구글 계정을 가리키는
# 주소라 받는 쪽에서는 열리지 않는다. 669통에 그대로 나갔다.
# render?cid= 형태가 '이 캘린더를 추가하시겠습니까?' 로 바로 뜨는 공개 주소다.
import urllib.parse as _up_cal
CALENDAR_LINK = ("https://calendar.google.com/calendar/render?cid="
                 + _up_cal.quote(COMMON_CAL_ID, safe=""))

# 클릭 추적 (Apps Script 웹앱) — 메일 링크를 이 URL 경유로 감싸 클릭을 기록
CLICK_TRACK_URL = "https://script.google.com/macros/s/AKfycbyqjB9JmN6BAHSjBHH7Okup4HJZ8l4ToI-6Y0icbSYWKQn8NJAMpjEcuR4pi0tSOpSH/exec"
CLICK_LOG_SHEET_ID = "1-gYegpHysgSvF1TgQB7Rfh3rs_tNfrE4NS3F1xLef0o"  # 클릭추적_로그 시트
MATCH_STATE_FILE = "match_state.json"  # 매칭 결과·AI판정·승인상태 자동 저장

def save_match_state(drive):
    """매칭 결과·AI판정·승인상태를 드라이브에 자동 저장 (재부팅 후 복원용)."""
    try:
        import json as _json
        payload = {
            'match_results': st.session_state.get('match_results', []),
            'ai_analysis':   st.session_state.get('ai_analysis', {}),
            'review_state':  st.session_state.get('review_state', {}),
            # 결정 출처는 review_state 와 같은 곳에 저장해야 한다.
            # 예전에는 save_review_state 에만 있었는데, ⚡ 일괄 분석은 save_ai_analysis 를,
            # 일괄 승인은 save_match_state 를 부르므로 출처가 드라이브에 올라가지 않았다.
            # 결과: 앱이 재시작되면 결정은 남고 출처만 사라졌다(10/13 회차 617건 중 592건 공백).
            'decision_src':  st.session_state.get('decision_src', {}),
            'round_id':      st.session_state.get('match_round_id', ''),
            'saved_at': datetime.today().strftime('%Y-%m-%d %H:%M'),
        }
        drive_upload(drive, MATCH_STATE_FILE,
                     _json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8'),
                     "application/json")
        return True
    except Exception:
        return False

def load_match_state(drive):
    """앱 시작 시 매칭 상태 자동 복원. 세션에 없을 때만 드라이브에서 로드."""
    if st.session_state.get('_match_state_loaded'):
        return
    try:
        saved = load_json(drive, MATCH_STATE_FILE)
        if saved:
            _rid = saved.get('round_id', '') or ''
            if _rid and not st.session_state.get('match_round_id'):
                st.session_state['match_round_id'] = _rid
            if not st.session_state.get('match_results'):
                st.session_state['match_results'] = saved.get('match_results', [])
            if not st.session_state.get('ai_analysis'):
                st.session_state['ai_analysis'] = saved.get('ai_analysis', {})
            if not st.session_state.get('review_state'):
                _rv = saved.get('review_state', {}) or {}
                # 회차 정보가 없는 구버전 저장본이면 승인(○)은 되살리지 않는다
                _rv = _rv if _rid else carry_over_reject(_rv)
                st.session_state['review_state'] = _rv
                # 출처도 같이 되살린다 — 남아 있는 결정의 키만
                _sr = saved.get('decision_src', {}) or {}
                st.session_state['decision_src'] = {k: v for k, v in _sr.items() if k in _rv}
        st.session_state['_match_state_loaded'] = True
    except Exception:
        st.session_state['_match_state_loaded'] = True

# ── 매칭 회차 ─────────────────────────────────────────
# 승인(○)·제외(✕)는 그 회차 안에서만 유효하다. 재매칭하면 승인은 반드시 비워지고,
# 제외만 옵션에 따라 이월된다. 키 포맷(기업명_공고ID)은 ai_analysis와 공유하므로
# 건드리지 않고, 저장 파일에 회차 ID를 함께 기록해 회차를 판정한다.
REVIEW_FILE = "review_state.json"

def new_round_id():
    """매칭 회차 ID — 매칭을 실행할 때마다 새로 발급한다."""
    return datetime.today().strftime('%Y%m%d-%H%M')

def current_round_id():
    return st.session_state.get('match_round_id', '')

def keep_reject_opt():
    """지난 회차 제외(✕) 이월 옵션 — 기본 켜짐."""
    return bool(st.session_state.get('round_keep_reject', True))

def carry_over_reject(prev_state, keep_reject=None):
    """새 회차의 시작 상태를 만든다. 승인(○)은 절대 이월하지 않는다."""
    if keep_reject is None:
        keep_reject = keep_reject_opt()
    if not keep_reject:
        return {}
    return {k: v for k, v in (prev_state or {}).items() if v == '✕'}

def save_review_state(drive, state=None, round_id=None):
    """검토 상태를 회차 ID와 함께 드라이브에 저장."""
    try:
        import json as _j
        payload = {
            'round_id':     current_round_id() if round_id is None else round_id,
            'review_state': st.session_state.get('review_state', {}) if state is None else state,
            'decision_src': st.session_state.get('decision_src', {}),
            'saved_at':     datetime.today().strftime('%Y-%m-%d %H:%M'),
        }
        drive_upload(drive, REVIEW_FILE,
                     _j.dumps(payload, ensure_ascii=False).encode('utf-8'),
                     "application/json")
        return True
    except Exception:
        return False

def load_review_state(drive, round_id=None, keep_reject=None):
    """드라이브의 검토 상태를 현재 회차 기준으로 읽는다.
    회차가 다르거나 회차 정보가 없는 구버전 파일이면 승인(○)은 버린다.
    반환: (state, saved_round, saved_at, is_same_round)"""
    saved       = load_json(drive, REVIEW_FILE) or {}
    state       = saved.get('review_state', {}) or {}
    saved_round = saved.get('round_id', '') or ''
    saved_at    = saved.get('saved_at', '') or ''
    cur  = current_round_id() if round_id is None else round_id
    same = bool(saved_round) and bool(cur) and saved_round == cur
    if not same:
        state = carry_over_reject(state, keep_reject)
    # 결정 출처도 함께 복원 — 남아 있는 상태의 키만 (회차 규칙은 review_state와 동일)
    _srcs = saved.get('decision_src', {}) or {}
    st.session_state['decision_src'] = {k: v for k, v in _srcs.items() if k in state}
    return state, saved_round, saved_at, same

def set_decision(key, value, source):
    """승인(○)·제외(✕)를 찍으면서 그 결정이 어디서 나왔는지 함께 남긴다.
    source: 'AI 자동 승인' / 'AI 자동 제외' / '담당자' / '🟡 자동 보완'
    담당자가 AI 자동 결정을 뒤집으면 출처가 '담당자'로 덮어써진다 —
    AI 판단과 사람 결정이 갈린 지점이 판단 기록에 그대로 남는다."""
    if 'review_state' not in st.session_state:
        st.session_state['review_state'] = {}
    if 'decision_src' not in st.session_state:
        st.session_state['decision_src'] = {}
    st.session_state['review_state'][key] = value
    if value in ('○', '✕'):
        st.session_state['decision_src'][key] = source
    else:
        st.session_state['decision_src'].pop(key, None)

# ── 발송 진행 기록 ────────────────────────────────────
# 기업 한 곳의 Gmail 발송이 성공하면 즉시 여기에 기록한다. 발송이 중간에 멈춰도
# 재실행 시 이 기록을 보고 이미 보낸 기업을 건너뛴다.
# send_history.xlsx는 구조·기존 기록을 그대로 두고, pending을 모아 반영한다
# (셀마다 서식을 입히는 save_excel을 기업마다 돌리면 너무 느리기 때문).
SEND_PROGRESS_FILE  = "send_progress.json"
HISTORY_FLUSH_EVERY = 10   # 이 개수만큼 발송할 때마다 엑셀 중간 저장

def send_round_id():
    """발송 회차 ID — 매칭 회차를 그대로 쓴다. 발송이 중단돼도 매칭 회차는
    그대로라 재실행 시 같은 회차로 이어진다."""
    _r = current_round_id()
    if _r:
        return _r
    if not st.session_state.get('_fallback_send_round'):
        st.session_state['_fallback_send_round'] = new_round_id()
    return st.session_state['_fallback_send_round']

def load_send_progress(drive, round_id):
    """현재 발송 회차의 진행 기록. 회차가 다르면 빈 기록으로 시작한다."""
    d = load_json(drive, SEND_PROGRESS_FILE) or {}
    if d.get('round_id') != round_id:
        return {'round_id': round_id, 'sent': {}, 'pending': []}
    d.setdefault('sent', {})
    d.setdefault('pending', [])
    d['round_id'] = round_id
    return d

def save_send_progress(drive, prog):
    """진행 기록 즉시 저장. False를 돌려주면 호출부는 발송을 중단해야 한다."""
    try:
        import json as _j
        prog['saved_at'] = datetime.today().strftime('%Y-%m-%d %H:%M:%S')
        return bool(drive_upload(drive, SEND_PROGRESS_FILE,
                                 _j.dumps(prog, ensure_ascii=False).encode('utf-8'),
                                 "application/json"))
    except Exception:
        return False

def flush_send_history(drive, prog):
    """pending을 send_history.xlsx에 합쳐 저장하고 비운다.
    엑셀의 컬럼 구조와 기존 기록은 그대로 둔다. 반환: (ok, 반영건수)"""
    rows = prog.get('pending', [])
    if not rows:
        return True, 0
    try:
        df_h   = load_excel(drive, HISTORY_FILE)
        df_new = pd.DataFrame(rows)
        df_fin = pd.concat([df_h, df_new], ignore_index=True) if not df_h.empty else df_new
        if not save_excel(drive, df_fin, HISTORY_FILE, "발송이력", "375623"):
            return False, 0
        prog['pending'] = []
        return True, len(rows)
    except Exception:
        return False, 0

# ── 회차별 판단 기록 ──────────────────────────────────
# 규칙 점수·AI 판정·최종 결정(과 그 출처)·발송·클릭·반응을 기업-공고 짝마다 한 줄로
# 남긴다. 나중에 규칙과 AI 판단이 실제로 맞았는지 되짚는 데이터.
# 기록 실패가 발송이나 저장 흐름을 막으면 안 되므로 전부 예외를 삼킨다.
DECISION_LOG_FILE = "decision_log.json"

# 발송이 끝난 회차의 매칭·AI판정·승인 상태를 통째로 남긴다.
# 발송 뒤에는 match_results 가 비워져서, 메일 모양을 한 번 확인하려 해도 수집·매칭·
# AI 분석을 처음부터 다시 돌려야 했다. 스냅샷이 있으면 비용 0으로 실제 데이터 그대로
# 미리보기·테스트 발송을 할 수 있다.
ROUND_SNAPSHOT_FILE = "round_snapshot.json"


def save_round_snapshot(drive, round_id):
    """발송 직후 호출. 실패해도 발송 흐름을 막지 않는다."""
    try:
        import json as _j
        payload = {
            'round_id':      round_id or '',
            'saved_at':      datetime.today().strftime('%Y-%m-%d %H:%M'),
            'match_results': st.session_state.get('match_results', []),
            'ai_analysis':   st.session_state.get('ai_analysis', {}),
            'review_state':  st.session_state.get('review_state', {}),
            'ref_notices':   st.session_state.get('_ref_notices_by_co', {}),
        }
        if not payload['match_results']:
            return False
        return bool(drive_upload(
            drive, ROUND_SNAPSHOT_FILE,
            _j.dumps(payload, ensure_ascii=False, default=str).encode('utf-8'),
            "application/json"))
    except Exception:
        return False


def load_round_snapshot(drive):
    """{'round_id','saved_at','match_results','ai_analysis','review_state','ref_notices'}"""
    try:
        return load_json(drive, ROUND_SNAPSHOT_FILE) or {}
    except Exception:
        return {}


def snapshot_buckets(snap):
    """스냅샷의 기업을 '메일에 실릴 맞춤 공고 수'로 묶는다.

    메일 모양이 가장 크게 갈리는 지점이라 이 세 가지만 보면 레이아웃 확인이 끝난다.
    HTML을 다 만들지 않고 관문만 통과시켜 세므로 가볍다."""
    res = snap.get('match_results', []) or []
    ai  = snap.get('ai_analysis', {}) or {}
    rv  = snap.get('review_state', {}) or {}
    cnt = {}
    for r in res:
        co = str(r.get('기업명', '') or '').strip()
        if not co:
            continue
        cnt.setdefault(co, 0)
        if can_include_notice(r, co, ai, rv)[0] and rv.get(
                f"{co}_{r.get('공고ID','')}", '') == '○':
            cnt[co] += 1
    out = {'맞춤 0건': [], '1~2건': [], '3건 이상': []}
    for co, c in sorted(cnt.items()):
        out['맞춤 0건' if c == 0 else ('1~2건' if c <= 2 else '3건 이상')].append(co)
    return out


def send_test_mail(to_list, company, html, meta):
    """테스트 메일 발송 — 실제 발송과 같은 발신자·제목 규칙을 쓴다."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.header import Header
    from email.utils import formataddr
    import base64 as _b64
    sent = 0
    for to in to_list:
        msg = MIMEMultipart('alternative')
        msg['From'] = formataddr((str(Header(MAIL_FROM_NAME, 'utf-8')), MAIL_FROM_ADDR))
        msg['To'] = to
        msg['Subject'] = Header("[TEST] " + mail_subject(company, meta), 'utf-8')
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        gmail_send(_b64.urlsafe_b64encode(msg.as_bytes()).decode())
        sent += 1
    return sent

def _ai_cache_version(res):
    """AI 판정 캐시 버전 — 판정 내용의 해시 앞 8자리.
    ai_analysis에 버전 필드가 없어서, 같은 판정이면 같은 값이 나오도록 만든다.
    🔁 재분석으로 내용이 바뀌면 값도 바뀐다. 미분석·오류면 빈 문자열."""
    if not isinstance(res, dict) or not res or res.get('error'):
        return ''
    try:
        import hashlib as _hl, json as _j
        _payload = {k: v for k, v in res.items() if not str(k).startswith('_')}
        return _hl.md5(_j.dumps(_payload, ensure_ascii=False, sort_keys=True)
                       .encode('utf-8')).hexdigest()[:8]
    except Exception:
        return ''

def build_click_map(df_click):
    """클릭 로그 → {(기업명, 공고ID 또는 공고명): {'count', 'last'}}.
    공고ID 컬럼이 없는 시트를 위해 공고명으로도 같이 색인한다."""
    out = {}
    try:
        if df_click is None or df_click.empty:
            return out
        cols = list(df_click.columns)
        def pick(*keys):
            for c in cols:
                if any(k in str(c).lower() for k in keys):
                    return c
            return None
        co_col = pick('기업', 'co')
        id_col = pick('공고id', 'notice', 'pblanc')
        nm_col = pick('공고명', 'name')
        tm_col = pick('시각', '시간', 'time', 'date') or cols[0]
        if not co_col:
            return out
        for _, r in df_click.iterrows():
            co = str(r.get(co_col, '') or '').strip()
            if not co:
                continue
            _t = str(r.get(tm_col, '') or '')
            for _c in (id_col, nm_col):
                if not _c:
                    continue
                v = str(r.get(_c, '') or '').strip()
                if not v:
                    continue
                e = out.setdefault((co, v), {'count': 0, 'last': ''})
                e['count'] += 1
                if _t > e['last']:
                    e['last'] = _t
    except Exception:
        pass
    return out

def _ts(v):
    """'2026-09-30 9:43:02' 처럼 한 자리 시(時)가 섞인 값도 비교 가능하게 만든다.
    문자열끼리 비교하면 '9:43' > '07:33' 이 되어 같은 날짜에서 순서가 뒤집힌다."""
    m = re.search(r'(\d{4})\D(\d{1,2})\D(\d{1,2})(?:\D+(\d{1,2})\D(\d{1,2})(?:\D(\d{1,2}))?)?',
                  str(v or ''))
    if not m:
        return None
    g = [int(x) if x else 0 for x in m.groups()]
    return tuple(g)


def reattach_clicks(rows, df_click):
    """판단 기록 전체(모든 회차)의 클릭 칸을 다시 계산한다.

    클릭 로그에는 회차가 없다. 같은 공고가 회차마다 다시 매칭되므로 (기업,공고)로만
    맞추면 과거 클릭이 최신 회차로 빨려간다 — 실제로 9/29 회차가 자기 클릭을 0건으로
    적고, 아직 발송도 안 한 10/13 회차에 10건이 찍혀 있었다.
    그래서 클릭 한 건을 '그 시각 이전의 가장 최근 발송'에 귀속시킨다.
    귀속할 발송이 없는 클릭(판단 기록에 없는 과거 회차 분)은 버린다 — 어느 회차의
    성과인지 알 수 없는 것을 아무 회차에나 얹지 않는다.

    발송하지 않은 행의 클릭 칸은 비운다. save_decision_log 가 매번 전체에 적용하므로
    나중에 도착한 클릭도 제 회차로 들어간다(과거 회차가 냉동되지 않는다).
    """
    rows = list(rows or [])
    if df_click is None or getattr(df_click, 'empty', True):
        return rows
    # ① 발송 색인 — (기업, 공고ID) 와 (기업, 공고명) 두 갈래로 만든다
    sent = {}
    for r in rows:
        if str(r.get('발송여부', '')) not in ('Y', '참고'):
            continue
        at = _ts(r.get('발송시각', ''))
        if not at:
            continue
        co = str(r.get('기업명', '') or '').strip()
        for v in (str(r.get('공고ID', '') or '').strip(),
                  str(r.get('공고명', '') or '').strip()):
            if v:
                sent.setdefault((co, v), []).append((at, str(r.get('회차ID', ''))))
    # ② 클릭 한 건씩 '직전 발송'에 귀속
    tally, dropped = {}, 0
    try:
        cols = list(df_click.columns)

        def pick(*keys):
            for c in cols:
                if any(k in str(c).lower() for k in keys):
                    return c
            return None

        co_col = pick('기업', 'co')
        id_col = pick('공고id', 'notice', 'pblanc')
        nm_col = pick('공고명', 'name')
        tm_col = pick('시각', '시간', 'time', 'date') or cols[0]
        if not co_col:
            return rows
        for _, cr in df_click.iterrows():
            co = str(cr.get(co_col, '') or '').strip()
            ct = _ts(cr.get(tm_col, ''))
            if not co or not ct:
                continue
            if id_col and str(cr.get(id_col, '') or '').strip() == OPEN_MARK:
                continue          # 오픈 추적 행 — 클릭이 아니다
            cand = []
            for _c in (id_col, nm_col):
                if not _c:
                    continue
                v = str(cr.get(_c, '') or '').strip()
                if v:
                    cand += sent.get((co, v), [])
            past = [(at, rid) for at, rid in cand if at <= ct]
            if not past:
                dropped += 1
                continue
            _, rid = max(past)
            pid = str(cr.get(id_col, '') or '').strip() if id_col else ''
            nm = str(cr.get(nm_col, '') or '').strip() if nm_col else ''
            e = tally.setdefault((rid, co, pid, nm), {'count': 0, 'last': ''})
            e['count'] += 1
            raw = str(cr.get(tm_col, '') or '')
            if _ts(raw) and (not e['last'] or _ts(raw) > _ts(e['last'])):
                e['last'] = raw
    except Exception:
        return rows
    # ③ 행에 되쓰기 — 발송한 행에만 값이 들어간다
    for r in rows:
        if str(r.get('발송여부', '')) not in ('Y', '참고'):
            r['클릭여부'], r['클릭시각'], r['클릭수'] = '', '', ''
            continue
        rid = str(r.get('회차ID', ''))
        co = str(r.get('기업명', '') or '').strip()
        hit = (tally.get((rid, co, str(r.get('공고ID', '') or '').strip(),
                          str(r.get('공고명', '') or '').strip())) or {})
        r['클릭여부'] = 'Y' if hit.get('count') else 'N'
        r['클릭시각'] = hit.get('last', '')
        r['클릭수'] = hit.get('count', 0) or ''
    if dropped:
        print(f"  (귀속할 발송 기록이 없어 제외된 클릭 {dropped}건)")
    return rows


def backfill_decision_src(rows):
    """출처가 비어 있는 행을 AI 판정으로 되짚어 채운다.

    v0929-23 이전에는 decision_src 가 save_match_state 경로로 저장되지 않아 앱이
    재시작되면 사라졌다. 10/13 회차는 결정 617건 중 592건이 공백이었다.
    결정과 AI 판정이 맞아떨어지면 자동 처리로 보고 '(추정)'을 붙인다 — 실제 기록과
    구분되게 둔다. 같은 회차 검증: 제외 537 ≡ AI비추천 537, 승인 55 ≡ AI추천 55,
    규칙에서 벗어난 결정 0건이었으므로 이 되짚기는 추측이 아니라 확정에 가깝다.
    맞아떨어지지 않는 건(담당자가 뒤집었거나 🟡 자동 보완) 은 구분이 불가능하므로
    '기록 없음'으로 남겨 솔직히 표시한다."""
    for r in (rows or []):
        if r.get('결정출처'):
            continue
        dec = r.get('최종결정', '')
        if dec not in ('승인', '제외'):
            continue
        rec = r.get('AI추천여부', '')
        if dec == '승인' and rec == '추천':
            r['결정출처'] = 'AI 자동 승인(추정)'
        elif dec == '제외' and rec == '비추천':
            r['결정출처'] = 'AI 자동 제외(추정)'
        else:
            r['결정출처'] = '기록 없음'
    return rows


def reattach_opens(rows, df_click):
    """오픈 추적 행(OPEN_MARK)을 읽어 회차·기업별 열람 여부를 행에 적는다.

    메일 한 통에 픽셀 하나라 '기업이 그 회차 메일을 열었는가'까지만 알 수 있다.
    공고별 구분은 안 되므로 같은 기업·회차의 모든 행에 같은 값이 들어간다.
    픽셀 URL에 회차 ID를 실어 보내므로 공고명 칸에서 바로 회차를 읽는다."""
    rows = list(rows or [])
    if df_click is None or getattr(df_click, 'empty', True):
        return rows
    try:
        cols = list(df_click.columns)

        def pick(*keys):
            for c in cols:
                if any(k in str(c).lower() for k in keys):
                    return c
            return None

        co_col = pick('기업', 'co')
        id_col = pick('공고id', 'notice', 'pblanc')
        nm_col = pick('공고명', 'name')
        tm_col = pick('시각', '시간', 'time', 'date') or cols[0]
        if not (co_col and id_col):
            return rows
        # 회차별 발송 시각 — 회차 ID가 비어 온 옛 행을 시각으로 귀속할 때 쓴다
        sent = {}
        for r in rows:
            if str(r.get('발송여부', '')) in ('Y', '참고'):
                at = _ts(r.get('발송시각', ''))
                if at:
                    sent.setdefault(str(r.get('기업명', '') or '').strip(), []).append(
                        (at, str(r.get('회차ID', ''))))
        opens = {}
        for _, cr in df_click.iterrows():
            if str(cr.get(id_col, '') or '').strip() != OPEN_MARK:
                continue
            co = str(cr.get(co_col, '') or '').strip()
            ot = _ts(cr.get(tm_col, ''))
            if not co or not ot:
                continue
            rid = str(cr.get(nm_col, '') or '').strip() if nm_col else ''
            if not rid:
                past = [(at, r) for at, r in sent.get(co, []) if at <= ot]
                if not past:
                    continue
                rid = max(past)[1]
            e = opens.setdefault((rid, co), {'count': 0, 'first': ''})
            e['count'] += 1
            raw = str(cr.get(tm_col, '') or '')
            if not e['first'] or _ts(raw) < _ts(e['first']):
                e['first'] = raw      # 첫 열람 시각이 '언제 읽었나'에 더 쓸모 있다
    except Exception:
        return rows
    for r in rows:
        if str(r.get('발송여부', '')) not in ('Y', '참고'):
            r['오픈여부'], r['오픈시각'] = '', ''
            continue
        hit = opens.get((str(r.get('회차ID', '')), str(r.get('기업명', '') or '').strip())) or {}
        r['오픈여부'] = 'Y' if hit.get('count') else 'N'
        r['오픈시각'] = hit.get('first', '')
    return rows


def collect_reactions(days=90, max_results=200):
    """메일 하단 반응 버튼의 회신을 Gmail에서 모은다 → {기업명: {'value','at'}}.
    반응 링크가 mailto라 클릭 자체는 추적되지 않고 회신이 와야 알 수 있다.
    버튼이 메일당 하나라 공고별 구분은 되지 않는다 — 기업 단위 값이다."""
    out = {}
    try:
        import base64 as _b64
        after = (datetime.today() - timedelta(days=int(days))).strftime('%Y/%m/%d')
        resp = gapi('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/messages',
                    params={'q': f'subject:"[원스톱 피드백]" after:{after}',
                            'maxResults': max_results})
        if not resp.ok:
            return out
        def _body(p):
            if p.get('body', {}).get('data'):
                return _b64.urlsafe_b64decode(p['body']['data'] + '==').decode('utf-8', errors='ignore')
            for part in p.get('parts', []):
                r = _body(part)
                if r:
                    return r
            return ''
        for ref in resp.json().get('messages', []):
            try:
                d = gapi('GET',
                         f'https://gmail.googleapis.com/gmail/v1/users/me/messages/{ref["id"]}',
                         params={'format': 'full'}).json()
                hs   = d.get('payload', {}).get('headers', [])
                subj = next((h['value'] for h in hs if h['name'] == 'Subject'), '')
                m    = re.search(r'\[원스톱 피드백\]\s*(.+?)\s*$', subj.strip())
                co   = m.group(1).strip() if m else ''
                if not co:
                    continue
                txt = _body(d.get('payload', {}))[:3000]
                mv  = re.search(r'반응\s*:\s*(도움됐어요|별로였어요)', txt)
                at  = ''
                if d.get('internalDate'):
                    at = datetime.fromtimestamp(int(d['internalDate']) / 1000).strftime('%Y-%m-%d %H:%M')
                prev = out.get(co)
                if not prev or at > prev.get('at', ''):
                    out[co] = {'value': mv.group(1) if mv else '의견 회신', 'at': at}
            except Exception:
                continue
    except Exception:
        pass
    return out

def round_stats(rows):
    """판단 기록 → 회차별 성과 요약 (오래된 회차부터).

    대시보드가 수기 타임라인 대신 보여줄 수치. 발송한 행만 분모로 쓴다 —
    보내지도 않은 공고를 클릭률 분모에 넣으면 숫자가 의미를 잃는다."""
    from collections import defaultdict
    by = defaultdict(list)
    for r in (rows or []):
        if str(r.get('발송여부', '')) in ('Y', '참고'):
            by[str(r.get('회차ID', ''))].append(r)
    out = []
    for rid in sorted(by):
        g = by[rid]
        cos = {}
        for r in g:
            co = str(r.get('기업명', '') or '')
            e = cos.setdefault(co, {'click': False, 'open': False})
            e['click'] = e['click'] or r.get('클릭여부') == 'Y'
            e['open'] = e['open'] or r.get('오픈여부') == 'Y'
        _n_co = len(cos) or 1
        _main = [r for r in g if r.get('발송여부') == 'Y']
        _ref = [r for r in g if r.get('발송여부') == '참고']
        out.append({
            '회차ID': rid,
            '발송일': str(next((r.get('발송시각', '') for r in g if r.get('발송시각')), ''))[:10],
            '발송기업': len(cos), '발송공고': len(g),
            '클릭기업': sum(1 for v in cos.values() if v['click']),
            '열람기업': sum(1 for v in cos.values() if v['open']),
            '클릭기업비율': sum(1 for v in cos.values() if v['click']) / _n_co * 100,
            '열람기업비율': sum(1 for v in cos.values() if v['open']) / _n_co * 100,
            '공고클릭률': sum(1 for r in g if r.get('클릭여부') == 'Y') / (len(g) or 1) * 100,
            '본공고클릭률': (sum(1 for r in _main if r.get('클릭여부') == 'Y')
                        / (len(_main) or 1) * 100) if _main else 0.0,
            '참고클릭률': (sum(1 for r in _ref if r.get('클릭여부') == 'Y')
                       / (len(_ref) or 1) * 100) if _ref else 0.0,
        })
    return out


def silent_companies(rows, last_n=3, min_age_days=2):
    """최근 last_n 회차 동안 한 번도 클릭하지 않은 기업 → 연락 대상.

    메일을 고쳐서 풀릴 문제가 아닐 수 있다(담당자 변경·주소 오류·스팸함).
    전화 한 통이 빠른 쪽을 골라내려는 목록이다.

    보낸 지 min_age_days 가 안 된 회차는 뺀다. 클릭은 발송 당일 오후와 다음 날
    오전에 몰리는데, 갓 보낸 회차를 넣으면 아직 열어보지도 않은 기업이 '무반응'으로
    잡혀 엉뚱한 곳에 전화하게 된다."""
    from datetime import date as _date
    stats = round_stats(rows)
    _today = _date.today()

    def _old_enough(s):
        try:
            y, m, d = (int(x) for x in str(s.get('발송일', ''))[:10].split('-'))
            return (_today - _date(y, m, d)).days >= int(min_age_days)
        except Exception:
            return True          # 발송일을 모르면 그냥 포함한다
    stats = [x for x in stats if _old_enough(x)]
    rids = [s['회차ID'] for s in stats][-int(last_n):]
    if not rids:
        return []
    sent, clicked = {}, set()
    for r in (rows or []):
        if str(r.get('회차ID', '')) not in rids:
            continue
        if str(r.get('발송여부', '')) not in ('Y', '참고'):
            continue
        co = str(r.get('기업명', '') or '')
        sent[co] = sent.get(co, 0) + 1
        if r.get('클릭여부') == 'Y':
            clicked.add(co)
    return sorted(co for co in sent if co not in clicked)


def build_decision_rows(round_id, results, ai_cache, review_state, decision_src,
                        sent_map=None, click_map=None, reaction_map=None):
    """이번 회차의 판단 기록 행 (기업-공고 짝마다 1행)."""
    rows = []
    _stat = {'○': '승인', '✕': '제외'}
    _now  = datetime.today().strftime('%Y-%m-%d %H:%M')
    sent_map     = sent_map or {}
    click_map    = click_map or {}
    reaction_map = reaction_map or {}
    for r in (results or []):
        co  = str(r.get('기업명', '') or '').strip()
        pid = str(r.get('공고ID', '') or '').strip()
        if not co or not pid:
            continue
        key = f"{co}_{pid}"
        ai  = (ai_cache or {}).get(key, {}) or {}
        if not isinstance(ai, dict) or ai.get('error'):
            ai = {}
        dec  = (review_state or {}).get(key, '')
        _s   = sent_map.get(co) or {}
        if not _s:
            _sent = ''
        elif pid in (_s.get('pids') or []):
            _sent = 'Y'
        elif pid in (_s.get('ref_pids') or []):
            _sent = '참고'
        else:
            _sent = 'N'
        _nm  = str(r.get('공고명', '') or '')
        _ck  = click_map.get((co, pid)) or click_map.get((co, _nm)) or {}
        _rx  = reaction_map.get(co) or {}
        rows.append({
            '회차ID': round_id, '기업명': co, '공고ID': pid, '공고명': _nm,
            '규칙점수': r.get('점수', ''), '등급': r.get('관련도', ''),
            'AI추천여부': ai.get('추천여부', ''), 'AI적합도': ai.get('적합도', ''),
            'AI업종일치': ai.get('업종일치', ''), 'AI자격충족': ai.get('자격충족', ''),
            'AI지역적합': ai.get('지역적합', ''), 'AI수요일치': ai.get('수요일치', ''),
            'AI캐시버전': _ai_cache_version(ai),
            'AI전문반영': ('Y' if ai.get('_전문반영') else 'N') if ai else '',
            '최종결정': _stat.get(dec, '미결정'),
            '결정출처': (decision_src or {}).get(key, '') if dec in ('○', '✕') else '',
            '발송여부': _sent, '발송시각': _s.get('at', ''),
            # 발송하지 않은 회차에는 클릭을 적지 않는다. 클릭 로그에 회차가 없어
            # 예전에는 '아직 보내지도 않은 공고'에 Y가 찍혔다.
            # 회차별 정확한 귀속은 reattach_clicks() 가 저장 직전에 다시 계산한다.
            '클릭여부': ('Y' if _ck.get('count') else 'N') if _sent in ('Y', '참고') else '',
            '클릭시각': _ck.get('last', '') if _sent in ('Y', '참고') else '',
            '클릭수': (_ck.get('count', 0) or '') if _sent in ('Y', '참고') else '',
            # 오픈은 reattach_opens() 가 저장 직전에 채운다 (메일 단위라 공고별 구분 불가)
            '오픈여부': '', '오픈시각': '',
            '반응버튼': _rx.get('value', ''), '반응시각': _rx.get('at', ''),
            '기록시각': _now,
        })
    return rows

def load_decision_log(drive):
    """누적 판단 기록 전체."""
    try:
        d = load_json(drive, DECISION_LOG_FILE) or {}
        return d.get('rows', []) if isinstance(d, dict) else list(d or [])
    except Exception:
        return []

def save_decision_log(drive, rows, round_id, df_click=None):
    """이번 회차 행을 통째로 교체하고 다른 회차 행은 그대로 둔다.
    담당자가 ○/✕를 바꾸면 다음 기록 때 최종 결정·출처가 자동 갱신된다.

    df_click 이 있으면 저장 직전에 '모든 회차'의 클릭 칸을 다시 계산한다.
    과거 회차 행을 그대로 두기만 하면 발송 뒤에 도착한 클릭이 영영 반영되지 않는다."""
    try:
        import json as _j
        keep = [r for r in load_decision_log(drive) if r.get('회차ID') != round_id]
        allr = backfill_decision_src(
            reattach_opens(reattach_clicks(keep + list(rows or []), df_click), df_click))
        if not allr:
            return False, 0
        ok = drive_upload(drive, DECISION_LOG_FILE,
                          _j.dumps({'rows': allr,
                                    'saved_at': datetime.today().strftime('%Y-%m-%d %H:%M')},
                                   ensure_ascii=False).encode('utf-8'),
                          "application/json")
        return bool(ok), len(allr)
    except Exception:
        return False, 0

def record_decision_log(drive, round_id=None, sent_map=None,
                        click_map=None, reaction_map=None, df_click=None):
    """현재 세션 상태로 이번 회차 판단 기록을 갱신한다.
    예외를 절대 밖으로 내보내지 않는다 — 기록 실패가 발송을 막으면 안 된다."""
    try:
        rid = round_id or current_round_id()
        if not rid:
            return False, 0
        rows = build_decision_rows(
            rid,
            st.session_state.get('match_results', []),
            st.session_state.get('ai_analysis', {}),
            st.session_state.get('review_state', {}),
            st.session_state.get('decision_src', {}),
            sent_map, click_map, reaction_map)
        st.session_state.pop('_declog_cache', None)
        # 이번 회차 매칭 결과가 비어 있어도(발송 뒤 상태 초기화 등) 그냥 끝내면 안 된다.
        # '🔄 갱신'의 주 목적은 과거 회차의 클릭 재귀속과 빈 출처 되짚기이기 때문이다.
        # rows 가 비면 save_decision_log 가 기존 기록만 손질해 다시 올린다.
        return save_decision_log(drive, rows, rid, df_click)
    except Exception:
        return False, 0

def track_link(dest_url, company, notice_id, notice_name):
    """공고 링크를 클릭 추적 URL로 감싼다. dest_url이 없으면 원본 그대로."""
    import urllib.parse as _up
    if not dest_url or dest_url == "#" or not CLICK_TRACK_URL:
        return dest_url or "#"
    q = _up.urlencode({
        "co": company or "", "notice": notice_id or "",
        "name": (notice_name or "")[:80], "url": dest_url,
    })
    return f"{CLICK_TRACK_URL}?{q}"

def build_aug_edu_html(company="", co_kw="", co_area="", co_type="",
                       deadline="2026-08-07", is_reminder=True):
    """8월 교육 신청 안내/리마인더 메일 HTML.
    is_reminder=True면 마감 임박 톤, D-day 자동계산, 기업 키워드 카드 포함."""
    from datetime import datetime as _dt, date as _date
    _dl_short = "8/7(금)"
    try:
        _dl = _dt.strptime(deadline, "%Y-%m-%d").date()
        _days = (_dl - _date.today()).days  # 시각 무시, 날짜 차이만
        _dday_txt = "마감" if _days < 0 else ("D-DAY" if _days == 0 else f"D-{_days}")
        _wd = ['월','화','수','목','금','토','일'][_dl.weekday()]
        _dl_short = f"{_dl.month}/{_dl.day}({_wd})"
    except Exception:
        _dday_txt = ""

    _curr = [
        ("1. 키워드 발굴 및 분석", "고객이 실제로 검색하는 키워드 추출 · 검색량 해석 · 블루오션 선점"),
        ("2. 트렌드 분석", "네이버 데이터랩 · 구글 트렌드 · 경쟁사 동향 모니터링"),
        ("3. 플레이스 로직 분석", "스마트플레이스 순위 요인 · 세팅 최적화 · 리뷰 관리"),
        ("4. 블로그 포스팅 전략", "상위 노출 콘텐츠 구조 · 체류시간 확보 · 어뷰징 방지"),
    ]
    _curr_html = ""
    for _t, _d in _curr:
        _curr_html += f"""
      <div style="margin-bottom:10px;padding:14px 16px;background:#FAFBFC;border:1px solid #E8ECF1;border-left:4px solid #03C75A;border-radius:0 8px 8px 0;">
        <p style="margin:0 0 3px;font-size:14px;font-weight:600;color:#1C2B3A;">{_t}</p>
        <p style="margin:0;font-size:12px;color:#5A6675;line-height:1.6;">{_d}</p>
      </div>"""

    _kw_card = ""
    if co_kw or co_area or co_type:
        _kw_card = f"""
      <div style="margin-top:20px;padding-top:18px;border-top:1px dashed #D8DEE6;">
        <p style="margin:0 0 8px;font-size:11px;font-weight:600;color:#8A96A3;letter-spacing:1px;">📋 저희가 파악한 귀사 정보</p>
        <div style="background:#F7F9FC;border:1px solid #E4EAF1;border-radius:8px;padding:12px 14px;">
          <p style="margin:0 0 4px;font-size:12px;color:#5A6675;">기술키워드 · <span style="font-weight:600;color:#1C2B3A;">{co_kw or '—'}</span></p>
          <p style="margin:0 0 4px;font-size:12px;color:#5A6675;">관심분야 · <span style="font-weight:600;color:#1C2B3A;">{co_area or '—'}</span></p>
          <p style="margin:0 0 8px;font-size:12px;color:#5A6675;">기업유형 · <span style="font-weight:600;color:#1C2B3A;">{co_type or '—'}</span></p>
          <p style="margin:0;font-size:11px;color:#6B7684;line-height:1.6;">이 정보가 다르거나 보완하고 싶으시면 신청 회신에 함께 적어주세요.</p>
        </div>
      </div>"""

    _greeting = ("앞서 안내드린 8월 교육 <b>신청 마감이 다가와</b> 다시 안내드립니다. "
                 "아직 신청하지 않으셨다면, 마감 전에 꼭 참여 신청해 주세요."
                 if is_reminder else
                 "원스톱 스케일업 8월 교육을 안내드립니다. 검색 노출과 온라인 유입에 초점을 맞춰, "
                 "우리 회사를 검색 상위에 올리는 실전 노하우를 다룹니다.")
    _sub_label = "8월 무료 교육 · 신청 마감 임박" if is_reminder else "8월 무료 교육"

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F2F4F7;font-family:'Apple SD Gothic Neo',Arial,sans-serif;">
<div style="max-width:600px;margin:0 auto;background:#F2F4F7;border-radius:14px;overflow:hidden;border:1px solid #E2E5EA;">
  <div style="background:#0F1D2E;padding:26px 28px 24px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td valign="top">
        <p style="margin:0 0 3px;font-size:10px;letter-spacing:2px;color:#7A96B2;">원스톱 스케일업 · {_sub_label}</p>
        <p style="margin:8px 0 8px;font-size:23px;font-weight:600;color:#FFFFFF;line-height:1.4;"><span style="color:#03C75A;">네이버</span>·<span style="color:#4285F4;">구</span><span style="color:#EA4335;">글</span> 검색 상위에<br>우리 회사를 올리는 법</p>
        <p style="margin:0;font-size:13px;color:#A8BDD1;">키워드 발굴 · 플레이스 최적화 · 블로그 상위노출</p>
      </td>
      <td width="70" align="right" valign="top">
        <div style="background:#DC2626;border-radius:10px;padding:9px 10px;text-align:center;min-width:52px;">
          <p style="margin:0;font-size:19px;font-weight:800;color:#FFFFFF;line-height:1;">{_dday_txt}</p>
          <p style="margin:3px 0 0;font-size:9px;font-weight:700;color:#FFFFFF;letter-spacing:0.5px;">~{_dl_short}</p>
        </div>
      </td>
    </tr></table>
    <div style="margin-top:16px;">
      <span style="display:inline-block;font-size:12px;color:#E0A458;background:#2A2109;border:1px solid #5A4718;padding:5px 12px;border-radius:6px;margin-right:6px;">무료 · 온라인 2시간</span>
      <span style="display:inline-block;font-size:12px;color:#F0A0A0;background:#2A0F0F;border:1px solid #5A2020;padding:5px 12px;border-radius:6px;">선착순 · 조기 종료 가능</span>
    </div>
  </div>
  <div style="height:4px;background:linear-gradient(to right,#03C75A 0%,#03C75A 33%,#4285F4 33%,#4285F4 55%,#EA4335 55%,#EA4335 73%,#FBBC05 73%,#FBBC05 100%);"></div>
  <div style="background:#FFFFFF;padding:24px 28px;">
    <p style="margin:0 0 4px;font-size:14px;color:#1C2B3A;">담당자님, 안녕하세요.</p>
    <p style="margin:0 0 14px;font-size:13px;color:#5A6675;line-height:1.75;">{_greeting}</p>
    <div style="margin-bottom:22px;padding:12px 16px;background:#F6FBF8;border:1px solid #D3EDDD;border-radius:8px;">
      <p style="margin:0;font-size:13px;color:#2C5F48;line-height:1.7;">💻 <span style="font-weight:600;">비대면 Zoom</span>으로 진행되어 사무실이나 자리에서 부담 없이 참여하실 수 있으니 많은 관심과 참여 부탁드립니다.</p>
    </div>
    <p style="margin:0 0 14px;font-size:15px;font-weight:600;color:#1C2B3A;">📚 이런 걸 배웁니다</p>
    {_curr_html}
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:14px 0 22px;">
      <tr>
        <td width="50%" style="padding:13px 16px;background:#0F1D2E;border-radius:8px 0 0 8px;">
          <p style="margin:0 0 4px;font-size:11px;color:#7A96B2;">일시</p>
          <p style="margin:0;font-size:14px;color:#FFFFFF;font-weight:500;">8/12(수) 14:00~16:00</p>
        </td>
        <td width="50%" style="padding:13px 16px;background:#16293F;border-radius:0 8px 8px 0;">
          <p style="margin:0 0 4px;font-size:11px;color:#7A96B2;">방식 · 강사</p>
          <p style="margin:0;font-size:14px;color:#FFFFFF;font-weight:500;">비대면 Zoom · 박성식</p>
        </td>
      </tr>
    </table>
    <div style="background:#EFF5FB;border:1px solid #CFE0F0;border-radius:10px;padding:16px 18px;">
      <p style="margin:0 0 8px;font-size:14px;font-weight:600;color:#0F1D2E;">📩 신청 방법 <span style="color:#DC2626;font-size:12px;">(~{_dl_short} 마감)</span></p>
      <p style="margin:0 0 6px;font-size:13px;color:#334155;line-height:1.7;">이 메일에 아래 정보를 <span style="color:#185FA5;font-weight:600;">회신</span>해 주세요.</p>
      <p style="margin:0;font-size:13px;color:#334155;line-height:1.9;">· 기업명<br>· 담당자명 / 연락처<br>· 참석 인원 (추가 참석자 있으면 함께)</p>
    </div>
    <div style="margin-top:12px;padding:12px 14px;background:#FBFAF6;border:1px solid #E8E2CF;border-radius:8px;">
      <p style="margin:0;font-size:12px;color:#6B6550;line-height:1.7;">📎 <span style="font-weight:600;color:#5A5340;">줌 링크와 교육자료</span>는 접수 종료 후, 신청하신 모든 기업께 <span style="font-weight:600;color:#5A5340;">일괄 발송</span>해 드립니다.</p>
    </div>
    {_kw_card}
  </div>
  <div style="background:#0A1628;padding:18px 28px;">
    <p style="margin:0;font-size:12px;color:#A8BDD1;line-height:1.8;">혁신제품지원센터 원스톱 스케일업 운영팀<br><a href="mailto:onestop.kipcc@gmail.com" style="color:#6EE7B7 !important;text-decoration:none;">onestop.kipcc@gmail.com</a></p>
    <p style="margin:8px 0 0;font-size:11px;color:#5F7A96;">함께 참석하실 사내 담당자분들께도 공유 부탁드립니다.</p>
  </div>
</div>
</body></html>"""
def build_sep_edu_html(company="", deadline="2026-09-09", is_reminder=False):
    """9월 교육(디지털 마케팅 · 김나영) 신청 안내/리마인더 메일 HTML.
    아이보리+네이비+골드 팔레트. D-day는 날짜 기준 자동 계산."""
    from datetime import datetime as _dt, date as _date
    _dl_short = "9/9(수)"
    try:
        _dl = _dt.strptime(deadline, "%Y-%m-%d").date()
        _days = (_dl - _date.today()).days
        _dday_txt = "마감" if _days < 0 else ("D-DAY" if _days == 0 else f"D-{_days}")
        _wd = ['월','화','수','목','금','토','일'][_dl.weekday()]
        _dl_short = f"{_dl.month}/{_dl.day}({_wd})"
    except Exception:
        _dday_txt = ""
    _who = f"<b>{company}</b> 담당자님" if company else "담당자님"
    _greeting = (f"많은 관심에 감사드리며, 9월 교육 신청 기간을 <b style=\"color:#2A2620;\">{_dl_short}까지 연장</b>하여 다시 안내드립니다. "
                 "아직 신청하지 않으셨다면 기간 내 회신으로 신청해 주세요."
                 if is_reminder else "원스톱 9월 교육을 안내드립니다.")
    _sub_label = "9월 무료 교육 · 접수 기간 연장" if is_reminder else "9월 무료 교육"
    _brand = "원스톱 스케일업"   # 브랜드는 하나로 고정
    _dl_label = f"~{_dl_short} 마감 (기간 연장)" if is_reminder else f"~{_dl_short} 마감"
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#E6E9EE;font-family:'Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#E6E9EE;padding:36px 0 52px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- 헤더 -->
  <tr>
    <td style="background:#1B2A41;border-radius:14px 14px 0 0;padding:30px 30px 26px;border-bottom:2px solid #C9A96A;">
      <table width="100%" cellpadding="0" cellspacing="0"><tr>
        <td valign="top">
          <p style="margin:0 0 14px;font-size:11px;letter-spacing:2px;color:#C9A96A;font-weight:700;">{_brand} · {_sub_label}</p>
          <p style="margin:0 0 6px;font-size:13px;color:#B4C0CE;">중소조달기업 실무에 바로 적용할 수 있는</p>
          <p style="margin:0 0 16px;font-size:26px;font-weight:700;color:#FFFFFF;line-height:1.3;">디지털 마케팅</p>
          <p style="margin:0;font-size:13px;color:#C5D0DC;line-height:1.7;">마케터의 AI 활용 &nbsp;|&nbsp; SNS 마케팅 실무 &nbsp;|&nbsp; B2B 콘텐츠 전략</p>
        </td>
        <td width="74" align="right" valign="top">
          <div style="background:linear-gradient(135deg,#C9A96A 0%,#B08D4F 100%);border-radius:12px;padding:10px 0;width:66px;text-align:center;">
            <p style="margin:0;font-size:19px;font-weight:800;color:#1B2A41;line-height:1;">{_dday_txt}</p>
            <p style="margin:4px 0 0;font-size:9px;font-weight:700;color:#1B2A41;letter-spacing:0.5px;">~{_dl_short}</p>
          </div>
        </td>
      </tr></table>
      <div style="margin-top:20px;">
        <span style="display:inline-block;font-size:12px;color:#E8D5A8;background:rgba(201,169,106,0.14);border:1px solid rgba(201,169,106,0.45);padding:5px 12px;border-radius:6px;margin-right:6px;">무료 · 온라인 2시간</span>
        <span style="display:inline-block;font-size:12px;color:#C5D0DC;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.18);padding:5px 12px;border-radius:6px;">선착순 · 조기 종료 가능</span>
      </div>
    </td>
  </tr>

  <!-- 본문 -->
  <tr>
    <td style="background:#FBFAF7;padding:30px 30px 28px;word-break:keep-all;overflow-wrap:break-word;">

      <p style="margin:0 0 16px;font-size:14px;color:#2A2620;">{_who}, 안녕하세요.</p>

      <p style="margin:0 0 12px;font-size:13px;color:#5A5548;line-height:1.9;">
        {_greeting}
      </p>
      <p style="margin:0 0 26px;font-size:13px;color:#5A5548;line-height:1.9;">
        이번 교육은 <b style="color:#2A2620;">AI 활용, SNS 운영, B2B 콘텐츠</b> 실무를 다룹니다.
      </p>

      <div style="margin-bottom:30px;padding:14px 18px;background:#F5F0E6;border:1px solid #E0D5BF;border-radius:8px;">
        <p style="margin:0;font-size:13px;color:#5A5548;line-height:1.8;">💻 <b style="color:#2A2620;">비대면 Zoom</b>으로 진행되어 자리에서 부담 없이 참여하실 수 있습니다. 마케팅·영업 담당자, 대표님 누구나 환영합니다.</p>
      </div>

      <p style="margin:0 0 14px;font-size:15px;font-weight:700;color:#2A2620;">📚 이런 걸 배웁니다</p>

      <div style="margin-bottom:12px;padding:16px 18px;background:#FFFFFF;border:1px solid #E8E2D5;border-left:4px solid #C9A96A;border-radius:0 8px 8px 0;">
        <p style="margin:0 0 6px;font-size:14px;font-weight:700;color:#2A2620;">마케터의 AI 활용</p>
        <p style="margin:0;font-size:12.5px;color:#6B6558;line-height:1.8;">실무에서 AI를 어떻게 활용해 마케팅 업무의 효율과 결과물의 질을 높이는지. 카피·기획·리서치에 바로 쓰는 프롬프트와 툴</p>
      </div>
      <div style="margin-bottom:12px;padding:16px 18px;background:#FFFFFF;border:1px solid #E8E2D5;border-left:4px solid #C9A96A;border-radius:0 8px 8px 0;">
        <p style="margin:0 0 6px;font-size:14px;font-weight:700;color:#2A2620;">온라인 SNS 마케팅 실무</p>
        <p style="margin:0;font-size:12.5px;color:#6B6558;line-height:1.8;">채널 운영과 콘텐츠 기획 등 현장에서 바로 적용 가능한 실무 노하우. 어떤 채널을, 어떤 주기로, 무엇을 올릴 것인가</p>
      </div>
      <div style="margin-bottom:30px;padding:16px 18px;background:#FFFFFF;border:1px solid #E8E2D5;border-left:4px solid #C9A96A;border-radius:0 8px 8px 0;">
        <p style="margin:0 0 6px;font-size:14px;font-weight:700;color:#2A2620;">B2B 콘텐츠 전략</p>
        <p style="margin:0;font-size:12.5px;color:#6B6558;line-height:1.8;">조달기업 특성에 맞는 효과적인 B2B 콘텐츠 유형. 공공기관·구매담당자에게 신뢰를 주는 상세페이지, 사례, 자료 구성</p>
      </div>

      <!-- 일시 · 강사 -->
      <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 14px;">
        <tr>
          <td width="50%" style="padding:16px 18px;background:#1B2A41;border-radius:8px 0 0 8px;">
            <p style="margin:0 0 6px;font-size:11px;color:#C9A96A;font-weight:700;">일시</p>
            <p style="margin:0;font-size:14px;color:#FFFFFF;font-weight:600;">9/16(수) 14:00 ~ 16:00</p>
          </td>
          <td width="50%" style="padding:16px 18px;background:#22344F;border-radius:0 8px 8px 0;">
            <p style="margin:0 0 6px;font-size:11px;color:#C9A96A;font-weight:700;">방식 · 강사</p>
            <p style="margin:0;font-size:14px;color:#FFFFFF;font-weight:600;">비대면 Zoom · 김나영</p>
          </td>
        </tr>
      </table>

      <!-- 강사 소개 -->
      <div style="margin-bottom:30px;padding:18px 20px;background:#FFFFFF;border:1.5px solid #D8D0C0;border-radius:10px;">
        <p style="margin:0 0 12px;font-size:11px;font-weight:700;color:#9A7B3F;letter-spacing:1.5px;">강사 소개</p>
        <p style="margin:0 0 14px;font-size:16px;font-weight:700;color:#2A2620;">김나영 <span style="font-size:12px;font-weight:400;color:#8A8478;margin-left:6px;">마케팅 전문가 · 강사</span></p>
        <table cellpadding="0" cellspacing="0" style="font-size:12.5px;color:#5A5548;line-height:1.9;">
          <tr><td width="28" valign="top" style="color:#C9A96A;font-weight:700;">현)</td><td>CCFM 전략기획실 실장</td></tr>
          <tr><td valign="top" style="color:#C9A96A;font-weight:700;">전)</td><td>그로스쿨(Groschool) 대표 &nbsp;— 실무 마케팅 교육 플랫폼, 2020 창업·2025 엑싯</td></tr>
          <tr><td valign="top" style="color:#C9A96A;font-weight:700;">전)</td><td>아이보스 · 인크루트 · 플랜티교육그룹 · 해커스교육그룹 마케팅</td></tr>
          <tr><td valign="top" style="color:#C9A96A;font-weight:700;">저서</td><td>『한 권으로 끝내는 인스타그램!』 (공저)</td></tr>
          <tr><td valign="top" style="color:#C9A96A;font-weight:700;">출강</td><td>카카오톡 · 언더독스 · 교보문고 등 기업·기관 다수</td></tr>
        </table>
      </div>

      <!-- 신청 방법 -->
      <div style="background:#F5F0E6;border:1.5px solid #D8C9A8;border-radius:10px;padding:18px 20px;">
        <p style="margin:0 0 12px;font-size:14px;font-weight:700;color:#2A2620;">📩 신청 방법 <span style="color:#B0894A;font-size:12px;font-weight:600;margin-left:4px;">{_dl_label}</span></p>
        <p style="margin:0 0 10px;font-size:13px;color:#5A5548;line-height:1.8;">이 메일에 아래 정보를 <b style="color:#1B2A41;">회신</b>해 주세요.</p>
        <p style="margin:0;font-size:13px;color:#5A5548;line-height:2.0;">
          · 기업명<br>
          · 담당자명 / 연락처<br>
          · 참석 인원 (추가 참석자 있으면 함께)
        </p>
      </div>

      <div style="margin-top:14px;padding:14px 18px;background:#FFFFFF;border:1px solid #E8E2D5;border-radius:8px;">
        <p style="margin:0;font-size:12px;color:#6B6558;line-height:1.9;">📎 <b style="color:#2A2620;">줌 링크와 교육 자료</b>는 접수 종료 후 신청하신 모든 기업께 일괄 발송해 드립니다.</p>
      </div>

    </td>
  </tr>

  <!-- 푸터 -->
  <tr>
    <td style="background:#1B2A41;border-radius:0 0 14px 14px;padding:20px 30px;border-top:2px solid #C9A96A;">
      <p style="margin:0;font-size:12px;color:#B4C0CE;line-height:1.9;">혁신제품지원센터 {_brand} 운영팀<br><a href="mailto:onestop.kipcc@gmail.com" style="color:#C9A96A !important;text-decoration:none;">onestop.kipcc@gmail.com</a></p>
      <p style="margin:10px 0 0;font-size:11px;color:#7A96B2;">함께 참석하실 사내 담당자분들께도 공유 부탁드립니다.</p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body></html>"""


def build_oct_edu_html(company="", deadline="2026-10-23", is_reminder=False):
    """10월 교육(지식재산 전략 · 함영석 변리사) 신청 안내/리마인더 메일 HTML.
    9월 교육과 같은 아이보리+네이비+골드 팔레트. 강의자료는 요약만 싣고 원본은 접수 종료 후 발송."""
    from datetime import datetime as _dt, date as _date
    _dl_short = "10/23(금)"
    try:
        _dl = _dt.strptime(deadline, "%Y-%m-%d").date()
        _days = (_dl - _date.today()).days
        _dday_txt = "마감" if _days < 0 else ("D-DAY" if _days == 0 else f"D-{_days}")
        _wd = ['월','화','수','목','금','토','일'][_dl.weekday()]
        _dl_short = f"{_dl.month}/{_dl.day}({_wd})"
    except Exception:
        _dday_txt = ""
    _who = f"<b>{company}</b> 담당자님" if company else "담당자님"
    _greeting = (f"10월 교육 신청이 <b style=\"color:#2A2620;\">{_dl_short}에 마감</b>되어 다시 안내드립니다. "
                 "아직 신청하지 않으셨다면 마감 전에 회신으로 신청해 주세요."
                 if is_reminder else "원스톱 10월 교육을 안내드립니다.")
    _sub_label = "10월 무료 교육 · 마감 임박" if is_reminder else "10월 무료 교육"
    _dl_label = f"~{_dl_short} 마감"
    _curr = [
        ("어떤 권리를 확보할 것인가 — 특허 · 상표 · 디자인",
         "권리별 확보 전략을 실제 분쟁 사례로 정리합니다. 숙박앱 BM 특허 무효 사건, '덮죽' 상표 선점 논란, "
         "정수기 디자인 분쟁에서 보는 '등록만으로는 이길 수 없는' 이유"),
        ("등록하지 않은 권리 지키기 — 영업비밀 · 부정경쟁방지법",
         "특허로 공개할지 영업비밀로 숨길지 판단하는 기준, 미등록 상표·제품 형태의 보호 범위와 한계, "
         "2024년 개정으로 강화된 징벌적 손해배상(최대 5배)"),
        ("해외 진출 전 브랜드 지키기",
         "최근 5년간 3만 건이 넘는 K-브랜드 해외 무단선점 현황과, 진출국 상표 선출원·현지 네이밍 체크리스트"),
        ("우리 회사 IP 포트폴리오 · 단계별 로드맵",
         "아이디어 → 출시 전 → 성장 → 운영 단계별로 챙길 것. 우선·초고속심사 활용, 중소기업 수수료 70% 감면, "
         "연차료 시점의 유지·포기 판단까지"),
    ]
    _curr_html = ""
    for _i, (_t, _d) in enumerate(_curr):
        _mb = "30px" if _i == len(_curr) - 1 else "12px"
        _curr_html += f"""
      <div style="margin-bottom:{_mb};padding:16px 18px;background:#FFFFFF;border:1px solid #E8E2D5;border-left:4px solid #C9A96A;border-radius:0 8px 8px 0;">
        <p style="margin:0 0 6px;font-size:14px;font-weight:700;color:#2A2620;">{_t}</p>
        <p style="margin:0;font-size:12.5px;color:#6B6558;line-height:1.8;">{_d}</p>
      </div>"""
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#E6E9EE;font-family:'Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#E6E9EE;padding:36px 0 52px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- 헤더 -->
  <tr>
    <td style="background:#1B2A41;border-radius:14px 14px 0 0;padding:30px 30px 26px;border-bottom:2px solid #C9A96A;">
      <table width="100%" cellpadding="0" cellspacing="0"><tr>
        <td valign="top">
          <p style="margin:0 0 14px;font-size:11px;letter-spacing:2px;color:#C9A96A;font-weight:700;">원스톱 스케일업 · {_sub_label}</p>
          <p style="margin:0 0 6px;font-size:13px;color:#B4C0CE;">기술·브랜드·디자인을 지키는</p>
          <p style="margin:0 0 16px;font-size:26px;font-weight:700;color:#FFFFFF;line-height:1.3;">기업이 알아야 할 지식재산 전략</p>
          <p style="margin:0;font-size:13px;color:#C5D0DC;line-height:1.7;">특허 &nbsp;|&nbsp; 상표 &nbsp;|&nbsp; 디자인 &nbsp;|&nbsp; 영업비밀</p>
        </td>
        <td width="74" align="right" valign="top">
          <div style="background:linear-gradient(135deg,#C9A96A 0%,#B08D4F 100%);border-radius:12px;padding:10px 0;width:66px;text-align:center;">
            <p style="margin:0;font-size:19px;font-weight:800;color:#1B2A41;line-height:1;">{_dday_txt}</p>
            <p style="margin:4px 0 0;font-size:9px;font-weight:700;color:#1B2A41;letter-spacing:0.5px;">~{_dl_short}</p>
          </div>
        </td>
      </tr></table>
      <div style="margin-top:20px;">
        <span style="display:inline-block;font-size:12px;color:#E8D5A8;background:rgba(201,169,106,0.14);border:1px solid rgba(201,169,106,0.45);padding:5px 12px;border-radius:6px;margin-right:6px;">무료 · 온라인 2시간</span>
        <span style="display:inline-block;font-size:12px;color:#C5D0DC;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.18);padding:5px 12px;border-radius:6px;">변리사 직강 · 실제 분쟁 사례</span>
      </div>
    </td>
  </tr>

  <!-- 본문 -->
  <tr>
    <td style="background:#FBFAF7;padding:30px 30px 28px;word-break:keep-all;overflow-wrap:break-word;">

      <p style="margin:0 0 16px;font-size:14px;color:#2A2620;">{_who}, 안녕하세요.</p>

      <p style="margin:0 0 12px;font-size:13px;color:#5A5548;line-height:1.9;">
        {_greeting}
      </p>
      <p style="margin:0 0 26px;font-size:13px;color:#5A5548;line-height:1.9;">
        이번 교육은 <b style="color:#2A2620;">특허·상표·디자인을 언제, 어떻게 확보하고 관리할지</b>를
        실제 분쟁 사례 중심으로 다룹니다. 해외 진출을 준비하는 기업이 놓치기 쉬운 상표 선점 문제도 함께 짚습니다.
      </p>

      <div style="margin-bottom:30px;padding:14px 18px;background:#F5F0E6;border:1px solid #E0D5BF;border-radius:8px;">
        <p style="margin:0;font-size:13px;color:#5A5548;line-height:1.8;">💻 <b style="color:#2A2620;">비대면 Zoom</b>으로 진행되어 자리에서 부담 없이 참여하실 수 있습니다. 대표님, 기술·연구 담당자, 마케팅·영업 담당자 누구나 환영합니다.</p>
      </div>

      <p style="margin:0 0 14px;font-size:15px;font-weight:700;color:#2A2620;">📚 이런 걸 배웁니다</p>
{_curr_html}

      <!-- 일시 · 강사 -->
      <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 14px;">
        <tr>
          <td width="50%" style="padding:16px 18px;background:#1B2A41;border-radius:8px 0 0 8px;">
            <p style="margin:0 0 6px;font-size:11px;color:#C9A96A;font-weight:700;">일시</p>
            <p style="margin:0;font-size:14px;color:#FFFFFF;font-weight:600;">10/28(수) 14:00 ~ 16:00</p>
          </td>
          <td width="50%" style="padding:16px 18px;background:#22344F;border-radius:0 8px 8px 0;">
            <p style="margin:0 0 6px;font-size:11px;color:#C9A96A;font-weight:700;">방식 · 강사</p>
            <p style="margin:0;font-size:14px;color:#FFFFFF;font-weight:600;">비대면 Zoom · 함영석 변리사</p>
          </td>
        </tr>
      </table>

      <!-- 강사 소개 -->
      <div style="margin-bottom:30px;padding:18px 20px;background:#FFFFFF;border:1.5px solid #D8D0C0;border-radius:10px;">
        <p style="margin:0 0 12px;font-size:11px;font-weight:700;color:#9A7B3F;letter-spacing:1.5px;">강사 소개</p>
        <p style="margin:0 0 14px;font-size:16px;font-weight:700;color:#2A2620;">함영석 <span style="font-size:12px;font-weight:400;color:#8A8478;margin-left:6px;">변리사</span></p>
        <table cellpadding="0" cellspacing="0" style="font-size:12.5px;color:#5A5548;line-height:1.9;">
          <tr><td width="28" valign="top" style="color:#C9A96A;font-weight:700;">현)</td><td>청운국제특허법인 (LEE &amp; PARK) 변리사</td></tr>
        </table>
      </div>

      <!-- 신청 방법 -->
      <div style="background:#F5F0E6;border:1.5px solid #D8C9A8;border-radius:10px;padding:18px 20px;">
        <p style="margin:0 0 12px;font-size:14px;font-weight:700;color:#2A2620;">📩 신청 방법 <span style="color:#B0894A;font-size:12px;font-weight:600;margin-left:4px;">{_dl_label}</span></p>
        <p style="margin:0 0 10px;font-size:13px;color:#5A5548;line-height:1.8;">이 메일에 아래 정보를 <b style="color:#1B2A41;">회신</b>해 주세요.</p>
        <p style="margin:0;font-size:13px;color:#5A5548;line-height:2.0;">
          · 기업명<br>
          · 담당자명 / 연락처<br>
          · 참석 인원 (추가 참석자 있으면 함께)
        </p>
      </div>

      <div style="margin-top:14px;padding:14px 18px;background:#FFFFFF;border:1px solid #E8E2D5;border-radius:8px;">
        <p style="margin:0;font-size:12px;color:#6B6558;line-height:1.9;">📎 <b style="color:#2A2620;">줌 링크와 교육 자료</b>는 접수 종료 후 신청하신 모든 기업께 일괄 발송해 드립니다.</p>
      </div>

    </td>
  </tr>

  <!-- 푸터 -->
  <tr>
    <td style="background:#1B2A41;border-radius:0 0 14px 14px;padding:20px 30px;border-top:2px solid #C9A96A;">
      <p style="margin:0;font-size:12px;color:#B4C0CE;line-height:1.9;">혁신제품지원센터 원스톱 스케일업 운영팀<br><a href="mailto:onestop.kipcc@gmail.com" style="color:#C9A96A !important;text-decoration:none;">onestop.kipcc@gmail.com</a></p>
      <p style="margin:10px 0 0;font-size:11px;color:#7A96B2;">함께 참석하실 사내 담당자분들께도 공유 부탁드립니다.</p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body></html>"""

API_KEY          = "Nt604D"
BASE_URL         = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
SELECTED_FILE    = "선정기업_명단.xlsx"   # ← 핵심 변경
NOTICES_FILE     = "notices_db.xlsx"
HISTORY_FILE     = "send_history.xlsx"
KEYWORDS_FILE    = "keywords.json"
DETAIL_FILE      = "notices_detail.xlsx"  # 크롤링 전문 DB
# 전문 DB는 3MB가 넘는데 대시보드가 쓰는 건 '몇 건 수집됐나' 뿐이라, 크롤러가
# 돌 때 이 요약만 따로 남긴다. 없으면 대시보드가 전문 파일을 직접 읽는다(구버전 호환).
DETAIL_SUMMARY_FILE = "notices_detail_summary.json"
AI_ANALYSIS_FILE = "ai_analysis.json"     # AI 분석 결과 영구 저장
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
        # 동의어 확장
        "메디컬","헬스테크","의생명","생물의약","디지털치료제",
        "의료정보","병원정보","의료데이터","EMR","PHR",
        "재활","보조기기","의료소프트웨어","수술로봇","진단기기",
    ],
    "미래차·모빌리티": [
        "미래차","모빌리티","전기차","자율주행","수소차","친환경차","UAM",
        "퍼스널모빌리티","전동화","충전인프라","배터리","이차전지",
        "자동차부품","차량","운송","교통수단","커넥티드카",
        # 동의어 확장
        "EV","전동킥보드","PM","도심항공","전기버스","수소버스",
        "차량공유","카셰어링","라이드헤일링","MaaS","통합모빌리티",
        "ADAS","자동차SW","차량용반도체","OBC","BMS",
    ],
    "환경·에너지 기술": [
        "환경","에너지","탄소중립","친환경","온실가스","신재생","태양광",
        "수소","폐기물","재활용","탄소","녹색","저탄소","청정",
        "에너지효율","ESG","탄소저감","기후","풍력","연료전지",
        "환경오염","수처리","대기","토양정화","친환경소재",
        # 동의어 확장
        "탄소발자국","넷제로","RE100","그린뉴딜","순환경제",
        "폐기물처리","하수처리","대기오염","미세먼지","소음진동",
        "환경모니터링","환경측정","에너지저장","ESS","BESS",
        "태양전지","풍력발전","바이오에너지","지열","조력",
    ],
    "스마트 제조·산업·기계": [
        "스마트제조","스마트공장","제조혁신","산업기계","자동화","로봇",
        "공정혁신","MES","제조","기계","장비","설비","부품","소재",
        "정밀기계","산업용","제조업","공정","생산","품질관리",
        "CNC","공작기계","산업로봇","협동로봇","용접","도금",
        # 동의어 확장
        "DX전환","디지털공장","산업IoT","IIoT","예지보전",
        "품질검사","비전검사","비파괴검사","측정","계측",
        "금형","주조","단조","압출","표면처리","열처리",
        "PCB제조","반도체장비","디스플레이장비","이차전지장비",
    ],
    "스마트 건설": [
        "스마트건설","건설","건축","BIM","모듈러","건설기술","건설자재","플랜트",
        "건설장비","건설안전","건축자재","인프라건설","토목","시공",
        "건물","구조물","시설물","유지보수","안전진단","건설IT",
        # 동의어 확장
        "OSC","탈현장건설","3D프린팅건설","드론측량","건설드론",
        "시설관리","FM","AMO","건물에너지","BEMS","FEMS",
        "안전모니터링","작업자안전","건설현장안전","붕괴예측",
    ],
    "도시·교통 인프라": [
        "스마트시티","도시","교통","인프라","철도","도로","물류","스마트교통",
        "도시개발","대중교통","지하철","버스","항만","공항",
        "물류센터","SCM","공급망","유통인프라","스마트물류",
        # 동의어 확장
        "C-ITS","도로인프라","교통신호","주차관제","주차공유",
        "라스트마일","배송","풀필먼트","크로스도킹","콜드체인",
        "스마트항만","항만물류","선박물류","물류자동화","WMS",
    ],
    "방산·국방 기술": [
        "방산","국방","방위","군수","보안","방위산업","군","방어",
        "국방기술","방위기술","무기","군용","군사","사이버보안",
        "정보보안","보안솔루션","네트워크보안","물리보안",
        # 동의어 확장
        "ITAR","방산수출","국방R&D","ADD","국방조달",
        "보안인증","CC인증","ISMS","ISMS-P","보안감사",
        "침해대응","취약점","위협인텔리전스","SOC","SIEM",
    ],
    "정보통신 기술": [
        "ICT","정보통신","소프트웨어","앱","플랫폼","클라우드","SaaS","통신",
        "SW","IT","시스템","솔루션","네트워크","서버","데이터센터",
        "사물인터넷","IoT","5G","통신망","디지털","스마트",
        "보안","ERP","CRM","그룹웨어","SI",
        # 동의어 확장
        "API","마이크로서비스","컨테이너","쿠버네티스","DevOps",
        "엣지컴퓨팅","엣지","멀티클라우드","하이브리드클라우드",
        "RPA","업무자동화","디지털워크플레이스","협업툴",
        "6G","위성통신","저궤도위성","O-RAN","오픈랜",
    ],
    "AI·데이터 기술": [
        "AI","인공지능","빅데이터","데이터","머신러닝","딥러닝","디지털전환","DX",
        "자연어처리","컴퓨터비전","생성형AI","ChatGPT","LLM",
        "데이터분석","데이터플랫폼","MLOps","AI솔루션","지능형",
        "예측","추천","자동화AI","AI서비스",
        # 동의어 확장
        "파운데이션모델","멀티모달","RAG","AI에이전트","AI플랫폼",
        "데이터레이크","데이터웨어하우스","데이터마트","ETL",
        "시각AI","음성AI","영상분석","이상탐지","예측유지보수",
        "AI반도체","NPU","온디바이스AI","경량화모델",
    ],
    "농축산·수산·식품": [
        "농업","농식품","식품","수산","축산","스마트팜","농산물","푸드테크",
        "농기계","농촌","원예","작물","가공식품","식품안전",
        "수산물","수산양식","해양수산","축산물","낙농",
        # 동의어 확장
        "정밀농업","농업IoT","농업드론","수직농장","식물공장",
        "대체육","배양육","세포농업","푸드업사이클","기능성식품",
        "HACCP","식품인증","GMP식품","유기농","GAP",
        "어업","어선","어망","수산가공","냉동수산",
    ],
    "우주·항공·해양": [
        "우주","항공","드론","해양","선박","해운","위성",
        "UAM","도심항공","항공기","항공부품","발사체",
        "해양플랜트","해양기술","조선","선박부품","해양수산",
        # 동의어 확장
        "소형위성","큐브샛","우주부품","발사서비스","뉴스페이스",
        "MRO","항공정비","항공소재","항공SW","항공안전",
        "수중드론","AUV","ROV","수중로봇","해양로봇",
        "선박자율운항","자율선박","스마트쉽","친환경선박",
    ],
    "핀테크·금융 IT": [
        "핀테크","금융","결제","블록체인","암호화폐","보험테크",
        "디지털금융","오픈뱅킹","간편결제","송금","대출플랫폼",
        "자산관리","투자플랫폼","금융데이터","RegTech",
        # 동의어 확장
        "마이데이터","신용평가","대안신용","P2P금융","크라우드펀딩",
        "CBDC","STO","NFT","디지털자산","웹3",
        "보험금청구","자동심사","손해사정","보험데이터",
        "PG","VAN","전자지갑","선불카드","BNPL",
    ],
    "전기·전자": [
        "전기","전자","반도체","디스플레이","배터리","전력","회로","센서",
        "전장","전기부품","전자부품","LED","OLED","PCB",
        "전력반도체","시스템반도체","전력변환","전기설비",
        "계측기","검사장비","시험장비",
        # 동의어 확장
        "SiC","GaN","MLCC","MEMS","RF부품","안테나",
        "마이크로LED","MiniLED","플렉서블디스플레이","투명디스플레이",
        "사이니지","전광판","스마트사이니지","디지털사이니지",
        "스마트미터","AMI","전력IT","에너지관리","HEMS",
    ],
    "교육·HR테크": [
        "에듀테크","교육","HR","인재","학습","이러닝","채용플랫폼",
        "온라인교육","직무교육","기업교육","학습관리","LMS",
        "인적자원","인사관리","채용","HRD","HRM",
        # 동의어 확장
        "적응형학습","메타버스교육","XR교육","AI튜터","코딩교육",
        "평생학습","직업훈련","직업교육","자격증","역량평가",
        "피플애널리틱스","인사AI","채용AI","온보딩","퇴직관리",
    ],
    "콘텐츠·미디어·문화": [
        "콘텐츠","미디어","문화","게임","엔터","영상","음악","OTT",
        "웹툰","웹소설","애니메이션","VFX","CG","디지털콘텐츠",
        "메타버스","XR","VR","AR","MR","실감콘텐츠",
        "MCN","유튜브","SNS","인플루언서","소셜미디어",
        "광고","마케팅","브랜드","PR","디지털광고",
        "관광","여행","스마트관광","여가","레저","스포츠테크",
    ],
}

# 별점 판정 함수용 flat 리스트 (설정 탭 표시용)
DEFAULT_HIGH = (
    TARGET_KW["조달기업특화"] +
    TYPE_KW["공공조달"] +
    # 원스톱 스케일업 핵심 대상 추가 키워드
    [
        "혁신형","혁신성장","혁신창업","혁신기업",
        "수출기업","수출유망","수출강소","수출지원",
        "해외조달","해외공공조달","UN조달","글로벌조달",
        "혁신제품","혁신제품지정","G-PASS","MAS","우수조달",
        "공공조달","조달시장","조달기업","조달지원",
        "중소벤처","벤처기업","이노비즈","메인비즈",
    ]
)
DEFAULT_MID = (
    TARGET_KW["수출기업특화"] +
    TYPE_KW["해외진출"] +
    TYPE_KW["마케팅홍보"] +
    TYPE_KW["인증특허"] +
    # 원스톱 대상 기업 MID 추가
    [
        "수출바우처","해외판로","해외마케팅","바이어발굴",
        "해외전시","무역사절단","수출인큐베이터",
        "인증","특허","지식재산","해외인증","국제인증",
        "스케일업","Scale-up","성장기업","글로벌","판로개척",
    ]
)
REALM_CODE   = {
    "금융":"01","기술개발":"02","인력":"03","수출":"04",
    "내수":"05","창업":"06","경영":"07","기타":"09",
}
# 테스트 수신자 — 설정 탭에서 변경 가능 (session_state 우선)
_DEFAULT_TEST_RECIPIENTS = ["fbwlgns819@naver.com","fbwlgns819@kip.re.kr"]


def build_together_html(company="", 담당자=""):
    """함께하기 회원소개 가입 독려 메일 HTML (선정기업 대상)."""
    _hi = f"{담당자} 담당자님" if 담당자 else "담당자님"
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F2F4F7;font-family:'Apple SD Gothic Neo',Arial,sans-serif;">
<div style="max-width:600px;margin:0 auto;background:#F2F4F7;border-radius:14px;overflow:hidden;border:1px solid #E2E5EA;">
  <div style="background:#0F1D2E;padding:28px 28px 26px;">
    <p style="margin:0 0 3px;font-size:10px;letter-spacing:2px;color:#7A96B2;">혁신제품지원센터 · 원스톱 스케일업</p>
    <p style="margin:8px 0 10px;font-size:23px;font-weight:600;color:#FFFFFF;line-height:1.4;">기업 회원소개 페이지에<br><span style="color:#5DCAA5;">귀사를 등록</span>해 주세요</p>
    <p style="margin:0;font-size:13px;color:#A8BDD1;">참여 기업을 소개하고, 협력의 접점을 만드는 공간입니다</p>
  </div>
  <div style="height:4px;background:linear-gradient(to right,#5DCAA5 0%,#4285F4 100%);"></div>
  <div style="background:#FFFFFF;padding:24px 28px;">
    <p style="margin:0 0 4px;font-size:14px;color:#1C2B3A;">{_hi}, 안녕하세요.</p>
    <p style="margin:0 0 16px;font-size:13px;color:#5A6675;line-height:1.75;">원스톱 스케일업 운영팀입니다. 참여 기업을 소개하고 기업 간 협력의 접점을 만들기 위해 <span style="color:#1C2B3A;font-weight:500;">'함께하기' 회원소개 페이지</span>를 준비했습니다. 페이지 오픈을 앞두고, 먼저 귀사의 정보를 등록해 주시면 감사하겠습니다.</p>
    <div style="margin-bottom:20px;padding:13px 16px;background:#FBFAF6;border:1px solid #E8E2CF;border-radius:8px;">
      <p style="margin:0;font-size:12px;color:#6B6550;line-height:1.75;">💡 선정 당시에는 회원소개 페이지가 준비되기 전이라 설문으로 정보를 받았습니다. 이제 페이지가 마련되어, <span style="font-weight:600;color:#5A5340;">직접 등록하는 방식</span>으로 다시 안내드립니다.</p>
    </div>
    <div style="margin-bottom:20px;padding:14px 16px;background:#F5F9FE;border:1px solid #D6E3F5;border-radius:10px;">
      <p style="margin:0;font-size:12px;color:#5A6675;line-height:1.8;">등록하신 기업 소개와 협력 희망 분야는, 다른 기업·기관이 귀사를 찾아보고 협력을 제안하는 데 활용됩니다.</p>
    </div>
    <p style="margin:0 0 14px;font-size:14px;font-weight:600;color:#1C2B3A;">📌 등록은 3단계면 됩니다</p>
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
      <tr>
        <td width="30%" align="center" valign="top" style="padding:0 4px;">
          <div style="background:#0F1D2E;border-radius:10px;padding:16px 8px;">
            <p style="margin:0 0 6px;font-size:22px;">🔗</p>
            <p style="margin:0;font-size:12px;font-weight:600;color:#FFFFFF;">1. 접속·가입</p>
            <p style="margin:4px 0 0;font-size:10px;color:#A8BDD1;line-height:1.4;">링크에서<br>회원가입</p>
          </div>
        </td>
        <td width="5%" align="center" style="font-size:16px;color:#B0BCC9;">›</td>
        <td width="30%" align="center" valign="top" style="padding:0 4px;">
          <div style="background:#16293F;border-radius:10px;padding:16px 8px;">
            <p style="margin:0 0 6px;font-size:22px;">✏️</p>
            <p style="margin:0;font-size:12px;font-weight:600;color:#FFFFFF;">2. 정보 입력</p>
            <p style="margin:4px 0 0;font-size:10px;color:#A8BDD1;line-height:1.4;">기업 소개·<br>협력 분야</p>
          </div>
        </td>
        <td width="5%" align="center" style="font-size:16px;color:#B0BCC9;">›</td>
        <td width="30%" align="center" valign="top" style="padding:0 4px;">
          <div style="background:#1F6F52;border-radius:10px;padding:16px 8px;">
            <p style="margin:0 0 6px;font-size:22px;">✅</p>
            <p style="margin:0;font-size:12px;font-weight:600;color:#FFFFFF;">3. 등록 완료</p>
            <p style="margin:4px 0 0;font-size:10px;color:#C3E8D5;line-height:1.4;">회원소개<br>노출</p>
          </div>
        </td>
      </tr>
    </table>
    <div style="text-align:center;margin:22px 0;">
      <a href="http://kipcc.eumsvr.com" style="display:inline-block;background:#185FA5;color:#FFFFFF !important;font-size:15px;font-weight:600;text-decoration:none;padding:14px 40px;border-radius:8px;">회원 가입하러 가기 →</a>
      <p style="margin:10px 0 0;font-size:11px;color:#8A96A3;">http://kipcc.eumsvr.com</p>
    </div>
    <div style="background:#FAFBFC;border:1px solid #E8ECF1;border-radius:8px;padding:14px 16px;margin-bottom:14px;">
      <p style="margin:0 0 6px;font-size:12px;font-weight:600;color:#1C2B3A;">📝 입력하실 내용</p>
      <p style="margin:0;font-size:12px;color:#5A6675;line-height:1.8;">· 기업 소개, 제품·기술 분야<br>· 협력 희망 분야 · 진출 국가 등</p>
    </div>
    <div style="padding:12px 16px;background:#F7F9FC;border:1px solid #E4EAF1;border-radius:8px;">
      <p style="margin:0;font-size:12px;color:#5A6675;line-height:1.75;">🔒 가입 이후 공개를 원하지 않을 경우 비공개 처리도 가능하니, 운영팀(<a href="mailto:onestop.kipcc@gmail.com" style="color:#185FA5 !important;text-decoration:none;">onestop.kipcc@gmail.com</a>)으로 연락 부탁드립니다.</p>
    </div>
  </div>
  <div style="background:#0A1628;padding:18px 28px;">
    <p style="margin:0;font-size:12px;color:#A8BDD1;line-height:1.8;">원스톱 스케일업 운영팀<br><a href="mailto:onestop.kipcc@gmail.com" style="color:#6EE7B7 !important;text-decoration:none;">onestop.kipcc@gmail.com</a></p>
    <p style="margin:8px 0 0;font-size:11px;color:#5F7A96;">가입이나 입력 중 궁금하신 점은 이 메일로 편하게 문의해 주세요.</p>
  </div>
</div>
</body></html>"""


def save_ai_analysis(drive):
    """ai_analysis session_state를 드라이브에 영구 저장"""
    data = st.session_state.get('ai_analysis', {})
    if not data:
        return True
    import json
    content = json.dumps(data, ensure_ascii=False, indent=None).encode('utf-8')
    return drive_upload(drive, AI_ANALYSIS_FILE, content, "application/json")

def load_ai_analysis(drive):
    """드라이브에서 ai_analysis를 복원 → session_state에 저장"""
    if 'ai_analysis' not in st.session_state:
        st.session_state['ai_analysis'] = {}
    saved = load_json(drive, AI_ANALYSIS_FILE)
    if saved and isinstance(saved, dict):
        # 기존 session_state와 병합 (새 분석이 우선)
        merged = {**saved, **st.session_state['ai_analysis']}
        st.session_state['ai_analysis'] = merged
        return len(saved)
    return 0


def reason_to_hashtag(reason_str):
    """매칭근거 문자열을 해시태그 형태로 변환"""
    if not reason_str: return ""
    tags = []
    parts = [p.strip() for p in reason_str.split("+")]
    for p in parts:
        if "조달기업 대상" in p:    tags.append("조달기업")
        elif "수출기업 대상" in p:  tags.append("수출기업")
        elif "중소벤처" in p:       tags.append("중소벤처")
        elif "중소기업" in p:       tags.append("중소기업")
        if "공공조달" in p:         tags.append("공공조달")
        elif "해외진출" in p:       tags.append("해외진출")
        elif "기술개발" in p:       tags.append("기술개발")
        elif "마케팅" in p:         tags.append("마케팅홍보")
        elif "인증특허" in p or "인증·특허" in p: tags.append("인증특허")
        elif "금융" in p and "융자" in p: tags.append("자금지원")
        elif "내수" in p:           tags.append("내수판로")
        if "수요태그(" in p:
            for t in p.split("(")[1].rstrip(")").split(","):
                t = t.strip()
                if t: tags.append(t)
        if "업종일치(" in p:
            ind = p.split("(")[1].rstrip(")").strip()
            if ind: tags.append(ind[:8])
        if "동일지역" in p:         tags.append("지역가점")
    seen = []
    for t in tags:
        if t not in seen: seen.append(t)
    hashtags = " ".join([f"#{t}" for t in seen[:5]])
    return hashtags


def reason_to_sentence(reason_str):
    """매칭근거 문자열을 메일용 자연스러운 한 줄 문장으로 변환"""
    if not reason_str: return ""
    parts = [p.strip() for p in reason_str.split("+")]
    targets, types, tags, industry, location = [], [], [], [], ""
    for p in parts:
        if "조달기업 대상" in p:    targets.append("조달")
        elif "수출기업 대상" in p:  targets.append("수출")
        elif "중소기업" in p:       targets.append("중소기업")
        if "공공조달" in p:         types.append("공공조달 진출")
        elif "해외진출" in p:       types.append("해외 판로 개척")
        elif "기술개발" in p:       types.append("기술개발")
        elif "마케팅" in p:         types.append("홍보·마케팅")
        elif "인증특허" in p or "인증·특허" in p: types.append("인증·특허")
        elif "금융" in p and "융자" in p:         types.append("자금 지원")
        elif "내수" in p:           types.append("내수 판로")
        if "수요태그(" in p:
            tags.append(p.split("(")[1].rstrip(")"))
        if "업종일치(" in p:
            industry = p.split("(")[1].rstrip(")")
        if "동일지역" in p: location = "지역 가점"
    parts_out = []
    if targets:
        parts_out.append("·".join(list(dict.fromkeys(targets))) + " 기업 대상")
    if types:
        mt = types[0] + (" 외 " + str(len(types)-1) + "개 지원" if len(types) > 1 else "")
        parts_out.append(mt)
    if tags:
        parts_out.append(", ".join(tags[:2]) + " 역량 활용 가능")
    if industry:
        parts_out.append(industry[:12] + " 분야 연관")
    if location:
        parts_out.append(location)
    return " · ".join(parts_out) if parts_out else reason_str[:40]


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
        'https://www.googleapis.com/auth/gmail.readonly',
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
    # 토큰 만료 시 강제 갱신
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GRequest())
            st.session_state['g_creds'] = creds
        except Exception:
            pass
    headers = kwargs.pop('headers', {})
    headers['Authorization'] = f'Bearer {creds.token}'
    return requests.request(method, url, headers=headers, **kwargs)

def render_html_table(df, max_rows=100):
    """DataFrame을 다크테마 HTML 표로 렌더링 (캔버스 대신 — CSS가 확실히 먹음)."""
    if df is None or df.empty:
        st.caption("데이터 없음")
        return
    import html as _html
    df = df.head(max_rows).fillna("")
    def _esc(v):
        s = str(v)
        return _html.escape(s) if s not in ("nan", "None", "NaT") else ""
    th = ('padding:9px 12px;text-align:left;font-size:12px;font-weight:600;'
          'color:#E8EFF6;background:#2A3346;border-bottom:2px solid #41485A;'
          'white-space:nowrap;')
    td = ('padding:8px 12px;font-size:13px;color:#E8EFF6;'
          'border-bottom:1px solid #2A3346;')
    _h = ('<div style="overflow-x:auto;border:1px solid #41485A;border-radius:8px;">'
          '<table style="width:100%;border-collapse:collapse;background:#16293F;">')
    _h += '<thead><tr>' + ''.join(f'<th style="{th}">{_esc(c)}</th>' for c in df.columns) + '</tr></thead>'
    _h += '<tbody>'
    for i, (_, row) in enumerate(df.iterrows()):
        bg = '#16293F' if i % 2 == 0 else '#1B3049'
        _h += '<tr>' + ''.join(
            f'<td style="{td}background:{bg};">{_esc(v)}</td>' for v in row) + '</tr>'
    _h += '</tbody></table></div>'
    st.markdown(_h, unsafe_allow_html=True)

def load_click_log(debug=False):
    """클릭추적_로그 시트를 Sheets API로 읽어 DataFrame 반환."""
    try:
        url = (f"https://sheets.googleapis.com/v4/spreadsheets/"
               f"{CLICK_LOG_SHEET_ID}/values/A:D")
        resp = gapi('GET', url)
        if not resp.ok:
            if debug: st.warning(f"클릭 로그 읽기 실패: {resp.status_code} {resp.text[:120]}")
            return pd.DataFrame()
        values = resp.json().get('values', [])
        if not values or len(values) < 2:
            return pd.DataFrame()
        header = values[0]
        data = [row + ['']*(len(header)-len(row)) for row in values[1:]]
        df = pd.DataFrame(data, columns=header)
        return df
    except Exception as e:
        if debug: st.warning(f"클릭 로그 오류: {e}")
        return pd.DataFrame()

# ── gmail API (requests 기반) ──────────────────────────
def gmail_send(raw_b64):
    resp = gapi('POST',
        'https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
        json={'raw': raw_b64})
    resp.raise_for_status()
    return resp.json()

# ── 안내메일 보관함 ───────────────────────────────────
# 지금까지 내보낸 안내메일을 기록으로 남긴다.
# 고쳐 쓰는 곳이 아니라 "그때 뭐라고 보냈는지" 다시 보는 곳이다.
#
# 모으는 길이 둘이다.
#  · Gmail 보낸메일함 — 앱에서 보낸 것. 제목으로 묶어 자동 수집한다.
#  · 그룹웨어(더존)   — Gmail에 흔적이 없다. HTML을 직접 올린다.
#
# 본문은 드라이브에 함께 저장한다. Gmail에서 지워져도 기록은 남아야 한다.

ARCHIVE_FILE = "메일보관함.json"

_ARCH_TEST = re.compile(r'^\s*\[TEST\]\s*')
_ARCH_REPLY = re.compile(r'^\s*(?:Re|RE|Fwd|FW|FWD)\s*[:：]', re.I)
_ARCH_OURS = re.compile(r'\[원스톱[^\]]*\]')


def arch_base(subject):
    """회차마다 달라지는 날짜와 건수를 치운다. 뒷부분은 손대지 않는다."""
    s = _ARCH_TEST.sub('', subject or '')
    s = re.sub(r'\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}', '{날짜}', s)
    s = re.sub(r'맞춤 지원공고\s*\d+건', '맞춤 지원공고 {n}건', s)
    return s.strip()


def arch_split(base):
    """마지막 '—' 앞뒤로 가른다. 없으면 뒤는 빈 문자열."""
    i = base.rfind('—')
    if i < 0:
        return base, ''
    return base[:i].strip(), base[i + 1:].strip()


def arch_group_key(subject):
    """한 통짜리(직접 올린 것)의 묶음 키. 뒷부분을 그대로 둔다."""
    return arch_base(subject)


def arch_kind(subject):
    s = subject or ''
    if re.search(r'교육|밋업|세미나|강의', s):      return '교육'
    if re.search(r'공고', s):                        return '공고 매칭'
    if re.search(r'실적|집계|회신|등록|공유|자료', s): return '안내·요청'
    return '기타'


def _arch_day(ts_ms):
    return datetime.fromtimestamp(int(ts_ms) / 1000).strftime('%Y-%m-%d')


def gmail_sent_ids():
    """보낸메일함 전체 id. 목록만 받으므로 빠르다."""
    ids, token = [], None
    while True:
        p = {'q': 'in:sent', 'maxResults': 500}
        if token:
            p['pageToken'] = token
        r = gapi('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/messages',
                 params=p)
        r.raise_for_status()
        j = r.json()
        ids += [m['id'] for m in j.get('messages', [])]
        token = j.get('nextPageToken')
        if not token:
            break
    return ids


def gmail_meta_many(ids, progress=None):
    """제목·수신자·시각만 받는다. 본문은 받지 않는다.

    한 통씩 받으면 1,800통에 몇 분이 걸려서 8가닥으로 나눠 받는다.
    실패한 건은 네 번까지 다시 받고, 끝내 못 받으면 몇 건인지 돌려준다.
    """
    import time as _t
    from concurrent.futures import ThreadPoolExecutor

    creds = get_creds()
    if not creds:
        raise Exception("구글 인증 실패")
    sess = requests.Session()
    sess.headers['Authorization'] = f'Bearer {creds.token}'
    url = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/{}'
    par = {'format': 'metadata', 'metadataHeaders': ['Subject', 'To', 'Date']}

    out, done, failed = [], [0], []

    def one(mid):
        for attempt in range(4):
            try:
                r = sess.get(url.format(mid), params=par, timeout=30)
                if r.status_code == 200:
                    return r.json()
                _t.sleep(1.2 * (attempt + 1))
            except Exception:
                _t.sleep(1.2 * (attempt + 1))
        failed.append(mid)
        return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        for j in ex.map(one, ids):
            done[0] += 1
            if progress and done[0] % 40 == 0:
                progress(done[0], len(ids))
            if not j:
                continue
            h = {x['name']: x['value']
                 for x in j.get('payload', {}).get('headers', [])}
            out.append({'id': j['id'], 'subject': h.get('Subject', ''),
                        'to': h.get('To', ''),
                        'ts': int(j.get('internalDate', 0))})
    if progress:
        progress(len(ids), len(ids))
    return out, failed


def gmail_html(msg_id):
    """메일 한 통의 HTML 본문을 꺼낸다. 없으면 빈 문자열."""
    import base64 as _b64
    r = gapi('GET',
             f'https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}',
             params={'format': 'full'})
    if not r.ok:
        return ''

    def walk(p):
        if p.get('mimeType') == 'text/html' and p.get('body', {}).get('data'):
            return p['body']['data']
        for c in (p.get('parts') or []):
            got = walk(c)
            if got:
                return got
        return ''

    data = walk(r.json().get('payload', {}))
    if not data:
        return ''
    try:
        pad = '=' * (-len(data) % 4)
        return _b64.urlsafe_b64decode(data + pad).decode('utf-8', 'replace')
    except Exception:
        return ''


def arch_collect_gmail(progress=None, min_count=3):
    """보낸메일함을 훑어 묶음으로 만든다.

    [TEST]와 답장·전달은 뺀다. min_count 통 미만은 개별 메일로 보고 뺀다.
    """
    ids = gmail_sent_ids()
    metas, failed = gmail_meta_many(ids, progress=progress)

    real = [m for m in metas
            if not _ARCH_TEST.match(m['subject'] or '')
            and not _ARCH_REPLY.match(m['subject'] or '')]

    # 제목 앞부분이 같은 것끼리 모은 뒤, 뒷부분이 통마다 다르면 그때만
    # {기업명}으로 본다. 「… — 8월 교육 신청 안내」처럼 뒷부분이 내용인
    # 제목까지 지워버리지 않으려는 것이다.
    heads = {}
    for m in real:
        b = arch_base(m['subject'])
        h, t = arch_split(b)
        heads.setdefault(h, []).append((m, t))

    groups = {}
    for h, lst in heads.items():
        tails = {t for _, t in lst}
        if len(tails) > 1:
            key = f"{h} — {{기업명}}"
        else:
            t = next(iter(tails))
            key = f"{h} — {t}" if t else h
        groups.setdefault(key, []).extend(m for m, _ in lst)

    items = []
    for key, rows in groups.items():
        # 숨은참조로 한 번에 보낸 것은 1통으로 남는다. 우리 머리말이 붙어
        # 있으면 통수가 적어도 단체 발송으로 보고 남긴다.
        if len(rows) < min_count and not _ARCH_OURS.search(key):
            continue
        rows.sort(key=lambda x: x['ts'])
        last = rows[-1]
        items.append({
            'key': key,
            'kind': arch_kind(last['subject']),
            'channel': 'Gmail',
            'first': _arch_day(rows[0]['ts']),
            'last': _arch_day(last['ts']),
            'count': len(rows),
            'sample_subject': last['subject'],
            'msg_id': last['id'],
            'html': gmail_html(last['id']),
        })
    items.sort(key=lambda x: x['last'], reverse=True)
    return items, {'총': len(ids), '테스트·답장 제외': len(real),
                   '묶음': len(items), '못 받은 건': len(failed)}


def arch_load(drive):
    raw = drive_download(drive, ARCHIVE_FILE)
    if not raw:
        return {'updated': '', 'items': []}
    try:
        d = json.loads(raw.decode('utf-8'))
        d.setdefault('items', [])
        d.setdefault('updated', '')
        return d
    except Exception:
        return {'updated': '', 'items': []}


def arch_save(drive, data):
    return drive_upload(drive, ARCHIVE_FILE,
                        json.dumps(data, ensure_ascii=False, indent=1).encode('utf-8'),
                        'application/json')


def arch_merge(old_items, new_gmail_items):
    """Gmail 수집분은 갈아끼우고, 직접 올린 그룹웨어 항목은 그대로 둔다."""
    manual = [x for x in (old_items or []) if x.get('channel') != 'Gmail']
    merged = list(new_gmail_items) + manual
    merged.sort(key=lambda x: x.get('last', ''), reverse=True)
    return merged

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
    import urllib.parse
    encoded_id = urllib.parse.quote(cal_id, safe='')
    url = f'https://www.googleapis.com/calendar/v3/calendars/{encoded_id}/events'
    resp = gapi('POST', url, json=body)
    if not resp.ok:
        return {'error': resp.status_code, 'msg': resp.text[:100], 'url': url[:80]}
    return resp.json()

def cal_create(summary, description):
    """캘린더 생성 → cal_id 반환"""
    resp = gapi('POST',
        'https://www.googleapis.com/calendar/v3/calendars',
        json={'summary': summary, 'description': description, 'timeZone': 'Asia/Seoul'})
    return resp.json().get('id', '') if resp.ok else ''

def cal_share(cal_id, email):
    """캘린더를 특정 이메일(reader)로 공유"""
    resp = gapi('POST',
        f'https://www.googleapis.com/calendar/v3/calendars/{cal_id}/acl',
        json={'scope': {'type': 'user', 'value': email}, 'role': 'reader'})
    return resp.ok

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

@st.cache_data(ttl=600, show_spinner=False)
def read_excel_cached(filename):
    """읽기 전용 화면을 위한 10분 캐시.

    Streamlit 은 위젯을 하나 누를 때마다 스크립트를 처음부터 다시 돌린다. 그런데
    load_excel 에 캐시가 없어 대시보드는 렌더링마다 드라이브에서 6MB 가까이
    (공고목록 2.7MB + 공고전문 3.2MB) 다시 내려받고 있었다 — 타임라인 필터 버튼
    하나만 눌러도 그랬다.
    쓰기 경로는 그대로 두고 읽기 전용 화면에서만 쓴다. 저장 직후 최신값이 필요한
    화면에 영향을 주지 않기 위해서다. 강제로 비우려면 read_excel_cached.clear()."""
    return load_excel(_get_drive(), filename)


@st.cache_data(ttl=600, show_spinner=False)
def read_json_cached(filename):
    """읽기 전용 화면을 위한 JSON 캐시 (판단 기록 등)."""
    return load_json(_get_drive(), filename) or {}


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

def trigger_github_crawl(limit=0):
    """GitHub Actions의 크롤링 워크플로를 원격 실행.
    Streamlit Cloud에서는 chromium 실행이 불안정하므로 Actions에 위임한다.
    필요: st.secrets['github_token'] (repo 또는 workflow 권한 PAT)"""
    token = st.secrets.get("github_token", "")
    if not token:
        return False, "GitHub 토큰이 설정되지 않았습니다. (Streamlit Secrets에 github_token 추가 필요)"
    owner_repo = st.secrets.get("github_repo", "onestopkipcc-web/scaleup-matching")
    wf = st.secrets.get("github_workflow", "crawl.yml")
    url = f"https://api.github.com/repos/{owner_repo}/actions/workflows/{wf}/dispatches"
    try:
        r = requests.post(url,
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            json={"ref": "main", "inputs": {"limit": str(int(limit))}},
            timeout=30)
        if r.status_code == 204:
            return True, ""
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:
        return False, str(e)[:200]


def load_text(drive, filename):
    content = drive_download(drive, filename)
    return content.decode('utf-8').strip() if content else ""

def load_keywords(drive):
    kw = load_json(drive, KEYWORDS_FILE)
    global TARGET_KW, TYPE_KW
    if "TARGET_KW" in kw: TARGET_KW = kw["TARGET_KW"]
    if "TYPE_KW"   in kw: TYPE_KW   = kw["TYPE_KW"]
    return kw.get("HIGH", DEFAULT_HIGH), kw.get("MID", DEFAULT_MID)

def load_kw_config(drive):
    """가중치, 제외키워드, 피드백 등 전체 키워드 설정 로드"""
    kw = load_json(drive, KEYWORDS_FILE) or {}
    weights = kw.get("weights", {
        "지원대상": 3, "사업성격": 2, "기업키워드": 2,
        "핵심수요": 3, "업종역방향": 1, "소재지가산": 3, "세그먼트": 2
    })
    return {
        "weights":          weights,
        "exclude_keywords": kw.get("exclude_keywords", []),
        "feedback":         kw.get("feedback", {}),
        "star3_threshold":  kw.get("star3_threshold", 20),
        "star2_threshold":  kw.get("star2_threshold", 10),
    }

# ── 유틸 ─────────────────────────────────────────────
def strip_html(html):
    return re.sub(r'<[^>]+>', ' ', html or '').strip()

def parse_deadline(s):
    try:
        end = s.split('~')[-1].strip()
        return datetime.strptime(re.sub(r'\.', '-', end), "%Y-%m-%d")
    except: return None


# ── 마감일 알림 파일(.ics) ─────────────────────────────
# 구독형 캘린더로는 기업에게 알림이 가지 않는다. 구독한 캘린더의 알림은
# 기본이 꺼짐이고, 이벤트에 넣은 reminders 는 캘린더 주인에게만 적용된다.
#
# .ics 는 구독이 아니라 복사다. 기업이 열어서 추가하면 '자기 일정'이 되고
# 파일에 같이 담긴 VALARM 이 그대로 자기 알림이 된다.
# 아웃룩·네이버·구글·애플 모두 VALARM 을 읽는다. 로그인도 필요 없다.

def _ics_esc(t):
    """RFC 5545 — 쉼표·세미콜론·역슬래시·줄바꿈을 피한다."""
    return (str(t or '').replace('\\', '\\\\').replace(';', '\\;')
            .replace(',', '\\,').replace('\r\n', '\\n')
            .replace('\n', '\\n').replace('\r', '\\n'))


def _ics_fold(line):
    """한 줄이 75옥텟을 넘으면 접는다.

    바이트로 세되 글자 가운데서 자르지 않는다. 한글이 쪼개지면
    받는 쪽에서 깨진 글자가 나온다.
    """
    if len(line.encode('utf-8')) <= 73:
        return line
    parts, cur = [], b''
    for ch in line:
        e = ch.encode('utf-8')
        if len(cur) + len(e) > 73:
            parts.append(cur.decode('utf-8'))
            cur = b''
        cur += e
    if cur:
        parts.append(cur.decode('utf-8'))
    return '\r\n '.join(parts)


def _ics_deadline(n):
    """공고에서 마감일을 꺼낸다. 접수기간이 우선, 없으면 마감일 칸."""
    dl = parse_deadline(n.get('접수기간', '') or '')
    if dl:
        return dl
    raw = str(n.get('마감일', '') or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(re.sub(r'[./]', '-', raw)[:10], '%Y-%m-%d')
    except Exception:
        return None


def build_ics(company, notices, now=None):
    """안내한 공고의 마감일을 담은 .ics 를 만든다. 없으면 None.

    종일 일정으로 넣고 7일 전·3일 전 알림을 붙인다.
    UID 는 공고와 기업으로 고정해, 같은 공고를 다시 안내해도
    캘린더에서 하나로 합쳐지고 두 번 쌓이지 않는다.
    """
    import hashlib
    from datetime import timedelta as _td
    stamp = (now or datetime.utcnow()).strftime('%Y%m%dT%H%M%SZ')

    body = []
    for n in notices or []:
        dl = _ics_deadline(n)
        nm = str(n.get('공고명', '') or '').strip()
        if not dl or not nm:
            continue
        pid = str(n.get('공고ID', '') or n.get('pblancId', '') or '')
        key = hashlib.md5((pid or nm).encode('utf-8')).hexdigest()[:16]
        who = hashlib.md5(str(company).encode('utf-8')).hexdigest()[:8]
        link = str(n.get('공고링크', '') or '')
        desc = f"주관기관: {n.get('주관기관','')}\n원스톱 스케일업이 안내드린 공고입니다.\n{link}"
        body += [
            'BEGIN:VEVENT',
            f'UID:{key}-{who}@kipcc.re.kr',
            f'DTSTAMP:{stamp}',
            f'DTSTART;VALUE=DATE:{dl.strftime("%Y%m%d")}',
            f'DTEND;VALUE=DATE:{(dl + _td(days=1)).strftime("%Y%m%d")}',
            f'SUMMARY:[마감] {_ics_esc(nm)}',
            f'DESCRIPTION:{_ics_esc(desc)}',
        ]
        if link:
            body.append(f'URL:{_ics_esc(link)}')
        body += ['TRANSP:TRANSPARENT']
        for days in (7, 3):
            body += ['BEGIN:VALARM', 'ACTION:DISPLAY',
                     f'TRIGGER:-P{days}D',
                     f'DESCRIPTION:[D-{days}] {_ics_esc(nm)}',
                     'END:VALARM']
        body.append('END:VEVENT')

    if not body:
        return None

    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0',
             'PRODID:-//KIPCC//onestop-scaleup//KO',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
             'X-WR-CALNAME:원스톱 스케일업 공고 마감일',
             'X-WR-TIMEZONE:Asia/Seoul'] + body + ['END:VCALENDAR']
    return ('\r\n'.join(_ics_fold(x) for x in lines) + '\r\n').encode('utf-8')


def ics_event_count(ics_bytes):
    return ics_bytes.decode('utf-8').count('BEGIN:VEVENT') if ics_bytes else 0

def notice_base_title(t):
    """공고 제목에서 '수정·재공고' 표시만 걷어내 같은 공고인지 본다.

    기업마당은 공고를 고치면 새 pblancId 로 다시 올린다. 제목에만
    '변경 공고', '수정공고' 가 붙는다. ID 로만 보면 다른 공고라
    중복 방지를 빠져나간다. 지난 446건에서 14건이 그렇게 나갔다.

        … 참여기업 모집 공고
        … 참여기업 모집 변경 공고      →  같은 공고로 본다

    차수와 분기는 남긴다. 3차를 받은 기업에게 4차는 새 기회다.

        3차 중소기업 CBAM대응 인프라구축 …
        4차 중소기업 CBAM대응 인프라구축 …   →  다른 공고로 본다
    """
    t = str(t or '')
    t = re.sub(r'^\[[^\]]*\]\s*', '', t)                       # [지역] 머리말
    t = re.sub(r'\d{4}\s*년도?', '', t)                          # 2026년
    t = re.sub(r'수정\s*공고|재\s*공고|변경\s*공고|정정\s*공고', '공고', t)
    t = re.sub(r'수정|정정|게시\s*안내', '', t)
    t = re.sub(r'[^0-9A-Za-z가-힣]', '', t).lower()
    return re.sub(r'(공고)+$', '공고', t)                          # 끝의 '공고' 반복


def company_key(name):
    """(주)·주식회사·띄어쓰기 차이를 지운 기업 이름."""
    return re.sub(r'\s|\(주\)|\(유\)|주식회사|㈜', '', str(name))


def presend_checks(approved, df_hist, df_companies, test_mode, today=None):
    """발송 직전 점검.

    경우의 수를 미리 다 떠올리는 건 불가능하다. 대신 '항상 참이어야 하는 것'
    몇 가지를 적어두고 매번 본다. 어긋나면 그때 드러난다.

    실제로 조용히 지나간 적이 있는 것들이다.
      · 같은 사업이 '수정공고'로 다시 나간 일 17건 (ID 가 달라 검사를 빠져나감)
      · 한 메일에 비슷한 공고 둘 (창조 엔지니어링 9/29)
      · 죽은 캘린더에 수백 번 404 — 반환값을 안 봐서 몇 달간 안 보였다

    돌려주는 것: [(수준, 제목, 설명), ...]
      수준 '치명' 이 하나라도 있으면 발송을 막는다.
    """
    import datetime as _dt
    today = today or _dt.date.today()
    out = []

    if not approved:
        return [('치명', '승인된 공고가 없습니다', "'공고·매칭 → 검토 & 승인'에서 먼저 승인해 주십시오.")]

    rows = pd.DataFrame(approved)
    ck = company_key
    bt = notice_base_title

    # ── ① 같은 기업에 같은 공고 ────────────────────────
    if df_hist is not None and not df_hist.empty and 'pblancId' in df_hist.columns:
        seen_id = set(zip(df_hist['기업명'].astype(str), df_hist['pblancId'].astype(str)))
        hit = [(a, b) for a, b in zip(rows['기업명'].astype(str),
                                      rows['공고ID'].astype(str)) if (a, b) in seen_id]
        out.append(('치명' if hit else '통과',
                    f'전에 보낸 공고가 또 들어감 {len(hit)}건',
                    '같은 기업에 같은 공고를 다시 보내는 것입니다.' if hit
                    else '같은 기업·같은 공고 중복 없음'))

        if '공고명' in df_hist.columns:
            seen_bt = set(zip(df_hist['기업명'].map(ck), df_hist['공고명'].map(bt)))
            hit2 = rows[[(ck(a), bt(b)) in seen_bt
                         for a, b in zip(rows['기업명'], rows['공고명'])]]
            out.append(('치명' if len(hit2) else '통과',
                        f'수정·재공고로 같은 사업이 또 들어감 {len(hit2)}건',
                        ' / '.join(str(x)[:40] for x in hit2['공고명'].head(3)) if len(hit2)
                        else '제목이 사실상 같은 공고 없음'))

    # ── ② 한 통 안에서 비슷한 공고 둘 ──────────────────
    rows['_ck'] = rows['기업명'].map(ck)
    rows['_bt'] = rows['공고명'].map(bt)
    dd = rows.groupby(['_ck', '_bt']).size()
    dd = dd[dd > 1]
    out.append(('치명' if len(dd) else '통과',
                f'한 기업에 비슷한 공고 둘 이상 {len(dd)}건',
                '같은 메일 안에 거의 같은 공고가 함께 들어갑니다.' if len(dd)
                else '한 통 안 중복 없음'))

    # ── ③ 마감 ────────────────────────────────────────
    # 마감일이 전부 비어 있으면 .dt.date 가 datetime64 로 남아 date 와 비교가
    # 안 된다(TypeError). '세부사업별 상이' 공고만 승인된 회차가 실제로 그렇다.
    # Timestamp 로 비교하고 빈 값은 notna 로 걸러낸다.
    dl  = pd.to_datetime(rows.get('마감일'), errors='coerce')
    _t0 = pd.Timestamp(today)
    _ok_dl = dl.notna()
    past = int((_ok_dl & (dl < _t0)).sum())
    near = int((_ok_dl & (dl >= _t0) & (dl <= _t0 + pd.Timedelta(days=3))).sum())
    out.append(('치명' if past else '통과',
                f'마감이 지난 공고 {past}건',
                '이미 끝난 공고를 안내하게 됩니다.' if past else '마감 지난 공고 없음'))
    out.append(('경고' if near else '통과',
                f'3일 안에 마감되는 공고 {near}건',
                '받고 나서 준비할 시간이 거의 없습니다.' if near else 'D-3 이내 없음'))

    # ── ④ 수신자 ──────────────────────────────────────
    if not test_mode and df_companies is not None and not df_companies.empty \
            and '이메일' in df_companies.columns:
        em = (df_companies.set_index(df_companies['기업명'].astype(str))['이메일']
              .astype(str).to_dict())
        noemail = sorted({c for c in rows['기업명'].astype(str)
                          if '@' not in em.get(c, '')})
        out.append(('치명' if noemail else '통과',
                    f'이메일이 없는 기업 {len(noemail)}개사',
                    ', '.join(noemail[:5]) if noemail else '수신자 주소 모두 확인'))

    # ── ⑤ 서로 안 맞는 숫자 ───────────────────────────
    n_co = rows['기업명'].nunique()
    out.append(('경고' if n_co == 0 else '통과',
                f'보낼 기업 {n_co}개사 · 공고 {len(rows)}건',
                f'기업당 평균 {len(rows)/max(n_co,1):.1f}건'))

    # ── ⑥ 승인했지만 메일에 안 실리는 공고 ────────────
    #     접수기간이 '세부사업별 상이' 이거나 '예산 소진시까지' 인 공고는
    #     can_include_notice 관문에서 빠진다. 승인 숫자만 보면 모른다.
    try:
        _drop, _byco = [], {}
        for _r in approved:
            _co = _r.get('기업명', '')
            _ok, _why = can_include_notice(_r, _co)
            _byco.setdefault(_co, [0, 0])
            _byco[_co][0] += 1
            if _ok:
                _byco[_co][1] += 1
            else:
                _drop.append(_why)
        import collections as _cl
        _dc = _cl.Counter(_drop)
        _empty = [c for c, (a, b) in _byco.items() if b == 0]
        out.append(('경고' if _drop else '통과',
                    f'승인했지만 메일에 안 실리는 공고 {len(_drop)}건',
                    ' · '.join(f'{k} {v}건' for k, v in _dc.most_common())
                    if _drop else '승인한 공고가 모두 실립니다'))
        # 빈손 기업은 발송 루프가 이미 건너뛴다(빈 메일 방지). 막을 일이 아니라
        # 알려줄 일이다. 한 곳이 막혀 49개사 발송이 멈추는 쪽이 더 나쁘다.
        out.append(('경고' if _empty else '통과',
                    f'공고가 한 건도 안 실리는 기업 {len(_empty)}개사 — 발송에서 자동 제외됩니다',
                    (', '.join(_empty[:6]) + (' 외' if len(_empty) > 6 else '')
                     + ' · 보낼 공고를 더 승인하시거나, 그대로 두시면 이 기업만 건너뜁니다')
                    if _empty else '모든 기업에 공고가 한 건 이상 실립니다'))
    except Exception as _ge:
        out.append(('경고', '메일 수록 여부를 확인하지 못했습니다', str(_ge)[:80]))

    return out


def render_presend_checks(checks):
    """점검 결과를 화면에 올리고, 막아야 하면 True 를 돌려준다."""
    bad = [c for c in checks if c[0] == '치명']
    warn = [c for c in checks if c[0] == '경고']
    ok = [c for c in checks if c[0] == '통과']

    if bad:
        st.error(f"⛔ 보내기 전에 풀어야 할 것이 {len(bad)}가지 있습니다.")
        for _, t, d in bad:
            st.markdown(f"- **{t}** — {d}")
    elif warn:
        st.warning(f"⚠️ 확인하실 것이 {len(warn)}가지 있습니다. 보내실 수는 있습니다.")
    else:
        st.success("✅ 점검 통과 — 보내셔도 됩니다.")

    with st.expander(f"점검 내역 {len(checks)}가지 보기", expanded=bool(bad)):
        for lv, t, d in checks:
            mark = {'치명': '⛔', '경고': '⚠️', '통과': '✅'}[lv]
            st.markdown(f"{mark} **{t}**")
            st.caption(f"　　{d}")
    return bool(bad)


def score_notice(notice, row, already_sent, HIGH, MID, feedback=None, kw_config=None,
                 sent_titles=None):
    pid = notice.get('pblancId', '')
    if (row['기업명'], pid) in already_sent: return None
    # 같은 사업이 수정·재공고로 다시 올라온 경우 — ID 는 달라도 이미 보낸 것으로 본다
    if sent_titles is not None:
        if (company_key(row['기업명']),
            notice_base_title(notice.get('공고명', ''))) in sent_titles:
            return None
    dl = notice.get('마감일', '')
    if dl:
        try:
            days_left = (datetime.strptime(dl, '%Y-%m-%d') - datetime.today()).days
            if days_left < 0: return None   # 이미 마감
            if days_left <= 3: return None  # D-3 이내 제외 (발송 후 신청 시간 부족)
        except Exception:
            if dl < datetime.today().strftime("%Y-%m-%d"): return None
    if str(row.get('수출실적',''))=='아니오' and '수출' in str(notice.get('분야','')): return None

    text = " ".join([str(notice.get(k,'')) for k in ['공고명','사업개요','전문내용','해시태그','주관기관','지원대상']])

    # ── 제외 키워드 필터 — 공고명만 본다 ────────────────
    # 예전에는 text(전문 수천 자 포함)에서 찾았다. 그러면 본문에 한 번 스친
    # 단어 때문에 멀쩡한 조달 공고가 통째로 사라진다. 실측(2026-10-27):
    #   '소상공인' → 공고명 22종 vs 전문까지 79종
    #   '고용'     → 공고명  8종 vs 전문까지 58종
    # 제외 기준(개선방안 3쪽)은 '그 대상만을 위한 사업'을 빼라는 것이지
    # 그 말이 언급된 사업을 빼라는 것이 아니다. 그래서 제목으로 판단한다.
    if kw_config:
        title = str(notice.get('공고명', ''))
        if not any(g in title for g in EXCL_GUARD):
            for excl_kw in kw_config.get("exclude_keywords", []):
                if excl_kw and excl_kw in title:
                    return None  # 제외 대상 전용 공고 → 즉시 제거

    # ── 업종 전시회 — 업종이 다르면 보내지 않는다 ────────
    if fair_industry_mismatch(notice, row):
        return None

    # 가중치 설정 (없으면 기본값)
    W = kw_config.get("weights", {}) if kw_config else {}
    W_TARGET = W.get("지원대상", 3)
    W_TYPE   = W.get("사업성격", 2)
    W_KW     = W.get("기업키워드", 2)
    W_DEMAND = W.get("핵심수요", 3)
    W_IND    = W.get("업종역방향", 1)
    W_LOC    = W.get("소재지가산", 3)
    W_SEG    = W.get("세그먼트", 4)

    # ── 강화된 부정 필터 — 자격 미달이 명확한 공고 사전 제거 ──
    # 업력 제한: 창업 초기 공고에 오래된 기업 매칭 방지
    biz_start = str(row.get('설립연도', row.get('창업연도', '')))
    if biz_start and biz_start.isdigit():
        biz_age = datetime.today().year - int(biz_start)
        # 공고에 "창업 7년 이내" 등 업력 제한이 명시된 경우
        age_patterns = re.findall(r'창업\s*(\d+)년\s*이내', text)
        for ap in age_patterns:
            if biz_age > int(ap):
                return None  # 업력 초과 → 제외
        startup_only = any(p in text for p in ['예비창업자', '창업팀', '예비 창업'])
        if startup_only:
            return None  # 예비창업자 전용 공고

    # 매출 규모 제한 (공고에 "매출 N억 이하" 명시 시 대형 기업 제외)
    revenue_str = str(row.get('매출규모', row.get('매출액', '')))
    if revenue_str and '억' in revenue_str:
        try:
            rev_amt = float(re.search(r'([\d.]+)', revenue_str).group(1))
            revenue_limits = re.findall(r'매출액?\s*(\d+)억\s*원?\s*이하', text)
            for rl in revenue_limits:
                if rev_amt > float(rl) * 1.5:  # 1.5배 여유 허용
                    return None
        except Exception:
            pass

    # ── 기업 세그먼트 자동 분류 ───────────────────────────
    # 기업 프로파일에 따라 3개 세그먼트로 분류 → 세그먼트별 점수 보정
    export_yn  = str(row.get('수출실적','')) not in ['아니오','','nan']
    trl_str    = str(row.get('TRL단계',''))
    trl_high   = any(t in trl_str for t in ['8','9'])
    trl_low    = any(t in trl_str for t in ['4','5','6'])
    demand     = str(row.get('핵심수요태그',''))
    has_procurement_tag = any(k in demand for k in ['혁신제품','G-PASS','우수조달','시범구매','MAS'])
    has_export_tag      = any(k in demand for k in ['해외조달','수출바우처','해외전시','해외진출'])
    has_rd_tag          = any(k in demand for k in ['기술사업화','특허','R&D','기술개발'])

    # 세그먼트 판정 (우선순위 순)
    if has_procurement_tag or (trl_high and not export_yn):
        segment = 'procurement'   # 조달강화형: 혁신제품·G-PASS 보유, 국내 조달 집중
    elif export_yn or has_export_tag:
        segment = 'export'        # 해외진출형: 수출 실적 있거나 해외 수요 명확
    elif trl_low or has_rd_tag:
        segment = 'rd'            # 기술개발형: TRL 낮거나 기술사업화 수요
    else:
        segment = 'general'       # 일반형

    # 세그먼트별 사업성격 점수 보정값 (매칭 시 type 카테고리에 가산)
    SEGMENT_BOOST = {
        'procurement': {'공공조달': 4, '해외진출': 2, '기술개발': 0, '금융융자': 0},
        'export':      {'해외진출': 4, '마케팅홍보': 2, '공공조달': 1, '인증특허': 1},
        'rd':          {'기술개발': 4, '인증특허': 2, '금융융자': 2, '공공조달': 0},
        'general':     {'공공조달': 1, '해외진출': 1, '기술개발': 1, '금융융자': 1},
    }
    seg_boost = SEGMENT_BOOST.get(segment, {})

    # ── TRL 필터: 8-9단계 기업과 R&D 공고 ──────────────
    # 예전에는 R&D 단어만 보이면 무조건 탈락시켰다. 접수 중 공고 1,750건을 재보니
    # R&D 계열 단어가 걸리는 137건 중 69건(절반)이 사업화·상용화·판로도 함께 다룬다.
    # 순수 R&D 공고만 탈락시키고, 사업화를 겸하면 감점만 준다.
    rd_penalty = 0
    trl = str(row.get('TRL단계',''))
    if any(t in trl for t in ['8','9']):
        if any(kw in text for kw in ['R&D','연구개발','기술개발과제','기초연구','원천기술']):
            if any(kw in text for kw in ['사업화','상용화','판로','마케팅','수출']):
                rd_penalty = -4      # 사업화 겸용 → 순위만 낮춘다
            else:
                return None          # 순수 R&D 공고 → 종전대로 제외

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
            str(notice.get('전문내용','')),  # 전문내용도 소재지 판단에 반영
        ])
        co_region = next((r for r in REGIONS if r in location), None)

        import re as _re

        # ① 공고명 [] 패턴 최우선
        bracket_match = _re.search(r'\[([^\]]+)\]', notice_name)
        if bracket_match:
            bracket_text = bracket_match.group(1)
            bracket_regions = [r for r in REGIONS if r in bracket_text]
            if bracket_regions:
                notice_region_tag = f"[{bracket_text}]"
                if co_region:
                    aliases = REGION_ALIAS.get(co_region, [co_region])
                    if any(a in bracket_text for a in aliases):
                        location_score = 3
                    else:
                        location_score = -5

        # ② 주관기관이 지방자치단체
        elif co_region:
            organizer = str(notice.get('주관기관',''))
            org_regions = [r for r in REGIONS if r in organizer]
            if org_regions:
                notice_region_tag = f"주관기관({organizer[:10]})"
                aliases = REGION_ALIAS.get(co_region, [co_region])
                if any(a in organizer for a in aliases):
                    location_score = 2
                else:
                    location_score = -5  # -3 → -5 강화

        # ③ 전문내용 포함 전체 텍스트에서 "○○ 소재 기업" 패턴
        elif co_region:
            if '전국' not in notice_full and '전 지역' not in notice_full:
                sojaepat = _re.findall(r'([가-힣]{2,4}(?:도|시|군|구))\s*소재', notice_full)
                if sojaepat:
                    notice_region_tag = ", ".join(sojaepat[:2])
                    aliases = REGION_ALIAS.get(co_region, [co_region])
                    if any(any(a in s for a in aliases) for s in sojaepat):
                        location_score = 2
                    else:
                        location_score = -5  # -3 → -5 강화

                # ④ 신규: 전문에서 지역 직접 언급 패턴
                # "광주 소재", "경남 지역", "○○시에 위치한" 등
                if location_score == 0:
                    region_mentions = [r for r in REGIONS
                                       if _re.search(rf'{r}.{{0,6}}(?:소재|지역|소속|위치|관내|내)', notice_full)]
                    if region_mentions:
                        notice_region_tag = ", ".join(region_mentions[:2])
                        aliases = REGION_ALIAS.get(co_region, [co_region])
                        if any(any(a in rm for a in aliases) for rm in region_mentions):
                            location_score = 2
                        else:
                            location_score = -3

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

    # ── 기술키워드 역매핑 확장: 기업 키워드 → INDUSTRY_KW 카테고리 → 공고 키워드 검색 ──
    # 너무 일반적인 단어는 역매핑에서 제외 (거의 모든 공고에 등장해 변별력 없음)
    GENERIC_WORDS = {
        '시스템','솔루션','서비스','플랫폼','기술','개발','소프트웨어','SW',
        'IT','ICT','디지털','스마트','데이터','네트워크','클라우드','AI',
        '관리','지원','운영','구축','통합','연계','자동화','혁신',
    }
    tech_kws = [k.strip() for k in str(row.get('기술키워드','')).split(',') if k.strip() and k.strip()!='nan']
    expanded_industry_hits = []
    for tech_kw in tech_kws:
        kw_lower = tech_kw.lower().replace(' ', '')
        if len(kw_lower) < 3:
            continue  # 너무 짧은 키워드는 오매칭 위험
        for ind_cat, ind_kws in INDUSTRY_KW.items():
            matched_cat = False
            for ind_kw in ind_kws:
                ind_lower = ind_kw.lower().replace(' ', '')
                if len(ind_lower) >= 3 and (ind_lower in kw_lower or kw_lower in ind_lower):
                    matched_cat = True
                    break
            if matched_cat:
                # 일반 단어 제외 후 카테고리 키워드만 추출
                cat_hits = [
                    k for k in ind_kws
                    if k in text and len(k) >= 2 and k not in GENERIC_WORDS
                ]
                for h in cat_hits[:2]:
                    if h not in expanded_industry_hits:
                        expanded_industry_hits.append(h)

    for h in expanded_industry_hits:
        if h not in matched_co:
            matched_co.append(h)

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
    # 이 필터도 부처·기관 이름에 걸린다. '식품'이 농림축산식품부에, '농업'이
    # 한국농업기술진흥원에, '수산'이 해양수산부에 들어 있다. 그래서 실측상
    # 조달·혁신제품 공고 20종이 업종 공고로 오인돼 지워지고 있었다 —
    # 「혁신제품 지정제도 시행계획」, 「해양수산부 혁신제품 지정」,
    # 「공공조달 입찰 컨설팅」, 「조달청 벤처나라 추천」 같은 것들이다.
    if not any(g in str(notice.get('공고명', '')) for g in EXCL_GUARD):
        for ind_kw in INDUSTRY_SPECIFIC:
            if ind_kw in text and not any(
                ind_kw in kw or kw in ind_kw for kw in co_kws + demand_tags
            ):
                return None

    # ── 점수 계산 ────────────────────────────────────
    seg_score = sum(min(seg_boost.get(cat, 0), W_SEG) for cat in matched_type.keys())

    feedback_penalty = 0
    fb = feedback or (kw_config.get("feedback", {}) if kw_config else {})
    if fb:
        co_feedback = fb.get(row.get("기업명",""), {})
        for cat in matched_type.keys():
            reject_count = co_feedback.get(cat, 0)
            if reject_count >= 3:   feedback_penalty -= 6
            elif reject_count >= 2: feedback_penalty -= 3

    score = (
        len(sum(matched_target.values(), [])) * W_TARGET +
        len(sum(matched_type.values(),   [])) * W_TYPE   +
        len(matched_co)     * W_KW    +
        len(matched_demand) * W_DEMAND +
        ind_score * W_IND   +
        xs + (location_score * W_LOC // 3) + seg_score + feedback_penalty + rd_penalty
    )
    if matched_demand: score += 8   # 핵심수요 직접매칭 강력 보너스
    if score <= 0: return None

    # ── ④ 별점 판정 — 점수 기반 통합 ──────────────────
    star3_threshold = kw_config.get("star3_threshold", 18) if kw_config else 18
    star2_threshold = kw_config.get("star2_threshold",  8) if kw_config else 8

    hard_star3 = (
        bool(matched_demand)
        or ("조달기업특화" in matched_target and "공공조달" in matched_type)
        or ("조달기업특화" in matched_target and "해외진출" in matched_type)
        or ("수출기업특화" in matched_target and "해외진출" in matched_type)
        or (bool(matched_co) and "공공조달" in matched_type)
    )

    if hard_star3 or score >= star3_threshold:
        stars = "★★★"
    elif score >= star2_threshold:
        stars = "★★"
    else:
        return None

    # 소재지 불일치 시 별점 강등
    if location_score < 0:
        if stars == "★★★":   stars = "★★"
        elif stars == "★★":  stars = "★"
    if stars == "★": return None


    # ── 매칭 근거 텍스트 ──────────────────────────────
    target_str = " / ".join([f"{k}({','.join(v)})" for k,v in matched_target.items()])
    type_str   = " / ".join([f"{k}({','.join(v)})" for k,v in matched_type.items()])

    return {
        "기업명":       row['기업명'],
        "관련도":       stars,
        "점수":         score,
        "세그먼트":     segment,
        "공고ID":       pid,
        "공고명":       notice.get('공고명',''),
        "주관기관":     notice.get('주관기관',''),
        "접수기간":     notice.get('접수기간',''),
        "지원대상":     notice.get('지원대상',''),
        "마감일":       dl,
        "사업개요":     str(notice.get('사업개요',''))[:300]+"...",
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
        "기준제목":     notice_base_title(notice.get('공고명','')),
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

def _anthropic_post(headers, payload, max_tries=4):
    """Anthropic API 호출 + 재시도(backoff).
    429/5xx/타임아웃 시 2→5→10초 대기 후 재시도. Retry-After 헤더 존중."""
    import time as _time
    _waits = [2, 5, 10]
    last_err = None
    for _try in range(max_tries):
        try:
            resp = requests.post("https://api.anthropic.com/v1/messages",
                                 headers=headers, json=payload, timeout=45)
            if resp.ok:
                return resp, None
            if resp.status_code in (429, 500, 502, 503, 529) and _try < max_tries - 1:
                _ra = resp.headers.get('retry-after', '')
                try:    _wait = min(max(float(_ra), 1), 30) if _ra else _waits[min(_try, 2)]
                except Exception: _wait = _waits[min(_try, 2)]
                _time.sleep(_wait)
                last_err = f"HTTP {resp.status_code}"
                continue
            return resp, None            # 재시도 불가 오류(4xx 등)는 그대로 반환
        except requests.exceptions.RequestException as e:
            last_err = str(e)[:80]
            if _try < max_tries - 1:
                _time.sleep(_waits[min(_try, 2)])
                continue
    return None, last_err or "재시도 초과"

def get_detail_map_cached():
    """AI 분석용 전문 DB(pblancId → 전문내용 등) — 세션 캐시.
    실패 사유는 _detail_map_ai_err에 저장해 화면에 노출."""
    if not st.session_state.get('_detail_map_ai'):   # 빈 맵은 캐시 취급 안 함 → 재시도
        _dm = {}; _err = ''
        try:
            _dfd = pd.DataFrame()
            for _try_dm in range(2):                     # 대용량 다운로드 재시도
                _dfd = load_excel(_get_drive(), DETAIL_FILE)
                if not _dfd.empty:
                    break
            if _dfd.empty:
                _err = f"{DETAIL_FILE} 이 비어 있거나 로드 실패"
            elif 'pblancId' not in _dfd.columns:
                _err = f"{DETAIL_FILE} 에 pblancId 컬럼 없음 — 컬럼: {list(_dfd.columns)[:6]}"
            else:
                if '크롤링성공' in _dfd.columns:
                    _dfd = _dfd[_dfd['크롤링성공'] == 'Y']
                _dfd = _dfd.dropna(subset=['pblancId'])
                _dfd['pblancId'] = _dfd['pblancId'].astype(str).str.strip()
                _dfd = _dfd[_dfd['전문내용'].astype(str).str.len() >= 200] if '전문내용' in _dfd.columns else _dfd
                _dm = _dfd.set_index('pblancId').to_dict('index')
                if not _dm:
                    _err = "전문 DB 필터 후 0건 (크롤링성공=Y & 전문 200자 이상 없음)"
        except Exception as _e:
            _err = f"전문 DB 로드 예외: {str(_e)[:120]}"
        st.session_state['_detail_map_ai'] = _dm
        st.session_state['_detail_map_ai_err'] = _err
    return st.session_state['_detail_map_ai']

# AI에 넣는 공고 전문의 상한. 실측상 저장된 전문의 최대가 2,498자라 사실상 무제한이며,
# 예전 1,500자 절단으로 뒷부분이 잘리던 문제를 없앤다.
# 배포 검증용 빌드 태그. app.py 를 고칠 때마다 올린다 (형식: v[월일]-[순번]).
BUILD_TAG = "v1030-51"

NOTICE_TEXT_CAP = 8000

# 제외 키워드보다 센 말들 — 공고명에 이 말이 있으면 제외 키워드를 적용하지 않는다.
# 제외 키워드가 부처·기관 이름에 걸려 멀쩡한 조달 공고를 지우고 있었다(실측):
#   '축산' → 「농림축산식품부 혁신제품 지정기간 연장 공고」 4종
#   '농업' → 「조달청 벤처나라 추천 지원사업 모집공고(한국농업기술진흥원)」
#   '채용' → 「해외조달시장 전문인력 양성과정 연계 채용희망기업 모집 공고」
# 이 공고들은 선정기업이 가장 기다리는 종류다. 걸러서 잃는 쪽이 비싸다 —
# 남겨 두면 AI 가 읽고 판단한다(비용은 공고 1건당 한 번).
EXCL_GUARD = ('조달', '나라장터', '혁신제품', '혁신조달', '공공구매',
              '벤처나라', '혁신장터', '공공판로', '공공입찰')

# ── 업종 전시회 ──────────────────────────────────────
# 업종을 밝힌 전시회는 그 업종 기업에만 쓸모가 있다. 실측(2026-10-27):
#   「이탈리아 밀라노 광학 전시회(MIDO)」 → 23개사 배정, 광학 기업 0개사
#   「소방산업체 국제 전시회」            → 12개사 배정, 소방 기업 1개사
#   「튀르키예 의료기기 전시회」          →  7개사 배정, 전원 바이오·의료 ← 맞았다
# 의료기기만 맞은 이유는 업종 역매칭 필터(INDUSTRY_SPECIFIC)에 '의료'가 있어서다.
# '광학'·'소방'은 거기 없다. 다만 그 필터는 전문 수천 자를 보기 때문에 업종어를
# 더하면 본문에 한 번 스친 단어로 멀쩡한 공고가 날아간다. 그래서 전시회만
# 공고명으로 따로 가린다.
FAIR_KW = ('전시회', '박람회', '무역사절단', '상담회', '한국관', '공동관',
           '전시상담', '쇼케이스', '엑스포')

# 공고가 쓰는 말 : 명단(제품분야·기술키워드·핵심수요태그)이 쓰는 말.
# 둘이 다르다 — 공고는 「의료기기」, 명단은 「바이오·의료」라고 적는다.
# 단순 포함으로 비교하면 맞는 기업까지 날아간다(실측에서 7개사 전부 날아갔다).
FAIR_IND = {
    '광학':       ('광학', '렌즈', '안경', '광계측'),
    '안경':       ('안경', '광학', '렌즈'),
    '소방':       ('소방', '화재', '방재', '소화'),
    '조선':       ('조선', '선박', '해양', '항만'),
    '신발':       ('신발', '제화'),
    '철강':       ('철강', '금속', '주조', '압연'),
    '인쇄':       ('인쇄', '출판'),
    '공예':       ('공예',),
    '주얼리':     ('주얼리', '귀금속', '보석'),
    '귀금속':     ('귀금속', '주얼리', '보석'),
    '가구':       ('가구', '목재'),
    '도자':       ('도자', '세라믹', '요업'),
    '농기계':     ('농기계', '농업', '농축산'),
    '시멘트':     ('시멘트', '콘크리트', '건설'),
    '조명':       ('조명', 'LED', '광원'),
    '스포츠용품': ('스포츠', '레저'),
    '목재':       ('목재', '가구', '임산'),
    '의료기기':   ('의료', '바이오', '헬스', '진단'),
    '화장품':     ('화장품', '뷰티', '코스메'),
    '식품':       ('식품', '농축산', '수산'),
    '섬유':       ('섬유', '패션', '의류'),
    '패션':       ('패션', '의류', '섬유'),
    '의류':       ('의류', '패션', '섬유'),
    '완구':       ('완구', '장난감'),
    # 10/29 회차에서 구멍이 드러난 업종들. 처음 목록을 10/27 자료만 보고 짠 탓에
    # 실제로 올라오는 해외 전시회(정보보안·공작기계·판금·자동차부품)가 빠져 있었다.
    # 실측 피해: 정보보안 16개사 중 0개사 일치, 판금 7개사 중 0개사(전원 바이오·의료),
    # 공작기계 15개사 중 0개사, 자동차부품 4개사 중 0개사.
    '정보보안':   ('보안', '정보보안', '암호', '관제', '백신', '방화벽'),
    '보안':       ('보안', '관제', '암호', 'CCTV'),
    '공작기계':   ('공작기계', '절삭', '공구', '가공기', '머시닝'),
    '판금':       ('판금', '프레스', '용접', '금속', '판재'),
    '자동차부품': ('자동차', '모빌리티', '차량', '미래차', '부품'),
    '자동차':     ('자동차', '모빌리티', '차량', '미래차'),
    '반도체':     ('반도체', '웨이퍼', '패키징', '전기·전자'),
    '항공':       ('항공', '우주', '드론', '무인기'),
    '물류':       ('물류', '운송', '창고', '포장'),
    '에너지':     ('에너지', '전력', '태양광', '배터리', '수소'),
}

# 한 기업이 한 회차에 받을 해외 전시회 공고의 최대 건수.
# 업종어 목록은 매 회차 새 업종을 못 따라간다 — 목록에 없는 전시회가 또 올라오면
# 12칸을 통째로 먹는다(10/29 실측: 3건 이상 받은 기업 12개사, 최다 5건).
# 목록과 별개로 상한을 둬서 피해를 여기서 멈춘다.
FAIR_MAX_PER_CO = 2


def is_fair_notice(title):
    """해외 전시회·박람회 참가 모집 공고인가. 상한을 세는 데 쓴다."""
    t = str(title or '')
    if any(g in t for g in EXCL_GUARD):
        return False
    return any(f in t for f in FAIR_KW)


def fair_industry_mismatch(notice, row):
    """업종을 밝힌 전시회인데 기업 업종이 아니면 True.

    업종을 안 밝힌 일반 전시회(「베트남 하노이 무역상품 전시상담회」)는
    건드리지 않는다 — 어느 업종이든 갈 수 있는 자리다."""
    title = str(notice.get('공고명', '') if notice is not None else '')
    if any(g in title for g in EXCL_GUARD):
        return False
    if not any(f in title for f in FAIR_KW):
        return False
    wanted = [w for k, ws in FAIR_IND.items() if k in title for w in ws]
    if not wanted:
        return False
    # row 는 pandas Series 다 — `row or {}` 로 쓰면 ValueError 가 난다
    # (Series 의 진리값은 모호하다). get 만 쓴다.
    prof = " ".join(str(row.get(c, '') or '') if row is not None else ''
                    for c in ('제품분야', '기술키워드', '핵심수요태그'))
    return not any(w in prof for w in wanted)

# ⚡ 일괄 AI 분석을 시작하려면 매칭 공고 중 이 비율 이상이 전문을 갖고 있어야 한다.
# 예전에는 1건만 겹쳐도 통과해서, 전문 없는 공고가 요약(300자)만으로 판정됐다.
FULLTEXT_MIN_COVERAGE = 0.7

# 기업마당 페이지를 통째로 긁은 탓에 모든 전문 앞에 메뉴가, 39%에 푸터가 붙어 있다.
# 실측: 앞 네비 10.6% + 뒤 푸터 4.9% = 전체 분량의 15.5%가 공고와 무관한 문자열.
_RE_NOTICE_HEAD = re.compile(r'소관부처|사업개요|신청기간')
_RE_NOTICE_FOOT = re.compile(r'자료이용 및 저작권보호|웹접근성정책|Copyright|'
                             r'중소벤처기업연구원 시스템문의|자주하는 질문|개인정보처리방침')

# ── AI 판정 버전 ──────────────────────────────────────
# 캐시 키(기업명_공고ID)는 그대로 두고, 판정 결과 안에 어떤 입력으로 뽑았는지를
# 기록한다. 프로필·전문·프롬프트가 바뀌면 '재분석 대상'으로 표시만 하고
# 자동 실행하지 않는다 (비용이 나가는 일은 담당자가 누를 때만).
AI_PROMPT_VER = "2026-10-27a"          # claude_analyze 프롬프트를 고칠 때 올린다
_PROFILE_KEYS = ('소재지', '기업유형', '관심사업분야', '제품분야', '기술키워드',
                 '핵심수요태그', '수출실적', 'TRL단계', '매출규모', '설립연도',
                 '입찰참가자격', '물품식별번호', '특허현황', '상용화단계', '혁신제품의향')

def _short_hash(text, n=8):
    import hashlib
    return hashlib.md5(str(text or '').encode('utf-8')).hexdigest()[:n]

def profile_hash(company_info):
    """기업 프로필 핵심 항목의 해시 — 프로필이 바뀌면 값이 바뀐다."""
    return _short_hash('|'.join(str((company_info or {}).get(k, '') or '')
                                for k in _PROFILE_KEYS))

def ai_input_version(company_info, notice_info):
    """이 판정이 어떤 입력으로 나왔는지."""
    return {'_v_profile': profile_hash(company_info),
            '_v_notice':  _short_hash(clean_notice_text(
                (notice_info or {}).get('전문내용', '') or
                (notice_info or {}).get('사업개요', ''))),
            '_v_prompt':  AI_PROMPT_VER}

def ai_version_stale(res, company_info, notice_info):
    """캐시된 판정이 지금 입력과 어긋나는가. 버전 정보가 없는 옛 판정은
    '알 수 없음'으로 보고 건드리지 않는다(False)."""
    if not isinstance(res, dict) or res.get('error') or not res.get('_v_prompt'):
        return False
    cur = ai_input_version(company_info, notice_info)
    return any(res.get(k) != cur[k] for k in cur)

def clean_notice_text(text):
    """공고 전문에서 사이트 네비게이션·푸터를 걷어낸다.
    제거 후 200자 미만이 되면(실측 0건) 원문을 그대로 돌려준다 — 내용 유실 방지."""
    t = re.sub(r'\s+', ' ', str(text or '')).strip()
    if len(t) < 200:
        return t
    _h = _RE_NOTICE_HEAD.search(t)
    _f = _RE_NOTICE_FOOT.search(t)
    core = t[_h.start() if _h else 0: _f.start() if _f else len(t)].strip()
    return core if len(core) >= 200 else t

def enrich_for_ai(nd):
    """매칭 결과 행(300자 요약뿐)에 크롤링 전문을 병합해 AI에 전달.
    — 매칭 단계와 달리 AI 분석 단계에는 전문이 전달되지 않던 문제 보완."""
    try:
        pid = str(nd.get('공고ID', '') or nd.get('pblancId', '')).strip()
        if not pid:
            return nd
        d = get_detail_map_cached().get(pid)
        if d:
            full = clean_notice_text(d.get('전문내용', ''))
            if len(full) >= 200:
                nd['전문내용'] = full
            for _k in ('지원금액', '선정규모'):
                if d.get(_k) and not nd.get(_k):
                    nd[_k] = d[_k]
    except Exception:
        pass
    return nd

_RE_NOTICE_DATE = re.compile(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})')

# 접수기간에서 날짜를 못 찾는 공고를 메일에 실을지.
# 실측(800건): 56%가 날짜 없음 — '예산 소진시까지' 152 · '상시 접수' 99 ·
# '세부사업별 상이' 67 · '모집 완료시' 33 · '선착순 접수' 27 · '추후 공지' 24 등.
# 이미 예산이 소진됐거나 아직 열리지 않았을 수 있어 메일에서는 제외한다.
# (매칭·검토 화면에는 그대로 보이고 메일에만 안 나간다)
REQUIRE_NOTICE_DATE = True

# 이미 끝났을 수 있는 접수 표기. 빈손 폴백에서도 이건 끝까지 내보내지 않는다.
# 이미 끝났을 수 있는 표기 — 본 공고·참고 공고 어디에도 내보내지 않는다.
# '모집 마감(시)'는 '모집 완료(시)'와 같은 뜻인데 패턴에서 빠져 있었다.
_RE_RISKY_PERIOD = re.compile(
    r'예산\s*소진|모집\s*완료|모집\s*마감|소진\s*시|선착순|조기\s*마감')
# 마감 위험이 구조적으로 없는 표기 — 날짜가 없어도 본 공고로 안내할 수 있다.
_RE_OPEN_PERIOD = re.compile(r'상시\s*접수|수시\s*접수|상시\s*모집|연중\s*수시')

def notice_period_risky(n):
    """'예산 소진시까지'처럼 이미 마감됐을 수 있는 표기인가."""
    return bool(_RE_RISKY_PERIOD.search(f"{n.get('마감일','')} {n.get('접수기간','')}"))


def notice_period_open(n):
    """'상시 접수'처럼 마감 위험이 없는 표기인가.

    notice_period_risky() 를 먼저 통과한 공고에만 의미가 있다 —
    '상시 접수(예산 소진시까지)' 같은 혼합 표기는 위험 쪽이 이겨야 한다."""
    return bool(_RE_OPEN_PERIOD.search(f"{n.get('마감일','')} {n.get('접수기간','')}"))

def notice_deadline_date(n):
    """공고의 마감일을 date로. 마감일 → 접수기간 끝 순으로 찾고, 없으면 None."""
    from datetime import date as _date
    for _src in (n.get('마감일', ''), n.get('접수기간', '')):
        _ms = _RE_NOTICE_DATE.findall(str(_src or ''))
        if _ms:
            _y, _mo, _dd = _ms[-1]
            try:
                return _date(int(_y), int(_mo), int(_dd))
            except ValueError:
                return None
    return None

def deadline_label(n):
    """카드에 찍을 접수기간 문구. 날짜가 없을 때 '상시'로 뭉개면
    '예산 소진시까지'인 공고가 상시 접수처럼 보인다 — 원문을 그대로 쓴다.

    '2026-10-19' 보다 '10/19(일) · D-6' 이 한눈에 읽힌다. 요일은 영업일 감각을
    주고, D-day는 암산을 덜어준다. 다만 수신자가 며칠 뒤 열면 D-day가 어긋나므로
    날짜가 주(主)이고 D-day는 뒤에 붙는 보조 표기다. 해가 바뀌는 공고만 연도를 쓴다."""
    from datetime import date as _date
    _d = notice_deadline_date(n)
    if _d:
        _wd = '월화수목금토일'[_d.weekday()]
        _today = _date.today()
        _head = (f"마감 {_d.month}/{_d.day}({_wd})" if _d.year == _today.year
                 else f"마감 {_d.year}.{_d.month}/{_d.day}({_wd})")
        _left = (_d - _today).days
        if _left == 0:
            return f"{_head} · 오늘 마감"
        if 0 < _left <= 30:
            return f"{_head} · D-{_left}"
        return _head
    _rp = str(n.get('접수기간', '') or '').strip()
    if not _rp:
        return "접수기간 확인 필요"
    # '상시 접수'에 접두사를 또 붙이면 '접수 상시 접수'가 된다.
    return _rp if ('접수' in _rp or '모집' in _rp) else f"접수 {_rp}"


def deadline_urgent(n):
    """마감을 붉게 강조할 것인가 — D-3 이내만.

    이번 회차 실측: 승인 63건 중 D-7 이내가 40건(63%)이고 그중 37건이 같은 날
    (10/19)이었다. D-7을 기준 삼으면 카드 대부분이 붉어져 경고가 무의미해진다."""
    from datetime import date as _date
    _d = notice_deadline_date(n)
    return bool(_d) and 0 <= (_d - _date.today()).days <= 3

def _notice_open(n, _ref=None):
    """발송 시점 기준으로 접수 중인 공고인지 검사.
    날짜가 없으면(상시 등) 여기서는 통과시키고, 제외 여부는
    can_include_notice()가 REQUIRE_NOTICE_DATE로 따로 판단한다."""
    from datetime import date as _date
    _ref = _ref or _date.today()
    _dl_txt = str(n.get('마감일', '') or '').strip()
    if _dl_txt in ('마감', '종료', '접수마감', '모집마감', '마감됨'):
        return False
    _d = notice_deadline_date(n)
    return True if _d is None else _d >= _ref

# 「설립 7년 이하」·「업력 7년 이상」처럼 업력이 걸린 공고를 찾아낸다.
# 선정기업 명단에 설립연도가 없어서(2026-05 신청서에 문항 자체가 없었다)
# AI 가 자격을 못 가리고 전부 '검토'로 올린다. 그 상태로 일괄 승인하면
# 자격 미달 기업에 메일이 나가므로, 요건 문장을 승인 버튼 앞에 꺼내 보인다.
_RE_TENURE = re.compile(
    r'(?:설립|업력|창업|존속)[^.\n]{0,12}?(\d+)\s*년\s*(이하|이내|미만|이상|초과)'
    r'|(\d+)\s*년\s*(이하|이내|미만|이상|초과)[^.\n]{0,8}?(?:설립|업력|창업)')


def notice_tenure_note(rows, ai_cache):
    """공고에 걸린 AI 판정에서 업력 요건 문장을 뽑는다. 없으면 ''.

    rows 는 같은 공고의 (기업, 공고) 행들. AI 주의사항·판단근거는 기업마다
    따로 쓰이므로 가장 많이 나온 표현을 고른다 — 한 기업 분석의 말버릇에
    끌려가지 않게."""
    if not ai_cache:
        return ''
    from collections import Counter as _C
    _hits = _C()
    for _r in rows:
        _k = f"{_r.get('기업명','')}_{_r.get('공고ID','')}"
        _a = ai_cache.get(_k) or {}
        for _f in ('주의사항', '판단근거'):
            for _sent in re.split(r'[.\n]', str(_a.get(_f, '') or '')):
                _m = _RE_TENURE.search(_sent)
                if _m:
                    _n = _m.group(1) or _m.group(3)
                    _w = _m.group(2) or _m.group(4)
                    _hits[f"{_n}년 {_w}"] += 1
    return _hits.most_common(1)[0][0] if _hits else ''


def can_include_notice(notice, company, ai_cache=None, review_state=None, ref=None,
                       allow_undated=False):
    """이 공고를 이 기업 메일에 넣어도 되는가 — 메일 수록 자격의 단일 관문.

    승인 카드·참고 공고·업종 강등분·👁 미리보기·🟡 자동 보완 후보가 전부 여기를 거친다.
    메일에 공고가 들어가는 경로를 새로 만들면 반드시 이 함수를 통과시킬 것.

    검사: ① 공고ID 있음 ② 현재 회차에서 ✕가 아님 ③ AI 자격충족이 X가 아님
          ④ _notice_open()으로 마감이 지나지 않음
    반환: (ok, reason) — reason은 제외 사유(진단·집계용), 통과면 ''.
    """
    _pid = str(notice.get('공고ID', '') or notice.get('pblancId', '')).strip()
    if not _pid:
        return False, '공고ID 없음'
    _co = str(company or notice.get('기업명', '') or '').strip()
    _key = f"{_co}_{_pid}"
    _rv = st.session_state.get('review_state', {}) if review_state is None else review_state
    if (_rv or {}).get(_key, '') == '✕':
        return False, '담당자 제외(✕)'
    _ai = st.session_state.get('ai_analysis', {}) if ai_cache is None else ai_cache
    if (_ai or {}).get(_key, {}).get('자격충족', '') == 'X':
        return False, '자격 미충족'
    if not _notice_open(notice, ref):
        return False, '마감 경과'
    if notice_deadline_date(notice) is None:
        # 소진형·선착순은 이미 끝났을 수 있다 — 본 공고든 참고 공고든 내보내지 않는다.
        if notice_period_risky(notice):
            return False, '소진·선착순 마감형'
        # '상시 접수'는 마감 위험이 구조적으로 없으므로 날짜가 없어도 본 공고로 안내한다.
        # REQUIRE_NOTICE_DATE 의 취지는 '마감된 공고를 보내지 말자'인데, 날짜가 없다는
        # 이유만으로 상시 접수까지 막고 있었다(실측: 접수 중 공고 108건이 무날짜이고
        # 그중 23건이 상시·수시 접수였다).
        if notice_period_open(notice):
            return True, ''
        # 그 밖의 불명(세부사업별 상이·추후 공지 등)은 참고 공고에서만 허용한다.
        if not allow_undated and REQUIRE_NOTICE_DATE:
            return False, '접수기간 불명'
    return True, ''

def _region_cut_result(row):
    """타지역 한정 공고 — AI 호출 없이 규칙으로 비추천 처리."""
    _rg = str(row.get('공고지역', '') or '해당 지역')
    return {'추천여부': '비추천', '적합도': '낮음', '한줄요약': '타지역 한정 공고',
            '업종일치': '△', '자격충족': '△', '지역적합': 'X', '수요일치': '△',
            '판단근거': f"'{_rg}' 지역 한정 공고로 귀사 소재지가 신청 대상 지역에 해당하지 않습니다. (규칙 자동 판정 — AI 호출 생략)",
            '주의사항': '없음', '_지역컷': True}

_RE_NOTICE_VARIANT = re.compile(r'(신규지정|기간연장|규격추가|재공고|추가모집|연장)')

def notice_base_key(name):
    """같은 사업의 변형 공고(신규지정/기간연장/규격추가 등)를 묶기 위한 정규화 키."""
    t = re.sub(r'\[[^\]]*\]', '', str(name or ''))
    t = _RE_NOTICE_VARIANT.sub('', t)
    t = re.sub(r'공고\s*$', '', t.strip())
    return re.sub(r'\s+', '', t)

def group_related_notices(notices):
    """같은 사업 변형 공고를 대표 1건으로 묶고 나머지는 rep['_related']에 보관.
    대표 선정: 신규지정 우선 → 점수 높은 순. 반환 목록은 점수 내림차순."""
    groups = {}
    for n in notices:
        groups.setdefault(notice_base_key(n.get('공고명', '')), []).append(n)
    out = []
    for g in groups.values():
        if len(g) == 1:
            out.append(g[0]); continue
        g2 = sorted(g, key=lambda x: (0 if '신규지정' in str(x.get('공고명', '')) else 1,
                                      -float(x.get('점수', 0) or 0)))
        rep_n = dict(g2[0]); rep_n['_related'] = g2[1:]
        out.append(rep_n)
    out.sort(key=lambda x: -float(x.get('점수', 0) or 0))
    return out

# 메일에 나가는 추천 이유에서 단정적 표현을 걷어낸다.
# 공고 본문에 자격 조건이 21.6%만 있는 상황이라 '정확히·완벽히'라고 쓸 근거가 약하다.
# 부사만 지우므로 문장 구조는 그대로 남는다.
#   "분야와 정확히 일치합니다"  → "분야와 일치합니다"
#   "목적과 완벽히 부합합니다"  → "목적과 부합합니다"
_SOFTEN_RULES = [
    (re.compile(r'정확히\s*'), ''),
    (re.compile(r'완벽(?:히|하게)\s*'), ''),
    (re.compile(r'확실히\s*'), ''),
    (re.compile(r'반드시\s*'), ''),
    (re.compile(r'매우\s*'), ''),
    (re.compile(r'완벽한\s*'), '적합한 '),
    (re.compile(r'최적의\s*'), '적합한 '),
    (re.compile(r'모두\s+충족'), '충족'),
    (re.compile(r'전부\s+충족'), '충족'),
]

# 메일 카드에 넣는 길이 상한. 예전에는 상한에서 그냥 잘라 문장이 뚝 끊겼다
# (주의사항 736건 중 332건이 90자에서 잘림).
# 💡 추천 사유 / ⚠️ 주의사항의 표시 상한.
# 실측(2026-10-13 회차 승인 80건): 원문은 판단근거 259자 · 주의사항 128자로
# 사유가 2배 긴데, 상한이 120/160 이라 화면에서는 주의가 더 길게 나왔다.
# 신청을 권하는 메일에서 경고가 권유보다 커지는 건 뒤바뀐 것이라 사유를 늘렸다.
REASON_MAX = 150
CAUTION_MAX = 160
# 카드에 보일 해시태그 수. 같은 회차에서 80건 중 73건이 태그 5개였는데
# 조합이 거의 같아 변별력 없이 한 줄을 통째로 먹었다. 되돌리려면 숫자만 올리면 된다.
TAG_MAX = 3
# 💡 추천 사유에 쓸 문장 수. 1문장만 쓰면 평균 69자라, 125자인 주의사항에 밀려
# 경고가 권유보다 커 보였다(REASON_MAX를 올려도 소용없었던 이유 — 상한이 아니라
# 문장 수에서 잘리고 있었다). 2문장이면 평균 120자로 균형이 맞고, 두 번째 문장이
# 자격요건·대상 조건을 담아 실제로 쓸모가 있다. 되돌리려면 1로 낮추면 된다.
REASON_SENTENCES = 2

def clip_text(text, limit):
    """limit 안에서 문장 경계로 자른다. 경계를 못 찾으면 자르고 … 을 붙인다."""
    t = str(text or '').strip()
    if len(t) <= limit:
        return t
    head = t[:limit]
    for _pat in (r'.*(?:다\.|\.)\s', r'.*[,·]\s'):
        _m = re.match(_pat, head, re.S)
        if _m and len(_m.group(0).strip()) >= limit * 0.5:
            return _m.group(0).strip().rstrip(',·') + ' …'
    return head.rstrip() + '…'

# AI가 기업명 대신 "기업은 …"으로 문장을 시작하는 경우가 81건 있었다.
# 받는 쪽에서 남 얘기처럼 읽히므로 '귀사'로 바꾼다.
_RE_LEAD_CO = re.compile(r'^(?:해당\s*|본\s*|동\s*)?기업(은|이|는|가|의|도)\s*')
_LEAD_JOSA = {'은': '는', '이': '가'}

def soften_reason(text):
    """단정적 표현 완화. 빈 값은 그대로 돌려준다."""
    t = str(text or '')
    if not t:
        return t
    for _pat, _to in _SOFTEN_RULES:
        t = _pat.sub(_to, t)
    return re.sub(r'\s{2,}', ' ', t).strip()

# 🟡 자동 보완으로 승인된 공고는 AI가 '검토'로 판정한 것이라, 판단근거 첫 문장이
# "핵심 정보가 누락되어 판단이 불가능합니다" 같은 내용일 수 있다.
# 그걸 그대로 💡 추천 이유로 내보내면 "귀사 정보가 없어 판단을 못 하겠다"를
# 추천 이유로 받는 꼴이 된다. 이런 문장은 아예 붙이지 않는다(카드에서 💡 줄만 빠짐).
_RE_NO_REASON = re.compile(
    r'판단이?\s*(?:어렵|불가)|판단\s*불가|누락|명시되지\s*않|제공되지\s*않|'
    r'확인\s*불가|정보가\s*없|알\s*수\s*없')

# 기업명을 '귀사'로 바꾸면 조사가 안 맞는 경우가 생긴다 ("귀사으로", "귀사이").
_JOSA_FIX = [
    (re.compile(r"기업명\s*'?귀사'?"), '귀사'),
    (re.compile(r'귀사으로'), '귀사로'),
    (re.compile(r'귀사은'), '귀사는'),
    (re.compile(r'귀사이(?=\s)'), '귀사가'),
    (re.compile(r'귀사을'), '귀사를'),
    (re.compile(r'귀사과'), '귀사와'),
    (re.compile(r'귀사와의'), '귀사의'),
]

def fix_josa(text):
    """'귀사' 치환 뒤 어긋난 조사를 바로잡는다."""
    t = str(text or '')
    for _pat, _to in _JOSA_FIX:
        t = _pat.sub(_to, t)
    return re.sub(r'\s{2,}', ' ', t).strip()

def attach_ai_reason(n, company, ai_cache):
    """공고 dict에 수신자용 추천 이유(_ai_reason)·주의사항(_ai_caution)을 부착.
    AI_판단근거 첫 문장에서 기업명을 '귀사'로 치환."""
    import html as _h
    _k = f"{n.get('기업명', '') or company}_{n.get('공고ID', '')}"
    res = ai_cache.get(_k, {}) or {}
    if res.get('error'):
        return n
    reason = str(res.get('판단근거', '') or '').strip()
    if reason and reason.lower() != 'nan':
        # 판단불가·정보누락을 말하는 문장은 추천 이유가 될 수 없다 — 문장별로 거른다.
        _sents = re.split(r'(?<=다\.)\s+', reason)[:REASON_SENTENCES]
        first = ' '.join(s for s in _sents if s and not _RE_NO_REASON.search(s))
        _names = {str(company or ''), str(n.get('기업명', '') or '')}
        for _nm in list(_names):
            _core = re.sub(r'\(주\)|\(유\)|주식회사|\s', '', _nm)
            if len(_core) >= 2:
                _names.add(_core)
        for _nm in sorted(_names, key=len, reverse=True):
            if len(_nm) >= 2:
                first = first.replace(f"'{_nm}'", '귀사').replace(_nm, '귀사')
        first = _RE_LEAD_CO.sub(
            lambda m: '귀사' + _LEAD_JOSA.get(m.group(1), m.group(1)) + ' ', first)
        first = fix_josa(first)
        if first:
            n['_ai_reason'] = _h.escape(clip_text(soften_reason(first), REASON_MAX))
    caution = str(res.get('주의사항', '') or '').strip()
    if caution and caution not in ('없음', 'nan'):
        # 주의사항은 경고문이라 '반드시 확인' 같은 표현이 오히려 맞다 — 완화하지 않고
        # 길이만 문장 경계로 맞춘다.
        n['_ai_caution'] = _h.escape(clip_text(caution, CAUTION_MAX))
    return n

# 받은편지함에 뜨는 발신자 표시 이름.
# 예전에는 'onestop.kipcc@gmail.com' 만 떠서 기업 담당자 눈에는 모르는 지메일
# 주소였다. 열람 여부는 '발신자 → 제목' 순으로 갈리는데 첫 관문이 비어 있었다.
MAIL_FROM_NAME = "한국조달연구원 원스톱 스케일업"
MAIL_FROM_ADDR = "onestop.kipcc@gmail.com"
# 오픈 추적 행을 클릭 행과 구분하는 표식 (클릭 로그의 공고ID 자리에 들어간다).
OPEN_MARK = "__OPEN__"


def mail_subject(company, meta=None):
    """메일 제목. 기업명·건수·마감을 앞으로 당긴다.

    예전: '[원스톱 스케일업] 2026.10.13 이번 주 맞춤 지원사업 공고 — 주식회사 ○○'
    48자쯤이라 휴대폰 받은편지함(약 35자)에서는 기업명도 건수도 보이지 않았다.
    날짜는 메일함이 이미 보여주므로 앞자리를 쓸 이유가 없다."""
    from datetime import date as _date
    meta = meta or {}
    _main = (meta.get('sss') or []) + (meta.get('ss') or [])
    if _main:
        head = f"[원스톱] {company} 맞춤 공고 {len(_main)}건"
        _left = []
        for _x in _main:
            _d = notice_deadline_date(_x)
            if _d:
                _left.append((_d - _date.today()).days)
        _near = min([x for x in _left if x >= 0], default=None)
        if _near is not None and _near <= 7:
            head += " · 오늘 마감" if _near == 0 else f" · 마감 D-{_near}"
        return head
    _ref = len(meta.get('review') or [])
    if _ref:
        return f"[원스톱] {company} 참고 공고 {_ref}건"
    return f"[원스톱] {company} 맞춤 공고 안내"


# 메일용 한글 폰트 스택.
# Gmail은 수신 메일에서 <body>와 그 style을 통째로 걷어낸다. body에만 선언하면
# 폰트가 사라지고 클라이언트 기본값(한글 글리프 없음 → 폴백)으로 그려져
# 본문이 굴림 계열로 떨어진다 — 작은 크기에서 비트맵처럼 깨져 보이는 원인이었다.
# 그래서 아래 스택을 모든 <td>에 직접 건다(자식 요소는 상속받는다).
# 더존 그룹웨어 편집기도 폰트가 비면 '굴림체 9pt'를 밀어넣으므로 같은 처리로 막힌다.
MAIL_FONT = ("font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',"
             "-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;")


def build_match_mail(company, notices, co_row, ai_cache, ref_map, review_state=None):
    """맞춤 공고 메일 HTML 생성 — 👁 미리보기와 실제 발송이 함께 쓰는 단일 진입점.

    공고 선별(마감 재검사 → 업종 강등 → 참고 공고 보완)부터 HTML 조립까지 전부 여기서만
    한다. 미리보기용 HTML을 따로 만들지 말 것 — 미리보기≠발송 불일치의 원인이었음.

    반환: (html, meta)
      html — 발송될 HTML 전문. 안내할 공고가 하나도 없으면 None (발송 스킵 대상).
      meta — {'sss', 'ss', 'review', 'empty'}
    """
    _ai_an = ai_cache or {}

    # ── 메일 수록 자격 관문 ────────────────────────────
    # 승인(○) 공고도 예외 없이 통과시킨다 — ✕ · 자격 미충족 · 마감 경과를 차단.
    def _may(n):
        return can_include_notice(n, company, _ai_an, review_state)[0]

    # 별점 기준으로 분류 (공고유형 무관)
    _sss_raw = [n for n in notices if n.get('관련도','')=='★★★' and _may(n)]
    _ss_raw  = [n for n in notices if n.get('관련도','')=='★★' and _may(n)]

    # 방향1: AI 업종일치가 △/X인 공고는 '맞춤'에서 제외 → 참고로 강등
    # (업종 안 맞는 걸 맞춤이라 내보내면 신뢰도 하락)
    def _ind_ok(n):
        _k = f"{company}_{n.get('공고ID','')}"
        _ind = _ai_an.get(_k, {}).get('업종일치', '')
        return _ind != '△' and _ind != 'X'  # O이거나 미판정('')은 통과
    notices_sss    = group_related_notices([n for n in _sss_raw if _ind_ok(n)])
    notices_ss     = group_related_notices([n for n in _ss_raw if _ind_ok(n)])
    for _n_dec in notices_sss + notices_ss:
        attach_ai_reason(_n_dec, company, _ai_an)
    _demoted       = [n for n in (_sss_raw + _ss_raw) if not _ind_ok(n)]  # 업종△/X → 참고행

    # 참고 공고: 승인 공고가 3건 미만이면 그 기업의 ★★ 검토 공고로 부족분 채움
    # (최소 3건 보장 — 딸랑 1건만 나가는 허전함 방지)
    # 업종 불일치로 강등된 공고(_demoted)도 참고 후보에 포함
    _ref_map = ref_map or {}
    notices_review = []
    _approved_cnt = len(notices_sss) + len(notices_ss)
    if _approved_cnt < 3:
        _need = 3 - _approved_cnt
        _approved_ids = {n.get('공고ID','') for n in notices_sss + notices_ss}
        # 강등된 것 우선, 그다음 검토 공고 — 양쪽 다 같은 관문을 통과해야 한다
        _cand = [x for x in _demoted if _may(x)] + [
            r for r in _ref_map.get(company, [])
            if r.get('공고ID','') not in _approved_ids and _may(r)]
        _seen_r = set()
        _cand_uniq = []
        for r in _cand:
            _rid = r.get('공고ID','')
            if _rid not in _approved_ids and _rid not in _seen_r:
                _cand_uniq.append(r); _seen_r.add(_rid)
        notices_review = _cand_uniq[:_need]

    # ── 빈손 폴백 ──────────────────────────────────────
    # 보낼 카드가 한 장도 없을 때만, 접수기간이 명시되지 않은 공고를 참고로 허용한다.
    # 아무것도 못 받는 것보다는 낫되, 소진형·선착순은 여기서도 제외한다.
    if not (notices_sss or notices_ss or notices_review):
        _fb = [r for r in _ref_map.get(company, [])
               if can_include_notice(r, company, _ai_an, review_state,
                                     allow_undated=True)[0]]
        for _n_fb in _fb[:2]:
            _n_fb['_undated_fallback'] = True
            notices_review.append(_n_fb)

    # ── 빈 메일 방지: 승인·참고 공고가 전부 걸러져 보여줄 카드가 없으면 스킵 ──
    if not (notices_sss or notices_ss or notices_review):
        return None, {'sss': [], 'ss': [], 'review': [], 'empty': True}

    def notice_card_simple(n, idx):
        """공통 공고용 심플 카드 (작고 간결하게)"""
        _dl_txt = deadline_label(n)
        _trk = track_link(n.get('공고링크','#'), company,
                          n.get('공고ID',''), n.get('공고명',''))
        return f"""
        <table width="100%" cellpadding="0" cellspacing="0"
               style="margin-bottom:6px;">
          <tr>
            <td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;padding:10px 14px;
                       background:#FBF9F5;
                       border:1px solid #E8E2D5;
                       border-radius:6px;">
              <a href="{_trk}"
                 style="font-size:13px;font-weight:500;color:#5A5548;
                        text-decoration:none;display:block;
                        word-break:keep-all;line-height:1.5;">
                {n.get('공고명','')}
              </a>
              <p style="margin:3px 0 0;font-size:12px;color:#78736A;">
                {n.get('주관기관','')} &nbsp;·&nbsp; {_dl_txt}
              </p>
            </td>
          </tr>
        </table>"""

    def notice_card(n, idx):
        _dl_txt = deadline_label(n)
        _dl_col = "#C0392B" if deadline_urgent(n) else "#8D6E3B"
        hashtags = reason_to_hashtag(n.get("매칭근거",""))
        tag_html = ""
        if hashtags:
            tag_html = "<div style=\'margin-top:6px;display:flex;flex-wrap:wrap;gap:5px;\'>"
            for _ti, tag in enumerate(hashtags.split()[:TAG_MAX]):
                _tc = ("background:#F3EDE0;color:#7E6433" if _ti == 0
                       else "background:#EDEBE5;color:#797469")
                tag_html += f"<span style=\'font-size:11px;{_tc};padding:3px 8px;border-radius:20px;\'>{tag}</span>"
            tag_html += "</div>"
        notice_name = n.get("공고명","")
        _trk = track_link(n.get("공고링크","#"), company,
                          n.get("공고ID",""), notice_name)
        _extra = ""
        if n.get('_ai_reason'):
            _extra += (f"<p style=\"margin:7px 0 0;font-size:13px;color:#7A6B45;"
                       f"line-height:1.65;\">💡 {n['_ai_reason']}</p>")
        if n.get('_ai_caution'):
            # 💡 추천 사유와 📌 주의는 역할이 정반대(권유 vs 경고)인데
            # 같은 모양의 작은 문단이라 뭉쳐 보였다. 주의에만 테두리를 준다.
            _extra += (f"<p style=\"margin:8px 0 0;padding:8px 10px;font-size:13px;"
                       f"color:#7E6C47;background:#FBF7EF;"
                       f"border-left:3px solid #D8C9A8;border-radius:4px;"
                       f"line-height:1.6;\">⚠️ 신청 전 확인: {n['_ai_caution']}</p>")
        if n.get('_related'):
            _rl = []
            for _rn in n['_related'][:3]:
                _m = _RE_NOTICE_VARIANT.search(str(_rn.get('공고명','')))
                _lb = _m.group(0) if _m else str(_rn.get('공고명',''))[:10]
                _rtrk = track_link(_rn.get('공고링크','#'), company,
                                   _rn.get('공고ID',''), _rn.get('공고명',''))
                _rl.append(f"<a href=\"{_rtrk}\" style=\"color:#8D6E3B;"
                           f"text-decoration:none;font-weight:600;\">{_lb}</a>")
            _extra += (f"<p style=\"margin:5px 0 0;font-size:12px;color:#78736A;\">"
                       f"같은 사업 관련 공고: {' · '.join(_rl)}</p>")
        return f"""
        <table width="100%" cellpadding="0" cellspacing="0"
               style="margin-bottom:8px;background:#FFFFFF;
                      border:1px solid #E8E2D5;border-radius:10px;overflow:hidden;
                      box-shadow:0 1px 4px rgba(26,35,50,0.05);">
          <tr>
            <td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;padding:14px 16px;">
              <a href="{_trk}"
                 style="font-size:14px;font-weight:600;color:#1B2A41;
                        text-decoration:none;line-height:1.5;display:block;
                        word-break:keep-all;">
                {notice_name}
              </a>
              <!-- 메타 줄과 버튼을 한 행에. 제목(평균 41자·96%가 2줄 이상)은
                   전체 폭을 쓰고, 버튼은 한 줄짜리 메타 옆에 붙어 밀리지 않는다. -->
              <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:4px;">
                <tr>
                  <td valign="middle" style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;font-size:13px;color:#757066;">
                    {n.get("주관기관","")} &nbsp;·&nbsp; <span style="color:{_dl_col};font-weight:600;">{_dl_txt}</span>
                  </td>
                  <td width="78" align="right" valign="middle" style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;">
                    <a href="{_trk}"
                       style="display:inline-block;padding:7px 15px;font-size:12px;
                              font-weight:700;color:#1B2A41;background:#C9A96A;
                              border-radius:6px;text-decoration:none;
                              white-space:nowrap;">
                      보기 →
                    </a>
                  </td>
                </tr>
              </table>
              {tag_html}
              {_extra}
            </td>
          </tr>
        </table>"""

    rows_html = ""

    # ── 0건 기업 안내 문구 ───────────────────────
    is_zero = not notices_sss and not notices_ss
    if is_zero:
        rows_html += """
        <div style="background:#F5F0E6;
                    border:1px solid #E0D5BF;
                    border-radius:8px;padding:14px 16px;margin-bottom:16px;">
          <p style="margin:0 0 6px;font-size:13px;font-weight:500;
                     color:#5A5548;">
            이번 주 귀사에 딱 맞는 공고를 찾지 못했습니다.
          </p>
          <p style="margin:0;font-size:12px;color:#786B4E;line-height:1.7;">
            더 정확한 공고를 드리기 위해 추가 키워드나 관심 분야를
            아래 답장하기 버튼으로 알려주세요.
          </p>
        </div>"""

    # ── 🔦 주목할 만한 공고 (★★★) ────────────
    if notices_sss:
        rows_html += """
        <p style="margin:0 0 12px;font-size:11px;font-weight:700;
                   color:#7E6433;">
          🔦 &nbsp;주목할 만한 공고
        </p>"""
        for i, n in enumerate(notices_sss):
            rows_html += notice_card(n, i)

    # ── 📌 이런 공고도 있어요 (★★) ──────────
    if notices_ss:
        rows_html += """
        <div style="border-top:1px solid #E8E2D5;
                    padding-top:16px;margin-top:8px;">
          <p style="margin:0 0 10px;font-size:11px;font-weight:700;
                     color:#7E6C47;">
            📌 &nbsp;이런 공고도 있어요
          </p>"""
        for i, n in enumerate(notices_ss):
            rows_html += notice_card_simple(n, i)
        rows_html += "</div>"

    # ── 📎 참고 공고 (승인 공고 3건 미만 시 부족분 채움) ──
    if notices_review:
        _has_approved = bool(notices_sss or notices_ss)
        # 맞춤 0건일 때는 위쪽에 이미 "딱 맞는 공고를 찾지 못했습니다" 안내가 나가므로
        # 같은 말을 반복하지 않는다.
        if any(x.get('_undated_fallback') for x in notices_review):
            _ref_desc = "접수기간이 공고에 명시되지 않은 사업입니다. 신청 전 공고에서 일정을 직접 확인해 주세요."
        elif _has_approved:
            _ref_desc = "위 공고와 함께 참고하실 만한 공고입니다."
        else:
            _ref_desc = ""
        _REF_DESC_HTML = (
            f'<p style="margin:0 0 12px;font-size:12px;color:#757066;">{_ref_desc}</p>'
            if _ref_desc else '')
        rows_html += f"""
        <div style="border-top:1px solid #E8E2D5;
                    padding-top:16px;margin-top:8px;">
          <p style="margin:0 0 6px;font-size:11px;font-weight:700;
                     color:#7E6C47;">
            📎 &nbsp;참고해보실 만한 공고
          </p>
          {_REF_DESC_HTML}"""
        for i, n in enumerate(notices_review[:3]):
            rows_html += notice_card_simple(n, i)
        rows_html += "</div>"

    # 전체 반응 버튼(👍 도움됐어요 / 👎 별로였어요 / 💬 의견)은 뺐다.
    # 여섯 회차 446통에 넣었지만 회신이 한 건도 없었다. 자리만 차지한다.

    import urllib.parse as _up
    kw_subject = _up.quote(f"[원스톱 피드백] {company}")
    kw_body    = _up.quote(
        "[추가 키워드]\n"
        "더 받고 싶은 분야나 키워드를 적어주세요:\n\n"
        "[Gmail 주소]\n"
        "맞춤 캘린더 알림을 받으시려면 Gmail 주소를 알려주세요:\n"
    )

    keyword_sec = f"""
    <div style="background:#FFFFFF;
                border:1.5px solid #D8D0C0;
                border-radius:10px;padding:16px 18px;margin:16px 0;">
      <p style="margin:0 0 8px;color:#22344F;font-weight:700;font-size:11px;">
        ✏️ 추가 키워드가 있으신가요?
      </p>
      <p style="margin:0 0 12px;font-size:12px;color:#6B6558;line-height:1.7;">
        더 잘 맞는 공고를 드리기 위해 받고 싶은 분야나 키워드를 답장으로 알려주세요.
      </p>
      <a href="mailto:onestop.kipcc@gmail.com?subject={kw_subject}&body={kw_body}"
         style="display:inline-block;padding:7px 16px;font-size:12px;font-weight:600;
                color:#FFFFFF;background:#22344F;border-radius:8px;
                text-decoration:none;">
        답장하기 →
      </a>
    </div>"""

    cal_sec = f"""
    <div style="background:#FFFFFF;border-radius:10px;
                padding:16px 18px;border:1.5px solid #D8D0C0;margin:16px 0;">
      <p style="margin:0 0 4px;color:#7E6433;font-weight:700;font-size:11px;">
        📅 공고 마감일 캘린더
      </p>
      <p style="margin:0 0 10px;font-size:12px;color:#6B6558;line-height:1.85;">
        안내드린 공고의 마감일을 한곳에 모아두었습니다.<br>
        구독하시면 새 공고가 올라올 때마다 자동으로 채워집니다.
      </p>
      <a href="{CALENDAR_LINK}"
         style="display:inline-block;background:#C9A96A;color:#3A2E15;
                padding:8px 18px;border-radius:7px;text-decoration:none;
                font-size:12px;font-weight:700;">
        캘린더 구독하기 →
      </a>
    </div>"""

    together_sec = f"""
    <div style="background:#22344F;border-radius:10px;
                padding:16px 18px;border:1.5px solid #C9A96A;margin:16px 0;">
      <p style="margin:0 0 5px;color:#C9A96A;font-weight:700;font-size:11px;">
        🤝 함께하기 · 기업 회원소개
      </p>
      <p style="margin:0 0 12px;font-size:12px;color:#C5D0DC;line-height:1.65;">
        원스톱 스케일업 참여 기업의 제품·기술과 협력 희망 분야를 소개하는 공간입니다.
        등록하시면 다른 기업·기관이 귀사를 찾아보고 협력을 제안할 수 있습니다.
      </p>
      <a href="https://www.kipcc.re.kr/join"
         style="display:inline-block;margin:0 6px 0 0;padding:9px 20px;
                font-size:12px;font-weight:700;color:#1B2A41;background:#C9A96A;
                border-radius:6px;text-decoration:none;">
        회원가입 →
      </a>
      <a href="https://www.kipcc.re.kr/"
         style="display:inline-block;padding:9px 20px;font-size:12px;font-weight:700;
                color:#C9A96A;background:transparent;border:1px solid #C9A96A;
                border-radius:6px;text-decoration:none;">
        센터 홈 →
      </a>
    </div>"""

    # ── 오픈 추적 1×1 ──────────────────────────────────
    # 클릭만 보면 '못 받았다 / 안 열었다 / 열었는데 관심 없다'를 구분할 수 없다.
    # 셋은 처방이 완전히 달라서, 무엇을 고칠지 정하려면 열람 여부가 먼저 필요하다.
    # 클릭 추적과 같은 Apps Script 를 쓰되 공고ID 자리에 OPEN_MARK 를 넣어 구분하고,
    # 공고명 자리에는 회차 ID를 넣어 어느 회차의 열람인지 남긴다.
    # 지메일은 이미지를 차단하는 경우가 있어 과소집계된다 — 절대값이 아니라 회차 추세로 본다.
    _open_px = ''
    if CLICK_TRACK_URL:
        import urllib.parse as _up_op
        _q_op = _up_op.urlencode({'co': company, 'notice': OPEN_MARK,
                                  'name': current_round_id() or '', 'url': ''})
        _open_px = (f'<img src="{CLICK_TRACK_URL}?{_q_op}" width="1" height="1" alt="" '
                    f'style="display:block;width:1px;height:1px;border:0;opacity:0;">')

    today_str = datetime.today().strftime('%Y.%m.%d')
    # PICKS 뱃지 — 실제로 메일에 실리는 맞춤 공고(🔦+📌) 수.
    # 승인 건수(len(notices))를 쓰면 마감 경과·업종 강등으로 빠진 공고까지 세어
    # "5 PICKS"라 써놓고 카드는 3장만 나가는 불일치가 생긴다. 0이면 뱃지를 숨긴다.
    _pick_n = len(notices_sss) + len(notices_ss)
    html=f"""<!DOCTYPE html>
    <html lang="ko">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    </head>
    <body style="margin:0;padding:0;background:#E6E9EE;
    font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0"
    style="background:#E6E9EE;padding:36px 0 52px;">
    <tr><td align="center" style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;">
    <table width="560" cellpadding="0" cellspacing="0">

    <!-- ── 로고 헤더 (흰 배경) ── -->
    <tr>
    <td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;background:#FFFFFF;border-radius:14px 14px 0 0;
    padding:20px 28px;border-bottom:1px solid #E8ECF0;
    border-top:1px solid #D9DEE5;">
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
    <td valign="middle" style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;">
    <img src="{LOGO_URL}"
     alt="혁신제품지원센터"
     width="160" height="auto"
     style="display:block;height:auto;max-height:36px;
            object-fit:contain;object-position:left;">
    </td>
    <td align="right" valign="middle" style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;">
    <p style="margin:0;font-size:11px;color:#9CAAB8;letter-spacing:0.3px;">
    {today_str}
    </p>
    </td>
    </tr>
    </table>
    </td>
    </tr>

    <!-- ── 메인 카드 (아이보리) ── -->
    <tr>
    <td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;background:#FBFAF7;
    box-shadow:0 8px 32px rgba(26,35,50,0.10);">

    <!-- 헤더존 (네이비) -->
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
    <td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;padding:30px 28px 24px;
         background:#1B2A41;
         border-bottom:2px solid #C9A96A;">
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
    <td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;">
      <p style="margin:0 0 2px;font-size:10px;font-weight:700;
                 letter-spacing:2.5px;color:#C9A96A;
                 text-transform:uppercase;">
        Scale-Up Program
      </p>
      <h1 style="margin:6px 0 4px;font-size:26px;font-weight:800;
                 color:#FFFFFF;letter-spacing:-0.6px;line-height:1.2;">
        원스톱 스케일업
      </h1>
      <p style="margin:0;font-size:12px;color:#B4C0CE;">
        이번 주 맞춤 지원사업 공고
      </p>
    </td>
    {f'''<td align="right" valign="middle" width="72" style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;">
      <div style="background:linear-gradient(135deg,#C9A96A 0%,#B08D4F 100%);
                  border-radius:12px;padding:11px 0;width:60px;
                  text-align:center;">
        <p style="margin:0;font-size:22px;font-weight:800;color:#1B2A41;
                   line-height:1;">{_pick_n}</p>
        <p style="margin:3px 0 0;font-size:9px;letter-spacing:1.2px;
                   color:#3A2E15;font-weight:700;text-transform:uppercase;">picks</p>
      </div>
    </td>''' if _pick_n else ''}
    </tr>
    </table>
    <!-- 기업명 카드 -->
    <div style="margin-top:20px;padding:14px 18px;
            background:rgba(255,255,255,0.06);
            border-radius:8px;border-left:3px solid #C9A96A;">
    <p style="margin:0 0 3px;font-size:15px;font-weight:700;color:#FFFFFF;">
    {company}
    <span style="font-size:13px;font-weight:400;
                 color:#B4C0CE;margin-left:4px;">담당자님</span>
    </p>
    <p style="margin:0;font-size:12px;color:#B4C0CE;line-height:1.6;">
    기술 키워드 분석을 통해 선별된 공고를 안내드립니다.
    </p>
    </div>

    </td>
    </tr>

    <!-- 기업 정보 카드 (아이보리 존) -->
    {f"""<tr><td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;padding:20px 28px 0;background:#FBFAF7;">
    <div style="padding:12px 16px;
            background:#F5F0E6;
            border:1px solid #E0D5BF;
            border-left:4px solid #C9A96A;border-radius:8px;">
    <p style="margin:0 0 11px;font-size:11px;font-weight:700;color:#7E6433;">
    저희가 파악한 귀사 정보</p>
    <p style="margin:0 0 4px;font-size:12px;color:#6B6558;">
    기술키워드 <span style="color:#2A2620;font-weight:600;word-break:keep-all;">{str(co_row.get("기술키워드","") or co_row.get("키워드보완","") or "—")[:30]}</span>
    </p>
    <p style="margin:0 0 4px;font-size:12px;color:#6B6558;">
    관심분야 <span style="color:#2A2620;font-weight:600;">{str(co_row.get("관심사업분야","") or "—")}</span>
    </p>
    <p style="margin:0 0 4px;font-size:12px;color:#6B6558;">
    기업유형 <span style="color:#2A2620;font-weight:600;word-break:keep-all;">{str(co_row.get("기업유형","") or "—")[:25]}</span>
    </p>
    <p style="margin:0;font-size:12px;color:#6B6558;">
    소재지 <span style="color:#2A2620;font-weight:600;">{str(co_row.get("소재지","") or "—")}</span>
    </p>
    </div>
    </td></tr>""" if co_row
    else ""}

    <!-- 공고 목록 -->
    <tr>
    <td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;padding:20px 28px 20px;background:#FBFAF7;">
    {rows_html}
    </td>
    </tr>

    <!-- 캘린더 -->
    {f'''<tr><td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;padding:0 28px 24px;background:#FBFAF7;">{keyword_sec}</td></tr>''' if keyword_sec else ''}
    {f'''<tr><td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;padding:0 28px 24px;background:#FBFAF7;">{cal_sec}</td></tr>''' if cal_sec else ''}
    <tr><td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;padding:0 28px 24px;background:#FBFAF7;">{together_sec}</td></tr>
    </table>
    </td>
    </tr>

    <!-- ── 네이비 푸터 ── -->
    <tr>
    <td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;background:#1B2A41;border-radius:0 0 14px 14px;
    padding:18px 28px;border-top:2px solid #C9A96A;">
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
    <td style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;">
    <p style="margin:0;font-size:12px;color:#B4C0CE;line-height:1.9;">
    혁신제품지원센터 원스톱 스케일업 운영팀<br>
    <a href="mailto:onestop.kipcc@gmail.com"
     style="color:#C9A96A;text-decoration:none;font-weight:600;">
    onestop.kipcc@gmail.com
    </a>
    </p>
    <p style="margin:8px 0 0;font-size:11px;color:#83A0BE;">
    본 메일은 원스톱 스케일업 프로그램 참여 시 수신에 동의하신 기업에 발송됩니다.
    </p>
    </td>
    <td align="right" valign="middle" style="font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;">
    <p style="margin:0;font-size:11px;color:#83A0BE;">
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
    {_open_px}
    </body></html>"""

    return html, {'sss': notices_sss, 'ss': notices_ss,
                  'review': notices_review, 'empty': False}


def claude_call_raw(prompt, max_tokens=1000):
    """단순 텍스트 프롬프트 → Claude 응답 문자열 반환"""
    api_key = ""
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        try:
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        except Exception:
            pass
    if not api_key:
        st.warning("⚠️ ANTHROPIC_API_KEY 없음")
        return ''
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }
    resp, _err = _anthropic_post(headers, payload)
    if resp is not None and resp.ok:
        content = resp.json().get('content', [])
        return content[0].get('text', '') if content else ''
    if resp is not None:
        st.warning(f"⚠️ Claude API 오류 {resp.status_code}: {resp.text[:100]}")
    else:
        st.warning(f"⚠️ Claude API 예외: {_err}")
    return ''


def get_companies_df():
    """기업 프로필 표. 세션 캐시가 없으면 드라이브에서 읽어 채운다.

    예전에는 「🔍 매칭 실행」 버튼 안에서만 df_companies_cache 를 채웠다.
    앱이 재시작되거나 다른 세션에서 ⚡ 분석을 돌리면 기업 정보가 통째로 빠진 채
    claude_analyze 가 호출돼, 판정이 '검토'(79%)와 자격충족 '△'(89%)로 몰렸다.
    실측: 버전 추적 가능한 438건 중 82건이 빈 프로필로 분석됨."""
    df = st.session_state.get('df_companies_cache')
    try:
        if df is None or df.empty:
            df = load_excel(_get_drive(), SELECTED_FILE)
            if not df.empty:
                st.session_state['df_companies_cache'] = df
    except Exception:
        df = pd.DataFrame()
    return df if df is not None else pd.DataFrame()

def company_profile(name):
    """기업명 → AI에 넘길 프로필 dict. 못 찾으면 기업명만 담아 돌려준다."""
    try:
        df = get_companies_df()
        if df is not None and not df.empty and '기업명' in df.columns:
            m = df[df['기업명'] == name]
            if not m.empty:
                d = m.iloc[0].to_dict()
                d['기업명'] = name
                return d
    except Exception:
        pass
    return {'기업명': name}

def procure_profile(company_info):
    """신청서에서 받은 조달 관련 항목을 프롬프트 줄로 만든다.

    왜 필요한가: 「나라장터 입찰참가자격 보유 업체에 한함」 같은 조건을 AI 가
    판정하려면 그 값이 프롬프트에 있어야 한다. 기업들은 WALLA 신청서에 이미
    적어 냈는데 명단으로 옮겨지지 않아, AI 가 자격충족을 전부 △(확인 필요)로
    올리고 있었다 — 2026-10-27 회차 검토 167건 중 자격충족 △ 가 141건.

    빈칸과 '없음'을 구분한다. 열 자체가 없으면 '미확인'(옛 명단), 열은 있는데
    값이 비어 있으면 그 기업이 해당 없다고 답한 것으로 본다. 둘을 섞으면
    AI 가 모르는 것을 '없다'고 단정한다."""
    ci = company_info or {}

    def val(key):
        if key not in ci:
            return '미확인'
        v = str(ci.get(key, '') or '').strip()
        return v if v else '미확인'

    if '물품식별번호' not in ci:
        goods_txt = '미확인'
    else:
        raw = str(ci.get('물품식별번호', '') or '')
        goods = [g.strip() for g in raw.split(',') if g.strip()]
        if goods:
            more = ' 외' if len(goods) > 3 else ''
            goods_txt = f"{len(goods)}건 보유 ({', '.join(goods[:3])}{more})"
        else:
            goods_txt = '없음'

    lines = [
        f"- 나라장터 입찰참가자격: {val('입찰참가자격')}",
        f"- 조달 물품식별번호: {goods_txt}",
        f"- 대표제품 특허: {val('특허현황')}",
        f"- 상용화 단계: {val('상용화단계')}",
        f"- 혁신제품 제도 활용 의향: {val('혁신제품의향')}",
    ]
    return "\n".join(lines)


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

    # 전문 내용 우선 활용 — 네비·푸터를 걷어내고 상한까지 그대로 넣는다.
    # (예전 1,500자 절단으로 뒤쪽 신청 자격·제외 대상이 잘리던 문제)
    notice_content = clean_notice_text(
        notice_info.get('전문내용','') or notice_info.get('사업개요','')
    )[:NOTICE_TEXT_CAP]

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
{procure_profile(company_info)}

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
2. 자격충족: 지원 자격 충족 가능성. 위 기업 정보에 적힌 값으로 판정하세요.
   나라장터 입찰참가자격·물품식별번호·특허·상용화 단계·혁신제품 의향은 기업이
   신청서에 직접 적어 낸 값입니다 — 이 값으로 충족·미충족이 가려지면 O 또는 X로
   답하세요. '미확인'인 항목이나 공고가 요구하는데 기업 정보에 아예 없는 항목
   (예: 설립연도) 때문에 못 가릴 때만 △로 두고, 무엇을 확인해야 하는지 적으세요.
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
  "판단근거": "3~4문장으로 구체적 근거 (기업의 어떤 특성이 공고의 어떤 조건과 맞거나 안 맞는지). 공고 본문에서 확인한 사실만 담담하게 쓰고 '정확히·완벽히·확실히·반드시' 같은 단정적 표현은 쓰지 마세요. 본문에서 확인되지 않은 조건은 단정하지 말고 확인이 필요하다고 적으세요.",
  "주의사항": "신청 전 반드시 확인할 사항 (없으면 없음)"
}}"""

    try:
        resp, _rerr = _anthropic_post(
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload={
                "model": "claude-sonnet-4-5",
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}]
            },
        )
        if resp is None:
            return {"error": f"재시도 후에도 실패: {_rerr}"}
        if resp.ok:
            text = resp.json()['content'][0]['text']
            import re as _re
            json_match = _re.search(r'[{].*[}]', text, _re.DOTALL)
            if json_match:
                _parsed = json.loads(json_match.group())
                if isinstance(_parsed, dict):
                    if len(str(notice_info.get('전문내용','') or '')) >= 200:
                        _parsed['_전문반영'] = True
                    # 어떤 입력으로 뽑은 판정인지 함께 남긴다 (재분석 대상 판별용)
                    _parsed.update(ai_input_version(company_info, notice_info))
                return _parsed
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

# ── 앱 초기화 — AI 분석 결과 드라이브에서 복원 ──────
if 'ai_analysis_loaded' not in st.session_state:
    try:
        _drive_init = _get_drive()
        _loaded = load_ai_analysis(_drive_init)
        st.session_state['ai_analysis_loaded'] = True
        if _loaded > 0:
            pass  # 조용히 복원 (배너 표시 안 함)
    except Exception:
        st.session_state['ai_analysis_loaded'] = True  # 실패해도 반복 시도 안 함

# ── 앱 초기화 — 매칭 결과·승인상태 자동 복원 ──────────
if not st.session_state.get('_match_state_loaded'):
    try:
        load_match_state(_get_drive())
    except Exception:
        st.session_state['_match_state_loaded'] = True

# ── CSS ──────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  /* 액센트는 메일 카드와 같은 골드 계열. 예전 핫핑크(#C9A96A)는 채도가 높아
     승인(초록)·제외(빨강)·경고(노랑) 상태색과 시각적으로 경쟁했다. */
  --accent:       #C9A96A;
  --accent-light: #1A150A;
  --accent-dark:  #A88A4F;
  --accent-on:    #2A2214;   /* 액센트 배경 위에 얹는 글자색 (골드는 밝아서 어두운 글자) */
  --border:       #2A2A2A;
  --border-2:     #333333;
  --surface:      #151515;
  --bg:           #0A0A0A;
  --text-1:       #F0F0F0;
  --text-2:       #AAAAAA;
  --text-3:       #666666;
  --text-cap:     #9A9A9A;   /* 캡션 전용 — #666 은 배경 대비 3.4:1 로 낮아 읽기 어렵다 */
  --blue:         #3B82F6;
  --yellow:       #F59E0B;
  --red:          #EF4444;
  --radius:       8px;
  --shadow:       0 1px 3px rgba(0,0,0,0.4);
  --shadow-md:    0 4px 12px rgba(201,169,106,0.1);
}

/* ── 전체 폰트·배경 ── */
.stApp {
  font-family: 'Inter','Apple SD Gothic Neo','Malgun Gothic',sans-serif !important;
  background: var(--bg) !important;
  color: var(--text-1) !important;
}

/* ── 타이포 ── */
h1 { font-size:22px !important; font-weight:700 !important; color:var(--text-1) !important; letter-spacing:-0.3px !important; }
h2 { font-size:17px !important; font-weight:600 !important; color:var(--text-1) !important; }
h3 { font-size:15px !important; font-weight:600 !important; color:var(--text-1) !important; }
p, span, div, label { color: var(--text-1) !important; }
strong { color: var(--accent) !important; font-weight:600 !important; }
code {
  color: var(--accent) !important;
  background: var(--accent-light) !important;
  border-radius:4px !important; padding:1px 6px !important; font-size:12px !important;
}

/* ── 메인 컨테이너 ── */
.main .block-container {
  background: var(--bg) !important;
  color: var(--text-1) !important;
}

/* ── 메트릭 카드 ── */
[data-testid="metric-container"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
  padding: 14px 18px !important;
  box-shadow: var(--shadow-md) !important;
}
[data-testid="stMetricLabel"] {
  font-size: 11px !important; font-weight:500 !important;
  text-transform: uppercase !important; letter-spacing:0.5px !important;
  color: var(--text-2) !important;
}
[data-testid="stMetricValue"] {
  font-size:24px !important; font-weight:700 !important;
  color: var(--accent) !important;
}

/* ── primary 버튼 ── */
button[kind="primary"] {
  background: var(--accent) !important;
  /* 골드 위 흰 글자는 2.2:1 로 읽기 어렵다 → 어두운 글자 (7.0:1) */
  color: var(--accent-on) !important; border:none !important; font-weight:700 !important;
  box-shadow: 0 1px 6px rgba(201,169,106,0.4) !important;
}
button[kind="primary"]:hover { background: var(--accent-dark) !important; }

/* ── 일반 버튼 ── */
.stButton button {
  border-radius: var(--radius) !important;
  font-size:13px !important; font-weight:600 !important;
  border: 1px solid var(--border-2) !important;
  background: var(--surface) !important;
  color: var(--text-1) !important;
  transition: all 0.15s !important;
}
.stButton button:hover {
  border-color: var(--accent) !important;
  color: var(--accent) !important;
  box-shadow: 0 0 8px rgba(201,169,106,0.2) !important;
}

/* ── 입력창 ── */
.stTextInput input, .stTextArea textarea, .stSelectbox select,
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea {
  background: var(--surface) !important;
  color: var(--text-1) !important;
  border-color: var(--border-2) !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px rgba(201,169,106,0.15) !important;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {
  color: var(--text-3) !important;
}

/* ── 셀렉트박스 ── */
[data-baseweb="select"] { background: var(--surface) !important; }
[data-baseweb="select"] * { background: var(--surface) !important; color: var(--text-1) !important; }
[data-baseweb="popover"] { background: #1A1A1A !important; border: 1px solid var(--border-2) !important; }
[data-baseweb="menu"] li:hover { background: var(--accent-light) !important; }

/* ── 탭 ── */
.stTabs [data-baseweb="tab-list"] {
  border-bottom: 2px solid var(--border) !important;
  background: transparent !important;
}
.stTabs [data-baseweb="tab"] {
  color: var(--text-2) !important;
  background: transparent !important;
}
.stTabs [aria-selected="true"] {
  color: var(--accent) !important;
  font-weight:600 !important;
  border-bottom: 2px solid var(--accent) !important;
  background: var(--accent-light) !important;
}

/* ── 알림 박스 ── */
.stSuccess { background: #0A1F15 !important; border-left: 3px solid #10B981 !important; border-radius:var(--radius) !important; }
.stSuccess * { color: #4DFFAA !important; }
.stWarning { background: #1A1200 !important; border-left: 3px solid var(--yellow) !important; border-radius:var(--radius) !important; }
.stWarning * { color: #FFD080 !important; }
.stError { background: #1A0000 !important; border-left: 3px solid var(--red) !important; border-radius:var(--radius) !important; }
.stError * { color: #FF8080 !important; }
.stInfo { background: #001020 !important; border-left: 3px solid var(--blue) !important; border-radius:var(--radius) !important; }
.stInfo * { color: #80BFFF !important; }

/* Streamlit 1.40+ 알림 (data-testid 기반) */
[data-testid="stAlert"] { border-radius: var(--radius) !important; }
[data-testid="stAlertContentSuccess"] {
  background: #0A1F15 !important; border-left: 3px solid #10B981 !important;
}
[data-testid="stAlertContentSuccess"] * { color: #4DFFAA !important; }
[data-testid="stAlertContentWarning"] {
  background: #1A1200 !important; border-left: 3px solid var(--yellow) !important;
}
[data-testid="stAlertContentWarning"] * { color: #FFD080 !important; }
[data-testid="stAlertContentError"] {
  background: #1A0000 !important; border-left: 3px solid var(--red) !important;
}
[data-testid="stAlertContentError"] * { color: #FF8080 !important; }
[data-testid="stAlertContentInfo"] {
  background: #001020 !important; border-left: 3px solid var(--blue) !important;
}
[data-testid="stAlertContentInfo"] * { color: #80BFFF !important; }

/* ── 코드블록(발송 로그) ── */
[data-testid="stCode"], pre {
  background: #0F0F0F !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
}
[data-testid="stCode"] code, pre code {
  background: transparent !important;
  color: #E0E0E0 !important;
}
[data-testid="stCode"] * { background: transparent !important; }

/* ── 구분선 ── */
hr { border: none !important; border-top: 1px solid var(--border) !important; }

/* ── 캡션 ── */
.stCaption, [data-testid="stCaptionContainer"] { color: var(--text-cap) !important; font-size:12px !important; }

/* ── data editor / dataframe ── */
[data-testid="stDataFrame"], .stDataFrame,
[data-testid="stDataFrameResizable"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
}
/* glide-data-grid 캔버스 컨테이너 */
[data-testid="stDataFrame"] > div,
[data-testid="stDataFrame"] .dvn-scroller,
[data-testid="stDataFrame"] .gdg-wmyidgi {
  background: var(--surface) !important;
}
/* 표 상단 툴바(검색/다운로드 아이콘) */
[data-testid="stElementToolbar"],
[data-testid="stElementToolbarButtonContainer"] {
  background: var(--surface-2, #1A1A1A) !important;
  border: 1px solid var(--border) !important;
  border-radius: 6px !important;
}
[data-testid="stElementToolbar"] button svg { fill: var(--text-1) !important; }
[data-testid="stElementToolbar"] button:hover { background: #C9A96A33 !important; }

/* ── 사이드바 ── */
section[data-testid="stSidebar"] {
  background: #0D0D0D !important;
  border-right: 1px solid #C9A96A33 !important;
}
section[data-testid="stSidebar"] * { color: var(--text-1) !important; }
section[data-testid="stSidebar"] .stRadio label:hover { color: var(--accent) !important; }

/* ── progress ── */
.stProgress > div > div { background: var(--accent) !important; }
[data-testid="stProgressBar"] > div { background: var(--accent) !important; }

/* ── link button ── */
.stLinkButton a {
  border: 1px solid var(--border-2) !important;
  border-radius: var(--radius) !important;
  color: var(--text-1) !important;
  font-size:13px !important; text-decoration:none !important;
  background: var(--surface) !important;
  transition: all 0.15s !important;
}
.stLinkButton a:hover { border-color: var(--accent) !important; color: var(--accent) !important; }

/* ── expander ── */
.streamlit-expander {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
}
.streamlit-expander summary { color: var(--text-1) !important; }
/* Streamlit 1.40+ expander (data-testid 기반) */
[data-testid="stExpander"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
}
[data-testid="stExpander"] details {
  background: var(--surface) !important;
  border: none !important;
}
[data-testid="stExpander"] summary {
  background: var(--surface) !important;
  color: var(--text-1) !important;
}
[data-testid="stExpander"] summary:hover { color: var(--accent) !important; }
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span,
[data-testid="stExpander"] summary svg {
  color: var(--text-1) !important;
  fill: var(--text-1) !important;
}
[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
  background: var(--surface) !important;
}

/* ── 사이드바: 데스크톱은 항상 표시, 모바일은 접기 허용 ── */
@media (min-width: 768px) {
  [data-testid="stSidebarCollapseButton"] { display:none !important; }
}
@media (max-width: 767px) {
  /* 모바일: 닫기 버튼 복원 + 잘 보이게 */
  [data-testid="stSidebarCollapseButton"] {
    display:flex !important;
  }
  [data-testid="stSidebarCollapseButton"] svg { fill:#C9A96A !important; }
  /* 본문 여백 축소 */
  .main .block-container { padding-left:12px !important; padding-right:12px !important; }
  /* 최소 폰트 보정 */
  html { -webkit-text-size-adjust:100%; }
}
@media (min-width: 768px) {
  [data-testid="collapsedControl"]        { display:none !important; }
  section[data-testid="stSidebar"] {
    display:block !important; transform:translateX(0) !important;
    min-width:244px !important; visibility:visible !important;
  }
  section[data-testid="stSidebar"][aria-expanded="false"] {
    display:block !important; transform:translateX(0) !important; margin-left:0 !important;
  }
}
@media (max-width: 767px) {
  /* 모바일 접힘: 화면 밖으로 완전히 밀어내고 내부까지 숨김 */
  section[data-testid="stSidebar"][aria-expanded="false"] {
    transform:translateX(-110%) !important;
    width:0 !important; min-width:0 !important; max-width:0 !important;
    visibility:hidden !important; opacity:0 !important;
    padding:0 !important; overflow:hidden !important; pointer-events:none !important;
  }
  section[data-testid="stSidebar"][aria-expanded="false"] * {
    visibility:hidden !important; opacity:0 !important;
  }
  /* 모바일 펼침: 본문 위에 오버레이 (본문을 밀지 않음) */
  section[data-testid="stSidebar"][aria-expanded="true"] {
    position:fixed !important; left:0 !important; top:0 !important;
    z-index:9999 !important; width:80vw !important; max-width:320px !important;
    box-shadow:0 0 40px rgba(0,0,0,0.7) !important;
    visibility:visible !important; opacity:1 !important;
  }
  /* 본문은 항상 전체 폭 */
  section.main, .main .block-container {
    width:100% !important; margin-left:0 !important;
  }
  [data-testid="collapsedControl"] { display:flex !important; }
}

/* ── 시스템 UI 숨김 ── */
.stTooltipIcon                    { display:none !important; }
div[data-testid="stStatusWidget"] { display:none !important; }
#MainMenu { visibility:hidden; }
footer    { visibility:hidden; }
header    { visibility:hidden; }

/* ── 슬라이더 ── */
[data-testid="stSlider"] [role="progressbar"] { background: var(--accent) !important; }
[data-testid="stSlider"] [role="slider"] {
  background: var(--accent) !important; border-color: var(--accent) !important;
}

/* ── 체크박스 ── */
[data-testid="stCheckbox"] label span { border-color: var(--border-2) !important; }
[data-testid="stCheckbox"] input:checked + span { background: var(--accent) !important; border-color: var(--accent) !important; }

/* ── 셀렉트박스 드롭다운 ── */
[data-baseweb="select"] > div {
  background: #151515 !important;
  border-color: #333333 !important;
  color: #F0F0F0 !important;
}
[data-baseweb="select"] span { color: #F0F0F0 !important; }
[data-baseweb="popover"] { background: #1A1A1A !important; border: 1px solid #333 !important; }
[data-baseweb="menu"] { background: #1A1A1A !important; }
[data-baseweb="menu"] ul { background: #1A1A1A !important; }
[data-baseweb="menu"] li {
  background: #1A1A1A !important;
  color: #F0F0F0 !important;
}
[data-baseweb="menu"] li:hover {
  background: #C9A96A !important;
  color: #000000 !important;
}
[data-baseweb="option"] {
  background: #1A1A1A !important;
  color: #F0F0F0 !important;
}
[data-baseweb="option"]:hover {
  background: #C9A96A !important;
  color: #000000 !important;
}
/* 선택된 항목 (드롭다운 옵션에만 적용) */
[data-baseweb="menu"] [aria-selected="true"],
[data-baseweb="popover"] [aria-selected="true"] {
  background: rgba(201,169,106,0.18) !important;
  color: #E6D0A3 !important;
  font-weight: 600 !important;
}
/* ── 드롭다운 팝오버 강제 (body 최상위 렌더 대응) ── */
div[data-baseweb="popover"] > div,
div[data-baseweb="popover"] ul {
  background: #1A1A1A !important;
}
ul[role="listbox"] { background: #1A1A1A !important; }
ul[role="listbox"] li,
li[role="option"] {
  background: #1A1A1A !important;
  color: #F0F0F0 !important;
}
ul[role="listbox"] li:hover,
li[role="option"]:hover {
  background: #C9A96A !important;
  color: #000000 !important;
}
li[role="option"][aria-selected="true"] {
  background: rgba(201,169,106,0.18) !important;
  color: #E6D0A3 !important;
  font-weight: 600 !important;
}

/* ── radio 버튼 ── */
[data-testid="stRadio"] label {
  color: var(--text-2) !important;
  font-size: 13px !important;
  background: transparent !important;
  transition: color 0.15s !important;
}
[data-testid="stRadio"] label > div {
  background: transparent !important;
}
[data-testid="stRadio"] [data-testid="stMarkdownContainer"] p {
  color: inherit !important;
}
/* 선택된 라벨: 배경 없이 밝은 핑크 글자 */
[data-testid="stRadio"] label:has(input:checked) {
  color: var(--accent) !important;
  font-weight: 600 !important;
  background: transparent !important;
}
[data-testid="stRadio"] label:has(input:checked) [data-testid="stMarkdownContainer"] p {
  color: var(--accent) !important;
}
[data-testid="stRadio"] label:hover { color: var(--text-1) !important; }

/* ── 타임라인 필터 버튼 명시적 색상 ── */
.tl-filter-active {
  background: var(--accent) !important;
  color: var(--accent-on) !important;   /* 골드 위 흰 글자는 대비 부족 */
  border-color: var(--accent) !important;
}
</style>
""", unsafe_allow_html=True)



# ── 사이드바 ──────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📢 원스톱 스케일업")
    # 빌드 태그는 배포 확인용이라 늘 보이는 자리에 둔다.
    # 예전에는 '⚡ 전 기업 일괄 AI 분석' 접힌 메뉴 안에 있어, 정작 배포가 끝났는지
    # 확인하려 할 때 찾지 못했다.
    st.caption(f"혁신제품지원센터 · 빌드 {BUILD_TAG}")
    st.divider()

    # 메뉴 그룹핑
    # 예전에는 '▸ 운영' 캡션 하나 아래 11개가 한 덩어리였다. 성격이 달라 찾기 어렵다.
    # 라디오는 하나로 두되(선택 상태를 나눌 수 없으므로) 구분선으로 묶어 보여준다.
    # 실무자는 회차를 돌리는 데 필요한 네 가지만 본다.
    # 기업 명단·가중치·제외 키워드를 건드리면 매칭이 틀어지므로 담당자만 본다.
    _IS_STAFF = st.session_state.get("role") == "staff"
    if _IS_STAFF:
        _MENU_GROUPS = [
            ("회차 운영", ["대시보드", "공고·매칭", "발송"]),
            ("확인",      ["발송 이력"]),
        ]
    else:
        _MENU_GROUPS = [
            ("운영",   ["대시보드", "공고·매칭", "발송"]),
            ("데이터", ["기업 관리", "발송 이력", "클릭 반응", "교육 신청 집계", "메일 보관함"]),
            ("도구",   ["안내 메일", "캘린더", "설정", "시스템 명세"]),
        ]
    _MENU = [m for _, items in _MENU_GROUPS for m in items]
    _GROUP_OF = {m: g for g, items in _MENU_GROUPS for m in items}

    def _menu_label(m):
        return m

    st.caption("▸ " + " · ".join(g for g, _ in _MENU_GROUPS))
    page = st.radio("메뉴", _MENU, format_func=_menu_label,
                    label_visibility="collapsed")
    st.caption(f"지금 보는 화면 — {_GROUP_OF.get(page, '')} / {page}")
    st.caption("👤 " + ("실무자" if _IS_STAFF else "담당자"))
    st.divider()
    test_mode = st.toggle("테스트 모드", value=True)
    if test_mode: st.warning("테스트 메일 발송")
    else:         st.success("실제 기업 발송")

    # ── 데이터 내보내기 ───────────────────────────────────
    # 진단 추출과 판단 기록 모두 가끔 쓰는 기능이라, 사이드바를 길게 차지하지
    # 않도록 한 묶음으로 접어둔다.
    st.divider()
    # 진단용 추출·판단 기록은 담당자 도구다. 전에는 빈 컨텍스트로 갈랐는데,
    # 파이썬은 with 본문을 건너뛸 수 없으니 접힘만 벗겨져 오히려 실무자에게
    # 활짝 펼쳐져 있었다. 감추려면 블록 자체를 안 타야 한다.
    if not _IS_STAFF:
        with st.expander("📦 데이터 내보내기", expanded=False):
            st.caption("🔍 진단용 결과 추출")
            _mr = st.session_state.get('match_results', [])
            if _mr:
                import io as _io
                _ai = st.session_state.get('ai_analysis', {})
                _rv = st.session_state.get('review_state', {})
                _df = pd.DataFrame(_mr).fillna('')
                def _key(r):
                    return f"{r.get('기업명','')}_{r.get('공고ID','')}"
                _ai_fields = ['추천여부','적합도','한줄요약','업종일치','자격충족',
                              '지역적합','수요일치','판단근거','주의사항']
                for _f in _ai_fields:
                    _df['AI_'+_f] = _df.apply(lambda r: _ai.get(_key(r), {}).get(_f, ''), axis=1)
                _stat = {'○':'승인','✕':'제외'}
                _df['검토상태'] = _df.apply(lambda r: _stat.get(_rv.get(_key(r), ''), '미검토'), axis=1)
                def _agg(g):
                    s = g['관련도'].astype(str)
                    rec = g['AI_추천여부']; stt = g['검토상태']
                    return pd.Series({
                        '매칭건수': len(g),
                        '★★★': (s=='★★★').sum(), '★★': (s=='★★').sum(),
                        'AI추천': (rec=='추천').sum(), 'AI검토': (rec=='검토').sum(),
                        'AI비추천': (rec=='비추천').sum(), 'AI미분석': (rec=='').sum(),
                        '승인': (stt=='승인').sum(), '제외': (stt=='제외').sum(),
                        '미검토': (stt=='미검토').sum(),
                    })
                _summary = _df.groupby('기업명').apply(_agg).reset_index()
                _buf = _io.BytesIO()
                with pd.ExcelWriter(_buf, engine='openpyxl') as _w:
                    _summary.to_excel(_w, index=False, sheet_name='기업별요약')
                    _df.to_excel(_w, index=False, sheet_name='매칭상세')
                st.download_button(
                    "📥 진단용 결과 다운로드",
                    data=_buf.getvalue(),
                    file_name=f"매칭진단_{datetime.today().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
                st.caption(f"기업 {_df['기업명'].nunique()}곳 · 매칭 {len(_df)}건")
            else:
                st.caption("매칭 결과 없음 — 먼저 매칭·AI 분석을 실행하세요")

            st.divider()
            st.caption("📊 판단 기록 (회차별 판단·반응 누적)")
            if st.button("🔄 갱신 (클릭·반응 수집)", key="declog_refresh", use_container_width=True):
                with st.spinner("클릭 로그·반응 회신 수집 중..."):
                    _dd   = _get_drive()
                    _drid = current_round_id()
                    _craw = load_click_log()          # 원본 — 회차 귀속에 시각이 필요하다
                    _cmap = build_click_map(_craw)
                    _rmap = collect_reactions()
                    _smap = load_send_progress(_dd, _drid).get('sent', {}) if _drid else {}
                    _ok_d, _cnt_d = record_decision_log(_dd, _drid, _smap, _cmap, _rmap, _craw)
                if _ok_d:
                    _mr_now = st.session_state.get('match_results', [])
                    st.success(
                        f"갱신 완료 — 누적 {_cnt_d}행"
                        + ("" if _mr_now else
                           " (이번 회차 매칭 결과가 없어 과거 회차의 클릭·출처만 손질했습니다)"))
                else:
                    st.warning("판단 기록이 비어 있거나 저장에 실패했습니다.")

            if '_declog_cache' not in st.session_state:
                st.session_state['_declog_cache'] = load_decision_log(_get_drive())
            _rows_d = st.session_state.get('_declog_cache') or []
            if _rows_d:
                import io as _io2
                _dfd  = pd.DataFrame(_rows_d)
                _bufd = _io2.BytesIO()
                with pd.ExcelWriter(_bufd, engine='openpyxl') as _wd:
                    _dfd.to_excel(_wd, index=False, sheet_name='전체')
                    if '회차ID' in _dfd.columns:
                        _sm_d = _dfd.groupby('회차ID').agg(
                            매칭건수=('공고ID', 'count'),
                            승인=('최종결정', lambda s: (s == '승인').sum()),
                            제외=('최종결정', lambda s: (s == '제외').sum()),
                            발송=('발송여부', lambda s: s.isin(['Y', '참고']).sum()),
                            클릭=('클릭여부', lambda s: (s == 'Y').sum()),
                        ).reset_index()
                        _sm_d.to_excel(_wd, index=False, sheet_name='회차별 요약')
                st.download_button(
                    "📥 판단 기록 다운로드",
                    data=_bufd.getvalue(),
                    file_name=f"판단기록_{datetime.today().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
                _nr = _dfd['회차ID'].nunique() if '회차ID' in _dfd.columns else 0
                st.caption(f"누적 {len(_dfd)}행 · 회차 {_nr}개")
            else:
                st.caption("아직 기록 없음 — 검토 완료 저장·발송 후 쌓입니다")

# 구글 서비스 — 필요할 때 get_creds()로 직접 인증


# ══════════════════════════════════════════════════════
# 대시보드
# ══════════════════════════════════════════════════════
def render_staff_home(df_c, df_n, df_h):
    """실무자 홈 — 이번 회차가 어디까지 왔는지, 무엇을 보고 정하는지.

    담당자 대시보드는 회차별 반응률·운영 기록·클릭 안 한 기업까지 담는다.
    실무자에게는 그게 '지금 무엇을 해야 하나'를 가린다. 흐름과 판단 기준만
    남긴다. 숫자는 이미 세션에 있는 것(매칭 결과·검토 상태·AI 판정)을 쓰므로
    드라이브를 더 읽지 않는다.
    """
    _res = st.session_state.get('match_results', []) or []
    _rv  = st.session_state.get('review_state', {}) or {}
    _ai  = st.session_state.get('ai_analysis', {}) or {}

    def _k(r):
        return f"{r.get('기업명','')}_{r.get('공고ID','')}"

    _n_ok   = sum(1 for r in _res if _rv.get(_k(r), '') == '○')
    _n_no   = sum(1 for r in _res if _rv.get(_k(r), '') == '✕')
    _n_todo = sum(1 for r in _res if _rv.get(_k(r), '') == '')
    _n_rec  = sum(1 for r in _res if (_ai.get(_k(r)) or {}).get('추천여부') == '추천')
    _n_chk  = sum(1 for r in _res if (_ai.get(_k(r)) or {}).get('추천여부') == '검토')
    _co_ok  = len({r.get('기업명','') for r in _res if _rv.get(_k(r), '') == '○'})

    # 보낼 수 있는 공고 — 마감이 아직 안 지난 것
    _active = 0
    if not df_n.empty and '마감일' in df_n.columns:
        _today = datetime.today().strftime('%Y-%m-%d')
        _active = int((df_n['마감일'].astype(str) >= _today).sum())
    _sel_co = int((df_c['선정구분'] == '선정').sum()) if '선정구분' in df_c.columns else len(df_c)
    _month_h = 0
    if not df_h.empty and '발송일' in df_h.columns:
        _ym = datetime.today().strftime('%Y-%m')
        _month_h = int(df_h['발송일'].astype(str).str.startswith(_ym).sum())

    _rid = current_round_id()
    st.caption(f"회차 {_rid or '— 아직 매칭을 돌리지 않았습니다'}"
               f"  ·  기준일 {datetime.today().strftime('%Y-%m-%d')}")

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("안내 대상 기업", f"{_sel_co}개사")
    # delta 를 그냥 두면 '전체 6,105건'이 초록 ↑ 로 붙어 늘어난 것처럼 보인다.
    # 여기 보조 숫자는 증감이 아니라 맥락이므로 색을 끈다.
    s2.metric("보낼 수 있는 공고", f"{_active:,}건", f"전체 {len(df_n):,}건",
              delta_color="off")
    s3.metric("이번 회차 승인", f"{_n_ok:,}건", f"{_co_ok}개사",
              delta_color="off")
    s4.metric("이번 달 발송", f"{_month_h}건")

    st.divider()

    # ── 흐름 5단계 ────────────────────────────────────
    STEPS = [
        ("1", "공고 모으기",
         f"보낼 수 있는 공고 {_active:,}건",
         "기업마당에서 매일 아침 자동으로 받아옵니다. 손대실 것 없습니다.",
         _active > 0),
        ("2", "기업별로 고르기",
         f"{len(_res):,}건 찾음" if _res else "아직 안 돌렸습니다",
         "기업의 업종·관심분야·지역을 공고와 맞춰 점수를 냅니다. "
         "이미 보낸 공고와 마감이 지난 공고는 여기서 자동으로 빠집니다.",
         bool(_res)),
        ("3", "안 맞는 것 거르기",
         f"추천 {_n_rec:,} · 검토 {_n_chk:,} · 제외 {_n_no:,}" if _res else "—",
         "점수만으로는 못 거르는 것이 있습니다. 판금 가공 전시회에 핀테크 "
         "기업이 71점으로 올라오는 식입니다. 그런 것을 AI가 뺍니다.",
         _n_no > 0),
        ("4", "남은 것 확인하기",
         f"승인 {_n_ok:,}건 · 아직 {_n_todo:,}건" if _res else "—",
         "같은 공고가 여러 기업에 걸립니다. 기업을 하나씩 넘기지 마시고 "
         "'공고 하나를 여러 기업에 한 번에 처리'를 쓰시면 빠릅니다.",
         _n_ok > 0 and _n_todo == 0),
        ("5", "보내기",
         f"{_n_ok:,}건 대기" if _n_ok else "승인하시면 열립니다",
         "'보내기 전 점검'을 통과해야 발송 버튼이 열립니다. "
         "테스트 모드로 먼저 한 통 받아보시고 실제 발송하십시오.",
         False),
    ]
    for _no, _title, _stat, _desc, _done in STEPS:
        _mark = "✅" if _done else ("⏳" if _no == "4" and _res else "⬜")
        st.markdown(
            f"**{_mark} {_no}. {_title}**"
            f"<span style='color:#9AA4B2;font-size:13px;margin-left:10px;'>{_stat}</span>",
            unsafe_allow_html=True)
        st.caption("　　" + _desc)

    st.divider()

    # ── 판단 기준 ─────────────────────────────────────
    with st.expander("📖 무엇을 보고 정하나 — 화면의 숫자와 표시 읽는 법", expanded=False):
        st.markdown("""
#### 점수
공고와 기업이 얼마나 맞는지를 아래를 더해서 냅니다.

| 보는 것 | 가중치 |
|---|---|
| 지원대상이 맞나 (조달기업·수출기업 …) | ×3 |
| 사업 성격이 맞나 (공공조달·해외진출 …) | ×2 |
| 기업 키워드가 공고에 나오나 | ×2 |
| 핵심수요 태그가 맞나 | ×3 (맞으면 +8) |
| 같은 지역인가 | +2~3 |
| 다른 지역 한정인가 | −5 |

지난 두 회차를 세어 보면 **점수가 높을수록 실제로 더 눌렀습니다.**
40점대는 6%, 60점 이상은 29%가 공고를 열어봤습니다.

#### ★ 별점은 점수가 아닙니다
지금 별점은 **지역**을 뜻합니다. 같은 지역이면 ★★★, 다른 지역 한정이면
★★로 한 단계 내려갑니다. 그래서 30점짜리와 70점짜리가 똑같이 ★★★입니다.
**별점 대신 점수를 보십시오.**

#### AI 판정
* **추천** — 바로 보내도 되는 것
* **검토** — 사람이 봐야 하는 것. 대부분 *설립 몇 년 됐는지 몰라서* 입니다
  (선정기업 명단에 설립연도가 비어 있으면 업력 조건을 확인할 수 없습니다)
* **비추천** — 업종이 안 맞거나 다른 지역 한정. 자동으로 빠집니다

#### ⚠ 승인하셔도 메일에 실리지 않습니다
접수기간이 `세부사업별 상이` 이거나 `예산 소진시까지` 인 공고입니다.
언제 끝나는지 알 수 없어서, 이미 끝난 공고를 보내지 않으려고 뺍니다.
승인 버튼 위에 이 문구가 보이면 다른 공고를 하나 더 승인해 주십시오.

---

#### 승인할지 말지 헷갈리실 때
* 이 기업이 **실제로 신청할 수 있는** 공고인가 — 업종·자격·지역
* 포상·표창처럼 **이미 실적이 있어야** 하는 공고는 아닌가
* 애매하면 **넘기셔도 됩니다.** 안 보내서 생기는 손해보다, 안 맞는 걸
  보내서 다음부터 안 열게 되는 손해가 큽니다
        """)

    st.caption("막히는 데가 있으면 담당자에게 알려주십시오. "
               "숫자가 오래된 것 같으면 위의 🔄 새로고침을 누르시면 됩니다.")


if page == "대시보드":
    drive = _get_drive()
    st.title("이번 회차, 어디까지 왔나" if _IS_STAFF else "📊 운영 대시보드")

    _c1, _c2 = st.columns([5, 1])
    _c2.caption("")
    if _c2.button("🔄 새로고침", key="dash_refresh", use_container_width=True,
                  help="캐시를 비우고 드라이브에서 다시 읽습니다 (기본 10분 캐시)"):
        read_excel_cached.clear()
        read_json_cached.clear()
        st.rerun()

    with st.spinner("데이터 로딩 중..."):
        df_c  = read_excel_cached(SELECTED_FILE)
        df_n  = read_excel_cached(NOTICES_FILE)
        df_h  = read_excel_cached(HISTORY_FILE)
        # 공고전문(3.2MB)은 '크롤링 몇 건 남았나'에만 쓰인다. 크롤러가 남기는
        # 가벼운 요약이 있으면 그걸 쓰고, 없을 때만 전문 파일을 읽는다.
        _det_sum = read_json_cached(DETAIL_SUMMARY_FILE)
        df_det = pd.DataFrame() if _det_sum else read_excel_cached(DETAIL_FILE)

    # ── 실무자 홈 ─────────────────────────────────────
    # 아래 담당자 화면은 회차별 반응률·운영 기록까지 담는다. 실무자에게는
    # 그게 '지금 무엇을 해야 하나'를 가리므로 흐름과 기준만 보여주고 멈춘다.
    if _IS_STAFF:
        render_staff_home(df_c, df_n, df_h)
        st.stop()

    # ── 상단 핵심 지표 4개 ─────────────────────────────
    m1, m2, m3, m4 = st.columns(4)

    # 선정 기업
    total_co = len(df_c)
    sel_co   = (df_c['선정구분']=='선정').sum() if '선정구분' in df_c.columns else total_co
    res_co   = (df_c['선정구분']=='예비').sum() if '선정구분' in df_c.columns else 0
    m1.metric("선정 기업", f"{sel_co}개사", f"예비 {res_co}개사")

    # 공고 DB
    active_n = 0
    if not df_n.empty and '마감일' in df_n.columns:
        today_str = datetime.today().strftime('%Y-%m-%d')
        active_n = (df_n['마감일'] >= today_str).sum()
    m2.metric("활성 공고", f"{active_n:,}건", f"전체 {len(df_n):,}건")

    # 최근 회차 반응 — 판단 기록에서 자동 집계
    _dl_rows = (read_json_cached(DECISION_LOG_FILE) or {}).get('rows', [])
    _stats   = round_stats(_dl_rows)
    if _stats:
        _last = _stats[-1]
        m3.metric("최근 회차 반응",
                  f"{_last['클릭기업비율']:.0f}%",
                  f"열람 {_last['열람기업비율']:.0f}% · 발송 {_last['발송기업']}개사")
    else:
        m3.metric("최근 회차 반응", "—", "판단 기록 없음")

    # 발송 이력
    this_month_h = 0
    if not df_h.empty and '발송일' in df_h.columns:
        this_month = datetime.today().strftime('%Y-%m')
        this_month_h = df_h['발송일'].astype(str).str.startswith(this_month).sum()
    m4.metric("이번 달 발송", f"{this_month_h}건", f"누적 {len(df_h)}건")

    st.divider()

    # ── 이번 주 할 일 체크리스트 ───────────────────────
    st.subheader("🗂 이번 주 운영 체크리스트")

    # 각 단계 상태 자동 판단
    last_collect = "—"
    if not df_n.empty and '수정일' in df_n.columns:
        last_collect = df_n['수정일'].max()[:10] if df_n['수정일'].max() else "—"

    last_crawl = "—"
    need_crawl_cnt = 0
    crawl_ok = 0
    have_crawl = False       # 전문 수집 정보를 가지고 있는가 (요약이든 원본이든)
    if _det_sum:
        last_crawl = str(_det_sum.get('마지막크롤링일', '') or '—')[:10]
        need_crawl_cnt = max(0, int(_det_sum.get('미수집', 0) or 0))
        crawl_ok = int(_det_sum.get('성공', 0) or 0)
        have_crawl = True
    else:
        have_crawl = not df_det.empty
        if not df_det.empty and '크롤링일' in df_det.columns:
            last_crawl = df_det['크롤링일'].max()[:10] if df_det['크롤링일'].max() else "—"
        if not df_det.empty:
            crawl_ok = int((df_det['크롤링성공'] == 'Y').sum())                 if '크롤링성공' in df_det.columns else int(len(df_det))
        if not df_n.empty and not df_det.empty and 'pblancId' in df_n.columns and 'pblancId' in df_det.columns:
            crawled_pids = set(df_det[df_det.get('크롤링성공',pd.Series(''))=='Y']['pblancId']) if '크롤링성공' in df_det.columns else set()
            need_crawl_cnt = len(set(df_n['pblancId']) - crawled_pids)

    results      = st.session_state.get('match_results', [])
    review_state = st.session_state.get('review_state', {})
    # 이번 회차 매칭 결과에 있는 공고만 집계 (이월된 ✕가 숫자를 부풀리지 않도록)
    _rv_keys     = {f"{r.get('기업명','')}_{r.get('공고ID','')}" for r in results}
    approved     = sum(1 for k in _rv_keys if review_state.get(k) == "○")
    pending_rev  = len(results) - sum(1 for k in _rv_keys if review_state.get(k) in ("○", "✕"))

    steps_data = [
        {
            "step": "① 공고 수집",
            "status": "완료" if not df_n.empty else "필요",
            "ok": not df_n.empty,
            "detail": f"마지막 수집: {last_collect} / 활성 공고 {active_n}건" if not df_n.empty else "공고 수집 탭에서 실행 필요",
            "action": "공고 수집"
        },
        {
            "step": "② 전문 크롤링",
            "status": "완료" if need_crawl_cnt == 0 else f"{need_crawl_cnt}건 대기",
            "ok": need_crawl_cnt == 0,
            "detail": (f"수집 완료 {crawl_ok:,}건 / 미수집 {need_crawl_cnt:,}건"
                       if have_crawl else "크롤링 미실행"),
            "action": "공고 수집"
        },
        {
            "step": "③ 매칭 실행",
            "status": "완료" if results else "미실행",
            "ok": bool(results),
            "detail": f"매칭 결과 {len(results)}건 로드됨" if results else "매칭 결과 탭에서 실행 필요",
            "action": "매칭 결과"
        },
        {
            "step": "④ 검토 & 승인",
            "status": "완료" if (results and pending_rev==0) else (f"{pending_rev}건 미검토" if results else "매칭 후 진행"),
            "ok": results and pending_rev == 0,
            "detail": f"승인 {approved}건 / 미검토 {pending_rev}건" if results else "매칭 실행 후 가능",
            "action": "매칭 결과"
        },
        {
            "step": "⑤ 발송",
            "status": "발송 가능" if approved > 0 else "승인 후 진행",
            "ok": False,
            "detail": f"승인된 공고 {approved}건 발송 대기" if approved > 0 else "검토 승인 후 발송 가능",
            "action": "발송 관리"
        },
    ]

    for s in steps_data:
        icon = "✅" if s['ok'] else ("🟡" if "대기" in s['status'] or "가능" in s['status'] else "⬜")
        c1, c2, c3 = st.columns([2, 4, 2])
        with c1:
            st.write(f"{icon} **{s['step']}**")
        with c2:
            st.caption(s['detail'])
        with c3:
            if s['ok']:
                badge_bg, badge_color = "#0A2E1F", "#4DFFAA"
            elif icon == "🟡":
                badge_bg, badge_color = "#2D1E00", "#FFD080"
            else:
                badge_bg, badge_color = "#1A1A1A", "#888888"
            st.markdown(
                f"<span style='background:{badge_bg};color:{badge_color};padding:3px 10px;"
                f"border-radius:6px;font-size:11px;font-weight:700;"
                f"border:1px solid {badge_color}44;'>{s['status']}</span>",
                unsafe_allow_html=True
            )

    st.divider()

    st.divider()

    # ── 최근 회차 성과 (판단 기록에서 자동) ───────────────
    # 예전 대시보드는 활동 타임라인을 사람이 직접 적어 넣는 구조라 손이 안 갔다.
    # 이제 판단 기록이 회차별로 쌓이므로 수치는 전부 자동으로 나온다.
    st.divider()
    st.subheader("📈 회차별 성과")
    _stats = round_stats(_dl_rows)
    if not _stats:
        st.info("판단 기록이 아직 없습니다. 발송 후 '발송 → 데이터 내보내기 → 🔄 갱신'을 누르면 쌓입니다.")
    else:
        _last = _stats[-1]
        _prev = _stats[-2] if len(_stats) > 1 else None
        r1, r2, r3, r4 = st.columns(4)

        def _delta(cur, key):
            if not _prev:
                return None
            return f"{cur - _prev[key]:+.0f}%p"

        r1.metric("발송", f"{_last['발송기업']}개사",
                  f"공고 {_last['발송공고']}건", delta_color="off")
        r2.metric("열람 기업", f"{_last['열람기업비율']:.0f}%",
                  _delta(_last['열람기업비율'], '열람기업비율'))
        r3.metric("클릭 기업", f"{_last['클릭기업비율']:.0f}%",
                  _delta(_last['클릭기업비율'], '클릭기업비율'))
        r4.metric("공고 클릭률", f"{_last['공고클릭률']:.0f}%",
                  _delta(_last['공고클릭률'], '공고클릭률'))
        st.caption(f"최근 회차 {_last['회차ID']} · 발송 {_last['발송일'] or '—'}  ·  "
                   f"본 공고 {_last['본공고클릭률']:.0f}% / 참고 공고 {_last['참고클릭률']:.0f}%"
                   + ("  ·  열람률은 이미지 차단 때문에 과소집계됩니다" if _last['열람기업비율'] else ""))

        _tbl = pd.DataFrame([{
            '회차': x['회차ID'], '발송일': x['발송일'],
            '기업': x['발송기업'], '공고': x['발송공고'],
            '열람기업%': round(x['열람기업비율']), '클릭기업%': round(x['클릭기업비율']),
            '공고클릭률%': round(x['공고클릭률']),
            '본공고%': round(x['본공고클릭률']), '참고%': round(x['참고클릭률']),
        } for x in _stats[-6:]])
        st.dataframe(_tbl, use_container_width=True, hide_index=True)

        # ── 손 써야 할 기업 ──
        _silent = silent_companies(_dl_rows, last_n=3)
        _used = [x['회차ID'] for x in round_stats(_dl_rows)][-3:]
        st.markdown("")
        if _silent:
            st.warning(f"최근 회차에서 한 번도 클릭하지 않은 기업 — {len(_silent)}개사")
            st.caption("메일을 고쳐서 풀릴 문제가 아닐 수 있습니다(담당자 변경·주소 오류·스팸함). "
                       "전화로 수신 담당자를 확인하는 편이 빠릅니다.")
            st.code("  ·  ".join(_silent), language=None)
        else:
            st.success("최근 3회차 안에 모든 기업이 한 번 이상 반응했습니다.")


    # ── 운영 활동 타임라인 (수기 기록) ────────────────────
    # 직접 적어 넣어야 해서 거의 쓰이지 않았다. 드라이브에 남은 과거 기록이 있으므로
    # 지우지 않고 접어 둔다 — 필요할 때만 펴보면 된다.
    st.divider()
    with st.expander("📋 운영 활동 타임라인 (직접 기록)", expanded=False):
        # ── 운영 활동 타임라인 ───────────────────────────────────
        st.subheader("📋 운영 활동 타임라인")

        TIMELINE_FILE = "timeline_log.json"

        # 타임라인 데이터 로드
        def load_timeline(drive):
            try:
                data = load_json(drive, TIMELINE_FILE)
                return data if data else []
            except:
                return []

        def save_timeline(drive, data):
            save_json(drive, data, TIMELINE_FILE)

        if 'timeline_data' not in st.session_state:
            raw = load_timeline(drive)
            # 드라이브 데이터가 없거나 비어있으면 기본 활동 기록 삽입
            DEFAULT_TIMELINE = [
                {
                    'date': '2026-04-29',
                    'type': 'eval',
                    'title': '2026 원스톱 스케일업 참가 신청 접수 시작',
                    'desc': '선정 대상 기업 공개 모집 · 온라인 신청 폼 운영',
                    'count': '접수 기간 4/29~5/22',
                    'note': '',
                },
                {
                    'date': '2026-05-22',
                    'type': 'eval',
                    'title': '참가 신청 접수 마감',
                    'desc': '총 184개사 신청 접수',
                    'count': '184개사',
                    'note': '',
                },
                {
                    'date': '2026-06-22',
                    'type': 'eval',
                    'title': '2026 원스톱 스케일업 최종 선정 확정',
                    'desc': '1단계 평가 → 상위 70개사 선정 확정',
                    'count': '선정 50개사 · 예비 20개사',
                    'note': '184개사 중 70개사',
                },
                {
                    'date': '2026-06-26',
                    'type': 'mail',
                    'title': '선정기업 대상 첫 안내 메일 발송',
                    'desc': '선정 축하 · 프로그램 안내 · 키워드 회신 요청',
                    'count': '50개사',
                    'note': '',
                },
                {
                    'date': '2026-07-06',
                    'type': 'match',
                    'title': '맞춤형 공고 1차 발송',
                    'desc': '나라장터 공고 크롤링 → 기업별 키워드 매칭 → 개별 발송 · 캘린더 자동 등록',
                    'count': '50개사 · 캘린더 21건',
                    'note': '',
                },
                {
                    'date': '2026-07-14',
                    'type': 'mail',
                    'title': '7월 교육 프로그램 신청 안내 발송',
                    'desc': 'AI 마케팅/콘텐츠 제작 활용 교육 안내 · CES 밋업 안내 포함',
                    'count': '50개사',
                    'note': '신청 마감 7/17(금) 18:00',
                },
                {
                    'date': '2026-07-29',
                    'type': 'edu',
                    'title': '7월 정기 교육 — AI 마케팅/콘텐츠 제작 활용',
                    'desc': '온라인 Zoom · 강사: 송윤경 (소상공인연합회)',
                    'count': '',
                    'note': '14:00~16:00 예정',
                },
            ]
            if not raw:
                raw = DEFAULT_TIMELINE
                save_timeline(drive, raw)
            st.session_state['timeline_data'] = raw
        tl_data = st.session_state['timeline_data']

        # 필터
        TYPE_LABELS = {
            "all": "전체",
            "mail": "📧 메일 발송",
            "match": "🎯 공고 매칭",
            "edu": "📚 교육",
            "meetup": "🤝 밋업",
            "system": "⚙️ 시스템",
            "eval": "📊 평가·선정",
        }
        TYPE_COLORS = {
            "mail": "#3B82F6", "match": "#F43F5E", "edu": "#10B981",
            "meetup": "#F59E0B", "system": "#8B5CF6", "eval": "#F59E0B",
        }
        TYPE_BADGE = {
            "mail": "background:#001020;color:#1D4ED8",
            "match": "background:#FFF1F2;color:#BE123C",
            "edu": "background:#0A1A0F;color:#059669",
            "meetup": "background:#1A0A00;color:#C2410C",
            "system": "background:#F5F3FF;color:#6D28D9",
            "eval": "background:#FFFBEB;color:#92400E",
        }

        filter_cols = st.columns(len(TYPE_LABELS))
        tl_filter = st.session_state.get('tl_filter', 'all')
        for i, (k, v) in enumerate(TYPE_LABELS.items()):
            with filter_cols[i]:
                is_active = tl_filter == k
                label = f"**{v}**" if is_active else v
                if st.button(
                    label,
                    key=f"tl_f_{k}",
                    type="primary" if is_active else "secondary",
                    use_container_width=True
                ):
                    st.session_state['tl_filter'] = k
                    st.rerun()

        tl_filter = st.session_state.get('tl_filter', 'all')
        filtered = [t for t in sorted(tl_data, key=lambda x: x.get('date',''), reverse=True)
                    if tl_filter == 'all' or t.get('type') == tl_filter]

        if not filtered:
            st.info("활동 기록이 없습니다. 아래에서 추가해주세요.")
        else:
            # 월별 그룹
            from itertools import groupby
            def month_key(item):
                d = item.get('date','')
                return d[:7] if d else '0000-00'

            for month, items in groupby(filtered, key=month_key):
                try:
                    import datetime as _dt2
                    yr, mo = int(month[:4]), int(month[5:7])
                    mo_label = f"{yr}년 {mo}월"
                except:
                    mo_label = month

                st.markdown(f"<p style='font-size:10px;font-weight:900;color:#C9A96A;letter-spacing:3px;text-transform:uppercase;margin:16px 0 8px 0;'>{mo_label}</p>", unsafe_allow_html=True)

                for item in items:
                    t = item.get('type','system')
                    color = TYPE_COLORS.get(t, '#94A3B8')
                    badge_style = TYPE_BADGE.get(t, 'background:#F1F5F9;color:#AAAAAA')
                    badge_label = TYPE_LABELS.get(t, t)
                    date_str = item.get('date','')
                    try:
                        d = datetime.strptime(date_str, '%Y-%m-%d')
                        day = d.strftime('%d')
                        dow = ['월','화','수','목','금','토','일'][d.weekday()]
                    except:
                        day, dow = '??', ''

                    meta_parts = []
                    if item.get('count'): meta_parts.append(f"📤 {item['count']}")
                    if item.get('note'): meta_parts.append(f"📝 {item['note']}")
                    meta_html = '&nbsp;·&nbsp;'.join(meta_parts)

                    st.markdown(f"""
    <div style="display:flex;gap:10px;align-items:flex-start;margin-bottom:8px;">
      <div style="width:36px;text-align:right;flex-shrink:0;padding-top:8px;">
        <div style="font-size:16px;font-weight:900;color:#F0F0F0;">{day}</div>
        <div style="font-size:10px;color:#666666;">{dow}</div>
      </div>
      <div style="width:10px;height:10px;border-radius:50%;background:{color};flex-shrink:0;margin-top:13px;box-shadow:0 0 8px {color},0 0 16px {color}66;"></div>
      <div style="background:#151515;border-radius:10px;padding:10px 14px;flex:1;border:1px solid #252525;border-left:3px solid {color};">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;">
          <span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;background:{color}22;color:{color};">{badge_label}</span>
          <span style="font-size:13px;font-weight:600;color:#F0F0F0;">{item.get('title','')}</span>
        </div>
        <div style="font-size:11px;color:#AAAAAA;line-height:1.5;">{item.get('desc','')}</div>
        {"<div style='font-size:10px;color:#888888;margin-top:4px;'>" + meta_html + "</div>" if meta_html else ""}
      </div>
    </div>""", unsafe_allow_html=True)

        st.divider()

        # 활동 추가
        col_add, col_reset = st.columns([5, 1])
        with col_reset:
            if st.button("🔄 초기화", key="tl_reset", help="기본 데이터로 초기화"):
                save_timeline(drive, DEFAULT_TIMELINE)
                st.session_state['timeline_data'] = DEFAULT_TIMELINE
                st.success("초기화 완료")
                st.rerun()

        st.markdown("""
    <style>
    .bp-egg { 
      opacity: 0 !important;
      transition: opacity 0.4s !important;
      text-align: right;
      font-size: 13px;
      letter-spacing: 3px;
      font-weight: 900;
      color: #C9A96A !important;
      margin-top: 32px;
      cursor: default;
      user-select: none;
    }
    .bp-egg:hover { opacity: 1 !important; }
    </style>
    <p class="bp-egg">BLACKPINK IN MY AREA</p>
    """, unsafe_allow_html=True)

        with st.expander("➕ 활동 기록 추가"):
            a1, a2, a3 = st.columns([1.5, 2, 1.5])
            with a1:
                new_date = st.date_input("날짜", key="tl_new_date")
                new_type = st.selectbox("유형", list(TYPE_LABELS.keys())[1:],
                                        format_func=lambda x: TYPE_LABELS[x], key="tl_new_type")
            with a2:
                new_title = st.text_input("제목", key="tl_new_title")
                new_desc  = st.text_input("설명 (선택)", key="tl_new_desc")
            with a3:
                new_count = st.text_input("수량 (선택, 예: 50개사)", key="tl_new_count")
                new_note  = st.text_input("비고 (선택)", key="tl_new_note")

            if st.button("✅ 추가", type="primary", key="tl_add_btn"):
                if new_title:
                    new_item = {
                        'date': str(new_date),
                        'type': new_type,
                        'title': new_title,
                        'desc': new_desc,
                        'count': new_count,
                        'note': new_note,
                    }
                    tl_data.append(new_item)
                    save_timeline(drive, tl_data)
                    st.session_state['timeline_data'] = tl_data
                    st.success(f"'{new_title}' 추가됐습니다.")
                    st.rerun()

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

        # ── 선정/예비 구분 ─────────────────────────────────
        has_status = '선정구분' in df_c.columns
        df_선정 = df_c[df_c['선정구분']=='선정'] if has_status else df_c
        df_예비 = df_c[df_c['선정구분']=='예비'] if has_status else pd.DataFrame()

        # ── 상단 메트릭 ────────────────────────────────────
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("전체", f"{len(df_c)}개사")
        c2.metric("선정", f"{len(df_선정)}개사")
        c3.metric("예비", f"{len(df_예비)}개사")
        c4.metric("수신거부", f"{(df_c['수신거부']=='Y').sum()}개사")
        st.divider()

        # ── 파일 교체 ──────────────────────────────────────
        with st.expander("📁 선정기업 명단 파일 교체"):
            uploaded = st.file_uploader("새 파일 업로드", type=["xlsx"], key="replace")
            if uploaded:
                df_new = pd.read_excel(uploaded, dtype=str).fillna("")
                for col in ['키워드보완','수신거부','메모','구글계정']:
                    if col not in df_new.columns: df_new[col] = ''
                if save_excel(drive, df_new, SELECTED_FILE, "선정기업명단", "1F4E79"):
                    st.success("교체 완료!"); st.rerun()

        if '기업명' not in df_c.columns:
            st.error(f"'기업명' 컬럼을 찾을 수 없음 — 현재 컬럼: {', '.join(df_c.columns.tolist())}")
            st.stop()

        # ── 탭 분리 ────────────────────────────────────────
        if has_status:
            tab_labels = [f"🟢 선정 {len(df_선정)}개사", f"🟡 예비 {len(df_예비)}개사", f"📋 전체 {len(df_c)}개사"]
        else:
            tab_labels = [f"📋 전체 {len(df_c)}개사"]
        tabs = st.tabs(tab_labels)

        def render_company_list(df_target, tab_key):
            search = st.text_input("🔍 기업명 검색", key=f"search_{tab_key}")
            df_show = df_target[df_target['기업명'].str.contains(search, na=False)] if search else df_target

            for idx, row in df_show.iterrows():
                unsub = str(row.get('수신거부','')) == 'Y'
                icon  = "🚫" if unsub else "🏢"
                status_badge = f"[{row.get('선정구분','')}]" if has_status and row.get('선정구분','') else ""
                score_badge  = f"총점 {row.get('평가_총점','')}점" if row.get('평가_총점','') else ""

                with st.expander(f"{icon} **{row.get('기업명','')}**  {status_badge}  |  {row.get('소재지','')}  |  {score_badge}"):
                    c1,c2 = st.columns(2)
                    with c1:
                        st.markdown(f"**소재지:** {row.get('소재지','')}")
                        st.markdown(f"**이메일:** {row.get('이메일','')}")
                        st.markdown(f"**관심분야:** {row.get('관심사업분야','')}")
                        st.markdown(f"**수출:** {row.get('수출실적','')} / {row.get('수출국가','')}")
                        st.markdown(f"**TRL단계:** {row.get('TRL단계','')}")
                        if row.get('평가_총점',''):
                            st.markdown(f"**평가점수:** 정량 {row.get('평가_정량점수','')}점 / 총점 {row.get('평가_총점','')}점")
                    with c2:
                        st.markdown(f"**제품분야:** {row.get('제품분야','')}")
                        st.markdown(f"**기술키워드:** {row.get('기술키워드','')}")
                        st.markdown(f"**핵심수요태그:** {row.get('핵심수요태그','')}")
                        st.markdown(f"**사업자번호:** {row.get('사업자등록번호','')}")
                        if row.get('평가_내부논의',''):
                            st.markdown(f"**평가의견:** {row.get('평가_내부논의','')}")

                    extra_kw   = st.text_input("키워드 보완", value=row.get('키워드보완',''),
                                    key=f"kw_{tab_key}_{idx}", placeholder="예: 스마트팜, IoT")
                    google_acc = st.text_input("구글계정", value=row.get('구글계정',''),
                                    key=f"ga_{tab_key}_{idx}", placeholder="example@gmail.com")
                    unsub_cb   = st.checkbox("수신거부", value=unsub, key=f"unsub_{tab_key}_{idx}")
                    memo       = st.text_input("메모", value=row.get('메모',''), key=f"memo_{tab_key}_{idx}")

                    if st.button("💾 저장", key=f"save_{tab_key}_{idx}"):
                        df_c.at[idx,'키워드보완'] = extra_kw
                        df_c.at[idx,'구글계정']   = google_acc
                        df_c.at[idx,'수신거부']   = 'Y' if unsub_cb else ''
                        df_c.at[idx,'메모']       = memo
                        with st.spinner("드라이브 저장 중..."):
                            if save_excel(drive, df_c, SELECTED_FILE, "선정기업명단", "1F4E79"):
                                st.success(f"{row['기업명']} 저장 완료!")

        if has_status:
            with tabs[0]: render_company_list(df_선정, "sel")
            with tabs[1]: render_company_list(df_예비, "res")
            with tabs[2]: render_company_list(df_c,   "all")
        else:
            with tabs[0]: render_company_list(df_c, "all")


# ══════════════════════════════════════════════════════
# 공고 수집
# ══════════════════════════════════════════════════════
elif page == "공고·매칭":
    drive = _get_drive()
    st.title("공고·매칭")

    tab_cm1, tab_cm1b, tab_cm2 = st.tabs(["📊 공고 현황", "🔍 전문 크롤링", "🎯 매칭 실행·검토"])

    with tab_cm1:
        info_box("공고 현황 (읽기 전용)",
            """
공고 수집은 **로컬 PC에서 실행**하고, 앱은 드라이브에 저장된 공고를 **읽기만** 합니다.

**왜 이렇게 바뀌었나요?**
- 기업마당 API가 해외 서버(앱 호스팅)의 접근을 차단하여, 앱에서 직접 수집 시 연결 타임아웃이 발생합니다.
- 로컬 PC(국내)에서는 정상 수집되므로, 수집은 로컬에서 하고 앱은 그 결과를 읽습니다.

**수집 방법 (주 1회 권장)**
1. 로컬 폴더에서 `python crawl_notices.py` 실행
2. 기업마당 전체 공고 수집 + 전문 크롤링 → 드라이브 자동 업로드
3. 앱은 아래 현황이 갱신되며, 바로 '매칭 실행' 탭에서 매칭 가능
            """,
            "수집은 로컬 crawl_notices.py로 — 앱에서는 매칭만 실행")

        with st.spinner("드라이브에서 공고 DB 로딩 중..."):
            df_n = load_excel(drive, NOTICES_FILE)

        if not df_n.empty:
            c1, c2, c3 = st.columns(3)
            db_count = len(df_n)
            c1.metric("현재 공고 DB", f"{db_count:,}건")
            c2.metric("마지막 수집일", df_n['수집일'].max() if '수집일' in df_n.columns else "—")
            _active = (df_n['마감일'] >= datetime.today().strftime("%Y-%m-%d")).sum() if '마감일' in df_n.columns else 0
            c3.metric("마감 유효 공고", f"{_active:,}건")

            # 최신성 안내
            _last = df_n['수집일'].max() if '수집일' in df_n.columns else ""
            if _last:
                try:
                    _days_ago = (datetime.today().date() - datetime.strptime(_last, "%Y-%m-%d").date()).days
                    if _days_ago == 0:
                        st.success(f"✅ 오늘 수집된 최신 공고입니다 ({db_count:,}건)")
                    elif _days_ago <= 7:
                        st.info(f"📅 마지막 수집: {_days_ago}일 전 ({_last}) — 매칭에 사용 가능합니다")
                    else:
                        st.warning(f"⚠️ 마지막 수집이 {_days_ago}일 전({_last})입니다 — 로컬에서 `crawl_notices.py` 재실행을 권장합니다")
                except Exception:
                    pass
        else:
            st.warning("공고 DB가 비어 있습니다 — 로컬에서 `crawl_notices.py`를 실행해 공고를 수집해 주세요.")

        st.divider()

        # 로컬 수집 명령 안내 (복사용)
        with st.expander("💻 로컬 수집 명령어 (복사용)", expanded=False):
            st.code(
                'cd "C:\\\\Users\\\\fbwlg\\\\Desktop\\\\26년도\\\\2. 원스톱\\\\7. 정보 전달 체계 구축"\n'
                'python crawl_notices.py',
                language="powershell")
            st.caption("실행하면 기업마당 전체 공고 수집 + 전문 크롤링 후 드라이브에 자동 업로드됩니다. "
                       "완료 후 이 화면을 새로고침하면 현황이 갱신됩니다.")

        if st.button("🔄 현황 새로고침"):
            st.rerun()

        if not df_n.empty:
            st.divider()
            st.subheader("공고 DB 미리보기 (최근 20건)")
            cols = [c for c in ["공고명","주관기관","분야","접수기간","마감일"] if c in df_n.columns]
            _prev = df_n.copy()
            if '수집일' in _prev.columns:
                _prev = _prev.sort_values('수집일', ascending=False)
            render_html_table(_prev[cols].head(20), max_rows=20)

    with tab_cm1b:
        st.subheader("📄 공고 전문 크롤링")
        st.caption("수집된 공고의 상세 내용을 크롤링합니다. 전문이 있어야 매칭 정확도가 높아집니다.")

        st.info("💻 전문 크롤링도 **로컬 PC에서 `crawl_notices.py`** 실행 시 함께 처리됩니다 "
                "(공고 수집 + 전문 크롤링 통합). 아래는 현재 전문 DB 현황이며, 앱에서 직접 크롤링은 "
                "기업마당 접근 차단으로 권장하지 않습니다.")

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

            # ── 권장: GitHub Actions에 위임 (Streamlit Cloud는 chromium 실행이 불안정) ──
            _cA, _cB = st.columns([1, 1])
            with _cA:
                if st.button("☁️ GitHub Actions로 크롤링 실행 (권장)",
                             type="primary", key="crawl_gh_btn"):
                    _ok, _err = trigger_github_crawl(crawl_limit)
                    if _ok:
                        st.success("크롤링 실행을 요청했습니다. GitHub Actions에서 진행됩니다 (수 분 소요).")
                        st.markdown("[▶ 진행 상황 보기]"
                                    "(https://github.com/onestopkipcc-web/scaleup-matching/actions)")
                        st.caption("완료 후 이 페이지를 새로고침하면 갱신된 전문 DB가 반영됩니다.")
                    else:
                        st.error(f"실행 요청 실패 — {_err}")
            with _cB:
                st.caption("이 앱 서버에서 직접 실행 (환경에 따라 실패할 수 있음)")

            if st.button("🕷️ 지금 크롤링 실행", key="crawl_btn"):
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

                # bizinfo 상세페이지는 SPA(JS 렌더링) 구조라 requests로는 빈 body만 받아온다
                # (실측: html 8~9만자, body 자식태그 0개 — 진단 확정됨) → Playwright로 브라우저를 띄워 렌더링 후 텍스트 추출
                with st.spinner("Chromium 준비 중... (최초 1회 최대 3분)"):
                    _pw_ok, _pw_err = install_playwright()
                if not _pw_ok:
                    st.error(f"Chromium 설치 실패 — 상세 크롤링을 실행할 수 없습니다.\n\n{_pw_err}")
                    st.info("requirements.txt에 `playwright`, packages.txt에 시스템 라이브러리가 "
                            "포함됐는지 확인 후 재배포해 주세요.")
                    st.stop()
                try:
                    from playwright.sync_api import sync_playwright
                except ModuleNotFoundError:
                    st.error("Playwright가 설치되지 않아 상세 크롤링을 실행할 수 없습니다. "
                             "requirements.txt에 `playwright` 추가 후 재배포해 주세요.")
                    st.stop()

                with sync_playwright() as pw:
                    try:
                        browser = pw.chromium.launch(
                            headless=True,
                            # --single-process 는 컨테이너에서 크래시(TargetClosedError) 유발 → 사용 안 함
                            args=["--no-sandbox", "--disable-dev-shm-usage",
                                  "--disable-gpu", "--disable-software-rasterizer"],
                        )
                    except Exception as _e:
                        st.error(f"Chromium 실행 실패 — {str(_e)[:200]}")
                        st.info("Streamlit Cloud에서는 브라우저 실행이 제한될 수 있습니다. "
                                "GitHub Actions 자동 크롤링(매일 09:30)을 이용해 주세요.")
                        st.stop()
                    page = browser.new_page(user_agent=HEADERS["User-Agent"])

                    for i, (_, row) in enumerate(df_target.iterrows()):
                        url = row.get('공고링크','')
                        pid = row.get('pblancId','')
                        name = row.get('공고명','')[:25]
                        if not url or not pid: continue

                        try:
                            _time.sleep(delay_sec)
                            page.goto(url, timeout=20000, wait_until="networkidle")
                            full_text = ""
                            for sel in ['.view-content','.detail-content','#bizSumryCn',
                                        '.bbs-view-content','#content','.board-view']:
                                try:
                                    el = page.query_selector(sel)
                                    if el:
                                        t = el.inner_text()
                                        if len(t) > 200:
                                            full_text = t
                                            break
                                except Exception:
                                    continue
                            if len(full_text) < 100:
                                full_text = page.inner_text('body')

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

                            MIN_TEXT_LEN = 200
                            ok = len(full_text) >= MIN_TEXT_LEN
                            if ok:
                                # ── ③ 키워드 태그 자동 추출 ─────────────
                                # 전문에서 TARGET_KW/TYPE_KW 매칭 결과를 사전 계산
                                tag_target = [cat for cat, kws in TARGET_KW.items()
                                              if any(kw in full_text for kw in kws)]
                                tag_type   = [cat for cat, kws in TYPE_KW.items()
                                              if any(kw in full_text for kw in kws)]
                                # 지역 태그
                                bracket_m = re.search(r'\[([^\]]+)\]', name or '')
                                tag_region = bracket_m.group(1) if bracket_m else ''
                                # 업력 제한
                                age_m = re.findall(r'창업\s*(\d+)년\s*이내', full_text)
                                tag_age_limit = age_m[0] if age_m else ''
                                # 선착순 여부
                                tag_urgent = '선착순' if '선착순' in full_text else ''

                                new_records.append({
                                    'pblancId':    pid,
                                    '전문내용':    full_text[:4000],
                                    '지원금액':    amount,
                                    '선정규모':    scale,
                                    '크롤링방법':  'Playwright',
                                    '크롤링일':    today,
                                    '크롤링성공':  'Y',
                                    '태그_지원대상': ', '.join(tag_target),
                                    '태그_사업성격': ', '.join(tag_type),
                                    '태그_지역':    tag_region,
                                    '태그_업력제한': tag_age_limit,
                                    '태그_긴급':    tag_urgent,
                                })
                                success += 1
                                logs.append(f"✅ {name} ({len(full_text)}자)")
                            else:
                                new_records.append({'pblancId':pid,'전문내용':f"[진단] Playwright 렌더링 후에도 본문 {len(full_text)}자",
                                                   '지원금액':'','선정규모':'','크롤링방법':'Playwright-diag',
                                                   '크롤링일':today,'크롤링성공':'N'})
                                fail += 1
                                logs.append(f"❌ {name} (본문 {len(full_text)}자 — 렌더링 후에도 부족)")
                        except Exception as e:
                            new_records.append({'pblancId':pid,'전문내용':f"[진단] 예외: {str(e)[:100]}",'지원금액':'',
                                               '선정규모':'','크롤링방법':'Playwright','크롤링일':today,'크롤링성공':'N'})
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

                    browser.close()

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

    with tab_cm2:
        info_box("매칭 실행·검토",
            """
선정기업 × 공고 DB 교차 매칭 → 담당자 검토 → 발송 승인

**매칭 로직**
- 공고 전문(크롤링 완료 건) + API 사업개요를 통합 반영해 한 번에 매칭
- 키워드 7개 축 × 별점 판정 → 점수 높은 순 정렬 → 기업당 최대 N건 추출
- 이미 발송한 공고 / 마감 지난 공고 / 수신거부 기업 자동 제외

**검토 방법** — ○ 승인 / ✕ 제외 클릭 → 공고 원문 링크로 내용 확인 후 판단
            """,
            "★★★ 위주 먼저 검토 권장")

        tab1, tab2 = st.tabs(["▶ 매칭 실행", "🔍 검토 & 승인"])

        with tab1:
            col1, col2 = st.columns(2)
            with col1:
                max_per = st.slider("기업당 최대 추천 건수", 5, 20, 12)
            with col2:
                st.markdown("**발송 대상 그룹**")
                target_group = st.radio(
                    "발송 대상 그룹", ["선정 50개사", "예비 20개사", "전체 70개사"],
                    horizontal=True, label_visibility="collapsed", key="match_target_group"
                )

            # ── 스마트 매칭 권고 알림 ────────────────────────
            df_n_check = load_excel(drive, NOTICES_FILE)

            # 드라이브에서 마지막 매칭 정보 복원 (앱 재시작 후에도 유지)
            if 'last_match_info' not in st.session_state:
                kw_saved = load_json(drive, KEYWORDS_FILE) or {}
                if 'last_match' in kw_saved:
                    st.session_state['last_match_info'] = kw_saved['last_match']

            last_match_info = st.session_state.get('last_match_info', {})
            need_rematch    = False
            rematch_reason  = ""

            if not df_n_check.empty:
                # 공고 DB 최신 날짜
                latest_notice_date = ""
                if '수정일' in df_n_check.columns:
                    latest_notice_date = df_n_check['수정일'].max()[:10] if df_n_check['수정일'].max() else ""

                last_match_date    = last_match_info.get('date','')
                last_match_notices = last_match_info.get('notice_count', 0)
                cur_notice_count   = len(df_n_check)

                if not last_match_date:
                    need_rematch  = True
                    rematch_reason = "아직 매칭을 실행한 적이 없습니다."
                elif latest_notice_date and latest_notice_date > last_match_date:
                    new_cnt = cur_notice_count - last_match_notices
                    need_rematch  = True
                    rematch_reason = f"마지막 매칭({last_match_date}) 이후 공고 {new_cnt:+d}건 변동이 있습니다."
                else:
                    days_since = (datetime.today() - datetime.strptime(last_match_date, '%Y-%m-%d')).days
                    if days_since >= 3:
                        need_rematch  = True
                        rematch_reason = f"마지막 매칭({last_match_date})으로부터 {days_since}일 경과했습니다."

            if need_rematch:
                st.warning(f"🔄 **매칭 재실행 권장** — {rematch_reason}")
            elif last_match_info:
                st.success(f"✅ 매칭 최신 상태 — 마지막 실행: {last_match_info.get('date','')} / {last_match_info.get('result_count',0)}건")

            # 전문 수집 현황
            df_det_check = load_excel(drive, DETAIL_FILE)
            detail_ok_count = 0
            if not df_det_check.empty and '크롤링성공' in df_det_check.columns:
                detail_ok_count = (df_det_check['크롤링성공']=='Y').sum()
            if detail_ok_count > 0:
                st.success(f"📄 전문 수집 완료: {detail_ok_count}건 — 매칭에 자동 반영됩니다.")
            else:
                st.info("📄 전문 미수집 — API 사업개요만으로 매칭합니다.")

            st.checkbox(
                "지난 회차 제외(✕) 이월", value=True, key="round_keep_reject",
                help="이전 회차에서 ✕로 제외한 공고를 새 회차에서도 제외 상태로 유지합니다. "
                     "승인(○)은 이 옵션과 무관하게 매칭할 때마다 항상 초기화됩니다.")

            if st.button("🔍 매칭 실행", type="primary"):
                with st.spinner("드라이브 데이터 로딩 중..."):
                    df_c    = load_excel(drive, SELECTED_FILE)
                    df_n    = load_excel(drive, NOTICES_FILE)
                    df_h    = load_excel(drive, HISTORY_FILE)
                    df_det  = load_excel(drive, DETAIL_FILE)
                    HIGH, MID = load_keywords(drive)

                if df_n.empty: st.error("notices_db 없음 → 공고 수집 먼저"); st.stop()
                if df_c.empty: st.error("선정기업 명단 없음 → 기업 관리에서 업로드"); st.stop()

                # 발송 대상 필터
                if '선정구분' in df_c.columns:
                    if target_group == "선정 50개사":
                        df_c = df_c[df_c['선정구분'] == '선정']
                    elif target_group == "예비 20개사":
                        df_c = df_c[df_c['선정구분'] == '예비']
                else:
                    st.warning("선정기업 명단에 '선정구분' 컬럼이 없어 전체 기업으로 매칭합니다.")
                if df_c.empty:
                    st.error(f"'{target_group}' 대상 기업이 없습니다."); st.stop()
                if '수신거부' in df_c.columns: df_c = df_c[df_c['수신거부']!='Y']

                # 전문내용 enrich 맵 구성
                detail_map = {}
                if not df_det.empty and 'pblancId' in df_det.columns:
                    # 버그 수정: df.get()은 컬럼 Series를 반환 → == 'Y' 비교 시 항상 빈 결과
                    # 올바른 방식: df['컬럼'] == 'Y'
                    if '크롤링성공' in df_det.columns:
                        df_det_ok = df_det[df_det['크롤링성공'] == 'Y']
                    else:
                        df_det_ok = df_det
                    df_det_ok = df_det_ok.drop_duplicates(subset='pblancId', keep='last')
                    detail_map = df_det_ok.set_index('pblancId').to_dict('index')

                # 진단: notices_db × notices_detail 교집합 확인
                notice_pids_set = set(df_n['pblancId'].str.strip()) if 'pblancId' in df_n.columns else set()
                overlap_count = len(notice_pids_set & set(detail_map.keys()))
                st.caption(f"📄 전문 DB {len(detail_map)}건 로드 | notices_db {len(df_n)}건 | 교집합(전문 반영 가능): {overlap_count}건")

                def enrich(n_dict):
                    """공고 dict에 전문내용을 병합해 매칭 정확도를 높인다.
                    score_notice()는 '사업개요'와 '전문내용' 두 필드를 모두 읽으므로 양쪽에 반영."""
                    pid = n_dict.get('pblancId','')
                    if pid in detail_map:
                        d = detail_map[pid]
                        full = str(d.get('전문내용',''))
                        if len(full) >= 200:
                            n_dict['전문내용'] = full   # score_notice 502줄에서 직접 읽힘
                            n_dict['사업개요'] = full   # 소재지 판정(578줄)에도 전문 내용 반영
                        n_dict['지원금액'] = d.get('지원금액','')
                        n_dict['선정규모'] = d.get('선정규모','')
                    return n_dict

                already_sent = set(zip(df_h['기업명'], df_h['pblancId'])) if not df_h.empty else set()
                # 같은 사업이 '수정공고'로 다시 올라오면 ID 가 달라져 위 검사를 빠져나간다.
                # 제목에서 회차·연도·수정 표시를 걷어낸 값으로 한 번 더 막는다.
                sent_titles = (set(zip(df_h['기업명'].map(company_key),
                                       df_h['공고명'].map(notice_base_title)))
                               if not df_h.empty and '공고명' in df_h.columns else set())
                all_results  = []
                prog         = st.progress(0, text="매칭 준비 중...")
                status_area  = st.empty()
                notice_recommend_count = {}
                match_errors = []

                # 피드백 + 가중치 + 제외키워드 통합 로드
                kw_config = load_kw_config(drive)
                feedback_map = kw_config.get('feedback', {})
                if feedback_map:
                    st.caption(f"🔄 피드백 반영 중 — {len(feedback_map)}개사 패턴 로드")
                if kw_config.get('exclude_keywords'):
                    st.caption(f"🚫 제외 키워드 {len(kw_config['exclude_keywords'])}개 적용 "
                               "— 공고명에 들어간 경우만")

                total_cos = len(df_c)
                for idx, (_, row) in enumerate(df_c.iterrows()):
                    co_name = row.get('기업명', f'기업{idx+1}')
                    prog.progress((idx+1)/total_cos,
                                  text=f"매칭 중... {idx+1}/{total_cos} ({co_name[:10]})")

                    try:
                        scored = []
                        for _, n in df_n.iterrows():
                            try:
                                r = score_notice(enrich(n.to_dict()), row, already_sent,
                                                 HIGH, MID, feedback_map, kw_config,
                                                 sent_titles=sent_titles)
                                if r:
                                    scored.append(r)
                            except Exception as e_inner:
                                # 개별 공고 오류는 skip
                                pass

                        for r in scored:
                            pid = r.get('공고ID','')
                            cnt = notice_recommend_count.get(pid, 0)
                            if cnt >= 15:   r['점수'] -= 20
                            elif cnt >= 10: r['점수'] -= 15
                            elif cnt >= 7:  r['점수'] -= 10
                            elif cnt >= 4:  r['점수'] -= 6
                            elif cnt >= 2:  r['점수'] -= 3

                        scored.sort(key=lambda x: -x['점수'])

                        # 한 기업에게 비슷한 공고가 두 건 가지 않게 한다.
                        # 창조 엔지니어링은 9/29 한 통에 '지정기간 연장(2차)'와
                        # '연장(1차)'를 같이 받았다. 점수 높은 쪽만 남긴다.
                        _seen_base, _uniq = set(), []
                        for _r in scored:
                            _b = _r.get('기준제목', '')
                            if _b and _b in _seen_base:
                                continue
                            if _b:
                                _seen_base.add(_b)
                            _uniq.append(_r)
                        scored = _uniq

                        # 한 기업의 12칸을 해외 전시회가 다 먹지 않게 한다.
                        # 10/29 회차 실측: 전시회 66건이 배정됐고 3건 이상 받은 기업이
                        # 12개사, 리얼디자인테크는 12칸 중 5칸이 해외 전시회였다.
                        # 업종어 목록(FAIR_IND)에 없는 업종이 또 올라와도 피해가
                        # 여기서 멈춘다 — 목록만으로는 매 회차 새 업종을 못 따라간다.
                        _fair_n, _capped = 0, []
                        for _r in scored:
                            if is_fair_notice(_r.get('공고명', '')):
                                if _fair_n >= FAIR_MAX_PER_CO:
                                    continue
                                _fair_n += 1
                            _capped.append(_r)
                        scored = _capped

                        top = scored[:max_per]

                        for r in top:
                            pid = r.get('공고ID','')
                            notice_recommend_count[pid] = notice_recommend_count.get(pid, 0) + 1
                            r['_recommend_count'] = notice_recommend_count[pid]

                        all_results.extend(top)

                    except Exception as e_outer:
                        match_errors.append(f"{co_name}: {str(e_outer)[:60]}")
                        continue

                prog.progress(1.0, text="매칭 완료!")

                if match_errors:
                    with st.expander(f"⚠️ 처리 중 오류 {len(match_errors)}건"):
                        for err in match_errors:
                            st.caption(err)

                for r in all_results:
                    r['공고유형'] = '공통' if notice_recommend_count.get(r.get('공고ID',''), 1) >= 4 else '맞춤'

                enriched_count = len(detail_map)
                st.session_state['match_results'] = all_results
                st.session_state['df_companies_cache'] = df_c

                # ── 새 매칭 회차 시작 ──────────────────────────
                # 승인(○)은 절대 다음 회차로 넘기지 않는다. 제외(✕)만 옵션에 따라 이월.
                _carried = carry_over_reject(st.session_state.get('review_state', {}))
                st.session_state['match_round_id'] = new_round_id()
                st.session_state['review_state']   = _carried
                save_review_state(_get_drive())   # 새 회차 상태를 드라이브에도 즉시 반영
                save_match_state(_get_drive())    # 매칭 직후 자동 저장
                st.caption(
                    f"🔄 새 회차 {st.session_state['match_round_id']} 시작 — 승인 0건에서 시작합니다"
                    + (f" · 지난 회차 제외(✕) {len(_carried)}건 이월" if _carried else ""))
                # 매칭 실행 정보 저장 — session_state + 드라이브 JSON (앱 재시작 후에도 유지)
                match_info = {
                    'date':         datetime.today().strftime('%Y-%m-%d'),
                    'time':         datetime.today().strftime('%H:%M'),
                    'notice_count': len(df_n),
                    'result_count': len(all_results),
                    'target_group': target_group,
                }
                st.session_state['last_match_info'] = match_info
                # 드라이브에도 저장
                kw_data_save = load_json(drive, KEYWORDS_FILE) or {}
                kw_data_save['last_match'] = match_info
                save_json(drive, kw_data_save, KEYWORDS_FILE)
                st.success(
                    f"✅ 매칭 완료 — 총 {len(all_results)}건 "
                    f"(전문 DB {enriched_count}건 반영 / 공고 총 {df_n.shape[0]}건 중 매칭) "
                    f"→ '검토 & 승인' 탭으로 이동"
                )

                # ── ① 버려진 공고 분석 ───────────────────────
                matched_pids = {r.get('공고ID','') for r in all_results}
                all_pids     = set(df_n['pblancId'].astype(str)) if 'pblancId' in df_n.columns else set()
                dropped_pids = all_pids - matched_pids
                dropped_df   = df_n[df_n['pblancId'].astype(str).isin(dropped_pids)]

                with st.expander(f"🗑️ 버려진 공고 분석 ({len(dropped_df)}건 / 전체 {len(df_n)}건)", expanded=False):
                    if not dropped_df.empty:
                        # 분야별 분포
                        c1, c2 = st.columns(2)
                        with c1:
                            st.caption("**버려진 공고 분야 분포**")
                            if '분야' in dropped_df.columns:
                                realm_drop = dropped_df['분야'].value_counts().head(8)
                                for realm, cnt in realm_drop.items():
                                    pct = cnt / len(dropped_df) * 100
                                    st.write(f"• {realm}: {cnt}건 ({pct:.0f}%)")
                        with c2:
                            st.caption("**버려진 공고 키워드 빈도**")
                            # 버려진 공고들에서 TARGET_KW/TYPE_KW 빈도 계산
                            kw_counter = {}
                            for _, row_d in dropped_df.iterrows():
                                text_d = str(row_d.get('사업개요','')) + str(row_d.get('공고명',''))
                                for cat, kws in {**TARGET_KW, **TYPE_KW}.items():
                                    if any(kw in text_d for kw in kws):
                                        kw_counter[cat] = kw_counter.get(cat, 0) + 1
                            for cat, cnt in sorted(kw_counter.items(), key=lambda x:-x[1])[:8]:
                                st.write(f"• {cat}: {cnt}건")

                        st.divider()
                        # 역제안: 버려진 공고 중 키워드 추가 시 매칭 가능한 것
                        st.caption("**💡 키워드 추가 시 매칭 가능할 수 있는 공고 (상위 10건)**")
                        st.caption("아래 공고들은 기업 키워드가 보완되면 매칭될 수 있습니다.")
                        dropped_sample = dropped_df[dropped_df['마감일'] >= datetime.today().strftime('%Y-%m-%d')].head(10)
                        for _, row_d in dropped_sample.iterrows():
                            name_d = str(row_d.get('공고명',''))[:40]
                            dl_d   = str(row_d.get('마감일',''))
                            realm_d = str(row_d.get('분야',''))
                            st.write(f"📌 **{name_d}** | {realm_d} | 마감 {dl_d}")

                if enriched_count == 0 and detail_ok_count > 0:
                    st.error("⚠️ 전문 DB 로드 실패 — '공고 수집' 탭에서 크롤링 상태를 확인하세요.")

        with tab2:
            results = st.session_state.get('match_results', [])
            if not results:
                st.info("매칭 실행 탭에서 먼저 실행 필요")
            else:
                df_show = pd.DataFrame(results)
                if 'review_state'  not in st.session_state: st.session_state['review_state']  = {}
                if 'ai_analysis'   not in st.session_state: st.session_state['ai_analysis']   = {}
                if 'custom_deadline' not in st.session_state: st.session_state['custom_deadline'] = {}

                # ── 검토 상태 저장/불러오기 ─────────────────────
                sv1, sv2, sv3 = st.columns([2, 2, 4])
                with sv1:
                    if st.button("💾 검토 상태 저장", help="드라이브에 현재 검토 상태를 저장합니다"):
                        save_review_state(drive)
                        st.success(f"검토 상태 저장 완료 (회차 {current_round_id() or '—'})")
                with sv2:
                    if st.button("📂 검토 상태 불러오기", help="드라이브에서 이전에 저장한 검토 상태를 불러옵니다"):
                        _st_l, _rid_l, _at_l, _same_l = load_review_state(drive)
                        if not _rid_l and not _st_l:
                            st.warning("저장된 검토 상태가 없습니다")
                        else:
                            st.session_state['review_state'] = _st_l
                            if _same_l:
                                st.session_state['_review_load_msg'] = (
                                    'ok', f"불러오기 완료 ({_at_l or '날짜 미상'} 저장본)")
                            else:
                                st.session_state['_review_load_msg'] = (
                                    'warn',
                                    f"지난 회차({_rid_l or '회차 정보 없음'}) 저장본이라 승인(○)은 빼고 "
                                    f"제외(✕) {len(_st_l)}건만 불러왔습니다.")
                            st.rerun()
                with sv3:
                    saved_json = load_json(drive, REVIEW_FILE)
                    if saved_json:
                        _sr = saved_json.get('round_id', '')
                        st.caption(f"마지막 저장: {saved_json.get('saved_at','—')}"
                                   + (f" · 회차 {_sr}" if _sr else " · 회차 정보 없음(구버전)"))
                    st.caption(f"현재 회차: {current_round_id() or '— (매칭 실행 전)'}")

                if st.session_state.get('_review_load_msg'):
                    _lk, _lm = st.session_state.pop('_review_load_msg')
                    (st.success if _lk == 'ok' else st.warning)(_lm)

                st.divider()

                # ── AI 판단 기준 필터 ──────────────────────────
                ai_view_filter = st.radio(
                    "공고 보기 기준",
                    ["전체", "🟢 추천 + 🟡 검토만 (비추천 제외)", "🟢 추천만"],
                    index=1,
                    horizontal=True,
                    key="ai_view_filter_radio",
                )

                # ── 필터 ────────────────────────────────────────
                c1, c2 = st.columns(2)
                with c1: filter_stars = st.multiselect("관련도", ["★★★","★★"], default=["★★★","★★"])
                with c2: filter_co    = st.selectbox("기업", ["전체"]+sorted(df_show['기업명'].unique().tolist()))
                filtered = df_show[df_show['관련도'].isin(filter_stars)]
                if filter_co != "전체": filtered = filtered[filtered['기업명']==filter_co]

                # AI 판단 필터 적용
                ai_map_f = st.session_state.get('ai_analysis', {})

                # AI 필터 결과를 미리 계산해서 컬럼으로 저장 (rerun 속도 개선)
                def get_ai_rec(r):
                    return ai_map_f.get(f"{r['기업명']}_{r.get('공고ID','')}", {}).get('추천여부','')

                if '___ai_rec' not in filtered.columns:
                    filtered = filtered.copy()
                    filtered['___ai_rec'] = filtered.apply(get_ai_rec, axis=1)

                if "추천 + 🟡 검토만" in ai_view_filter:
                    filtered = filtered[filtered['___ai_rec'].isin(['추천','검토',''])]
                    st.info(f"비추천 제외 → {len(filtered)}건 표시 중")
                elif "추천만" in ai_view_filter:
                    filtered = filtered[filtered['___ai_rec'] == '추천']
                    st.info(f"AI 추천 {len(filtered)}건만 표시 중")

                # ── 공고 하나를 여러 기업에 한 번에 ─────────────
                # 같은 공고가 수십 개사에 걸리는 일이 매 회차 생긴다.
                # 기업을 하나씩 넘기며 누르면 공고 하나에 수십 번이다.
                with st.expander("📌 공고 하나를 여러 기업에 한 번에 처리", expanded=False):
                    st.caption("같은 공고가 여러 기업에 걸렸을 때, 기업을 넘기지 않고 "
                               "공고 단위로 승인하거나 제외합니다. 지금 화면 필터가 걸러낸 범위 안에서만 처리합니다.")

                    _rv_now = st.session_state.get('review_state', {})
                    _ai_tn = st.session_state.get('ai_analysis', {}) or {}

                    def _dec_of(_r):
                        return _rv_now.get(f"{_r['기업명']}_{_r.get('공고ID','')}", '')

                    _by_nt = (filtered.assign(_결정=filtered.apply(_dec_of, axis=1))
                              .groupby('공고명')
                              .agg(기업수=('기업명', 'nunique'),
                                   미결정=('_결정', lambda v: int((v == '').sum())),
                                   평균점수=('점수', 'mean'))
                              .reset_index())
                    _by_nt = _by_nt[_by_nt['미결정'] > 0].sort_values(
                        ['미결정', '평균점수'], ascending=[False, False])

                    if _by_nt.empty:
                        st.success("아직 정하지 않은 공고가 없습니다.")
                    else:
                        # 업력 요건이 걸린 공고를 미리 찾아 둔다 — 목록에 ⚠ 를 붙이고
                        # 승인 직전에 요건을 다시 보여주기 위해.
                        _tenure = {}
                        for _nt in _by_nt['공고명']:
                            _rows_nt = filtered[filtered['공고명'] == _nt].to_dict('records')
                            _note = notice_tenure_note(_rows_nt, _ai_tn)
                            if _note:
                                _tenure[_nt] = _note
                        _opts = [
                            ("⚠ " if r['공고명'] in _tenure else "")
                            + f"{int(r['미결정'])}개사 · 평균 {r['평균점수']:.0f}점 — {r['공고명']}"
                            for _, r in _by_nt.iterrows()
                        ]
                        if _tenure:
                            st.caption(f"⚠ 표시 {len(_tenure)}건 — 업력·설립연수 요건이 걸린 공고입니다.")
                        _pick = st.multiselect(
                            "공고 고르기 (미결정 건이 많은 순)", _opts, key="bulk_notice_pick",
                            help="여러 개를 함께 고르셔도 됩니다.")
                        _names = [_opts.index(x) for x in _pick]
                        _sel_nt = set(_by_nt.iloc[_names]['공고명']) if _names else set()

                        _target = filtered[filtered['공고명'].isin(_sel_nt)].copy()
                        _target = _target[_target.apply(lambda r: _dec_of(r) == '', axis=1)]

                        if len(_target):
                            st.info(f"고르신 공고 {len(_sel_nt)}건 → 아직 정하지 않은 "
                                    f"**{len(_target)}건 / {_target['기업명'].nunique()}개사**가 처리됩니다.")
                            # 업력 요건이 걸린 공고를 고르셨으면 승인 버튼 앞에서 한 번 세운다.
                            _warn = [(_nt, _tenure[_nt]) for _nt in _sel_nt if _nt in _tenure]
                            if _warn:
                                st.warning(
                                    f"**업력·설립연수 요건이 있는 공고 {len(_warn)}건이 들어 있습니다**\n\n"
                                    + "\n".join(f"- {_nt} — **설립·업력 {_rq}**만 신청 가능"
                                                for _nt, _rq in _warn)
                                    + "\n\n선정기업 명단에 설립연도가 없어 앱이 자격을 "
                                      "가려내지 못합니다. 해당되는 기업만 골라 승인하시고, "
                                      "확실하지 않으면 그냥 두십시오.")
                            _bn1, _bn2 = st.columns(2)
                            with _bn1:
                                if st.button(f"✅ {len(_target)}건 승인", type="primary",
                                             key="bulk_notice_ok", use_container_width=True):
                                    for _, _r in _target.iterrows():
                                        set_decision(f"{_r['기업명']}_{_r.get('공고ID','')}",
                                                     "○", '담당자')
                                    st.session_state['bulk_notice_msg'] = (
                                        f"✅ {len(_target)}건 승인했습니다. "
                                        f"'검토 완료 저장'을 눌러야 드라이브에 남습니다.")
                                    st.rerun()
                            with _bn2:
                                if st.button(f"❌ {len(_target)}건 제외",
                                             key="bulk_notice_no", use_container_width=True):
                                    for _, _r in _target.iterrows():
                                        set_decision(f"{_r['기업명']}_{_r.get('공고ID','')}",
                                                     "✕", '담당자')
                                    st.session_state['bulk_notice_msg'] = (
                                        f"❌ {len(_target)}건 제외했습니다. "
                                        f"'검토 완료 저장'을 눌러야 드라이브에 남습니다.")
                                    st.rerun()
                        elif _sel_nt:
                            st.success("고르신 공고는 이미 다 정해져 있습니다.")

                    if st.session_state.get('bulk_notice_msg'):
                        st.warning(st.session_state.pop('bulk_notice_msg'))

                # ── 0건 기업 자동 보완 승인 ──────────────────
                with st.expander("🟡 0건 기업 자동 보완 승인 (검토 상위)", expanded=False):
                    st.caption("승인이 0건인 기업에 한해 — AI '검토' 판정 중 타지역·자격미달(X)·이미 제외(✕)한 공고를 빼고 "
                               "규칙점수 상위 공고를 자동 승인합니다. 추천/비추천 판정은 건드리지 않습니다.")
                    if st.session_state.get('auto_fill_msg'):
                        st.success(st.session_state.pop('auto_fill_msg'))
                    _n_auto = st.number_input("기업당 승인 건수", 1, 3, 1, key="auto_fill_n")
                    if st.button("🟡 자동 보완 실행", key="auto_fill_go", use_container_width=True):
                        from collections import defaultdict as _dd
                        _mrs2 = st.session_state.get('match_results', [])
                        # 드라이브 AI 캐시 병합 — 재시작 직후 세션이 비어 있어도 동작
                        _ai2 = load_json(drive, AI_ANALYSIS_FILE) or {}
                        _ai2.update(st.session_state.get('ai_analysis', {}))
                        st.session_state['ai_analysis'] = _ai2
                        # 드라이브 승인 상태 병합 — 기존 승인을 덮어쓰지 않도록.
                        # 단 지난 회차 저장본이면 승인(○)은 버리고 제외(✕)만 가져온다.
                        try:
                            _rv_saved, _, _, _ = load_review_state(drive)
                        except Exception:
                            _rv_saved = {}
                        _rv2 = dict(_rv_saved); _rv2.update(st.session_state.get('review_state', {}))
                        st.session_state['review_state'] = _rv2
                        if not _mrs2:
                            st.error("매칭 결과가 세션에 없습니다 — 매칭 실행·검토 화면을 먼저 열어 매칭 상태를 불러온 뒤 다시 눌러주세요.")
                            st.stop()
                        if not any(isinstance(v, dict) and v.get('추천여부') == '검토' for v in _ai2.values()):
                            st.error("AI 분석 캐시에 '검토' 판정이 없습니다 — ⚡ 일괄 분석이 완료된 상태인지 확인해 주세요.")
                            st.stop()
                        _by_co = _dd(list)
                        for _r2 in _mrs2:
                            _by_co[_r2.get('기업명', '')].append(_r2)
                        _f_co = 0; _f_cnt = 0; _no_cand = []
                        for _co2, _rows2 in _by_co.items():
                            if any(_rv2.get(f"{_co2}_{_r2.get('공고ID','')}") == "○"
                                   and can_include_notice(_r2, _co2, _ai2, _rv2)[0]
                                   for _r2 in _rows2):
                                continue   # 메일에 실릴 수 있는 승인 공고를 이미 보유
                            _cands2 = []
                            for _r2 in _rows2:
                                _k2 = f"{_co2}_{_r2.get('공고ID','')}"
                                # 메일 수록 자격(✕ · 자격 미충족 · 마감 경과)은 관문에서 한 번에
                                if not can_include_notice(_r2, _co2, _ai2, _rv2)[0]:
                                    continue
                                if _ai2.get(_k2, {}).get('추천여부') != '검토':
                                    continue   # '검토' 등급만 보완 대상 (자동 보완 고유 규칙)
                                try:
                                    if float(_r2.get('소재지점수', 0) or 0) < 0:
                                        continue
                                except Exception:
                                    pass
                                _cands2.append((_r2, _k2))
                            _cands2.sort(key=lambda x: -float(x[0].get('점수', 0) or 0))
                            if not _cands2:
                                _no_cand.append(_co2); continue
                            for _r2, _k2 in _cands2[:int(_n_auto)]:
                                _rv2[_k2] = "○"; _f_cnt += 1
                                st.session_state.setdefault('decision_src', {})[_k2] = '🟡 자동 보완'
                            _f_co += 1
                        save_review_state(drive, _rv2)
                        _msg = f"자동 보완 완료: {_f_co}개사 / {_f_cnt}건 승인 · 드라이브 저장됨"
                        if _no_cand:
                            _msg += f" · 후보 없음 {len(_no_cand)}개사({', '.join(_no_cand[:4])}…)"
                        st.session_state['auto_fill_msg'] = _msg
                        st.rerun()

                # 이번 회차 매칭 결과에 있는 공고만 집계
                # (이월된 ✕ 중 이번 회차에 매칭되지 않은 건은 세지 않는다)
                _rv_now   = st.session_state['review_state']
                _keys_now = {f"{r['기업명']}_{r.get('공고ID','')}" for _, r in df_show.iterrows()}
                ap      = sum(1 for k in _keys_now if _rv_now.get(k) == "○")
                rj      = sum(1 for k in _keys_now if _rv_now.get(k) == "✕")
                total   = len(df_show)
                pending = max(0, total - ap - rj)

                # ── 상단 진행 현황 ──────────────────────────────
                # '전체'는 맥락일 뿐이라 캡션으로 내리고, 사람이 오래 머무는 화면이니
                # "얼마나 남았나"를 진행률 바로 먼저 보여준다.
                _done = ap + rj
                st.progress(_done / max(total, 1),
                            text=f"검토 {_done:,}/{total:,}건  ({_done/max(total,1)*100:.0f}%)"
                                 + (f" · 남은 {pending:,}건" if pending else " · 완료"))
                c2, c3, c4, c5 = st.columns([2, 2, 2, 3])
                c2.metric("✅ 승인", f"{ap:,}건")
                c3.metric("❌ 제외", f"{rj:,}건")
                c4.metric("⏳ 미검토", f"{pending:,}건")
                with c5:
                    if ap > 0:
                        if st.button(
                            f"📨 승인 {ap}건 발송 준비 →",
                            type="primary",
                            use_container_width=True,
                            help="검토 완료 저장 후 발송 탭으로 이동합니다."
                        ):
                            # 검토 상태 드라이브 저장 (현재 회차로)
                            save_review_state(drive)
                            st.session_state['_go_to_send'] = True
                            st.rerun()
                    else:
                        st.button("📨 발송 준비", disabled=True,
                                  use_container_width=True,
                                  help="승인된 공고가 없습니다.")

                # 발송 탭 이동 처리
                if st.session_state.pop('_go_to_send', False):
                    st.success(f"✅ 검토 상태 저장 완료 — 사이드바에서 '발송' 탭으로 이동하세요.")

                st.divider()

                # ── ⚡ 전 기업 일괄 처리 ────────────────────────────
                with st.expander("⚡ 전 기업 일괄 AI 분석 + 자동 처리", expanded=False):
                    st.caption("50개사 전체를 한 번에 분석 → AI 추천 자동 승인 → AI 비추천 자동 제외 → 검토 등급만 남깁니다.")

                    bulk_c1, bulk_c2 = st.columns(2)
                    with bulk_c1:
                        auto_approve = st.checkbox("추천 자동 승인", value=True, key="bulk_auto_approve")
                        auto_reject  = st.checkbox("비추천 자동 제외", value=True, key="bulk_auto_reject")
                        skip_region  = st.checkbox("타지역 공고 AI 생략 (자동 비추천)", value=True, key="bulk_skip_region",
                                                   help="공고지역이 기업 소재지와 안 맞는 공고는 API 호출 없이 규칙으로 비추천 처리 — 비용·시간 절감")
                        run_limit    = st.number_input("이번 실행 신규 분석 한도", min_value=50, max_value=600,
                                                       value=150, step=50, key="bulk_run_limit",
                                                       help="한 번에 다 돌리다 끊기면 유실됩니다. 150건씩 나눠 실행하고, 끝나면 같은 버튼을 다시 누르세요 — 완료분은 캐시로 건너뜁니다.")
                    with bulk_c2:
                        # ⚡ 일괄 실행은 필터와 무관하게 df_show 전체를 돈다.
                        # 예전에는 필터된 건수만 보여줘 실행 시 나오는 숫자와 어긋났다.
                        _ai_cache_now = st.session_state.get('ai_analysis', {})
                        _done_all = sum(1 for _, r in df_show.iterrows()
                                        if f"{r['기업명']}_{r.get('공고ID','')}" in _ai_cache_now)
                        _done_view = sum(1 for _, r in filtered.iterrows()
                                         if f"{r['기업명']}_{r.get('공고ID','')}" in _ai_cache_now)
                        st.metric("분석 완료", f"{_done_all:,}/{len(df_show):,}건",
                                  help="⚡ 일괄 실행이 실제로 도는 범위입니다 (화면 필터와 무관).")
                        st.caption(f"화면 표시분 {_done_view:,}/{len(filtered):,}건")

                    # ── 버전이 달라진 판정 — 표시만 하고 자동 실행하지 않는다 ──
                    _ai_now = st.session_state.get('ai_analysis', {})
                    _co_cache = get_companies_df()
                    _stale_ver = []
                    if _co_cache is not None and not _co_cache.empty:
                        _co_map = {r['기업명']: r.to_dict() for _, r in _co_cache.iterrows()}
                        for _, _r in filtered.iterrows():
                            _k = f"{_r['기업명']}_{_r.get('공고ID','')}"
                            _res = _ai_now.get(_k)
                            if _res and ai_version_stale(_res, _co_map.get(_r['기업명'], {}),
                                                         enrich_for_ai(_r.to_dict())):
                                _stale_ver.append(_k)
                    if _stale_ver:
                        st.warning(f"🔁 버전 변경 {len(_stale_ver)}건 — 기업 프로필이나 공고 전문, "
                                   f"프롬프트가 바뀐 뒤의 판정입니다. 자동으로 다시 돌리지 않으니 "
                                   f"필요하면 아래 버튼으로 캐시를 지우고 ⚡ 실행하세요.")

                    rq_col1, rq_col2 = st.columns([2, 2])
                    with rq_col1:
                        _rq_clicked = st.button(
                            "🔁 '검토' 판정 재분석 준비 (전문 반영)",
                            key="requeue_review_ai", use_container_width=True,
                            help="요약만 보고 '검토'로 미뤄진 판정을 지웁니다. "
                                 "지운 뒤 ⚡ 실행을 누르면 공고 전문을 반영해 다시 분석합니다.")
                    with rq_col2:
                        if st.button(f"🔁 버전 변경 {len(_stale_ver)}건 재분석 준비",
                                     key="requeue_stale_ver", use_container_width=True,
                                     disabled=not _stale_ver):
                            _drv_sv = _get_drive()
                            _m_sv = load_json(_drv_sv, AI_ANALYSIS_FILE) or {}
                            _m_sv.update(st.session_state.get('ai_analysis', {}))
                            for _k in _stale_ver:
                                _m_sv.pop(_k, None)
                            st.session_state['ai_analysis'] = _m_sv
                            save_ai_analysis(_drv_sv)
                            st.success(f"버전 변경 {len(_stale_ver)}건 캐시 삭제 — "
                                       f"⚡ 전 기업 일괄 실행 시 다시 분석됩니다.")
                    if _rq_clicked:
                        _drv_rq = _get_drive()
                        # 드라이브 캐시 + 세션 캐시 병합 후 대상 산출 (재부팅 직후에도 동작)
                        _merged_rq = load_json(_drv_rq, AI_ANALYSIS_FILE) or {}
                        _merged_rq.update(st.session_state.get('ai_analysis', {}))
                        _stale_review = [k for k, v in _merged_rq.items()
                                         if isinstance(v, dict) and v.get('추천여부') == '검토'
                                         and not v.get('_지역컷') and not v.get('_전문반영')]
                        if not _stale_review:
                            st.info("재분석 대상이 없습니다 — '검토' 판정이 모두 전문 반영본이거나 캐시가 비어 있습니다.")
                        else:
                            for _k in _stale_review:
                                _merged_rq.pop(_k, None)
                            st.session_state['ai_analysis'] = _merged_rq
                            save_ai_analysis(_drv_rq)
                            st.success(f"'검토' {len(_stale_review)}건 캐시 삭제 완료 — 아래 ⚡ 전 기업 일괄 실행을 누르면 전문 반영으로 재분석됩니다.")

                    btn_col1, btn_col2 = st.columns(2)
                    with btn_col1:
                        if st.button("⚡ 전 기업 일괄 실행", type="primary", key="global_bulk_ai", use_container_width=True):
                            _drive = _get_drive()
                            prog_g = st.progress(0, text="캐시 확인 중...")

                            # 전문 DB 상태 점검 — AI에 전문이 실제로 들어가는지 가시화
                            _dm_chk = get_detail_map_cached()
                            _dm_err = st.session_state.get('_detail_map_ai_err', '')
                            _pid_col = df_show['공고ID'].astype(str).str.strip() if '공고ID' in df_show.columns else pd.Series([], dtype=str)
                            _hit_chk = int(_pid_col.isin(set(_dm_chk.keys())).sum())
                            # 예전에는 1건만 겹쳐도 통과시켜, 전문 없는 공고가 요약만으로
                            # 판정되는 걸 막지 못했다. 보유율 기준으로 바꾼다.
                            _cov = _hit_chk / max(len(df_show), 1)
                            if _dm_err or _cov < FULLTEXT_MIN_COVERAGE:
                                _why = _dm_err or (
                                    f"현재 매칭 {len(df_show)}건 중 전문 보유가 {_hit_chk}건"
                                    f"({_cov*100:.0f}%)뿐 — 기준 {FULLTEXT_MIN_COVERAGE*100:.0f}% 미달")
                                st.error(f"⛔ 분석 중단: {_why}\n\n"
                                         f"요약(300자)만으로 분석하면 '검토' 판정이 과다 발생해 비용만 낭비됩니다. "
                                         f"공고 전문 크롤링을 먼저 돌린 뒤 다시 실행하세요. "
                                         f"(부득이하게 강행하려면 아래 체크 후 재실행)")
                                if not st.session_state.get('force_no_fulltext', False):
                                    st.checkbox("⚠️ 전문 없이 강행 (권장 안 함)", key="force_no_fulltext")
                                    st.stop()
                            else:
                                st.caption(f"📄 AI용 전문 DB {len(_dm_chk)}건 로드 · 현재 매칭 {len(df_show)}건 중 "
                                           f"전문 반영 가능 {_hit_chk}건 ({_cov*100:.0f}%)")

                            # 드라이브 캐시 먼저 로드 → 세션에 병합
                            cached = load_json(_drive, AI_ANALYSIS_FILE) or {}
                            if 'ai_analysis' not in st.session_state:
                                st.session_state['ai_analysis'] = {}
                            st.session_state['ai_analysis'].update(cached)

                            all_rows = df_show
                            total_g  = len(all_rows)

                            if total_g == 0:
                                st.warning("매칭 결과가 없습니다. 먼저 매칭을 실행하세요.")
                            else:
                                ok_g = 0; ap_g = 0; rj_g = 0; skip_g = 0; cut_g = 0; fail_g = 0; enr_g = 0
                                prog_g.progress(0, text=f"0/{total_g} 처리 중...")

                                for gi, (_, gr) in enumerate(all_rows.iterrows()):
                                    gkey = f"{gr['기업명']}_{gr.get('공고ID','')}"

                                    _prev_g = st.session_state['ai_analysis'].get(gkey)
                                    if not _prev_g or _prev_g.get('error'):
                                        # 지역 컷: 타지역 한정 공고는 API 호출 없이 규칙 판정
                                        try:    _loc_g = float(gr.get('소재지점수', 0) or 0)
                                        except Exception: _loc_g = 0
                                        if skip_region and _loc_g <= -5:
                                            st.session_state['ai_analysis'][gkey] = _region_cut_result(gr)
                                            cut_g += 1
                                        else:
                                            ci = company_profile(gr['기업명'])
                                            _nd_g = enrich_for_ai(gr.to_dict())
                                            if len(str(_nd_g.get('전문내용','') or '')) >= 200:
                                                enr_g += 1
                                            _res_g = claude_analyze(ci, _nd_g)
                                            if _res_g.get('error'):
                                                fail_g += 1   # 오류는 캐시하지 않음 → 다음 실행 때 자동 재시도
                                            else:
                                                st.session_state['ai_analysis'][gkey] = _res_g
                                                ok_g += 1
                                                if ok_g % 25 == 0:
                                                    save_ai_analysis(_drive)   # 25건마다 중간 저장 — 끊겨도 유실 없음
                                            import time as _t_g; _t_g.sleep(0.5)   # 레이트리밋 완화 간격
                                    else:
                                        skip_g += 1

                                    if ok_g >= run_limit:
                                        save_ai_analysis(_drive)
                                        st.info(f"이번 실행 한도 {run_limit}건 도달 — 저장 완료. 같은 버튼을 다시 누르면 이어서 진행합니다.")
                                        break

                                    rec_g = st.session_state['ai_analysis'].get(gkey, {}).get('추천여부', '')
                                    if auto_approve and rec_g == '추천':
                                        set_decision(gkey, '○', 'AI 자동 승인'); ap_g += 1
                                    elif auto_reject and rec_g == '비추천':
                                        set_decision(gkey, '✕', 'AI 자동 제외'); rj_g += 1

                                    prog_g.progress(
                                        (gi+1)/total_g,
                                        text=f"{gi+1}/{total_g} 처리 중... (신규 {ok_g} / 지역컷 {cut_g} / 캐시 {skip_g} / 실패 {fail_g})"
                                    )

                                if ok_g > 0 or cut_g > 0:
                                    save_ai_analysis(_drive)
                                # 자동승인·자동제외는 set_decision 으로 review_state 에
                                # 들어가는데, 여기서 save_ai_analysis 만 부르고 있었다.
                                # 그래서 결정이 화면에만 남고 드라이브에 올라가지 않았다 —
                                # 10/27 회차에서 승인 26건이 다음 접속 때 미검토로 돌아갔고,
                                # 「어제는 다 보낼 수 있었는데 왜 또 적어졌냐」가 이것이었다.
                                if ap_g or rj_g:
                                    save_match_state(_drive)
                                prog_g.progress(1.0, text="✅ 완료!")
                                st.session_state['bulk_result'] = (
                                    f"신규분석 {ok_g}건(전문반영 {enr_g}건) / 지역컷 {cut_g}건 / 캐시재사용 {skip_g}건 / 자동승인 {ap_g}건 / 자동제외 {rj_g}건"
                                    + (f" / ⚠️ 실패 {fail_g}건 — 같은 버튼으로 다시 실행하면 실패분만 재시도됩니다" if fail_g else ""))
                                st.rerun()

                # 완료 메시지 (rerun 후)
                if 'bulk_result' in st.session_state:
                    st.success(f"✅ 일괄 처리 완료 — {st.session_state.pop('bulk_result')}")

                    with btn_col2:
                        ai_done_count = sum(
                            1 for _, r in df_show.iterrows()
                            if st.session_state.get('ai_analysis', {}).get(
                                f"{r['기업명']}_{r.get('공고ID','')}", {}
                            ).get('추천여부') == '추천'
                            and st.session_state.get('review_state', {}).get(
                                f"{r['기업명']}_{r.get('공고ID','')}", '') != '○'
                        )
                        if st.button(
                            f"✅ AI 분석 완료 공고 일괄 승인 ({ai_done_count}건)",
                            key="bulk_approve_analyzed",
                            use_container_width=True,
                            disabled=ai_done_count == 0
                        ):
                            for _, r in df_show.iterrows():
                                gkey = f"{r['기업명']}_{r.get('공고ID','')}"
                                rec  = st.session_state.get('ai_analysis', {}).get(gkey, {}).get('추천여부','')
                                if rec == '추천':
                                    set_decision(gkey, '○', 'AI 자동 승인')
                            save_match_state(_get_drive())  # 일괄 승인 후 자동 저장
                            st.success(f"✅ AI 추천 공고 일괄 승인 완료")
                            st.rerun()

                    # 검토 등급만 보기 토글
                    show_review_only = st.checkbox(
                        "🟡 검토 등급 공고만 보기 (추천·비추천 제외)",
                        key="show_review_only",
                        help="AI가 '검토'로 판단한 공고와 미분석 공고만 표시합니다."
                    )

                st.divider()

                # ══════════════════════════════════════════════
                # 기업별 검토 (단일 모드)
                # ══════════════════════════════════════════════
                if True:

                    companies_in_result = filtered['기업명'].unique().tolist()

                    def co_pending_count(co):
                        return sum(1 for _, r in filtered[filtered['기업명']==co].iterrows()
                                   if st.session_state['review_state'].get(
                                       f"{r['기업명']}_{r.get('공고ID','')}", "") == "")

                    co_labels = [
                        f"{'✅' if co_pending_count(co)==0 else '⏳'} {co}  ({co_pending_count(co)}건 미검토)"
                        for co in companies_in_result
                    ]
                    co_map = dict(zip(co_labels, companies_in_result))

                    # 기업명 자체를 session_state에 저장 (레이블 재생성 시 인덱스 틀어짐 방지)
                    if 'review_co_name' not in st.session_state or \
                       st.session_state['review_co_name'] not in companies_in_result:
                        st.session_state['review_co_name'] = companies_in_result[0]
                    cur_name    = st.session_state['review_co_name']
                    current_idx = companies_in_result.index(cur_name)

                    nav1, nav2, nav3, nav4 = st.columns([1, 5, 1, 2])
                    with nav1:
                        prev_clicked = st.button("◀ 이전", disabled=current_idx==0, key="btn_prev_co")
                    with nav2:
                        # 드롭다운 선택 (표시용) — index를 current_idx로 고정
                        # on_change 없이 매 rerun마다 index로 위치를 강제 지정
                        chosen = st.selectbox(
                            "기업 선택", co_labels,
                            index=current_idx,
                            label_visibility="collapsed",
                            key=f"co_select_{cur_name}"   # 기업명이 바뀌면 key도 바뀌어 위젯 초기화
                        )
                        # 드롭다운으로 직접 선택한 경우
                        chosen_name = co_map.get(chosen, cur_name)
                        if chosen_name != cur_name:
                            st.session_state['review_co_name'] = chosen_name
                            st.rerun()
                    with nav3:
                        next_clicked = st.button("다음 ▶", disabled=current_idx==len(co_labels)-1, key="btn_next_co")
                    with nav4:
                        st.caption(f"{current_idx+1} / {len(co_labels)}개사")

                    if prev_clicked:
                        st.session_state['review_co_name'] = companies_in_result[current_idx - 1]
                        st.rerun()
                    if next_clicked:
                        st.session_state['review_co_name'] = companies_in_result[current_idx + 1]
                        st.rerun()

                    selected_co = st.session_state['review_co_name']
                    co_rows = filtered[filtered['기업명'] == selected_co].copy()
                    co_rows['점수_num'] = pd.to_numeric(co_rows['점수'], errors='coerce').fillna(0)
                    # AI 적합도 순 우선 정렬 (추천→검토→비추천→미분석), 동점 시 점수 순
                    ai_map = st.session_state.get('ai_analysis', {})
                    def ai_order(r):
                        k   = f"{r['기업명']}_{r.get('공고ID','')}"
                        rec = ai_map.get(k, {}).get('추천여부', '')
                        return {"추천": 0, "검토": 1, "비추천": 2}.get(rec, 3)
                    co_rows['_ai_order'] = co_rows.apply(ai_order, axis=1)
                    co_rows = co_rows.sort_values(['_ai_order', '점수_num'], ascending=[True, False])

                    co_ap  = sum(1 for _, r in co_rows.iterrows() if st.session_state['review_state'].get(f"{r['기업명']}_{r.get('공고ID','')}", "")=="○")
                    co_rj  = sum(1 for _, r in co_rows.iterrows() if st.session_state['review_state'].get(f"{r['기업명']}_{r.get('공고ID','')}", "")=="✕")
                    co_pen = len(co_rows) - co_ap - co_rj

                    # ── 기업 정보 패널 ──────────────────────────
                    st.divider()
                    with st.expander(f"🏢 {selected_co} 기업 정보", expanded=True):
                        co_info_panel = company_profile(selected_co)

                        # 상단 핵심 지표
                        pi1, pi2, pi3, pi4 = st.columns(4)
                        pi1.metric("공고 현황", f"전체 {len(co_rows)}건",
                                   f"✅{co_ap} / ❌{co_rj} / ⏳{co_pen}")
                        pi2.metric("소재지", co_info_panel.get('소재지','—'))
                        biz_type = co_info_panel.get('기업유형','—')
                        pi3.metric("기업유형", biz_type[:16] + ('...' if len(str(biz_type))>16 else '') if biz_type else '—')
                        pi4.metric("TRL / 매출", f"TRL {co_info_panel.get('TRL단계','—')} / {co_info_panel.get('매출규모','—')[:6]}" if co_info_panel.get('매출규모') else f"TRL {co_info_panel.get('TRL단계','—')}")

                        st.divider()

                        # 매칭 관련 정보
                        ic1, ic2 = st.columns(2)
                        with ic1:
                            st.markdown("**관심사업분야**")
                            st.write(co_info_panel.get('관심사업분야','—'))
                            st.markdown("**기술키워드**")
                            st.write(co_info_panel.get('기술키워드','—'))
                            st.markdown("**핵심수요태그**")
                            st.write(co_info_panel.get('핵심수요태그','—'))
                            if co_info_panel.get('키워드보완'):
                                st.markdown("**보완키워드** ✏️")
                                st.write(co_info_panel.get('키워드보완',''))
                        with ic2:
                            st.markdown("**제품분야**")
                            st.write(co_info_panel.get('제품분야','—'))
                            st.markdown("**수출실적 / 수출국가**")
                            st.write(f"{co_info_panel.get('수출실적','—')} / {co_info_panel.get('수출국가','—')}")
                            st.markdown("**이메일**")
                            st.write(co_info_panel.get('이메일','—'))

                        # 주관식 답변 (있는 경우만 표시)
                        has_subjective = any([
                            co_info_panel.get('희망서비스요약',''),
                            co_info_panel.get('평가_서비스요청',''),
                            co_info_panel.get('평가_내부논의',''),
                            co_info_panel.get('메모',''),
                        ])
                        if has_subjective:
                            st.divider()
                            if co_info_panel.get('희망서비스요약',''):
                                st.markdown("**📝 희망 서비스** (신청 시 작성)")
                                st.info(co_info_panel.get('희망서비스요약',''))
                            if co_info_panel.get('평가_서비스요청',''):
                                st.markdown("**📝 서비스 요청** (평가 시 작성)")
                                st.info(co_info_panel.get('평가_서비스요청',''))
                            if co_info_panel.get('평가_내부논의',''):
                                st.markdown("**📋 평가 내부 의견**")
                                st.warning(co_info_panel.get('평가_내부논의',''))
                            if co_info_panel.get('메모',''):
                                st.markdown("**🗒 운영 메모**")
                                st.write(co_info_panel.get('메모',''))

                    # ── AI 추천 필터 (상단 배치) ────────────────
                    ai_analysis_map = st.session_state.get('ai_analysis', {})
                    ai_rec_n = sum(1 for _, r in co_rows.iterrows()
                                   if ai_analysis_map.get(f"{r['기업명']}_{r.get('공고ID','')}", {}).get('추천여부') == '추천')
                    ai_rev_n = sum(1 for _, r in co_rows.iterrows()
                                   if ai_analysis_map.get(f"{r['기업명']}_{r.get('공고ID','')}", {}).get('추천여부') == '검토')
                    ai_bad_n = sum(1 for _, r in co_rows.iterrows()
                                   if ai_analysis_map.get(f"{r['기업명']}_{r.get('공고ID','')}", {}).get('추천여부') == '비추천')

                    tog_c1, tog_c2 = st.columns([2, 4])
                    with tog_c1:
                        ai_only = st.toggle(
                            "🟢 AI 추천 공고만 보기",
                            key="toggle_ai_only",
                            help="AI가 추천한 공고만 표시합니다. 꺼두면 전체 확인 가능합니다."
                        )
                    with tog_c2:
                        st.markdown(
                            f"<div style='padding:8px 0;font-size:13px;'>"                            f"🟢 추천 <b>{ai_rec_n}</b>건 &nbsp;&nbsp;"                            f"🟡 검토 <b>{ai_rev_n}</b>건 &nbsp;&nbsp;"                            f"🔴 비추천 <b>{ai_bad_n}</b>건"                            f"</div>",
                            unsafe_allow_html=True
                        )

                    # AI 필터 적용
                    display_rows = co_rows.copy()
                    show_review_only = st.session_state.get('show_review_only', False)
                    if show_review_only:
                        # 검토 등급 + 미분석만
                        display_rows = co_rows[[
                            ai_analysis_map.get(
                                f"{r['기업명']}_{r.get('공고ID','')}", {}
                            ).get('추천여부', '') in ['검토', '']
                            for _, r in co_rows.iterrows()
                        ]]
                        if len(display_rows) == 0:
                            st.success("✅ 검토가 필요한 공고가 없습니다.")
                    elif ai_only:
                        display_rows = co_rows[[
                            ai_analysis_map.get(f"{r['기업명']}_{r.get('공고ID','')}", {}).get('추천여부') == '추천'
                            for _, r in co_rows.iterrows()
                        ]]
                        if len(display_rows) > 0:
                            if st.button(f"✅ AI 추천 {len(display_rows)}건 일괄 승인",
                                         type="primary", key="bulk_ai_approve"):
                                for _, r in display_rows.iterrows():
                                    set_decision(f"{r['기업명']}_{r.get('공고ID','')}",
                                                 "○", 'AI 자동 승인')
                                st.rerun()
                        else:
                            st.info("AI 추천 공고가 없습니다.")

                    # ── AI 비추천 일괄 제외 (정밀도 보정) ──────────
                    ai_bad_rows = co_rows[[
                        ai_analysis_map.get(f"{r['기업명']}_{r.get('공고ID','')}", {}).get('추천여부') == '비추천'
                        for _, r in co_rows.iterrows()
                    ]]
                    if len(ai_bad_rows) > 0:
                        if st.button(f"🔴 AI 비추천 {len(ai_bad_rows)}건 일괄 제외",
                                     key="bulk_ai_reject"):
                            for _, r in ai_bad_rows.iterrows():
                                set_decision(f"{r['기업명']}_{r.get('공고ID','')}",
                                             "✕", 'AI 자동 제외')
                            st.rerun()

                    st.divider()

                    # ── 일괄 처리 버튼 (기업별) ─────────────────────
                    ba1, ba2 = st.columns([1, 3])
                    with ba1:
                        co_ai_done  = sum(1 for _, r in co_rows.iterrows()
                                          if f"{r['기업명']}_{r.get('공고ID','')}"
                                          in st.session_state.get('ai_analysis', {}))
                        co_ai_total = len(co_rows)
                        if co_ai_done < co_ai_total:
                            if st.button(f"🤖 AI 분석 ({co_ai_done}/{co_ai_total})",
                                         key="co_bulk_ai", use_container_width=True):
                                prog_co_ai = st.progress(0, text="AI 분석 중...")
                                for ai_i, (_, ai_row) in enumerate(co_rows.iterrows()):
                                    ai_key = f"{ai_row['기업명']}_{ai_row.get('공고ID','')}"
                                    if 'ai_analysis' not in st.session_state:
                                        st.session_state['ai_analysis'] = {}
                                    _prev_c = st.session_state['ai_analysis'].get(ai_key)
                                    if not _prev_c or _prev_c.get('error'):
                                        try:    _loc_c = float(ai_row.get('소재지점수', 0) or 0)
                                        except Exception: _loc_c = 0
                                        if st.session_state.get('bulk_skip_region', True) and _loc_c <= -5:
                                            st.session_state['ai_analysis'][ai_key] = _region_cut_result(ai_row)
                                        else:
                                            ci = company_profile(ai_row['기업명'])
                                            _res_c = claude_analyze(ci, enrich_for_ai(ai_row.to_dict()))
                                            if not _res_c.get('error'):
                                                st.session_state['ai_analysis'][ai_key] = _res_c
                                    prog_co_ai.progress((ai_i+1)/co_ai_total,
                                                        text=f"AI 분석 중... {ai_i+1}/{co_ai_total}")
                                save_ai_analysis(_get_drive())
                                st.success(f"✅ {selected_co} 분석 완료"); st.rerun()
                        else:
                            st.success(f"✅ 분석 완료 ({co_ai_total}건)")
                    with ba2:
                        st.caption("전 기업 일괄 처리는 위 ⚡ 버튼을 사용하세요.")

                    st.divider()

                    # ── 공고 목록 (카드 형태) ───────────────────
                    for i, (idx, row) in enumerate(display_rows.iterrows()):
                        key     = f"{row['기업명']}_{row.get('공고ID','')}"
                        current = st.session_state['review_state'].get(key, "")
                        ai_res  = st.session_state.get('ai_analysis', {}).get(key)

                        try: loc_v = int(str(row.get('소재지점수','0')))
                        except: loc_v = 0
                        loc_txt  = "🟢 지역일치" if loc_v > 0 else ("🔴 타지역" if loc_v < 0 else "🔵 전국")
                        dl       = row.get('마감일','')
                        dl_txt   = "⚠️ 비정형" if not dl or not dl.strip() else dl
                        star     = row.get('관련도','')
                        nm       = row.get('공고명','')
                        org      = row.get('주관기관','')
                        reason   = row.get('매칭근거','')

                        # D-day 계산
                        d_day_txt = ""
                        days_left = None
                        if dl and dl.strip():
                            try:
                                days_left = (datetime.strptime(dl, '%Y-%m-%d') - datetime.today()).days
                                if days_left < 0:
                                    d_day_txt = f"마감 {abs(days_left)}일 전"
                                    d_color   = "#94A3B8"
                                elif days_left == 0:
                                    d_day_txt = "D-0 ⚠️"
                                    d_color   = "#EF4444"
                                else:
                                    d_day_txt = f"D-{days_left}"
                                    d_color   = "#EF4444" if days_left <= 3 else "#F59E0B" if days_left <= 7 else "#10B981"
                            except: d_day_txt = dl; d_color = "#94A3B8"
                        else:
                            d_day_txt = "상시"; d_color = "#94A3B8"

                        # D-0 이하 공고는 경고 표시 (스킵하지 않고 담당자가 판단)
                        is_deadline_warn = days_left is not None and days_left <= 0

                        # 상태 색상
                        status_color = {"○": "#ECFDF5", "✕": "#FEF2F2"}.get(current, "#F8FAFC")
                        status_border = {"○": "#10B981", "✕": "#EF4444"}.get(current, "#E2E8F0")
                        status_icon  = {"○": "✅ 승인됨", "✕": "❌ 제외됨"}.get(current, "⏳ 미검토")

                        # AI 배지
                        ai_badge = ""
                        if ai_res and not ai_res.get('error'):
                            rec = ai_res.get('추천여부','')
                            ai_badge = {"추천":"🟢 AI추천","검토":"🟡 AI검토","비추천":"🔴 AI비추천"}.get(rec,"")

                        # D-0 경고 배너
                        if is_deadline_warn:
                            st.markdown(
                                f"<div style='background:#FEF2F2;border:1px solid #FECACA;border-radius:6px;"
                                f"padding:6px 12px;margin-bottom:6px;font-size:12px;color:#991B1B !important;'>"
                                f"⚠️ 마감일이 지났거나 오늘까지입니다 — 발송 전 신청 가능 여부를 확인하세요.</div>",
                                unsafe_allow_html=True
                            )

                        # ── 카드 상단: 별점 + 공고명 + 상태 ──
                        top_c1, top_c2 = st.columns([8, 2])
                        with top_c1:
                            star_color = {"★★★":"#F59E0B","★★":"#10B981"}.get(star,"#94A3B8")
                            badges = f"<span style='font-size:13px;font-weight:700;color:{star_color};'>{star}</span>"
                            if ai_badge:
                                ai_col = {"🟢 AI추천":"#10B981","🟡 AI검토":"#F59E0B","🔴 AI비추천":"#EF4444"}.get(ai_badge,"#94A3B8")
                                badges += f" &nbsp;<span style='font-size:11px;background:{ai_col}22;color:{ai_col};padding:2px 7px;border-radius:10px;font-weight:600;'>{ai_badge}</span>"
                            st.markdown(
                                f"{badges}<br>"
                                f"<span style='font-size:15px;font-weight:700;color:#F0F0F0;'>{nm}</span>"
                                f"<span style='font-size:12px;color:#A8BDD1;font-weight:400;'> ({int(row.get('점수', 0))}점)</span><br>"
                                f"<span style='font-size:12px;color:#888888;'>{org}</span>",
                                unsafe_allow_html=True
                            )
                        with top_c2:
                            st.markdown(
                                f"<div style='text-align:right;'>"
                                f"<span style='font-size:14px;font-weight:700;color:{d_color};'>{d_day_txt}</span><br>"
                                f"<span style='font-size:11px;color:#666666;'>{dl_txt}</span><br>"
                                f"<span style='font-size:11px;color:#666666;'>{loc_txt}</span>"
                                f"</div>",
                                unsafe_allow_html=True
                            )

                        # ── 매칭근거 (전체 표시) + AI 요약 ──
                        if reason:
                            # 매칭근거를 태그별로 파싱해서 보기 좋게 표시
                            parts = [p.strip() for p in reason.split('+') if p.strip()]
                            tags_html = " ".join([
                                f"<span style='display:inline-block;background:#1E3048;color:#A8BDD1;"
                                f"border:1px solid #BFDBFE;border-radius:12px;padding:1px 8px;"
                                f"font-size:11px;margin:2px 2px;'>{p}</span>"
                                for p in parts
                            ])
                            st.markdown(
                                f"<div style='padding:4px 0;line-height:2;'>{tags_html}</div>",
                                unsafe_allow_html=True
                            )
                        if ai_res and not ai_res.get('error'):
                            summary = ai_res.get('한줄요약','')
                            if summary:
                                st.markdown(
                                    f"<div style='font-size:12px;color:#CCCCCC;padding:3px 0;"
                                    f"border-left:3px solid #10B981;padding-left:8px;margin:4px 0;'>"
                                    f"{summary}</div>",
                                    unsafe_allow_html=True
                                )
                            checks = {
                                "업종일치": ai_res.get('업종일치','—'),
                                "자격충족": ai_res.get('자격충족','—'),
                                "지역적합": ai_res.get('지역적합','—'),
                                "수요일치": ai_res.get('수요일치','—')
                            }
                            icon_map = {"O":"✅","X":"❌","△":"⚠️"}
                            o_count = sum(1 for v in checks.values() if v == "O")
                            checks_html = " &nbsp; ".join([
                                f"<span style='font-size:12px;'>{icon_map.get(v,'—')} {k}</span>"
                                for k, v in checks.items()
                            ])
                            if o_count >= 3:
                                checks_html += ""
                            st.markdown(
                                f"<div style='padding:4px 0;'>{checks_html}</div>",
                                unsafe_allow_html=True
                            )

                        # ── 핵심 정보 요약 ──
                        info_parts = []
                        if row.get('지원대상','') and row.get('지원대상','') != '—':
                            info_parts.append(f"<b>지원대상</b> {str(row.get('지원대상',''))[:40]}")
                        if row.get('지원금액','') and str(row.get('지원금액','')) not in ['','nan']:
                            info_parts.append(f"<b>지원금액</b> {str(row.get('지원금액',''))[:30]}")
                        if row.get('접수기간','') and str(row.get('접수기간','')) not in ['','nan']:
                            info_parts.append(f"<b>접수기간</b> {str(row.get('접수기간',''))[:30]}")
                        if info_parts:
                            st.markdown(
                                "<div style='background:#151515;border-radius:6px;padding:8px 12px;"
                                "margin:6px 0;font-size:12px;color:#CCCCCC;line-height:1.8;'>"
                                + "<br>".join(info_parts) +
                                "</div>",
                                unsafe_allow_html=True
                            )

                        # ── 액션 버튼 행 ──
                        b1, b2, b3, b4 = st.columns([2, 2, 2, 2])
                        with b1:
                            lbl = "✅ 승인" if current != "○" else "↩ 승인취소"
                            btn_type = "primary" if current != "○" else "secondary"
                            # 이 루프의 공고는 row 다(r 은 위쪽 컴프리헨션 변수여서
                            # 블록을 안 거치면 아예 없다 — 그래서 NameError 가 났다).
                            _inc_ok, _inc_why = can_include_notice(
                                row, row.get('기업명', ''),
                                st.session_state.get('ai_analysis', {}))
                            if not _inc_ok and _inc_why != '담당자 제외(✕)':
                                st.caption(f"⚠ 승인하셔도 메일에 실리지 않습니다 — {_inc_why}")
                            if st.button(lbl, key=f"o_{key}_{i}", use_container_width=True, type=btn_type):
                                set_decision(key, "" if current=="○" else "○", '담당자')
                                # rerun 대신 상태만 변경 → 전체 재렌더링 없이 버튼 상태만 반영
                                st.rerun()
                        with b2:
                            lbl = "❌ 제외" if current != "✕" else "↩ 제외취소"
                            if st.button(lbl, key=f"x_{key}_{i}", use_container_width=True):
                                set_decision(key, "" if current=="✕" else "✕", '담당자')
                                st.rerun()
                        with b3:
                            if row.get('공고링크',''):
                                st.link_button("🔗 공고 원문", row.get('공고링크',''),
                                               use_container_width=True)
                        with b4:
                            if not ai_res or ai_res.get('error'):
                                _ai_btn_lbl = "🔁 재분석" if (ai_res and ai_res.get('error')) else "🤖 AI 분석"
                                if st.button(_ai_btn_lbl, key=f"ai_{key}_{i}", use_container_width=True):
                                    with st.spinner("분석 중..."):
                                        ci = company_profile(row['기업명'])
                                        if 'ai_analysis' not in st.session_state:
                                            st.session_state['ai_analysis'] = {}
                                        st.session_state['ai_analysis'][key] = claude_analyze(ci, enrich_for_ai(row.to_dict()))
                                    st.rerun()

                        # ── AI 분석 상세 ──
                        # 예전에는 항상 펼쳐져 있어 카드 하나가 화면을 거의 채웠다.
                        # 12~16건을 훑어야 하므로 한 줄 요약만 노출하고 접어 둔다.
                        if ai_res and not ai_res.get('error'):
                            rec       = ai_res.get('추천여부','')
                            fit       = ai_res.get('적합도','')
                            reason_ai = ai_res.get('판단근거', ai_res.get('적합이유',''))
                            caution   = ai_res.get('주의사항','')
                            rec_icon  = {"추천":"🟢","검토":"🟡","비추천":"🔴"}.get(rec,"⚪")
                            # 다크 배경 + 밝은 글자 (전역 CSS와 조화 — 밝은배경 싸움 회피)
                            rec_bg_map  = {"추천":"#0F2E1F","검토":"#2E2410","비추천":"#2E1515"}
                            rec_bdr_map = {"추천":"#10B981","검토":"#F59E0B","비추천":"#EF4444"}
                            rec_txt_map = {"추천":"#6EE7B7","검토":"#FCD34D","비추천":"#FCA5A5"}
                            bg    = rec_bg_map.get(rec, "#1A1A1A")
                            bdr   = rec_bdr_map.get(rec, "#333333")
                            txt   = rec_txt_map.get(rec, "#CCCCCC")

                            import html as _html_ai
                            _reason_esc = _html_ai.escape(str(reason_ai or ''))
                            _caution_esc = _html_ai.escape(str(caution or ''))
                            _caution_html = ""
                            if caution and caution not in ['없음','','nan']:
                                _caution_html = (
                                    f"<div style='margin-top:8px;padding:8px 12px;"
                                    f"background:rgba(245,158,11,0.12);border:1px solid {bdr};border-radius:6px;"
                                    f"font-size:12px;color:#FCD34D !important;font-weight:500;'>⚠️ {_caution_esc}</div>"
                                )
                            _ai_sum = (
                                f"{rec_icon} {rec} · 적합도 {fit or '—'} · "
                                f"업종 {ai_res.get('업종일치','—')} · 자격 {ai_res.get('자격충족','—')} · "
                                f"지역 {ai_res.get('지역적합','—')} · 수요 {ai_res.get('수요일치','—')}"
                                + ("  ⚠️ 확인사항" if _caution_html else ""))
                            with st.expander(_ai_sum, expanded=False):
                                st.markdown(
                                    f"<div style='background:{bg};border:1px solid {bdr};"
                                    f"border-left:4px solid {bdr};border-radius:8px;"
                                    f"padding:14px 16px;margin:6px 0;'>"
                                    f"<div style='font-size:13px;line-height:1.6;color:#E8EFF6 !important;'>{_reason_esc}</div>"
                                    f"{_caution_html}"
                                    f"</div>",
                                    unsafe_allow_html=True
                                )

                        st.divider()

                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("✅ 검토 완료 저장", type="primary"):
                        for r in results:
                            r['담당자검토'] = st.session_state['review_state'].get(
                                f"{r['기업명']}_{r.get('공고ID','')}", "")
                        st.session_state['match_results'] = results
                        save_match_state(_get_drive())
                        record_decision_log(_get_drive())   # 판단 기록 갱신 (실패해도 흐름 유지)
                        st.success(f"저장 완료 — 승인 {ap}건 → '발송 관리' 메뉴로 이동")
                with c2:
                    if st.button("📥 매칭결과 엑셀 저장"):
                        fname = f"매칭결과_{datetime.today().strftime('%Y%m%d')}.xlsx"
                        ai_data = st.session_state.get('ai_analysis', {})
                        export_rows = []
                        for r in results:
                            r2  = dict(r)
                            key = f"{r2.get('기업명','')}_{r2.get('공고ID','')}"
                            ai  = ai_data.get(key, {})
                            if ai and not ai.get('error'):
                                r2['AI_추천여부'] = ai.get('추천여부','')
                                r2['AI_적합도']   = ai.get('적합도','')
                                r2['AI_한줄요약'] = ai.get('한줄요약','')
                                r2['AI_판단근거'] = ai.get('판단근거', ai.get('적합이유',''))
                                r2['AI_주의사항'] = ai.get('주의사항','')
                                r2['AI_업종일치'] = ai.get('업종일치','')
                                r2['AI_자격충족'] = ai.get('자격충족','')
                                r2['AI_지역적합'] = ai.get('지역적합','')
                                r2['AI_수요일치'] = ai.get('수요일치','')
                            export_rows.append(r2)
                        with st.spinner("드라이브 저장 중..."):
                            save_excel(drive, pd.DataFrame(export_rows), fname,
                                       "매칭결과", "C55A11", star_col="관련도")
                        ai_cnt = sum(1 for r in export_rows if r.get('AI_추천여부',''))
                        st.success(f"✅ {fname} 저장 완료 — AI 분석 {ai_cnt}건 포함")
                with c3:
                    with st.expander("🔄 피드백 반영 (매칭 개선)"):
                        st.caption("""제외한 공고 패턴을 분석해 다음 매칭에 자동 반영합니다.
    기업별로 자주 제외된 사업성격을 낮은 우선순위로 설정합니다.""")
                        if st.button("피드백 적용", key="apply_feedback"):
                            # 제외된 공고의 사업성격 패턴 집계
                            rejected = [r for r in results
                                        if st.session_state['review_state'].get(
                                            f"{r['기업명']}_{r.get('공고ID','')}", "") == "✕"]

                            # 기업별 제외 패턴
                            co_reject_types = {}
                            for r in rejected:
                                co  = r.get('기업명','')
                                typ = r.get('사업성격매칭','')
                                if co and typ:
                                    if co not in co_reject_types:
                                        co_reject_types[co] = []
                                    for t in typ.split('/'):
                                        t = t.strip().split('(')[0].strip()
                                        if t: co_reject_types[co].append(t)

                            # keywords.json에 제외 패턴 저장
                            kw_data = load_json(drive, KEYWORDS_FILE) or {}
                            feedback = kw_data.get('feedback', {})
                            for co, types in co_reject_types.items():
                                if co not in feedback:
                                    feedback[co] = {}
                                for t in types:
                                    feedback[co][t] = feedback[co].get(t, 0) + 1
                            kw_data['feedback'] = feedback

                            if save_json(drive, kw_data, KEYWORDS_FILE):
                                summary_lines = [f"{co}: {dict(v)}" for co, v in list(co_reject_types.items())[:5]]
                                st.success(f"피드백 반영 완료 — {len(rejected)}건 제외 패턴 저장")
                                for line in summary_lines:
                                    st.caption(line)
                            else:
                                st.error("저장 실패")


# ══════════════════════════════════════════════════════
# 발송 관리
# ══════════════════════════════════════════════════════
elif page == "발송":
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

    # ── 🧪 메일 테스트 (매칭 불필요) ─────────────────────
    # 발송이 끝나면 match_results 가 비워져, 메일 모양을 한 번 보려 해도 수집·매칭·
    # AI 분석을 다시 돌려야 했다. 마지막 회차 스냅샷으로 비용 0으로 재현한다.
    with st.expander("🧪 메일 테스트 — 매칭 없이 지난 회차로 확인", expanded=False):
        _snap = load_round_snapshot(drive)
        if not _snap.get('match_results'):
            st.caption("아직 저장된 회차 스냅샷이 없습니다. 다음 발송이 끝나면 자동으로 생깁니다.")
        else:
            st.caption(f"스냅샷 회차 {_snap.get('round_id','?')} · 저장 {_snap.get('saved_at','?')}"
                       f" · 매칭 {len(_snap.get('match_results',[])):,}건")
            _bk = snapshot_buckets(_snap)
            _labels = [f"{_lb} ({len(_cos)}개사)" for _lb, _cos in _bk.items() if _cos]
            _by_label = {f"{_lb} ({len(_cos)}개사)": _cos
                         for _lb, _cos in _bk.items() if _cos}
            if not _labels:
                st.caption("스냅샷에 기업이 없습니다.")
            else:
                _pick = st.radio("승인 공고 수로 본 메일 유형", _labels,
                                 key="snap_pick", horizontal=True)
                # 유형 안에서 기업을 고를 수 있게 한다. 같은 유형이라도 참고 공고가
                # 채워지는지 여부로 메일 모양이 갈려서, 첫 기업만 보면 놓치는 경우가 있다.
                _co_t = st.selectbox("기업", _by_label[_pick], key="snap_co")
                _df_ct = get_companies_df()
                _row_t = {}
                if not _df_ct.empty and '기업명' in _df_ct.columns:
                    _mt = _df_ct[_df_ct['기업명'] == _co_t]
                    if not _mt.empty:
                        _row_t = _mt.iloc[0].to_dict()
                # 실제 발송은 승인(○) 공고만 build_match_mail 에 넘긴다(grouped = approved).
                # 여기서도 똑같이 걸러야 테스트 메일이 실제 메일과 같아진다.
                _rv_t = _snap.get('review_state', {}) or {}
                _notices_t = [r for r in _snap['match_results']
                              if str(r.get('기업명', '')).strip() == _co_t
                              and _rv_t.get(f"{_co_t}_{r.get('공고ID','')}", '') == '○']
                _html_t, _meta_t = build_match_mail(
                    _co_t, _notices_t, _row_t,
                    _snap.get('ai_analysis', {}) or {},
                    _snap.get('ref_notices', {}) or {},
                    _snap.get('review_state', {}) or {})
                if _html_t is None:
                    st.warning(f"{_co_t} — 실을 공고가 없어 실제 발송에서도 건너뛰는 기업입니다.")
                else:
                    st.caption(f"제목: {mail_subject(_co_t, _meta_t)}")
                    _t1, _t2 = st.columns(2)
                    if _t1.button("👁 미리보기", key="snap_prev", use_container_width=True):
                        st.session_state['_snap_html'] = _html_t
                    if _t2.button("📤 테스트 발송", key="snap_send", use_container_width=True,
                                  help="사이드바 테스트 수신자에게만 보냅니다"):
                        try:
                            _nt = send_test_mail(get_test_recipients(), _co_t, _html_t, _meta_t)
                            st.success(f"테스트 발송 {_nt}통 — {', '.join(get_test_recipients())}")
                        except Exception as _e_t:
                            st.error(f"발송 실패: {str(_e_t)[:160]}")
                    if st.session_state.get('_snap_html'):
                        st.components.v1.html(st.session_state.pop('_snap_html'),
                                              height=1200, scrolling=True)

    results  = st.session_state.get('match_results', [])

    # review_state 없으면 드라이브에서 불러오기 (현재 회차 것만)
    if 'review_state' not in st.session_state or not st.session_state['review_state']:
        _st_r, _rid_r, _, _same_r = load_review_state(drive)
        if _st_r or _rid_r:
            st.session_state['review_state'] = _st_r
            if not _same_r:
                st.warning(
                    f"드라이브 검토 상태가 지난 회차({_rid_r or '회차 정보 없음'}) 저장본이라 "
                    f"승인(○)은 불러오지 않았습니다. '검토 & 승인' 화면에서 다시 승인해 주세요.")

    review_state = st.session_state.get('review_state', {})

    # match_results와 review_state 동기화
    # ai_analysis 없으면 드라이브에서 로드
    if 'ai_analysis' not in st.session_state or not st.session_state['ai_analysis']:
        _cached = load_json(drive, AI_ANALYSIS_FILE) or {}
        st.session_state['ai_analysis'] = _cached

    ai_cache = st.session_state.get('ai_analysis', {})

    # ── 메일 수록 자격 검사 (발송 시점 기준) ──────────────
    # 마감 경과·담당자 제외(✕)·자격 미충족을 can_include_notice() 한 곳에서 판정한다.
    # 승인 공고와 참고 공고 후보가 모두 이 관문을 지난 뒤에만 아래로 내려간다.
    _today_str = datetime.today().strftime('%Y-%m-%d')
    _cut_reason = {}
    _results_live = []
    _results_lax  = []          # 빈손 폴백용 — 접수기간 불명도 담되 소진형은 뺀다
    for r in results:
        _ok_r, _why_r = can_include_notice(r, r.get('기업명',''), ai_cache, review_state)
        if _ok_r:
            _results_live.append(r); _results_lax.append(r)
        else:
            _cut_reason[_why_r] = _cut_reason.get(_why_r, 0) + 1
            if _why_r == '접수기간 불명' and can_include_notice(
                    r, r.get('기업명',''), ai_cache, review_state,
                    allow_undated=True)[0]:
                _results_lax.append(r)
    _n_expired = len(results) - len(_results_live)

    approved = [
        r for r in _results_live
        if review_state.get(f"{r.get('기업명','')}_{r.get('공고ID','')}", '') == '○'
    ]

    # 참고 공고: 승인 0건 기업용 — AI가 '검토'로 판정한 것 중 점수 높은 순.
    # _results_live가 이미 관문을 통과했으므로 ✕·자격 미충족·마감 공고는 들어올 수 없다.
    # 참고 공고 풀은 폴백 후보까지 담는다. build_match_mail 의 정상 경로는
    # 엄격한 관문으로 다시 거르므로, 접수기간 불명 건은 빈손일 때만 쓰인다.
    _ref_by_co = {}
    for r in _results_lax:
        _rec = ai_cache.get(f"{r.get('기업명','')}_{r.get('공고ID','')}", {}).get('추천여부','')
        if _rec == '검토':
            _ref_by_co.setdefault(r.get('기업명',''), []).append(r)
    for _co in _ref_by_co:
        _ref_by_co[_co] = sorted(_ref_by_co[_co],
                                 key=lambda x: x.get('점수', 0), reverse=True)[:3]
    st.session_state['_ref_notices_by_co'] = _ref_by_co
    # 매칭 실행 탭을 안 열었거나 앱이 재시작되면 위젯 키가 비어 '미확인'이 떴다.
    # keywords.json 의 last_match 에 실제 값이 있으므로 세션 → 세션 캐시 → 드라이브 순으로 찾는다.
    matched_group = (
        st.session_state.get('match_target_group')
        or st.session_state.get('last_match_info', {}).get('target_group')
        or ((load_json(drive, KEYWORDS_FILE) or {}).get('last_match', {}) or {}).get('target_group')
        or '미확인')

    if not approved:
        st.warning("승인된 공고 없음 — '매칭 결과'에서 검토 완료 후 진행")
    else:
        # 배너가 연달아 세 개면 정작 중요한 '발송 모드'가 묻힌다.
        # 맥락 정보(대상 그룹·자동 제외)는 캡션과 접힘으로 내리고 경고는 모드에만 쓴다.
        st.caption(f"📌 매칭 대상 그룹 **{matched_group}** · 기준일 {_today_str}"
                   "  —  다른 그룹으로 보내려면 '공고·매칭'에서 그룹을 바꿔 재매칭하세요.")
        if _n_expired:
            _cut_detail = " · ".join(f"{_k} {_v:,}건" for _k, _v in
                                     sorted(_cut_reason.items(), key=lambda x: -x[1]))
            with st.expander(f"⏰ 발송 대상에서 자동 제외 {_n_expired:,}건", expanded=False):
                st.markdown(f"**{_cut_detail}**")
                st.caption("담당자 제외(✕)는 검토 화면에서, 접수기간 불명·마감 경과는 "
                           "공고 데이터에서 비롯됩니다.")
        # 전체 기업 목록 로드 (선정 기업만)
        _df_c_top = load_excel(drive, SELECTED_FILE)
        if not _df_c_top.empty and '기업명' in _df_c_top.columns:
            if '선정구분' in _df_c_top.columns:
                _df_c_top = _df_c_top[_df_c_top['선정구분'] == '선정']
            _names = _df_c_top['기업명'].dropna().astype(str)
            _names = _names[_names.str.strip() != '']
            companies = list(dict.fromkeys(_names.tolist()))
        else:
            companies = list(set(r['기업명'] for r in approved))
        c1,c2,c3  = st.columns(3)
        c1.metric("승인 건수", f"{len(approved):,}건")
        c2.metric("대상 기업", f"{len(companies):,}개사")
        c3.metric("발송 모드", "테스트" if test_mode else "실제 발송",
                  help="사이드바의 '테스트 모드' 토글로 바꿉니다.")
        if test_mode:
            st.warning("⚠️ 테스트 모드 — 본인 메일로만 발송됩니다")
            _tc1, _tc2 = st.columns([1, 2])
            with _tc1:
                _test_limit = st.number_input(
                    "테스트 발송 기업 수", min_value=1, max_value=50, value=4,
                    key="match_test_limit",
                    help="전체 대신 지정한 개수만 발송합니다 (0건 기업 포함해 다양하게 추출)")
            with _tc2:
                _test_pick = st.radio(
                    "추출 방식",
                    ["유형별 샘플", "공고 많은 순", "무작위"],
                    horizontal=True, key="match_test_pick",
                    help="유형별 샘플: 공고 많음/1건/0건 등 서로 다른 케이스를 섞어 추출")
        else:
            st.success("✅ 실제 모드 — 기업 담당자 이메일로 발송")
            _test_limit, _test_pick = 0, ""

        # 0건 기업 표시
        approved_cos = set(r['기업명'] for r in approved)
        zero_cos = [co for co in companies if co not in approved_cos]
        if zero_cos:
            with st.expander(f"⚠️ 맞춤 공고 0건 기업 {len(zero_cos)}개사 (📢 섹션으로만 발송)"):
                for co in zero_cos:
                    st.write(f"• {co}")

        # ── 발송 직전 점검 ──────────────────────────
        # 조용히 지나가던 것들을 여기서 잡는다.
        st.divider()
        st.subheader("보내기 전 점검")
        try:
            _chk = presend_checks(approved, df_h, _df_c_top, test_mode)
            _blocked = render_presend_checks(_chk)
        except Exception as _ce:
            _blocked = False
            st.warning("점검을 돌리지 못했습니다 — " + str(_ce)[:120] + "  "
                       "점검 없이도 발송은 됩니다. 담당자에게 알려 주십시오.")
        st.session_state['_presend_blocked'] = _blocked

        st.divider()
        st.subheader("발송 미리보기")
        st.caption("실제 발송과 같은 함수(build_match_mail)로 만든 HTML입니다. 발송되지 않습니다.")

        _pv_c1, _pv_c2 = st.columns([3, 1])
        with _pv_c1:
            preview_co = st.selectbox("기업 선택", sorted(companies),
                                      key="send_preview_co_sel")
        with _pv_c2:
            st.write("")
            if st.button("👁 발송 경로로 확인", use_container_width=True,
                         key="send_preview_btn",
                         help="같은 HTML을 실제 발송 루프를 그대로 통과시켜 렌더합니다. "
                              "기업 묶기·건너뛰기까지 확인할 때 쓰세요. 발송은 안 됩니다."):
                st.session_state['_send_preview_co'] = preview_co

        _co_info = company_profile(preview_co)

        _preview_html, _prev_meta = build_match_mail(
            preview_co,
            [r for r in approved if r['기업명'] == preview_co],
            _co_info,
            st.session_state.get('ai_analysis', {}),
            st.session_state.get('_ref_notices_by_co', {}),
            st.session_state.get('review_state', {}))

        if _preview_html is None:
            st.warning(f"{preview_co} — 안내할 공고가 없어 실제 발송에서도 제외됩니다.")
        else:
            _pv_fb = any(x.get('_undated_fallback') for x in _prev_meta['review'])
            st.caption(f"🔦 주목 {len(_prev_meta['sss']):,}건 · "
                       f"📌 이런 공고도 {len(_prev_meta['ss']):,}건 · "
                       f"📎 참고 {len(_prev_meta['review']):,}건"
                       + ("  ·  ⚠️ 접수기간 미명시 공고로 채운 메일" if _pv_fb else ""))
            st.components.v1.html(_preview_html, height=900, scrolling=True)

        st.divider()

        _blk = st.session_state.get('_presend_blocked', False)
        if _blk:
            st.error("⛔ 점검에서 걸린 것이 있어 발송 버튼을 잠갔습니다. "
                     "위 '보내기 전 점검'을 먼저 확인해 주십시오.")
        if st.button("📤 발송 실행", type="primary", disabled=_blk)                 or st.session_state.get('_send_preview_co'):
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.header import Header
            from email.utils import formataddr
            import base64

            cal_id        = load_text(drive, CALID_FILE)
            ind_cals      = load_json(drive, INDCAL_FILE)
            df_c_cur      = load_excel(drive, SELECTED_FILE)

            history_records = []; prog = st.progress(0); log = st.empty(); logs = []

            # 승인 공고 기준으로 grouped 구성
            grouped = {}
            for r in approved:
                grouped.setdefault(r['기업명'],[]).append(r)

            # 0건 기업도 발송 대상에 추가 (참고 공고로 채움)
            if '선정구분' in df_c_cur.columns:
                all_companies = df_c_cur[df_c_cur['선정구분']=='선정']['기업명'].dropna().tolist()
            else:
                all_companies = df_c_cur['기업명'].dropna().tolist()
            for co in all_companies:
                if co not in grouped:
                    grouped[co] = []  # 승인 공고 없음 → 빈 리스트로 추가

            # ── 발송 화면 미리보기 모드: 선택 기업만 ──────
            _pv_only = st.session_state.get('_send_preview_co')
            if _pv_only:
                grouped = {k: v for k, v in grouped.items() if k == _pv_only}
                if not grouped:
                    st.warning(f"{_pv_only} — 매칭 데이터가 없어 미리보기를 만들 수 없습니다.")
                    st.session_state.pop('_send_preview_co', None)
                    st.stop()

            # ── 발송 진행 기록 — 중단 후 재실행 시 중복 발송 방지 ──
            # 테스트 모드와 👁 미리보기는 실제 이력을 남기지 않으므로 건드리지 않는다.
            _record_history = (not test_mode) and (not _pv_only)
            _send_rid = send_round_id()
            _sprog    = {'round_id': _send_rid, 'sent': {}, 'pending': []}
            if _record_history:
                _sprog = load_send_progress(drive, _send_rid)
                # 지난 실행이 중간에 멈춰 엑셀에 못 들어간 기록부터 복구
                _ok_f, _n_f = flush_send_history(drive, _sprog)
                if not _ok_f:
                    st.error("⛔ 이전 발송의 미기록분을 send_history.xlsx에 저장하지 못했습니다.\n\n"
                             "드라이브 연결을 확인한 뒤 다시 실행하세요. (이번에는 발송하지 않았습니다)")
                    st.stop()
                if _n_f:
                    save_send_progress(drive, _sprog)
                    st.info(f"🔁 이전 발송의 미기록분 {_n_f}건을 발송 이력에 반영했습니다.")
                _already_co = [c for c in grouped if c in _sprog['sent']]
                if _already_co:
                    grouped = {k: v for k, v in grouped.items() if k not in _sprog['sent']}
                    st.info(f"⏭️ 이번 회차({_send_rid})에 이미 발송된 {len(_already_co)}개사 건너뜀 — "
                            + ", ".join(_already_co[:8])
                            + (" 외" if len(_already_co) > 8 else ""))
                if not grouped:
                    st.success(f"이번 회차({_send_rid})는 대상 {len(_already_co)}개사가 모두 발송 완료된 상태입니다.")
                    st.stop()

            # ── 테스트 모드: 지정 개수만 추출 ──────────────
            if test_mode and _test_limit and _test_limit < len(grouped):
                _items = list(grouped.items())
                if _test_pick == "공고 많은 순":
                    _items.sort(key=lambda x: len(x[1]), reverse=True)
                    _picked = _items[:_test_limit]
                elif _test_pick == "무작위":
                    import random as _rnd
                    _picked = _rnd.sample(_items, _test_limit)
                else:  # 유형별 샘플 — 서로 다른 케이스가 섞이도록
                    _many = sorted([x for x in _items if len(x[1]) >= 3],
                                   key=lambda x: len(x[1]), reverse=True)
                    _few  = [x for x in _items if 1 <= len(x[1]) <= 2]
                    _zero = [x for x in _items if len(x[1]) == 0]
                    _picked, _seen = [], set()
                    for _bucket in (_many, _few, _zero):   # 각 유형에서 번갈아 뽑기
                        for _it in _bucket:
                            if len(_picked) >= _test_limit: break
                            if _it[0] not in _seen:
                                _picked.append(_it); _seen.add(_it[0])
                            break  # 버킷당 1개씩 → 라운드로빈
                    _pool = _many + _few + _zero          # 남는 자리는 순서대로 채움
                    for _it in _pool:
                        if len(_picked) >= _test_limit: break
                        if _it[0] not in _seen:
                            _picked.append(_it); _seen.add(_it[0])
                grouped = dict(_picked)
                st.info(f"테스트 추출: {len(grouped)}개사 — "
                        + ", ".join(f"{c}({len(n)}건)" for c, n in grouped.items()))

            _empty_skipped = []
            for idx,(company,notices) in enumerate(grouped.items()):
                # 기업 정보 조회
                co_row = {}
                if not df_c_cur.empty:
                    _mx = df_c_cur[df_c_cur['기업명'] == company]
                    if not _mx.empty:
                        co_row = _mx.iloc[0].to_dict()

                html, _mail_meta = build_match_mail(
                    company, notices, co_row,
                    st.session_state.get('ai_analysis', {}),
                    st.session_state.get('_ref_notices_by_co', {}),
                    st.session_state.get('review_state', {}))
                today_str = datetime.today().strftime('%Y.%m.%d')

                # ── 빈 메일 방지: 안내할 카드가 하나도 없으면 발송 스킵 ──
                if html is None:
                    if st.session_state.get('_send_preview_co'):
                        st.warning(f"{company} — 마감 경과 등으로 안내할 공고가 없어, 실제 발송에서는 이 기업을 건너뜁니다.")
                        st.session_state.pop('_send_preview_co', None)
                        st.stop()
                    _empty_skipped.append(company)
                    continue

                co_email=""; cc_list=[]; _optout=False
                if not df_c_cur.empty and '이메일' in df_c_cur.columns:
                    m = df_c_cur[df_c_cur['기업명']==company]
                    if not m.empty:
                        _r0 = m.iloc[0]
                        co_email = str(_r0.get('이메일','') or '').strip()
                        _optout = str(_r0.get('수신거부','') or '').strip().upper() == 'Y'
                        # 추가 수신자(수신이메일2/3) → Cc
                        for _c in ('수신이메일2','수신이메일3'):
                            _v = str(_r0.get(_c,'') or '').strip()
                            if _v and '@' in _v and _v.lower() != co_email.lower() \
                               and _v.lower() not in [x.lower() for x in cc_list]:
                                cc_list.append(_v)

                if _optout and not test_mode:
                    logs.append(f"⏭️ {company} — 수신거부 (발송 제외)")
                    prog.progress((idx+1)/max(len(grouped),1)); log.text("\n".join(logs[-8:]))
                    continue
                if not test_mode and not co_email:
                    logs.append(f"⚠️ {company} — 이메일 없음 (발송 실패)")
                    prog.progress((idx+1)/max(len(grouped),1)); log.text("\n".join(logs[-8:]))
                    continue

                if st.session_state.get('_send_preview_co'):
                    st.markdown(f"#### 👁 {company} — 실제 발송 HTML 미리보기")
                    st.components.v1.html(html, height=1500, scrolling=True)
                    st.caption("위 화면이 수신자가 받는 메일과 동일합니다. 발송은 실행되지 않았습니다.")
                    st.session_state.pop('_send_preview_co', None)
                    st.stop()

                # 마감일 알림은 .ics 첨부 대신 공통 캘린더 구독 링크로 간다.
                # 첨부는 네이버·아웃룩에서 '수락/미정/거절' 회의 초대처럼 보였다.
                # build_ics 는 남겨둔다 — 나중에 추적되는 링크로 다시 쓸 수 있다.
                recipients = get_test_recipients() if test_mode else [co_email]
                for to in recipients:
                    msg = MIMEMultipart('alternative')
                    # 한글 표시 이름·제목은 RFC 2047 로 인코딩해야 클라이언트에서 안 깨진다.
                    msg['From']    = formataddr(
                        (str(Header(MAIL_FROM_NAME, 'utf-8')), MAIL_FROM_ADDR))
                    msg['To']      = to
                    if cc_list and not test_mode:
                        msg['Cc'] = ", ".join(cc_list)
                    msg['Subject'] = Header(
                        ("[TEST] " if test_mode else "")
                        + mail_subject(company, _mail_meta), 'utf-8')
                    msg.attach(MIMEText(html, 'html', 'utf-8'))
                    gmail_send(base64.urlsafe_b64encode(msg.as_bytes()).decode())
                    logs.append(f"✅ {company} → {to}" + (f" (+Cc {len(cc_list)})" if cc_list and not test_mode else ""))

                # 예전에는 여기서 기업마다 calendar_id.txt 와 기업별 캘린더에
                # 마감·D-7·D-3 세 건씩 넣으려 했다. 그 캘린더들이 모두 사라져
                # 회차마다 수백 번을 404 로 헛돌고 있었다. 반환값을 보지 않아
                # 실패가 드러나지도 않았다. 공통 캘린더 등록은 발송이 끝난 뒤
                # 아래에서 한 번만 한다. 기업에게 가는 알림은 .ics 첨부가 맡는다.

                _co_rows = [{"기업명":company,"pblancId":n.get('공고ID',''),
                        "공고명":n.get('공고명',''),"발송일":datetime.today().strftime("%Y-%m-%d"),
                        "마감일":n.get('마감일',''),"공고링크":n.get('공고링크',''),
                        "매칭점수":n.get('점수',''),"담당자검토":"○",
                        "검토의견":n.get('검토의견',''),"신청여부":"","선정결과":""}
                    for n in notices]
                history_records.extend(_co_rows)

                # ── 발송 성공 → 이 기업 이력을 즉시 저장 ──────────
                # 기록에 실패하면 다음 기업으로 절대 넘어가지 않는다 (중복 발송 위험).
                if _record_history:
                    _sprog['sent'][company] = {
                        'at':    datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
                        'round': _send_rid,
                        'pids':  [n.get('공고ID','') for n in notices],
                        # 참고 공고도 메일에 실렸으므로 판단 기록에서 구분할 수 있게 남긴다
                        'ref_pids': [x.get('공고ID','') for x in (_mail_meta or {}).get('review', [])],
                        'count': len(_co_rows),
                    }
                    _sprog['pending'].extend(_co_rows)
                    if not save_send_progress(drive, _sprog):
                        st.error(f"⛔ {company} 메일은 나갔지만 발송 기록 저장에 실패했습니다.\n\n"
                                 f"기록 없이 계속 보내면 중복 발송 위험이 있어 여기서 중단합니다. "
                                 f"드라이브 연결을 확인한 뒤 다시 실행하면 이미 보낸 기업은 건너뜁니다.")
                        st.stop()
                    # 엑셀 중간 저장 — 셀 서식 때문에 매번 쓰기엔 느려서 묶어서 반영
                    if len(_sprog['sent']) % HISTORY_FLUSH_EVERY == 0:
                        _ok_m, _n_m = flush_send_history(drive, _sprog)
                        if not _ok_m:
                            st.error("⛔ send_history.xlsx 중간 저장에 실패했습니다. "
                                     "중복 발송을 막기 위해 중단합니다.")
                            st.stop()
                        save_send_progress(drive, _sprog)

                logs.append(f"✅ {company} — {len(notices)}건 발송 완료")
                log.code("\n".join(logs)); prog.progress((idx+1)/len(grouped))

            if test_mode:
                prog.progress(1.0)
                st.success(f"✅ 테스트 발송 완료 — {len(history_records)}건 (발송 이력 저장 안 함)")
                if _empty_skipped:
                    st.info(f"⏭️ 안내할 공고가 없어 발송 제외: {len(_empty_skipped)}개사 — {', '.join(_empty_skipped[:8])}{' 외' if len(_empty_skipped)>8 else ''}")
                st.info("테스트 모드에서는 발송 이력 저장과 캘린더 등록이 모두 생략됩니다. "
                        "실제 발송 시에만 기록·등록됩니다.")
            else:
                if _record_history:
                    with st.spinner("발송 이력 드라이브 저장 중..."):
                        _ok_e, _n_e = flush_send_history(drive, _sprog)
                    if not _ok_e:
                        st.error("⛔ send_history.xlsx 최종 저장에 실패했습니다.\n\n"
                                 "진행 기록은 남아 있으니 드라이브 연결을 확인한 뒤 다시 실행하세요. "
                                 "이미 보낸 기업은 건너뛰고 미반영분만 기록합니다.")
                        st.stop()
                    save_send_progress(drive, _sprog)
                    # 판단 기록에 발송 결과 반영 — 실패해도 발송 흐름을 막지 않는다
                    record_decision_log(drive, _send_rid, _sprog.get('sent', {}))
                    # 이 회차를 그대로 재현할 수 있게 남긴다 (실패해도 발송엔 영향 없음)
                    save_round_snapshot(drive, _send_rid)
                prog.progress(1.0)
                st.success(f"발송 완료 — {len(history_records)}건 → send_history.xlsx 저장 "
                           f"(회차 {_send_rid} · {len(_sprog['sent'])}개사)")
                if _empty_skipped:
                    st.info(f"⏭️ 안내할 공고가 없어 발송 제외: {len(_empty_skipped)}개사 — {', '.join(_empty_skipped[:8])}{' 외' if len(_empty_skipped)>8 else ''}")

                # ── 공통 캘린더 마감일 이벤트 자동 등록 ──
                _CAL_ID = "9078a49950a47b46ddb3511040886f3a016b75ca17169ec1113e5692b7327375@group.calendar.google.com"  # 직접 하드코딩

                try:
                    cal_prog = st.progress(0, text="캘린더 이벤트 등록 중...")
                    added = 0; skipped = 0

                    # 이미 등록된 이벤트 조회 (중복 방지)
                    existing_events = []
                    try:
                        evts = cal_list_events(_CAL_ID)
                        existing_events = [e.get('summary','') for e in evts.get('items',[])]
                    except Exception:
                        pass

                    # 마감일 있는 공고만 등록
                    seen_notices = set()
                    to_register  = []
                    for r in history_records:
                        pname = r.get('공고명','')
                        dl    = r.get('마감일','')
                        if not dl or not pname or pname in seen_notices:
                            continue
                        seen_notices.add(pname)
                        to_register.append({'공고명': pname, '마감일': dl,
                                            '공고링크': r.get('공고링크','')})

                    for i, n in enumerate(to_register):
                        pname = n['공고명']
                        dl    = n['마감일']
                        link  = n.get('공고링크','')

                        if pname in existing_events:
                            skipped += 1
                        else:
                            try:
                                event = {
                                    'summary': pname,
                                    'description': link,
                                    'start': {'date': dl},
                                    'end':   {'date': dl},
                                    'reminders': {
                                        'useDefault': False,
                                        'overrides': [
                                            {'method': 'popup', 'minutes': 60*24*7},
                                            {'method': 'popup', 'minutes': 60*24*3},
                                        ]
                                    }
                                }
                                cal_insert_event(_CAL_ID, event)
                                added += 1
                            except Exception:
                                skipped += 1

                        cal_prog.progress((i+1)/len(to_register),
                                          text=f"캘린더 등록 중... {i+1}/{len(to_register)}")

                    st.success(f"📅 캘린더 이벤트 등록 완료 — 신규 {added}건 / 중복 스킵 {skipped}건")
                except Exception as e:
                    st.warning(f"캘린더 등록 실패 (발송은 완료됨): {e}")
            if not test_mode:
                # 발송 완료 → 회차 종료. 세션뿐 아니라 드라이브 저장본도 비워야
                # 앱 재시작 시 발송한 공고가 승인 상태로 되살아나지 않는다.
                st.session_state['match_results']=[]; st.session_state['review_state']={}
                st.session_state['match_round_id'] = new_round_id()
                save_review_state(drive)
                save_match_state(drive)
            else:
                st.info("테스트 모드 — 매칭 결과와 승인 상태는 그대로 유지됩니다.")


# ══════════════════════════════════════════════════════
# 안내 메일
# ══════════════════════════════════════════════════════
elif page == "안내 메일":
    drive = _get_drive()
    st.title("안내 메일")

    mail_tab1, mail_tab2 = st.tabs(["📨 메일 발송", "📬 회신 확인 (키워드 수집)"])

    with mail_tab2:
        st.subheader("회신 메일 확인 — 키워드 자동 추출")
        st.caption("기업 담당자가 안내 메일에 답장한 내용을 읽어 키워드를 자동 추출합니다.")

        df_c_reply = load_excel(drive, SELECTED_FILE)

        c1, c2 = st.columns(2)
        with c1:
            reply_label = st.text_input("회신 검색 키워드", value="원스톱 스케일업",
                placeholder="발송 메일 제목에 포함된 키워드")
        with c2:
            reply_days = st.number_input("최근 N일 회신 검색", value=30, min_value=1, max_value=90)

        st.caption("💡 기업 담당자가 안내 메일에 **답장(Reply)** 하면 자동으로 여기서 확인됩니다.")

        if st.button("📬 Gmail 회신 검색", type="primary", key="fetch_replies"):
            with st.spinner("Gmail 회신 검색 중..."):
                try:
                    after_date = (datetime.today() - timedelta(days=int(reply_days))).strftime('%Y/%m/%d')
                    query = f'in:inbox after:{after_date}'
                    resp = gapi('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/messages',
                                params={'q': query, 'maxResults': 100})

                    # 응답 상태 디버그 표시
                    if not resp.ok:
                        st.error(f"Gmail API 오류 {resp.status_code}: {resp.text[:200]}")
                    else:
                        all_msgs = resp.json().get('messages', [])
                        st.session_state['reply_msgs'] = all_msgs
                        st.session_state['reply_label_filter'] = reply_label

                        if not all_msgs:
                            st.info(f"최근 {reply_days}일 내 받은 메일이 없습니다.")
                            st.caption(f"검색 쿼리: {query}")
                        else:
                            st.success(f"메일 {len(all_msgs)}건 로드 — 아래에서 확인하세요.")
                except Exception as e:
                    st.error(f"Gmail 검색 실패: {e}")

        def extract_body(payload):
            """멀티파트 메일에서 본문 텍스트 재귀 추출"""
            import base64
            mime = payload.get('mimeType', '')
            if mime == 'text/plain':
                data = payload.get('body', {}).get('data', '')
                if data:
                    return base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='ignore')
            elif mime == 'text/html':
                data = payload.get('body', {}).get('data', '')
                if data:
                    html = base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='ignore')
                    # 태그 제거 후 텍스트만
                    import re as _re
                    return _re.sub(r'<[^>]+>', ' ', html)
            # 멀티파트 재귀
            for part in payload.get('parts', []):
                result = extract_body(part)
                if result and len(result) > 50:
                    return result
            return ''

        # 회신 목록 표시
        if 'reply_msgs' in st.session_state and st.session_state['reply_msgs']:
            st.divider()
            total_msgs = len(st.session_state['reply_msgs'])
            st.subheader(f"회신 목록 ({total_msgs}건)")

            # 선정기업 이메일 목록 미리 구성
            co_emails = {}
            if not df_c_reply.empty and '이메일' in df_c_reply.columns:
                for _, row in df_c_reply.iterrows():
                    em = str(row.get('이메일','')).strip().lower()
                    if em:
                        co_emails[em] = row.get('기업명','')

            # ── 일괄 추출 버튼 ─────────────────────────
            st.info("💡 개별 메일을 열어 '🤖 키워드 자동 추출' 후 저장하거나, 아래 버튼으로 전체 일괄 추출할 수 있습니다.")
            if st.button("🤖 전체 일괄 추출 + 자동 저장", type="primary", key="bulk_extract"):
                import json as _json, re as _re2
                df_bulk = load_excel(drive, SELECTED_FILE)
                prog_bulk = st.progress(0, text="일괄 추출 중...")
                bulk_ok = 0; bulk_fail = 0; bulk_log = []

                for bi, msg_ref in enumerate(st.session_state['reply_msgs'][:50]):
                    try:
                        resp = gapi('GET',
                            f'https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_ref["id"]}',
                            params={'format': 'full'})
                        if not resp.ok:
                            bulk_fail += 1; continue
                        msg_b = resp.json()
                        hdrs_b = {h['name']: h['value'] for h in msg_b.get('payload',{}).get('headers',[])}
                        sender_b = hdrs_b.get('From','')
                        em_b = _re2.search(r'<(.+?)>', sender_b)
                        if em_b:
                            em_b = em_b.group(1).lower().strip()
                        else:
                            # <> 없으면 전체가 이메일
                            em_b = sender_b.lower().strip().strip('"')
                        co_b = co_emails.get(em_b, '')
                        if not co_b:
                            bulk_log.append(f"⏭ {sender_b[:30]} — 미매칭 스킵")
                            prog_bulk.progress((bi+1)/min(total_msgs,50))
                            continue

                        body_b = extract_body(msg_b.get('payload',{}))
                        for sep in ['On ', '-----', '보낸 사람', 'From:']:
                            idx = body_b.find(sep)
                            if idx > 100: body_b = body_b[:idx]; break
                        body_b = body_b.strip()
                        if not body_b:
                            bulk_log.append(f"⏭ {co_b} — 본문 없음")
                            prog_bulk.progress((bi+1)/min(total_msgs,50))
                            continue

                        prompt_b = f"""기업 담당자 회신에서 키워드를 추출하세요.

회신:
{body_b[:1000]}

JSON만 응답 (코드블록 없이):
{{"기술키워드": ["키워드1", "키워드2"], "필요지원": ["지원유형"], "수출관심국": [], "요약": "요약"}}"""

                        res_b = claude_call_raw(prompt_b)
                        if not res_b or not res_b.strip():
                            bulk_fail += 1
                            bulk_log.append(f"❌ {co_b} — Claude 응답 없음 (API 오류)")
                            prog_bulk.progress((bi+1)/min(total_msgs,50))
                            continue
                        res_b = _re2.sub(r'```(?:json)?\s*', '', res_b).strip().rstrip('`').strip()
                        # { } 사이 내용 추출 (중첩 포함)
                        jm = _re2.search(r'\{[^}]*\}', res_b, _re2.DOTALL)
                        if not jm:
                            jm = _re2.search(r'\{.*\}', res_b, _re2.DOTALL)
                        if not jm:
                            bulk_fail += 1
                            bulk_log.append(f"❌ {co_b} — JSON 파싱 실패: [{res_b[:80]}]")
                            prog_bulk.progress((bi+1)/min(total_msgs,50))
                            continue

                        ext_b = _json.loads(jm.group())
                        kws_b = ext_b.get('기술키워드', [])
                        sup_b = ext_b.get('필요지원', [])
                        exp_b = ext_b.get('수출관심국', [])

                        # 드라이브 저장
                        mask_b = df_bulk['기업명'] == co_b
                        if mask_b.any():
                            existing_b = str(df_bulk.loc[mask_b, '키워드보완'].values[0] or '')
                            new_kws_b  = ', '.join(kws_b + sup_b)
                            df_bulk.loc[mask_b, '키워드보완'] = ', '.join(filter(None, [existing_b, new_kws_b]))
                            if exp_b:
                                existing_exp = str(df_bulk.loc[mask_b, '수출국가'].values[0] or '')
                                df_bulk.loc[mask_b, '수출국가'] = ', '.join(filter(None, [existing_exp, ', '.join(exp_b)]))
                            bulk_ok += 1
                            bulk_log.append(f"✅ {co_b} — {', '.join(kws_b[:3])}")
                        prog_bulk.progress((bi+1)/min(total_msgs,50))

                    except Exception as e_b:
                        bulk_fail += 1
                        bulk_log.append(f"❌ {sender_b[:20]}: {str(e_b)[:30]}")

                # 일괄 저장
                if bulk_ok > 0:
                    save_excel(drive, df_bulk, SELECTED_FILE, "선정기업명단", "1F4E79")
                    st.success(f"✅ {bulk_ok}개사 키워드 저장 완료 / 실패 {bulk_fail}건")
                else:
                    st.warning(f"저장된 기업 없음 (실패 {bulk_fail}건)")

                with st.expander("처리 로그"):
                    for log in bulk_log:
                        st.caption(log)

            st.divider()

            shown = 0
            for i, msg_ref in enumerate(st.session_state['reply_msgs'][:50]):
                try:
                    resp = gapi('GET',
                        f'https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_ref["id"]}',
                        params={'format': 'full'})
                    if not resp.ok: continue
                    msg = resp.json()

                    hdrs    = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
                    subject = hdrs.get('Subject', '')
                    sender  = hdrs.get('From', '')
                    date_str= hdrs.get('Date', '')[:16]

                    import re as _re
                    sender_email_clean = _re.search(r'<(.+?)>', sender)
                    sender_email_clean = sender_email_clean.group(1).lower() if sender_email_clean else sender.lower()

                    # 선정기업 여부 확인
                    matched_co = co_emails.get(sender_email_clean, '')
                    badge = f"✅ {matched_co}" if matched_co else "❓ 미매칭"

                    body_text = extract_body(msg.get('payload', {}))
                    # 이메일 인용 구분선 이전 내용만 (답장 본문)
                    import re as _re
                    for sep in ['On ', '---- ', '-----', '____', '보낸 사람', 'From:']:
                        idx = body_text.find(sep)
                        if idx > 100:
                            body_text = body_text[:idx]
                            break
                    body_text = body_text.strip()

                    shown += 1
                    with st.expander(f"{badge} | **{sender[:30]}** — {subject[:35]} ({date_str})"):

                        # 기업명 자동 매칭 (이미 위에서 계산됨)
                        if matched_co:
                            st.success(f"✅ 매칭 기업: **{matched_co}**")
                        else:
                            st.caption(f"발신: {sender_email_clean}")
                            matched_co = st.selectbox("기업 선택 (수동 매칭)",
                                [''] + (df_c_reply['기업명'].tolist() if not df_c_reply.empty else []),
                                key=f"reply_co_{i}")

                        # 회신 본문 표시
                        if body_text:
                            st.text_area("회신 내용 (답장 본문)", value=body_text[:800],
                                         height=130, key=f"reply_body_{i}", disabled=True)
                        else:
                            st.warning("본문을 읽을 수 없습니다.")

                        # 키워드 추출
                        if body_text and st.button("🤖 키워드 자동 추출", key=f"extract_{i}"):
                            with st.spinner("Claude 분석 중..."):
                                prompt = f"""아래는 지원사업 안내 메일에 대한 기업 담당자의 회신입니다.
[공고 피드백] 섹션에 '맞아요/애매해요/안 맞아요: 공고명' 형식이 있을 수 있고,
[Q1], [Q2] 형식의 키워드 답변도 있을 수 있습니다.
[Gmail 주소] 섹션에 구글 계정 주소가 있을 수 있습니다.

회신 내용:
{body_text[:1500]}

위 내용에서 다음을 추출해주세요.
- [공고 피드백] 섹션에서 공고별 피드백 추출
- [키워드 보완] 또는 Q1/Q2 답변에서 기술키워드와 필요지원 추출
- [Gmail 주소] 섹션에서 @gmail.com 또는 구글 계정 이메일 추출
- 형식이 없으면 전체 내용에서 추출

반드시 아래 JSON 형식으로만 응답하세요. 코드블록이나 설명 텍스트 없이 JSON만:
{{"기술키워드": ["키워드1"], "필요지원": ["지원유형"], "수출관심국": [], "공고피드백": [{{"공고명": "...", "피드백": "맞아요"}}], "gmail": "", "요약": "한 줄 요약"}}"""
                                try:
                                    import json as _json, re as _re2
                                    res = claude_call_raw(prompt)
                                    # 코드블록 제거
                                    res = _re2.sub(r'```(?:json)?\s*', '', res).strip().rstrip('`').strip()
                                    # 중첩 JSON 추출
                                    json_match = _re2.search(r'\{[^{}]*\}', res, _re2.DOTALL)
                                    if not json_match:
                                        json_match = _re2.search(r'\{.*\}', res, _re2.DOTALL)
                                    if json_match:
                                        extracted = _json.loads(json_match.group())
                                        st.session_state[f'extracted_{i}'] = extracted
                                    else:
                                        st.error(f"JSON 파싱 실패 — Claude 응답: {res[:100]}")
                                except Exception as e:
                                    st.error(f"추출 실패: {e}")

                        # 추출 결과
                        if f'extracted_{i}' in st.session_state:
                            ext = st.session_state[f'extracted_{i}']
                            kws = ext.get('기술키워드', [])
                            sup = ext.get('필요지원', [])
                            exp = ext.get('수출관심국', [])
                            feedbacks = ext.get('공고피드백', [])

                            col_a, col_b, col_c = st.columns(3)
                            with col_a:
                                st.caption("**기술 키워드**")
                                st.write(', '.join(kws) if kws else '—')
                            with col_b:
                                st.caption("**필요 지원**")
                                st.write(', '.join(sup) if sup else '—')
                            with col_c:
                                st.caption("**수출 관심국**")
                                st.write(', '.join(exp) if exp else '—')

                            # 공고 피드백 표시
                            if feedbacks:
                                st.caption("**공고 피드백**")
                                for fb in feedbacks:
                                    icon = {"맞아요":"✅","애매해요":"🟡","안맞아요":"❌","안 맞아요":"❌"}.get(fb.get('피드백',''), "❓")
                                    st.write(f"{icon} {fb.get('피드백','')} — {fb.get('공고명','')[:40]}")

                            gmail = ext.get('gmail','')
                            if gmail:
                                st.caption("**Gmail 주소**")
                                st.write(gmail)

                            st.caption(f"요약: {ext.get('요약','')}")

                            if matched_co and (kws or sup or gmail):
                                if st.button(f"💾 {matched_co} 저장",
                                             key=f"save_reply_{i}", type="primary"):
                                    df_c2 = load_excel(drive, SELECTED_FILE)
                                    mask  = df_c2['기업명'] == matched_co
                                    if mask.any():
                                        if kws or sup:
                                            existing = str(df_c2.loc[mask, '키워드보완'].values[0] or '')
                                            new_kws  = ', '.join(kws + sup)
                                            merged   = ', '.join(filter(None, [existing, new_kws]))
                                            df_c2.loc[mask, '키워드보완'] = merged
                                        if exp:
                                            existing_exp = str(df_c2.loc[mask, '수출국가'].values[0] or '')
                                            df_c2.loc[mask, '수출국가'] = ', '.join(
                                                filter(None, [existing_exp, ', '.join(exp)]))
                                        if gmail and 'Gmail' in df_c2.columns:
                                            df_c2.loc[mask, 'Gmail'] = gmail
                                        elif gmail and 'Gmail' not in df_c2.columns:
                                            df_c2['Gmail'] = ''
                                            df_c2.loc[mask, 'Gmail'] = gmail
                                        if save_excel(drive, df_c2, SELECTED_FILE, "선정기업명단", "1F4E79"):
                                            st.success(f"✅ {matched_co} 저장 완료")
                                        else:
                                            st.error("저장 실패")
                            elif not matched_co:
                                st.warning("저장하려면 위에서 기업을 선택하세요.")

                except Exception as e:
                    continue

            if shown == 0:
                st.info("메일 내용을 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")

    with mail_tab1:
        info_box("안내 메일",
            """
공고 매칭과 무관한 일반 안내 메일을 선정/예비 기업에게 발송합니다.

**활용 예시**
- 첫 안내 메일 (선정 축하 + 회신 요청)
- 교육 프로그램 수요조사
- 성과집계 조사 요청
- 서류 제출 안내
            """,
            "발송 대상 선택 → 제목/내용 작성 → 미리보기 확인 → 발송")

        with st.spinner("기업 명단 로딩 중..."):
            df_c = load_excel(drive, SELECTED_FILE)

        if df_c.empty:
            st.warning("선정기업 명단이 없습니다. 기업 관리 탭에서 먼저 업로드하세요.")
            st.stop()

        for col in ['수신거부','선정구분']:
            if col not in df_c.columns: df_c[col] = ''

        st.subheader("① 발송 대상 선택")
        has_status = '선정구분' in df_c.columns and df_c['선정구분'].str.strip().ne('').any()

        col1, col2 = st.columns(2)
        with col1:
            if has_status:
                target_group = st.radio(
                    "발송 그룹",
                    ["선정 50개사", "예비 20개사", "전체 70개사",
                     "리마인더 (선정-교육 미신청)", "직접 선택", "이메일 직접 입력"],
                    horizontal=False, key="notice_mail_group"
                )
            else:
                target_group = "전체"

        # 대상 기업 필터링
        df_active = df_c[df_c['수신거부'] != 'Y'].copy()
        direct_input_email = None
        if has_status:
            if target_group == "선정 50개사":
                df_target = df_active[df_active['선정구분'] == '선정']
            elif target_group == "예비 20개사":
                df_target = df_active[df_active['선정구분'] == '예비']
            elif target_group == "리마인더 (선정-교육 미신청)":
                # 교육 신청 이력(edu_registration.json)에서 특정 회차 신청자를 제외
                import json as _json_rem
                def _load_edu_rem(drv):
                    try:
                        raw = load_json(drv, "edu_registration.json")
                        return raw if isinstance(raw, list) else []
                    except Exception:
                        return []
                def _norm_co(s):
                    s = str(s)
                    s = re.sub(r'\(주\)|\(유\)|주식회사|㈜', '', s)
                    return s.replace(' ', '').strip()
                _edu = _load_edu_rem(drive)
                _rounds = sorted({r.get('교육회차', '') for r in _edu if r.get('교육회차')}, reverse=True)
                if not _rounds:
                    st.warning("교육 신청 이력에 회차 정보가 없습니다. '교육 신청 집계' 탭에서 먼저 회신을 파싱해 주세요.")
                    df_target = df_active.head(0)
                else:
                    _sel_round = st.selectbox("제외할 교육 회차 (이 회차 신청자에게는 발송 안 함)",
                                              _rounds, key="rem_round")
                    _applied_keys = {_norm_co(r['기업명']) for r in _edu
                                     if r.get('교육회차') == _sel_round and r.get('기업명')}
                    _sel_df = df_active[df_active['선정구분'] == '선정'].copy()
                    _mask = ~_sel_df['기업명'].apply(lambda x: _norm_co(x) in _applied_keys)
                    df_target = _sel_df[_mask]
                    st.caption(f"선정 50개사 중 {_sel_round} 신청 {len(_applied_keys)}개사 제외 "
                               f"→ 발송 대상 {len(df_target)}개사")
            elif target_group == "직접 선택":
                selected_names = st.multiselect(
                    "기업 직접 선택", df_active['기업명'].tolist(), key="notice_mail_select"
                )
                df_target = df_active[df_active['기업명'].isin(selected_names)]
            elif target_group == "이메일 직접 입력":
                direct_input_email = st.text_input(
                    "수신 이메일 주소",
                    placeholder="example@company.com",
                    key="notice_direct_email_input"
                )
                df_target = df_active.head(0)  # 빈 데이터프레임
            else:
                df_target = df_active
        else:
            df_target = df_active

        # 제외 기업 선택 (모든 그룹 공통 — 이미 신청한 기업 등 빼고 발송)
        if direct_input_email is None and not df_target.empty:
            _excl = st.multiselect(
                "🚫 제외할 기업 (선택)", df_target['기업명'].tolist(),
                key="notice_mail_exclude",
                help="이미 신청했거나 이번 발송에서 빼야 하는 기업을 선택하세요.")
            if _excl:
                df_target = df_target[~df_target['기업명'].isin(_excl)]
                st.caption(f"제외 {len(_excl)}개사 적용 → 최종 발송 대상 {len(df_target)}개사")

        with col2:
            st.metric("발송 대상", f"{len(df_target)}개사")
            if not df_target.empty:
                email_count = df_target['이메일'].str.strip().ne('').sum()
                st.metric("이메일 보유", f"{email_count}개사")

        st.divider()
        st.subheader("② 메일 내용 작성")

        # 템플릿 선택
        st.caption("템플릿 선택 (직접 수정 가능)")
        template_choice = st.radio(
            "템플릿 선택",
            [
                "직접 작성",
                "첫 안내 메일 (선정 축하 + 회신 요청)",
                "선정 기업 축하 및 프로그램 안내",
                "10월 교육 신청 안내",
                "10월 교육 리마인더 (미신청 대상)",
                "함께하기 회원소개 가입 안내",
                "CES 혁신상 밋업 신청 안내",
                "교육 프로그램 수요조사",
                "성과집계 조사 요청",
                "서류 제출 안내",
            ],
            key="notice_mail_template",
            horizontal=True,
            label_visibility="collapsed",
        )

        TEMPLATES = {
            "10월 교육 신청 안내": {
                "subject": "[원스톱 스케일업] 10월 무료 교육 신청 안내 (~10/23) — 기업이 알아야 할 지식재산 전략",
                "body": "10월 28일(수) 14~16시 Zoom으로 진행되는 지식재산(특허·상표·디자인) 전략 교육을 안내드립니다. 10/23(금)까지 회신으로 신청해 주세요.",
            },
            "10월 교육 리마인더 (미신청 대상)": {
                "subject": "[원스톱 스케일업] 10월 무료 교육 마감 임박 (~10/23) — 기업이 알아야 할 지식재산 전략",
                "body": "10월 교육 신청이 10/23(금)에 마감되어 다시 안내드립니다. 마감 전에 회신으로 신청해 주세요.",
            },
            "9월 교육 신청 안내": {
                "subject": "[원스톱 스케일업] 9월 무료 교육 신청 안내 (~9/9) — 실무에 바로 적용하는 디지털 마케팅",
                "body": "9월 16일(수) 14~16시 Zoom으로 진행되는 디지털 마케팅 교육을 안내드립니다. 9/9(수)까지 회신으로 신청해 주세요.",
            },
            "9월 교육 리마인더 (미신청 대상)": {
                "subject": "[원스톱 스케일업] 9월 무료 교육 신청 기간 연장 (~9/9) — 실무에 바로 적용하는 디지털 마케팅",
                "body": "9월 교육 신청 기간을 9/9(수)까지 연장하여 다시 안내드립니다. 기간 내 회신으로 신청해 주세요.",
            },
            "8월 교육 리마인더 (미신청 대상)": {
                "subject": "[원스톱 스케일업] 8월 무료 교육 마감 임박 (~8/7) — 네이버·구글 검색 상위 노하우",
                "body": "8월 교육 신청 마감이 다가와 다시 안내드립니다. 마감 전에 꼭 신청해 주세요.",
            },
            "함께하기 회원소개 가입 안내": {
                "subject": "[원스톱 스케일업] 함께하기(기업 회원소개) 등록 안내",
                "body": "함께하기 회원소개 페이지를 준비했습니다. 귀사 정보를 등록해 주세요.",
            },
            "7월 교육 프로그램 신청 안내": {
                "subject": "[원스톱 스케일업] 7월 교육 프로그램 참여 신청 안내 (7/14~17)",
                "body": """안녕하세요, 원스톱 스케일업 운영팀입니다.
선정 기업 여러분께 제공되는 7월 교육 프로그램을 안내드립니다.
부담 없이 참여하실 수 있으며, 실무에 바로 적용할 수 있는 내용으로 준비했습니다.
많은 관심과 참여 부탁드립니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 7월 정기 교육 | 선정기업 무료 제공 | 온라인 (Zoom)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

주  제: AI 마케팅 / 콘텐츠 제작 활용
        온라인(SNS) 홍보 · AI 마케팅/홍보 · CANVA · 캡컷 · 미리캔버스 활용 실습
강  사: 송윤경 강사 (소상공인연합회)
일  시: 2026년 7월 29일(수) 14:00 ~ 16:00 (질의응답 포함)
방  식: 온라인 (Zoom)

※ 줌 링크·교육자료는 다음 주 초 별도 안내드릴 예정입니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 신청 방법 | 마감: 7월 22일(수)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

이 메일에 아래 내용을 작성하여, 본 메일에 답장해 주세요.

기업명:
담당자명:
연락처:
※ 1인 이상 참여 시 참여 인원 정보를 모두 작성해 주세요.

─────────────────────────────────
📢 이런 행사도 있어요
─────────────────────────────────

CES 혁신상 수상 노하우 공유 밋업
일시: 2026년 7월 28일(화) (시간·장소 추후 안내)
내용: CES 혁신상 수상 경험 공유 및 2027 CES 도전 준비 Q&A
관심 있으신 기업은 별도 안내 시 참고해 주세요.

─────────────────────────────────
📅 하반기 월별 교육 일정
─────────────────────────────────

07월 | AI 마케팅 / 콘텐츠 제작 활용  ← 현재
08월 | 디지털 마케팅
09월 | 네이버 크리에이터 & 비즈니스 플랫폼 활용
10월 | 특허·상표권·디자인권 보호
11월 | 해외 ODA 시장 진출 및 KOICA 무상원조 참여방안
12월 | 해외 지식재산권 보호 지원사업 및 활용사례

※ 상기 일정은 내부 사정에 따라 변동될 수 있습니다.

감사합니다.
혁신제품지원센터 원스톱 스케일업 운영팀
onestop.kipcc@gmail.com""",
            },
            "CES 혁신상 밋업 신청 안내": {
                "subject": "[원스톱 스케일업] CES 혁신상 수상 노하우 공유 밋업 안내",
                "body": """안녕하세요, 원스톱 스케일업 운영팀입니다.

CES 2026(1월 6~9일, 미국 라스베이거스)에서 조달기업 30개사가
혁신상을 수상하며 역대 최다 성과를 거뒀습니다.
수상 노하우를 직접 들을 수 있는 밋업에 여러분을 초대합니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 CES 2026 조달기업 성과
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

· 혁신상 수상 30개사 (역대 최다)
· AI 융복합 제품 17개
· 혁신제품 지정기업 19개사 · 벤처나라 등록기업 13개사
· 재난·안전 / 자원순환 / 헬스케어 등 공공분야 혁신제품 국제적 주목

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎤 이번 밋업 | 선정기업 무료
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

주  제: CES 혁신상 수상 노하우 공유
일  시: 2026년 7월 28일(화) 14:00 ~ 18:30 (17:30부터 네트워킹 디너)
장  소: MIK BASE CAMP (서울 서초구 원터6길 1)

🎤 밋업 프로그램 구성
· 1부 | CES INSIGHT / INNOVATION AWARDS VALUE
· 2부 | 혁신상 수상 기업이 전하는 핵심 노하우
· 3부 | CES INNOVATION AWARD 전문가 토크
· 4부 | 네트워킹 디너 (신청자만 참석 · 자부담 비용 5만원 발생)

📍 오시는 길
· 장소: MIK BASE CAMP (서울 서초구 원터6길 1)
· 주차: 청계산근린광장 공영주차장 (서초구 원지동 361-1)
· 교통: 신분당선 청계산입구역 2번 출구 도보 약 10분 (약 650m)

🗓️ 하반기 글로벌 진출 밋업 시리즈
· 7월  | CES 혁신상 수상 노하우 공유 밋업 (7/28 진행 예정)
· 11월 | 글로벌 전시회 참가 전략 밋업 ① (일정 추후 안내)
· 12월 | 글로벌 전시회 참가 전략 밋업 ② (일정 추후 안내)
· 12월 | CES 2027 수상기업 네트워킹 파티 (일정 추후 안내)
※ 상기 일정과 프로그램은 내부 사정에 따라 변경될 수 있습니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 CES 2027 혁신상 도전 안내
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

· 신청 접수: 2026. 6. 5.(금) ~ 8. 19.(수)
· 결과 통보: 2026. 11. 2.(월)
· 수상 발표: 2026. 11. 9.(월)
· 출시 조건: 2026.4.1 ~ 2027.3.31 최초 출시 제품
· 제품 1개당 최대 4개 카테고리 출품 가능
· CES 전시 참가 없이도 혁신상 신청 가능

신청 바로가기: https://cta.secure-platform.com/ces-awards

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 참여 신청
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

아래 내용을 작성하여, 본 메일에 답장해 주세요.
※ 신청 마감: 7월 24일(금) 18:00까지

기업명:
담당자명:
연락처:
※ 1인 이상 참여 시 참여 인원 정보를 모두 작성해 주세요.
감사합니다.

WITH AVING NEWS
혁신제품지원센터 원스톱 스케일업 운영팀
onestop.kipcc@gmail.com""",
            },
            "첫 안내 메일 (선정 축하 + 회신 요청)": {
                "subject": "[원스톱 스케일업] 2026년 선정을 축하드립니다",
                "body": """안녕하세요, 혁신제품지원센터 원스톱 스케일업 운영팀입니다.

2026년 원스톱 스케일업 프로그램 선정 기업으로 확정되신 것을
진심으로 축하드립니다.

─────────────────────────────────
▣ 원스톱 스케일업이란?
─────────────────────────────────

귀사의 성장 단계와 수요에 맞춰 지원사업 공고 안내부터
역량강화 교육, 개별 컨설팅, 기업 간 협업 매칭까지
필요한 것을 한 곳에서 지원받으실 수 있는 프로그램입니다.

─────────────────────────────────
▣ 주요 프로그램 (7월~11월)
─────────────────────────────────

① 맞춤 공고 정기 안내 (격주)
   귀사 분야에 맞는 지원사업 공고를 선별해 격주로 보내드립니다.
   공고 마감일은 구글 캘린더에 자동 등록되며 D-7, D-3 알림을 받으실 수 있습니다.

② 역량강화 교육 (월 1회, 7월~12월)
   온라인마케팅, MAS 실무, 특허·상표권, 해외ODA 진출 등
   월별 전문가 강의를 안내해드립니다.

③ 개별 담당자 배정
   담당자가 배정되어 목표 확인 및 분기별 체크인을 진행합니다.

④ 기업 간 협업 매칭
   기술협력·마케팅 제휴·해외진출 파트너 연결을 지원합니다.

─────────────────────────────────
▣ 한 가지 부탁드립니다
─────────────────────────────────

귀사에 꼭 맞는 공고를 선별해드리기 위해
이 메일에 답장으로 아래 내용을 채워서 보내주시면 감사하겠습니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Q1] 귀사 주요 제품이나 기술을 한 줄로 소개해주세요.

예) 실내 공기질 측정 IoT 센서를 제조합니다
예) AI 기반 의료 영상 분석 소프트웨어를 개발합니다
예) 친환경 수처리 필터 소재를 생산합니다

→ 답변:


[Q2] 올해 가장 집중하고 싶은 것을 알려주세요.

예) G-PASS 등록 후 해외조달 시장 진출
예) 수출바우처로 동남아 시장 마케팅
예) 혁신제품 재지정 및 MAS 등록 준비
예) R&D 과제 발굴 및 기술개발

→ 답변:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

짧게 적어주셔도 충분합니다.
회신 내용을 바탕으로 더 정확한 공고를 선별해드리겠습니다.

─────────────────────────────────

앞으로 귀사의 성장을 함께 돕겠습니다.
궁금한 점은 언제든 이 메일로 답장해주세요.

감사합니다.

혁신제품지원센터 원스톱 스케일업 운영팀
담당: [담당자명] / [연락처] / [이메일]""",
            },
            "선정 기업 축하 및 프로그램 안내": {
                "subject": "[원스톱 스케일업] 2026년 선정 기업 안내 드립니다",
                "body": """안녕하세요, 혁신제품지원센터 원스톱 스케일업 운영팀입니다.

    귀사가 2026년 원스톱 스케일업 프로그램 참여 기업으로 선정되셨음을 진심으로 축하드립니다.

    본 프로그램은 혁신제품 지정기업, G-PASS 기업, 우수조달기업 등 조달·수출 역량을 갖춘 기업의 해외 판로 개척 및 공공조달 시장 진출을 집중 지원하기 위해 기획되었습니다.

    ▣ 주요 지원 내용
    - 맞춤형 지원사업 공고 발굴 및 정기 안내
    - 해외조달시장(G-PASS, KONEPS 연계 등) 진출 컨설팅
    - 조달·수출 분야 역량강화 교육 프로그램
    - 성과 분석 및 지속적 피드백 제공

    향후 운영 일정과 세부 안내는 순차적으로 말씀드릴 예정입니다. 프로그램 운영 기간 동안 적극적인 참여와 관심 부탁드립니다.

    문의사항이 있으시면 아래 연락처로 편하게 연락 주시기 바랍니다.
    감사합니다.""",
            },
            "교육 프로그램 수요조사": {
                "subject": "[원스톱 스케일업] 역량강화 교육 프로그램 수요조사 안내",
                "body": """안녕하세요, 혁신제품지원센터 원스톱 스케일업 운영팀입니다.

    2026년 하반기 역량강화 교육 프로그램 편성을 위해 수요조사를 진행합니다.
    귀사에 실질적으로 도움이 되는 교육을 기획하고자 하오니, 3분 내외의 짧은 응답 부탁드립니다.

    📋 수요조사 참여하기: [링크]
    응답 기한: [응답 기한]

    ▣ 주요 조사 항목
    - 희망 교육 분야 (해외조달, 수출바우처 활용, 혁신제품 지정, IP·인증 등)
    - 선호 교육 방식 (온라인/오프라인, 집합교육/1:1 컨설팅)
    - 희망 교육 시간 및 일정

    수요조사 결과는 교육 프로그램 편성에 직접 반영될 예정입니다.
    바쁘신 와중에도 귀한 시간 내어 주셔서 감사합니다.""",
            },
            "성과집계 조사 요청": {
                "subject": "[원스톱 스케일업] 프로그램 참여 성과 자료 제출 요청",
                "body": """안녕하세요, 혁신제품지원센터 원스톱 스케일업 운영팀입니다.

    2026년 원스톱 스케일업 프로그램 운영 성과 집계를 위해 참여 기업의 성과 현황 파악이 필요합니다.
    아래 안내에 따라 기한 내 자료 제출을 부탁드립니다.

    ▣ 제출 항목
    - 프로그램 참여 후 지원사업 신청·선정 현황
    - 해외 수출 계약 또는 해외조달시장 진입 실적
    - 혁신제품 지정, G-PASS 등 인증 취득 현황
    - 기타 프로그램 활용 성과

    📋 성과 입력 링크: [링크]
    제출 기한: [제출 기한]

    제출해 주신 자료는 프로그램 개선 및 정책 보고 목적으로만 활용되며, 개별 정보는 외부에 공개되지 않습니다.
    협조해 주셔서 감사합니다.""",
            },
            "서류 제출 안내": {
                "subject": "[원스톱 스케일업] 참여 확약서 및 필수 서류 제출 안내",
                "body": """안녕하세요, 혁신제품지원센터 원스톱 스케일업 운영팀입니다.

    2026년 원스톱 스케일업 프로그램 참여를 위한 필수 서류 제출을 안내드립니다.
    아래 항목을 확인하시고 기한 내에 제출하여 주시기 바랍니다.

    ▣ 제출 서류
    1. 프로그램 참여 확약서 (서명 후 스캔 또는 사진 첨부)
    2. 사업자등록증 사본
    3. 기업 소개자료 (제품 및 기술 개요 포함, A4 2페이지 이내)

    📋 서류 제출 방법: [제출 링크 또는 이메일 안내]
    제출 기한: [제출 기한]
    제출처: onestop.kipcc@gmail.com

    기한 내 미제출 시 프로그램 참여가 제한될 수 있으니 반드시 기한을 준수해 주시기 바랍니다.
    서류 관련 문의사항은 아래 운영팀으로 연락 주시기 바랍니다.
    감사합니다.""",
            },
        }

        # 템플릿 선택 시 session_state를 직접 갱신 → text_input/text_area에 즉시 반영
        # (Streamlit에서 value= 파라미터는 최초 렌더링에만 적용되므로 session_state 방식 필요)
        prev_template = st.session_state.get('_prev_notice_template', '')
        if template_choice != prev_template:
            st.session_state['_prev_notice_template'] = template_choice
            if template_choice != "직접 작성" and template_choice in TEMPLATES:
                st.session_state['notice_mail_subject'] = TEMPLATES[template_choice]["subject"]
                st.session_state['notice_mail_body']    = TEMPLATES[template_choice]["body"]
            else:
                st.session_state['notice_mail_subject'] = ""
                st.session_state['notice_mail_body']    = ""
            st.rerun()

        mail_subject = st.text_input("제목", key="notice_mail_subject")
        mail_body    = st.text_area("본문", height=300, key="notice_mail_body",
                                    help="수신자 이름은 자동으로 '[기업명] 담당자님'으로 삽입됩니다.")
        form_link    = st.text_input("📋 구글 폼 링크 (선택사항)", placeholder="https://forms.gle/...",
                                     key="notice_mail_form")

        st.divider()
        st.subheader("③ 발송 미리보기")

        if df_target.empty and not direct_input_email:
            st.warning("발송 대상 기업이 없습니다.")
        elif (not mail_subject or not mail_body) and template_choice not in ("7월 교육 프로그램 신청 안내", "8월 교육 리마인더 (미신청 대상)", "9월 교육 신청 안내", "9월 교육 리마인더 (미신청 대상)", "10월 교육 신청 안내", "10월 교육 리마인더 (미신청 대상)", "함께하기 회원소개 가입 안내", "CES 혁신상 밋업 신청 안내"):
            st.info("제목과 본문을 작성하면 미리보기가 표시됩니다.")
        else:
            sample_company = df_target.iloc[0]['기업명'] if not df_target.empty else "샘플기업"
            today_str = datetime.today().strftime('%Y.%m.%d')

            form_section = ""
            if form_link:
                form_section = f"""
                <div style="background:rgba(74,158,255,0.1);border:1px solid rgba(74,158,255,0.3);
                            border-radius:8px;padding:16px 18px;margin:16px 0;">
                  <p style="margin:0 0 8px;font-size:11px;font-weight:700;color:#10B981;letter-spacing:1.5px;">
                    📋 설문/폼 링크
                  </p>
                  <a href="{form_link}" style="font-size:13px;color:#10B981;">{form_link}</a>
                </div>"""

            body_html = mail_body.replace('\n', '<br>')

            # 함께하기 가입 안내 HTML 미리보기
            if template_choice == "함께하기 회원소개 가입 안내":
                _nm = df_target.iloc[0].get('기업명','') if not df_target.empty else ''
                sample_html = build_together_html(company=_nm, 담당자='')
                st.components.v1.html(sample_html, height=1400, scrolling=True)

            # 10월 교육 안내/리마인더 전용 HTML 미리보기
            elif template_choice in ("10월 교육 신청 안내", "10월 교육 리마인더 (미신청 대상)"):
                _co_nm = df_target.iloc[0].get('기업명','') if not df_target.empty else ''
                sample_html = build_oct_edu_html(company=_co_nm,
                    is_reminder=(template_choice == "10월 교육 리마인더 (미신청 대상)"))
                st.components.v1.html(sample_html, height=1400, scrolling=True)

            # 9월 교육 안내/리마인더 전용 HTML 미리보기
            elif template_choice in ("9월 교육 신청 안내", "9월 교육 리마인더 (미신청 대상)"):
                _co_nm = df_target.iloc[0].get('기업명','') if not df_target.empty else ''
                sample_html = build_sep_edu_html(company=_co_nm,
                    is_reminder=(template_choice == "9월 교육 리마인더 (미신청 대상)"))
                st.components.v1.html(sample_html, height=1300, scrolling=True)

            # 8월 교육 리마인더 전용 HTML 미리보기
            elif template_choice == "8월 교육 리마인더 (미신청 대상)":
                _co_kw   = df_target.iloc[0].get('기술키워드','') if not df_target.empty else ''
                _co_area = df_target.iloc[0].get('관심사업분야','') if not df_target.empty else ''
                _co_type = df_target.iloc[0].get('기업유형','') if not df_target.empty else ''
                _co_nm   = df_target.iloc[0].get('기업명','') if not df_target.empty else ''
                sample_html = build_aug_edu_html(company=_co_nm, co_kw=_co_kw,
                    co_area=_co_area, co_type=_co_type, is_reminder=True)
                st.components.v1.html(sample_html, height=1200, scrolling=True)

            # 7월 교육 템플릿 전용 HTML 미리보기
            elif template_choice == "7월 교육 프로그램 신청 안내":
                # 미리보기용 - 기업 정보 샘플로 표시
                _co_kw   = df_target.iloc[0].get('기술키워드','—') if not df_target.empty else '—'
                _co_area = df_target.iloc[0].get('관심사업분야','—') if not df_target.empty else '—'
                _co_type = df_target.iloc[0].get('기업유형','—') if not df_target.empty else '—'
                sample_html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F2F4F7;font-family:'Apple SD Gothic Neo',Arial,sans-serif;">
<div style="max-width:580px;margin:32px auto;">
  <div style="background:#0F1D2E;border-radius:14px 14px 0 0;padding:24px 28px 20px;border:1px solid #1E3A5F;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td valign="top">
        <p style="margin:0 0 2px;font-size:10px;color:rgba(255,255,255,0.4);letter-spacing:2px;">원스톱 스케일업 · 혁신제품지원센터</p>
        <p style="margin:0;font-size:20px;font-weight:700;color:#fff;">7월 교육 프로그램 신청 안내</p>
        <p style="margin:4px 0 0;font-size:12px;color:#9FD6C0;">신청 기간 ~ 7월 22일(수)</p>
      </td>
      <td width="64" align="right" valign="top">
        <div style="background:#F59E0B;border-radius:10px;padding:8px 10px;text-align:center;min-width:48px;">
          <p style="margin:0;font-size:18px;font-weight:800;color:#0F172A;line-height:1;">⏰</p>
          <p style="margin:3px 0 0;font-size:9px;font-weight:700;color:#0F172A;letter-spacing:0.5px;">마감임박</p>
        </div>
      </td>
    </tr></table>
  </div>
  <div style="background:#fff;padding:20px 28px 16px;border-left:1px solid #E2E8F0;border-right:1px solid #E2E8F0;">
    <p style="margin:0;font-size:13px;color:#374151;line-height:1.8;">
      안녕하세요, 원스톱 스케일업 운영팀입니다.<br>
      선정 기업 여러분께 제공되는 <b>7월 교육 프로그램</b>을 안내드립니다.<br>
      부담 없이 참여하실 수 있으며, 실무에 바로 적용할 수 있는 내용으로 준비했습니다.<br>
      많은 관심과 참여 부탁드립니다.
    </p>
  </div>
  <div style="background:#fff;padding:0 28px 20px;border-left:1px solid #E2E8F0;border-right:1px solid #E2E8F0;">
    <div style="background:#F0FDF4;border:1.5px solid #10B981;border-radius:10px;padding:18px 20px;">
      <div style="margin-bottom:12px;">
        <span style="background:#10B981;color:#fff;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;">7월 정기 교육</span>
        <span style="background:#ECFDF5;color:#059669;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;margin-left:6px;">선정기업 무료 제공</span>
        <span style="font-size:11px;color:#6B7280;margin-left:6px;">온라인 (Zoom)</span>
      </div>
      <p style="margin:0 0 4px;font-size:16px;font-weight:700;color:#0F172A;">AI 마케팅 / 콘텐츠 제작 활용</p>
      <div style="margin:6px 0 12px;padding:10px 14px;background:#fff;border-radius:8px;border-left:3px solid #10B981;">
        <p style="margin:0;font-size:12px;color:#374151;line-height:1.8;">
          · 2026 SNS 트렌드와 AI 마케팅 변화<br>
          · 업종별 채널 선택 &amp; AI 도구 활용법<br>
          · AI를 활용한 SNS 콘텐츠 기획 및 제작<br>
          · 바로 쓰는 AI 팁
        </p>
      </div>
      <table width="100%" cellpadding="0" cellspacing="4">
        <tr>
          <td style="padding:8px 14px;background:#F8FAFC;border-radius:8px;width:50%;">
            <p style="margin:0 0 2px;font-size:10px;color:#94A3B8;font-weight:600;">강사</p>
            <p style="margin:0;font-size:13px;color:#0F172A;font-weight:600;">송윤경 강사</p>
            <p style="margin:0;font-size:11px;color:#6B7280;">소상공인연합회</p>
          </td>
          <td style="padding:8px 14px;background:#F8FAFC;border-radius:8px;width:50%;">
            <p style="margin:0 0 2px;font-size:10px;color:#94A3B8;font-weight:600;">일시</p>
            <p style="margin:0;font-size:13px;color:#0F172A;font-weight:600;">7월 29일(수)</p>
            <p style="margin:0;font-size:11px;color:#6B7280;">14:00 ~ 16:00</p>
          </td>
        </tr>
      </table>
      <p style="margin:10px 0 0;font-size:11px;color:#059669;">※ 줌 링크·교육자료는 다음 주 초 별도 안내드릴 예정입니다.</p>
    </div>
  </div>
  <div style="background:#EFF6FF;padding:20px 28px;border:1px solid #BFDBFE;">
    <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#1D4ED8;letter-spacing:2px;">✅ 신청 방법</p>
    <p style="margin:0 0 14px;font-size:14px;font-weight:600;color:#1E3A5F;">아래 내용을 작성하여, 본 메일에 답장해 주세요</p>
    <div style="background:#fff;border:1px solid #BFDBFE;border-radius:8px;padding:14px 16px;font-size:13px;color:#1E3A5F;line-height:2.4;">
      기업명 : <span style="color:#94A3B8;">____________</span><br>
      담당자명 : <span style="color:#94A3B8;">____________</span><br>
      연락처 : <span style="color:#94A3B8;">____________</span>
    </div>
    <p style="margin:10px 0 0;font-size:11px;color:#3B82F6;">※ 1인 이상 참여 시 참여 인원 정보를 모두 작성해 주세요.</p>
    <div style="margin-top:12px;background:#F59E0B;border-radius:8px;padding:10px 16px;text-align:center;">
      <p style="margin:0;font-size:13px;font-weight:700;color:#0F172A;">📅 신청 마감: 7월 22일(수)까지</p>
    </div>
  </div>
  <div style="background:#fff;padding:16px 28px;border-left:1px solid #E2E8F0;border-right:1px solid #E2E8F0;">
    <div style="border:1px solid #E2E8F0;border-radius:8px;padding:14px 16px;">
      <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#94A3B8;letter-spacing:1.5px;">📢 이런 행사도 있어요</p>
      <p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#0F172A;">CES 혁신상 수상 노하우 공유 밋업</p>
      <p style="margin:0 0 6px;font-size:12px;color:#6B7280;">7월 28일(화) · 오프라인 · 시간·장소 추후 안내</p>
      <p style="margin:0;font-size:12px;color:#475569;line-height:1.6;">CES 혁신상 수상 경험 공유 및 2027 CES 도전 준비 Q&amp;A<br>관심 있으신 기업은 별도 안내 시 참고해 주세요.</p>
    </div>
  </div>
  <div style="background:#fff;padding:0 28px 20px;border-left:1px solid #E2E8F0;border-right:1px solid #E2E8F0;">
    <div style="background:#F8FAFC;border-radius:8px;padding:14px 16px;border:1px solid #E2E8F0;">
      <p style="margin:0 0 10px;font-size:11px;font-weight:700;color:#64748B;letter-spacing:1.5px;">📅 하반기 월별 교육 일정</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <tr style="background:#ECFDF5;"><td style="padding:7px 10px;font-size:12px;font-weight:700;color:#059669;white-space:nowrap;width:45px;">07월</td><td style="padding:7px 10px;font-size:12px;color:#0F172A;font-weight:600;">AI 마케팅 / 콘텐츠 제작 활용 ← 현재</td></tr>
        <tr><td style="padding:7px 10px;font-size:12px;color:#94A3B8;white-space:nowrap;">08월</td><td style="padding:7px 10px;font-size:12px;color:#374151;">디지털 마케팅</td></tr>
        <tr style="background:#F8FAFC;"><td style="padding:7px 10px;font-size:12px;color:#94A3B8;white-space:nowrap;">09월</td><td style="padding:7px 10px;font-size:12px;color:#374151;">네이버 크리에이터 &amp; 비즈니스 플랫폼 활용</td></tr>
        <tr><td style="padding:7px 10px;font-size:12px;color:#94A3B8;white-space:nowrap;">10월</td><td style="padding:7px 10px;font-size:12px;color:#374151;">특허·상표권·디자인권 보호</td></tr>
        <tr style="background:#F8FAFC;"><td style="padding:7px 10px;font-size:12px;color:#94A3B8;white-space:nowrap;">11월</td><td style="padding:7px 10px;font-size:12px;color:#374151;">해외 ODA 시장 진출 및 KOICA 무상원조 참여방안</td></tr>
        <tr><td style="padding:7px 10px;font-size:12px;color:#94A3B8;white-space:nowrap;">12월</td><td style="padding:7px 10px;font-size:12px;color:#374151;">해외 지식재산권 보호 지원사업 및 활용사례</td></tr>
      </table>
      <p style="margin:8px 0 0;font-size:11px;color:#94A3B8;">※ 상기 일정은 내부 사정에 따라 변동될 수 있습니다.</p>
    </div>
  </div>
  <div style="background:#fff;padding:0 28px 20px;border-left:1px solid #E2E8F0;border-right:1px solid #E2E8F0;">
    <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:14px 16px;">
      <p style="margin:0 0 6px;font-size:11px;font-weight:700;color:#64748B;letter-spacing:1px;">📋 저희가 파악한 귀사 정보</p>
      <p style="margin:0 0 4px;font-size:12px;color:#374151;">기술키워드 <span style="font-weight:600;color:#0F172A;">{_co_kw}</span></p>
      <p style="margin:0 0 4px;font-size:12px;color:#374151;">관심분야 <span style="font-weight:600;color:#0F172A;">{_co_area}</span></p>
      <p style="margin:0 0 10px;font-size:12px;color:#374151;">기업유형 <span style="font-weight:600;color:#0F172A;">{_co_type}</span></p>
      <p style="margin:0;font-size:12px;color:#475569;line-height:1.6;">위 정보가 다르거나 추가하고 싶은 내용이 있으시면 이 메일에 답장으로 알려주시면 다음 공고 안내에 반영하겠습니다.</p>
    </div>
  </div>
  <div style="background:#0A1628;border-radius:0 0 14px 14px;padding:14px 28px;text-align:center;border:1px solid #1E3A5F;">
    <p style="margin:0 0 4px;font-size:12px;color:rgba(255,255,255,0.7);">혁신제품지원센터 원스톱 스케일업 · <a href="mailto:onestop.kipcc@gmail.com" style="color:#5DCAA5;text-decoration:none;">onestop.kipcc@gmail.com</a></p>
    <p style="margin:0;font-size:11px;color:rgba(255,255,255,0.5);">본 메일은 원스톱 스케일업 프로그램 참여 시 수신에 동의하신 기업에 발송됩니다.</p>
  </div>
</div>
</body></html>"""
            elif template_choice == "CES 혁신상 밋업 신청 안내":
                _ces_img = "https://raw.githubusercontent.com/onestopkipcc-web/scaleup-matching/main/CES.jpg"
                sample_html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#FAFAF8;font-family:'Apple SD Gothic Neo',Arial,sans-serif;">
<div style="max-width:580px;margin:20px auto;">
  <img src="{_ces_img}" style="width:100%;height:170px;object-fit:cover;display:block;border-radius:14px 14px 0 0;" alt="Las Vegas">
  <div style="background:#0A0A0A;padding:22px 28px 20px;border-left:1px solid #D4AF37;border-right:1px solid #D4AF37;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td valign="top">
        <p style="margin:0 0 8px;font-size:10px;color:#D4AF37;letter-spacing:3px;font-weight:600;">원스톱 스케일업 · 특별 밋업</p>
        <p style="margin:0;font-size:22px;font-weight:800;color:#fff;line-height:1.35;">CES 혁신상 수상<br><span style="color:#D4AF37;">노하우 공유 밋업</span></p>
        <p style="margin:10px 0 0;font-size:12px;color:rgba(255,255,255,0.6);">글로벌 무대를 준비하는 기업을 위한 특별 세션</p>
      </td>
      <td width="70" align="right" valign="top">
        <div style="text-align:center;">
          <p style="margin:0;font-size:26px;font-weight:800;color:#D4AF37;line-height:1;letter-spacing:2px;">CES</p>
          <div style="border-top:1px solid rgba(212,175,55,0.4);margin:5px 0 4px;"></div>
          <p style="margin:0;font-size:6.5px;font-weight:600;color:rgba(212,175,55,0.7);letter-spacing:0.3px;line-height:1.4;">CONSUMER<br>ELECTRONICS SHOW</p>
        </div>
      </td>
    </tr></table>
  </div>
  <div style="background:#fff;border-left:1px solid #EBE6DB;border-right:1px solid #EBE6DB;padding:0 28px;">
    <div style="padding:20px 0 16px;">
      <p style="margin:0;font-size:13px;color:#374151;line-height:1.8;">안녕하세요, 원스톱 스케일업 운영팀입니다.<br>CES 2026(1월 6~9일, 미국 라스베이거스)에서 <b>조달기업 30개사가 혁신상을 수상</b>하며 역대 최다 성과를 거뒀습니다.<br>수상 노하우를 직접 들을 수 있는 밋업에 여러분을 초대합니다.</p>
    </div>
    <div style="padding:0 0 16px;">
      <div style="background:#0A0A0A;border-radius:12px;padding:20px 18px;">
        <table width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="text-align:center;width:33%;padding:0 6px;"><p style="margin:0;font-size:30px;font-weight:800;color:#D4AF37;line-height:1;">30<span style="font-size:13px;font-weight:600;">개사</span></p><p style="margin:6px 0 0;font-size:11px;color:rgba(255,255,255,0.6);font-weight:600;">혁신상 수상</p></td>
          <td style="width:1px;background:rgba(212,175,55,0.3);"></td>
          <td style="text-align:center;width:33%;padding:0 6px;"><p style="margin:0;font-size:30px;font-weight:800;color:#D4AF37;line-height:1;">17<span style="font-size:13px;font-weight:600;">개</span></p><p style="margin:6px 0 0;font-size:11px;color:rgba(255,255,255,0.6);font-weight:600;">AI 융복합 제품</p></td>
          <td style="width:1px;background:rgba(212,175,55,0.3);"></td>
          <td style="text-align:center;width:33%;padding:0 6px;"><p style="margin:0;font-size:23px;font-weight:800;color:#D4AF37;line-height:1.1;">역대최다</p><p style="margin:6px 0 0;font-size:11px;color:rgba(255,255,255,0.6);font-weight:600;">수상 성과</p></td>
        </tr></table>
        <div style="border-top:1px solid rgba(212,175,55,0.25);margin-top:14px;padding-top:12px;"><p style="margin:0;font-size:11px;color:rgba(255,255,255,0.75);line-height:1.7;"><b style="color:#D4AF37;">혁신제품 지정기업</b> 19개사 · <b style="color:#D4AF37;">벤처나라 등록기업</b> 13개사<br>재난·안전 / 자원순환 / 헬스케어 등 공공분야 혁신제품도 국제적 주목</p></div>
      </div>
    </div>
    <div style="padding:0 0 16px;">
      <div style="background:#0A0A0A;border:1px solid #D4AF37;border-radius:12px;overflow:hidden;">
        <div style="padding:18px 20px 16px;">
          <div style="margin-bottom:12px;">
            <span style="background:#D4AF37;color:#0A0A0A;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;">이번 밋업</span>
            <span style="border:1px solid rgba(212,175,55,0.4);color:#D4AF37;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;margin-left:6px;">선정기업 무료</span>
          </div>
          <p style="margin:0;font-size:15px;font-weight:700;color:#fff;">CES 혁신상 수상 노하우 공유</p>
          <table width="100%" cellpadding="0" cellspacing="4" style="margin-top:12px;"><tr>
            <td style="padding:8px 14px;background:rgba(212,175,55,0.08);border:1px solid rgba(212,175,55,0.2);border-radius:8px;width:50%;"><p style="margin:0 0 2px;font-size:10px;color:#D4AF37;font-weight:600;">일시</p><p style="margin:0;font-size:12px;color:#fff;font-weight:600;">7월 28일(화) 14:00~18:30</p><p style="margin:0;font-size:10px;color:rgba(255,255,255,0.5);">17:30부터 네트워킹 디너</p></td>
            <td style="padding:8px 14px;background:rgba(212,175,55,0.08);border:1px solid rgba(212,175,55,0.2);border-radius:8px;width:50%;"><p style="margin:0 0 2px;font-size:10px;color:#D4AF37;font-weight:600;">장소</p><p style="margin:0;font-size:12px;color:#fff;font-weight:600;">MIK BASE CAMP</p><p style="margin:0;font-size:10px;color:rgba(255,255,255,0.5);">서울 서초구 원터6길 1</p></td>
          </tr></table>
        </div>
        <div style="border-top:1px solid rgba(212,175,55,0.25);padding:14px 20px;">
          <p style="margin:0 0 10px;font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;">PROGRAM · 프로그램 구성</p>
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding:0 0 8px;vertical-align:top;width:36px;"><span style="display:inline-block;font-size:10px;font-weight:800;color:#D4AF37;border:1px solid rgba(212,175,55,0.4);border-radius:5px;padding:2px 5px;">1부</span></td><td style="padding:0 0 8px 4px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:600;color:#fff;">CES INSIGHT / INNOVATION AWARDS VALUE</p><p style="margin:1px 0 0;font-size:10px;color:rgba(255,255,255,0.5);">CES 현장 인사이트와 혁신상의 가치</p></td></tr>
            <tr><td style="padding:0 0 8px;vertical-align:top;"><span style="display:inline-block;font-size:10px;font-weight:800;color:#D4AF37;border:1px solid rgba(212,175,55,0.4);border-radius:5px;padding:2px 5px;">2부</span></td><td style="padding:0 0 8px 4px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:600;color:#fff;">혁신상 수상 기업이 전하는 핵심 노하우</p><p style="margin:1px 0 0;font-size:10px;color:rgba(255,255,255,0.5);">실제 수상 기업의 준비 과정과 실전 전략</p></td></tr>
            <tr><td style="padding:0 0 8px;vertical-align:top;"><span style="display:inline-block;font-size:10px;font-weight:800;color:#D4AF37;border:1px solid rgba(212,175,55,0.4);border-radius:5px;padding:2px 5px;">3부</span></td><td style="padding:0 0 8px 4px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:600;color:#fff;">CES INNOVATION AWARD 전문가 토크</p><p style="margin:1px 0 0;font-size:10px;color:rgba(255,255,255,0.5);">혁신상 전문가와 함께하는 Q&amp;A</p></td></tr>
            <tr><td style="vertical-align:top;"><span style="display:inline-block;font-size:10px;font-weight:800;color:#0A0A0A;background:#D4AF37;border-radius:5px;padding:2px 5px;">4부</span></td><td style="padding:0 0 0 4px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:600;color:#fff;">네트워킹 디너 🥂</p><p style="margin:1px 0 0;font-size:10px;color:#E0B84C;">※ 신청자만 참석 · 자부담 비용 5만원 발생</p></td></tr>
          </table>
        </div>
        <div style="border-top:1px solid rgba(212,175,55,0.25);padding:14px 20px;">
          <p style="margin:0 0 10px;font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;">LOCATION · 오시는 길</p>
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding:0 0 8px;vertical-align:top;width:44px;font-size:10px;color:#D4AF37;font-weight:700;">주차</td><td style="padding:0 0 8px;vertical-align:top;font-size:11px;color:rgba(255,255,255,0.9);">청계산근린광장 공영주차장 <span style="color:rgba(255,255,255,0.4);">(서초구 원지동 361-1)</span></td></tr>
            <tr><td style="vertical-align:top;font-size:10px;color:#D4AF37;font-weight:700;">교통</td><td style="vertical-align:top;font-size:11px;color:rgba(255,255,255,0.9);">신분당선 청계산입구역 2번 출구 <span style="color:rgba(255,255,255,0.4);">도보 약 10분 (650m)</span></td></tr>
          </table>
        </div>
      </div>
    </div>
    <div style="padding:0 0 16px;">
      <div style="background:#0A0A0A;border:1px solid #D4AF37;border-radius:12px;padding:18px 20px;">
        <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#D4AF37;letter-spacing:2px;">✅ 참여 신청</p>
        <p style="margin:0 0 12px;font-size:14px;font-weight:600;color:#fff;">아래 내용을 작성하여, 본 메일에 답장해 주세요</p>
        <div style="background:#D4AF37;border-radius:8px;padding:10px 16px;text-align:center;margin-bottom:14px;">
          <p style="margin:0;font-size:13px;font-weight:700;color:#0A0A0A;">📅 신청 마감: 7월 24일(금) 18:00까지</p>
        </div>
        <div style="background:rgba(255,255,255,0.06);border:1px solid rgba(212,175,55,0.2);border-radius:8px;padding:14px 16px;font-size:13px;color:rgba(255,255,255,0.9);line-height:2.4;">
          기업명 : &nbsp;<br>담당자명 : &nbsp;<br>연락처 : &nbsp;
        </div>
        <p style="margin:10px 0 0;font-size:11px;color:rgba(212,175,55,0.7);">※ 1인 이상 참여 시 참여 인원 정보를 모두 작성해 주세요.</p>
      </div>
    </div>
    <div style="padding:0 0 16px;">
      <div style="background:#FAF8F2;border:1px solid #EBE6DB;border-radius:12px;padding:18px;">
        <p style="margin:0 0 14px;font-size:11px;font-weight:700;color:#9A7B1F;letter-spacing:1.5px;">🗓️ 하반기 글로벌 진출 밋업 시리즈</p>
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td style="padding:0 0 10px;vertical-align:top;width:52px;"><div style="background:#0A0A0A;border:1px solid #D4AF37;border-radius:8px;padding:8px 6px;text-align:center;min-width:36px;"><p style="margin:0;font-size:12px;font-weight:800;color:#D4AF37;line-height:1;">7월</p></div></td><td style="padding:0 0 10px 12px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:700;color:#0F172A;">CES 혁신상 수상 노하우 공유 밋업</p><p style="margin:2px 0 0;font-size:11px;color:#9A7B1F;font-weight:600;">7월 28일(화) · 진행 예정</p></td></tr>
          <tr><td style="padding:0 0 10px;vertical-align:top;"><div style="background:#292524;border-radius:8px;padding:8px 6px;text-align:center;min-width:36px;"><p style="margin:0;font-size:12px;font-weight:800;color:#D4AF37;line-height:1;">11월</p></div></td><td style="padding:0 0 10px 12px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:700;color:#0F172A;">글로벌 전시회 참가 전략 밋업 ①</p><p style="margin:2px 0 0;font-size:11px;color:#A8A29E;">일정 추후 안내</p></td></tr>
          <tr><td style="padding:0 0 10px;vertical-align:top;"><div style="background:#292524;border-radius:8px;padding:8px 6px;text-align:center;min-width:36px;"><p style="margin:0;font-size:12px;font-weight:800;color:#D4AF37;line-height:1;">12월</p></div></td><td style="padding:0 0 10px 12px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:700;color:#0F172A;">글로벌 전시회 참가 전략 밋업 ②</p><p style="margin:2px 0 0;font-size:11px;color:#A8A29E;">일정 추후 안내</p></td></tr>
          <tr><td style="vertical-align:top;"><div style="background:#D4AF37;border-radius:8px;padding:8px 6px;text-align:center;min-width:36px;"><p style="margin:0;font-size:12px;font-weight:800;color:#0A0A0A;line-height:1;">12월</p></div></td><td style="padding:0 0 0 12px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:700;color:#0F172A;">CES 2027 수상기업 네트워킹 파티 🥂</p><p style="margin:2px 0 0;font-size:11px;color:#A8A29E;">일정 추후 안내</p></td></tr>
        </table>
        <p style="margin:12px 0 0;font-size:11px;color:#A8A29E;">※ 상기 일정과 프로그램은 내부 사정에 따라 변경될 수 있습니다.</p>
      </div>
    </div>
    <div style="padding:0 0 20px;">
      <div style="background:#FAFAF9;border:1px solid #E7E5E4;border-radius:12px;padding:18px;">
        <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#57534E;letter-spacing:1.5px;">🎯 CES 2027 혁신상 도전 안내</p>
        <p style="margin:0 0 14px;font-size:12px;color:#78716C;line-height:1.6;">이번 밋업에서 CES 2027 혁신상 도전을 함께 준비해보세요.</p>
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #E7E5E4;border-radius:8px;overflow:hidden;">
          <tr style="background:#fff;"><td style="padding:9px 14px;font-size:11px;color:#57534E;font-weight:700;white-space:nowrap;width:80px;border-bottom:1px solid #F5F5F4;">신청 접수</td><td style="padding:9px 14px;font-size:12px;color:#0F172A;border-bottom:1px solid #F5F5F4;">2026. 6. 5.(금) ~ 8. 19.(수)</td></tr>
          <tr style="background:#fff;"><td style="padding:9px 14px;font-size:11px;color:#57534E;font-weight:700;white-space:nowrap;border-bottom:1px solid #F5F5F4;">결과 통보</td><td style="padding:9px 14px;font-size:12px;color:#0F172A;border-bottom:1px solid #F5F5F4;">2026. 11. 2.(월)</td></tr>
          <tr style="background:#fff;"><td style="padding:9px 14px;font-size:11px;color:#57534E;font-weight:700;white-space:nowrap;border-bottom:1px solid #F5F5F4;">수상 발표</td><td style="padding:9px 14px;font-size:12px;color:#0F172A;border-bottom:1px solid #F5F5F4;">2026. 11. 9.(월)</td></tr>
          <tr style="background:#fff;"><td style="padding:9px 14px;font-size:11px;color:#57534E;font-weight:700;white-space:nowrap;">출시 조건</td><td style="padding:9px 14px;font-size:12px;color:#0F172A;">2026.4.1 ~ 2027.3.31 최초 출시 제품</td></tr>
        </table>
        <p style="margin:12px 0 14px;font-size:11px;color:#78716C;line-height:1.7;">· 제품 1개당 최대 4개 카테고리 출품 가능<br>· CES 전시 참가 없이도 혁신상 신청 가능</p>
        <a href="https://cta.secure-platform.com/ces-awards" style="display:block;background:#0A0A0A;color:#D4AF37;text-align:center;padding:12px;border-radius:8px;text-decoration:none;font-size:13px;font-weight:700;border:1px solid #D4AF37;">CES 2027 혁신상 신청 바로가기 →</a>
      </div>
    </div>
  </div>
  <div style="background:#0A0A0A;border-radius:0 0 14px 14px;padding:16px 28px;text-align:center;border:1px solid #D4AF37;">
    <p style="margin:0 0 6px;font-size:10px;color:#D4AF37;letter-spacing:3px;font-weight:700;">WITH AVING NEWS</p>
    <p style="margin:0 0 4px;font-size:12px;color:rgba(255,255,255,0.7);">혁신제품지원센터 원스톱 스케일업 · <a href="mailto:onestop.kipcc@gmail.com" style="color:#5DCAA5;text-decoration:none;">onestop.kipcc@gmail.com</a></p>
    <p style="margin:0;font-size:11px;color:rgba(255,255,255,0.45);">본 메일은 원스톱 스케일업 프로그램 참여 시 수신에 동의하신 기업에 발송됩니다.</p>
  </div>
</div>
</body></html>"""
            else:
                sample_html = f"""<!DOCTYPE html>
    <html lang="ko">
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background:#F2F4F7;
                 font-family:'Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#F2F4F7;padding:36px 0 52px;">
    <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0">
      <tr>
        <td style="background:#ffffff;border-radius:14px 14px 0 0;
                   padding:20px 28px;border-bottom:1px solid #E8ECF0;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td valign="middle">
                <span style="font-size:15px;font-weight:700;color:#1F4E79;">혁신제품지원센터</span>
              </td>
              <td align="right" valign="middle">
                <p style="margin:0;font-size:11px;color:#A0ADB8;">{today_str}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td style="background:#0F1D2E;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="padding:28px 28px 20px;
                         background:#101F33;
                         border-bottom:1px solid rgba(255,255,255,0.06);">
                <p style="margin:0 0 2px;font-size:10px;font-weight:700;letter-spacing:2.5px;
                           color:rgba(255,255,255,0.3);text-transform:uppercase;">
                  원스톱 스케일업 안내
                </p>
                <h1 style="margin:6px 0 0;font-size:22px;font-weight:800;color:#FFFFFF;line-height:1.3;">
                  {mail_subject}
                </h1>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 28px;background:#0F1D2E;">
                <div style="padding:14px 18px;background:rgba(255,255,255,0.05);
                            border-radius:8px;border-left:3px solid #10B981;margin-bottom:20px;">
                  <p style="margin:0;font-size:14px;font-weight:600;color:#FFFFFF;">
                    {sample_company}
                    <span style="font-size:13px;font-weight:400;color:rgba(255,255,255,0.45);margin-left:4px;">담당자님</span>
                  </p>
                </div>
                <div style="font-size:13px;color:rgba(255,255,255,0.75);line-height:1.9;">
                  {body_html}
                </div>
                {form_section}
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td style="background:#ffffff;border-radius:0 0 14px 14px;
                   padding:18px 28px;border-top:1px solid #E8ECF0;">
          <p style="margin:0;font-size:12px;color:#A8BDD1;line-height:1.9;">
            혁신제품지원센터 원스톱 스케일업 운영팀<br>
            <a href="mailto:onestop.kipcc@gmail.com"
               style="color:#5DCAA5;text-decoration:none;font-weight:600;">
              onestop.kipcc@gmail.com
            </a>
          </p>
        </td>
      </tr>
    </table>
    </td></tr></table>
    </body></html>"""

            with st.expander(f"📧 미리보기 — {sample_company}", expanded=True):
                st.components.v1.html(sample_html, height=500, scrolling=True)

            st.divider()
            st.subheader("④ 발송 실행")

            # 직접 작성 모드 - 단건 발송용 이메일 입력 (이전 코드 제거)
            direct_email = None

            c1, c2 = st.columns(2)
            with c1:
                if target_group == "이메일 직접 입력" and direct_input_email:
                    st.info(f"**발송 대상:** {direct_input_email} (단건)")
                else:
                    st.info(f"**발송 대상:** {target_group if has_status else '전체'} ({len(df_target)}개사)")
            with c2:
                if target_group != "이메일 직접 입력" and not df_target.empty:
                    no_email = df_target[df_target['이메일'].str.strip() == '']
                    if not no_email.empty:
                        st.warning(f"이메일 없는 기업 {len(no_email)}개사는 발송 제외됩니다.")

            # ── 첨부파일 + 기업 키워드 옵션 ──────────────
            opt1, opt2 = st.columns(2)
            with opt1:
                attach_file = st.file_uploader(
                    "📎 첨부파일 (선택)",
                    type=["pdf", "docx", "xlsx", "hwp"],
                    help="공고문 등 첨부할 파일을 선택하세요. 전체 기업에게 동일하게 첨부됩니다."
                )
                if attach_file:
                    st.caption(f"✅ {attach_file.name} ({attach_file.size//1024}KB)")
            with opt2:
                insert_kw = st.checkbox(
                    "📊 기업별 키워드 본문 삽입",
                    value=True,
                    help="각 기업의 관심분야·기술키워드를 메일 본문에 자동 삽입합니다."
                )
                if insert_kw:
                    st.caption("관심분야 / 기술키워드 / 기업유형이 메일에 표시됩니다.")

            if test_mode:
                st.warning("⚠️ 테스트 모드 — 본인 메일로만 발송됩니다.")

            if st.button("📤 안내 메일 발송", type="primary", key="notice_mail_send"):
                from email.mime.multipart import MIMEMultipart
                from email.mime.text import MIMEText
                from email.mime.base import MIMEBase
                from email import encoders
                import base64

                # 첨부파일 미리 읽기
                attach_data = None
                attach_name = None
                if attach_file:
                    attach_data = attach_file.read()
                    attach_name = attach_file.name

                df_send = df_target[df_target['이메일'].str.strip() != ''] if not df_target.empty else df_target

                # 이메일 직접 입력 모드 단건 발송
                if target_group == "이메일 직접 입력" and direct_input_email and direct_input_email.strip():
                    import pandas as _pd_direct
                    df_send = _pd_direct.DataFrame([{
                        '기업명': '테스트',
                        '이메일': direct_input_email.strip(),
                        '담당자': '',
                        '선정구분': '선정'
                    }])

                prog = st.progress(0); log_area = st.empty(); logs = []
                ok_count = fail_count = 0

                for i, (_, row) in enumerate(df_send.iterrows()):
                    company  = row['기업명']
                    to_email  = row['이메일'].strip() if not test_mode else get_test_recipients()[0]
                    # 추가 수신자(수신이메일2/3) → Cc
                    cc_list = []
                    if not test_mode:
                        for _c in ('수신이메일2', '수신이메일3'):
                            _v = str(row.get(_c, '') or '').strip()
                            if _v and '@' in _v and _v.lower() != to_email.lower() \
                               and _v.lower() not in [x.lower() for x in cc_list]:
                                cc_list.append(_v)
                    today_str = datetime.today().strftime('%Y.%m.%d')

                    # 기업별 키워드 섹션 생성
                    kw_section_html = ""
                    kw_section_text = ""
                    if insert_kw:
                        co_interest = str(row.get('관심사업분야', '') or row.get('관심분야', '') or '')
                        co_keywords = str(row.get('기술키워드', '') or '')
                        co_biztype  = str(row.get('기업유형', '') or '')
                        co_kw_extra = str(row.get('키워드보완', '') or '')
                        if any([co_interest, co_keywords, co_biztype]):
                            kw_section_html = f"""
                        <div style="background:#0A1A0F;border:1px solid #BBF7D0;
                                    border-left:4px solid #10B981;border-radius:8px;
                                    padding:16px 18px;margin:16px 0;">
                          <p style="margin:0 0 10px;font-size:11px;font-weight:700;
                                    color:#059669;letter-spacing:1px;">
                            📊 저희가 파악한 귀사 정보
                          </p>
                          {'<p style="margin:4px 0;font-size:13px;color:#F0F0F0;"><b>관심분야:</b> ' + co_interest + '</p>' if co_interest else ''}
                          {'<p style="margin:4px 0;font-size:13px;color:#F0F0F0;"><b>기술키워드:</b> ' + co_keywords + '</p>' if co_keywords else ''}
                          {'<p style="margin:4px 0;font-size:13px;color:#F0F0F0;"><b>기업유형:</b> ' + co_biztype + '</p>' if co_biztype else ''}
                          {'<p style="margin:4px 0;font-size:13px;color:#F0F0F0;"><b>추가 키워드:</b> ' + co_kw_extra + '</p>' if co_kw_extra else ''}
                          <p style="margin:10px 0 0;font-size:12px;color:#888888;">
                            위 정보를 기반으로 맞춤 공고를 선별하고 있습니다.<br>
                            다르거나 추가하고 싶은 내용은 Q1, Q2 답변에 자유롭게 적어주세요.
                          </p>
                        </div>"""
                            kw_section_text = f"""
─────────────────────────────────
▣ 저희가 파악한 귀사 정보
─────────────────────────────────
{'관심분야: ' + co_interest if co_interest else ''}
{'기술키워드: ' + co_keywords if co_keywords else ''}
{'기업유형: ' + co_biztype if co_biztype else ''}

위 정보를 기반으로 맞춤 공고를 선별하고 있습니다.
다르거나 추가하고 싶은 내용은 Q1, Q2 답변에 자유롭게 적어주세요.
"""

                    # HTML 본문 생성
                    body_html_co = ""
                    if template_choice == "함께하기 회원소개 가입 안내":
                        html_body = build_together_html(
                            company=str(row.get('기업명','')), 담당자='')
                    elif template_choice in ("10월 교육 신청 안내", "10월 교육 리마인더 (미신청 대상)"):
                        html_body = build_oct_edu_html(company=str(row.get('기업명','')),
                            is_reminder=(template_choice == "10월 교육 리마인더 (미신청 대상)"))
                    elif template_choice in ("9월 교육 신청 안내", "9월 교육 리마인더 (미신청 대상)"):
                        html_body = build_sep_edu_html(company=str(row.get('기업명','')),
                            is_reminder=(template_choice == "9월 교육 리마인더 (미신청 대상)"))
                    elif template_choice == "8월 교육 리마인더 (미신청 대상)":
                        _co_kw   = str(row.get('기술키워드','') or row.get('키워드보완','') or '')[:40]
                        _co_area = str(row.get('관심사업분야','') or '')
                        _co_type = str(row.get('기업유형','') or '')[:30]
                        html_body = build_aug_edu_html(company=str(row.get('기업명','')),
                            co_kw=_co_kw, co_area=_co_area, co_type=_co_type, is_reminder=True)
                    elif template_choice == "7월 교육 프로그램 신청 안내":
                        _co_kw   = str(row.get('기술키워드','') or row.get('키워드보완','') or '—')[:40]
                        _co_area = str(row.get('관심사업분야','') or '—')
                        _co_type = str(row.get('기업유형','') or '—')[:30]
                        html_body = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F2F4F7;font-family:'Apple SD Gothic Neo',Arial,sans-serif;">
<div style="max-width:580px;margin:32px auto;">
  <div style="background:#0F1D2E;border-radius:14px 14px 0 0;padding:24px 28px 20px;border:1px solid #1E3A5F;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td valign="top">
        <p style="margin:0 0 2px;font-size:10px;color:rgba(255,255,255,0.4);letter-spacing:2px;">원스톱 스케일업 · 혁신제품지원센터</p>
        <p style="margin:0;font-size:20px;font-weight:700;color:#fff;">7월 교육 프로그램 신청 안내</p>
        <p style="margin:4px 0 0;font-size:12px;color:#9FD6C0;">신청 기간 ~ 7월 22일(수)</p>
      </td>
      <td width="64" align="right" valign="top">
        <div style="background:#F59E0B;border-radius:10px;padding:8px 10px;text-align:center;min-width:48px;">
          <p style="margin:0;font-size:18px;font-weight:800;color:#0F172A;line-height:1;">⏰</p>
          <p style="margin:3px 0 0;font-size:9px;font-weight:700;color:#0F172A;letter-spacing:0.5px;">마감임박</p>
        </div>
      </td>
    </tr></table>
  </div>
  <div style="background:#fff;padding:20px 28px 16px;border-left:1px solid #E2E8F0;border-right:1px solid #E2E8F0;">
    <p style="margin:0;font-size:13px;color:#374151;line-height:1.8;">
      안녕하세요, 원스톱 스케일업 운영팀입니다.<br>
      선정 기업 여러분께 제공되는 <b>7월 교육 프로그램</b>을 안내드립니다.<br>
      부담 없이 참여하실 수 있으며, 실무에 바로 적용할 수 있는 내용으로 준비했습니다.<br>
      많은 관심과 참여 부탁드립니다.
    </p>
  </div>
  <div style="background:#fff;padding:0 28px 20px;border-left:1px solid #E2E8F0;border-right:1px solid #E2E8F0;">
    <div style="background:#F0FDF4;border:1.5px solid #10B981;border-radius:10px;padding:18px 20px;">
      <div style="margin-bottom:12px;">
        <span style="background:#10B981;color:#fff;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;">7월 정기 교육</span>
        <span style="background:#ECFDF5;color:#059669;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;margin-left:6px;">선정기업 무료 제공</span>
        <span style="font-size:11px;color:#6B7280;margin-left:6px;">온라인 (Zoom)</span>
      </div>
      <p style="margin:0 0 4px;font-size:16px;font-weight:700;color:#0F172A;">AI 마케팅 / 콘텐츠 제작 활용</p>
      <div style="margin:6px 0 12px;padding:10px 14px;background:#fff;border-radius:8px;border-left:3px solid #10B981;">
        <p style="margin:0;font-size:12px;color:#374151;line-height:1.8;">
          · 2026 SNS 트렌드와 AI 마케팅 변화<br>
          · 업종별 채널 선택 &amp; AI 도구 활용법<br>
          · AI를 활용한 SNS 콘텐츠 기획 및 제작<br>
          · 바로 쓰는 AI 팁
        </p>
      </div>
      <table width="100%" cellpadding="0" cellspacing="4">
        <tr>
          <td style="padding:8px 14px;background:#F8FAFC;border-radius:8px;width:50%;">
            <p style="margin:0 0 2px;font-size:10px;color:#94A3B8;font-weight:600;">강사</p>
            <p style="margin:0;font-size:13px;color:#0F172A;font-weight:600;">송윤경 강사</p>
            <p style="margin:0;font-size:11px;color:#6B7280;">소상공인연합회</p>
          </td>
          <td style="padding:8px 14px;background:#F8FAFC;border-radius:8px;width:50%;">
            <p style="margin:0 0 2px;font-size:10px;color:#94A3B8;font-weight:600;">일시</p>
            <p style="margin:0;font-size:13px;color:#0F172A;font-weight:600;">7월 29일(수)</p>
            <p style="margin:0;font-size:11px;color:#6B7280;">14:00 ~ 16:00</p>
          </td>
        </tr>
      </table>
      <p style="margin:10px 0 0;font-size:11px;color:#059669;">※ 줌 링크·교육자료는 다음 주 초 별도 안내드릴 예정입니다.</p>
    </div>
  </div>
  <div style="background:#EFF6FF;padding:20px 28px;border:1px solid #BFDBFE;">
    <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#1D4ED8;letter-spacing:2px;">✅ 신청 방법</p>
    <p style="margin:0 0 14px;font-size:14px;font-weight:600;color:#1E3A5F;">아래 내용을 작성하여, 본 메일에 답장해 주세요</p>
    <div style="background:#fff;border:1px solid #BFDBFE;border-radius:8px;padding:14px 16px;font-size:13px;color:#1E3A5F;line-height:2.4;">
      기업명 : &nbsp;<br>
      담당자명 : &nbsp;<br>
      연락처 : &nbsp;
    </div>
    <p style="margin:10px 0 0;font-size:11px;color:#3B82F6;">※ 1인 이상 참여 시 참여 인원 정보를 모두 작성해 주세요.</p>
    <div style="margin-top:12px;background:#F59E0B;border-radius:8px;padding:10px 16px;text-align:center;">
      <p style="margin:0;font-size:13px;font-weight:700;color:#0F172A;">📅 신청 마감: 7월 22일(수)까지</p>
    </div>
  </div>
  <div style="background:#fff;padding:16px 28px;border-left:1px solid #E2E8F0;border-right:1px solid #E2E8F0;">
    <div style="border:1px solid #E2E8F0;border-radius:8px;padding:14px 16px;">
      <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#94A3B8;letter-spacing:1.5px;">📢 이런 행사도 있어요</p>
      <p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#0F172A;">CES 혁신상 수상 노하우 공유 밋업</p>
      <p style="margin:0 0 6px;font-size:12px;color:#6B7280;">7월 28일(화) · 오프라인 · 시간·장소 추후 안내</p>
      <p style="margin:0;font-size:12px;color:#475569;line-height:1.6;">CES 혁신상 수상 경험 공유 및 2027 CES 도전 준비 Q&amp;A<br>관심 있으신 기업은 별도 안내 시 참고해 주세요.</p>
    </div>
  </div>
  <div style="background:#fff;padding:0 28px 20px;border-left:1px solid #E2E8F0;border-right:1px solid #E2E8F0;">
    <div style="background:#F8FAFC;border-radius:8px;padding:14px 16px;border:1px solid #E2E8F0;">
      <p style="margin:0 0 10px;font-size:11px;font-weight:700;color:#64748B;letter-spacing:1.5px;">📅 하반기 월별 교육 일정</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <tr style="background:#ECFDF5;"><td style="padding:7px 10px;font-size:12px;font-weight:700;color:#059669;white-space:nowrap;width:45px;">07월</td><td style="padding:7px 10px;font-size:12px;color:#0F172A;font-weight:600;">AI 마케팅 / 콘텐츠 제작 활용 ← 현재</td></tr>
        <tr><td style="padding:7px 10px;font-size:12px;color:#94A3B8;white-space:nowrap;">08월</td><td style="padding:7px 10px;font-size:12px;color:#374151;">디지털 마케팅</td></tr>
        <tr style="background:#F8FAFC;"><td style="padding:7px 10px;font-size:12px;color:#94A3B8;white-space:nowrap;">09월</td><td style="padding:7px 10px;font-size:12px;color:#374151;">네이버 크리에이터 &amp; 비즈니스 플랫폼 활용</td></tr>
        <tr><td style="padding:7px 10px;font-size:12px;color:#94A3B8;white-space:nowrap;">10월</td><td style="padding:7px 10px;font-size:12px;color:#374151;">특허·상표권·디자인권 보호</td></tr>
        <tr style="background:#F8FAFC;"><td style="padding:7px 10px;font-size:12px;color:#94A3B8;white-space:nowrap;">11월</td><td style="padding:7px 10px;font-size:12px;color:#374151;">해외 ODA 시장 진출 및 KOICA 무상원조 참여방안</td></tr>
        <tr><td style="padding:7px 10px;font-size:12px;color:#94A3B8;white-space:nowrap;">12월</td><td style="padding:7px 10px;font-size:12px;color:#374151;">해외 지식재산권 보호 지원사업 및 활용사례</td></tr>
      </table>
      <p style="margin:8px 0 0;font-size:11px;color:#94A3B8;">※ 상기 일정은 내부 사정에 따라 변동될 수 있습니다.</p>
    </div>
  </div>
  <div style="background:#fff;padding:0 28px 20px;border-left:1px solid #E2E8F0;border-right:1px solid #E2E8F0;">
    <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:14px 16px;">
      <p style="margin:0 0 6px;font-size:11px;font-weight:700;color:#64748B;letter-spacing:1px;">📋 저희가 파악한 귀사 정보</p>
      <p style="margin:0 0 4px;font-size:12px;color:#374151;">기술키워드 <span style="font-weight:600;color:#0F172A;">{_co_kw}</span></p>
      <p style="margin:0 0 4px;font-size:12px;color:#374151;">관심분야 <span style="font-weight:600;color:#0F172A;">{_co_area}</span></p>
      <p style="margin:0 0 10px;font-size:12px;color:#374151;">기업유형 <span style="font-weight:600;color:#0F172A;">{_co_type}</span></p>
      <p style="margin:0;font-size:12px;color:#475569;line-height:1.6;">위 정보가 다르거나 추가하고 싶은 내용이 있으시면 이 메일에 답장으로 알려주시면 다음 공고 안내에 반영하겠습니다.</p>
    </div>
  </div>
  <div style="background:#0A1628;border-radius:0 0 14px 14px;padding:14px 28px;text-align:center;border:1px solid #1E3A5F;">
    <p style="margin:0 0 4px;font-size:12px;color:rgba(255,255,255,0.7);">혁신제품지원센터 원스톱 스케일업 · <a href="mailto:onestop.kipcc@gmail.com" style="color:#5DCAA5;text-decoration:none;">onestop.kipcc@gmail.com</a></p>
    <p style="margin:0;font-size:11px;color:rgba(255,255,255,0.5);">본 메일은 원스톱 스케일업 프로그램 참여 시 수신에 동의하신 기업에 발송됩니다.</p>
  </div>
</div>
</body></html>"""
                        body_html_co = mail_body.replace('\n', '<br>')
                    elif template_choice == "CES 혁신상 밋업 신청 안내":
                        _ces_img = "https://raw.githubusercontent.com/onestopkipcc-web/scaleup-matching/main/CES.jpg"
                        html_body = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#FAFAF8;font-family:'Apple SD Gothic Neo',Arial,sans-serif;">
<div style="max-width:580px;margin:20px auto;">
  <img src="{_ces_img}" style="width:100%;height:170px;object-fit:cover;display:block;border-radius:14px 14px 0 0;" alt="Las Vegas">
  <div style="background:#0A0A0A;padding:22px 28px 20px;border-left:1px solid #D4AF37;border-right:1px solid #D4AF37;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td valign="top">
        <p style="margin:0 0 8px;font-size:10px;color:#D4AF37;letter-spacing:3px;font-weight:600;">원스톱 스케일업 · 특별 밋업</p>
        <p style="margin:0;font-size:22px;font-weight:800;color:#fff;line-height:1.35;">CES 혁신상 수상<br><span style="color:#D4AF37;">노하우 공유 밋업</span></p>
        <p style="margin:10px 0 0;font-size:12px;color:rgba(255,255,255,0.6);">글로벌 무대를 준비하는 기업을 위한 특별 세션</p>
      </td>
      <td width="70" align="right" valign="top">
        <div style="text-align:center;">
          <p style="margin:0;font-size:26px;font-weight:800;color:#D4AF37;line-height:1;letter-spacing:2px;">CES</p>
          <div style="border-top:1px solid rgba(212,175,55,0.4);margin:5px 0 4px;"></div>
          <p style="margin:0;font-size:6.5px;font-weight:600;color:rgba(212,175,55,0.7);letter-spacing:0.3px;line-height:1.4;">CONSUMER<br>ELECTRONICS SHOW</p>
        </div>
      </td>
    </tr></table>
  </div>
  <div style="background:#fff;border-left:1px solid #EBE6DB;border-right:1px solid #EBE6DB;padding:0 28px;">
    <div style="padding:20px 0 16px;">
      <p style="margin:0;font-size:13px;color:#374151;line-height:1.8;">안녕하세요, 원스톱 스케일업 운영팀입니다.<br>CES 2026(1월 6~9일, 미국 라스베이거스)에서 <b>조달기업 30개사가 혁신상을 수상</b>하며 역대 최다 성과를 거뒀습니다.<br>수상 노하우를 직접 들을 수 있는 밋업에 여러분을 초대합니다.</p>
    </div>
    <div style="padding:0 0 16px;">
      <div style="background:#0A0A0A;border-radius:12px;padding:20px 18px;">
        <table width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="text-align:center;width:33%;padding:0 6px;"><p style="margin:0;font-size:30px;font-weight:800;color:#D4AF37;line-height:1;">30<span style="font-size:13px;font-weight:600;">개사</span></p><p style="margin:6px 0 0;font-size:11px;color:rgba(255,255,255,0.6);font-weight:600;">혁신상 수상</p></td>
          <td style="width:1px;background:rgba(212,175,55,0.3);"></td>
          <td style="text-align:center;width:33%;padding:0 6px;"><p style="margin:0;font-size:30px;font-weight:800;color:#D4AF37;line-height:1;">17<span style="font-size:13px;font-weight:600;">개</span></p><p style="margin:6px 0 0;font-size:11px;color:rgba(255,255,255,0.6);font-weight:600;">AI 융복합 제품</p></td>
          <td style="width:1px;background:rgba(212,175,55,0.3);"></td>
          <td style="text-align:center;width:33%;padding:0 6px;"><p style="margin:0;font-size:23px;font-weight:800;color:#D4AF37;line-height:1.1;">역대최다</p><p style="margin:6px 0 0;font-size:11px;color:rgba(255,255,255,0.6);font-weight:600;">수상 성과</p></td>
        </tr></table>
        <div style="border-top:1px solid rgba(212,175,55,0.25);margin-top:14px;padding-top:12px;"><p style="margin:0;font-size:11px;color:rgba(255,255,255,0.75);line-height:1.7;"><b style="color:#D4AF37;">혁신제품 지정기업</b> 19개사 · <b style="color:#D4AF37;">벤처나라 등록기업</b> 13개사<br>재난·안전 / 자원순환 / 헬스케어 등 공공분야 혁신제품도 국제적 주목</p></div>
      </div>
    </div>
    <div style="padding:0 0 16px;">
      <div style="background:#0A0A0A;border:1px solid #D4AF37;border-radius:12px;overflow:hidden;">
        <div style="padding:18px 20px 16px;">
          <div style="margin-bottom:12px;">
            <span style="background:#D4AF37;color:#0A0A0A;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;">이번 밋업</span>
            <span style="border:1px solid rgba(212,175,55,0.4);color:#D4AF37;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;margin-left:6px;">선정기업 무료</span>
          </div>
          <p style="margin:0;font-size:15px;font-weight:700;color:#fff;">CES 혁신상 수상 노하우 공유</p>
          <table width="100%" cellpadding="0" cellspacing="4" style="margin-top:12px;"><tr>
            <td style="padding:8px 14px;background:rgba(212,175,55,0.08);border:1px solid rgba(212,175,55,0.2);border-radius:8px;width:50%;"><p style="margin:0 0 2px;font-size:10px;color:#D4AF37;font-weight:600;">일시</p><p style="margin:0;font-size:12px;color:#fff;font-weight:600;">7월 28일(화) 14:00~18:30</p><p style="margin:0;font-size:10px;color:rgba(255,255,255,0.5);">17:30부터 네트워킹 디너</p></td>
            <td style="padding:8px 14px;background:rgba(212,175,55,0.08);border:1px solid rgba(212,175,55,0.2);border-radius:8px;width:50%;"><p style="margin:0 0 2px;font-size:10px;color:#D4AF37;font-weight:600;">장소</p><p style="margin:0;font-size:12px;color:#fff;font-weight:600;">MIK BASE CAMP</p><p style="margin:0;font-size:10px;color:rgba(255,255,255,0.5);">서울 서초구 원터6길 1</p></td>
          </tr></table>
        </div>
        <div style="border-top:1px solid rgba(212,175,55,0.25);padding:14px 20px;">
          <p style="margin:0 0 10px;font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;">PROGRAM · 프로그램 구성</p>
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding:0 0 8px;vertical-align:top;width:36px;"><span style="display:inline-block;font-size:10px;font-weight:800;color:#D4AF37;border:1px solid rgba(212,175,55,0.4);border-radius:5px;padding:2px 5px;">1부</span></td><td style="padding:0 0 8px 4px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:600;color:#fff;">CES INSIGHT / INNOVATION AWARDS VALUE</p><p style="margin:1px 0 0;font-size:10px;color:rgba(255,255,255,0.5);">CES 현장 인사이트와 혁신상의 가치</p></td></tr>
            <tr><td style="padding:0 0 8px;vertical-align:top;"><span style="display:inline-block;font-size:10px;font-weight:800;color:#D4AF37;border:1px solid rgba(212,175,55,0.4);border-radius:5px;padding:2px 5px;">2부</span></td><td style="padding:0 0 8px 4px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:600;color:#fff;">혁신상 수상 기업이 전하는 핵심 노하우</p><p style="margin:1px 0 0;font-size:10px;color:rgba(255,255,255,0.5);">실제 수상 기업의 준비 과정과 실전 전략</p></td></tr>
            <tr><td style="padding:0 0 8px;vertical-align:top;"><span style="display:inline-block;font-size:10px;font-weight:800;color:#D4AF37;border:1px solid rgba(212,175,55,0.4);border-radius:5px;padding:2px 5px;">3부</span></td><td style="padding:0 0 8px 4px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:600;color:#fff;">CES INNOVATION AWARD 전문가 토크</p><p style="margin:1px 0 0;font-size:10px;color:rgba(255,255,255,0.5);">혁신상 전문가와 함께하는 Q&amp;A</p></td></tr>
            <tr><td style="vertical-align:top;"><span style="display:inline-block;font-size:10px;font-weight:800;color:#0A0A0A;background:#D4AF37;border-radius:5px;padding:2px 5px;">4부</span></td><td style="padding:0 0 0 4px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:600;color:#fff;">네트워킹 디너 🥂</p><p style="margin:1px 0 0;font-size:10px;color:#E0B84C;">※ 신청자만 참석 · 자부담 비용 5만원 발생</p></td></tr>
          </table>
        </div>
        <div style="border-top:1px solid rgba(212,175,55,0.25);padding:14px 20px;">
          <p style="margin:0 0 10px;font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;">LOCATION · 오시는 길</p>
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding:0 0 8px;vertical-align:top;width:44px;font-size:10px;color:#D4AF37;font-weight:700;">주차</td><td style="padding:0 0 8px;vertical-align:top;font-size:11px;color:rgba(255,255,255,0.9);">청계산근린광장 공영주차장 <span style="color:rgba(255,255,255,0.4);">(서초구 원지동 361-1)</span></td></tr>
            <tr><td style="vertical-align:top;font-size:10px;color:#D4AF37;font-weight:700;">교통</td><td style="vertical-align:top;font-size:11px;color:rgba(255,255,255,0.9);">신분당선 청계산입구역 2번 출구 <span style="color:rgba(255,255,255,0.4);">도보 약 10분 (650m)</span></td></tr>
          </table>
        </div>
      </div>
    </div>
    <div style="padding:0 0 16px;">
      <div style="background:#0A0A0A;border:1px solid #D4AF37;border-radius:12px;padding:18px 20px;">
        <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#D4AF37;letter-spacing:2px;">✅ 참여 신청</p>
        <p style="margin:0 0 12px;font-size:14px;font-weight:600;color:#fff;">아래 내용을 작성하여, 본 메일에 답장해 주세요</p>
        <div style="background:#D4AF37;border-radius:8px;padding:10px 16px;text-align:center;margin-bottom:14px;">
          <p style="margin:0;font-size:13px;font-weight:700;color:#0A0A0A;">📅 신청 마감: 7월 24일(금) 18:00까지</p>
        </div>
        <div style="background:rgba(255,255,255,0.06);border:1px solid rgba(212,175,55,0.2);border-radius:8px;padding:14px 16px;font-size:13px;color:rgba(255,255,255,0.9);line-height:2.4;">
          기업명 : &nbsp;<br>담당자명 : &nbsp;<br>연락처 : &nbsp;
        </div>
        <p style="margin:10px 0 0;font-size:11px;color:rgba(212,175,55,0.7);">※ 1인 이상 참여 시 참여 인원 정보를 모두 작성해 주세요.</p>
      </div>
    </div>
    <div style="padding:0 0 16px;">
      <div style="background:#FAF8F2;border:1px solid #EBE6DB;border-radius:12px;padding:18px;">
        <p style="margin:0 0 14px;font-size:11px;font-weight:700;color:#9A7B1F;letter-spacing:1.5px;">🗓️ 하반기 글로벌 진출 밋업 시리즈</p>
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td style="padding:0 0 10px;vertical-align:top;width:52px;"><div style="background:#0A0A0A;border:1px solid #D4AF37;border-radius:8px;padding:8px 6px;text-align:center;min-width:36px;"><p style="margin:0;font-size:12px;font-weight:800;color:#D4AF37;line-height:1;">7월</p></div></td><td style="padding:0 0 10px 12px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:700;color:#0F172A;">CES 혁신상 수상 노하우 공유 밋업</p><p style="margin:2px 0 0;font-size:11px;color:#9A7B1F;font-weight:600;">7월 28일(화) · 진행 예정</p></td></tr>
          <tr><td style="padding:0 0 10px;vertical-align:top;"><div style="background:#292524;border-radius:8px;padding:8px 6px;text-align:center;min-width:36px;"><p style="margin:0;font-size:12px;font-weight:800;color:#D4AF37;line-height:1;">11월</p></div></td><td style="padding:0 0 10px 12px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:700;color:#0F172A;">글로벌 전시회 참가 전략 밋업 ①</p><p style="margin:2px 0 0;font-size:11px;color:#A8A29E;">일정 추후 안내</p></td></tr>
          <tr><td style="padding:0 0 10px;vertical-align:top;"><div style="background:#292524;border-radius:8px;padding:8px 6px;text-align:center;min-width:36px;"><p style="margin:0;font-size:12px;font-weight:800;color:#D4AF37;line-height:1;">12월</p></div></td><td style="padding:0 0 10px 12px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:700;color:#0F172A;">글로벌 전시회 참가 전략 밋업 ②</p><p style="margin:2px 0 0;font-size:11px;color:#A8A29E;">일정 추후 안내</p></td></tr>
          <tr><td style="vertical-align:top;"><div style="background:#D4AF37;border-radius:8px;padding:8px 6px;text-align:center;min-width:36px;"><p style="margin:0;font-size:12px;font-weight:800;color:#0A0A0A;line-height:1;">12월</p></div></td><td style="padding:0 0 0 12px;vertical-align:top;"><p style="margin:0;font-size:12px;font-weight:700;color:#0F172A;">CES 2027 수상기업 네트워킹 파티 🥂</p><p style="margin:2px 0 0;font-size:11px;color:#A8A29E;">일정 추후 안내</p></td></tr>
        </table>
        <p style="margin:12px 0 0;font-size:11px;color:#A8A29E;">※ 상기 일정과 프로그램은 내부 사정에 따라 변경될 수 있습니다.</p>
      </div>
    </div>
    <div style="padding:0 0 20px;">
      <div style="background:#FAFAF9;border:1px solid #E7E5E4;border-radius:12px;padding:18px;">
        <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#57534E;letter-spacing:1.5px;">🎯 CES 2027 혁신상 도전 안내</p>
        <p style="margin:0 0 14px;font-size:12px;color:#78716C;line-height:1.6;">이번 밋업에서 CES 2027 혁신상 도전을 함께 준비해보세요.</p>
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #E7E5E4;border-radius:8px;overflow:hidden;">
          <tr style="background:#fff;"><td style="padding:9px 14px;font-size:11px;color:#57534E;font-weight:700;white-space:nowrap;width:80px;border-bottom:1px solid #F5F5F4;">신청 접수</td><td style="padding:9px 14px;font-size:12px;color:#0F172A;border-bottom:1px solid #F5F5F4;">2026. 6. 5.(금) ~ 8. 19.(수)</td></tr>
          <tr style="background:#fff;"><td style="padding:9px 14px;font-size:11px;color:#57534E;font-weight:700;white-space:nowrap;border-bottom:1px solid #F5F5F4;">결과 통보</td><td style="padding:9px 14px;font-size:12px;color:#0F172A;border-bottom:1px solid #F5F5F4;">2026. 11. 2.(월)</td></tr>
          <tr style="background:#fff;"><td style="padding:9px 14px;font-size:11px;color:#57534E;font-weight:700;white-space:nowrap;border-bottom:1px solid #F5F5F4;">수상 발표</td><td style="padding:9px 14px;font-size:12px;color:#0F172A;border-bottom:1px solid #F5F5F4;">2026. 11. 9.(월)</td></tr>
          <tr style="background:#fff;"><td style="padding:9px 14px;font-size:11px;color:#57534E;font-weight:700;white-space:nowrap;">출시 조건</td><td style="padding:9px 14px;font-size:12px;color:#0F172A;">2026.4.1 ~ 2027.3.31 최초 출시 제품</td></tr>
        </table>
        <p style="margin:12px 0 14px;font-size:11px;color:#78716C;line-height:1.7;">· 제품 1개당 최대 4개 카테고리 출품 가능<br>· CES 전시 참가 없이도 혁신상 신청 가능</p>
        <a href="https://cta.secure-platform.com/ces-awards" style="display:block;background:#0A0A0A;color:#D4AF37;text-align:center;padding:12px;border-radius:8px;text-decoration:none;font-size:13px;font-weight:700;border:1px solid #D4AF37;">CES 2027 혁신상 신청 바로가기 →</a>
      </div>
    </div>
  </div>
  <div style="background:#0A0A0A;border-radius:0 0 14px 14px;padding:16px 28px;text-align:center;border:1px solid #D4AF37;">
    <p style="margin:0 0 6px;font-size:10px;color:#D4AF37;letter-spacing:3px;font-weight:700;">WITH AVING NEWS</p>
    <p style="margin:0 0 4px;font-size:12px;color:rgba(255,255,255,0.7);">혁신제품지원센터 원스톱 스케일업 · <a href="mailto:onestop.kipcc@gmail.com" style="color:#5DCAA5;text-decoration:none;">onestop.kipcc@gmail.com</a></p>
    <p style="margin:0;font-size:11px;color:rgba(255,255,255,0.45);">본 메일은 원스톱 스케일업 프로그램 참여 시 수신에 동의하신 기업에 발송됩니다.</p>
  </div>
</div>
</body></html>"""
                        body_html_co = ""

                    # 기업 키워드 카드를 "▣ 한 가지 부탁드립니다" 앞에 삽입
                    if kw_section_html and '▣ 한 가지 부탁드립니다' in body_html_co:
                        body_html_co = body_html_co.replace(
                            '▣ 한 가지 부탁드립니다',
                            f'</div>{kw_section_html}<div style="font-size:13px;color:rgba(255,255,255,0.75);line-height:1.9;">▣ 한 가지 부탁드립니다'
                        )
                        kw_section_html = ""  # 이미 삽입했으므로 하단 중복 방지

                    form_sec_co = ""
                    if form_link:
                        form_sec_co = f"""
                        <div style="background:rgba(74,158,255,0.1);border:1px solid rgba(74,158,255,0.3);
                                    border-radius:8px;padding:16px 18px;margin:16px 0;">
                          <p style="margin:0 0 8px;font-size:11px;font-weight:700;color:#10B981;letter-spacing:1.5px;">
                            📋 설문/폼 링크
                          </p>
                          <a href="{form_link}" style="font-size:13px;color:#10B981;">{form_link}</a>
                        </div>"""

                    if template_choice not in ("7월 교육 프로그램 신청 안내", "8월 교육 리마인더 (미신청 대상)", "9월 교육 신청 안내", "9월 교육 리마인더 (미신청 대상)", "10월 교육 신청 안내", "10월 교육 리마인더 (미신청 대상)", "함께하기 회원소개 가입 안내", "CES 혁신상 밋업 신청 안내"):
                        html_body = f"""<!DOCTYPE html>
    <html lang="ko"><head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background:#F2F4F7;
                 font-family:'Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#F2F4F7;padding:36px 0 52px;">
    <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0">
      <tr>
        <td style="background:#ffffff;border-radius:14px 14px 0 0;
                   padding:20px 28px;border-bottom:1px solid #E8ECF0;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td valign="middle">
                <span style="font-size:15px;font-weight:700;color:#1F4E79;">혁신제품지원센터</span>
              </td>
              <td align="right">
                <p style="margin:0;font-size:11px;color:#A0ADB8;">{today_str}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td style="background:#0F1D2E;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="padding:28px 28px 20px;
                         background:#101F33;
                         border-bottom:1px solid rgba(255,255,255,0.06);">
                <p style="margin:0 0 2px;font-size:10px;font-weight:700;letter-spacing:2.5px;
                           color:rgba(255,255,255,0.3);text-transform:uppercase;">
                  원스톱 스케일업 안내
                </p>
                <h1 style="margin:6px 0 0;font-size:22px;font-weight:800;color:#FFFFFF;line-height:1.3;">
                  {mail_subject}
                </h1>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 28px;background:#0F1D2E;">
                <div style="padding:14px 18px;background:rgba(255,255,255,0.05);
                            border-radius:8px;border-left:3px solid #10B981;margin-bottom:20px;">
                  <p style="margin:0;font-size:14px;font-weight:600;color:#FFFFFF;">
                    {company}
                    <span style="font-size:13px;font-weight:400;color:rgba(255,255,255,0.45);margin-left:4px;">담당자님</span>
                  </p>
                </div>
                <div style="font-size:13px;color:rgba(255,255,255,0.75);line-height:1.9;">
                  {body_html_co}
                </div>
                {kw_section_html}
                {form_sec_co}
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td style="background:#ffffff;border-radius:0 0 14px 14px;
                   padding:18px 28px;border-top:1px solid #E8ECF0;">
          <p style="margin:0;font-size:12px;color:#A8BDD1;line-height:1.9;">
            혁신제품지원센터 원스톱 스케일업 운영팀<br>
            <a href="mailto:onestop.kipcc@gmail.com"
               style="color:#5DCAA5;text-decoration:none;font-weight:600;">
              onestop.kipcc@gmail.com
            </a>
          </p>
        </td>
      </tr>
    </table>
    </td></tr></table>
    </body></html>"""

                    try:
                        # 첨부파일 있으면 mixed, 없으면 alternative
                        if attach_data:
                            msg = MIMEMultipart('mixed')
                            alt = MIMEMultipart('alternative')
                            alt.attach(MIMEText(html_body, 'html', 'utf-8'))
                            msg.attach(alt)
                            # 첨부파일명 인코딩 (한글/특수문자 대응)
                            from email.utils import encode_rfc2231
                            part = MIMEBase('application', 'octet-stream')
                            part.set_payload(attach_data)
                            encoders.encode_base64(part)
                            # RFC2231 방식으로 파일명 인코딩
                            try:
                                attach_name.encode('ascii')
                                # ASCII만 있으면 그대로
                                part.add_header('Content-Disposition',
                                                f'attachment; filename="{attach_name}"')
                            except UnicodeEncodeError:
                                # 한글 등 비ASCII 파일명 → RFC2231
                                encoded_name = encode_rfc2231(attach_name, charset='utf-8')
                                part.add_header('Content-Disposition',
                                                f"attachment; filename*={encoded_name}")
                            # Content-Type에도 파일명 명시
                            import mimetypes
                            mime_type, _ = mimetypes.guess_type(attach_name)
                            if mime_type:
                                main, sub = mime_type.split('/')
                                part.replace_header('Content-Type',
                                                    f'{mime_type}; name="{attach_name}"')
                            msg.attach(part)
                        else:
                            msg = MIMEMultipart('alternative')
                            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

                        msg['Subject'] = mail_subject if not test_mode else f"[TEST] {mail_subject}"
                        msg['From']    = "onestop.kipcc@gmail.com"
                        msg['To']      = to_email
                        if cc_list:
                            msg['Cc'] = ", ".join(cc_list)
                        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
                        gmail_send(raw)
                        ok_count += 1
                        logs.append(f"✅ {company} → {to_email}"
                                    + (f" (+Cc {len(cc_list)})" if cc_list else "")
                                    + (" 📎" if attach_data else ""))
                    except Exception as e:
                        fail_count += 1
                        logs.append(f"❌ {company} — {str(e)[:40]}")

                    prog.progress((i+1)/len(df_send))
                    log_area.code("\n".join(logs[-10:]))

                if ok_count > 0:
                    st.success(f"✅ 발송 완료 — 성공 {ok_count}건 / 실패 {fail_count}건")
                if fail_count > 0:
                    st.error(f"실패 {fail_count}건 — 로그를 확인하세요.")


elif page == "교육 신청 집계":
    drive = _get_drive()
    st.title("교육 신청 집계")
    st.caption("Gmail 회신에서 교육 신청 내용을 자동으로 파싱하여 집계합니다.")

    EDU_REG_FILE = "edu_registration.json"

    # 기존 신청 데이터 로드
    def load_edu_reg(drive):
        try:
            return load_json(drive, EDU_REG_FILE) or []
        except:
            return []

    def save_edu_reg(drive, data):
        save_json(drive, data, EDU_REG_FILE)

    edu_data = load_edu_reg(drive)

    # 현황 메트릭
    df_c = load_excel(drive, SELECTED_FILE)
    total_cos = len(df_c[df_c['선정구분']=='선정']) if not df_c.empty and '선정구분' in df_c.columns else 50
    registered_cos = list(set(r['기업명'] for r in edu_data if r.get('기업명')))
    total_people = sum(r.get('인원', 1) for r in edu_data)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("신청 기업", f"{len(registered_cos)}개사")
    c2.metric("미신청 기업", f"{total_cos - len(registered_cos)}개사")
    c3.metric("신청률", f"{len(registered_cos)/total_cos*100:.0f}%")
    c4.metric("총 신청 인원", f"{total_people}명")

    st.divider()

    # Gmail 자동 파싱
    st.subheader("📥 Gmail 회신 자동 파싱")

    # ── 교육 회차 키 추출 (제목의 "N월" → 2026-0N) ──
    def extract_edu_round(subject_text):
        """메일 제목에서 'N월'을 찾아 YYYY-MM 회차 키로 변환.
        [리마인더] 유무·괄호 날짜에 무관하게 같은 달이면 동일 회차로 묶임."""
        m = re.search(r'(\d{1,2})\s*월', str(subject_text))
        if not m:
            return ''
        month = int(m.group(1))
        # 제목에 연도가 있으면 사용, 없으면 올해
        ym = re.search(r'(20\d{2})', str(subject_text))
        year = int(ym.group(1)) if ym else datetime.today().year
        return f"{year}-{month:02d}"

    col_s1, col_s2 = st.columns([3, 1])
    with col_s1:
        mail_subject_input = st.text_input(
            "발송한 메일 제목 입력",
            placeholder="예: [원스톱 스케일업] 7월 교육 프로그램 참여 신청 안내 (7/14~17)",
            key="edu_subject_input"
        )
    with col_s2:
        search_days = st.number_input("최근 N일", min_value=1, max_value=30, value=7, key="edu_search_days")

    st.caption("💡 발송한 메일 제목을 입력하면 해당 메일의 회신만 정확히 수집합니다.")
    parse_btn = st.button("🔍 Gmail 회신 파싱 실행", type="primary", disabled=not mail_subject_input)

    if parse_btn and mail_subject_input:
        with st.spinner("Gmail 회신 검색 중..."):
            try:
                after_date = (datetime.today() - timedelta(days=int(search_days))).strftime('%Y/%m/%d')
                # 발송한 메일 제목으로 정확한 회신만 수집
                query = f'in:inbox subject:"{mail_subject_input}" after:{after_date}'
                resp = gapi('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/messages',
                            params={'q': query, 'maxResults': 100})

                if not resp.ok:
                    st.error(f"Gmail API 오류: {resp.text[:200]}")
                else:
                    msgs = resp.json().get('messages', [])
                    if not msgs:
                        st.info(f"최근 {search_days}일 내 관련 회신이 없습니다.")
                    else:
                        st.success(f"회신 {len(msgs)}건 발견 — AI 파싱 중...")
                        prog = st.progress(0)
                        new_count = 0

                        for i, msg_ref in enumerate(msgs):
                            detail = gapi('GET',
                                f'https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_ref["id"]}',
                                params={'format': 'full'}).json()

                            # 이미 파싱된 메시지 스킵
                            if any(r.get('msg_id') == msg_ref['id'] for r in edu_data):
                                prog.progress((i+1)/len(msgs))
                                continue

                            # 발신자, 제목, 본문 추출
                            headers_list = detail.get('payload', {}).get('headers', [])
                            sender = next((h['value'] for h in headers_list if h['name']=='From'), '')
                            subject = next((h['value'] for h in headers_list if h['name']=='Subject'), '')

                            # 본문 추출
                            import base64
                            def extract_body(payload):
                                if payload.get('body', {}).get('data'):
                                    return base64.urlsafe_b64decode(
                                        payload['body']['data'] + '==').decode('utf-8', errors='ignore')
                                for part in payload.get('parts', []):
                                    result = extract_body(part)
                                    if result: return result
                                return ''

                            body = extract_body(detail.get('payload', {}))[:2000]

                            # AI로 신청 정보 파싱
                            ai_prompt = f"""아래는 교육 신청 회신 메일입니다. JSON으로만 응답하세요.

제목: {subject}
발신자: {sender}
본문:
{body}

추출할 정보:
{{
  "기업명": "기업명 (없으면 null)",
  "담당자명": "담당자명 (없으면 null)",
  "연락처": "연락처 (없으면 null)",
  "인원": 참여 인원 수 (숫자, 기본 1),
  "추가참석자": ["추가 참석자 정보 목록"],
  "교육신청여부": true/false
}}

교육신청여부는 신청 의사가 명확할 때만 true."""

                            try:
                                ai_resp = requests.post(
                                    'https://api.anthropic.com/v1/messages',
                                    headers={'x-api-key': st.secrets.get('ANTHROPIC_API_KEY',''),
                                             'anthropic-version': '2023-06-01',
                                             'content-type': 'application/json'},
                                    json={'model': 'claude-sonnet-4-6',
                                          'max_tokens': 500,
                                          'messages': [{'role':'user','content': ai_prompt}]}
                                )
                                ai_text = ai_resp.json().get('content',[{}])[0].get('text','{}')
                                ai_text = ai_text.strip().lstrip('```json').rstrip('```').strip()
                                parsed = json.loads(ai_text)

                                if parsed.get('교육신청여부'):
                                    edu_data.append({
                                        'msg_id': msg_ref['id'],
                                        '기업명': parsed.get('기업명',''),
                                        '담당자명': parsed.get('담당자명',''),
                                        '연락처': parsed.get('연락처',''),
                                        '인원': parsed.get('인원', 1),
                                        '추가참석자': parsed.get('추가참석자', []),
                                        '발신자': sender,
                                        '수신일': datetime.today().strftime('%Y-%m-%d'),
                                        # 개별 회신 제목 우선, 없으면 검색어 제목에서 회차 추출
                                        '교육회차': extract_edu_round(subject) or extract_edu_round(mail_subject_input),
                                        '비고': ''
                                    })
                                    new_count += 1
                            except:
                                pass

                            prog.progress((i+1)/len(msgs))

                        save_edu_reg(drive, edu_data)
                        st.success(f"✅ 신규 신청 {new_count}건 추가됐습니다.")
                        st.rerun()

            except Exception as e:
                st.error(f"오류: {e}")

    st.divider()

    # 신청 현황 테이블
    st.subheader("📋 신청 현황")

    if edu_data:
        import pandas as _pd_edu
        df_edu = _pd_edu.DataFrame(edu_data)
        display_cols = ['기업명','담당자명','연락처','인원','교육회차','수신일','비고']
        df_edu_show = df_edu[[c for c in display_cols if c in df_edu.columns]]

        edited_edu = st.data_editor(
            df_edu_show,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "인원": st.column_config.NumberColumn("인원", min_value=1),
                "비고": st.column_config.TextColumn("비고"),
            }
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 저장", type="primary"):
                for i, row in edited_edu.iterrows():
                    if i < len(edu_data):
                        for col in display_cols:
                            if col in row:
                                edu_data[i][col] = row[col]
                save_edu_reg(drive, edu_data)
                st.success("저장 완료")

        with col2:
            if st.button("🗑️ 전체 초기화"):
                if st.session_state.get('edu_reset_confirm'):
                    edu_data = []
                    save_edu_reg(drive, edu_data)
                    st.session_state['edu_reset_confirm'] = False
                    st.success("초기화 완료")
                    st.rerun()
                else:
                    st.session_state['edu_reset_confirm'] = True
                    st.warning("한 번 더 클릭하면 초기화됩니다.")

        # 미신청 기업 목록
        if not df_c.empty:
            selected_cos = df_c[df_c['선정구분']=='선정']['기업명'].tolist()
            unreg_cos = [co for co in selected_cos if co not in registered_cos]
            if unreg_cos:
                with st.expander(f"📋 미신청 기업 {len(unreg_cos)}개사"):
                    for co in unreg_cos:
                        st.write(f"• {co}")

        # 엑셀 다운로드
        st.divider()
        # 예전에는 '/mnt/user-data/outputs/' 에 파일을 쓰고 present_files() 를 불렀다.
        # 그 경로도 그 함수도 이 앱에는 없어서 버튼을 누르면 터졌다(2026-07-14부터).
        # 진단 다운로드와 같은 방식 — 메모리에서 만들어 바로 내려준다.
        import io as _io_edu
        _df_edu = pd.DataFrame([{
            '기업명':   r.get('기업명', ''),
            '담당자명': r.get('담당자명', ''),
            '연락처':   r.get('연락처', ''),
            '인원':     r.get('인원', 1),
            '수신일':   r.get('수신일', ''),
            '비고':     r.get('비고', ''),
        } for r in edu_data])
        _buf_edu = _io_edu.BytesIO()
        with pd.ExcelWriter(_buf_edu, engine='openpyxl') as _w_edu:
            _df_edu.to_excel(_w_edu, index=False, sheet_name='교육신청현황')
        st.download_button(
            "📥 엑셀 다운로드",
            data=_buf_edu.getvalue(),
            file_name=f"교육신청현황_{datetime.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        st.caption(f"{len(_df_edu)}개사 · 총 {pd.to_numeric(_df_edu['인원'], errors='coerce').fillna(0).sum():.0f}명")
    else:
        st.info("아직 신청 데이터가 없습니다. Gmail 회신 파싱을 실행해주세요.")

    # 수동 추가
    st.divider()
    st.subheader("✏️ 수동 추가")
    with st.expander("수동으로 신청 추가"):
        m1, m2, m3, m4 = st.columns(4)
        m_co   = m1.text_input("기업명", key="edu_m_co")
        m_name = m2.text_input("담당자명", key="edu_m_name")
        m_tel  = m3.text_input("연락처", key="edu_m_tel")
        m_cnt  = m4.number_input("인원", min_value=1, value=1, key="edu_m_cnt")
        if st.button("추가", key="edu_m_add"):
            if m_co:
                edu_data.append({
                    'msg_id': f'manual_{datetime.today().strftime("%Y%m%d%H%M%S")}',
                    '기업명': m_co, '담당자명': m_name,
                    '연락처': m_tel, '인원': m_cnt,
                    '추가참석자': [], '발신자': '수동입력',
                    '수신일': datetime.today().strftime('%Y-%m-%d'), '비고': ''
                })
                save_edu_reg(drive, edu_data)
                st.success(f"{m_co} 추가 완료")
                st.rerun()


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

            # 최근 200건만 표시 (속도 최적화)
            df_show_h = df_h.tail(200).reset_index(drop=True)
            if len(df_h) > 200:
                st.caption(f"※ 최근 200건만 표시 (전체 {len(df_h)}건)")

            if _IS_STAFF:
                st.caption("보기 전용입니다. 이 표를 고치면 중복 발송 방지가 깨져서, "
                           "수정은 담당자만 할 수 있습니다.")
            edited = st.data_editor(df_show_h, use_container_width=True, hide_index=True,
                disabled=_IS_STAFF,
                column_config={
                    "신청여부":st.column_config.SelectboxColumn("신청여부",options=["","Y","N"]),
                    "선정결과":st.column_config.SelectboxColumn("선정결과",options=["","선정","미선정","대기"]),
                })
            if st.button("💾 드라이브 저장", disabled=_IS_STAFF):
                with st.spinner("저장 중..."):
                    # 편집된 부분을 전체 df_h에 반영
                    df_h.iloc[-len(edited):] = edited.values
                    save_excel(drive, df_h, HISTORY_FILE, "발송이력", "375623")
                st.success("저장 완료")

            st.divider()
            st.markdown("**📅 공통 캘린더 일괄 등록**")
            st.caption("send_history의 마감일 있는 공고를 공통 캘린더에 일괄 등록합니다. 이미 등록된 공고는 스킵됩니다.")

            if st.button("📅 캘린더 일괄 등록 실행", type="primary", disabled=_IS_STAFF):
                _CAL_ID = "9078a49950a47b46ddb3511040886f3a016b75ca17169ec1113e5692b7327375@group.calendar.google.com"
                # CALID_FILE 값 무시 (잘못된 ID 저장됨)

                try:

                    # 이미 등록된 이벤트 조회
                    existing_events = []
                    try:
                        evts = cal_list_events(_CAL_ID)
                        existing_events = [e.get('summary','') for e in evts.get('items',[])]
                    except Exception:
                        pass

                    # notices_db에서 공고명→마감일 매핑 로드
                    df_n_cal = load_excel(drive, NOTICES_FILE)
                    name_to_dl   = {}
                    name_to_link = {}
                    if not df_n_cal.empty:
                        for _, nr in df_n_cal.iterrows():
                            nm = str(nr.get("공고명","") or "")
                            dl = str(nr.get("마감일","") or "")
                            lk = str(nr.get("공고링크","") or "")
                            if nm and dl and dl not in ["","nan","None"]:
                                name_to_dl[nm]   = dl[:10]
                                name_to_link[nm] = lk

                    # 마감일 있는 공고만 중복 제거해서 등록
                    to_reg = {}
                    for _, row in df_h.iterrows():
                        pname = str(row.get("공고명","") or "")
                        dl    = str(row.get("마감일","") or "")
                        link  = str(row.get("공고링크","") or "")
                        if (not dl or dl in ["nan","None",""]) and pname in name_to_dl:
                            dl   = name_to_dl[pname]
                            link = name_to_link.get(pname, link)
                        if pname and dl and dl not in ["", "nan", "None", "상시"]:
                            to_reg[pname] = {"마감일": dl[:10], "공고링크": link}

                    cal_prog = st.progress(0, text="등록 중...")
                    added = 0; skipped = 0
                    items = list(to_reg.items())
                    error_logs = []

                    for i, (pname, info) in enumerate(items):
                        if pname in existing_events:
                            skipped += 1
                        else:
                            try:
                                event = {
                                    'summary': pname,
                                    'description': info['공고링크'],
                                    'start': {'date': info['마감일']},
                                    'end':   {'date': info['마감일']},
                                    'reminders': {
                                        'useDefault': False,
                                        'overrides': [
                                            {'method': 'popup', 'minutes': 60*24*7},
                                            {'method': 'popup', 'minutes': 60*24*3},
                                        ]
                                    }
                                }
                                result = cal_insert_event(_CAL_ID, event)
                                if result.get('id'):
                                    added += 1
                                else:
                                    error_logs.append(f"{pname[:30]}: {result}")
                                    skipped += 1
                            except Exception as e:
                                error_logs.append(f"{pname[:30]}: {str(e)[:60]}")
                                skipped += 1
                        cal_prog.progress((i+1)/max(len(items),1),
                                          text=f"{i+1}/{len(items)} 처리 중...")

                    st.success(f"✅ 캘린더 등록 완료 — 신규 {added}건 / 중복 스킵 {skipped}건")
                    if error_logs:
                        with st.expander(f"⚠️ 실패 {len(error_logs)}건 상세"):
                            for log in error_logs[:10]:
                                st.caption(log)
                except Exception as e:
                    st.error(f"캘린더 등록 실패: {e}")

            st.divider()
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as w: df_h.to_excel(w, index=False)
            st.download_button("📥 엑셀 다운로드", buf.getvalue(), HISTORY_FILE,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

elif page == "메일 보관함":
    drive = _get_drive()
    st.title("메일 보관함")
    info_box("메일 보관함",
        """
    지금까지 기업에 내보낸 안내메일 기록

    **Gmail** — 앱에서 보낸 것. 제목으로 묶어 자동 수집
    **그룹웨어** — Gmail에 안 남는다. HTML을 직접 올린다

    고쳐 쓰는 곳이 아니라 그때 뭐라고 보냈는지 다시 보는 곳이다.
        """,
        "제목 표준은 8. 교육 프로그램 POOL / 0. 안내메일 템플릿 보관 / 0_메일 제목·파일명 표준.md")

    _data = arch_load(drive)
    _items = _data.get('items', [])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("보관 항목", f"{len(_items)}건")
    c2.metric("Gmail", f"{sum(1 for x in _items if x.get('channel') == 'Gmail')}건")
    c3.metric("그룹웨어", f"{sum(1 for x in _items if x.get('channel') != 'Gmail')}건")
    c4.metric("마지막 갱신", _data.get('updated', '—') or '—')

    # ── Gmail 수집 ───────────────────────────────────
    cb1, cb2 = st.columns([1, 3])
    with cb1:
        _go = st.button("🔄 Gmail에서 수집", use_container_width=True)
    with cb2:
        st.caption("보낸메일함 전체를 훑는다. 1,800통 기준 1~2분. "
                   "[TEST]와 답장·전달은 빠지고, 3통 미만도 개별 메일로 보고 뺀다.")

    if _go:
        _bar = st.progress(0.0, text="보낸메일함 목록 읽는 중…")

        def _prog(done, total):
            _bar.progress(min(done / max(total, 1), 1.0),
                          text=f"제목 읽는 중… {done:,} / {total:,}통")

        try:
            _new, _stat = arch_collect_gmail(progress=_prog)
            _bar.empty()
            _data['items'] = arch_merge(_items, _new)
            _data['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')
            if arch_save(drive, _data):
                st.success(f"수집 완료 — 보낸메일 {_stat['총']:,}통에서 묶음 {_stat['묶음']}건")
                if _stat['못 받은 건']:
                    st.warning(f"{_stat['못 받은 건']}통은 못 받았다. 다시 눌러 주십시오.")
                st.rerun()
        except Exception as _e:
            _bar.empty()
            st.error(f"수집 실패: {_e}")

    st.divider()

    # ── 그룹웨어로 보낸 것 직접 올리기 ───────────────
    with st.expander("➕ 그룹웨어로 보낸 메일 올리기", expanded=False):
        st.caption("더존 그룹웨어로 내보낸 메일은 Gmail에 안 남는다. "
                   "만들 때 썼던 HTML을 그대로 올리면 된다.")
        _uf = st.file_uploader("HTML 파일", type=['html', 'htm'], key="arch_up")
        _u1, _u2 = st.columns(2)
        _udate = _u1.date_input("보낸 날", value=datetime.now(), key="arch_date")
        _ucnt = _u2.number_input("보낸 통수", min_value=0, value=0, step=1, key="arch_cnt")
        _utitle = st.text_input("제목", key="arch_title",
                                placeholder="[원스톱 스케일업] 10월 무료 교육 신청 안내 (~10/23) — …")
        if st.button("보관함에 넣기", disabled=not (_uf and _utitle)):
            _html = _uf.read().decode('utf-8', 'replace')
            _items.append({
                'key': arch_group_key(_utitle),
                'kind': arch_kind(_utitle),
                'channel': '그룹웨어',
                'first': _udate.strftime('%Y-%m-%d'),
                'last': _udate.strftime('%Y-%m-%d'),
                'count': int(_ucnt) or None,
                'sample_subject': _utitle,
                'msg_id': '',
                'html': _html,
            })
            _items.sort(key=lambda x: x.get('last', ''), reverse=True)
            _data['items'] = _items
            _data['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')
            if arch_save(drive, _data):
                st.success("넣었습니다.")
                st.rerun()

    if not _items:
        st.info("아직 보관된 메일이 없다. 위 「Gmail에서 수집」을 눌러 주십시오.")
    else:
        # ── 거르기 ───────────────────────────────────
        f1, f2, f3 = st.columns([1, 1, 2])
        _kinds = ['전체'] + sorted({x.get('kind', '기타') for x in _items})
        _kind = f1.selectbox("종류", _kinds, key="arch_f_kind")
        _ch = f2.selectbox("통로", ['전체', 'Gmail', '그룹웨어'], key="arch_f_ch")
        _q = f3.text_input("제목 검색", key="arch_f_q", placeholder="교육, 공고, 지침서 …")

        _view = [x for x in _items
                 if (_kind == '전체' or x.get('kind') == _kind)
                 and (_ch == '전체' or x.get('channel') == _ch)
                 and (not _q or _q.lower() in (x.get('key', '') or '').lower())]

        st.caption(f"{len(_view)}건")

        _labels = []
        for x in _view:
            _d = x.get('first', '')
            if x.get('last') and x.get('last') != _d:
                _d += f" ~ {x['last'][5:]}"
            _n = f"{x['count']}통" if x.get('count') else "—"
            _labels.append(f"{_d}  ·  {_n}  ·  [{x.get('channel','')}]  {x.get('key','')}")

        _pick = st.radio("보관 목록", range(len(_view)),
                         format_func=lambda i: _labels[i],
                         label_visibility="collapsed", key="arch_pick")

        if _view:
            _it = _view[_pick]
            st.divider()
            st.markdown(f"**{_it.get('sample_subject','')}**")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("보낸 날", _it.get('first', '—'))
            m2.metric("통수", f"{_it['count']}통" if _it.get('count') else "—")
            m3.metric("통로", _it.get('channel', '—'))
            m4.metric("종류", _it.get('kind', '—'))

            _html = _it.get('html') or ''
            if not _html:
                st.warning("본문이 저장되어 있지 않다. 다시 수집하면 채워진다.")
            else:
                pv1, pv2 = st.tabs(["👁 미리보기", "📋 붙여넣기용 코드"])
                with pv1:
                    st.components.v1.html(_html, height=1100, scrolling=True)
                with pv2:
                    st.caption("그룹웨어 메일 쓰기에 그대로 붙여넣으면 된다.")
                    st.code(_html, language="html")
                    st.download_button(
                        "HTML 파일로 내려받기", _html.encode('utf-8'),
                        file_name=f"{_it.get('first','')}_{_it.get('kind','')}.html",
                        mime="text/html")

elif page == "설정":
    drive = _get_drive()
    st.title("설정")
    st.caption("키워드·매칭 설정 / 드라이브 연동 / 인증 관리")

    tab_s1, tab_s2, tab_s3, tab_s4, tab_s5 = st.tabs([
        "🎯 축1 — 지원대상", "📋 축2 — 사업성격",
        "🏢 기업별 키워드", "⚖️ 매칭 가중치", "🔧 시스템 설정"
    ])
    kw_data = load_json(drive, KEYWORDS_FILE) or {}
    HIGH_kw, MID_kw = load_keywords(drive)
    df_c = load_excel(drive, SELECTED_FILE)

    # ── 탭1: 축1 지원대상 ──────────────────────────────
    with tab_s1:
        st.subheader("축1 — 지원대상 키워드")
        st.caption("공고가 어떤 기업을 대상으로 하는지 판단합니다. 이 키워드가 공고에 있을 때 해당 카테고리로 분류됩니다.")

        current_target = kw_data.get("TARGET_KW", TARGET_KW)
        t_inputs = {}
        label_map1 = {
            "조달기업특화": "🏆 조달기업특화 (G-PASS·조달청·혁신제품 대상 공고) → ★★★",
            "수출기업특화": "🌏 수출기업특화 (수출·글로벌 대상 공고) → ★★★",
            "중소벤처일반": "🏢 중소벤처일반 (일반 중소·벤처 대상 공고) → ★★",
        }
        for cat, kws in current_target.items():
            st.markdown(f"**{label_map1.get(cat, cat)}**")
            st.caption(f"현재 {len(kws)}개 키워드")
            t_inputs[cat] = st.text_area(
                f"{cat}", value=", ".join(kws), height=80,
                key=f"tkw_{cat}", label_visibility="collapsed",
                placeholder="쉼표로 구분하여 입력"
            )
            st.divider()

        if st.button("💾 축1 키워드 저장", type="primary", key="save_target_kw"):
            new_target = {}
            for cat in current_target:
                new_target[cat] = [k.strip() for k in t_inputs[cat].split(',') if k.strip()]
            kw_data["TARGET_KW"] = new_target
            if save_json(drive, kw_data, KEYWORDS_FILE):
                total = sum(len(v) for v in new_target.values())
                st.success(f"축1 저장 완료 — 총 {total}개 키워드")
            else:
                st.error("저장 실패")

    # ── 탭2: 축2 사업성격 ──────────────────────────────
    with tab_s2:
        st.subheader("축2 — 사업성격 키워드")
        st.caption("공고가 어떤 종류의 지원인지 판단합니다. 축1과 교차하여 별점이 결정됩니다.")

        current_type = kw_data.get("TYPE_KW", TYPE_KW)
        ty_inputs = {}
        label_map2 = {
            "공공조달":   "🏛 공공조달 (조달청·시범구매·MAS) → ★★★",
            "해외진출":   "🌏 해외진출 (수출바우처·해외판로) → ★★★",
            "마케팅홍보": "📢 마케팅·홍보 (전시회·박람회·홍보) → ★★",
            "인증특허":   "📋 인증·특허 (해외인증·IP) → ★★",
            "기술개발":   "🔬 기술개발 (R&D·기술사업화) → ★★",
            "금융융자":   "💰 금융·융자 (정책자금·보증) → ★★",
            "내수판로":   "🛒 내수판로 (온라인몰·유통) → ★★",
            "인력채용":   "👥 인력·채용 (청년채용·인재양성) → ★★",
        }
        for cat, kws in current_type.items():
            st.markdown(f"**{label_map2.get(cat, cat)}**")
            st.caption(f"현재 {len(kws)}개 키워드")
            ty_inputs[cat] = st.text_area(
                f"{cat}", value=", ".join(kws), height=80,
                key=f"tykw_{cat}", label_visibility="collapsed",
                placeholder="쉼표로 구분하여 입력"
            )
            st.divider()

        if st.button("💾 축2 키워드 저장", type="primary", key="save_type_kw"):
            new_type = {}
            for cat in current_type:
                new_type[cat] = [k.strip() for k in ty_inputs[cat].split(',') if k.strip()]
            kw_data["TYPE_KW"] = new_type
            if save_json(drive, kw_data, KEYWORDS_FILE):
                total = sum(len(v) for v in new_type.values())
                st.success(f"축2 저장 완료 — 총 {total}개 키워드")
            else:
                st.error("저장 실패")

    # ── 탭3: 기업별 키워드 ────────────────────────────
    with tab_s3:
        st.subheader("기업별 키워드 보완")
        st.caption("각 기업에 추가 키워드를 설정합니다. 기업 관리 탭과 동일한 필드이며 여기서 일괄 편집 가능합니다.")

        # 매칭결과 기반 기본 키워드 (분석 결과로 자동 생성)
        DEFAULT_CO_KW = {
            "(주)더세이프": "친환경, 환경, 에너지, 운송, 대기, 탄소중립",
            "(주)빛가람시스템": "AI, 정보통신, 통신, 네트워크, ICT, 클라우드",
            "(주)새영테크놀로지": "환경, 에너지, 탄소, 저탄소, ESG, 대기",
            "(주)세이프텍리서치": "국방, 방어, 방산, AI, 데이터, 데이터분석",
            "(주)아이서티": "정보통신, 통신, 인공지능, 데이터플랫폼, AI, 데이터",
            "(주)아이쉐어넷": "모빌리티, 운송, 자율주행, 차량, 전자, 진단",
            "(주)에코라이프": "탄소, 대기, 녹색, 환경, 에너지, 탄소중립",
            "(주)엠피웨이브": "정보통신, 통신, IoT, ICT, AI, 스마트",
            "(주)오썸피아": "해외조달, 정보통신, 통신, AI, IoT, 교육",
            "(주)오투엔비": "탄소, 대기, 환경, 에너지, 녹색, 제조",
            "(주)케이씨티이엔씨": "건설, 건설자재, 통신, 보안, 정보통신",
            "(주)테스토닉": "전자, 환경, 헬스, 디지털헬스, 탄소, 대기",
            "(주)피투에스지글로벌": "AI, 전자, 반도체, 물류, 글로벌",
            "대성": "소재, 생산, 장비, 제조, 수산, 수산물",
            "블루센 주식회사": "전자, 배터리, 센서, 대기, 탄소, 녹색",
            "비웨이브(주)": "바이오, 진단, 의료, 헬스케어, 헬스, 정보통신",
            "스마트이앤씨": "정보통신, 통신, 소프트웨어, SW, AI",
            "아이씨피(주)": "방산, 운송, 물류, 공급망, 국방, 인프라",
            "에스엠테크": "탄소, 대기, 환경, 에너지, 로봇, 장비",
            "에이트스튜디오 주식회사": "AI, 네트워크, 헬스, 디지털헬스, IoT, 스마트",
            "유비컨트롤 주식회사": "제조, 소재, 기계, 장비, 설비, 생산",
            "이노넷(주)": "AI, 드론, 건설, 보안, 물류, 공급망",
            "인플랩 주식회사": "금융, 인프라, 정보통신, 통신, 물류, 물류센터",
            "주식회사 동성이에스": "탄소중립, 탄소, 대기, 환경, 에너지, 전자",
            "주식회사 리얼디자인테크": "AI, 헬스, 디지털헬스, IoT, 진단, 의료기기",
            "주식회사 바르미페인트": "모빌리티, 자율주행, 대기, 해외조달, 친환경, 환경",
            "주식회사 바이오바이츠": "바이오, 헬스케어, 진단, 헬스, 정보통신, 통신",
            "주식회사 아스팔트아트": "정보통신, 통신, 5G, 인프라, 스마트물류",
            "주식회사 애니락": "건축, 환경, 대기",
            "주식회사 에어딥": "환경, 대기, 데이터센터, 5G, 에너지, ESG",
            "주식회사 엠쓰리시스템즈": "장비, 제조, 소재, 건설, 건설자재, 제조업",
            "주식회사 옥스": "전자, 배터리, 센서, AI, 정보통신, 통신",
            "주식회사 와트": "해외전시, AI솔루션, 지능형, 데이터분석, 통신",
            "주식회사 이지서티": "정보통신, 통신, 금융, AI, AI솔루션, 지능형",
            "주식회사 제이씨에프테크놀러지": "해외조달, 교육, 인재, AI, 헬스, 디지털헬스",
            "주식회사 칼렛바이오": "친환경, 환경, 에너지, 대기, 모빌리티, 자율주행",
            "주식회사 케이스마트피아": "대기, 환경, 에너지",
            "주식회사 퀀텀바이오닉스": "환경, 탄소중립, 온실가스, 탄소, 녹색, 기후",
            "주식회사 클리어창": "대기, 탄소, 친환경",
            "주식회사 트레시스": "전자, 대기, 탄소, 배터리, 센서, 이차전지",
            "주식회사 필메디": "바이오, 의료, 의료기기, 헬스, 디지털헬스, 의약",
            "주식회사 휴마스터": "수소, 탄소중립, 탄소, 대기, 온실가스, 녹색",
            "창조 엔지니어링": "수산, 수산물, 식품, 축산, 해양수산, 환경",
            "탐투스(주)": "해외조달, 전자, 환경, 탄소, 대기, 배터리",
            "파이어버스터Lab": "모빌리티, 자율주행, 차량, 배터리, 자동차부품",
            "팔수": "헬스, 디지털헬스, 진단, 바이오, 의료, 의약",
            "피아스페이스(주)": "AI, 정보통신, 통신, 데이터분석, 디지털전환",
            "주식회사 쎈인더스트리": "제조, 장비, 설비, 기계",
            "주식회사 애니락": "건축, 건설자재, 환경",
            "주식회사 쎈인더스트리": "제조, 장비, 설비, 스마트제조",
        }

        if df_c.empty:
            st.warning("선정기업 명단이 없습니다.")
        else:
            if '키워드보완' not in df_c.columns:
                df_c['키워드보완'] = ''

            # 키워드 없는 기업에 DEFAULT_CO_KW 자동 채우기 버튼
            no_kw_count = (df_c['키워드보완'].fillna('') == '').sum()
            if no_kw_count > 0:
                c1, c2 = st.columns([2, 3])
                with c1:
                    st.warning(f"⚠️ {no_kw_count}개사 키워드 미입력")
                with c2:
                    if st.button("🤖 분석 기반 키워드 자동 채우기", key="auto_fill_kw"):
                        filled = 0
                        for idx, row in df_c.iterrows():
                            co = row.get('기업명','')
                            if not row.get('키워드보완','') and co in DEFAULT_CO_KW:
                                df_c.at[idx, '키워드보완'] = DEFAULT_CO_KW[co]
                                filled += 1
                        if filled > 0:
                            if save_excel(drive, df_c, SELECTED_FILE, "선정기업명단", "1F4E79"):
                                st.success(f"✅ {filled}개사 키워드 자동 입력 완료")
                                st.rerun()
            else:
                st.success("✅ 전체 기업 키워드 입력 완료")

            search = st.text_input("🔍 기업명 검색", key="kw_co_search")
            df_show = df_c[df_c['기업명'].str.contains(search, na=False)] if search else df_c

            changed = {}
            for idx, row in df_show.iterrows():
                c1, c2 = st.columns([2, 3])
                with c1:
                    nm = row.get('기업명', '')
                    st.write(f"**{nm}**")
                    st.caption(f"{row.get('제품분야','—')[:20]} | {row.get('소재지','—')}")
                with c2:
                    cur_kw = row.get('키워드보완','')
                    hint   = DEFAULT_CO_KW.get(nm, '')
                    new_kw = st.text_input(
                        "추가 키워드",
                        value=cur_kw,
                        key=f"co_kw_{idx}",
                        placeholder=hint if hint else "예: 스마트팜, IoT 센서",
                        label_visibility="collapsed"
                    )
                    if new_kw != cur_kw:
                        changed[idx] = new_kw

            if changed:
                if st.button(f"💾 변경된 {len(changed)}개사 키워드 저장",
                             type="primary", key="save_co_kw"):
                    for idx, val in changed.items():
                        df_c.at[idx, '키워드보완'] = val
                    if save_excel(drive, df_c, SELECTED_FILE, "선정기업명단", "1F4E79"):
                        st.success(f"{len(changed)}개사 키워드 저장 완료")
                        st.rerun()
                    else:
                        st.error("저장 실패")

        # 피드백 패턴 (이전 검토에서 쌓인 데이터)
        feedback = kw_data.get('feedback', {})
        if feedback:
            st.divider()
            st.subheader("📋 피드백 패턴 (제외 이력)")
            st.caption("이전 검토에서 제외한 공고의 사업성격 패턴입니다. 다음 매칭 시 자동 감점됩니다.")
            for co, patterns in list(feedback.items())[:10]:
                st.write(f"**{co}**: " + ", ".join([f"{k}({v}회)" for k,v in sorted(patterns.items(), key=lambda x:-x[1])]))

    # ── 탭4: 매칭 가중치 ──────────────────────────────
    with tab_s4:
        st.subheader("매칭 축별 가중치 조정")
        st.caption("각 축의 점수 비중을 조정합니다. 합산 점수가 별점(★) 판정에 영향을 줍니다.")

        weights = kw_data.get("weights", {
            "지원대상": 3, "사업성격": 2, "기업키워드": 2,
            "핵심수요": 3, "업종역방향": 1, "소재지가산": 3, "세그먼트": 2
        })

        st.markdown("**각 매칭 축의 기본 점수 (건당)**")
        c1, c2 = st.columns(2)
        with c1:
            w_target  = st.slider("지원대상 매칭 (×건수)", 1, 6, weights.get("지원대상", 3), key="w1")
            w_type    = st.slider("사업성격 매칭 (×건수)", 1, 6, weights.get("사업성격", 2), key="w2")
            w_kw      = st.slider("기업키워드 매칭 (×건수)", 1, 6, weights.get("기업키워드", 2), key="w3")
            w_demand  = st.slider("핵심수요 매칭 (×건수)", 1, 6, weights.get("핵심수요", 3), key="w4")
        with c2:
            w_ind     = st.slider("업종 역방향 매칭 (×건수)", 1, 6, weights.get("업종역방향", 1), key="w5")
            w_loc     = st.slider("소재지 일치 가산점", 1, 6, weights.get("소재지가산", 3), key="w6")
            w_seg     = st.slider("세그먼트 부스트 (최대)", 1, 8, weights.get("세그먼트", 4), key="w7")

        st.divider()
        st.subheader("★ 별점 판정 기준")
        col1, col2 = st.columns(2)
        with col1:
            star3_threshold = st.slider("★★★ 최소 점수", 10, 40, kw_data.get("star3_threshold", 20), key="s3")
        with col2:
            star2_threshold = st.slider("★★ 최소 점수",  5, 30, kw_data.get("star2_threshold", 10), key="s2")
        st.caption(f"현재 설정: ★★★ ≥ {star3_threshold}점, ★★ ≥ {star2_threshold}점")

        if st.button("💾 가중치 저장", type="primary", key="save_weights"):
            kw_data["weights"] = {
                "지원대상": w_target, "사업성격": w_type,
                "기업키워드": w_kw, "핵심수요": w_demand,
                "업종역방향": w_ind, "소재지가산": w_loc, "세그먼트": w_seg
            }
            kw_data["star3_threshold"] = star3_threshold
            kw_data["star2_threshold"] = star2_threshold
            if save_json(drive, kw_data, KEYWORDS_FILE):
                st.success("가중치 저장 완료 — 다음 매칭 실행 시 반영됩니다.")
            else:
                st.error("저장 실패")

        with st.expander("ℹ️ 가중치 설명"):
            st.markdown("""
**지원대상 매칭** — 공고가 "수출기업", "벤처기업" 등 기업 유형을 명시한 경우

**사업성격 매칭** — 공고가 "해외진출", "기술개발" 등 사업 유형에 해당하는 경우

**기업키워드 매칭** — 기업의 기술키워드/제품분야가 공고 텍스트에 직접 등장하는 경우

**핵심수요 매칭** — 기업의 핵심수요태그(G-PASS, 수출바우처 등)가 공고와 일치하는 경우

**업종 역방향 매칭** — 기업 제품분야 → INDUSTRY_KW → 공고 텍스트로 간접 매칭된 경우

**소재지 일치** — 지역 제한 공고에서 기업 소재지가 일치하는 경우

**세그먼트 부스트** — 기업 세그먼트(해외진출형/조달강화형 등)에 맞는 공고 유형 보너스
            """)

    # ── 탭5: 시스템 설정 ──────────────────────────────
    with tab_s5:
        st.subheader("🔧 시스템 설정")

        # 드라이브 연동 상태
        st.markdown("**📁 드라이브 연동 현황**")
        st.markdown(f"[📂 드라이브 폴더 열기](https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID})")
        files_check = {
            SELECTED_FILE: "선정기업 명단",
            NOTICES_FILE:  "공고 DB",
            HISTORY_FILE:  "발송 이력",
            KEYWORDS_FILE: "키워드 설정",
            AI_ANALYSIS_FILE: "AI 분석 결과",
            INDCAL_FILE:   "기업별 캘린더",
        }
        cols = st.columns(2)
        for i, (fname, label) in enumerate(files_check.items()):
            fid = drive_file_id(drive, fname)
            cols[i%2].write(f"{'✅' if fid else '❌'} {label} (`{fname}`)")

        st.divider()

        # 인증 상태
        st.markdown("**🔑 구글 인증 상태**")
        try:
            test_resp = gapi('GET', 'https://www.googleapis.com/drive/v3/about',
                             params={'fields': 'user'})
            if test_resp.ok:
                user_info = test_resp.json().get('user', {})
                st.success(f"✅ 인증 정상 — {user_info.get('emailAddress', '확인됨')}")
            else:
                st.error(f"❌ 인증 실패 ({test_resp.status_code}) — 토큰 갱신 필요")
        except Exception as e:
            st.error(f"❌ 인증 오류: {e}")

        st.divider()

        # 토큰 갱신 안내
        st.markdown("**🔄 토큰 갱신 방법**")
        st.info("""
토큰이 만료되면 드라이브/Gmail/캘린더 기능이 모두 중단됩니다.

**갱신 순서:**
1. 회사 PC에서 `python refresh_token.py` 실행
2. 브라우저 구글 로그인 → 권한 허용
3. `token_new.json` 생성 확인
4. Streamlit Cloud → Settings → Secrets → `token` 값 교체
5. 앱 Reboot
        """)

        st.divider()
        st.markdown("**ℹ️ 앱 정보**")
        st.caption(f"GitHub: onestopkipcc-web/scaleup-matching")
        st.caption(f"배포: Streamlit Cloud")
        st.caption(f"드라이브 폴더 ID: {DRIVE_FOLDER_ID}")

        st.divider()

        # 발송 이력 초기화
        st.markdown("**🗑️ 발송 이력 초기화**")
        st.warning("초기화하면 `send_history.xlsx`의 모든 이력이 삭제됩니다. 다음 매칭 시 이미 발송한 공고도 다시 추천됩니다.")

        confirm_reset = st.text_input(
            "초기화하려면 **RESET** 을 입력하세요",
            key="reset_history_confirm",
            placeholder="RESET"
        )
        if st.button("🗑️ 발송 이력 초기화 실행", key="reset_history_btn",
                     disabled=(confirm_reset != "RESET")):
            import pandas as _pd_reset
            empty_df = _pd_reset.DataFrame(columns=[
                "기업명","pblancId","공고명","발송일",
                "매칭점수","담당자검토","검토의견","신청여부","선정결과"
            ])
            if save_excel(drive, empty_df, HISTORY_FILE, "발송이력", "375623"):
                # 진행 기록도 함께 비운다 — 남겨두면 다음 발송이 계속 건너뛴다
                save_send_progress(drive, {'round_id': '', 'sent': {}, 'pending': []})
                st.success("✅ 발송 이력 초기화 완료 — 다음 매칭부터 모든 공고가 다시 추천됩니다.")
            else:
                st.error("초기화 실패 — 드라이브 연결을 확인하세요.")



# ══════════════════════════════════════════════════════
# 클릭 반응 대시보드
# ══════════════════════════════════════════════════════
elif page == "클릭 반응":
    drive = _get_drive()
    st.title("🖱 클릭 반응")
    st.caption("발송 메일의 공고 링크 클릭을 집계합니다 (Apps Script 경유 기록)")

    if st.button("🔄 새로고침"):
        st.rerun()

    df_click = load_click_log(debug=True)

    if df_click.empty:
        st.info("아직 클릭 기록이 없습니다. 발송된 메일에서 공고 링크가 클릭되면 여기 집계됩니다.")
    else:
        # 컬럼 자동 인식
        cols = list(df_click.columns)
        co_col = next((c for c in cols if '기업' in str(c)), cols[1] if len(cols)>1 else cols[0])
        nm_col = next((c for c in cols if '공고명' in str(c) or 'name' in str(c).lower()), None)
        tm_col = next((c for c in cols if '시각' in str(c) or 'time' in str(c).lower() or '시간' in str(c)), cols[0])

        # 테스트 클릭 제외
        _df = df_click.copy()
        _df = _df[~_df[co_col].astype(str).str.contains('테스트|test', case=False, na=False)]
        _df = _df[_df[co_col].astype(str).str.strip() != ""]

        total_clicks = len(_df)
        uniq_co = _df[co_col].nunique()

        c1, c2, c3 = st.columns(3)
        c1.metric("총 클릭", f"{total_clicks}회")
        c2.metric("클릭한 기업", f"{uniq_co}개사")
        if nm_col:
            c3.metric("클릭된 공고", f"{_df[nm_col].nunique()}건")

        st.divider()

        # 기업별 클릭
        st.subheader("기업별 클릭 수")
        by_co = _df.groupby(co_col).size().reset_index(name='클릭수')
        by_co = by_co.sort_values('클릭수', ascending=False)
        by_co.columns = ['기업명', '클릭수']
        render_html_table(by_co, max_rows=50)

        # 공고별 클릭
        if nm_col:
            st.subheader("공고별 클릭 수")
            by_nt = _df.groupby(nm_col).size().reset_index(name='클릭수')
            by_nt = by_nt.sort_values('클릭수', ascending=False)
            by_nt.columns = ['공고명', '클릭수']
            render_html_table(by_nt, max_rows=50)

        # 최근 클릭 로그
        st.subheader("최근 클릭 기록")
        _recent = _df.sort_values(tm_col, ascending=False).head(30)
        render_html_table(_recent, max_rows=30)


# ══════════════════════════════════════════════════════
# 캘린더 관리
# ══════════════════════════════════════════════════════
elif page == "캘린더":
    drive = _get_drive()
    st.title("캘린더 관리")
    info_box("캘린더 관리",
        """
기업별 구글 캘린더를 생성하고 담당자에게 공유합니다.

**운영 흐름**
1. 기업 담당자 구글계정 수집 (기업 관리 탭 또는 DB 업로드)
2. 캘린더 일괄 생성 → individual_calendars.json 저장
3. 담당자 이메일로 공유 초대 자동 발송
4. 이후 발송 시 공고 마감일이 캘린더에 자동 등록됨
        """,
        "테스트 먼저 → 전체 실행")

    tab_cal1, tab_cal2, tab_cal3 = st.tabs([
        "🧪 테스트 생성", "📋 기업별 현황", "⚙️ 전체 실행"
    ])

    # ── 공통 데이터 로드 ──────────────────────────────
    df_c       = load_excel(drive, SELECTED_FILE)
    ind_cals   = load_json(drive, INDCAL_FILE) or {}

    # ── 탭1: 테스트 생성 ──────────────────────────────
    with tab_cal1:
        st.subheader("테스트용 캘린더 생성")
        st.caption("실제 기업 DB와 무관하게 테스트 계정으로 먼저 동작 확인합니다.")

        with st.form("test_cal_form"):
            t_company  = st.text_input("테스트 기업명", value="테스트기업_홍길동",
                                        placeholder="캘린더 이름에 표시될 기업명")
            t_email    = st.text_input("공유할 구글 계정",
                                        placeholder="example@gmail.com",
                                        help="이 계정으로 캘린더 공유 초대가 발송됩니다")
            t_interest = st.text_input("관심분야 (선택)", placeholder="수출, 기술개발")
            t_keyword  = st.text_input("기술키워드 (선택)", placeholder="AI, IoT")
            submitted  = st.form_submit_button("🗓 테스트 캘린더 생성", type="primary")

        if submitted:
            if not t_email or '@' not in t_email:
                st.error("구글 계정 이메일을 올바르게 입력해주세요.")
            else:
                with st.spinner("캘린더 생성 중..."):
                    try:
                        cal_id = cal_create(
                            f"[원스톱] {t_company} 지원공고 D-day",
                            f"혁신제품지원센터 원스톱 스케일업 프로그램\n기업: {t_company}\n관심분야: {t_interest}\n기술키워드: {t_keyword}\n문의: onestop.kipcc@gmail.com"
                        )
                        if not cal_id:
                            st.error("캘린더 생성 실패 — 인증 상태를 확인하세요.")
                        else:
                            sub_link = f"https://calendar.google.com/calendar?cid={cal_id}"
                            st.success("✅ 캘린더 생성 완료!")
                            st.code(f"캘린더 ID: {cal_id}")

                            # 공유 초대
                            if cal_share(cal_id, t_email):
                                st.success(f"✅ {t_email} 으로 공유 초대 발송 완료!")
                            else:
                                st.warning("⚠️ 공유 초대 실패 — 이메일을 확인하세요.")
                            st.markdown(f"[📅 캘린더 구독 링크]({sub_link})")

                            # 테스트 이벤트 등록
                            from datetime import timedelta
                            test_date = (datetime.today() + timedelta(days=7)).strftime('%Y-%m-%d')
                            event = {
                                'summary': f"[D-7] 테스트공고 마감 — {t_company}",
                                'description': "원스톱 스케일업 테스트 이벤트입니다.",
                                'start': {'date': test_date, 'timeZone': 'Asia/Seoul'},
                                'end':   {'date': test_date, 'timeZone': 'Asia/Seoul'},
                            }
                            cal_insert_event(cal_id, event)
                            st.success(f"✅ 테스트 이벤트 등록 완료 ({test_date} D-7 알림)")
                            st.info("📱 구글 캘린더 앱에서 공유 초대를 수락하면 캘린더가 추가됩니다.")

                    except Exception as e:
                        st.error(f"오류 발생: {str(e)}")

    # ── 탭2: 기업별 현황 ──────────────────────────────
    with tab_cal2:
        st.subheader("기업별 캘린더 현황")

        if not ind_cals:
            st.info("아직 생성된 캘린더가 없습니다. '전체 실행' 탭에서 생성하세요.")
        else:
            total    = len(ind_cals)
            shared   = sum(1 for v in ind_cals.values() if v.get('shared'))
            noshare  = total - shared

            c1, c2, c3 = st.columns(3)
            c1.metric("전체 캘린더", f"{total}개")
            c2.metric("✅ 공유 완료", f"{shared}개")
            c3.metric("⏳ 공유 대기", f"{noshare}개")
            st.divider()

            for co, info in ind_cals.items():
                status = "✅" if info.get('shared') else "⏳"
                with st.expander(f"{status} {co}"):
                    c1, c2 = st.columns(2)
                    c1.caption("구글 계정")
                    c1.write(info.get('google_account', '미입력') or '미입력')
                    c2.caption("공유 상태")
                    c2.write("공유 완료" if info.get('shared') else "미공유")
                    if info.get('subscribe_link'):
                        st.markdown(f"[📅 구독 링크]({info['subscribe_link']})")

                    # 미공유 기업 수동 공유 버튼
                    if not info.get('shared') and info.get('google_account'):
                        if st.button(f"📨 {info['google_account']}에 공유", key=f"share_{co}"):
                            try:
                                ok = cal_share(info['calendar_id'], info['google_account'])
                                if ok:
                                    ind_cals[co]['shared'] = True
                                    import json as _json
                                    content = _json.dumps(ind_cals, ensure_ascii=False).encode('utf-8')
                                    drive_upload(drive, INDCAL_FILE, content, "application/json")
                                    st.success("공유 완료!")
                                    st.rerun()
                                else:
                                    st.error("공유 실패 — 구글 계정을 확인하세요.")
                            except Exception as e:
                                st.error(f"공유 실패: {e}")

        # DB 업로드 섹션
        st.divider()
        st.subheader("📁 individual_calendars.json 직접 업로드")
        st.caption("로컬에서 create_individual_calendars.py 실행 후 생성된 파일을 업로드하세요.")
        uploaded_cal = st.file_uploader("individual_calendars.json 업로드",
                                         type=["json"], key="cal_upload")
        if uploaded_cal:
            import json as _json
            cal_data = _json.loads(uploaded_cal.read().decode('utf-8'))
            content  = _json.dumps(cal_data, ensure_ascii=False).encode('utf-8')
            if drive_upload(drive, INDCAL_FILE, content, "application/json"):
                st.success(f"✅ {len(cal_data)}개사 캘린더 정보 업로드 완료")
                st.rerun()

    # ── 탭3: 전체 실행 ────────────────────────────────
    with tab_cal3:
        st.subheader("전체 기업 캘린더 일괄 생성")

        if df_c.empty:
            st.warning("선정기업 명단이 없습니다.")
        else:
            has_google = '구글계정' in df_c.columns
            google_filled = (df_c['구글계정'].fillna('') != '').sum() if has_google else 0
            no_google     = len(df_c) - google_filled if has_google else len(df_c)

            c1, c2, c3 = st.columns(3)
            c1.metric("전체 기업", f"{len(df_c)}개사")
            c2.metric("구글계정 입력", f"{google_filled}개사")
            c3.metric("계정 미입력", f"{no_google}개사")

            if no_google > 0:
                st.warning(f"⚠️ {no_google}개사는 구글계정이 없어 캘린더 공유가 불가합니다. "
                           f"기업 관리 탭에서 구글계정을 먼저 입력하세요.")
            already_created = len(ind_cals)
            remaining = len(df_c) - already_created
            if already_created > 0:
                st.info(f"이미 생성된 캘린더: {already_created}개사 / 새로 생성할: {remaining}개사")

            st.divider()
            st.warning("⚠️ 실행 전 테스트 탭에서 먼저 동작을 확인하세요.")

            col1, col2 = st.columns(2)
            with col1:
                confirm_text = st.text_input("확인코드 입력", placeholder="캘린더생성",
                                              key="cal_create_confirm")
            with col2:
                st.caption("확인코드: **캘린더생성**")

            if st.button("🗓 전체 캘린더 일괄 생성", type="primary", key="create_all_cal"):
                if confirm_text != "캘린더생성":
                    st.error("확인코드를 입력해주세요.")
                else:
                    prog = st.progress(0, text="캘린더 생성 중...")
                    logs = []; ok = 0; fail = 0

                    for i, (_, row) in enumerate(df_c.iterrows()):
                        co       = row.get('기업명', '')
                        g_email  = str(row.get('구글계정', '') or '').strip()
                        interest = str(row.get('관심사업분야', '') or '')[:30]
                        keywords = str(row.get('기술키워드', '') or '')[:40]

                        if co in ind_cals:
                            logs.append(f"⏭ {co} — 이미 생성됨")
                            prog.progress((i+1)/len(df_c), text=f"{i+1}/{len(df_c)} 처리 중...")
                            continue

                        try:
                            cal_id = cal_create(
                                f"[원스톱] {co} 지원공고 D-day",
                                f"혁신제품지원센터 원스톱 스케일업 프로그램\n기업: {co}\n관심분야: {interest}\n기술키워드: {keywords}\n문의: onestop.kipcc@gmail.com"
                            )
                            if not cal_id:
                                raise Exception("캘린더 생성 실패")

                            sub_link = f"https://calendar.google.com/calendar?cid={cal_id}"
                            shared   = False

                            if g_email and '@' in g_email:
                                shared = cal_share(cal_id, g_email)

                            ind_cals[co] = {
                                'calendar_id':    cal_id,
                                'google_account': g_email,
                                'shared':         shared,
                                'subscribe_link': sub_link,
                                'interest':       interest,
                            }
                            ok += 1
                            logs.append(f"✅ {co}" + (f" → {g_email} 공유완료" if shared else " (공유 대기)"))

                            # 5개마다 중간 저장
                            if ok % 5 == 0:
                                import json as _json
                                _c = _json.dumps(ind_cals, ensure_ascii=False).encode('utf-8')
                                drive_upload(drive, INDCAL_FILE, _c, "application/json")

                        except Exception as e:
                            fail += 1
                            logs.append(f"❌ {co}: {str(e)[:40]}")

                        prog.progress((i+1)/len(df_c), text=f"{i+1}/{len(df_c)} 처리 중...")

                    # 최종 저장
                    import json as _json
                    _c = _json.dumps(ind_cals, ensure_ascii=False).encode('utf-8')
                    drive_upload(drive, INDCAL_FILE, _c, "application/json")

                    st.success(f"✅ 완료 — 생성 {ok}개 / 실패 {fail}개")
                    with st.expander("처리 로그"):
                        for log in logs:
                            st.caption(log)
                    st.rerun()



elif page == "시스템 명세":
    st.title("시스템 명세")
    st.caption("원스톱 스케일업 공고 매칭 시스템 — 구조 및 운영 가이드")

    tab1, tab2, tab3, tab4 = st.tabs(["전체 흐름", "매칭 로직", "키워드 구조", "파일 구조"])

    # ── 탭1: 전체 흐름 ──────────────────────────────
    with tab1:
        st.subheader("원스톱 스케일업 시스템 전체 흐름")

        st.markdown("""
<div style="background:#16293F;
                                  border:1px solid #24405F;border-radius:12px;padding:24px;font-family:'Apple SD Gothic Neo',sans-serif;">

<h4 style="color:#F0F0F0;margin:0 0 20px;">📌 전체 파이프라인</h4>

<div style="display:flex;flex-direction:column;gap:4px;">

<!-- 단계 1 -->
<div style="background:#16293F;
                                  border:1px solid #24405F;border-radius:8px;padding:14px 18px;">
  <div style="display:flex;align-items:center;gap:12px;">
    <span style="background:#10B981;color:#fff;font-size:12px;font-weight:700;padding:3px 10px;border-radius:20px;">STEP 1</span>
    <span style="font-size:14px;font-weight:600;color:#F0F0F0;">기업 DB 구축</span>
    <span style="font-size:11px;color:#666666;margin-left:auto;">기수 시작 시 1회</span>
  </div>
  <div style="margin-top:10px;padding-left:4px;color:#AAAAAA;font-size:13px;line-height:1.8;">
    WALLA 신청서 → <code>walla_to_selected.py</code> → <code>선정기업_명단.xlsx</code> → 구글 드라이브<br>
    포함 정보: 기업명, 이메일, 소재지, 기업유형, TRL, 관심사업분야, 기술키워드, 핵심수요태그, 수출실적
  </div>
</div>

<div style="text-align:center;color:#10B981;font-size:18px;margin:2px 0;">↓</div>

<!-- 단계 2 -->
<div style="background:#16293F;
                                  border:1px solid #24405F;border-radius:8px;padding:14px 18px;">
  <div style="display:flex;align-items:center;gap:12px;">
    <span style="background:#10B981;color:#fff;font-size:12px;font-weight:700;padding:3px 10px;border-radius:20px;">STEP 2</span>
    <span style="font-size:14px;font-weight:600;color:#F0F0F0;">공고 수집</span>
    <span style="font-size:11px;color:#666666;margin-left:auto;">매주 월요일 (수동 실행)</span>
  </div>
  <div style="margin-top:10px;padding-left:4px;color:#AAAAAA;font-size:13px;line-height:1.8;">
    bizinfo API → 8개 분야 공고 수집 → <code>notices_db.xlsx</code><br>
    이후 Playwright 크롤링 → 공고 전문 → <code>notices_detail.xlsx</code>
  </div>
</div>

<div style="text-align:center;color:#10B981;font-size:18px;margin:2px 0;">↓</div>

<!-- 단계 3 -->
<div style="background:#16293F;
                                  border:1px solid #24405F;border-radius:8px;padding:14px 18px;">
  <div style="display:flex;align-items:center;gap:12px;">
    <span style="background:#10B981;color:#fff;font-size:12px;font-weight:700;padding:3px 10px;border-radius:20px;">STEP 3</span>
    <span style="font-size:14px;font-weight:600;color:#F0F0F0;">매칭 실행</span>
    <span style="font-size:11px;color:#666666;margin-left:auto;">격주 수요일 (수동 실행)</span>
  </div>
  <div style="margin-top:10px;padding-left:4px;color:#AAAAAA;font-size:13px;line-height:1.8;">
    50개사 × 전체 공고 → 7개 축 점수 계산 → 별점 판정 → 상위 N건 추출<br>
    출력: 기업별 ★★★/★★ 공고 목록 (소재지 강등 · 쏠림 페널티 · 세그먼트 부스트 적용)
  </div>
</div>

<div style="text-align:center;color:#10B981;font-size:18px;margin:2px 0;">↓</div>

<!-- 단계 4 -->
<div style="background:#16293F;
                                  border:1px solid #24405F;border-radius:8px;padding:14px 18px;">
  <div style="display:flex;align-items:center;gap:12px;">
    <span style="background:#3B82F6;color:#fff;font-size:12px;font-weight:700;padding:3px 10px;border-radius:20px;">STEP 4</span>
    <span style="font-size:14px;font-weight:600;color:#F0F0F0;">담당자 검토</span>
    <span style="font-size:11px;color:#666666;margin-left:auto;">격주 수~목 (수동)</span>
  </div>
  <div style="margin-top:10px;padding-left:4px;color:#AAAAAA;font-size:13px;line-height:1.8;">
    기업별 검토 탭 → 공고 상세 확인 + AI 분석 → ✅ 승인 / ❌ 제외<br>
    검토 상태 드라이브 자동 저장 → 이전/다음 버튼으로 50개사 순회
  </div>
</div>

<div style="text-align:center;color:#10B981;font-size:18px;margin:2px 0;">↓</div>

<!-- 단계 5 -->
<div style="background:#16293F;
                                  border:1px solid #24405F;border-radius:8px;padding:14px 18px;">
  <div style="display:flex;align-items:center;gap:12px;">
    <span style="background:#10B981;color:#fff;font-size:12px;font-weight:700;padding:3px 10px;border-radius:20px;">STEP 5</span>
    <span style="font-size:14px;font-weight:600;color:#F0F0F0;">발송</span>
    <span style="font-size:11px;color:#666666;margin-left:auto;">격주 목요일 (수동 실행)</span>
  </div>
  <div style="margin-top:10px;padding-left:4px;color:#AAAAAA;font-size:13px;line-height:1.8;">
    승인된 공고 → 기업별 HTML 메일 발송 (Gmail API)<br>
    메일 내 공고카드: 공고명 + 마감일 + <b style="color:#10B981;">매칭근거 자연어 한 줄</b><br>
    동시에: 공고 마감 D-7·D-3 → 기업별 구글 캘린더 이벤트 등록
  </div>
</div>

<div style="text-align:center;color:#10B981;font-size:18px;margin:2px 0;">↓</div>

<!-- 단계 6 -->
<div style="background:#16293F;
                                  border:1px solid #24405F;border-radius:8px;padding:14px 18px;">
  <div style="display:flex;align-items:center;gap:12px;">
    <span style="background:#F59E0B;color:#fff;font-size:12px;font-weight:700;padding:3px 10px;border-radius:20px;">STEP 6</span>
    <span style="font-size:14px;font-weight:600;color:#F0F0F0;">피드백 수집 · 개선</span>
    <span style="font-size:11px;color:#666666;margin-left:auto;">상시</span>
  </div>
  <div style="margin-top:10px;padding-left:4px;color:#AAAAAA;font-size:13px;line-height:1.8;">
    기업 회신 메일 → Gmail API 읽기 → Claude 키워드 추출 → 기업 키워드 보완 자동 저장<br>
    검토 제외 패턴 → 피드백 루프 → 다음 매칭 자동 감점<br>
    신청여부·선정결과 → 발송 이력 입력 → 분기 성과 집계
  </div>
</div>

</div>
</div>
        """, unsafe_allow_html=True)

        st.divider()
        st.subheader("📊 점수 계산 한눈에 보기")
        st.markdown("""
| 매칭 축 | 계산 방식 | 기본 점수 | 최대 점수 |
|---------|-----------|-----------|-----------|
| **축1 지원대상** | TARGET_KW 카테고리 매칭 건수 × 가중치 | ×3점 | ~15점 |
| **축2 사업성격** | TYPE_KW 카테고리 매칭 건수 × 가중치 | ×2점 | ~10점 |
| **축3 기업키워드** | 기업 키워드 → 공고 전문 직접 검색 | ×2점 | ~10점 |
| **축4 핵심수요** | 핵심수요태그 → 공고 직접 매칭 | ×3점 | ~9점 |
| **축5 업종역방향** | 제품분야 → INDUSTRY_KW → 공고 간접매칭 | ×1점 | ~6점 |
| **축6 소재지** | 지역 일치 +3점 / 불일치 -5점 | ±점 | +3 / -5 |
| **축7 세그먼트** | 기업 유형별 사업성격 부스트 | +1~4점 | +4점 |
| **★ 별점 보너스** | ★★★ 판정 시 추가 가산 | +5점 | +5점 |
| **쏠림 페널티** | 이미 많은 기업에 추천된 공고 감산 | -3~-20점 | — |
| **피드백 페널티** | 과거 자주 제외한 사업성격 감산 | -3~-6점 | — |

**별점 판정 기준**
- ★★★ : 핵심수요 직접매칭 / 조달+공공조달 / 조달+해외진출 / 수출+해외진출 / 기업키워드+공공조달
- ★★  : 기업키워드+사업성격 / 조달·수출+마케팅·인증 / 중소벤처+조달·해외진출
- 소재지 불일치 시 강제 강등: ★★★→★★, ★★→★ (★는 제외)
        """)

        st.divider()
        st.subheader("🔄 키워드 개선 루프")
        st.markdown("""
```
기업 DB 구축 (기술키워드 · 핵심수요태그)
    ↓
매칭 실행 → 점수 계산
    ↓
담당자 검토 → 제외 패턴 수집
    ↓ (피드백 반영 버튼)
keywords.json 업데이트 → 다음 매칭 자동 반영
    ↓
기업 회신 메일 → Claude 키워드 추출
    ↓
키워드보완 컬럼 업데이트 → 다음 매칭 정확도 향상
    ↓ (반복)
매칭 품질 점진적 개선
```
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

기업마당 크롤링 (공고 수집 탭에서 수동 실행)
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
        st.subheader("전체 매칭 점수 체계")
        st.markdown("""
**기본 구조: 공고 1건 × 기업 1개사 → 점수 계산 → 별점 판정**

최종 점수 = 지원대상 + 사업성격 + 기업키워드 + 핵심수요 + 업종역방향 + 소재지 + 세그먼트부스트 + 피드백페널티
        """)

        st.divider()
        st.subheader("① 사전 필터 (점수 계산 전 자동 제외)")
        st.markdown("""
| 조건 | 제외 이유 |
|------|-----------|
| 마감일 지난 공고 | 신청 불가 |
| 이미 발송한 공고 | 중복 발송 방지 (send_history 체크) |
| 수신거부 기업 | 기업 관리 탭 수신거부=Y |
| 수출실적 없음 + 수출 전용 분야 | 자격 미달 |
| 제외 키워드 포함 공고 | 키워드 관리 탭에서 설정 가능 |
| 업력 초과 (창업 N년 이내 공고) | 설립연도 기반 자동 계산 |
| 예비창업자 전용 공고 | "예비창업자", "창업팀" 등 명시 |
        """)

        st.divider()
        st.subheader("② 매칭 점수 계산 (7개 축)")
        st.markdown("""
**축1. 지원대상 매칭 (+W_TARGET점/건)**
- 공고 텍스트에서 TARGET_KW(조달기업특화/수출기업특화/중소벤처일반) 탐색
- 매칭된 키워드 수 × 가중치(기본 3점)

**축2. 사업성격 매칭 (+W_TYPE점/건)**
- 공고 텍스트에서 TYPE_KW(공공조달/해외진출/마케팅/인증/기술개발/금융/내수/인력) 탐색
- 매칭된 키워드 수 × 가중치(기본 2점)

**축3. 기업키워드 직접매칭 (+W_KW점/건)**
- 기업의 기술키워드 + 제품분야 + 키워드보완 + 핵심수요태그를 공고 전문에서 직접 검색
- 매칭된 키워드 수 × 가중치(기본 2점)
- **역매핑 확장**: 기업 기술키워드 → INDUSTRY_KW 카테고리 → 공고에서 유사어 검색 (3자 이상 포함관계)

**축4. 핵심수요 태그 매칭 (+W_DEMAND점/건)**
- 기업 핵심수요태그가 공고에 직접 등장하면 가산 (가중치 3점, 가장 높음)
- 예: "G-PASS" 기업 + "G-PASS 등록 지원" 공고 → +3점

**축5. 업종 역방향 매칭 (+W_IND점)**
- 기업의 제품분야(WALLA 15개 카테고리) → INDUSTRY_KW → 공고에서 업종 키워드 매칭
- 카테고리 단위로 최대 +6점

**축6. 소재지 (+W_LOC점 또는 -5점)**
- 공고명 [] 패턴 → 주관기관 지자체 → 전문내용 "○○ 소재" 패턴 순으로 감지
- 일치: +2~3점 / 불일치: -3~5점
- **불일치 시 별점 강등**: ★★★→★★, ★★→★ (★는 최종 제외)

**축7. 세그먼트 부스트 (+최대 W_SEG점)**
- 기업을 4개 세그먼트로 자동 분류: 조달강화형/해외진출형/기술개발형/일반형
- 세그먼트에 맞는 사업성격 카테고리에 추가 점수
        """)
        with st.expander("세그먼트 분류 기준"):
            st.markdown("""
| 세그먼트 | 분류 조건 | 부스트 |
|---------|-----------|--------|
| 조달강화형 | 혁신제품·G-PASS·우수조달 태그 있거나, TRL 8~9이면서 수출실적 없음 | 공공조달 +4, 해외진출 +2 |
| 해외진출형 | 수출실적 있거나 해외조달·수출바우처 태그 있음 | 해외진출 +4, 마케팅홍보 +2 |
| 기술개발형 | TRL 4~6이거나 기술사업화·특허·R&D 태그 있음 | 기술개발 +4, 인증특허 +2 |
| 일반형 | 위 해당 없음 | 전 유형 균등 +1 |
            """)

        st.divider()
        st.subheader("③ 별점 판정 기준")
        st.markdown("""
| 별점 | 조건 (아래 중 하나 이상 해당) |
|------|-------------------------------|
| ★★★ | 핵심수요태그 직접매칭 |
| ★★★ | 조달기업특화 + 공공조달 |
| ★★★ | 조달기업특화 + 해외진출 |
| ★★★ | 수출기업특화 + 해외진출 |
| ★★★ | 기업키워드 매칭 + 공공조달 |
| ★★ | 기업키워드 매칭 + 사업성격 |
| ★★ | 조달·수출기업 + 마케팅·인증·기술개발 |
| ★★ | 중소벤처일반 + 공공조달 또는 해외진출 |
| ★★ | 수출국가 매칭 + 조달 또는 해외 |
        """)

        st.divider()
        st.subheader("④ 공고 쏠림 페널티")
        st.markdown("""
같은 공고가 너무 많은 기업에게 추천되면 자동 감산:

| 추천 기업 수 | 점수 감산 |
|-------------|-----------|
| 2개사 이상 | -3점 |
| 4개사 이상 | -6점 |
| 7개사 이상 | -10점 |
| 10개사 이상 | -15점 |
| 15개사 이상 | -20점 (사실상 차단) |
        """)

        st.divider()
        st.subheader("⑤ 소재지 판단 우선순위")
        st.markdown("""
| 우선순위 | 감지 방법 | 예시 | 신뢰도 |
|----------|-----------|------|--------|
| 1순위 | 공고명 [] 패턴 | [경기] 중소기업 수출지원 | 최고 |
| 2순위 | 주관기관이 지자체 | 충청남도, 경기도청 | 높음 |
| 3순위 | 전문내용 "○○ 소재 기업" | "충남 소재 중소기업 대상" | 중간 |
| 4순위 | 전문내용 지역 언급 패턴 | "광주에 위치한", "경남 관내" | 보조 |
        """)

        st.divider()
        st.subheader("⑥ 피드백 루프")
        st.markdown("""
검토 완료 → "피드백 반영" 버튼 클릭 → 제외한 공고의 사업성격 패턴 집계 → keywords.json 저장

다음 매칭 실행 시 해당 기업에게 자주 제외된 사업성격 유형 감산:
- 2회 이상 제외 → -3점
- 3회 이상 제외 → -6점

**효과**: 사이클이 반복될수록 각 기업에게 맞지 않는 유형의 공고가 자동으로 걸러집니다.
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
| **notices_detail.xlsx** | **공고 전문 DB** | **공고 수집 탭에서 크롤링 실행** |
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
| **crawl_notices.py** | **공고 전문 크롤러 (앱 내 직접 실행)** |
| **walla_to_selected.py** | **WALLA → 선정기업 명단 변환 (선정 후 1회)** |

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
