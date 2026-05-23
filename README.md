# 🇰🇷 Korean Official Document Analyzer

대한민국 공문서·계획서 전용 AI 분석 스킬  
**Claude / GPT / Gemini 등 모든 LLM에서 사용 가능**

---

## 📌 개요

교육청·학교 등 행정기관에서 작성하는 공문서를 AI가 자동으로 검토합니다.  
날짜·요일 오류, 맞춤법, 명칭 불일치, 연도 변경 누락 등을 한 번에 탐지합니다.

### 두 가지 분석 모드 자동 판별

| 모드 | 사용 상황 |
|---|---|
| 🔵 **공문서 교정 모드** | 현재 작성 중인 공문의 오류 점검 |
| 🟠 **연도변경 분석 모드** | 작년 계획서를 올해 버전으로 전환 |

---

## 📁 파일 구성

```
korean-official-doc-analyzer/
├── README.md          ← 이 파일
├── SKILL.md           ← AI에게 전달할 스킬 정의 (핵심)
└── scripts/
    ├── verify_dates.py    ← 날짜·요일 정확성 검증
    ├── check_naming.py    ← 명칭 일관성 검증
    ├── compare_docs.py    ← 두 문서 비교 (연도변경 모드 B)
    └── section_parser.py  ← 섹션 구조 분류
```

---

## 🚀 사용 방법

### Claude (claude.ai / Claude Desktop)

**방법 1 — SKILL.md 직접 붙여넣기**
1. `SKILL.md` 파일 내용을 복사
2. Claude 대화창에 붙여넣은 뒤 분석할 문서를 업로드
3. "공문 검토해줘" 또는 "연도 바꿔야 할 곳 찾아줘" 입력

**방법 2 — Claude Desktop 스킬 등록**
1. `korean-official-doc-analyzer` 폴더 전체를 클론
2. `~/.claude/skills/` 경로에 폴더 복사
3. Claude Desktop에서 자동으로 스킬 인식

```bash
git clone https://github.com/<your-username>/korean-official-doc-analyzer.git
cp -r korean-official-doc-analyzer ~/.claude/skills/
```

---

### GPT (ChatGPT)

1. `SKILL.md` 전체 내용을 복사
2. ChatGPT 대화 시작 시 "다음 지침을 따라 분석해줘:" 후 붙여넣기
3. 분석할 공문서 파일 업로드 또는 텍스트 입력

```
다음 지침을 따라 공문서를 분석해줘:

[SKILL.md 내용 전체 붙여넣기]

---
분석할 문서: [파일 업로드 또는 텍스트 입력]
```

---

### Gemini (Google AI Studio / Gemini Advanced)

1. `SKILL.md` 내용을 System Instruction 또는 첫 번째 메시지에 삽입
2. 문서 첨부 후 분석 요청

**Google AI Studio 사용 시:**
- System Instruction 칸에 `SKILL.md` 내용 붙여넣기
- 문서 파일 첨부 후 "공문 검토해줘" 입력

---

## ✅ 지원 파일 형식

| 형식 | 교정 모드 | 연도변경 모드 |
|---|---|---|
| `.hwpx` (한글) | ✅ | ✅ |
| `.docx` (Word) | ✅ | ✅ |
| `.pdf` | ✅ | ✅ |
| `.txt` / `.md` | ✅ | ✅ |
| 이미지 (캡처본) | ✅ (OCR) | ❌ |
| 텍스트 직접 입력 | ✅ | ❌ |

---

## 🔍 탐지 항목

### 🔵 공문서 교정 모드
- 한국어 맞춤법·어법 오류 (국립국어원 기준)
- 날짜·요일 정확성 (Python datetime으로 계산)
- 단어 누락·반복·비정상 표현
- 명칭 일관성 검증

### 🟠 연도변경 분석 모드
- 🔴 기존 문서 자체 오류
- 🟠 연도 필수 변경 항목
- 🟡 날짜 전면 재설정 필요 항목
- 🟢 내용 갱신 필요 항목 (인사·예산·실적)
- 🟣 명칭 불일치 탐지
- 🔵 사용자 직접 확인 필요 항목

---

## 💡 사용 예시 (트리거 문장)

```
공문 검토해줘
공문에 오류 있어?
날짜 맞는지 확인해줘
작년 계획서 분석해줘
2025 문서를 2026으로 바꿔야 할 곳 찾아줘
두 문서 비교해서 미변경 항목 찾아줘
```

---

## ⚙️ scripts 실행 환경

- **Python 3.8 이상** 필요
- 별도 외부 패키지 없음 (표준 라이브러리만 사용)

```bash
# 날짜·요일 검증
python3 scripts/verify_dates.py "문서텍스트" 2026

# 명칭 일관성 검증
python3 scripts/check_naming.py "문서텍스트" 2026

# 두 문서 비교
python3 scripts/compare_docs.py --old-text "과거문서" --new-text "현재문서" --source-year 2025 --target-year 2026
```

---

## 📝 라이선스

MIT License — 자유롭게 사용·수정·배포 가능합니다.  
교육 현장에서 선생님들이 편하게 쓸 수 있도록 만들었습니다.

---

## 🙋 만든 이

특수교육 현장에서 공문서 작성 부담을 줄이기 위해 개발했습니다.  
개선 아이디어나 버그 제보는 Issues에 남겨주세요.
