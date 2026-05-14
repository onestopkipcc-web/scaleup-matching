# 깃허브 세팅 가이드

## 1단계: 깃허브 저장소 생성
1. github.com 접속 → 로그인
2. 우측 상단 + → New repository
3. Repository name: `scaleup-matching`
4. **Private** 선택 (보안)
5. Create repository 클릭

## 2단계: 로컬 폴더 초기화
작업 폴더에서 PowerShell 실행:
```bash
cd "C:\Users\fbwlg\Desktop\26년도\2. 원스톱\7. 정보 전달 체계 구축"
git init
git add .gitignore requirements.txt app.py
git add collect_notices.py matching.py send.py sync_calendars.py
git add create_category_calendars.py create_individual_calendars.py
git commit -m "초기 세팅"
git remote add origin https://github.com/본인계정/scaleup-matching.git
git push -u origin main
```

## 3단계: 보안 파일 제외 확인
아래 파일은 절대 push 하면 안 됨:
- credentials.json
- token.json
- *.xlsx (기업 개인정보)
- *.csv (기업 개인정보)
→ .gitignore에 이미 설정되어 있음

## 4단계: Streamlit Cloud 배포
1. share.streamlit.io 접속
2. GitHub 계정으로 로그인
3. New app → 저장소 선택 → Branch: main → Main file: app.py
4. Deploy 클릭
5. URL 생성됨 (팀원 공유)

## 5단계: Secrets 설정 (Streamlit Cloud)
Streamlit Cloud에서 credentials.json 내용을 환경변수로 설정:
Settings → Secrets 탭에 추가:
```toml
[google]
credentials = '''
{여기에 credentials.json 전체 내용 붙여넣기}
'''
```

## 6단계: 팀원 협업
팀원이 코드 수정 후:
```bash
git pull   # 최신 코드 받기
git add .
git commit -m "수정 내용"
git push   # 업로드
```
→ Streamlit Cloud 자동 재배포됨
