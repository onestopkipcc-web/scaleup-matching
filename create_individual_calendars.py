"""
create_individual_calendars.py
선정 50개사 기업별 개별 캘린더 자동 생성 + 공유

실행: python create_individual_calendars.py
결과:
  - 기업별 캘린더 자동 생성
  - 기업 담당자 구글 계정으로 공유 초대
  - individual_calendars.json (캘린더 ID 저장)
"""
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd
import json, os

WORK_DIR   = r'C:\Users\fbwlg\Desktop\26년도\2. 원스톱\7. 정보 전달 체계 구축'
WALLA_FILE = 'TEST_(WALLA) 2026년도 스케일업 프로그램 선정기업.xlsx'
SCOPES     = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]


def load_companies():
    col_map = {
        '기업명':   '(기본정보) 기업명을 입력해 주시기 바랍니다.',
        '구글계정': '구글 계정 이메일을 입력해 주시기 바랍니다.',  # 동의서 수집 후 추가
        '이메일':   '(기본정보) 담당자 이메일을 입력해 주시기 바랍니다.',
        '관심분야': '(수요파악) 관심있는 정부 사업 분야를 선택하여 주시기 바랍니다.(최대 2개 선택 가능)',
        '기술키워드':'(수요파악) 귀사 제품의 주요 기술/분야 키워드를 입력하여 주시기 바랍니다.',
    }
    raw = pd.read_excel(WALLA_FILE)
    df  = pd.DataFrame({k: raw[v] for k, v in col_map.items() if v in raw.columns})
    return df.fillna("")


def create_company_calendar(service, company_name, interest, keywords):
    """기업별 캘린더 생성 + 공개 구독 설정"""
    body = {
        'summary':     f"📢 {company_name} — 맞춤 지원공고 D-day",
        'description': (
            f"혁신제품지원센터 원스톱 스케일업 프로그램\n"
            f"기업: {company_name}\n"
            f"관심분야: {interest}\n"
            f"키워드: {keywords}\n"
            f"문의: onestop.kipcc@gmail.com"
        ),
        'timeZone': 'Asia/Seoul',
    }
    created = service.calendars().insert(body=body).execute()
    cal_id  = created['id']

    # 운영팀만 읽기 가능 (기본 비공개)
    # 기업 공유는 아래 share_calendar에서 처리
    return cal_id


def share_calendar(service, cal_id, google_email):
    """기업 담당자 구글 계정으로 캘린더 공유"""
    rule = {
        'scope': {'type': 'user', 'value': google_email},
        'role':  'reader',  # 읽기 전용
    }
    try:
        service.acl().insert(calendarId=cal_id, body=rule).execute()
        return True
    except HttpError as e:
        print(f"    ⚠ 공유 실패 ({google_email}): {e}")
        return False


def main():
    os.chdir(WORK_DIR)

    creds   = Credentials.from_authorized_user_file('token.json', SCOPES)
    service = build('calendar', 'v3', credentials=creds)

    df = load_companies()

    # 기존 생성된 캘린더 로드 (재실행 시 중복 방지)
    if os.path.exists('individual_calendars.json'):
        with open('individual_calendars.json', 'r', encoding='utf-8') as f:
            result = json.load(f)
        print(f"기존 캘린더 {len(result)}개 로드됨")
    else:
        result = {}

    print(f"\n총 {len(df)}개사 처리 시작\n{'='*50}")

    for _, row in df.iterrows():
        company     = row['기업명']
        google_acct = row.get('구글계정', row.get('이메일', ''))
        interest    = row.get('관심분야', '')
        keywords    = str(row.get('기술키워드', ''))[:50]

        # 이미 생성된 기업 스킵
        if company in result:
            print(f"  ⏭ 스킵 (기존): {company}")
            continue

        print(f"▶ {company}")

        # 캘린더 생성
        cal_id = create_company_calendar(service, company, interest, keywords)
        sub_link = f"https://calendar.google.com/calendar?cid={cal_id}"

        # 구글 계정 있으면 공유
        shared = False
        if google_acct and '@' in google_acct:
            shared = share_calendar(service, cal_id, google_acct)
            if shared:
                print(f"  ✓ 생성 + 공유 완료 → {google_acct}")
            else:
                print(f"  ✓ 생성 완료 (공유 실패 → 수동 공유 필요)")
        else:
            print(f"  ✓ 생성 완료 (구글 계정 미입력 → 공유 대기)")

        result[company] = {
            'calendar_id':    cal_id,
            'google_account': google_acct,
            'shared':         shared,
            'subscribe_link': sub_link,
            'interest':       interest,
        }

        # 중간 저장 (중단돼도 진행분 보존)
        with open('individual_calendars.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"완료! 총 {len(result)}개사 캘린더 생성")
    shared_count = sum(1 for v in result.values() if v.get('shared'))
    print(f"공유 완료: {shared_count}개사 / 공유 대기: {len(result)-shared_count}개사")
    print("individual_calendars.json 저장됨")


if __name__ == "__main__":
    main()
