"""선정기업 설립연도 조사 — 조사 전용. 명단·앱·드라이브를 건드리지 않는다.

왜 필요한가
  「설립 7년 이하」(기술개발제품 시범구매) / 「업력 7년 이상」(도약 Jump-Up)
  처럼 업력이 걸린 공고가 매 회차 올라오는데, 선정기업 명단에 설립연도가
  없다. 2026-05 WALLA 신청서 56개 문항에 설립일을 묻는 항목이 아예 없었다.
  그래서 claude_analyze 가 자격을 가리지 못하고 전부 '검토'로 올린다.

왜 이 방식인가
  무료 공개 API 는 전부 막혀 있다(2026-10-27 확인).
    · 벤처확인기업 공시 — 벤처기업법 시행령 제18조의5 가 정한 공시 항목에
      설립일이 없다(상호·업종·법인등록번호·주소·전화·주요제품뿐)
    · 공공데이터 중소벤처기업부_벤처기업명단 — 12개 컬럼, 설립일·사업자번호 없음
    · sminfo — 설립일자는 자가진단 입력란일 뿐 조회 기능 없음
    · 국세청 사업자등록정보 — 상태조회는 과세유형·폐업일만. 진위확인은
      개업일을 *입력*으로 받는다
    · 국민연금 가입 사업장 내역 — 3인 이상 법인만 수록
  남은 임시방편이 기업 홈페이지 연혁이다.

어떻게 믿을 수 있게 하나
  ① 사업자등록번호로 동일 기업임을 확인한다. 한국 기업 홈페이지는 푸터에
     사업자등록번호를 거의 다 적는다. 명단 값과 일치하면 동명이인 위험이
     사라진다. 일치를 확인 못 하면 신뢰도를 낮춰 기록한다.
  ② 2019~2022년으로 나오는 기업은 값을 비운다. 업력 7년 경계(2026-7=2019)에
     걸려서, 연혁상 창업 연도와 법적 설립일의 차이가 결론을 뒤집는다.
     블루센이 그 예다 — 연혁은 2004년 시작이지만 2022년에 상호가 바뀌었다.
  ③ 근거 문구와 출처 URL 을 같이 남긴다. 나중에 의심스러우면 되짚을 수 있게.

쓰는 법
    python 설립연도_조사.py                 # 전체(자체 도메인 보유 기업)
    python 설립연도_조사.py --limit 5       # 5개사만 시험
    python 설립연도_조사.py --name 테스토닉  # 한 기업만

결과는 설립연도_조사결과.xlsx 로 떨어진다. 명단에 반영하는 것은 사람이
검토한 뒤 따로 한다 — 이 스크립트는 아무것도 덮어쓰지 않는다.
"""
import argparse
import io
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROSTER = "선정기업_명단.xlsx"
OUT = "설립연도_조사결과.xlsx"

# 무료 메일은 홈페이지를 유추할 수 없다. 이 기업들은 기업명으로 따로 찾아야 한다.
FREE_MAIL = {
    "naver.com", "gmail.com", "hanmail.net", "daum.net", "nate.com",
    "kakao.com", "outlook.com", "hotmail.com", "yahoo.com", "empal.com",
    "korea.com", "hanmir.com", "dreamwiz.com",
}

# 연혁·회사소개 페이지로 보이는 링크. 사이트마다 영문/국문이 섞여 있다.
HISTORY_HINT = re.compile(
    r"연혁|회사\s*소개|기업\s*소개|회사\s*개요|about|history|company|greeting|intro",
    re.I)

# 「2004년 8월 법인 설립」 / 「설립일 : 2012-01-02」 / 「2012.01 (주)테스토닉 설립」
_RE_YEAR_THEN = re.compile(
    r"(19[6-9]\d|20[0-2]\d)\s*[년.\-/]?[^\n]{0,40}?(법인\s*설립|설립|창립|창업|설립일)")
_RE_THEN_YEAR = re.compile(
    r"(법인\s*설립|설립일자?|창립일?|창업일?)\s*[:：]?\s*(19[6-9]\d|20[0-2]\d)")

# 경계 구간 — 2026년 기준 업력 7년 선(2019)을 둘러싼 폭. 여기 들어오면 비운다.
BORDER = range(2019, 2023)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")


def norm_bizno(v):
    """사업자등록번호에서 숫자만. 명단은 하이픈 없이, 홈페이지는 있게 적는다."""
    return re.sub(r"\D", "", str(v or ""))


def fetch(url, timeout=12):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout,
                         allow_redirects=True, verify=False)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        r.encoding = r.apparent_encoding or r.encoding
        return r, ""
    except Exception as e:
        return None, f"{type(e).__name__}"


