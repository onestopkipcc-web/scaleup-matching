"""
send.py
매칭결과_날짜.xlsx에서 ○ 승인 건만 읽어서
HTML 메일 발송 + 캘린더 이벤트 등록 + send_history.csv 기록
"""
import pandas as pd
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import base64, re, os, glob

WORK_DIR = r'C:\Users\fbwlg\Desktop\26년도\2. 원스톱\7. 정보 전달 체계 구축'

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]

TEST_MODE       = True
TEST_RECIPIENTS = ["fbwlgns819@naver.com", "fbwlgns819@kip.re.kr"]

CALENDAR_LINK = (
    "https://calendar.google.com/calendar?cid="
    "963198bcdb540c8939439a7325b0ff3ad6d1f57c374824b5498e37b74fd98997"
    "@group.calendar.google.com"
)


def parse_deadline(reqst_str):
    try:
        end_str = reqst_str.split('~')[-1].strip()
        return datetime.strptime(re.sub(r'\.', '-', end_str), "%Y-%m-%d")
    except:
        return None


def build_html(company_name, notices):
    rows=""
    for i,n in enumerate(notices,1):
        rows+=f"""
        <tr>
          <td style="padding:10px 8px;border-bottom:1px solid #e0e0e0;
                     font-weight:bold;color:#1F4E79;width:40px;">{i}. {n.get('관련도','')}</td>
          <td style="padding:10px 8px;border-bottom:1px solid #e0e0e0;">
            <a href="{n.get('공고링크','#')}"
               style="color:#2E75B6;font-weight:bold;text-decoration:none;">
              {n.get('공고명','')}
            </a>
          </td>
          <td style="padding:10px 8px;border-bottom:1px solid #e0e0e0;
                     color:#595959;width:100px;">{n.get('주관기관','')}</td>
          <td style="padding:10px 8px;border-bottom:1px solid #e0e0e0;
                     color:#595959;width:130px;">{n.get('접수기간','')}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<body style="margin:0;padding:0;background:#f5f5f5;font-family:'맑은 고딕',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:30px 0;">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
  <tr>
    <td style="background:#1F4E79;padding:24px 32px;">
      <p style="margin:0;color:#fff;font-size:13px;opacity:.8;">혁신제품지원센터</p>
      <h1 style="margin:6px 0 0;color:#fff;font-size:20px;font-weight:bold;">원스톱 스케일업 프로그램</h1>
    </td>
  </tr>
  <tr>
    <td style="padding:28px 32px 16px;">
      <p style="margin:0;font-size:15px;color:#222;">안녕하세요, <strong>{company_name}</strong> 담당자님.</p>
      <p style="margin:10px 0 0;font-size:14px;color:#444;line-height:1.7;">
        귀사의 관심 분야와 관련된 지원사업 공고 <strong>{len(notices)}건</strong>을 안내드립니다.
      </p>
    </td>
  </tr>
  <tr>
    <td style="padding:0 32px 24px;">
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid #e0e0e0;border-radius:6px;overflow:hidden;">
        <tr style="background:#2E75B6;">
          <td style="padding:10px 8px;color:#fff;font-size:12px;font-weight:bold;">순위</td>
          <td style="padding:10px 8px;color:#fff;font-size:12px;font-weight:bold;">공고명</td>
          <td style="padding:10px 8px;color:#fff;font-size:12px;font-weight:bold;">주관기관</td>
          <td style="padding:10px 8px;color:#fff;font-size:12px;font-weight:bold;">접수기간</td>
        </tr>
        {rows}
      </table>
    </td>
  </tr>
  <tr>
    <td style="padding:0 32px 28px;">
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#EBF3FB;border-radius:6px;">
        <tr><td style="padding:16px;">
          <p style="margin:0;font-size:13px;color:#1F4E79;font-weight:bold;">📅 공고 마감일 캘린더 구독</p>
          <p style="margin:8px 0 12px;font-size:13px;color:#444;line-height:1.6;">
            D-7·D-3 마감 알림을 받아보실 수 있습니다.
          </p>
          <a href="{CALENDAR_LINK}"
             style="display:inline-block;background:#1F4E79;color:#fff;
                    padding:10px 20px;border-radius:4px;font-size:13px;
                    font-weight:bold;text-decoration:none;">캘린더 구독하기</a>
        </td></tr>
      </table>
    </td>
  </tr>
  <tr>
    <td style="background:#f9f9f9;padding:18px 32px;border-top:1px solid #e0e0e0;">
      <p style="margin:0;font-size:12px;color:#888;line-height:1.8;">
        혁신제품지원센터 원스톱 스케일업 운영팀<br>
        E-mail: <a href="mailto:onestop.kipcc@gmail.com" style="color:#2E75B6;">onestop.kipcc@gmail.com</a><br>
        <span style="font-size:11px;color:#aaa;">
          ※ 본 메일은 정보제공 수신에 동의하신 기업에 한해 발송됩니다.
        </span>
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body></html>"""


