import streamlit as st
import google.generativeai as genai
import pdfplumber
import os

# [중요] 발급받은 실제 API 키로 변경해 주세요
GOOGLE_API_KEY = "AQ.Ab8RN6KwA02mIILTd13GWXQx8Y4asqYRm6yOiff-qA76OEGFzg" 
genai.configure(api_key=GOOGLE_API_KEY)

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

st.set_page_config(page_title="하수처리시설 기술지원 AI 챗봇", layout="wide")
st.title("🛠️ 하수처리시설 기술지원 AI 어시스턴트")
st.caption("사례집 내용을 기반으로 운영 문제점과 개선방안을 도출합니다.")

pdf_files = ["기술진단사례집(08~09년 기후부).pdf", "기술진단 사례집(13~17년_동부).pdf"]

with st.spinner("기술진단 사례집 내용을 분석 중입니다... (최초 1회 소요)"):
    knowledge_base = load_pdf_text(pdf_files)

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
                # 1단계 업데이트 후, 가장 표준적인 텍스트 모델인 'gemini-pro'로 매칭합니다.
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                prompt = f"""
                당신은 하·폐수 처리장 기술진단 전문가입니다. 
                제공된 [기술진단 사례집]의 내용을 바탕으로 사용자의 [질문]에 답변하세요.
                
                [사례집 문맥 규칙]
                - 사례집 내용 중 '◇' 기호 뒤에 나오는 내용은 해당 사례의 '문제점(현상/원인)'을 의미합니다.
                - 사례집 내용 중 '☞' 기호 뒤에 나오는 내용은 해당 사례의 '개선방안(대책)'을 의미합니다.
                
                [지침]
                1. 사용자의 [질문]과 가장 유사한 문제 상황을 [기술진단 사례집]에서 검색하세요.
                2. 답변은 반드시 아래 서식에 맞춰 깔끔하게 구분하여 출력하세요:
                   - **유사 사례 상황:** (사례집에서 찾은 핵심 상황 요약)
                   - **원인 및 문제점 (◇ 참고):** (◇ 기호 뒤 내용을 바탕으로 요약)
                   - **구체적 개선방안 (☞ 참고):** (☞ 기호 뒤 내용을 바탕으로 요약)

                [기술진단 사례집 내용]
                {knowledge_base[:50000]}

                [질문]
                {user_question}
                """
                
                response = model.generate_content(prompt)
                ai_answer = response.text
                
                st.markdown(ai_answer)
                st.session_state.messages.append({"role": "assistant", "content": ai_answer})
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