def page_text(resp):
    soup = BeautifulSoup(resp.text, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    return soup, re.sub(r"[ \t]+", " ", soup.get_text("\n"))


def find_year(text):
    """가장 이른 설립 연도와 근거 문구. 연혁은 최신순으로 적는 곳도 있어
    '가장 이른 것'을 고른다."""
    hits = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or len(line) > 200:
            continue
        for rx, gi in ((_RE_YEAR_THEN, 1), (_RE_THEN_YEAR, 2)):
            m = rx.search(line)
            if m:
                y = int(m.group(gi))
                if 1960 <= y <= 2026:
                    hits.append((y, line))
    if not hits:
        return None, ""
    hits.sort()
    return hits[0]


def history_links(soup, base):
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        label = (a.get_text(" ") or "") + " " + a["href"]
        if not HISTORY_HINT.search(label):
            continue
        u = urljoin(base, a["href"])
        if urlparse(u).netloc != urlparse(base).netloc:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out[:6]


def survey_company(name, bizno, domain):
    """한 기업 조사. (설립연도, 신뢰도, 근거, 출처URL, 비고)"""
    want = norm_bizno(bizno)
    for scheme in ("https://www.", "https://", "http://www.", "http://"):
        root = scheme + domain
        resp, err = fetch(root)
        if resp:
            break
    else:
        return None, "실패", "", "", f"홈페이지 접속 안 됨 ({err})"

    soup, text = page_text(resp)
    bizno_seen = want and want in norm_bizno(text)

    year, ev = find_year(text)
    src = resp.url
    if year is None:
        for u in history_links(soup, resp.url):
            r2, _ = fetch(u)
            if not r2:
                continue
            s2, t2 = page_text(r2)
            if want and not bizno_seen:
                bizno_seen = want in norm_bizno(t2)
            year, ev = find_year(t2)
            if year:
                src = r2.url
                break
            time.sleep(0.4)

    if year is None:
        return None, "실패", "", src, "연혁에서 설립 연도를 못 찾음"

    note = ""
    trust = "확인" if bizno_seen else "미확인"
    if not bizno_seen:
        note = "홈페이지에서 사업자등록번호를 못 찾아 동일 기업 확인 불가"
    if year in BORDER:
        note = (note + " / " if note else "") + \
            f"업력 7년 경계({min(BORDER)}~{max(BORDER)}) — 값을 쓰지 말 것"
        trust = "경계"
    return year, trust, ev[:160], src, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N개사만")
    ap.add_argument("--name", default="", help="기업명에 이 말이 든 곳만")
    a = ap.parse_args()

    if not os.path.exists(ROSTER):
        sys.exit(f"명단을 찾을 수 없습니다: {ROSTER}")
    df = pd.read_excel(ROSTER, header=1)
    df = df[df["선정구분"] == "선정"][["기업명", "사업자등록번호", "이메일", "소재지"]].copy()

    def dom(e):
        e = str(e)
        return e.split("@")[-1].strip().lower() if "@" in e else ""

    df["도메인"] = df["이메일"].map(dom)
    df["자체도메인"] = (~df["도메인"].isin(FREE_MAIL)) & (df["도메인"] != "")

    if a.name:
        df = df[df["기업명"].astype(str).str.contains(a.name, na=False)]

    todo = df[df["자체도메인"]]
    if a.limit:
        todo = todo.head(a.limit)

    print(f"선정 {len(df)}개사 · 자체 도메인 {int(df['자체도메인'].sum())}개사 "
          f"· 이번에 조사 {len(todo)}개사")

    rows = []
    for i, (_, r) in enumerate(todo.iterrows(), 1):
        y, trust, ev, src, note = survey_company(
            r["기업명"], r["사업자등록번호"], r["도메인"])
        mark = {"확인": "OK", "경계": "경계", "미확인": "약함", "실패": "--"}[trust]
        print(f"  [{i}/{len(todo)}] {mark:<4} {str(r['기업명'])[:20]:<22} "
              f"{y or '-'}  {note[:40]}")
        rows.append({
            "기업명": r["기업명"], "사업자등록번호": r["사업자등록번호"],
            "소재지": r["소재지"], "도메인": r["도메인"],
            "설립연도": y, "신뢰도": trust,
            "업력(2026기준)": (2026 - y) if y else None,
            "7년기준": ("" if (not y or trust == "경계")
                     else ("7년 이하" if 2026 - y <= 7 else "7년 이상")),
            "근거문구": ev, "출처": src, "비고": note,
        })
        time.sleep(0.6)

    # 홈페이지를 유추할 수 없는 곳은 기업명·사업자등록번호만 남겨 손으로 채우게.
    for _, r in df[~df["자체도메인"]].iterrows():
        rows.append({
            "기업명": r["기업명"], "사업자등록번호": r["사업자등록번호"],
            "소재지": r["소재지"], "도메인": r["도메인"],
            "설립연도": None, "신뢰도": "조사불가", "업력(2026기준)": None,
            "7년기준": "", "근거문구": "", "출처": "",
            "비고": "무료 메일을 써서 홈페이지를 유추할 수 없음 — 기업명으로 검색 필요",
        })

    out = pd.DataFrame(rows)
    with pd.ExcelWriter(OUT, engine="openpyxl") as w:
        out.to_excel(w, index=False, sheet_name="설립연도조사")
    print(f"\n{OUT} 저장 — 총 {len(out)}행")
    print(out["신뢰도"].value_counts().to_string())
    print("\n명단에는 아무것도 쓰지 않았습니다. 검토 후 사람이 반영하십시오.")


if __name__ == "__main__":
    requests.packages.urllib3.disable_warnings()
    main()
