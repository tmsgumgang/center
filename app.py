import streamlit as st
import google.generativeai as genai
import pdfplumber
import os
import re

# [중요] 발급받은 실제 API 키로 변경해 주세요
GOOGLE_API_KEY = "AQ.Ab8RN6KwA02mIILTd13GWXQx8Y4asqYRm6yOiff-qA76OEGFzg"
genai.configure(api_key=GOOGLE_API_KEY)

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
CONTEXT_CHAR_BUDGET = 60000  # Gemini 무료 티어 분당 25만 토큰 한도를 넘지 않도록 제한

@st.cache_data
def load_pdf_text(file_paths):
    full_text = ""
    for path in file_paths:
        if os.path.exists(path):
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n"
    return full_text

@st.cache_data
def build_chunks(text):
    chunks = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for start in range(0, len(text), step):
        chunk = text[start:start + CHUNK_SIZE]
        if chunk.strip():
            chunks.append(chunk)
    return chunks

def _keywords(question):
    words = re.split(r"[\s,.:;!?()\[\]{}\"'/·・,]+", question)
    return [w for w in words if len(w) >= 2]

def _bigrams(question):
    s = re.sub(r"\s+", "", question)
    return {s[i:i + 2] for i in range(len(s) - 1)}

def select_relevant_chunks(chunks, question, char_budget=CONTEXT_CHAR_BUDGET):
    words = _keywords(question)
    bigrams = _bigrams(question)

    scored = []
    for chunk in chunks:
        score = sum(chunk.count(w) * 3 for w in words)
        score += sum(chunk.count(bg) for bg in bigrams)
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)

    selected = []
    total_chars = 0
    for score, chunk in scored:
        if total_chars + len(chunk) > char_budget:
            break
        selected.append(chunk)
        total_chars += len(chunk)

    return selected

st.set_page_config(page_title="하수처리시설 기술지원 AI 챗봇", layout="wide")
st.title("🛠️ 하수처리시설 기술지원 AI 어시스턴트")
st.caption("사례집 내용을 기반으로 운영 문제점과 개선방안을 도출합니다.")

pdf_files = ["기술진단사례집(08~09년 기후부).pdf", "기술진단 사례집(13~17년_동부).pdf"]

with st.spinner("기술진단 사례집 내용을 분석 중입니다... (최초 1회 소요)"):
    knowledge_base = load_pdf_text(pdf_files)
    knowledge_chunks = build_chunks(knowledge_base)

if not knowledge_base:
    st.error("PDF 파일을 찾을 수 없습니다. 파일명을 확인해주세요.")
else:
    st.success("기술진단 사례집 로드 완료!")

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
                relevant_chunks = select_relevant_chunks(knowledge_chunks, user_question)

                if not relevant_chunks:
                    ai_answer = "질문과 관련된 사례를 사례집에서 찾지 못했습니다. 다른 표현으로 다시 질문해 주세요."
                    st.markdown(ai_answer)
                    st.session_state.messages.append({"role": "assistant", "content": ai_answer})
                else:
                    context_text = "\n\n---\n\n".join(relevant_chunks)

                    # 1단계 업데이트 후, 가장 표준적인 텍스트 모델인 'gemini-pro'로 매칭합니다.
                    model = genai.GenerativeModel('gemini-2.5-flash')

                    prompt = f"""
                    당신은 하·폐수 처리장 기술진단 전문가입니다.
                    아래 [기술진단 사례집 발췌]는 방대한 사례집 중 사용자의 [질문]과 키워드가 겹치는 부분만 미리 추려낸 것입니다.
                    이 발췌 내용을 바탕으로 사용자의 [질문]에 답변하세요.

                    [사례집 문맥 규칙]
                    - 사례집 내용 중 '◇' 기호 뒤에 나오는 내용은 해당 사례의 '문제점(현상/원인)'을 의미합니다.
                    - 사례집 내용 중 '☞' 기호 뒤에 나오는 내용은 해당 사례의 '개선방안(대책)'을 의미합니다.
                    - 이런 기호가 없는 발췌는 표 형태(구분/문제점/개선방안)로 정리된 사례이니 문맥으로 문제점과 개선방안을 구분하세요.

                    [지침]
                    1. 사용자의 [질문]과 동일하거나 유사한 문제 상황을 [기술진단 사례집 발췌]에서 찾을 수 있는 만큼(최대 5개) 모두 찾으세요.
                    2. 찾은 사례가 여러 개라면 아래처럼 번호를 매겨 각각 나열하세요. 사례가 1개뿐이면 1개만 출력하세요.
                    3. 각 사례는 반드시 아래 서식에 맞춰 출력하세요:
                       **사례 N**
                       - **문제 상황:** (발췌에서 찾은 핵심 상황 요약)
                       - **원인:** (관련 원인 요약)
                       - **개선방안:** (관련 개선방안 요약)
                    4. 발췌 내용 중 유사한 사례를 하나도 찾지 못하면, 없다고 명확히 답변하세요.

                    [기술진단 사례집 발췌]
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
