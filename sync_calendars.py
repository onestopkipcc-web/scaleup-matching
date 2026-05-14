"""
sync_calendars.py
매칭·발송 승인된 공고를
→ 분야별 공통 캘린더 + 기업별 개별 캘린더에 동시 등록

send.py 발송 후 자동으로 호출되거나 단독 실행 가능
"""
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
import pandas as pd
import json, re, os, glob

WORK_DIR = r'C:\Users\fbwlg\Desktop\26년도\2. 원스톱\7. 정보 전달 체계 구축'
SCOPES   = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]

# 분야별 캘린더 매핑 키워드
REALM_MAP = {
    "tech":   ["기술개발","R&D","기술","연구"],
    "export": ["수출","해외","글로벌","무역"],
    "mgmt":   ["경영","금융","창업","융자","내수"],
    "innov":  ["혁신제품","조달","G-PASS","혁신"],
}


def parse_deadline(s):
    try:
        end = s.split('~')[-1].strip()
        return datetime.strptime(re.sub(r'\.', '-', end), "%Y-%m-%d")
    except:
        return None


def get_category_key(notice):
    """공고 분야 → 캘린더 키 결정"""
    text = f"{notice.get('공고명','')}{notice.get('분야','')}{notice.get('시스템매칭','')}"
    for key, keywords in REALM_MAP.items():
        if any(kw in text for kw in keywords):
            return key
    return "innov"  # 기본값: 혁신제품


def event_exists(service, cal_id, pblanc_id):
    try:
        ev = service.events().list(
            calendarId=cal_id,
            privateExtendedProperty=f"pblancId={pblanc_id}"
        ).execute()
        return len(ev.get('items', [])) > 0
    except:
        return False


def add_events(service, cal_id, notice, company_name, is_individual=False):
    """마감·D-7·D-3 이벤트 등록"""
    deadline  = parse_deadline(notice.get('접수기간', ''))
    if not deadline:
        return False

    pblanc_id = notice.get('공고ID', notice.get('pblancId', ''))
    if event_exists(service, cal_id, pblanc_id):
        return False  # 중복 스킵

    desc = (
        f"주관기관: {notice.get('주관기관','')}\n"
        f"접수기간: {notice.get('접수기간','')}\n"
        f"공고링크: {notice.get('공고링크','')}\n"
        + (f"안내기업: {company_name}" if is_individual else "")
    )

    for days, label in [(0,"마감"), (7,"D-7"), (3,"D-3")]:
        d = (deadline - timedelta(days=days)).strftime('%Y-%m-%d')
        service.events().insert(
            calendarId=cal_id,
            body={
                'summary':     f"[{label}] {notice.get('공고명','')}",
                'description': desc,
                'start': {'date': d, 'timeZone': 'Asia/Seoul'},
                'end':   {'date': d, 'timeZone': 'Asia/Seoul'},
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email',  'minutes': 60},
                        {'method': 'popup',  'minutes': 60},
                    ],
                },
                'extendedProperties': {'private': {'pblancId': pblanc_id}},
            }
        ).execute()
    return True


def main():
    os.chdir(WORK_DIR)

    creds   = Credentials.from_authorized_user_file('token.json', SCOPES)
    service = build('calendar', 'v3', credentials=creds)

    # 캘린더 ID 로드
    with open('category_calendars.json', encoding='utf-8') as f:
        cat_cals = json.load(f)

    ind_cals = {}
    if os.path.exists('individual_calendars.json'):
        with open('individual_calendars.json', encoding='utf-8') as f:
            ind_cals = json.load(f)

    # 가장 최근 매칭결과 로드
    files = sorted(glob.glob(os.path.join(WORK_DIR, "매칭결과_*.xlsx")), reverse=True)
    if not files:
        print("❌ 매칭결과 파일 없음"); return

    df = pd.read_excel(files[0], header=1).fillna("")
    df.columns = [c.replace('\n(○/✕)', '').replace('\n', '') for c in df.columns]
    approved = df[df['담당자검토'] == '○']

    print(f"승인 건: {len(approved)}건\n{'='*50}")

    cat_count = ind_count = 0

    for _, notice in approved.iterrows():
        company   = notice.get('기업명', '')
        notice_d  = notice.to_dict()

        print(f"▶ {company} — {notice.get('공고명','')[:30]}")

        # ① 분야별 공통 캘린더 등록
        cat_key = get_category_key(notice_d)
        cat_id  = cat_cals.get(cat_key, {}).get('calendar_id', '')
        if cat_id:
            if add_events(service, cat_id, notice_d, company, is_individual=False):
                print(f"  ✓ 공통 캘린더({cat_key}) 등록")
                cat_count += 1
            else:
                print(f"  ⏭ 공통 캘린더({cat_key}) 이미 등록됨")

        # ② 기업별 개별 캘린더 등록
        ind_info = ind_cals.get(company, {})
        ind_id   = ind_info.get('calendar_id', '')
        if ind_id:
            if add_events(service, ind_id, notice_d, company, is_individual=True):
                print(f"  ✓ 개별 캘린더 등록")
                ind_count += 1
            else:
                print(f"  ⏭ 개별 캘린더 이미 등록됨")
        else:
            print(f"  ⚠ 개별 캘린더 없음 → create_individual_calendars.py 실행 필요")

    print(f"\n{'='*50}")
    print(f"완료! 공통 캘린더 {cat_count}건 / 개별 캘린더 {ind_count}건 등록")


if __name__ == "__main__":
    main()
