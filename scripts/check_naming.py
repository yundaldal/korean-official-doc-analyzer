#!/usr/bin/env python3
"""
문서 내 명칭 일관성 검증 스크립트

같은 행사·프로그램·기관을 지칭하는 명칭이 문서 안에서 혼용되고 있는지 탐지한다.

사용법:
    python3 check_naming.py "<추출된_텍스트>" <target_year>

출력(JSON):
    {
        "groups": [
            {
                "canonical": "가장 많이 등장한 명칭 (추정 공식명)",
                "variants": ["다른 표기 A", "다른 표기 B"],
                "issue_type": "연도혼용|축약혼용|띄어쓰기|기관명",
                "occurrences": {"명칭A": 5, "명칭B": 2},
                "recommendation": "통일 권장 명칭 및 이유"
            }
        ],
        "total_issues": N
    }
"""

import sys
import re
import json
from collections import Counter, defaultdict
from difflib import SequenceMatcher


# ==============================
# 명칭 후보 추출 패턴
# ==============================

# 한글 공문서에서 고유명사처럼 보이는 패턴들
EVENT_NAME_PATTERNS = [
    # "2026 ○○○한마당" 형태 — 연도 포함 행사명
    r'(?:20\d{2}\s+)?[가-힣]{2,15}(?:한마당|행사|대회|연수|워크숍|포럼|캠프|축제|발표회|공모전|교육|연구회)',
    # "제N회 ○○○" 형태
    r'제\s*\d+\s*회\s*[가-힣\s]{2,20}',
    # 연도 포함 사업·프로그램명
    r'(?:20\d{2}년?\s+)?[가-힣]{2,20}(?:사업|프로그램|운영|계획|지원)',
]

ORG_NAME_PATTERNS = [
    # 부서명: ○○교육청, ○○과, ○○팀
    r'[가-힣]{2,10}(?:교육청|교육지원청|교육원|학교|연구원)',
    r'[가-힣]{2,8}(?:특수교육과|특수교육지원과|교육과|지원과|기획과)',
    # "○○부" "○○처" 형태는 제외 (너무 일반적)
]


def extract_candidates(text: str) -> list[str]:
    """명칭 후보를 텍스트에서 추출"""
    candidates = []
    for pattern in EVENT_NAME_PATTERNS + ORG_NAME_PATTERNS:
        found = re.findall(pattern, text)
        candidates.extend([f.strip() for f in found if len(f.strip()) >= 4])
    return candidates


# ==============================
# 유사도 판단
# ==============================

def similarity(a: str, b: str) -> float:
    """두 문자열의 유사도 (0~1)"""
    return SequenceMatcher(None, a, b).ratio()


def normalize(name: str) -> str:
    """비교를 위한 정규화: 연도·공백·특수문자 제거"""
    n = re.sub(r'20\d{2}', '', name)   # 연도 제거
    n = re.sub(r'\s+', '', n)           # 공백 제거
    n = re.sub(r'[^\w가-힣]', '', n)    # 특수문자 제거
    return n.strip()


