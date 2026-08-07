#!/usr/bin/env python3
"""
날짜 검증 스크립트 (섹션 인식 버전, v3)

v1(구버전)은 "요일이 날짜와 맞는가"만 확인했다. v2에서 아래 세 가지를 서로 독립적으로
판정하도록 확장했다.

  calendar_valid : 실제로 존재하는 날짜인가? (예: 2월 30일 → False)
  weekday_valid  : 표기한 요일이 실제 요일과 맞는가?
  year_valid     : 이 섹션에서 허용되는 연도인가? (문서 기준연도와 비교)

v3 변경사항 (전수 점검 반영):
  - [P0-5] CLI에 --input-file / --current-year 옵션 추가 (기존 위치인자·--text 방식도 하위 호환).
  - [P0-6] 각 날짜 결과에 section_parser가 계산한 line_no(1-indexed)를 그대로 노출.
  - [P1-4] 동일 (연도,월,일,요일,섹션타입) 조합이 문서 여러 곳에 있어도 하나로 뭉개지 않고
    `occurrences` 배열(각 발생 위치의 line_no/context)로 모두 보존한다.

세 값은 서로 결과에 영향을 주지 않는다 — 날짜가 존재하지 않아도(calendar_valid False) 연도
자체는 검사할 수 있고, 요일이 맞아도(weekday_valid True) 연도가 틀렸을 수 있다(YEAR_MISMATCH).
예: "2025. 9. 1.(월)"이 문서가 2026년 CURRENT 섹션에 있는 경우
    calendar_valid = True   (9월 1일은 실존하는 날짜)
    weekday_valid  = True   (2025-09-01은 실제로 월요일)
    year_valid     = False  (문서 기준연도 2026과 다름 → YEAR_MISMATCH)

섹션 타입별 처리:
  CURRENT/ATTACH/UNKNOWN — calendar/weekday 오류 시 ❌, 연도 불일치 시 ⚠(과거)/🔵(미래)
  PAST                   — calendar/weekday 오류 시 🔴(원본 공문 대조 요청), 연도 검사 제외
  REF_NUM                — 세 항목 모두 검증 제외
"""

import argparse
import re
import sys
import json
import datetime
import os

DAY_KOR = {0: '월', 1: '화', 2: '수', 3: '목', 4: '금', 5: '토', 6: '일'}
YEAR_CHECKED_TYPES = ('CURRENT', 'ATTACH', 'UNKNOWN')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from section_parser import tag_dates_with_sections
    SECTION_AWARE = True
except ImportError:
    SECTION_AWARE = False


def check_calendar(year, month, day):
    """날짜가 실제로 존재하는지 확인. (존재여부: bool, datetime.date|None)"""
    try:
        return True, datetime.date(year, month, day)
    except (ValueError, TypeError):
        return False, None


def check_weekday(dt, claimed):
    """dt(datetime.date)의 실제 요일과 표기 요일 비교. dt가 None이면 판정 불가(None)."""
    if dt is None:
        return None, None
    actual = DAY_KOR[dt.weekday()]
    return (actual == claimed), actual


def check_year(year, section_type, current_year):
    """
    섹션 타입에 맞는 연도인지 확인.
    반환: (year_valid: bool|None, issue: 'stale'|'future'|None, reason: str)
    """
    if section_type not in YEAR_CHECKED_TYPES:
        return None, None, '연도 검사 대상 아님(PAST/REF_NUM 등)'

    if year == current_year:
        return True, None, f'연도 일치({year})'

    if year < current_year:
        return False, 'stale', (
            f'⚠ 연도 미변경 의심: 문서 기준연도는 {current_year}년인데 '
            f'이 날짜는 {year}년으로 표기됨'
        )

    return False, 'future', (
        f'🔵 확인 필요: 문서 기준연도({current_year}년)보다 뒤인 {year}년 날짜 — '
        f'의도된 표기인지 확인 필요'
    )


def verify_entry(d, current_year):
    """태깅된 날짜 하나(dict)에 대해 세 항목을 독립적으로 판정한다."""
    if d['section_type'] == 'REF_NUM':
        return {
            **d,
            'calendar_valid': None, 'weekday_valid': None, 'year_valid': None,
            'year_issue': None, 'year_expected': None,
            'issues': [], 'reason': '참조문서번호-제외', 'valid': None,
        }

    cal_ok, dt = check_calendar(d['year'], d['month'], d['day'])
    wd_ok, actual_wd = check_weekday(dt, d['claimed_day'])
    yr_ok, yr_issue, yr_reason = check_year(d['year'], d['section_type'], current_year)

    issues = []
    if not cal_ok:
        issues.append('INVALID_DATE')
    if wd_ok is False:
        issues.append('WEEKDAY_MISMATCH')
    if yr_ok is False:
        issues.append('YEAR_MISMATCH')

    reason_parts = []
    reason_parts.append('날짜 존재: 정상' if cal_ok else '❌ 날짜 존재: 오류(실존하지 않는 날짜)')
    if wd_ok is None:
        reason_parts.append('요일: 판정 불가(날짜 자체가 무효)')
    elif wd_ok:
        reason_parts.append('요일: 정상')
    else:
        claimed = d['claimed_day']
        reason_parts.append(f'요일: ❌ 오류(실제:{actual_wd} / 표기:{claimed})')
    if yr_ok is not None:
        reason_parts.append('연도: 정상' if yr_ok else f'연도: {yr_reason}')

    entry = {
        **d,
        'calendar_valid': cal_ok,
        'weekday_valid': wd_ok,
        'actual_weekday': actual_wd,
        'year_valid': yr_ok,
        'year_issue': yr_issue,
        'year_expected': current_year if yr_ok is not None else None,
        'issues': issues,
        'reason': ' / '.join(reason_parts),
        # 구버전 호환용 필드: calendar+weekday만 반영(연도는 issues로 별도 확인해야 함)
        'valid': (cal_ok and (wd_ok is not False)) if wd_ok is not None else cal_ok,
    }
    return entry


