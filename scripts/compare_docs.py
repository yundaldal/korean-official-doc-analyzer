#!/usr/bin/env python3
"""
두 문서(과거 vs 현재) 비교 스크립트 — 미변경 항목 탐지

사용법 (v2 — 파일 경로 방식 우선, 긴 문서에서 쉘 인자 길이 문제 방지):
    python3 compare_docs.py \
        --old-file "<과거_문서_텍스트_파일_경로>" \
        --new-file "<현재_문서_텍스트_파일_경로>" \
        --source-year 2025 \
        --target-year 2026

    (--old-text/--new-text로 직접 텍스트를 넘기는 것도 가능하지만 긴 문서에는 쓰지 말 것 —
     v1에는 이 옵션이 강제라서, 파일 경로 문자열을 그대로 텍스트인 척 비교해버리는
     조용한 실패가 있었다. 항상 --old-file/--new-file을 우선 사용한다.)

출력(JSON):
    {
        "unchanged_critical":  [{"line": "...", "reason": "..."}],   # ⚠ 변경 필요한데 그대로인 항목
        "unchanged_review":    [{"line": "...", "reason": "..."}],   # 🔵 의도적 유지 여부 사용자 확인
        "newly_added":         [{"line": "...", "reason": "..."}],   # ✅ 새로 추가된 항목
        "summary": {"critical": N, "review": N, "added": N}
    }

알려진 한계(다음 단계 개선 예정, 이번 업데이트에는 미포함):
    - 현재는 줄 단위 exact-line 비교만 수행한다. SequenceMatcher를 import는 하지만
      실제 유사도 비교(fuzzy matching)에는 아직 쓰지 않는다. 그 결과 한 글자만 바뀐
      동일 항목도 "완전히 새 항목"으로 분류될 수 있다 — 결과를 볼 때 이 점을 감안할 것.
"""

import sys
import re
import json
import argparse
from difflib import SequenceMatcher


# ==============================
# 유틸: 의미 있는 줄만 추출
# ==============================
def meaningful_lines(text: str) -> list[str]:
    """빈 줄·공백만 있는 줄 제거 후 반환"""
    return [l.strip() for l in text.splitlines() if l.strip()]


# ==============================
# 핵심 판별 함수들
# ==============================
def contains_source_year(line: str, source_year: str) -> bool:
    """줄에 원본 연도(source_year)가 포함돼 있는지"""
    return source_year in line


def contains_date_expression(line: str) -> bool:
    """날짜 패턴이 포함돼 있는지"""
    patterns = [
        r'\d{4}[년.\-]\s*\d{1,2}[월.\-]\s*\d{1,2}',  # 2025년 3월 15일, 2025.3.15
        r'\d{1,2}월\s*\d{1,2}일',                       # 3월 15일
        r'\d{1,2}\.\s*\d{1,2}\.',                        # 3. 15.
        r'\d{4}\.\s*\d{1,2}\.\s*\d{1,2}',               # 2025. 3. 15
    ]
    return any(re.search(p, line) for p in patterns)


def contains_money(line: str) -> bool:
    """금액 표현이 포함돼 있는지"""
    return bool(re.search(r'\d[\d,]*\s*(원|천원|만원|백만원|억원)', line))


def contains_person_count(line: str) -> bool:
    """인원수 표현이 포함돼 있는지"""
    return bool(re.search(r'\d+\s*(명|학생|교사|인|팀)', line))


HEADING_PATTERNS = [
    r'^[○●◎◆■□▶▷►▸]\s',        # 한글 공문 불릿
    r'^\d+\.\s',                   # 1. 2. 3.
    r'^[가나다라마바사아자차카타파하]\.\s',  # 가. 나. 다.
    r'^제\d+조',                    # 제1조
]


def is_heading(line: str) -> bool:
    """섹션 제목·헤딩처럼 보이는 줄인지"""
    return any(re.match(p, line) for p in HEADING_PATTERNS)


LAW_PATTERNS = [
    r'법률\s*제\d+호',
    r'(시행령|시행규칙|고시|훈령)',
    r'제\d+조(제\d+항)?',
]


def is_law_reference(line: str) -> bool:
    """법령 인용구인지"""
    return any(re.search(p, line) for p in LAW_PATTERNS)


