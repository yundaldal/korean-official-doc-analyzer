#!/usr/bin/env python3
"""
날짜-요일 자동 검증 스크립트 (섹션 인식 버전)

섹션 타입별 처리:
  CURRENT  — 현재 계획/일정  → 오류 시 ❌
  PAST     — 과거 운영 성과  → 오류 시 🔴 (원본 공문 대조 요청)
  ATTACH   — 별첨/서식       → 오류 시 ❌
  REF_NUM  — 참조 문서 번호  → 검증 제외
"""

import re, sys, json, datetime, os

DAY_KOR = {0:'월',1:'화',2:'수',3:'목',4:'금',5:'토',6:'일'}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from section_parser import tag_dates_with_sections
    SECTION_AWARE = True
except ImportError:
    SECTION_AWARE = False


def verify_single(year, month, day, claimed):
    if year is None:
        return None, '연도 불명', None
    try:
        dt = datetime.date(year, month, day)
    except ValueError:
        return False, '존재하지 않는 날짜', None
    actual = DAY_KOR[dt.weekday()]
    if actual == claimed:
        return True, f'정확({actual})', actual
    return False, f'실제:{actual}요일 / 표기:{claimed}요일', actual


def run(text, current_year=None):
    if current_year is None:
        current_year = datetime.datetime.now().year

    if SECTION_AWARE:
        tagged = tag_dates_with_sections(text, current_year)
    else:
        pat = re.compile(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*\(([월화수목금토일])\)')
        tagged = [{'date':m.group(0),'year':int(m.group(1)),'month':int(m.group(2)),
                   'day':int(m.group(3)),'claimed_day':m.group(4),
                   'section_type':'CURRENT','section_header':'(파서 없음)',
                   'context':text[max(0,m.start()-40):m.end()+40]}
                  for m in pat.finditer(text)]

    seen, unique = set(), []
    for d in tagged:
        k = (d['year'],d['month'],d['day'],d['claimed_day'],d['section_type'])
        if k not in seen:
            seen.add(k); unique.append(d)

    results = []
    for d in unique:
        if d['section_type'] == 'REF_NUM':
            results.append({**d,'valid':None,'reason':'참조문서번호-제외'}); continue
        ok, reason, actual = verify_single(d['year'],d['month'],d['day'],d['claimed_day'])
        results.append({**d,'valid':ok,'reason':reason,**(({'actual_day':actual}) if actual else {})})

    err_cur  = [r for r in results if r['valid'] is False and r['section_type'] in ('CURRENT','ATTACH','UNKNOWN')]
    err_past = [r for r in results if r['valid'] is False and r['section_type'] == 'PAST']
    correct  = [r for r in results if r['valid'] is True]
    skipped  = [r for r in results if r['valid'] is None]

    return {'total':len(results),'correct':len(correct),
            'errors_current':len(err_cur),'errors_past':len(err_past),
            'skipped_ref':len(skipped),'section_aware':SECTION_AWARE,
            'details':results,'error_details_current':err_cur,'error_details_past':err_past}


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('사용법: python3 verify_dates.py <파일경로> [현재연도]'); sys.exit(1)
    if sys.argv[1] == '--text':
        text = sys.argv[2] if len(sys.argv)>2 else ''
        ref_year = int(sys.argv[3]) if len(sys.argv)>3 else None
    else:
        with open(sys.argv[1],encoding='utf-8') as f: text=f.read()
        ref_year = int(sys.argv[2]) if len(sys.argv)>2 else None

    r = run(text, ref_year)
    print(json.dumps(r, ensure_ascii=False, indent=2))
