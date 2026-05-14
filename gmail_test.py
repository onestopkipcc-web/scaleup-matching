import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]

# ── 수신자 (테스트용) ─────────────────────────────────
TEST_RECIPIENTS = [
    "fbwlgns819@naver.com",
    "fbwlgns819@kip.re.kr",
]

# ── 샘플 공고 데이터 (실제 운영 시 매칭결과에서 자동 입력) ──
sample_notice = {
    "공고명":   "2026년 혁신제품 시범구매 사업자 모집",
    "주관기관": "조달청",
    "접수기간": "2026.05.01 ~ 2026.05.31",
    "공고링크": "https://www.bizinfo.go.kr",
    "사업개요": "혁신제품 지정기업을 대상으로 공공기관 시범구매를 지원하는 사업입니다.",
}

def build_mail_body(notice):
    return f"""
안녕하세요.
혁신제품지원센터 원스톱 스케일업 프로그램 운영팀입니다.

귀사의 관심 분야와 관련된 지원사업 공고를 안내드립니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
■ 공고명:   {notice['공고명']}
■ 주관기관: {notice['주관기관']}
■ 접수기간: {notice['접수기간']}
■ 공고링크: {notice['공고링크']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ 사업개요
{notice['사업개요']}

문의사항은 아래 연락처로 부탁드립니다.
혁신제품지원센터 원스톱 스케일업 운영팀
E-mail: onestop.kipcc@gmail.com

※ 본 메일은 정보제공 수신에 동의하신 기업에 한해 발송됩니다.
   수신을 원치 않으실 경우 위 이메일로 문의해 주시기 바랍니다.
""".strip()

def send_mail(service, to, subject, body):
    msg = MIMEMultipart()
    msg['To']      = to
    msg['From']    = "onestop.kipcc@gmail.com"
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(
        userId='me',
        body={'raw': raw}
    ).execute()
    print(f"  발송 완료 → {to}")

# ── 실행 ─────────────────────────────────────────────
creds   = Credentials.from_authorized_user_file('token.json', SCOPES)
service = build('gmail', 'v1', credentials=creds)

subject = f"[원스톱 스케일업] 관련 지원사업 공고 안내 — {sample_notice['공고명']}"
body    = build_mail_body(sample_notice)

print("테스트 발송 시작...")
for recipient in TEST_RECIPIENTS:
    send_mail(service, recipient, subject, body)

print("\n완료. 메일함 확인해보세요.")