# chatbot_app.py
import streamlit as st
import google.generativeai as genai
import os
from dotenv import load_dotenv
from datetime import datetime
import requests
import json

# --- 0. 출판사 목록 및 정규화 함수 ---
ORIGINAL_MAJOR_PUBLISHERS = [
    "시공사", "위즈덤하우스", "창비", "북이십일", "김영사", "다산북스", "알에이치코리아", 
    "쌤앤파커스", "영림카디널", "내 인생의 책", "바람의아이들", "스타북스", "비룡소", 
    "국민서관", "웅진씽크빅", "계림북스", "계몽사", "문학수첩", "민음사", "밝은세상",
    "범우사", "문학과지성사", "문학동네", "사회평론", "자음과모음", "중앙M&B", 
    "창작과비평사", "한길사", "은유출판", "열린책들", "살림출판사", "학지사", "박영사", 
    "안그라픽스", "길벗", "제이펍", "다락원", "평단문화사", "정보문화사", "영진닷컴", 
    "성안당", "박문각", "넥서스북", "리스컴", "가톨릭출판사", "대한기독교서회", 
    "한국장로교출판사", "아가페출판사", "분도출판사"
]

def normalize_publisher_name(name):
    if not isinstance(name, str): name = ""
    name_lower = name.lower()
    name_processed = name_lower.replace("(주)", "").replace("주식회사", "").replace("㈜", "")
    name_processed = name_processed.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").replace(",", "")
    if "알에이치코리아" in name_processed or "랜덤하우스코리아" in name_processed: return "알에이치코리아"
    if "문학과지성" in name_processed : return "문학과지성사"
    if "창작과비평" in name_processed : return "창작과비평사"
    if "김영사" in name_processed : return "김영사"
    if "위즈덤하우스" in name_processed : return "위즈덤하우스"
    return name_processed

MAJOR_PUBLISHERS_NORMALIZED = {normalize_publisher_name(p) for p in ORIGINAL_MAJOR_PUBLISHERS}
EXCLUDED_PUBLISHER_KEYWORDS = ["씨익북스", "ceic books"]

# --- 1. 기본 설정 및 API 키 준비 ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY"); KAKAO_API_KEY = os.getenv("KAKAO_REST_API_KEY")
gemini_model_name = 'gemini-2.0-flash-lite'
gemini_model = None; gemini_api_error = None; kakao_api_error = None
if GEMINI_API_KEY:
    try: genai.configure(api_key=GEMINI_API_KEY); gemini_model = genai.GenerativeModel(gemini_model_name)
    except Exception as e: gemini_api_error = f"Gemini API ({gemini_model_name}) 설정 오류: {e}"
else: gemini_api_error = "Gemini API 키가 .env에 설정되지 않았어요! 🗝️"
if not KAKAO_API_KEY: kakao_api_error = "Kakao REST API 키가 .env에 설정되지 않았어요! 🔑"

# --- library_db.py 함수 가져오기 ---
try:
    from library_db import find_book_in_library_by_isbn
except ImportError:
    if not st.session_state.get('library_db_import_warning_shown', False):
        st.warning("`library_db.py` 또는 `find_book_in_library_by_isbn` 함수 없음! (임시 기능 사용)", icon="😿")
        st.session_state.library_db_import_warning_shown = True
    def find_book_in_library_by_isbn(isbn_query): return {"found_in_library": False, "error": "도서관 DB 모듈 로드 실패"}

# --- 세션 상태 초기화 ---
if 'TODAYS_DATE' not in st.session_state:
    st.session_state.TODAYS_DATE = datetime.now().strftime("%Y년 %m월 %d일")
    if not st.session_state.get('app_already_run_once', False):
         st.session_state.app_already_run_once = True
if 'liked_books_list' not in st.session_state: st.session_state.liked_books_list = []
if 'current_book_to_add' not in st.session_state: st.session_state.current_book_to_add = ""

# --- 2. AI 및 API 호출 관련 함수들 ---
def create_prompt_for_search_query(student_data):
    level_desc = student_data["reading_level"] # 이건 "새싹탐험가..." 같은 긴 설명
    topic = student_data["topic"]
    # age_grade 대신 student_age_group_selection 사용
    age_grade_selection = student_data["student_age_group"] # "초등학생", "중학생", "고등학생", "선택안함"
    difficulty_hint = student_data["difficulty_hint"] # 실제 난이도 조절 힌트

    genres_str = ", ".join(student_data["genres"]) if student_data["genres"] else "특별히 없음"
    interests = student_data["interests"]
    liked_books_str = ", ".join(student_data["liked_books"]) if student_data["liked_books"] else "언급된 책 없음"

    age_specific_instruction = ""
    if "초등학생" in age_grade_selection:
        age_specific_instruction = "생성되는 모든 검색어는 반드시 초등학생이 이해할 수 있는 매우 쉬운 단어로 구성되어야 하며, 초등학생 대상의 도서를 찾는 데 적합해야 합니다. 어려운 한자어나 전문 용어는 절대 포함하지 마세요."

    prompt = f"""
당신은 학생의 요구사항을 분석하여 한국 도서 검색 API에서 사용할 **다양하고 효과적인 검색어들을 최대 3-4개까지 생성하는** AI 어시스턴트입니다.
학생의 정보를 바탕으로, 관련 도서를 폭넓게 찾기 위한 검색어 목록을 다음 지침에 따라 제안해주세요:

1.  **핵심 주제 유지 및 일반화:** 학생의 '주요 탐구 주제'를 그대로 사용하거나, 약간 더 일반적이거나 포괄적인 표현으로 바꾼 검색어 1개를 생성합니다.
2.  **핵심 키워드 추출 및 확장:** 학생의 '주요 탐구 주제' 및 '주제 관련 특별 관심사'에서 핵심적인 단어(명사 위주) 1~2개를 식별합니다.
3.  **확장된 검색어 생성:** 식별된 각 핵심 단어에 대해, 관련된 동의어, 유사어, 좀 더 넓은 개념, 또는 구체적인 하위 개념을 포함하는 파생 검색어를 1개씩 생성합니다.
    * **주의:** 학생의 주제를 너무 잘게 쪼개거나, 아주 세부적인 하위 주제 여러 개로 나누어 검색어를 만들지 마세요. 오히려 핵심 주제를 포괄할 수 있는 다양한 표현을 찾아주세요.
4.  **최종 목록:** 위 과정을 통해 생성된 검색어들을 종합하여, 중복을 피하고 가장 효과적이라고 판단되는 최종 검색어들을 최대 3-4개 선정하여 각 줄에 하나씩 나열해주세요.
5.  학생의 나이/학년과 독서 수준을 고려하여 너무 전문적이거나 어려운 검색어는 피해주세요. {age_specific_instruction} {{/* << NEW: 초등학생 특별 지시 삽입 >> */}}
6.  답변은 각 검색어를 **새로운 줄에 하나씩** 나열해야 합니다. 다른 설명이나 부연은 일절 포함하지 마세요.

[학생 정보]
- 독서 수준 묘사: {level_desc}
- 학생 학년 수준: {age_grade_selection}
- 주요 탐구 주제: {topic}
- 선호 장르: {genres_str}
- 주제 관련 특별 관심사/파고들고 싶은 부분: {interests}
- 최근 재미있게 읽은 책 (취향 참고용): {liked_books_str}

[학생 수준 참고사항]
{difficulty_hint}

생성된 최종 검색어 목록 (각 줄에 하나씩, 최대 3-4개):"""
    return prompt