def _group_occurrences(tagged):
    """[P1-4] 동일 (연도,월,일,요일,섹션타입) 조합을 대표 1건 + occurrences 배열로 묶는다."""
    groups = {}
    order = []
    for d in tagged:
        k = (d['year'], d['month'], d['day'], d['claimed_day'], d['section_type'])
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(d)

    grouped = []
    for k in order:
        items = groups[k]
        base = dict(items[0])
        base['occurrences'] = [
            {'line_no': it.get('line_no'), 'context': it.get('context'),
             'date': it.get('date'), 'inferred': it.get('inferred', False)}
            for it in items
        ]
        base['occurrence_count'] = len(items)
        grouped.append(base)
    return grouped


def run(text, current_year=None):
    if current_year is None:
        current_year = datetime.datetime.now().year

    if SECTION_AWARE:
        tagged = tag_dates_with_sections(text, current_year)
    else:
        pat = re.compile(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*\(([월화수목금토일])\)')
        tagged = []
        for m in pat.finditer(text):
            line_no = text[:m.start()].count('\n') + 1
            tagged.append({
                'date': m.group(0), 'year': int(m.group(1)), 'month': int(m.group(2)),
                'day': int(m.group(3)), 'claimed_day': m.group(4),
                'section_type': 'CURRENT', 'section_header': '(파서 없음)',
                'context': text[max(0, m.start() - 40):m.end() + 40],
                'line_no': line_no, 'inferred': False,
            })

    grouped = _group_occurrences(tagged)
    results = [verify_entry(d, current_year) for d in grouped]

    def _f(pred):
        return [r for r in results if pred(r)]

    errors_calendar_or_weekday_current = _f(
        lambda r: r['section_type'] in ('CURRENT', 'ATTACH', 'UNKNOWN')
        and ('INVALID_DATE' in r['issues'] or 'WEEKDAY_MISMATCH' in r['issues'])
    )
    errors_calendar_or_weekday_past = _f(
        lambda r: r['section_type'] == 'PAST'
        and ('INVALID_DATE' in r['issues'] or 'WEEKDAY_MISMATCH' in r['issues'])
    )
    year_stale = _f(lambda r: r.get('year_issue') == 'stale')
    year_future = _f(lambda r: r.get('year_issue') == 'future')
    correct = _f(lambda r: r['valid'] is True and not r['issues'])
    skipped = _f(lambda r: r['section_type'] == 'REF_NUM')

    return {
        'total': len(results),
        'total_occurrences': sum(r.get('occurrence_count', 1) for r in results),
        'correct': len(correct),
        'errors_current': len(errors_calendar_or_weekday_current),   # 구버전 호환(날짜/요일 오류만)
        'errors_past': len(errors_calendar_or_weekday_past),          # 구버전 호환
        'errors_year_stale': len(year_stale),      # 연도 미변경 의심(과거연도 잔존)
        'notes_year_future': len(year_future),     # 연도가 기준연도보다 미래(확인 권장)
        'skipped_ref': len(skipped),
        'section_aware': SECTION_AWARE,
        'current_year_used': current_year,
        'details': results,
        'error_details_current': errors_calendar_or_weekday_current,
        'error_details_past': errors_calendar_or_weekday_past,
        'error_details_year_stale': year_stale,
        'note_details_year_future': year_future,
    }


def _load_text(args):
    if args.input_file:
        with open(args.input_file, encoding='utf-8') as f:
            return f.read()
    if args.text is not None:
        return args.text
    raise SystemExit('입력이 없습니다: --input-file 또는 --text 중 하나를 지정하세요.')


def _build_arg_parser():
    p = argparse.ArgumentParser(description='공문서 날짜/요일/연도를 검증한다.')
    p.add_argument('--input-file', help='텍스트 파일 경로 (긴 문서는 반드시 이 옵션을 사용)')
    p.add_argument('--text', help='텍스트 직접 입력 (짧은 경우에만 사용)')
    p.add_argument('--current-year', type=int, default=None, help='문서 기준연도 (기본값: 실행 시점의 현재 연도)')
    return p


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == '--text':
        # 구버전 하위 호환: --text "<텍스트>" [연도]
        text = sys.argv[2] if len(sys.argv) > 2 else ''
        ref_year = int(sys.argv[3]) if len(sys.argv) > 3 else None
    elif len(sys.argv) >= 2 and not sys.argv[1].startswith('--'):
        # 구버전 하위 호환: python3 verify_dates.py <파일경로> [연도]
        with open(sys.argv[1], encoding='utf-8') as f:
            text = f.read()
        ref_year = int(sys.argv[2]) if len(sys.argv) > 2 else None
    elif len(sys.argv) < 2:
        print('사용법: python3 verify_dates.py --input-file <파일경로> [--current-year YYYY]')
        sys.exit(1)
    else:
        args = _build_arg_parser().parse_args()
        text = _load_text(args)
        ref_year = args.current_year

    r = run(text, ref_year)
    print(json.dumps(r, ensure_ascii=False, indent=2))
