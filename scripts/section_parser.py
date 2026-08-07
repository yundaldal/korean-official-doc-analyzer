#!/usr/bin/env python3
"""
섹션 인식 파서 — 공문서 텍스트를 섹션 단위로 분류한다.

각 섹션에 타입 레이블을 부여하여 날짜 검증 등 분석 시
섹션 맥락을 함께 제공한다.

섹션 타입:
  CURRENT  — 현재 연도 계획/일정 (날짜 검증 대상)
  PAST     — 과거 운영 성과/실적 (날짜 검증 대상, 별도 표시)
  REF_NUM  — 참조 문서 번호 (예: 광주특수교육과-1234(2025.3.4.)) → 검증 제외
  ATTACH   — 별첨/서식 (날짜 검증 대상)
  UNKNOWN  — 분류 불명

v3 변경사항 (전수 점검 반영):
  - [P0-4] 참조문서번호 제외 로직을 "날짜 앞 50자 텍스트 검색" 방식에서
    "참조문서번호 전체 span을 먼저 찾고 그 안에 날짜가 포함되는지" 방식으로 교체.
    기존 방식은 검사 대상 문자열이 날짜 자신의 숫자를 포함하지 못해 사실상 매칭이
    불가능한 구조적 오류였다.
  - [P0-5] CLI에 --input-file / --current-year 옵션 추가 (기존 위치인자 방식도 하위 호환 지원).
  - [P0-6] 태깅된 각 날짜에 1-indexed line_no(문서 전체 기준 줄 번호)를 추가.
  - [P1-1] NUM_HEADER(1. 2. 가. 나. ①②… 등 소항목)를 실제로 사용한다. 특히 PAST 키워드로
    진입한 하위 섹션이 다음 소항목에서 상위(로마 대목차) 섹션 타입으로 복귀하지 못하고
    로마 대목차가 다시 나올 때까지 계속 PAST로 남는 문제를 고친다. (완전한 다단계 헤더
    계층 구조까지는 구현하지 않음 — "PAST 등 키워드 진입 후 다음 소항목에서 부모 타입으로
    복귀"라는 핵심 실패 케이스만 해결한다.)
  - [P1-2] PAST_KEYWORDS에서 '2025년도 운영'/'2024년도 운영' 같은 연도 하드코딩 제거.
    (동적 `20\\d{2} < current_year` 판정으로 이미 커버됨)
  - [P1-3] ATTACH_HEADER를 줄 중간 등장("붙임 1 참조")이 아니라 줄 시작 위치로 앵커링.
  - 날짜 범위(~) 종료일이 연도·월을 생략한 경우 시작일 기준으로 추론하여 함께 추출(v2 기능 유지).
"""

import argparse
import datetime
import re
import sys
import json


# ─────────────────────────────────────────
# 섹션 헤더 패턴
# ─────────────────────────────────────────