def create_prompt_for_no_results_advice(student_data, original_search_queries):
    level_desc = student_data["reading_level"]
    topic = student_data["topic"]
    age_grade_selection = student_data["student_age_group"]
    difficulty_hint = student_data["difficulty_hint"]
    interests = student_data["interests"]
    queries_str = ", ".join(original_search_queries) if original_search_queries else "없음"

    prompt = f"""
당신은 매우 친절하고 도움이 되는 도서관 요정 '도도'입니다.
학생이 아래 [학생 정보]로 책을 찾아보려고 했고, 이전에 [{queries_str}] 등의 검색어로 시도했지만, 안타깝게도 카카오 도서 API에서 관련 책을 찾지 못했습니다.

이 학생이 실망하지 않고 탐구를 계속할 수 있도록 실질적인 도움과 따뜻한 격려를 해주세요.
답변에는 다음 내용을 반드시 포함해주세요:
1.  결과를 찾지 못해 안타깝다는 공감의 메시지. (예: "이런, 이번에는 마법 거울이 책을 못 찾아왔네! 힝...")
2.  학생의 [학생 정보]를 바탕으로 시도해볼 만한 **새로운 검색 키워드 2~3개**를 구체적으로 제안. (이전에 시도한 검색어와는 다른 관점이나 단어 활용)
3.  책을 찾기 위한 **추가적인 서칭 방법이나 유용한 팁** 1-2가지.
4.  학생이 탐구를 포기하지 않도록 격려하는 따뜻한 마무리 메시지. (예: "포기하지 않으면 분명 좋은 책을 만날 수 있을 거야! 요정의 가루를 뿌려줄게! ✨")

**주의: 이 단계에서는 절대로 구체적인 책 제목을 지어내서 추천하지 마세요.** 오직 조언과 다음 단계 제안에만 집중해주세요.
답변은 마크다운 형식을 활용하여 가독성 좋게 작성해주세요.

[학생 정보]
- 독서 수준 묘사: {level_desc}
- 학생 학년 수준: {age_grade_selection}
- 주요 탐구 주제: {topic}
- 주제 관련 특별 관심사/파고들고 싶은 부분: {interests}

[학생 수준 참고사항]
{difficulty_hint}

[이전에 시도했던 대표 검색어들 (참고용)]
{queries_str}

학생을 위한 다음 단계 조언 (새로운 검색 키워드 및 서칭 팁 포함):"""
    return prompt

# (코드 조각 1에 이어서 chatbot_app.py 파일에 작성)

def search_kakao_books(query, api_key, size=10, target="title"):
    if not api_key: return None, "카카오 API 키가 설정되지 않았습니다."
    url = "https://dapi.kakao.com/v3/search/book"
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = { "query": query, "sort": "accuracy", "size": size, "target": target }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and "documents" in data:
            for doc in data["documents"]:
                isbn_raw = doc.get('isbn', '')
                if isbn_raw:
                    isbns = isbn_raw.split()
                    isbn13 = next((s.replace('-', '') for s in isbns if len(s.replace('-', '')) == 13), None)
                    isbn10 = next((s.replace('-', '') for s in isbns if len(s.replace('-', '')) == 10), None)
                    chosen_isbn = isbn13 if isbn13 else (isbn10 if isbn10 else (isbns[0].replace('-', '') if isbns else ''))
                    doc['cleaned_isbn'] = "".join(filter(lambda x: x.isdigit() or x.upper() == 'X', chosen_isbn))
                else: doc['cleaned_isbn'] = ''
        return data, None
    except requests.exceptions.Timeout:
        print(f"Kakao API 요청 시간 초과: {query}"); return None, f"카카오 API '{query}' 검색 시간 초과 🐢"
    except requests.exceptions.RequestException as e:
        print(f"Kakao API 요청 오류: {e}"); return None, f"카카오 '{query}' 검색 오류: {e}"