# ==============================
# 비교 핵심 로직
# ==============================
def compare_documents(old_text: str, new_text: str,
                      source_year: str, target_year: str) -> dict:
    old_lines = meaningful_lines(old_text)
    new_lines = meaningful_lines(new_text)

    old_set = set(old_lines)
    new_set = set(new_lines)

    unchanged_critical = []
    unchanged_review = []
    newly_added = []

    # ── ① 현재 문서에서 과거 문서와 동일한 줄 탐지 ──────────────────
    for line in new_lines:
        if line not in old_set:
            continue  # 새 문서에만 있거나 변경된 줄 → 아래 ③에서 처리

        # 동일한 줄이 현재 문서에도 존재 → 변경 여부 판단
        if contains_source_year(line, source_year):
            # 원본 연도가 그대로 남아 있음 → 명백한 미변경
            unchanged_critical.append({
                "line": line,
                "reason": f"'{source_year}' 연도 표기가 그대로 남아 있음 (→ {target_year}으로 변경 필요)"
            })
        elif contains_date_expression(line) and not contains_source_year(line, target_year):
            # 날짜 표현이 있는데 목표 연도가 없는 경우
            unchanged_critical.append({
                "line": line,
                "reason": "날짜 표현이 원본과 동일 — 연도·요일 재확인 필요"
            })
        elif contains_money(line):
            # 금액이 동일
            unchanged_review.append({
                "line": line,
                "reason": f"금액 표현이 과거 문서({source_year})와 동일 — 예산 현행화 여부 확인"
            })
        elif contains_person_count(line):
            # 인원수가 동일
            unchanged_review.append({
                "line": line,
                "reason": f"인원수 표현이 과거 문서({source_year})와 동일 — 현재 연도 현황 반영 여부 확인"
            })
        elif is_heading(line):
            # 헤딩·섹션 제목: 구조 유지는 정상이므로 '의도적 유지' 확인 대상
            unchanged_review.append({
                "line": line,
                "reason": "섹션 제목/헤딩이 과거 문서와 동일 — 의도적 유지 여부 확인"
            })
        elif is_law_reference(line):
            # 법령 인용구
            unchanged_review.append({
                "line": line,
                "reason": "법령 인용구가 과거 문서와 동일 — 법령 개정 여부 확인"
            })
        # 그 외 완전히 동일한 줄은 의도적 유지로 간주 (무시)

    # ── ③ 현재 문서에 새로 추가된 줄 탐지 ───────────────────────────
    for line in new_lines:
        if line in old_set:
            continue  # 과거와 동일 → 위에서 처리
        # 새로 추가된 줄 중 의미 있는 것만
        if len(line) > 10 and not line.startswith('#'):
            newly_added.append({
                "line": line[:120] + ('...' if len(line) > 120 else ''),
                "reason": "현재 문서에 새로 추가된 내용"
            })

    # 너무 많으면 상위 30개만 유지
    newly_added = newly_added[:30]

    return {
        "unchanged_critical": unchanged_critical,
        "unchanged_review": unchanged_review,
        "newly_added": newly_added,
        "summary": {
            "critical": len(unchanged_critical),
            "review": len(unchanged_review),
            "added": len(newly_added)
        }
    }


# ==============================
# 메인
# ==============================
def main():
    parser = argparse.ArgumentParser(description='두 문서 비교 — 미변경 항목 탐지')
    parser.add_argument('--old-file', help='과거 문서 텍스트 파일 경로 (긴 문서는 반드시 이 옵션 사용)')
    parser.add_argument('--new-file', help='현재 문서 텍스트 파일 경로 (긴 문서는 반드시 이 옵션 사용)')
    parser.add_argument('--old-text', help='과거 문서 텍스트 직접 입력 (짧은 경우에만)')
    parser.add_argument('--new-text', help='현재 문서 텍스트 직접 입력 (짧은 경우에만)')
    parser.add_argument('--source-year', required=True, help='원본 연도 (예: 2025)')
    parser.add_argument('--target-year', required=True, help='목표 연도 (예: 2026)')
    args = parser.parse_args()

    if args.old_file:
        with open(args.old_file, encoding='utf-8') as f:
            old_text = f.read()
    elif args.old_text is not None:
        old_text = args.old_text
    else:
        parser.error('--old-file 또는 --old-text 중 하나를 지정하세요.')

    if args.new_file:
        with open(args.new_file, encoding='utf-8') as f:
            new_text = f.read()
    elif args.new_text is not None:
        new_text = args.new_text
    else:
        parser.error('--new-file 또는 --new-text 중 하나를 지정하세요.')

    result = compare_documents(
        old_text=old_text,
        new_text=new_text,
        source_year=args.source_year,
        target_year=args.target_year
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