def group_similar(names: list[str], threshold: float = 0.72) -> list[list[str]]:
    """유사한 명칭끼리 묶기 (Union-Find 방식)"""
    parent = list(range(len(names)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            ni, nj = normalize(names[i]), normalize(names[j])
            if not ni or not nj:
                continue
            # 완전 포함 관계 또는 높은 유사도
            if ni in nj or nj in ni or similarity(ni, nj) >= threshold:
                union(i, j)

    groups = defaultdict(list)
    for i, name in enumerate(names):
        groups[find(i)].append(name)

    return [sorted(set(g), key=len, reverse=True) for g in groups.values() if len(set(g)) > 1]


# ==============================
# 연도 혼용 전용 탐지
# ==============================

def detect_year_mixing(text: str, target_year: str) -> list[dict]:
    """같은 행사명인데 연도 표기가 다른 경우 탐지"""
    issues = []

    # 연도 포함 명칭 추출: "20XX ○○○" 패턴
    year_name_pattern = r'(20\d{2})\s+([가-힣]{3,20}(?:한마당|행사|대회|연수|워크숍|포럼|캠프|축제|발표회|교육|사업|프로그램))'
    matches = re.findall(year_name_pattern, text)

    # 행사 기반명(연도 제거) 별로 연도들 수집
    base_years = defaultdict(set)
    for year, base_name in matches:
        key = normalize(base_name)
        if key:
            base_years[key].add(year)

    for base_key, years in base_years.items():
        if len(years) > 1:
            # 여러 연도가 같은 행사명에 등장
            year_list = sorted(years)
            # 실제 표기 원본 복원
            original_forms = []
            for yr in year_list:
                pattern = rf'{yr}\s+[가-힣]*{re.escape(base_key[:4])}[가-힣]*'
                found = re.findall(pattern, text)
                original_forms.extend(found[:2])

            issues.append({
                "canonical": f"{target_year} {base_key}",
                "variants": list(set(original_forms)) if original_forms else [f"{y} {base_key}" for y in year_list],
                "issue_type": "연도혼용",
                "occurrences": {yr: text.count(yr + ' ') for yr in year_list},
                "recommendation": f"'{target_year} {base_key}'로 통일. 다른 연도 표기 ({', '.join(y for y in year_list if y != target_year)}) 잔존 여부 확인"
            })

    return issues


# ==============================
# 띄어쓰기 불일치 탐지
# ==============================

def detect_spacing_variants(text: str, candidates: list[str], counts: Counter) -> list[dict]:
    """같은 명칭인데 띄어쓰기만 다른 경우"""
    issues = []
    processed = set()

    for name in candidates:
        if name in processed:
            continue
        # 공백 유무 두 가지 형태 모두 검색
        no_space = name.replace(' ', '')
        with_space_variants = []

        # 2~3글자 단위로 공백 삽입 시도
        if ' ' not in name and len(name) >= 4:
            # 흔한 한국어 띄어쓰기 경계 (2·2, 2·3, 3·2, 3·3)
            for split in [2, 3]:
                variant = name[:split] + ' ' + name[split:]
                if variant in text and variant != name:
                    with_space_variants.append(variant)

        for variant in with_space_variants:
            if counts.get(name, 0) > 0 and counts.get(variant, 0) > 0:
                canonical = name if counts[name] >= counts[variant] else variant
                other = variant if canonical == name else name
                issues.append({
                    "canonical": canonical,
                    "variants": [other],
                    "issue_type": "띄어쓰기",
                    "occurrences": {name: counts[name], variant: counts[variant]},
                    "recommendation": f"띄어쓰기 통일 필요: '{canonical}' 또는 '{other}' 중 공식 표기로 통일"
                })
                processed.add(name)
                processed.add(variant)

    return issues


# ==============================
# 메인 분석
# ==============================

def analyze_naming(text: str, target_year: str) -> dict:
    all_issues = []

    # ① 연도 혼용 탐지 (가장 중요)
    year_issues = detect_year_mixing(text, target_year)
    all_issues.extend(year_issues)

    # ② 유사 명칭 군집 탐지
    candidates_raw = extract_candidates(text)
    counts = Counter(candidates_raw)
    unique_candidates = list(counts.keys())

    similar_groups = group_similar(unique_candidates)
    for group in similar_groups:
        if len(group) < 2:
            continue

        # 가장 많이 등장한 것을 공식명으로 추정
        canonical = max(group, key=lambda x: counts.get(x, 0))
        variants = [v for v in group if v != canonical]

        # 이슈 타입 판단
        norms = [normalize(v) for v in group]
        if all(n in normalize(canonical) or normalize(canonical) in n for n in norms):
            issue_type = "축약혼용"
            recommendation = f"'{canonical}'이 가장 많이 등장하는 공식명으로 추정됩니다. 축약 표기({', '.join(variants)})를 공식명으로 통일하세요."
        else:
            issue_type = "유사명혼용"
            recommendation = f"'{canonical}'과 유사한 명칭이 혼용됩니다. 공식 명칭을 확인하고 통일하세요."

        # 이미 연도혼용으로 처리된 그룹과 중복 방지
        if not any(canonical in str(yi.get('variants', '')) or canonical == yi.get('canonical', '') for yi in year_issues):
            all_issues.append({
                "canonical": canonical,
                "variants": variants,
                "issue_type": issue_type,
                "occurrences": {v: counts.get(v, 0) for v in group},
                "recommendation": recommendation
            })

    # ③ 띄어쓰기 불일치
    spacing_issues = detect_spacing_variants(text, unique_candidates, counts)
    all_issues.extend(spacing_issues)

    return {
        "groups": all_issues,
        "total_issues": len(all_issues)
    }


# ==============================
# 메인
# ==============================

def main():
    if len(sys.argv) < 3:
        print("사용법: check_naming.py <텍스트> <target_year>", file=sys.stderr)
        sys.exit(1)

    text = sys.argv[1]
    target_year = sys.argv[2]

    result = analyze_naming(text, target_year)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