def create_prompt_for_final_selection(student_data, kakao_book_candidates_docs):
    level_desc = student_data["reading_level"]
    topic = student_data["topic"]
    age_grade_selection = student_data["student_age_group"]
    difficulty_hint = student_data["difficulty_hint"]
    interests = student_data["interests"]
    candidate_books_info = []
    if kakao_book_candidates_docs and isinstance(kakao_book_candidates_docs, list):
        for i, book in enumerate(kakao_book_candidates_docs):
            if i >= 7: break 
            if not isinstance(book, dict): continue
            try:
                publish_date_str = book.get("datetime", "")
                publish_year = datetime.fromisoformat(publish_date_str.split('T')[0]).strftime("%Y년") if publish_date_str and isinstance(publish_date_str, str) and publish_date_str.split('T')[0] else "정보 없음"
            except ValueError: publish_year = "정보 없음 (날짜형식오류)"
            display_isbn = book.get('cleaned_isbn', '정보 없음')
            publisher_name = book.get('publisher', '정보 없음')

            candidate_books_info.append(
                f"  후보 {i+1}:\n"
                f"    제목: {book.get('title', '정보 없음')}\n"
                f"    저자: {', '.join(book.get('authors', ['정보 없음']))}\n"
                f"    출판사: {publisher_name}\n"
                f"    출판년도: {publish_year}\n"
                f"    ISBN: {display_isbn}\n"
                f"    소개(요약): {book.get('contents', '정보 없음')[:250]}..."
            )
    candidate_books_str = "\n\n".join(candidate_books_info) if candidate_books_info else "검색된 책 후보 없음."


    # --- NEW: 초등학생일 경우 특별 강조 지시 추가 ---
    age_specific_selection_instruction = ""
    if "초등학생" in age_grade_selection:
        age_specific_selection_instruction = "특히, 이 학생은 초등학생이므로, 제공된 후보 목록 중에서도 **반드시 초등학생의 눈높이에 맞는 단어, 문장, 그림(만약 유추 가능하다면), 주제 접근 방식을 가진 책**을 골라야 합니다. 청소년이나 성인 대상의 책은 내용이 아무리 좋아도 제외해주세요. 책의 '소개(요약)', '출판사', '제목' 등을 통해 초등학생 적합성을 최우선으로 판단해야 합니다. 만약 후보 중에 초등학생에게 진정으로 적합한 책이 없다면, JSON 결과로 빈 배열 `[]`을 반환하고, 그 외 텍스트 영역에 그 이유를 설명해주세요."


    prompt = f"""
당신은 제공된 여러 실제 책 후보 중에서 학생의 원래 요구사항에 가장 잘 맞는 책을 최대 3권까지 최종 선택하고, 각 책에 대한 맞춤형 추천 이유를 작성하는 친절하고 현명한 도서관 요정 '도도'입니다.

[학생 정보 원본]
- 독서 수준 묘사: {level_desc}
- 학생 학년 수준: {age_grade_selection}
- 주요 탐구 주제: {topic}
- 주제 관련 특별 관심사/파고들고 싶은 부분: {interests}

[학생 수준 참고사항]
{difficulty_hint}

[카카오 API에서 검색된 책 후보 목록 (자체 스코어링 및 우선순위 정렬이 일부 반영된 상위 목록)]
{candidate_books_str}

[요청 사항]
1.  위 [카카오 API에서 검색된 책 후보 목록]에서 학생에게 가장 적합하다고 판단되는 책을 최대 3권까지 선택해주세요.
2.  선택 시 다음 사항을 **종합적으로 고려**하여, 학생의 탐구 활동에 실질적으로 도움이 될 **'인기 있거나 검증된 좋은 책'**을 우선적으로 선정해주세요:
    * **학생의 요구사항 부합도 (가장 중요!):** 주제, 관심사, 그리고 특히 **'학생 학년 수준'과 '학생 수준 참고사항'에 명시된 난이도**에 얼마나 잘 맞는가?
    * {age_specific_selection_instruction} {{/* << NEW: 초등학생 특별 강조 지시 삽입 >> */}}
    * **책의 신뢰도 및 대중성(추정):** (이전과 동일)
    * **정보의 깊이와 폭:** (이전과 동일)
3.  선택된 각 책의 정보는 아래 명시된 필드를 포함하는 **JSON 객체**로 만들어주세요. (이하 JSON 관련 지시는 이전과 동일)
{
    # ... (이전 프롬프트의 JSON 객체 필드 설명, BOOKS_JSON_START/END, 빈 배열 반환 조건 등은 그대로 유지) ...
    # (이전 코드 조각 2/7의 JSON 관련 요청 사항 부분을 여기에 그대로 넣어주세요!)
    # 제가 다시 적으면 너무 길어져서 생략했어요! 아가씨 코드에는 이 부분이 이미 잘 들어가 있을 거예요!
}
JSON 객체 필드 설명:
- "title" (String): 정확한 책 제목
- "author" (String): 실제 저자명
- "publisher" (String): 실제 출판사명
- "year" (String): 출판년도 (YYYY년 형식)
- "isbn" (String): 실제 ISBN (숫자와 X만 포함된 순수 문자열, 하이픈 없이)
- "reason" (String): 학생 맞춤형 추천 이유 (1-2 문장)

JSON 배열 형식 예시:
BOOKS_JSON_START
[
  {{
    "title": "(실제 후보 목록에서 선택한 책 제목)",
    "author": "(실제 후보 목록에서 가져온 저자명)",
    "publisher": "(실제 후보 목록에서 가져온 출판사명)",
    "year": "(실제 후보 목록에서 가져온 출판년도)",
    "isbn": "(실제 후보 목록에서 가져온 ISBN)",
    "reason": "(학생 정보와 위 선택 기준을 바탕으로 생성한 추천 이유)"
  }}
]
BOOKS_JSON_END

만약 [카카오 API에서 검색된 책 후보 목록]이 "검색된 책 후보 없음"이거나, 후보 중에서 위 기준에 따라 적절한 책을 고르기 어렵다면, BOOKS_JSON_START와 BOOKS_JSON_END 마커 사이에 빈 배열 `[]`을 넣어주고, 그 외의 텍스트 영역에 학생의 [학생 정보 원본]과 [학생 수준 참고사항]만을 참고하여 일반적인 조언이나 탐색 방향을 제시해주세요. 단, 이 경우에도 구체적인 (가상의) 책 제목을 JSON 안에 지어내지는 마세요.

자, 이제 최종 추천을 부탁해요! ✨
"""
    return prompt

