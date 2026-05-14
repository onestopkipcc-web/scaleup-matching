"""
collect_notices.py
bizinfo API 공고 수집 → notices_db.csv 누적 저장
- pblancId 기준 중복 방지
- 수정된 공고 자동 업데이트
- 주 1회 실행 권장
"""
import requests
import pandas as pd
from datetime import datetime
import re, os

API_KEY  = "Nt604D"
BASE_URL = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
WORK_DIR = r'C:\Users\fbwlg\Desktop\26년도\2. 원스톱\7. 정보 전달 체계 구축'
DB_FILE  = "notices_db.csv"

REALM_CODES = ["01","02","03","04","05","06","07","09"]


def strip_html(html):
    return re.sub(r'<[^>]+>', ' ', html or '').strip()


def parse_deadline(reqst_str):
    try:
        end_str = reqst_str.split('~')[-1].strip()
        end_str = re.sub(r'\.', '-', end_str)
        return datetime.strptime(end_str, "%Y-%m-%d").strftime("%Y-%m-%d")
    except:
        return ""


def fetch_all():
    all_items, seen = [], set()
    for code in REALM_CODES:
        params = {
            "crtfcKey": API_KEY, "dataType": "json",
            "searchCnt": "0", "searchLclasId": code,
        }
        try:
            items = requests.get(BASE_URL, params=params, timeout=30).json().get('jsonArray', [])
            for item in items:
                pid = item.get('pblancId', '')
                if pid and pid not in seen:
                    seen.add(pid)
                    all_items.append(item)
            print(f"  분야코드 {code}: {len(items)}건")
        except Exception as e:
            print(f"  분야코드 {code} 오류: {e}")
    return all_items


def to_row(item):
    return {
        "pblancId":   item.get('pblancId', ''),
        "공고명":     item.get('pblancNm', ''),
        "주관기관":   item.get('jrsdInsttNm', ''),
        "분야":       item.get('pldirSportRealmLclasCodeNm', ''),
        "세부분야":   item.get('pldirSportRealmMlsfcCodeNm', ''),
        "접수기간":   item.get('reqstBeginEndDe', ''),
        "마감일":     parse_deadline(item.get('reqstBeginEndDe', '')),
        "지원대상":   item.get('trgetNm', ''),
        "사업개요":   strip_html(item.get('bsnsSumryCn', ''))[:500],
        "해시태그":   item.get('hashtags', ''),
        "공고링크":   item.get('pblancUrl', ''),
        "수정일":     item.get('updtPnttm', ''),
        "수집일":     datetime.today().strftime("%Y-%m-%d"),
    }


def main():
    os.chdir(WORK_DIR)

    # 기존 DB 로드
    if os.path.exists(DB_FILE):
        df_existing = pd.read_csv(DB_FILE, dtype=str).fillna("")
        existing_map = {row['pblancId']: row['수정일']
                        for _, row in df_existing.iterrows()}
        print(f"기존 공고 DB: {len(df_existing)}건")
    else:
        df_existing = pd.DataFrame()
        existing_map = {}
        print("공고 DB 없음 → 새로 생성")

    # API 수집
    print("\nAPI 수집 중...")
    all_items = fetch_all()
    print(f"\n전체 수집: {len(all_items)}건")

    # 신규/업데이트 분류
    new_rows, updated_rows = [], []
    for item in all_items:
        pid = item.get('pblancId', '')
        if not pid:
            continue
        row = to_row(item)
        if pid not in existing_map:
            new_rows.append(row)
        elif existing_map[pid] != item.get('updtPnttm', ''):
            updated_rows.append(row)

    print(f"신규: {len(new_rows)}건 / 업데이트: {len(updated_rows)}건")

    # DB 갱신
    if not df_existing.empty:
        updated_ids = {r['pblancId'] for r in updated_rows}
        df_keep = df_existing[~df_existing['pblancId'].isin(updated_ids)]
        df_new  = pd.DataFrame(new_rows + updated_rows)
        df_final = pd.concat([df_keep, df_new], ignore_index=True)
    else:
        df_final = pd.DataFrame(new_rows)

    df_final.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {DB_FILE} (총 {len(df_final)}건)")


if __name__ == "__main__":
    main()
