from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]

creds   = Credentials.from_authorized_user_file('token.json', SCOPES)
service = build('calendar', 'v3', credentials=creds)

# ── 공통 캘린더 생성 ──────────────────────────────────
calendar_body = {
    'summary':  '📢 원스톱 스케일업 — 지원공고 D-day',
    'description': (
        '혁신제품지원센터 원스톱 스케일업 프로그램\n'
        '선정기업 대상 지원사업 공고 마감일 안내 캘린더입니다.\n'
        '문의: onestop.kipcc@gmail.com'
    ),
    'timeZone': 'Asia/Seoul',
}

created = service.calendars().insert(body=calendar_body).execute()
calendar_id = created['id']

print(f"✓ 공통 캘린더 생성 완료")
print(f"  캘린더 ID: {calendar_id}")
print(f"  캘린더명:  {created['summary']}")

# ── 공개 구독 설정 ────────────────────────────────────
rule = {
    'scope': {'type': 'default'},  # 링크 아는 사람 누구나
    'role': 'reader',              # 읽기 전용
}
service.acl().insert(calendarId=calendar_id, body=rule).execute()
print(f"\n✓ 공개 구독 설정 완료")
print(f"  구독 링크: https://calendar.google.com/calendar?cid={calendar_id}")

# ── calendar_id 로컬 저장 (이후 스크립트에서 재사용) ──
with open('calendar_id.txt', 'w') as f:
    f.write(calendar_id)
print(f"\n✓ calendar_id.txt 저장 완료 (이후 스크립트에서 자동 로드)")