def get_ai_recommendation(model_to_use, prompt_text, generation_config=None):
    if not model_to_use:
        return "🚫 AI 모델이 준비되지 않았어요. API 키 설정을 확인해주세요!"
    try:
        final_generation_config = generation_config if generation_config else genai.GenerationConfig(temperature=0.3)
        response = model_to_use.generate_content(
            prompt_text,
            generation_config=final_generation_config
        )
        return response.text
    except genai.types.generation_types.BlockedPromptException as e: # 구체적인 오류 타입 명시
        print(f"Gemini API BlockedPromptException: {e}")
        return "🚨 이런! 도도 요정이 이 요청에 대한 답변을 생성하는 데 어려움을 느끼고 있어요. 입력 내용을 조금 바꿔서 다시 시도해볼까요? (콘텐츠 안전 문제일 수 있어요!)"
    except Exception as e:
        error_message_detail = str(e).lower()
        # --- NEW: Rate Limit 오류 메시지 개선 시도 ---
        if "rate limit" in error_message_detail or "quota" in error_message_detail or "resource_exhausted" in error_message_detail or "resource has been exhausted" in error_message_detail:
            error_message = "🚀 지금 도도를 찾는 친구들이 너무 많아서 조금 바빠요! 잠시 후에 다시 시도해주면 요정의 가루를 뿌려줄게요! ✨ (요청 한도 초과)"
        else:
            error_message = f"🧚 AI 요정님 호출 중 예상치 못한 오류 발생!: {str(e)[:200]}...\n잠시 후 다시 시도해주세요."
        print(f"Gemini API Error: {e}")
        return error_message

# --- 3. Streamlit 앱 UI 구성 ---
st.set_page_config(page_title="도서관 요정 도도의 도서 추천! 🕊️", page_icon="🧚", layout="centered")

# --- NEW: 서비스 소개 문구 (가운데 정렬) ---
st.markdown(
    """
    <div style='
        background-color: #f0f0f0; 
        padding: 13px 8px 11px 8px; 
        border-radius: 7px; 
        margin-bottom: 5px;
        font-size: 1.03em;
        color: #343434;
        font-weight: 500;
        text-align: center;
    '>
        이 서비스는 AI를 활용한 도서 추천으로,<br>
        사용량이 많거나 복잡한 요청 시 응답이 지연될 수 있습니다.<br>
        너른 양해 부탁드려요! 😊
    </div>
    """,
    unsafe_allow_html=True
)
st.markdown("---")

st.markdown("""
<style>
    .main-title-container {
        background-color: #E0F7FA; padding: 30px; border-radius: 15px;
        text-align: center; box-shadow: 0 6px 12px rgba(0,0,0,0.1); margin-bottom: 40px;
    }
    .main-title-container h1 { color: #00796B; font-weight: bold; font-size: 2.5em; margin-bottom: 15px; }
    .main-title-container p { color: #004D40; font-size: 1.15em; line-height: 1.7; }
    .centered-subheader { text-align: center; margin-top: 20px; margin-bottom: 10px; color: #00796B; font-weight:bold; }
    .centered-caption { text-align: center; display: block; margin-bottom: 20px; margin-top: -5px}
    .recommendation-card-title { text-align: center; color: #004D40; margin-top: 0; margin-bottom: 8px; font-size: 1.4em; font-weight: bold;}
    .book-meta { font-size: 0.9em; color: #37474F; margin-bottom: 10px; }
    .reason { font-style: normal; color: #263238; background-color: #E8F5E9; padding: 12px; border-radius: 5px; margin-bottom:10px; border-left: 4px solid #4CAF50;}
    .library-status-success { color: #2E7D32; font-weight: bold; background-color: #C8E6C9; padding: 8px; border-radius: 5px; display: block; margin-top: 8px; text-align: left;}
    .library-status-info { color: #0277BD; font-weight: bold; background-color: #B3E5FC; padding: 8px; border-radius: 5px; display: block; margin-top: 8px; text-align: left;}
    .library-status-warning { color: #C62828; background-color: #FFCDD2; padding: 8px; border-radius: 5px; margin-top: 8px; display:block; text-align: left;}
    .highlighted-advice-block { background-color: #FFFDE7; border-left: 5px solid #FFC107; padding: 20px; border-radius: 8px; margin-top: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .highlighted-advice-block h5 { color: #FFA000; margin-top: 0; margin-bottom: 10px; }
</style>
<div class="main-title-container">
    <h1>📚 도도의 똑똑한 도서 추천! 🕊️</h1>
    <p>안녕하세요! 여러분의 탐구 보고서 작성을 도와줄 도서관 요정, <strong>도도</strong>입니다!<br>
    아래 정보를 입력해주시면 맞춤형 책을 찾아드릴게요! 얍얍!</p>
</div>
""", unsafe_allow_html=True)

if gemini_api_error: st.error(gemini_api_error); st.stop()
if kakao_api_error: st.error(kakao_api_error); st.stop()

# --- 사이드바 구성 ---
st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    <div style="text-align:center; font-weight:bold; font-size:1.15em; margin-bottom:0.3em;">
        도도의 비밀 노트 🤫
    </div>
    """,
    unsafe_allow_html=True
)
st.sidebar.markdown(
    f"""
    <div style="text-align:center; color:#00796B; font-size:1.05em; margin-bottom:0.7em;">
        오늘 날짜: {st.session_state.get('TODAYS_DATE', '날짜 정보 없음')}
    </div>
    """,
    unsafe_allow_html=True
)
st.sidebar.markdown(
    """
    <ul style="font-size:0.98em; color:#333; margin-bottom:1em; margin-left:-1em;">
        <li>도도는 <b>Google Gemini API</b>와 <b>Kakao Book API</b>를 사용해요.</li>
        <li>AI가 가끔 너무 신나서 엉뚱한 추천을 할 수도 있으니 너그러이 봐주세요!</li>
        <li>AI가 알려준 정보를 그대로 수용하지 말고, 추가 검증을 꼭 거치세요!</li>
        <li>버그나 개선점은 '개발자'에게 살짝 알려주세요!</li>
    </ul>
    """,
    unsafe_allow_html=True
)
st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    <div style="text-align:center;">
        <span style="font-weight:bold;">⚙️ 현재 사용 엔진 정보</span>
    </div>
    """,
    unsafe_allow_html=True
)
st.sidebar.markdown(
    f"""
    <div style="text-align:center; margin-bottom:10px;">
        <b>AI 모델:</b> <code>{gemini_model_name}</code>
    </div>
    """,
    unsafe_allow_html=True
)

