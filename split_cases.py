# -*- coding: utf-8 -*-
"""
기술진단 사례집 2종을 '사례 단위'로 자르는 스크립트
- 사례집A (08~09년 기후부): ◇(문제점) / ☞(개선방안) 기호 기반 → 텍스트 패턴으로 자름
- 사례집B (13~17년 동부): 구분/문제점/개선방안 3열 표 기반 → 표 추출로 자름
결과: cases.json (사례 리스트) — app.py에서 이 파일을 읽어 chunk로 사용
"""
import pdfplumber
import re
import json
import glob

# ==========================================================================
# [사례집A] 08~09년: ◇ 문제점 ... ☞ 개선방안 ... 패턴
# ==========================================================================
def parse_pdf_symbol_based(path):
    """◇/☞ 기호로 사례를 자른다. 섹션 제목(구 분 ① ...)을 문맥으로 함께 저장."""
    # 1) 전체 텍스트 추출
    full_text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                full_text += t + "\n"

    lines = full_text.split("\n")

    # 페이지 머리글/바닥글 제거 (사례 중간에 끼어드는 노이즈)
    noise_patterns = [
        re.compile(r"^\s*-\s*\d+\s*-\s*$"),                    # - 123 - (페이지 번호)
        re.compile(r"^2008~2009년 하수ㆍ분뇨 처리시설 기술진단 사례"),  # 머리글
        re.compile(r"^제\d장\s"),                                # 장 제목 머리글
    ]
    def is_noise(line):
        return any(p.match(line) for p in noise_patterns)

    cases = []
    section = ""       # 현재 섹션 (예: 2.3.1 하수유입특성)
    subsection = ""    # 현재 소구분 (예: ① 하수유입량 및 수질이 ...)
    cur = None         # 지금 만들고 있는 사례 {"problem": [...], "solution": [...]}
    mode = None        # 'problem' 또는 'solution' — 이어지는 줄을 어디에 붙일지

    def flush():
        """만들던 사례를 완성해서 목록에 추가"""
        nonlocal cur
        if cur and cur["problem"]:
            cases.append({
                "source": "기술진단사례집(08~09년)",
                "section": section,
                "subsection": subsection,
                "problem": " ".join(cur["problem"]).strip(),
                "solution": " ".join(cur["solution"]).strip(),
            })
        cur = None

    sec_re = re.compile(r"^(\d+\.\d+(\.\d+)?)\s+(.+)$")          # 2.3.1 하수유입특성
    sub_re = re.compile(r"^구\s*분\s*([①-⑳].*)$")               # 구 분 ① ...
    sub_only_re = re.compile(r"^([①-⑳]\s*.+)$")                  # ① ... (줄 시작)

    for raw in lines:
        line = raw.strip()
        if not line or is_noise(line):
            continue

        # 섹션 제목 갱신 (목차의 '.....' 줄은 제외)
        m = sec_re.match(line)
        if m and "·" not in line:
            flush()
            section = f"{m.group(1)} {m.group(3)}"
            subsection = ""
            mode = None
            continue

        # 소구분 제목 갱신
        m = sub_re.match(line) or sub_only_re.match(line)
        if m:
            flush()
            subsection = m.group(1).strip()
            mode = None
            continue

        # '개선방안' 라벨이 줄 앞에 붙는 경우 제거 (예: "개선방안 ◇ ...")
        line = re.sub(r"^개선방안\s+", "", line)

        # ◇ = 새 사례의 문제점 시작
        if line.startswith("◇"):
            flush()
            cur = {"problem": [line[1:].strip()], "solution": []}
            mode = "problem"
            continue

        # ☞ = 현재 사례의 개선방안 시작
        if line.startswith("☞"):
            if cur is None:  # 문제점 없이 개선방안만 나오는 예외 케이스
                cur = {"problem": [""], "solution": []}
            cur["solution"].append(line[1:].strip())
            mode = "solution"
            continue

        # 이어지는 줄: 직전 모드에 붙임
        if cur is not None and mode:
            cur[mode].append(line)

    flush()
    return cases


# ==========================================================================
# [사례집B] 13~17년: 구분/문제점/개선방안(사례) 3열 표
# ==========================================================================
def parse_pdf_table_based(path):
    """표를 추출해서 행 = 사례 1건으로 자른다. 페이지 넘어가는 행도 이어붙인다."""
    cases = []
    section = ""     # 예: 2.3.2 연계처리수 유입특성
    subsection = ""  # 예: ① 연계방법 부적절

    sec_re = re.compile(r"^(\d+\.\d+(\.\d+)?)\s+(.+)$")
    sub_re = re.compile(r"^[①-⑳]\s*.+$")

    def clean(cell):
        """셀 안의 줄바꿈을 공백으로 바꾸고 정리"""
        if not cell:
            return ""
        return re.sub(r"\s+", " ", cell).strip()

    prev_case = None  # 페이지를 넘어 이어지는 행 처리용

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            # 표 밖 텍스트에서 섹션 제목 추적
            txt = page.extract_text() or ""
            for line in txt.split("\n"):
                line = line.strip()
                m = sec_re.match(line)
                if m and "·" not in line:
                    section = f"{m.group(1)} {m.group(3)}"

            for table in page.extract_tables():
                header_seen = False
                for row in table:
                    row = [clean(c) for c in row]
                    if not any(row):
                        continue

                    # 소구분 제목 행 (예: ['③ 유입수질 높음', '', ''])
                    if sub_re.match(row[0]) and not any(row[1:]):
                        subsection = row[0]
                        prev_case = None
                        continue

                    # 헤더 행 (구분/문제점/개선방안)
                    if "문제점" in row and any("개선방안" in c for c in row):
                        header_seen = True
                        prev_case = None
                        continue

                    if len(row) < 3:
                        continue
                    num, problem, solution = row[0], row[1], row[2]

                    if num and num.isdigit():
                        # 새 사례 시작
                        case = {
                            "source": "기술진단사례집(13~17년)",
                            "section": section,
                            "subsection": subsection,
                            "problem": problem,
                            "solution": solution,
                        }
                        cases.append(case)
                        prev_case = case
                    elif prev_case is not None and (problem or solution):
                        # 구분 번호가 없는 행 = 직전 사례가 페이지를 넘어 이어진 것
                        if problem:
                            prev_case["problem"] += " " + problem
                        if solution:
                            prev_case["solution"] += " " + solution
    return cases


# ==========================================================================
# 실행
# ==========================================================================
if __name__ == "__main__":
    pdfs = sorted(glob.glob("*.pdf"))
    all_cases = []
    for p in pdfs:
        if "08~09" in p or "08∼09" in p:
            got = parse_pdf_symbol_based(p)
        else:
            got = parse_pdf_table_based(p)
        print(f"{p}: {len(got)}건")
        all_cases.extend(got)

    # 너무 짧은 파편 제거 (문제점+개선방안 합쳐 40자 미만은 노이즈로 간주)
    before = len(all_cases)
    all_cases = [c for c in all_cases if len(c["problem"]) + len(c["solution"]) >= 40]
    print(f"노이즈 제거: {before} -> {len(all_cases)}건")

    with open("cases.json", "w", encoding="utf-8") as f:
        json.dump(all_cases, f, ensure_ascii=False, indent=1)
    print("cases.json 저장 완료")
