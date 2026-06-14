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
"""

import re
import sys
import json


# ─────────────────────────────────────────
# 섹션 헤더 패턴
# ─────────────────────────────────────────

# 로마 숫자 대목차: Ⅰ Ⅱ Ⅲ Ⅳ Ⅴ Ⅵ
ROMAN_HEADER = re.compile(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\s*[\.\s]')

# 숫자 소목차: 1. 2. ①②③ 등
NUM_HEADER = re.compile(r'^\s*[①②③④⑤⑥⑦⑧⑨⑩]|^\s*\d+\.\s')

# 별첨 패턴
ATTACH_HEADER = re.compile(r'별첨\s*\d+|붙임\s*\d+')

# 참조 문서 번호 패턴 (기관명-번호(날짜) 형식)
REF_NUM_PATTERN = re.compile(
    r'[가-힣\s]+-\s*\d+\s*\(\s*\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.\s*\)'
)

# 과거 실적 섹션을 나타내는 키워드
PAST_KEYWORDS = [
    '운영 성과', '운영성과', '추진 성과', '추진성과',
    '지난해', '전년도', '작년', '2025년도 운영', '2024년도 운영',
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

    # 과거 연도(현재연도-1 이하)가 헤더에 포함된 경우
    years_in_header = re.findall(r'\b(20\d{2})\b', text)
    for y in years_in_header:
        if int(y) < current_year:
            return 'PAST'

    return 'CURRENT'


def parse_sections(text: str, current_year: int) -> list:
    """
    텍스트를 줄 단위로 순회하며 섹션 구조를 파악한다.
    반환값: [{'type': str, 'header': str, 'start_line': int, 'end_line': int, 'content': str}, ...]
    """
    lines = text.splitlines()
    sections = []
    current_section = {
        'type': 'CURRENT',
        'header': '(문서 시작)',
        'start_line': 0,
        'lines': []
    }

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 별첨 헤더 감지
        if ATTACH_HEADER.search(stripped):
            _close_section(sections, current_section, i - 1)
            current_section = {
                'type': 'ATTACH',
                'header': stripped,
                'start_line': i,
                'lines': [line]
            }
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
            continue

        # 과거 실적 키워드가 줄 중간에 등장 (소제목 형태)
        for kw in PAST_KEYWORDS:
            if kw in stripped and len(stripped) < 60:
                _close_section(sections, current_section, i - 1)
                current_section = {
                    'type': 'PAST',
                    'header': stripped,
                    'start_line': i,
                    'lines': [line]
                }
                break
        else:
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
REF_INLINE = re.compile(
    r'[가-힣\s]+-\s*\d+\s*\(\s*\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.'
)


def tag_dates_with_sections(text: str, current_year: int) -> list:
    """
    문서 전체 텍스트에서 날짜를 추출하고 각 날짜에 섹션 타입을 태깅한다.
    반환값: [{'date': str, 'year':int, 'month':int, 'day':int,
               'claimed_day': str, 'section_type': str,
               'section_header': str, 'context': str}, ...]
    """
    sections = parse_sections(text, current_year)

    tagged = []
    for sec in sections:
        content = sec['content']
        for m in DATE_PATTERN.finditer(content):
            # 참조 문서 번호 내부인지 확인 (앞 50자에 기관명-번호 패턴)
            before = content[max(0, m.start() - 50): m.start()]
            if REF_INLINE.search(before):
                effective_type = 'REF_NUM'
            else:
                effective_type = sec['type']

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
            })

    return tagged


# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────

if __name__ == '__main__':
    import datetime

    if len(sys.argv) < 2:
        print('사용법: python3 section_parser.py <텍스트_파일경로> [현재연도]')
        sys.exit(1)

    with open(sys.argv[1], encoding='utf-8') as f:
        text = f.read()

    current_year = int(sys.argv[2]) if len(sys.argv) > 2 else datetime.datetime.now().year
    result = tag_dates_with_sections(text, current_year)
    print(json.dumps(result, ensure_ascii=False, indent=2))
