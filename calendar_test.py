from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import re

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]

# ── 샘플 공고 ──────────────────────────────────────────
sample_notices = [
    {
        "공고ID":   "PBLN_TEST_001",
        "공고명":   "2026년 혁신제품 시범구매 사업자 모집",
        "주관기관": "조달청",
        "접수기간": "2026.05.01 ~ 2026.06.15",
        "공고링크": "https://www.bizinfo.go.kr",
        "대상기업": ["(주)장성산업", "지노테크"],
    },
    {
        "공고ID":   "PBLN_TEST_002",
        "공고명":   "수출바우처 지원기업 모집(2차)",
        "주관기관": "한국무역보험공사",
        "접수기간": "2026.05.10 ~ 2026.06.30",
        "공고링크": "https://www.bizinfo.go.kr",
        "대상기업": ["(주)브레인테크", "주식회사 가나이엔지"],
    },
]

def parse_deadline(reqst_str):
    try:
        end_str = reqst_str.split('~')[-1].strip()
        end_str = re.sub(r'\.', '-', end_str)
        return datetime.strptime(end_str, "%Y-%m-%d")
    except:
        return None

def event_exists(service, pblanc_id):
    events = service.events().list(
        calendarId='primary',
        privateExtendedProperty=f'pblancId={pblanc_id}'
    ).execute()
    return len(events.get('items', [])) > 0

def add_dday_events(service, notice):
    deadline = parse_deadline(notice['접수기간'])
    if not deadline:
        print(f"  ⚠ 마감일 파싱 불가 → 스킵: {notice['공고명']}")
        return

    if event_exists(service, notice['공고ID']):
        print(f"  ⚠ 이미 등록됨 → 스킵: {notice['공고명']}")
        return

    companies = ", ".join(notice['대상기업'])
    desc = (
        f"공고링크: {notice['공고링크']}\n"
        f"주관기관: {notice['주관기관']}\n"
        f"접수기간: {notice['접수기간']}\n"
        f"대상기업: {companies}"
    )

    targets = [
        (0, f"[마감] {notice['공고명']}"),
        (7, f"[D-7] {notice['공고명']} 마감 7일 전"),
        (3, f"[D-3] {notice['공고명']} 마감 3일 전"),
    ]

    for days_before, summary in targets:
        event_date = deadline - timedelta(days=days_before)
        event = {
            'summary': summary,
            'description': desc,
            'start': {'date': event_date.strftime('%Y-%m-%d'), 'timeZone': 'Asia/Seoul'},
            'end':   {'date': event_date.strftime('%Y-%m-%d'), 'timeZone': 'Asia/Seoul'},
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 60},
                    {'method': 'popup', 'minutes': 60},
                ],
            },
            'extendedProperties': {
                'private': {'pblancId': notice['공고ID']}
            },
        }
        service.events().insert(calendarId='primary', body=event).execute()
        print(f"  ✓ 등록: {summary} ({event_date.strftime('%Y-%m-%d')})")

# ── 실행 ─────────────────────────────────────────────
creds   = Credentials.from_authorized_user_file('token.json', SCOPES)
service = build('calendar', 'v3', credentials=creds)

print("캘린더 D-day 이벤트 등록 시작...\n")
for notice in sample_notices:
    print(f"▶ {notice['공고명']}")
    add_dday_events(service, notice)
    print()

print("완료. 구글 캘린더에서 확인해보세요.")