# --- NEW: 모델별 RPM/RPD 정보 표시 ---
if gemini_model_name == 'gemini-1.5-flash-latest':
    RPM_INFO = "분당 요청 수(RPM): 약 15회 (무료 등급)"
    RPD_INFO = "일일 요청 수(RPD): 약 500회 (무료 등급)"
    CONCURRENT_USERS_ESTIMATE = "동시 사용 예상: 약 7명 내외 (학생당 2회 AI 호출 가정)"
elif gemini_model_name == 'gemini-1.5-pro-latest': # Pro 모델의 경우, 알려진 무료 한도가 있다면 여기에 명시
    RPM_INFO = "분당 요청 수(RPM): 확인 필요 (일반적으로 Flash보다 높거나 유사할 수 있음)"
    RPD_INFO = "일일 요청 수(RPD): 확인 필요"
    CONCURRENT_USERS_ESTIMATE = "동시 사용 예상: 실제 테스트 필요"
elif 'flash-lite' in gemini_model_name.lower(): # 예시: 'gemini-2.0-flash-lite'
    RPM_INFO = "분당 요청 수(RPM): 약 30회 (무료 등급)"
    RPD_INFO = "일일 요청 수(RPD): 약 1,500회 (무료 등급)"
    CONCURRENT_USERS_ESTIMATE = "동시 사용 예상: 약 15명 내외 (학생당 2회 AI 호출 가정)"
else: # 기타 모델 또는 정보 없을 시
    RPM_INFO = "분당 요청 수(RPM): 모델별 확인 필요"
    RPD_INFO = "일일 요청 수(RPD): 모델별 확인 필요"
    CONCURRENT_USERS_ESTIMATE = "동시 사용 예상: 확인 필요"

st.sidebar.markdown(
    f"""
    <div style="font-size:0.85em; text-align:center; margin-bottom:12px; line-height:1.8;">
        📌 분당 요청 수(RPM) <b>{RPM_INFO.split(':')[-1].strip()}</b><br>
        📌 일일 요청 수(RPD) <b>{RPD_INFO.split(':')[-1].strip()}</b><br>
        📌 동시 사용 <b>{CONCURRENT_USERS_ESTIMATE.split(':')[-1].strip()}</b>
    </div>
    """,
    unsafe_allow_html=True
)

