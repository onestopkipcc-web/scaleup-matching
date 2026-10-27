# 다른 PC에서 이어서 작업하기

USB 없이, 아무것도 메일로 보내지 않고 세팅하는 법.

인증 파일 3개(`token.json` · `credentials.json` · `.streamlit/secrets.toml`)는
깃허브에 올리지 않는다. 구글 계정 접근 권한과 비밀번호가 들어 있어서다.
**옮기는 대신 다시 만든다.** 필요한 값은 전부 Streamlit Cloud 설정 화면에
이미 들어 있고, 거기는 브라우저 로그인만으로 들어간다.

---

## 0. 먼저 — 정말 필요한가

| 하려는 일 | 세팅 필요? |
|---|---|
| 공고 매칭·검토·발송 | **필요 없음.** 배포된 웹앱에서 한다 |
| 결과 엑셀 내려받기 | **필요 없음** |
| 코드 읽기 | 클론만 하면 됨 |
| 코드 고치고 로컬에서 띄우기 | 1~3 전부 |
| 드라이브 데이터 직접 작업 | 1~2 |

실무는 웹앱으로 다 된다. 아래는 코드를 만질 때만 필요하다.

---

## 1. 레포 받기

```bash
git clone https://github.com/onestopkipcc-web/scaleup-matching.git
cd scaleup-matching
pip install -r requirements.txt
```

## 2. `token.json` 만들기 — 구글 드라이브 접근

재인증할 필요 없다. **지금 쓰는 토큰이 Streamlit Cloud Secrets 안에 그대로
들어 있다.**

1. <https://share.streamlit.io> 로그인 → 이 앱 → `⋮` → **Settings** → **Secrets**
2. `[google]` 아래 `token = '...'` 의 **작은따옴표 안쪽 전체**를 복사
   (`{"token": "...", "refresh_token": "...", ...}` 모양의 JSON 한 덩어리다)
3. 레포 폴더에 `token.json` 이라는 이름으로 붙여넣고 저장

`app.py` 가 `st.secrets['google']['token']` 에서 읽는 값과 같은 것이다
(`app.py` 의 `get_creds`). 파일로 두면 로컬 스크립트도 같은 걸 쓴다.

> `credentials.json` 은 **필요 없다.** `token.json` 안에 `client_id` 와
> `client_secret` 이 같이 들어 있어서 갱신까지 혼자 된다. 토큰을 아예 새로
> 발급해야 할 때만 구글 클라우드 콘솔에서 내려받아 `refresh_token.py` 를
> 돌린다.

## 3. `.streamlit/secrets.toml` 만들기 — 로컬 실행용

같은 Secrets 화면에 값이 다 있다. 키 3개만 옮겨 적으면 된다.

```toml
local_dev = "true"
ANTHROPIC_API_KEY = "sk-ant-..."   # Secrets 화면의 같은 키 값
password_staff = "..."             # Secrets 화면의 같은 키 값
```

없으면 로그인이 안 되고 AI 분석도 안 된다.

```bash
python -m streamlit run app.py
```

## 4. 엑셀 원본이 필요한 경우

`*.xlsx` 는 개인정보가 들어 있어 깃에 올리지 않는다.

- `선정기업_명단.xlsx` — **받을 필요 없다.** 앱이 드라이브에서 읽는다.
  로컬 스크립트도 `drive_download` 로 가져오면 된다
- `_한국조달연구원_2026_…_20260615_.xlsx` — 명단을 **재생성**할 때만 필요하다
  (`walla_to_selected.py`). 드라이브의 원본 폴더에서 받는다

---

## 끝나고 — 공용 PC였다면

`token.json` 과 `.streamlit/secrets.toml` 을 지우고 간다. 이 두 파일만 있으면
드라이브와 메일 발송 권한이 그대로 넘어간다.
