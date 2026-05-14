from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]

os.chdir(r'C:\Users\fbwlg\Desktop\26년도\2. 원스톱\7. 정보 전달 체계 구축')

creds   = Credentials.from_authorized_user_file('token.json', SCOPES)
service = build('calendar', 'v3', credentials=creds)

# 삭제할 캘린더 선택
# 'primary'        → 기본 캘린더 (onestop.kipcc@gmail.com)
# calendar_id.txt  → 공통 캘린더
cal_id = open('calendar_id.txt').read().strip()

print("이벤트 목록 불러오는 중...")
deleted = 0

while True:
    events = service.events().list(
        calendarId=cal_id,
        maxResults=250,        # 한 번에 최대 250개
        singleEvents=True,
    ).execute()

    items = events.get('items', [])
    if not items:
        break

    for event in items:
        service.events().delete(calendarId=cal_id, eventId=event['id']).execute()
        print(f"  삭제: {event.get('summary', '(제목없음)')}")
        deleted += 1

print(f"\n완료 — 총 {deleted}건 삭제")