st.sidebar.markdown(
    """
    <div style="font-size:0.80em; line-height:1.8; color:gray; text-align:center;">
        위 정보는 일반적인 무료 등급 기준이며,<br>
        실제 할당량은 다를 수 있습니다.
    </div>
    """,
    unsafe_allow_html=True
)
st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    <div style="text-align:center; margin-bottom:0.2em;">
        <span style="font-weight:bold;">👩‍💻 총괄 디렉터: 꾸물 🐌</span><br>
        <span style="font-weight:bold;">🕊️ AI 어시스턴트: 도도</span>
    </div>
    """,
    unsafe_allow_html=True
)
st.sidebar.markdown(
    """
    <div style="font-size:0.92em; color:#888; text-align:center; margin-top:4px; margin-bottom:12px;">
        문의: <a href="mailto:zambi23@gmail.com" style="color:#888; text-decoration:underline;">zambi23@gmail.com</a><br>
        블로그: <a href="https://blog.naver.com/snailslowclub" style="color:#888; text-decoration:underline;" target="_blank">꾸물책장</a>
    </div>
    """,
    unsafe_allow_html=True
)
st.sidebar.markdown("---")
st.sidebar.caption("⚠️ API 호출은 사용량에 따라 비용이 발생할 수 있으니 주의해주세요!")

st.markdown("---")
st.markdown("<h3 class='centered-subheader'>📚 최근 재미있게 읽은 책 (선택 사항)</h3>", unsafe_allow_html=True)
st.markdown("<p class='centered-caption'>AI 요정 도도가 여러분의 취향을 파악하는 데 큰 도움이 돼요! 한 권씩 추가해주세요!</p>", unsafe_allow_html=True)

col_add_book_input, col_add_book_button_placeholder = st.columns([0.75, 0.25])
with col_add_book_input:
    st.session_state.current_book_to_add = st.text_input(
        "책 제목과 저자를 입력해주세요:", value=st.session_state.current_book_to_add,
        placeholder="예: 멋진 신세계 (올더스 헉슬리)", key="new_book_text_input_widget_key_outside_form", label_visibility="collapsed"
    )
with col_add_book_button_placeholder:
    if st.button("➕ 이 책 추가", key="add_book_button_key_outside_form", use_container_width=True):
        book_val = st.session_state.new_book_text_input_widget_key_outside_form
        if book_val:
            if book_val not in st.session_state.liked_books_list: st.session_state.liked_books_list.append(book_val)
            st.session_state.current_book_to_add = ""
            st.rerun()
        else: st.warning("책 제목을 입력해주세요!", icon="🕊️")

if st.session_state.liked_books_list:
    st.write("📖 추가된 책 목록:")
    for i, book_title in enumerate(list(st.session_state.liked_books_list)):
        with st.container(border=True):
            item_col1, item_col2 = st.columns([0.9, 0.1])
            with item_col1: st.markdown(f"  - {book_title}")
            with item_col2:
                if st.button("➖", key=f"remove_book_outside_form_{i}", help="이 책을 목록에서 삭제해요.", use_container_width=True):
                    st.session_state.liked_books_list.pop(i)
                    st.rerun()
    st.write("")
else:
    # --- UI 개선: "(아직 추가된 책이 없어요.)" 가운데 정렬 ---
    st.markdown("<p class='centered-caption' style='font-style: italic;'>(아직 추가된 책이 없어요.)</p>", unsafe_allow_html=True)
st.markdown("---")

# (코드 조각 4에 이어서 chatbot_app.py 파일에 작성)

# --- 메인 입력 폼 ---
st.markdown("<h3 class='centered-subheader'>🧭 탐험가의 나침반을 채워주세요!</h3>", unsafe_allow_html=True)
with st.form("recommendation_form"):
    level_opts = ["새싹 탐험가 🌱 (그림 많고 글자 적은 게 좋아요!)", "초보 탐험가 🚶‍♀️ (술술 읽히고 너무 두껍지 않은 책!)", "중급 탐험가 🏃‍♂️ (어느 정도 깊이 있는 내용도 OK!)", "고수 탐험가 🧗‍♀️ (전문 용어나 복잡한 내용도 도전 가능!)"]
    reading_level = st.selectbox("📖 독서 수준:", options=level_opts, help="독서 경험에 가장 잘 맞는 설명을 골라주세요!")
    
    # --- NEW: 학생 연령대 선택으로 변경 ---
    age_group_options = ["선택안함", "초등학생 (8-13세)", "중학생 (14-16세)", "고등학생 (17-19세)"]
    student_age_group_selection = st.selectbox("🧑‍🎓 학생의 학년 그룹을 선택해주세요:", options=age_group_options, index=0, help="학생의 학년 수준을 알려주시면 난이도 조절에 큰 도움이 돼요!")

    topic = st.text_input("🔬 주요 탐구 주제:", placeholder="예: 인공지능과 직업의 미래", help="가장 핵심적인 탐구 주제를 알려주세요.")
    
    genre_opts = ["소설", "SF", "판타지", "역사", "과학", "수학/공학", "예술/문화", "사회/정치/경제", "인물 이야기", "에세이/철학", "기타"] # "소설" 추가됨
    genres = st.multiselect("🎨 선호 장르 (다중 선택 가능):", options=genre_opts, help="좋아하는 이야기 스타일을 골라주시면 취향 저격에 도움이 돼요!")
    
    interests = st.text_input("💡 주제 관련 특별 관심사:", placeholder="예: AI 윤리 중 알고리즘 편향성", help="주제 안에서도 궁금한 세부 내용을 적어주세요.")
    disliked_conditions = st.text_input("🚫 피하고 싶은 조건:", placeholder="예: 너무 슬픈 결말, 지나치게 전문적인 내용", help="이런 책은 추천에서 빼드릴게요!")
    
    form_cols = st.columns([1, 1.5, 1])
    with form_cols[1]:
        submitted = st.form_submit_button("🕊️ 도도에게 책 추천받기! ✨", use_container_width=True)

# --- 4. 추천 로직 실행 및 결과 표시 ---
if submitted:
    # --- NEW: 난이도 힌트 설정 ---
    difficulty_hints_map = {
        "초등학생 (8-13세)": "이 학생은 초등학생입니다. 매우 이해하기 쉬운 단어와 문장을 사용하고, 친절하고 상세한 설명을 제공해주세요. 추천하는 책이나 검색어도 초등학생 눈높이에 맞춰주세요.",
        "중학생 (14-16세)": "이 학생은 중학생입니다. 적절한 수준의 어휘를 사용하고, 너무 단순하거나 유치하지 않으면서도 명확한 설명을 제공해주세요. 추천하는 책이나 검색어도 중학생 수준에 적합해야 합니다.",
        "고등학생 (17-19세)": "이 학생은 고등학생입니다. 정확한 개념과 논리적인 설명을 중심으로 답변해주세요. 탐구 보고서 작성에 도움이 될 만한 심도 있는 내용이나 다양한 관점을 제시해도 좋습니다.",
        "선택안함": "학생의 연령대가 특정되지 않았습니다. 일반적인 청소년 수준을 고려하되, 너무 어렵거나 전문적인 내용은 피해주세요."
    }
    selected_difficulty_hint = difficulty_hints_map.get(student_age_group_selection, difficulty_hints_map["선택안함"])

    if not topic.strip(): st.warning("❗ 주요 탐구 주제를 입력해주셔야 추천이 가능해요!", icon="📝")
    # elif not age_or_grade.strip(): st.warning("❗ 나이 또는 학년을 입력해주시면 더 정확한 추천이 가능해요!", icon="🎂") # age_or_grade 대신 student_age_group_selection 사용
    elif student_age_group_selection == "선택안함": # 선택안함을 골랐을 때 경고 대신, 기본 힌트가 적용됨. 필요시 경고 추가 가능.
        st.info("학년 그룹을 선택하시면 도도가 더욱 정확한 난이도의 책을 추천해드릴 수 있어요! 😊")
        # 이 경우에도 추천은 계속 진행합니다. difficulty_hint에 "선택안함"에 대한 내용이 들어갑니다.

    # 모든 필수 조건이 충족되었을 때 로직 진행 (topic은 필수)
    if topic.strip() : # and student_age_group_selection != "선택안함" # 학년 선택을 필수로 하려면 이 조건 추가
        st.markdown("---")
        st.markdown("<h2 class='centered-subheader'>🎁 도도의 정밀 탐색 결과!</h2>", unsafe_allow_html=True)
            
        with st.spinner("도도 요정이 마법 안경을 쓰고 책을 찾고 있어요... 잠시만 기다려주세요... 🧚✨"):
            student_data = {
                "reading_level": reading_level, "topic": topic, 
                "student_age_group": student_age_group_selection, # << NEW
                "difficulty_hint": selected_difficulty_hint, # << NEW
                "age_grade": student_age_group_selection, # 기존 변수명도 일단 유지 (프롬프트에서 age_grade_selection으로 대체)
                "genres": genres if genres else [], "interests": interests if interests else "특별히 없음",
                "liked_books": st.session_state.liked_books_list,
                "disliked_conditions": disliked_conditions if disliked_conditions else "특별히 없음"
            }

            # --- 1단계: Gemini에게 "다중 검색어" 생성 요청 ---
            search_queries_prompt = create_prompt_for_search_query(student_data)
            search_query_gen_config = genai.GenerationConfig(temperature=0.1)
            search_queries_response = get_ai_recommendation(gemini_model, search_queries_prompt, generation_config=search_query_gen_config)
            generated_search_queries = [q.strip().replace("*","").replace("#","") for q in search_queries_response.split('\n') if q.strip()]

            if "AI 요정님 호출 중 오류" in search_queries_response or "AI 모델이 준비되지 않았어요" in search_queries_response or not generated_search_queries:
                st.error(f"도도 요정이 검색어 생성에 실패했어요: {search_queries_response}")
                st.stop()
            
            st.info(f"도도 요정이 추천한 검색어 목록: **{', '.join(generated_search_queries)}**")

            # --- 2단계: 생성된 "다중 검색어"로 카카오 도서 API 호출 및 결과 통합/중복 제거 ---
            all_kakao_books_raw = []
            unique_isbns_fetched = set()
            search_progress_text = "카카오 도서 검색 진행 중... ({current}/{total})"
            progress_bar_placeholder = st.empty() 
            search_errors = []

            for i, query in enumerate(generated_search_queries):
                if not query: continue
                progress_bar_placeholder.progress( (i + 1) / len(generated_search_queries), text=search_progress_text.format(current=i+1, total=len(generated_search_queries)))
                kakao_page_results, kakao_error_msg = search_kakao_books(query, KAKAO_API_KEY, size=10)
                
                if kakao_error_msg:
                    search_errors.append(f"'{query}' 검색 시: {kakao_error_msg}")
                    continue
                if kakao_page_results and kakao_page_results.get("documents"):
                    for book_doc in kakao_page_results["documents"]:
                        publisher_check = book_doc.get('publisher', '').lower()
                        is_excluded = any(excluded_keyword in publisher_check for excluded_keyword in EXCLUDED_PUBLISHER_KEYWORDS)
                        if is_excluded: continue

                        cleaned_isbn = book_doc.get('cleaned_isbn', '')
                        if cleaned_isbn and cleaned_isbn not in unique_isbns_fetched:
                            all_kakao_books_raw.append(book_doc)
                            unique_isbns_fetched.add(cleaned_isbn)
            progress_bar_placeholder.empty()
            if search_errors:
                st.warning("일부 검색어에 대한 카카오 검색 중 다음 오류가 발생했어요:\n\n" + "\n\n".join(search_errors))

            if not all_kakao_books_raw:
                st.markdown("<div class='highlighted-advice-block'>", unsafe_allow_html=True)
                st.markdown("##### 😥 이런! 카카오에서 책을 찾지 못했어요...")
                prompt_for_advice = create_prompt_for_no_results_advice(student_data, generated_search_queries)
                advice_text = get_ai_recommendation(gemini_model, prompt_for_advice, generation_config=genai.GenerationConfig(temperature=0.5))
                st.markdown(advice_text)
                st.markdown("</div>", unsafe_allow_html=True)
                st.stop()

            st.success(f"카카오에서 총 {len(all_kakao_books_raw)}권의 고유한 책 후보를 찾았어요! 이제 우선순위를 정해볼게요!")

            # --- 3단계: 우선순위 결정을 위한 정보 취합 ---
            enriched_book_candidates = []
            CHILDREN_PUBLISHERS_NORMALIZED = {normalize_publisher_name(p) for p in [
                "비룡소", "국민서관", "웅진씽크빅", "계림북스", "계몽사", "시공주니어", 
                "사계절출판사", "보림출판", "한림출판사", "길벗어린이", "풀빛미디어", "다섯수레"
            ]}

            for book_doc in all_kakao_books_raw:
                isbn_to_check = book_doc.get('cleaned_isbn')
                library_info = {"found_in_library": False}
                if isbn_to_check: library_info = find_book_in_library_by_isbn(isbn_to_check)
                
                publisher = book_doc.get('publisher', '').strip()
                normalized_kakao_publisher = normalize_publisher_name(publisher)
                is_major_publisher = normalized_kakao_publisher in MAJOR_PUBLISHERS_NORMALIZED

                # --- 자체 스코어링 ---
                score = 0
                # 1. 출판년도
                try:
                    publish_year_str = book_doc.get("datetime", "").split('T')[0][:4]
                    if publish_year_str.isdigit():
                        publish_year = int(publish_year_str)
                        current_year = datetime.now().year
                        if publish_year >= current_year - 1: score += 30
                        elif publish_year >= current_year - 3: score += 20
                        elif publish_year >= current_year - 5: score += 10
                except: pass
                # 2. 책 소개 길이
                contents_len = len(book_doc.get('contents', ''))
                if contents_len > 200: score += 20
                elif contents_len > 100: score += 10
                
                # --- NEW: 학생 학년 수준에 따른 스코어링 추가 ---
                if "초등학생" in student_data["student_age_group"]:
                    if normalized_kakao_publisher in CHILDREN_PUBLISHERS_NORMALIZED:
                        score += 50 # 어린이 전문 출판사면 큰 가산점!
                    if "어린이" in book_doc.get('title', '') or "초등" in book_doc.get('title', ''):
                        score += 40 # 제목에 어린이/초등 키워드
                    if "어린이" in book_doc.get('contents', '') or "초등학생" in book_doc.get('contents', ''):
                        score += 30 # 소개에 어린이/초등학생 키워드
                
                enriched_book_candidates.append({
                    "kakao_doc": book_doc, "library_info": library_info,
                    "is_major_publisher": is_major_publisher,
                    "in_library": library_info.get("found_in_library", False),
                    "custom_score": score 
                })

            # --- 4단계: 우선순위 정렬 ---
            def sort_priority(book_entry): return (not book_entry["in_library"], not book_entry["is_major_publisher"], -book_entry.get('custom_score', 0))
            sorted_candidates_enriched = sorted(enriched_book_candidates, key=sort_priority)
            candidates_for_gemini_selection_docs = [entry["kakao_doc"] for entry in sorted_candidates_enriched[:7]]

            if not candidates_for_gemini_selection_docs:
                st.markdown("<div class='highlighted-advice-block'>", unsafe_allow_html=True)
                st.markdown("##### 😥 이런! 조건을 만족하는 책 후보가 없네요...")
                prompt_for_advice = create_prompt_for_no_results_advice(student_data, generated_search_queries)
                advice_text = get_ai_recommendation(gemini_model, prompt_for_advice, generation_config=genai.GenerationConfig(temperature=0.5))
                st.markdown(advice_text)
                st.markdown("</div>", unsafe_allow_html=True)
                st.stop()

            # --- 5단계: 정렬된 후보를 바탕으로 Gemini에게 최종 선택 및 이유 생성 요청 ---
            final_selection_prompt = create_prompt_for_final_selection(student_data, candidates_for_gemini_selection_docs)
            final_selection_gen_config = genai.GenerationConfig(temperature=0.4)
            final_recs_text = get_ai_recommendation(gemini_model, final_selection_prompt, generation_config=final_selection_gen_config)

            # --- 6단계: 최종 결과 파싱 및 표시 ---
            books_data_from_ai = []; intro_text_from_ai = ""
            try:
                json_start_marker = "BOOKS_JSON_START"; json_end_marker = "BOOKS_JSON_END"
                start_idx = final_recs_text.find(json_start_marker); end_idx = final_recs_text.find(json_end_marker)
                if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                    intro_text_from_ai = final_recs_text[:start_idx].strip()
                    if intro_text_from_ai: st.markdown(intro_text_from_ai)
                    
                    json_string_raw = final_recs_text[start_idx + len(json_start_marker) : end_idx].strip()
                    if json_string_raw.startswith("```json"): json_string_raw = json_string_raw[len("```json"):].strip()
                    if json_string_raw.endswith("```"): json_string_raw = json_string_raw[:-len("```")].strip()
                    
                    if json_string_raw and json_string_raw != "[]":
                        books_data_from_ai = json.loads(json_string_raw)
                        if not isinstance(books_data_from_ai, list):
                            st.warning("AI가 JSON 배열 형태로 주지 않았어요. 😥"); books_data_from_ai = []
                    
                    if not books_data_from_ai : # JSON이 비었거나(AI가 [] 반환) 파싱에 문제가 생겼을 때
                        # intro_text_from_ai는 위에서 이미 표시되었을 수 있음
                        # AI가 빈 배열을 반환하고 부연 설명을 했을 수 있으므로, outro_text도 확인
                        outro_text_from_ai_check = final_recs_text[end_idx + len(json_end_marker):].strip() if end_idx != -1 else ""
                        if not intro_text_from_ai and not outro_text_from_ai_check: # AI가 정말 아무 말도 안하고 []만 보냈다면
                             st.info("도도 요정이 카카오 후보 중에서 최종 추천할 만한 책을 고르지 못했나 봐요...")
                        
                        # "결과 없음 조언" 표시 (JSON이 비었을 때 항상 표시)
                        st.markdown("<div class='highlighted-advice-block'>", unsafe_allow_html=True)
                        prompt_for_advice = create_prompt_for_no_results_advice(student_data, generated_search_queries)
                        advice_text = get_ai_recommendation(gemini_model, prompt_for_advice, generation_config=genai.GenerationConfig(temperature=0.5))
                        st.markdown(advice_text)
                        st.markdown("</div>", unsafe_allow_html=True)

                    outro_text_from_ai = final_recs_text[end_idx + len(json_end_marker):].strip() if end_idx != -1 else ""
                    if outro_text_from_ai: st.markdown("---"); st.markdown(outro_text_from_ai)
                
                else: # 마커를 못 찾았을 경우
                    with st.container(border=True): st.markdown(final_recs_text)
                    st.warning("앗, AI 답변에서 약속된 책 정보(JSON) 부분을 찾지 못했어요.", icon="⚠️")
            
            except json.JSONDecodeError:
                st.error("AI 생성 책 정보(JSON) 파싱 실패! 😭", icon="🔥"); st.code(final_recs_text, language="text")
            except Exception as e: st.error(f"책 정보 처리 중 오류: {e}", icon="💥"); st.code(final_recs_text, language="text")

            if books_data_from_ai: # 성공적으로 파싱된 책 데이터가 있을 경우에만
                if intro_text_from_ai and books_data_from_ai : st.markdown("---")
                for book_data in books_data_from_ai:
                    with st.container(border=True):
                        title = book_data.get("title", "제목 없음"); author = book_data.get("author", "저자 없음")
                        publisher = book_data.get("publisher", "출판사 정보 없음")
                        year = book_data.get("year", "출판년도 없음"); isbn = book_data.get("isbn")
                        reason = book_data.get("reason", "추천 이유 없음")

                        st.markdown(f"<h4 class='recommendation-card-title'>{title}</h4>", unsafe_allow_html=True)
                        st.markdown(f"<span class='book-meta'>**저자:** {author} | **출판사:** {publisher} | **출판년도:** {year}</span>", unsafe_allow_html=True)
                        if isbn: st.markdown(f"<span class='book-meta'>**ISBN:** `{isbn}`</span>", unsafe_allow_html=True)
                        st.markdown(f"<div class='reason'>{reason}</div>", unsafe_allow_html=True)

                        if isbn:
                            clean_isbn = "".join(filter(lambda x: x.isdigit() or x.upper() == 'X', isbn))
                            if len(clean_isbn) in [10, 13]:
                                lib_info = find_book_in_library_by_isbn(clean_isbn)
                                if lib_info.get("found_in_library"):
                                    status_html = f"<div class='library-status-success'>🏫 <strong>우리 학교 도서관 소장!</strong> ✨<br>&nbsp;&nbsp;&nbsp;- 청구기호: {lib_info.get('call_number', '정보 없음')}<br>&nbsp;&nbsp;&nbsp;- 상태: {lib_info.get('status', '소장중')}</div>"
                                    st.markdown(status_html, unsafe_allow_html=True)
                                else: st.markdown("<div class='library-status-info'>😿 아쉽지만 이 책은 학교 도서관 목록에 없어요.</div>", unsafe_allow_html=True)
                            else: st.markdown(f"<div class='library-status-warning'>⚠️ 제공된 ISBN '{isbn}'이 유효하지 않아 학교 도서관 검색 불가.</div>", unsafe_allow_html=True)
                        else: st.markdown("<div class='library-status-warning'>⚠️ ISBN 정보가 없어 학교 도서관 검색 불가.</div>", unsafe_allow_html=True)
            
            elif not ("AI 요정님 호출 중 오류" in final_recs_text or \
                      (intro_text_from_ai and ("카카오에서 책을 찾지 못했어요" in intro_text_from_ai or "추천할 만한 책을 찾지 못했나 봐요" in intro_text_from_ai)) ) and \
                      not intro_text_from_ai:
                with st.container(border=True):
                    st.markdown(final_recs_text)
                    st.caption("도도 요정님의 답변에서 개별 책 정보를 정확히 추출하지 못했어요.")