# 로마 숫자 대목차: Ⅰ Ⅱ Ⅲ Ⅳ Ⅴ Ⅵ
ROMAN_HEADER = re.compile(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\s*[\.\s]')

# 숫자/한글/원문자 소목차: 1. 2. 가. 나. ①②③ 등 — 줄 시작에서만 인정
NUM_HEADER = re.compile(r'^\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+\.\s|[가-힣]\.\s)')

# 별첨 패턴 — [P1-3] 줄 시작으로 앵커링 (본문 중 "붙임 1 참조" 같은 표현은 헤더로 오인하지 않음)
ATTACH_HEADER = re.compile(r'^\s*(별첨|붙임)\s*\d+')

# 참조 문서 번호 패턴 (기관명-번호(날짜) 형식) — 날짜만 단독으로 쓸 때 참고용
REF_NUM_PATTERN = re.compile(
    r'[가-힣\s]+-\s*\d+\s*\(\s*\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.\s*\)'
)

# 과거 실적 섹션을 나타내는 키워드 — [P1-2] 연도 하드코딩 제거
PAST_KEYWORDS = [
    '운영 성과', '운영성과', '추진 성과', '추진성과',
    '지난해', '전년도', '작년',
    '지난 해', '운영 결과', '추진 결과',
]


# ─────────────────────────────────────────
# 섹션 분류 로직
# ─────────────────────────────────────────

def classify_section(header_text: str, current_year: int) -> str:
    """섹션 헤더 텍스트를 보고 섹션 타입 반환"""
    text = header_text.strip()

    # 별첨/붙임
    if ATTACH_HEADER.search(text):
        return 'ATTACH'

    # 과거 실적 키워드
    for kw in PAST_KEYWORDS:
        if kw in text:
            return 'PAST'

    # 과거 연도(현재연도-1 이하)가 헤더에 포함된 경우 — 동적 판정 (하드코딩 없음)
    years_in_header = re.findall(r'\b(20\d{2})\b', text)
    for y in years_in_header:
        if int(y) < current_year:
            return 'PAST'

    return 'CURRENT'


def parse_sections(text: str, current_year: int) -> list:
    """
    텍스트를 줄 단위로 순회하며 섹션 구조를 파악한다.
    반환값: [{'type': str, 'header': str, 'start_line': int, 'end_line': int, 'content': str}, ...]

    start_line/end_line은 0-indexed(내부 계산용). 외부에 노출하는 line_no는 1-indexed로 변환한다.
    """
    lines = text.splitlines()
    sections = []
    current_section = {
        'type': 'CURRENT',
        'header': '(문서 시작)',
        'start_line': 0,
        'lines': []
    }
    # [P1-1] 현재 속해 있는 로마 대목차(상위 섹션)의 타입. 소항목이 나오면 이 타입으로 복귀한다.
    roman_type = 'CURRENT'

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 별첨 헤더 감지 (줄 시작 앵커링)
        if ATTACH_HEADER.match(stripped):
            _close_section(sections, current_section, i - 1)
            current_section = {
                'type': 'ATTACH',
                'header': stripped,
                'start_line': i,
                'lines': [line]
            }
            roman_type = 'ATTACH'
            continue

        # 로마 대목차 감지
        if ROMAN_HEADER.match(stripped) and len(stripped) > 1:
            _close_section(sections, current_section, i - 1)
            sec_type = classify_section(stripped, current_year)
            current_section = {
                'type': sec_type,
                'header': stripped,
                'start_line': i,
                'lines': [line]
            }
            roman_type = sec_type
            continue

        # 과거 실적 키워드가 줄 중간에 등장 (소제목 형태)
        matched_past_kw = False
        for kw in PAST_KEYWORDS:
            if kw in stripped and len(stripped) < 60:
                _close_section(sections, current_section, i - 1)
                current_section = {
                    'type': 'PAST',
                    'header': stripped,
                    'start_line': i,
                    'lines': [line]
                }
                matched_past_kw = True
                break
        if matched_past_kw:
            continue

        # [P1-1] 숫자/한글/원문자 소항목: 현재 섹션이 "키워드로 진입한 PAST 등 하위 섹션"이면
        # 이 소항목 자체가 새로운 과거 언급이 아닌 한 상위(로마 대목차) 타입으로 복귀한다.
        if NUM_HEADER.match(stripped) and current_section['type'] != roman_type:
            has_past_signal = any(kw in stripped for kw in PAST_KEYWORDS)
            years_here = re.findall(r'\b(20\d{2})\b', stripped)
            has_old_year = any(int(y) < current_year for y in years_here)
            if not (has_past_signal or has_old_year):
                _close_section(sections, current_section, i - 1)
                current_section = {
                    'type': roman_type,
                    'header': stripped,
                    'start_line': i,
                    'lines': [line]
                }
                continue
            # 소항목 자체에 과거 신호가 있으면 PAST로 전환
            _close_section(sections, current_section, i - 1)
            current_section = {
                'type': 'PAST',
                'header': stripped,
                'start_line': i,
                'lines': [line]
            }
            continue

        current_section['lines'].append(line)

    # 마지막 섹션 닫기
    _close_section(sections, current_section, len(lines) - 1)
    return sections


def _close_section(sections, section, end_line):
    section['end_line'] = end_line
    section['content'] = '\n'.join(section['lines'])
    sections.append(section)


# ─────────────────────────────────────────
# 날짜 + 섹션 태깅
# ─────────────────────────────────────────

DATE_PATTERN = re.compile(
    r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*\(([월화수목금토일])\)'
)

# [P0-4] 참조문서번호 전체 span(기관명-번호(연도.월.일.[.(요일)]) 형식)을 통째로 찾는 패턴.
# 날짜 span이 이 안에 포함되는지로 REF_NUM 여부를 판정한다(부분 문자열 선-검색 방식 폐기).
REF_NUM_FULL = re.compile(
    r'[가-힣A-Za-z0-9]+[가-힣A-Za-z0-9\s]*-\s*\d+\s*'
    r'\(\s*\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.'
    r'(?:\s*\(\s*[월화수목금토일]\s*\))?'
    r'\s*\)'
)

# 날짜 범위의 "종료일" — 연도(그리고 흔히 월)를 생략하고 물결(~)로 이어지는 표기.
# 예: "~8. 12.(수)"  또는  "~12.(수)" (월도 생략, 시작일과 같은 달)
RANGE_CONT_PATTERN = re.compile(
    r'^\s*[~∼-]\s*(?:(\d{1,2})\.\s*)?(\d{1,2})\.\s*\(([월화수목금토일])\)'
)
RANGE_LOOKAHEAD_CHARS = 20


def tag_dates_with_sections(text: str, current_year: int) -> list:
    """
    문서 전체 텍스트에서 날짜를 추출하고 각 날짜에 섹션 타입 + 줄 번호를 태깅한다.
    날짜 범위(~)의 종료일이 연도/월을 생략한 경우, 시작일 기준으로 추론하여 함께 포함한다.
    참조문서번호 내부의 날짜는 REF_NUM으로 정확히 제외한다(span 포함 여부 기준).

    반환값: [{'date': str, 'year':int, 'month':int, 'day':int,
               'claimed_day': str, 'section_type': str,
               'section_header': str, 'context': str,
               'line_no': int, 'inferred': bool}, ...]
    """
    sections = parse_sections(text, current_year)

    tagged = []
    for sec in sections:
        content = sec['content']
        ref_spans = [(m.start(), m.end()) for m in REF_NUM_FULL.finditer(content)]

        def _in_ref_span(start, end):
            return any(rs <= start and end <= re_ for rs, re_ in ref_spans)

        def _line_no(pos_in_content):
            return sec['start_line'] + content[:pos_in_content].count('\n') + 1

        for m in DATE_PATTERN.finditer(content):
            effective_type = 'REF_NUM' if _in_ref_span(m.start(), m.end()) else sec['type']

            context_start = max(0, m.start() - 40)
            context_end = min(len(content), m.end() + 40)

            tagged.append({
                'date': m.group(0),
                'year': int(m.group(1)),
                'month': int(m.group(2)),
                'day': int(m.group(3)),
                'claimed_day': m.group(4),
                'section_type': effective_type,
                'section_header': sec['header'],
                'context': content[context_start:context_end].replace('\n', ' '),
                'line_no': _line_no(m.start()),
                'inferred': False,
            })

            # ── 범위 종료일 탐지 ──
            tail = content[m.end(): m.end() + RANGE_LOOKAHEAD_CHARS]
            cm = RANGE_CONT_PATTERN.match(tail)
            if cm:
                cont_month = int(cm.group(1)) if cm.group(1) else int(m.group(2))
                cont_day = int(cm.group(2))
                cont_claimed = cm.group(3)
                cont_start = m.end() + cm.start()
                cont_end = m.end() + cm.end()
                cctx_start = max(0, cont_start - 40)
                cctx_end = min(len(content), cont_end + 40)
                tagged.append({
                    'date': f"{m.group(1)}.{cont_month}.{cont_day}.({cont_claimed}) [범위 종료일 — 연도"
                            + ('' if cm.group(1) else '·월') + " 시작일에서 추론]",
                    'year': int(m.group(1)),
                    'month': cont_month,
                    'day': cont_day,
                    'claimed_day': cont_claimed,
                    'section_type': effective_type,
                    'section_header': sec['header'],
                    'context': content[cctx_start:cctx_end].replace('\n', ' '),
                    'line_no': _line_no(cont_start),
                    'inferred': True,
                })

    return tagged


# ─────────────────────────────────────────
# 입력 처리 / 메인
# ─────────────────────────────────────────

def _load_text(args) -> str:
    if args.input_file:
        with open(args.input_file, encoding='utf-8') as f:
            return f.read()
    if args.text is not None:
        return args.text
    raise SystemExit('입력이 없습니다: --input-file 또는 --text 중 하나를 지정하세요.')


def _build_arg_parser():
    p = argparse.ArgumentParser(description='공문서 텍스트를 섹션 단위로 분류한다.')
    p.add_argument('--input-file', help='텍스트 파일 경로 (긴 문서는 반드시 이 옵션을 사용)')
    p.add_argument('--text', help='텍스트 직접 입력 (짧은 경우에만 사용)')
    p.add_argument('--current-year', type=int, default=None, help='문서 기준연도 (기본값: 실행 시점의 현재 연도)')
    return p


if __name__ == '__main__':
    parser = _build_arg_parser()
    if len(sys.argv) >= 2 and not sys.argv[1].startswith('--'):
        # 하위 호환: python3 section_parser.py <파일경로> [연도]
        text = open(sys.argv[1], encoding='utf-8').read()
        current_year = int(sys.argv[2]) if len(sys.argv) > 2 else datetime.datetime.now().year
    else:
        args = parser.parse_args()
        text = _load_text(args)
        current_year = args.current_year if args.current_year is not None else datetime.datetime.now().year

    result = tag_dates_with_sections(text, current_year)
    print(json.dumps(result, ensure_ascii=False, indent=2))