def send_mail(gmail, to, company_name, notices):
    msg=MIMEMultipart('alternative')
    msg['To']=to; msg['From']="onestop.kipcc@gmail.com"
    msg['Subject']=f"[원스톱 스케일업] 맞춤 지원공고 {len(notices)}건 안내 — {company_name}"
    msg.attach(MIMEText(build_html(company_name,notices),'html','utf-8'))
    raw=base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId='me',body={'raw':raw}).execute()
    print(f"  ✉ 발송 → {to}")


def add_calendar_events(cal, cal_id, notice, company_name):
    deadline=parse_deadline(notice.get('접수기간',''))
    if not deadline: return
    pid=notice.get('공고ID','')

    try:
        existing=cal.events().list(
            calendarId=cal_id,
            privateExtendedProperty=f"pblancId={pid}"
        ).execute()
        if existing.get('items'): return
    except HttpError: pass

    desc=(f"주관기관: {notice.get('주관기관','')}\n"
          f"접수기간: {notice.get('접수기간','')}\n"
          f"공고링크: {notice.get('공고링크','')}\n"
          f"안내기업: {company_name}")

    for days,label in [(0,"마감"),(7,"D-7"),(3,"D-3")]:
        d=(deadline-timedelta(days=days)).strftime('%Y-%m-%d')
        event={
            'summary':f"[{label}] {notice.get('공고명','')}",
            'description':desc,
            'start':{'date':d,'timeZone':'Asia/Seoul'},
            'end':  {'date':d,'timeZone':'Asia/Seoul'},
            'reminders':{'useDefault':False,'overrides':[
                {'method':'email','minutes':60},{'method':'popup','minutes':60}]},
            'extendedProperties':{'private':{'pblancId':pid}},
        }
        cal.events().insert(calendarId=cal_id,body=event).execute()
    print(f"  📅 캘린더 등록 → {notice.get('공고명','')} (마감·D-7·D-3)")


def save_history(records, history_file):
    df_new=pd.DataFrame(records)
    if os.path.exists(history_file):
        df_old=pd.read_csv(history_file,dtype=str).fillna("")
        df_final=pd.concat([df_old,df_new],ignore_index=True)
    else:
        df_final=df_new
    df_final.to_csv(history_file,index=False,encoding="utf-8-sig")
    print(f"\n발송 이력 저장: {history_file} (누적 {len(df_final)}건)")


def main():
    os.chdir(WORK_DIR)

    # 가장 최근 매칭결과 파일
    files=sorted(glob.glob("매칭결과_*.xlsx"),reverse=True)
    if not files:
        print("❌ 매칭결과 파일 없음 → matching.py 먼저 실행하세요.")
        return
    result_file=files[0]
    print(f"로드: {result_file}")

    df=pd.read_excel(result_file,sheet_name="매칭결과",header=1)
    df=df.fillna("")
    df.columns=[c.replace('\n(○/✕)','').replace('\n','') for c in df.columns]

    approved=df[df['담당자검토']=='○']
    print(f"총 {len(df)}건 중 승인 {len(approved)}건\n")

    if approved.empty:
        print("승인된 건 없음 → 엑셀에서 ○ 입력 후 재실행하세요.")
        return

    creds =Credentials.from_authorized_user_file('token.json',SCOPES)
    gmail =build('gmail','v1',credentials=creds)
    cal   =build('calendar','v3',credentials=creds)
    cal_id=open('calendar_id.txt').read().strip()

    history_records=[]

    for company,group in approved.groupby('기업명'):
        notices=group.to_dict('records')
        print(f"▶ {company} — {len(notices)}건")

        recipients=TEST_RECIPIENTS if TEST_MODE else [group.iloc[0].get('이메일','')]
        for to in recipients:
            send_mail(gmail,to,company,notices)

        for n in notices:
            add_calendar_events(cal,cal_id,n,company)
            history_records.append({
                "기업명":    company,
                "pblancId":  n.get('공고ID',''),
                "공고명":    n.get('공고명',''),
                "발송일":    datetime.today().strftime("%Y-%m-%d"),
                "매칭점수":  n.get('점수',''),
                "담당자검토":n.get('담당자검토','○'),
                "검토의견":  n.get('검토의견',''),
                "신청여부":  "",
                "선정결과":  "",
            })
        print()

    save_history(history_records,"send_history.csv")
    print("="*55)
    print("완료! 메일함 + 캘린더 확인하세요.")


if __name__=="__main__":
    main()
