import streamlit as st
import google.generativeai as genai
import json
import os
import re

# [중요] 발급받은 실제 API 키로 변경해 주세요
GOOGLE_API_KEY = "여기에_새로_발급받은_키를_넣으세요"
genai.configure(api_key=GOOGLE_API_KEY)

CONTEXT_CHAR_BUDGET = 60000  # Gemini 무료 티어 분당 25만 토큰 한도를 넘지 않도록 제한
MAX_CASES = 30               # 한 번에 프롬프트에 넣을 최대 사례 수

# --------------------------------------------------------------------------
# [데이터 로드] split_cases.py가 미리 만들어둔 cases.json을 읽는다
# - 예전처럼 매번 PDF를 파싱하지 않으므로 시작이 훨씬 빠름
# - cases.json이 없으면 안내 메시지를 띄우고 중단
# --------------------------------------------------------------------------
@st.cache_data
def load_cases():
    if not os.path.exists("cases.json"):
        return None
    with open("cases.json", "r", encoding="utf-8") as f:
        return json.load(f)

def case_to_text(case):
    """사례 1건을 프롬프트에 넣을 텍스트로 변환 (섹션 정보 = 검색 힌트 겸 문맥)"""
    parts = []
    if case["section"] or case["subsection"]:
        parts.append(f"[분류] {case['section']} > {case['subsection']}".strip(" >"))
    parts.append(f"[문제점] {case['problem']}")
    if case["solution"]:
        parts.append(f"[개선방안] {case['solution']}")
    parts.append(f"[출처] {case['source']}")
    return "\n".join(parts)

# --------------------------------------------------------------------------
# [검색] 키워드 점수로 관련 사례를 골라낸다 (조각이 아니라 '사례' 단위!)
# --------------------------------------------------------------------------
def _keywords(question):
    words = re.split(r"[\s,.:;!?()\[\]{}\"'/·・,]+", question)
    return [w for w in words if len(w) >= 2]

def _bigrams(question):
    s = re.sub(r"\s+", "", question)
    return {s[i:i + 2] for i in range(len(s) - 1)}

def select_relevant_cases(cases, question, char_budget=CONTEXT_CHAR_BUDGET):
    words = _keywords(question)
    bigrams = _bigrams(question)

    scored = []
    for case in cases:
        # 분류(섹션) 제목에 걸리면 가중치를 더 준다 (예: "침전지" 질문 → 침전지 섹션 사례)
        title_text = case["section"] + " " + case["subsection"]
        body_text = case["problem"] + " " + case["solution"]

        score = sum(title_text.count(w) * 6 for w in words)
        score += sum(body_text.count(w) * 3 for w in words)
        score += sum(body_text.count(bg) for bg in bigrams)
        if score > 0:
            scored.append((score, case))

    scored.sort(key=lambda x: x[0], reverse=True)

    selected = []
    total_chars = 0
    for score, case in scored[:MAX_CASES]:
        text = case_to_text(case)
        if total_chars + len(text) > char_budget:
            break
        selected.append(text)
        total_chars += len(text)

    return selected

# --------------------------------------------------------------------------
# [UI]
# --------------------------------------------------------------------------
st.set_page_config(page_title="하수처리시설 기술지원 AI 챗봇", layout="wide")
st.title("🛠️ 하수처리시설 기술지원 AI 어시스턴트")
st.caption("사례집 내용을 기반으로 운영 문제점과 개선방안을 도출합니다.")

knowledge_cases = load_cases()

if knowledge_cases is None:
    st.error("cases.json 파일이 없습니다. 먼저 터미널에서 `python split_cases.py`를 한 번 실행해 주세요.")
    st.stop()
else:
    st.success(f"기술진단 사례 {len(knowledge_cases)}건 로드 완료!")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_question := st.chat_input("처리장의 현상이나 문제점을 입력하세요."):
    with st.chat_message("user"):
        st.markdown(user_question)
    st.session_state.messages.append({"role": "user", "content": user_question})

    with st.chat_message("assistant"):
        with st.spinner("사례집에서 유사 사례와 개선방안을 찾는 중..."):
            try:
                relevant_cases = select_relevant_cases(knowledge_cases, user_question)

                if not relevant_cases:
                    ai_answer = "질문과 관련된 사례를 사례집에서 찾지 못했습니다. 다른 표현으로 다시 질문해 주세요."
                    st.markdown(ai_answer)
                    st.session_state.messages.append({"role": "assistant", "content": ai_answer})
                else:
                    context_text = "\n\n---\n\n".join(relevant_cases)

                    model = genai.GenerativeModel('gemini-2.5-flash')

                    prompt = f"""
                    당신은 하·폐수 처리장 기술진단 전문가입니다.
                    아래 [기술진단 사례 목록]은 방대한 사례집에서 사용자의 [질문]과 관련된
                    사례만 미리 추려낸 것입니다. 각 사례는 [분류], [문제점], [개선방안], [출처]로
                    이미 구분되어 있습니다.

                    [지침]
                    1. 사용자의 [질문]과 동일하거나 유사한 사례를 목록에서 찾을 수 있는 만큼(최대 5개) 모두 찾으세요.
                    2. 찾은 사례가 여러 개라면 아래처럼 번호를 매겨 각각 나열하세요. 사례가 1개뿐이면 1개만 출력하세요.
                    3. 각 사례는 반드시 아래 서식에 맞춰 출력하세요:
                       **사례 N** (출처: 해당 사례의 출처)
                       - **문제 상황:** ([문제점] 내용 요약)
                       - **개선방안:** ([개선방안] 내용 요약)
                    4. 목록에서 유사한 사례를 하나도 찾지 못하면, 없다고 명확히 답변하세요.
                    5. 사례에 없는 내용을 지어내지 마세요.

                    [기술진단 사례 목록]
                    {context_text}

                    [질문]
                    {user_question}
                    """

                    response = model.generate_content(prompt)
                    ai_answer = response.text

                    st.markdown(ai_answer)
                    st.session_state.messages.append({"role": "assistant", "content": ai_answer})

            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
