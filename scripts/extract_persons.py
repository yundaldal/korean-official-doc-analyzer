#!/usr/bin/env python3
"""
공문서 내 인물명 추출 스크립트

공문서에서 사람 이름으로 추정되는 한글 2~4글자를 역할/직책 키워드 근처에서 탐지한다.
AI가 이 결과를 기반으로 사용자에게 해당 인물이 실제 기안문/공문에 들어갈 사람인지 확인을 요청한다.

사용법:
    python3 extract_persons.py "<추출된_텍스트>"

출력(JSON):
    {
        "persons": [
            {
                "name": "홍길동",
                "role": "담당자",
                "context": "담당자: 홍길동(062-717-6819)",
                "phone": "062-717-6819",
                "location": "본문 3번째 줄"
            }
        ],
        "total_found": N,
        "note": "AI가 텍스트를 직접 읽어 추가 인물을 보완할 수 있습니다."
    }
"""

import argparse
import sys
import re
import json


# ==============================
# 역할/직책 키워드
# ==============================

# 이름 앞에 오는 역할 키워드 (역할: 이름, 역할 이름)
ROLE_BEFORE_NAME = [
    '기안자', '기안', '검토자', '검토', '결재자', '결재',
    '협조자', '협조',
    '담당자', '담당', '책임자', '책임',
    '수신자', '수신',
    '발신자', '발신',
    '작성자', '작성',
    '시행자', '시행',
    '문의',
]

# 이름 뒤에 오는 직급/직책 키워드
TITLE_AFTER_NAME = [
    '장학사', '장학관', '교육연구사', '교육연구관',
    '사무관', '주무관', '행정사', '서기',
    '교사', '교감', '교장', '원장', '원감',
    '과장', '팀장', '계장', '실장', '국장', '부장',
    '선생님', '선생', '센터장',
]

# 전화번호 패턴
PHONE_PATTERN = re.compile(
    r'(0\d{1,2}[\-\s]?\d{3,4}[\-\s]?\d{4})'
)

# 한글 이름 패턴 (2~4글자, 한글만)
KOREAN_NAME = re.compile(r'[가-힣]{2,4}')


# ==============================
# 추출 로직
# ==============================

def extract_persons(text: str) -> list[dict]:
    """텍스트에서 인물명 후보를 추출"""
    persons = []
    seen_names = set()
    lines = text.splitlines()

    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # ── 패턴 1: "역할[:/\s] 이름" ──
        for role in ROLE_BEFORE_NAME:
            # "담당자: 홍길동", "담당자 홍길동", "담당: 홍길동"
            pattern = re.compile(
                rf'{re.escape(role)}\s*[:：\s]\s*([가-힣]{{2,4}})'
            )
            for m in pattern.finditer(stripped):
                name = m.group(1)
                if _is_likely_name(name) and name not in seen_names:
                    phone = _find_nearby_phone(stripped, m.end())
                    context = _extract_context(stripped, m.start(), m.end() + 20)
                    persons.append({
                        'name': name,
                        'role': role,
                        'context': context,
                        'phone': phone,
                        'location': f'{line_idx + 1}번째 줄'
                    })
                    seen_names.add(name)

        # ── 패턴 2: "이름 직책" (예: "홍길동 장학사") ──
        # 이름 앞에 다른 한글이 바로 붙어있으면 오탐이므로, 앞에 한글이 아닌 문자 또는 줄 시작이어야 함
        for title in TITLE_AFTER_NAME:
            pattern = re.compile(
                rf'(?<![가-힣])([가-힣]{{2,4}})\s+{re.escape(title)}'
            )
            for m in pattern.finditer(stripped):
                name = m.group(1)
                if _is_likely_name(name) and name not in seen_names:
                    phone = _find_nearby_phone(stripped, m.end())
                    context = _extract_context(stripped, m.start(), m.end() + 20)
                    persons.append({
                        'name': name,
                        'role': title,
                        'context': context,
                        'phone': phone,
                        'location': f'{line_idx + 1}번째 줄'
                    })
                    seen_names.add(name)

        # ── 패턴 3: 전화번호 바로 앞의 이름 ──
        # "홍길동(062-717-6819)" 또는 "홍길동 062-717-6819"
        phone_with_name = re.compile(
            r'([가-힣]{2,4})\s*[\(\(]?\s*(0\d{1,2}[\-\s]?\d{3,4}[\-\s]?\d{4})\s*[\)\)]?'
        )
        for m in phone_with_name.finditer(stripped):
            name = m.group(1)
            phone = m.group(2).strip()
            if _is_likely_name(name) and name not in seen_names:
                # 역할 추정: 같은 줄에서 역할 키워드 찾기
                role = _guess_role_from_line(stripped, ROLE_BEFORE_NAME)
                context = _extract_context(stripped, m.start(), m.end())
                persons.append({
                    'name': name,
                    'role': role if role else '(연락처 근처)',
                    'context': context,
                    'phone': phone,
                    'location': f'{line_idx + 1}번째 줄'
                })
                seen_names.add(name)

    return persons


