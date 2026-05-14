"""
create_category_calendars.py
분야별 공통 캘린더 4개 생성 (운영팀 내부용)
→ 기술개발 / 수출 / 경영·금융 / 혁신제품

실행: python create_category_calendars.py
결과: category_calendars.json (캘린더 ID 저장)
"""
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json, os

WORK_DIR = r'C:\Users\fbwlg\Desktop\26년도\2. 원스톱\7. 정보 전달 체계 구축'
SCOPES   = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]

# ── 생성할 캘린더 정의 ────────────────────────────────
CATEGORY_CALENDARS = [
    {
        "key":         "tech",
        "summary":     "📡 스케일업 — 기술개발 공고 D-day",
        "description": "기술개발·R&D 관련 지원사업 공고 마감일 안내\n대상: 기술개발 분야 관심 선정기업\n문의: onestop.kipcc@gmail.com",
        "realm":       ["기술개발", "R&D", "기술"],
    },
    {
        "key":         "export",
        "summary":     "✈️ 스케일업 — 수출 공고 D-day",
        "description": "수출·해외진출 관련 지원사업 공고 마감일 안내\n대상: 수출 분야 관심 선정기업\n문의: onestop.kipcc@gmail.com",
        "realm":       ["수출", "해외진출", "글로벌"],
    },
    {
        "key":         "mgmt",
        "summary":     "💼 스케일업 — 경영·금융 공고 D-day",
        "description": "경영·금융 관련 지원사업 공고 마감일 안내\n대상: 경영·금융 분야 관심 선정기업\n문의: onestop.kipcc@gmail.com",
        "realm":       ["경영", "금융", "창업"],
    },
    {
        "key":         "innov",
        "summary":     "🏆 스케일업 — 혁신제품 공고 D-day",
        "description": "혁신제품·조달 관련 지원사업 공고 마감일 안내\n대상: 혁신제품 지정 선정기업\n문의: onestop.kipcc@gmail.com",
        "realm":       ["혁신제품", "조달", "G-PASS"],
    },
]


def main():
    os.chdir(WORK_DIR)
    creds   = Credentials.from_authorized_user_file('token.json', SCOPES)
    service = build('calendar', 'v3', credentials=creds)

    result = {}

    for cal_def in CATEGORY_CALENDARS:
        print(f"\n▶ 생성 중: {cal_def['summary']}")

        # 캘린더 생성
        body = {
            'summary':     cal_def['summary'],
            'description': cal_def['description'],
            'timeZone':    'Asia/Seoul',
        }
        created    = service.calendars().insert(body=body).execute()
        cal_id     = created['id']

        # 공개 구독 설정 (링크 아는 사람 누구나 읽기 가능)
        rule = {'scope': {'type': 'default'}, 'role': 'reader'}
        service.acl().insert(calendarId=cal_id, body=rule).execute()

        sub_link = f"https://calendar.google.com/calendar?cid={cal_id}"

        result[cal_def['key']] = {
            'calendar_id':    cal_id,
            'summary':        cal_def['summary'],
            'subscribe_link': sub_link,
            'realm':          cal_def['realm'],
        }

        print(f"  ✓ 생성 완료")
        print(f"  캘린더 ID:  {cal_id}")
        print(f"  구독 링크:  {sub_link}")

    # JSON 저장 (이후 스크립트에서 자동 로드)
    with open('category_calendars.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n" + "="*55)
    print("분야별 캘린더 4개 생성 완료!")
    print("category_calendars.json 저장됨")
    print("\n【구독 링크 요약】")
    for key, info in result.items():
        print(f"  {info['summary']}")
        print(f"  → {info['subscribe_link']}\n")


if __name__ == "__main__":
    main()
