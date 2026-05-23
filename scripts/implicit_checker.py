#!/usr/bin/env python3
"""
implicit_checker.py — 암묵지 항목 탐지 스크립트

AI가 정답을 알 수 없는 기관 고유 정보를 문서에서 패턴으로 추출한다.
추출된 값은 "맞다/틀리다" 판정 없이 사용자 확인용으로만 제시한다.

탐지 항목:
  - 발신 기관명 및 공문번호 (예: XX교육청-1234)
  - 담당자 이름
  - 담당자 연락처 (전화번호, 이메일)
  - 수신기관 명칭

사용법:
  python3 implicit_checker.py "<문서_텍스트>"
  python3 implicit_checker.py --file <텍스트_파일_경로>

출력: JSON 형태로 탐지 결과 반환
"""

import re
import sys
import json
import argparse


# ─────────────────────────────────────────
# 탐지 패턴 정의
# ─────────────────────────────────────────

# 공문번호: 기관명-번호(연도.월.일.) 또는 기관명-번호
DOC_NUMBER_PATTERN = re.compile(
    r'([가-힣a-zA-Z\s]{2,20})-(\d{3,6})(?:\((\d{4}\.\d{1,2}\.\d{1,2}\.?)\))?'
)

# 발신 기관명 단독 (공문 상단 "발신:" 또는 "발신기관:" 뒤)
SENDER_LABEL_PATTERN = re.compile(
    r'(?:발신|발신기관|발신처)\s*[:：]\s*([가-힣a-zA-Z\s]{2,30})'
)

# 수신기관 (수신: 뒤에 오는 값)
RECIPIENT_PATTERN = re.compile(
    r'(?:수신|수신처|수신자)\s*[:：]\s*([가-힣a-zA-Z,\s·]{2,60})'
)

# 담당자 이름 (성명, 담당자, 담당 뒤에 오는 2~4글자 한국어 이름)
STAFF_NAME_PATTERN = re.compile(
    r'(?:담당자?|성명|담당)\s*[:：]?\s*([가-힣]{2,4})'
)

# 전화번호 패턴 (02-, 031-, 010- 등)
PHONE_PATTERN = re.compile(
    r'(?:전화|TEL|Tel|tel|☎|전화번호)?\s*[:：]?\s*'
    r'(0\d{1,2}-\d{3,4}-\d{4})'
)

# 팩스 번호
FAX_PATTERN = re.compile(
    r'(?:팩스|FAX|Fax|fax)\s*[:：]?\s*(0\d{1,2}-\d{3,4}-\d{4})'
)

# 이메일
EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
)


# ─────────────────────────────────────────
# 탐지 함수
# ─────────────────────────────────────────

def detect_doc_numbers(text: str) -> list[dict]:
    """공문번호 및 발신 기관명 탐지"""
    results = []
    for m in DOC_NUMBER_PATTERN.finditer(text):
        agency = m.group(1).strip()
        number = m.group(2)
        date = m.group(3) or ""
        results.append({
            "agency": agency,
            "number": number,
            "date": date,
            "raw": m.group(0),
            "position": m.start()
        })
    return results


def detect_sender(text: str) -> list[str]:
    """발신기관 레이블 뒤 기관명 탐지"""
    results = []
    for m in SENDER_LABEL_PATTERN.finditer(text):
        results.append(m.group(1).strip())
    return list(set(results))


def detect_recipients(text: str) -> list[str]:
    """수신기관 명칭 탐지"""
    results = []
    for m in RECIPIENT_PATTERN.finditer(text):
        value = m.group(1).strip().rstrip(',·')
        results.append(value)
    return list(set(results))


def detect_staff_names(text: str) -> list[str]:
    """담당자 이름 탐지"""
    results = []
    for m in STAFF_NAME_PATTERN.finditer(text):
        name = m.group(1).strip()
        # 일반 명사 필터링 (2글자 이상 고유명사 추정)
        if len(name) >= 2:
            results.append(name)
    return list(set(results))


def detect_phone_numbers(text: str) -> dict:
    """전화번호 및 팩스 번호 탐지"""
    phones = list(set(m.group(1) for m in PHONE_PATTERN.finditer(text)))
    faxes = list(set(m.group(1) for m in FAX_PATTERN.finditer(text)))
    # 팩스와 전화 중복 제거
    phones = [p for p in phones if p not in faxes]
    return {"phone": phones, "fax": faxes}


def detect_emails(text: str) -> list[str]:
    """이메일 탐지"""
    return list(set(EMAIL_PATTERN.findall(text)))


# ─────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────

def analyze(text: str) -> dict:
    doc_numbers = detect_doc_numbers(text)
    senders = detect_sender(text)
    recipients = detect_recipients(text)
    staff_names = detect_staff_names(text)
    contacts = detect_phone_numbers(text)
    emails = detect_emails(text)

    # 공문번호에서 추출한 기관명을 발신기관 후보에 병합
    agency_candidates = senders[:]
    for dn in doc_numbers:
        if dn["agency"] not in agency_candidates:
            agency_candidates.append(dn["agency"])

    return {
        "implicit_items": {
            "발신_기관명": {
                "탐지값": agency_candidates,
                "확인_요청": "실제 발신 기관명과 일치하는지 확인해주세요."
            },
            "공문번호": {
                "탐지값": [dn["raw"] for dn in doc_numbers],
                "확인_요청": "번호 형식 및 연번이 현재 기준에 맞는지 확인해주세요."
            },
            "수신기관": {
                "탐지값": recipients,
                "확인_요청": "수신 대상이 올바른지 확인해주세요."
            },
            "담당자_이름": {
                "탐지값": staff_names,
                "확인_요청": "현재 담당자 이름이 맞는지 확인해주세요."
            },
            "전화번호": {
                "탐지값": contacts["phone"],
                "확인_요청": "현재 유효한 연락처인지 확인해주세요."
            },
            "팩스번호": {
                "탐지값": contacts["fax"],
                "확인_요청": "현재 유효한 팩스 번호인지 확인해주세요."
            },
            "이메일": {
                "탐지값": emails,
                "확인_요청": "현재 담당자 이메일이 맞는지 확인해주세요."
            }
        },
        "harness_checkpoints": [
            {"cp": "CP-04", "label": "발신 기관명 확인", "type": "암묵지", "status": "미완료"},
            {"cp": "CP-05", "label": "공문번호 형식·연번 확인", "type": "암묵지", "status": "미완료"},
            {"cp": "CP-06", "label": "담당자 이름 확인", "type": "암묵지", "status": "미완료"},
            {"cp": "CP-07", "label": "담당자 연락처 확인", "type": "암묵지", "status": "미완료"},
            {"cp": "CP-08", "label": "수신기관 명칭 확인", "type": "암묵지", "status": "미완료"},
        ],
        "note": "위 탐지값은 AI가 맞다/틀리다 판정하지 않습니다. 사용자가 직접 확인해주세요."
    }


def main():
    parser = argparse.ArgumentParser(description="공문서 암묵지 항목 탐지")
    parser.add_argument("text", nargs="?", help="분석할 텍스트 (직접 입력)")
    parser.add_argument("--file", help="분석할 텍스트 파일 경로")
    args = parser.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    result = analyze(text)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