# ==============================
# 보조 함수
# ==============================

# 이름이 아닐 가능성이 높은 단어 (오탐 방지)
NOT_NAMES = {
    # 일반 명사 / 기관·부서 키워드
    '교육청', '교육과', '교육원', '지원청', '특수교육', '중등교육',
    '초등교육', '학교교육', '교육부', '교육감',
    '시행일', '수신처', '발신처', '참조',
    '운영계획', '세부계획', '추진계획', '실행계획',
    '관련', '협조', '시행', '검토', '결재', '기안',
    '대상자', '신청자', '참가자', '참여자', '수혜자',
    '보호자', '학부모', '학생', '교사', '직원',
    '교육지원', '특수교육과', '특수교육지원',
    '연락처', '전화번호', '팩스',
    '장애학생', '비장애', '일반학생',
    '프로그램', '운영', '계획', '수립', '지원',
    '기관명', '학교명', '기관',
    # 직급·직책 (이름과 혼동 방지)
    '장학사', '장학관', '교육연구사', '교육연구관',
    '사무관', '주무관', '행정사', '서기',
    '교감', '교장', '원장', '원감',
    '과장', '팀장', '계장', '실장', '국장', '부장',
    '선생님', '센터장',
}


def _is_likely_name(candidate: str) -> bool:
    """이름으로 볼 수 있는지 간단 필터"""
    if not candidate or len(candidate) < 2 or len(candidate) > 4:
        return False
    # 오탐 목록 체크
    if candidate in NOT_NAMES:
        return False
    # 모든 글자가 한글인지
    if not re.fullmatch(r'[가-힣]+', candidate):
        return False
    # 2글자 이름은 성씨 가능성 체크 (완벽하지 않지만 흔한 성씨로 시작하면 허용)
    common_surnames = set('김이박최정강조윤장임한오서신권황안송류전홍고문양손배조백허유남심노정하곽성차주우구신')
    if len(candidate) == 2 and candidate[0] not in common_surnames:
        return False
    return True


def _find_nearby_phone(line: str, start_pos: int) -> str:
    """줄에서 특정 위치 근처의 전화번호 추출"""
    # 이름 이후 50자 이내에서 전화번호 찾기
    search_area = line[start_pos:start_pos + 50]
    m = PHONE_PATTERN.search(search_area)
    if m:
        return m.group(1).strip()
    # 이름 이전 30자에서도 찾기
    search_before = line[max(0, start_pos - 30):start_pos]
    m = PHONE_PATTERN.search(search_before)
    if m:
        return m.group(1).strip()
    return ''


def _guess_role_from_line(line: str, roles: list) -> str:
    """같은 줄에서 역할 키워드 찾기"""
    for role in roles:
        if role in line:
            return role
    return ''


def _extract_context(line: str, start: int, end: int, padding: int = 20) -> str:
    """주변 문맥 추출"""
    ctx_start = max(0, start - padding)
    ctx_end = min(len(line), end + padding)
    context = line[ctx_start:ctx_end].strip()
    if ctx_start > 0:
        context = '…' + context
    if ctx_end < len(line):
        context = context + '…'
    return context


# ==============================
# 메인
# ==============================

def main():
    if len(sys.argv) >= 2 and sys.argv[1].startswith('--'):
        parser = argparse.ArgumentParser(description='공문서 내 인물명 추출')
        parser.add_argument('--input-file', help='텍스트 파일 경로 (긴 문서는 반드시 이 옵션을 사용)')
        parser.add_argument('--text', help='텍스트 직접 입력 (짧은 경우에만 사용)')
        args = parser.parse_args()
        if args.input_file:
            with open(args.input_file, encoding='utf-8') as f:
                text = f.read()
        elif args.text is not None:
            text = args.text
        else:
            print('입력이 없습니다: --input-file 또는 --text 중 하나를 지정하세요.', file=sys.stderr)
            sys.exit(1)
    elif len(sys.argv) < 2:
        print('사용법: python3 extract_persons.py --input-file <파일경로>', file=sys.stderr)
        sys.exit(1)
    else:
        # 구버전 하위 호환: 위치인자 1개 — 파일경로면 읽고, 아니면 텍스트 자체로 간주
        arg = sys.argv[1]
        try:
            with open(arg, encoding='utf-8') as f:
                text = f.read()
        except (FileNotFoundError, OSError):
            text = arg

    persons = extract_persons(text)

    result = {
        'persons': persons,
        'total_found': len(persons),
        'note': 'AI가 텍스트를 직접 읽어 추가 인물을 보완할 수 있습니다.'
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
