# -*- coding: utf-8 -*-
"""keywords.json 의 제외 키워드를 드라이브에 써 넣는다. 로컬에서만 실행한다.

앱에는 제외 키워드 기능이 있지만 값을 넣는 화면이 없다. 그래서 이 스크립트로
넣는다. 목록을 고칠 일이 생기면 EXCLUDE 를 고치고 다시 돌리면 된다.

    python docs/제외키워드_설정.py            # 미리보기
    python docs/제외키워드_설정.py --write    # 실제 반영

근거: 「원스톱 스케일업서비스 멘토링 제공 방식 개편 내용 정리_UJH.pdf」 3쪽
  (제외할 사업분야 및 키워드)
    ① 여성, 장애인, 지역기업 지원  ② 창업기업 지원  ③ 소상공인·전통시장
    ④ 인력 지원 분야  ⑤ 기타 인증 및 지정 제도 + '수출'
  (제외 대상 판정 기준) 아래 중 하나라도 해당하면 '제외'
    · 특정 대상 한정 사업 · 창업 단계 전용 사업
    · 인증·지정·제도 운영 목적 사업 · 수출·해외 진출 목적 사업

⑤(인증·지정 제도)와 '수출'은 넣지 않았다. 그 기준은 매트릭스 분류용이고,
시범구매·혁신제품 지정 공고는 선정기업이 가장 기다리는 공고다. 앱의 HIGH
키워드가 '혁신제품·혁신조달·해외조달'로 가점을 주고 있는 것과도 충돌한다.
— 담당자 확인이 필요한 부분으로 따로 보고했다(2026-10-27).

'지역기업'(①)도 키워드로 넣지 않았다. 공고명의 지역명은 소재지가산(6점)과
claude_analyze 의 지역적합 판정이 이미 본다. 키워드로 자르면 전국 사업까지
날아간다.

주의: app.py 의 score_notice 는 이 키워드를 **공고명에서만** 찾고, 공고명에
EXCL_GUARD(조달·혁신제품 등)가 있으면 적용하지 않는다. 전문까지 보면 본문에
한 번 스친 단어로 멀쩡한 조달 공고가 사라진다('소상공인' 공고명 22종 vs
전문까지 79종).
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from crawl_notices import DRIVE_FOLDER_ID, drive_download, gapi, get_creds  # noqa: E402

NAME = "keywords.json"

EXCLUDE = {
    # ③ 소상공인·전통시장 / ① 특정 대상 한정
    "특정대상한정": ["소상공인", "자영업", "전통시장", "상인회",
                     "장애인기업", "여성기업", "사회적기업", "협동조합", "마을기업"],
    # ② 창업 단계 전용
    "창업단계전용": ["예비창업", "재창업", "프리랜서"],
    # 업종 한정 — 선정기업 50개사에 해당 업종이 없다
    "업종한정":     ["농업", "농가", "어업", "어민", "축산", "임업", "귀농", "귀어",
                     "관광", "숙박", "음식점", "문화예술", "예술산업", "공연"],
    # 기업 지원이 아닌 사업
    "대상아님":     ["주거", "전세", "월세", "출산", "육아", "복지",
                     "유학생", "대학생", "학자금"],
    # ④ 인력 지원 분야
    "인력지원":     ["고용", "일자리", "채용", "인턴십", "시니어"],
    # 포상·표창 — 지원사업이 아니라 상 받을 사람을 추천받는 공고다(풀에 105종).
    # 쓰면 안 되는 말도 확인했다: '유공'은 「자유공모」에, '시상'은 「전시상담회」에
    # 걸린다. '선정계획'은 「세계일류상품 선정계획」처럼 실제 지원사업이 27종이다.
    "포상표창":     ["포상", "표창", "유공자", "수출탑"],
}

FLAT = [k for group in EXCLUDE.values() for k in group]


def drive_upload_json(creds, name, body):
    """crawl_notices 의 drive_upload 는 mime 이 xlsx 로 고정돼 있어 json 을 못 올린다."""
    params = {'q': f"name='{name}' and '{DRIVE_FOLDER_ID}' in parents and trashed=false",
              'fields': 'files(id)', 'orderBy': 'modifiedTime desc'}
    r = gapi('GET', 'https://www.googleapis.com/drive/v3/files', creds, params=params)
    files = r.json().get('files', []) if r.ok else []
    fid = files[0]['id'] if files else None
    meta = {"name": name} if fid else {"name": name, "parents": [DRIVE_FOLDER_ID]}

    bnd, crlf = "boundary_kipcc_scaleup", b"\r\n"
    data = b"".join([
        b"--" + bnd.encode() + crlf,
        b"Content-Type: application/json; charset=UTF-8" + crlf + crlf,
        json.dumps(meta).encode("utf-8") + crlf,
        b"--" + bnd.encode() + crlf,
        b"Content-Type: application/json" + crlf + crlf,
        body + crlf,
        b"--" + bnd.encode() + b"--" + crlf])
    url = (f'https://www.googleapis.com/upload/drive/v3/files/{fid}' if fid
           else 'https://www.googleapis.com/upload/drive/v3/files')
    resp = gapi('PATCH' if fid else 'POST', url, creds,
                params={'uploadType': 'multipart'}, data=data,
                headers={'Content-Type': f'multipart/related; boundary={bnd}'})
    return resp.ok, (resp.text[:300] if not resp.ok else '저장됨')


def main():
    write = "--write" in sys.argv
    creds = get_creds()
    raw = drive_download(creds, NAME)
    kw = json.loads(raw.decode("utf-8")) if raw else {}
    print(f"현재 keywords.json 키: {sorted(kw)}")
    print(f"현재 exclude_keywords {len(kw.get('exclude_keywords', []))}개\n")
    print(f"넣을 키워드 {len(FLAT)}개:")
    for g, ks in EXCLUDE.items():
        print(f"  {g:<12} {len(ks):>2}개  {', '.join(ks)}")
    assert len(set(FLAT)) == len(FLAT), "중복 키워드 있음"

    if not write:
        print("\n[미리보기] --write 를 붙이면 반영한다.")
        return

    kw["exclude_keywords"] = FLAT
    ok, info = drive_upload_json(
        creds, NAME, json.dumps(kw, ensure_ascii=False, indent=2).encode("utf-8"))
    print(f"\n업로드 {'성공' if ok else '실패'} — {info}")
    if not ok:
        sys.exit(1)
    back = json.loads(drive_download(creds, NAME).decode("utf-8"))
    print(f"확인 — exclude_keywords {len(back.get('exclude_keywords', []))}개 / "
          f"다른 키 유지 {sorted(k for k in back if k != 'exclude_keywords')}")


if __name__ == "__main__":
    main()
