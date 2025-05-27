# chatbot_app.py 개선 버전 (2024-05-26 최신, 클러스터링 및 필터링 강화)
import streamlit as st
import google.generativeai as genai
import os
from dotenv import load_dotenv
from datetime import datetime
import requests
import json
import re
# 추가 모듈
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

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

CHILDREN_PUBLISHERS_KEYWORDS_FOR_FILTER = [ # 정규화된 이름으로 관리
    "비룡소", "국민서관", "웅진씽크빅", "계림북스", "계몽사", "시공주니어",
    "사계절출판사", "보림출판", "한림출판사", "길벗어린이", "풀빛미디어", "다섯수레",
    "창비교육", "문학동네어린이", "현암주니어", "주니어김영사", "주니어rhk", "을파소",
    "걸음동무", "처음주니어"
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

CHILDREN_PUBLISHERS_NORMALIZED = {normalize_publisher_name(p) for p in CHILDREN_PUBLISHERS_KEYWORDS_FOR_FILTER}

MAJOR_PUBLISHERS_NORMALIZED = {normalize_publisher_name(p) for p in ORIGINAL_MAJOR_PUBLISHERS}
EXCLUDED_PUBLISHER_KEYWORDS = ["씨익북스", "ceic books"] # 소문자로 비교

# --- 1. 기본 설정 및 API 키 준비 ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY"); KAKAO_API_KEY = os.getenv("KAKAO_REST_API_KEY")
gemini_model_name = 'gemini-2.0-flash-lite' # 사용자의 기존 모델명 유지
gemini_model = None; gemini_api_error = None; kakao_api_error = None
if GEMINI_API_KEY:
    try: genai.configure(api_key=GEMINI_API_KEY); gemini_model = genai.GenerativeModel(gemini_model_name)
    except Exception as e: gemini_api_error = f"Gemini API ({gemini_model_name}) 설정 오류: {e}"
else: gemini_api_error = "Gemini API 키가 .env에 설정되지 않았어요! 🗝️"
if not KAKAO_API_KEY: kakao_api_error = "Kakao REST API 키가 .env에 설정되지 않았어요! 🔑"

# --- library_db.py 함수 가져오기 ---
try:
    from library_db import find_book_in_library_by_isbn, find_book_in_library_by_title_author # 새 함수 추가
except ImportError:
    if not st.session_state.get('library_db_import_warning_shown', False): # 중복 경고 방지
        st.warning("`library_db.py` 또는 `find_book_in_library_by_isbn` / `find_book_in_library_by_title_author` 함수 없음! (임시 기능 사용)", icon="😿")
        st.session_state.library_db_import_warning_shown = True
    def find_book_in_library_by_isbn(isbn_query): return {"found_in_library": False, "error": "도서관 DB 모듈 로드 실패"}
    def find_book_in_library_by_title_author(title_query, author_query): return {"found_in_library": False, "error": "도서관 DB 모듈 로드 실패 (제목/저자 검색용)"} # 임시 함수도 추가

# --- 세션 상태 초기화 ---
if 'TODAYS_DATE' not in st.session_state:
    st.session_state.TODAYS_DATE = datetime.now().strftime("%Y년 %m월 %d일")
    if not st.session_state.get('app_already_run_once', False):
         st.session_state.app_already_run_once = True
if 'liked_books_list' not in st.session_state: st.session_state.liked_books_list = []
if 'current_book_to_add' not in st.session_state: st.session_state.current_book_to_add = ""

# --- 2. AI 및 API 호출 관련 함수들 ---

def extract_search_queries_from_llm(llm_response, topic, genres):
    lines = [q.strip().replace("*", "").replace("#", "") for q in llm_response.split('\n') if q.strip()]
    filtered = []
    for q in lines:
        word_count = len(q.split())
        if 1 <= word_count <= 3 and re.match(r"^[가-힣a-zA-Z0-9 \-]+$", q):
            filtered.append(q)
    fallback = []
    if topic and genres:
        for g in genres:
            fg = f"{topic.strip()} {g.strip()}"
            if fg not in filtered:
                fallback.append(fg)
    if topic and topic.strip() not in filtered:
        fallback.append(topic.strip())
    if genres:
        for g in genres:
            if g.strip() not in filtered:
                fallback.append(g.strip())
    filtered += [f for f in fallback if f not in filtered][:3]
    filtered = list(dict.fromkeys(filtered))
    return filtered[:6]

# --- Gemini 검색어 생성 프롬프트 (사용자 요청대로 다변화/난이도 강조) ---
def create_prompt_for_search_query(student_data):
    level_desc = student_data.get("reading_level", "")
    topic = student_data.get("topic", "")
    age_grade_selection = student_data.get("student_age_group", "")
    difficulty_hint = student_data.get("difficulty_hint", "")
    genres = student_data.get("genres", [])
    genres_str = ", ".join(genres) if genres else "없음"
    interests = student_data.get("interests", "")
    liked_books_str = ", ".join(student_data.get("liked_books", [])) if student_data.get("liked_books") else "없음"

    # fallback 예시 자동 생성 (주제+장르, 주제, 장르 단독 등)
    fallback_keywords = []
    if topic and genres:
        for g in genres:
            fallback_keywords.append(f"{topic.strip()} {g.strip()}")
    if topic and topic not in fallback_keywords:
        fallback_keywords.append(topic.strip())
    for g in genres:
        if g not in fallback_keywords:
            fallback_keywords.append(g)
    fallback_example_str = "\n".join(fallback_keywords[:3])  # 예시 3개까지만

    # level_desc 활용 난이도 안내 문구
    if "상" in level_desc:
        reading_hint = "(심화: 더 넓고 어려운 개념/용어도 가능)"
    elif "중" in level_desc:
        reading_hint = "(보통: 학교 권장 수준, 입문~중간 정도 난이도)"
    elif "하" in level_desc:
        reading_hint = "(기초: 쉬운 단어/초보자·입문자용 중심, 전문용어X)"
    else:
        reading_hint = ""

    # age_grade 기반 세부 난이도/용어 안내
    if "초등" in age_grade_selection:
        age_specific_instruction = "초등학생이 이해할 수 있는 쉬운 단어로만 생성, 한자/전문용어/어려운 학술어 금지."
    elif "중등" in age_grade_selection or "중학생" in age_grade_selection:
        age_specific_instruction = "중학생 눈높이에 맞는 명확하고 단순한 단어 위주로 생성, 고등/대학/성인 전문용어는 제외."
    elif "고등" in age_grade_selection or "고등학생" in age_grade_selection:
        age_specific_instruction = "고등학생 수준, 대학 교재/성인 전문용어/지나치게 심화된 키워드는 피하세요."
    else:
        age_specific_instruction = ""

    prompt = f"""
아래 학생 정보를 종합적으로 고려해,
한국 도서 검색 엔진(카카오 등)에서 실제 책이 잘 검색될 수 있는 “명사+명사” 중심의 검색 키워드(3~5개)를 생성하세요.

- **모든 입력정보(주제, 장르, 관심사, 독서 수준, 연령, 난이도, 선호 도서 등)를 반드시 반영**하여,
  해당 학생에게 “실제 추천이 유의미한” 키워드를 제안해야 합니다.
- 각 검색어는 반드시 1~3개 “명사”의 조합이어야 하며(예: ‘건축 소설’, ‘건축가’, ‘건축 이야기’, ‘과학 만화’ 등),
  “설명문, 너무 긴 복합어, 완전한 문장형, 예술적 수식, 문단, 느낌표, 불필요한 꾸밈말, 부연 설명”은 절대 포함하지 마세요.
- 키워드는 반드시 실제 책 제목/분야/목차/도서관 분류에서 많이 쓰이는 현실적인 단어만을 조합해야 합니다.
- **생성되는 키워드 중 최소 하나 이상은 학생이 명시적으로 선택한 주요 주제('{topic}')와 선호 장르('{genres_str}')를 직접적으로 결합한 형태여야 합니다.** (예: '{topic} {genres[0] if genres else "관련"} {genres_str if not genres else ""}' 또는 단순히 '{topic} {genres_str}' 형태. 만약 장르가 여러 개면 그 중 하나 이상과 결합)
- **다른 키워드들도 가능한 주요 주제('{topic}')와의 연관성을 유지하도록 노력해주세요.** 주제와 장르를 다양한 방식으로 조합하되, 주제에서 너무 벗어난 하위 장르나 일반적인 장르 키워드는 최소화해주세요.
- 예를 들어, 주제가 '학교도서관'이고 장르가 '소설'이라면, '학교도서관 소설', '학교도서관 배경 청소년 소설' 등을 우선적으로 고려하고, 주제와 직접 관련 없는 '디스토피아 소설' 같은 키워드는 학생의 다른 관심사가 명확하지 않다면 지양해주세요.
- 각 키워드는 한 줄에 하나씩 제안하세요(최소 3개~최대 5개, 부연설명 금지).
- [예시]
{fallback_example_str}

※ 독서 수준: {level_desc} {reading_hint}
※ 연령/학년: {age_grade_selection} ({age_specific_instruction})
※ 난이도 참고: {difficulty_hint}
※ 관심사: {interests}
※ 최근 읽은 책: {liked_books_str}

[입력정보]
주제: {topic}
장르: {genres_str}
관심사: {interests}
"""
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

# --- 카카오 도서 API (사용자 요청대로 변경 없음 명시, 기존 코드 유지) ---
def search_kakao_books(query, api_key, size=10, target="title"): # 기본 size는 10으로 유지
    if not api_key: return None, "카카오 API 키가 설정되지 않았습니다."
    url = "https://dapi.kakao.com/v3/search/book"
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = { "query": query, "sort": "accuracy", "size": size, "target": target } # accuracy 우선
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and "documents" in data:
            for doc in data["documents"]:
                isbn_raw = doc.get('isbn', '')
                if isbn_raw: # ISBN 정리 로직은 기존과 동일
                    isbns = isbn_raw.split()
                    isbn13 = next((s.replace('-', '') for s in isbns if len(s.replace('-', '')) == 13), None)
                    isbn10 = next((s.replace('-', '') for s in isbns if len(s.replace('-', '')) == 10), None)
                    chosen_isbn = isbn13 if isbn13 else (isbn10 if isbn10 else (isbns[0].replace('-', '') if isbns else ''))
                    doc['cleaned_isbn'] = "".join(filter(lambda x: x.isdigit() or x.upper() == 'X', chosen_isbn))
                else: doc['cleaned_isbn'] = ''
        return data, None
    except requests.exceptions.Timeout:
        # print(f"Kakao API 요청 시간 초과: {query}") # 운영 환경에서는 print 대신 로깅 권장
        return None, f"카카오 API '{query}' 검색 시간 초과 🐢"
    except requests.exceptions.RequestException as e:
        # print(f"Kakao API 요청 오류: {e}")
        return None, f"카카오 '{query}' 검색 오류: {e}"
    except Exception as e: # 기타 예외 처리
        # print(f"Kakao API 처리 중 알 수 없는 오류: {e}")
        return None, f"카카오 API 처리 중 알 수 없는 오류: {str(e)[:100]}"


# --- 책 군집화 기반 다양성 추출 (핵심 기능) ---
def cluster_books_for_diversity(book_docs, n_clusters=3):
    """ TF-IDF와 코사인 유사도를 사용해 책 목록에서 다양한 주제의 책 n_clusters개를 선택합니다. """
    texts = [(doc.get('title', '') + ' ' + doc.get('contents', '')) for doc in book_docs]

    # 책 수가 요청 클러스터 수보다 적거나 같으면, 모든 책을 개별 클러스터로 반환
    if not book_docs or len(book_docs) <= n_clusters:
        return [[doc] for doc in book_docs]

    try:
        vectorizer = TfidfVectorizer(min_df=1) # 단일 문서에서도 작동하도록 min_df=1
        tfidf_matrix = vectorizer.fit_transform(texts)

        # 첫 번째 책을 첫 번째 클러스터의 대표로 선택
        selected_indices = [0]
        cluster_representatives = [book_docs[0]]

        for _ in range(1, min(n_clusters, len(book_docs))): # 실제 책 수와 n_clusters 중 작은 값만큼 반복
            min_max_similarity = float('inf')
            next_candidate_idx = -1

            # 아직 선택되지 않은 책 중에서 다음 후보를 찾음
            # (선택된 대표들과의 *최대* 유사도가 *가장 낮은* 책을 선택 -> 다양성 극대화 시도)
            # 또는 (선택된 대표들과의 *평균* 유사도가 *가장 낮은* 책을 선택 -> 사용자 제공 코드 방식)
            # 사용자 제공 코드 방식(평균 유사도 최소화)을 따름:
            
            best_avg_sim_score = float('inf')
            current_best_idx = -1

            for i in range(len(book_docs)):
                if i in selected_indices:
                    continue
                
                # i번째 책과 이미 선택된 대표들과의 평균 유사도 계산
                avg_similarity_to_selected = sum(
                    cosine_similarity(tfidf_matrix[i], tfidf_matrix[j])[0][0] for j in selected_indices
                ) / len(selected_indices)

                if avg_similarity_to_selected < best_avg_sim_score:
                    best_avg_sim_score = avg_similarity_to_selected
                    current_best_idx = i
            
            if current_best_idx != -1:
                selected_indices.append(current_best_idx)
                cluster_representatives.append(book_docs[current_best_idx])
            else: # 더 이상 추가할 후보가 없으면 중단
                break
        
        return [[rep] for rep in cluster_representatives] # 각 대표를 단일 항목 클러스터로 반환

    except Exception as e:
        # print(f"Clustering error: {e}") # 로깅
        # 오류 발생 시 모든 책을 단일 클러스터로 반환하거나, 첫 N개만 반환하는 등의 폴백
        return [book_docs[:n_clusters]] # 단순하게 첫 N개 책을 반환 (또는 각 책을 개별 클러스터로)

# --- 난이도, 출판사 등 자체 스코어 (사용자 요청 버전) ---
def enriched_score_function(book_doc, student_data):
    score = 0
    publisher = book_doc.get('publisher', '')
    normalized_publisher = normalize_publisher_name(publisher)
    title = book_doc.get('title', '').lower() # 소문자 변환 추가
    contents = book_doc.get('contents', '').lower() # 소문자 변환 추가 
    
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
    contents_len = len(book_doc.get('contents', '')) # 원본 contents 사용 (소문자 변환 전)
    if contents_len > 200: score += 10 # 기존 20점에서 10점으로 조정됨
    # elif contents_len > 100: score += 10 # 이 부분은 사용자 코드에서 빠짐

    # 3. 주요 출판사
    if normalized_publisher in MAJOR_PUBLISHERS_NORMALIZED: score += 10

    # 4. 학생 학년 수준에 따른 스코어링
    student_age_group = student_data.get("student_age_group", "")
    if "초등학생" in student_age_group:
        if normalized_publisher in CHILDREN_PUBLISHERS_NORMALIZED:
            score += 30 # 어린이 전문 출판사면 큰 가산점!
        if "어린이" in title or "초등" in title or "동화" in title:
            score += 20 # 제목에 어린이/초등 키워드
        if "어린이" in contents or "초등학생" in contents or "쉽게 배우는" in contents: # contents도 소문자로 비교
            score += 10 # 소개에 어린이/초등학생 키워드
    elif "중학생" in student_age_group:
        if "중학생" in title or "청소년" in title or "10대" in title:
            score += 15
        if "중학생" in contents or "청소년" in contents or "십대를 위한" in contents: # contents도 소문자로 비교
            score += 7
    elif "고등학생" in student_age_group:
        if "고등학생" in title or "수험생" in title or ("청소년" in title and "심화" in title):
            score += 10
        # 고등학생은 내용 일치도가 더 중요할 수 있어 contents 가점은 일단 보류 또는 다른 방식으로 접근

    # 0. 도서관 소장 여부 가산점 추가
    if book_doc.get("found_in_library"):
        score += 40  # (30~50점 추천, 전체 점수 분포에 맞게)
    
    return score

def select_final_candidates_with_library_priority(candidates, top_n=4):
    """소장자료가 있으면 반드시 상위 1권 포함, 없으면 그냥 다양성/적합성 top_n 반환 + 안내문구"""
    library_books = [b for b in candidates if b.get("found_in_library")]
    non_library_books = [b for b in candidates if not b.get("found_in_library")]
    library_books = sorted(library_books, key=lambda x: x['score'], reverse=True)
    non_library_books = sorted(non_library_books, key=lambda x: x['score'], reverse=True)
    if library_books:
        final_candidates = [library_books[0]] + non_library_books[:top_n-1]
        library_notice = "도서관 소장 자료가 포함된 추천 리스트입니다."
    else:
        final_candidates = non_library_books[:top_n]
        library_notice = "아쉽게도 도서관에 소장된 추천 도서는 없어요. 대신 이런 책을 추천해요!"
    return final_candidates, library_notice

def create_prompt_for_final_selection(student_data, kakao_book_candidates_docs):
    level_desc = student_data["reading_level"]
    topic = student_data["topic"]
    age_grade_selection = student_data["student_age_group"]
    difficulty_hint = student_data["difficulty_hint"]
    interests = student_data["interests"]
    candidate_books_info = []

    # 최대 7권까지 후보로 보여주는 것은 동일 (실제로는 클러스터링 결과로 3~4권이 주로 전달될 것)
    if kakao_book_candidates_docs and isinstance(kakao_book_candidates_docs, list):
        for i, book in enumerate(kakao_book_candidates_docs):
            if i >= 10: break # Gemini에게 전달할 후보 최대 개수 제한
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
                f"    소개(요약): {book.get('contents', '정보 없음')[:250]}..." # 요약 길이 유지
            )
    candidate_books_str = "\n\n".join(candidate_books_info) if candidate_books_info else "검색된 책 후보 없음."

    age_specific_selection_instruction = ""
    if "초등학생" in age_grade_selection:
        age_specific_selection_instruction = "특히, 이 학생은 초등학생이므로, 제공된 후보 목록 중에서도 **반드시 초등학생의 눈높이에 맞는 단어, 문장, 그림(만약 유추 가능하다면), 주제 접근 방식을 가진 책**을 골라야 합니다. 청소년이나 성인 대상의 책은 내용이 아무리 좋아도 제외해주세요. 책의 '소개(요약)', '출판사', '제목' 등을 통해 초등학생 적합성을 최우선으로 판단해야 합니다. 만약 후보 중에 초등학생에게 진정으로 적합한 책이 없다면, JSON 결과로 빈 배열 `[]`을 반환하고, 그 외 텍스트 영역에 그 이유를 설명해주세요."
    elif "중학생" in age_grade_selection:
        age_specific_selection_instruction = "이 학생은 중학생입니다. 후보 중에서 **중학생의 지적 호기심을 자극하고 이해 수준에 맞는 책**을 골라주세요. 너무 어리거나 전문적인 책은 피해주세요."
    elif "고등학생" in age_grade_selection:
        age_specific_selection_instruction = "이 학생은 고등학생입니다. **탐구 주제에 대해 심도 있는 이해를 돕거나 다양한 관점을 제시하는 책**을 우선적으로 고려해주세요. 너무 가볍거나 전문성이 떨어지는 책은 제외하고, 대학 전공 서적 수준의 깊이는 아니어야 합니다."


    prompt = f"""
당신은 제공된 여러 실제 책 후보 중에서 학생의 원래 요구사항에 가장 잘 맞는 책을 최대 3권까지 최종 선택하고, 각 책에 대한 맞춤형 추천 이유를 작성하는 친절하고 현명한 도서관 요정 '도도'입니다.

[학생 정보 원본]
- 독서 수준 묘사: {level_desc}
- 학생 학년 수준: {age_grade_selection}
- 주요 탐구 주제: {topic}
- 주제 관련 특별 관심사/파고들고 싶은 부분: {interests}

[학생 수준 참고사항]
{difficulty_hint}

[카카오 API 및 자체 필터링/다양성 확보를 통해 선정된 주요 책 후보 목록]
{candidate_books_str}

[요청 사항]
1.  위 [주요 책 후보 목록]에서 학생에게 가장 적합하다고 판단되는 책을 최소 2권, 가능하다면 최대 5권까지 선택해주세요.
2.  선택 시 다음 사항을 **종합적으로 고려**하여, 학생의 탐구 활동에 실질적으로 도움이 될 **'인기 있거나 검증된 좋은 책'**을 우선적으로 선정해주세요:
    * **학생의 요구사항 부합도 (가장 중요!):** 주제, 관심사, 그리고 특히 **'학생 학년 수준'과 '학생 수준 참고사항'에 명시된 난이도**에 얼마나 잘 맞는가?
    * {age_specific_selection_instruction}
    * **책의 신뢰도 및 대중성(추정):** 출판사, 저자 인지도, 출판년도(너무 오래되지 않은 책), 소개글의 충실도 등을 고려해주세요.
    * **정보의 깊이와 폭:** 학생의 탐구 주제에 대해 얼마나 깊이 있고 넓은 정보를 제공하는가? (단, 학생 수준에 맞춰야 함)
3.  선택된 각 책의 정보는 아래 명시된 필드를 포함하는 **JSON 객체**로 만들어주세요.
JSON 객체 필드 설명:
- "title" (String): 정확한 책 제목
- "author" (String): 실제 저자명 (쉼표로 구분된 문자열)
- "publisher" (String): 실제 출판사명
- "year" (String): 출판년도 (YYYY년 형식)
- "isbn" (String): 실제 ISBN (숫자와 X만 포함된 순수 문자열, 하이픈 없이)
- "reason" (String): 학생 맞춤형 추천 이유 (1-2 문장, 친절하고 설득력 있게)

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

만약 [주요 책 후보 목록]이 "검색된 책 후보 없음"이거나, 후보 중에서 위 기준에 따라 적절한 책을 고르기 어렵다면, BOOKS_JSON_START와 BOOKS_JSON_END 마커 사이에 빈 배열 `[]`을 넣어주고, 그 외의 텍스트 영역에 학생의 [학생 정보 원본]과 [학생 수준 참고사항]만을 참고하여 일반적인 조언이나 탐색 방향을 제시해주세요. 단, 이 경우에도 구체적인 (가상의) 책 제목을 JSON 안에 지어내지는 마세요.

자, 이제 최종 추천을 부탁해요! ✨
"""
    return prompt

def get_ai_recommendation(model_to_use, prompt_text, generation_config=None):
    if not model_to_use:
        return "🚫 AI 모델이 준비되지 않았어요. API 키 설정을 확인해주세요!"
    try:
        # 기본 temperature를 약간 낮춰서 일관성 있는 답변 유도 (필요시 프롬프트별 조정)
        final_generation_config = generation_config if generation_config else genai.GenerationConfig(temperature=0.3)
        response = model_to_use.generate_content(
            prompt_text,
            generation_config=final_generation_config,
            # safety_settings=[ # 필요시 안전 설정 강화 또는 완화
            #     {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            #     {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            # ]
        )
        return response.text
    except genai.types.generation_types.BlockedPromptException as e:
        # print(f"Gemini API BlockedPromptException: {e}") # 로깅
        return "🚨 이런! 도도 요정이 이 요청에 대한 답변을 생성하는 데 어려움을 느끼고 있어요. 입력 내용을 조금 바꿔서 다시 시도해볼까요? (콘텐츠 안전 문제일 수 있어요!)"
    except Exception as e:
        error_message_detail = str(e).lower()
        if "rate limit" in error_message_detail or "quota" in error_message_detail or "resource_exhausted" in error_message_detail or "resource has been exhausted" in error_message_detail or "429" in error_message_detail:
            error_message = "🚀 지금 도도를 찾는 친구들이 너무 많아서 조금 바빠요! 잠시 후에 다시 시도해주면 요정의 가루를 뿌려줄게요! ✨ (요청 한도 초과 또는 일시적 과부하)"
        else:
            error_message = f"🧚 AI 요정님 호출 중 예상치 못한 오류 발생!: {str(e)[:200]}...\n잠시 후 다시 시도해주세요."
        # print(f"Gemini API Error: {e}") # 로깅
        return error_message

# --- 3. Streamlit 앱 UI 구성 (기존 UI 최대한 유지) ---
st.set_page_config(page_title="도서관 요정 도도의 도서 추천! 🕊️", page_icon="🧚", layout="centered")

# 서비스 소개 문구 (기존과 동일)
st.markdown(
    """
    <div style='
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        background-color: #f0f0f0;
        padding: 13px 8px 11px 8px;
        border-radius: 7px;
        margin-bottom: 5px;
        font-size: 1.03em;
        color: #343434;
        font-weight: 500;
        width: 100%;
    '>
        <div style="width:100%;text-align:center;">
            이 서비스는 AI를 활용한 도서 추천으로,<br>
            사용량이 많거나 복잡한 요청 시 응답이 지연될 수 있습니다.<br>
            너른 양해 부탁드려요! 😊
        </div>
    </div>
    """,
    unsafe_allow_html=True
)
st.markdown("---") # 구분선

# 메인 타이틀 (기존과 동일)
st.markdown("""
<style>
    .main-title-container {
        background-color: #E0F7FA; padding: 30px; border-radius: 15px;
        text-align: center; box-shadow: 0 6px 12px rgba(0,0,0,0.1); margin-bottom: 40px;
    }
    .main-title-container h1 { color: #00796B; font-weight: bold; font-size: 2.5em; margin-bottom: 15px; }
    .main-title-container p { color: #004D40; font-size: 1.15em; line-height: 1.7; }
    .centered-subheader { text-align: center; margin-top: 20px; margin-bottom: 10px; color: #00796B; font-weight:bold; }
    .centered-caption { text-align: center; display: block; margin-bottom: 20px; margin-top: -5px} /* 기존 스타일 유지 */
    .recommendation-card-title { text-align: center; color: #004D40; margin-top: 0; margin-bottom: 8px; font-size: 1.4em; font-weight: bold;}
    .book-meta { font-size: 0.9em; color: #37474F; margin-bottom: 10px; }
    .reason { font-style: normal; color: #263238; background-color: #E8F5E9; padding: 12px; border-radius: 5px; margin-bottom:10px; border-left: 4px solid #4CAF50;}
    .library-status-success { color: #2E7D32; font-weight: bold; background-color: #C8E6C9; padding: 8px; border-radius: 5px; display: block; margin-top: 8px; text-align: left;}
    .library-status-info { color: #0277BD; font-weight: bold; background-color: #B3E5FC; padding: 8px; border-radius: 5px; display: block; margin-top: 8px; text-align: left;}
    .library-status-warning { color: #C62828; /* 경고색 변경 */ background-color: #FFCDD2; padding: 8px; border-radius: 5px; margin-top: 8px; display:block; text-align: left;}
    .highlighted-advice-block { background-color: #FFFDE7; border-left: 5px solid #FFC107; padding: 20px; border-radius: 8px; margin-top: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .highlighted-advice-block h5 { color: #FFA000; margin-top: 0; margin-bottom: 10px; }
</style>
<div class="main-title-container">
    <h1>✨ 도도의 똑똑한 도서 추천! ✨</h1>
    <p>안녕하세요! 여러분의 도서 검색을 도와줄 도서관 요정 🧚<strong>도도</strong>입니다!<br>
    아래 정보를 입력해주시면 맞춤형 책을 찾아드릴게요! 얍얍!</p>
</div>
""", unsafe_allow_html=True)

if gemini_api_error: st.error(gemini_api_error); st.stop()
if kakao_api_error: st.error(kakao_api_error); st.stop()

# --- 사이드바 구성 (기존과 동일) ---
st.sidebar.markdown("---")
st.sidebar.markdown(
    """<div style="text-align:center; font-weight:bold; font-size:1.15em; margin-bottom:0.3em;">도도의 비밀 노트 🤫</div>""",
    unsafe_allow_html=True
)
st.sidebar.markdown(
    f"""<div style="text-align:center; color:#00796B; font-size:1.05em; margin-bottom:0.7em;">오늘 날짜: {st.session_state.get('TODAYS_DATE', '날짜 정보 없음')}</div>""",
    unsafe_allow_html=True
)
st.sidebar.markdown(
    """
    <ul style="font-size:0.98em; color:#333; margin-bottom:1em; margin-left:-1em;">
        <li>도도는 <b>Gemini</b>와 <b>Kakao API</b>를 사용해요.</li>
        <li>가끔 너무 신나서 엉뚱한 추천을 할 수도 있으니 너그러이 봐주세요.</li>
        <li>AI가 알려준 정보를 그대로 수용하지 말고, 추가 검증을 꼭 거치세요!</li>
        <li>버그나 개선점은 👩‍💻 <b>개발자</b>에게 살짝 알려주세요.</li>
    </ul>
    """,
    unsafe_allow_html=True
)
st.sidebar.markdown("---")
st.sidebar.markdown(
    """<div style="text-align:center;"><span style="font-weight:bold;">⚙️ 현재 사용 엔진 정보</span></div>""",
    unsafe_allow_html=True
)
st.sidebar.markdown(
    f"""<div style="text-align:center; margin-bottom:10px;"><b>AI 모델:</b> <code>{gemini_model_name}</code></div>""",
    unsafe_allow_html=True
)

# 모델별 RPM/RPD 정보 (기존과 동일)
if gemini_model_name == 'gemini-1.5-flash-latest':
    RPM_INFO = "분당 요청 수(RPM): 약 15회 (무료 등급)"
    RPD_INFO = "일일 요청 수(RPD): 약 500회 (무료 등급)"
    CONCURRENT_USERS_ESTIMATE = "동시 사용 예상: 약 7명 내외 (학생당 2회 AI 호출 가정)"
elif gemini_model_name == 'gemini-1.5-pro-latest':
    RPM_INFO = "분당 요청 수(RPM): 확인 필요 (일반적으로 Flash보다 높거나 유사할 수 있음)"
    RPD_INFO = "일일 요청 수(RPD): 확인 필요"
    CONCURRENT_USERS_ESTIMATE = "동시 사용 예상: 실제 테스트 필요"
elif 'flash-lite' in gemini_model_name.lower() or 'gemini-2.0-flash-lite' in gemini_model_name.lower() : # 현재 모델명 대응
    RPM_INFO = "분당 요청 수(RPM): 약 30회 (무료 등급)" # Gemini 2.0 Flash Lite의 정확한 한도 확인 필요
    RPD_INFO = "일일 요청 수(RPD): 약 1,500회 (무료 등급)" # Gemini 2.0 Flash Lite의 정확한 한도 확인 필요
    CONCURRENT_USERS_ESTIMATE = "동시 사용 예상: 약 15명 내외 (학생당 2회 AI 호출 가정)"
else:
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
    """<div style="font-size:0.80em; line-height:1.8; color:gray; text-align:center;">위 정보는 일반적인 무료 등급 기준이며,<br>실제 할당량은 다를 수 있습니다.</div>""",
    unsafe_allow_html=True
)
st.sidebar.markdown("---")
st.sidebar.markdown(
    """<div style="text-align:center; margin-bottom:0.2em;"><span style="font-weight:bold;">👩‍💻 총괄 디렉터: 꾸물 🐌</span><br><span style="font-weight:bold;">🕊️ AI 어시스턴트: 도도</span></div>""",
    unsafe_allow_html=True
)
st.sidebar.markdown(
    """<div style="font-size:0.92em; color:#888; text-align:center; margin-top:4px; margin-bottom:12px;">문의: <a href="mailto:zambi23@gmail.com" style="color:#888; text-decoration:underline;">zambi23@gmail.com</a><br>블로그: <a href="https://blog.naver.com/snailslowclub" style="color:#888; text-decoration:underline;" target="_blank">꾸물책장</a></div>""",
    unsafe_allow_html=True
)
st.sidebar.markdown("---")
st.sidebar.caption("⚠️ API 호출은 사용량에 따라 비용이 발생할 수 있으니 주의해주세요!")


st.markdown("---") # 구분선 추가
st.markdown("<h3 class='centered-subheader'>📚 최근 재미있게 읽은 책 (선택 사항)</h3>", unsafe_allow_html=True)
st.markdown("<p class='centered-caption'>AI 요정 도도가 여러분의 취향을 파악하는 데 큰 도움이 돼요! 한 권씩 추가해주세요!</p>", unsafe_allow_html=True)

col_add_book_input, col_add_book_button_placeholder = st.columns([0.75, 0.25])
with col_add_book_input:
    st.session_state.current_book_to_add = st.text_input(
        "책 제목과 저자를 입력해주세요:", value=st.session_state.get("current_book_to_add", ""), # get으로 안전하게 접근
        placeholder="예: 멋진 신세계 (올더스 헉슬리)", key="new_book_text_input_widget_key_outside_form", label_visibility="collapsed"
    )
with col_add_book_button_placeholder:
    if st.button("➕ 이 책 추가", key="add_book_button_key_outside_form", use_container_width=True):
        book_val = st.session_state.new_book_text_input_widget_key_outside_form # 직접 접근
        if book_val and book_val.strip():
            if book_val not in st.session_state.liked_books_list:
                st.session_state.liked_books_list.append(book_val)
            st.session_state.current_book_to_add = "" # 입력 필드 초기화
            st.rerun() # 목록 즉시 업데이트
        else: st.warning("책 제목을 입력해주세요!", icon="🕊️")

if st.session_state.liked_books_list:
    st.write("📖 추가된 책 목록:")
    for i, book_title in enumerate(list(st.session_state.liked_books_list)): # 복사본 순회
        with st.container(border=True): # 테두리 있는 컨테이너
            item_col1, item_col2 = st.columns([0.9, 0.1])
            with item_col1: st.markdown(f"  - {book_title}")
            with item_col2:
                if st.button("➖", key=f"remove_book_outside_form_{i}", help="이 책을 목록에서 삭제해요.", use_container_width=True):
                    st.session_state.liked_books_list.pop(i)
                    st.rerun() # 목록 즉시 업데이트
    st.write("") # 약간의 여백
else:
    st.markdown("<p class='centered-caption' style='font-style: italic;'>(아직 추가된 책이 없어요.)</p>", unsafe_allow_html=True)

st.markdown("---")


# --- 메인 입력 폼 (기존과 동일) ---
st.markdown("<h3 class='centered-subheader'>🧭 탐험가의 나침반을 채워주세요!</h3>", unsafe_allow_html=True)
with st.form("recommendation_form"):
    level_opts = ["새싹 탐험가 🌱 (그림 많고 글자 적은 게 좋아요!)", "초보 탐험가 🚶‍♀️ (술술 읽히고 너무 두껍지 않은 책!)", "중급 탐험가 🏃‍♂️ (어느 정도 깊이 있는 내용도 OK!)", "고수 탐험가 🧗‍♀️ (전문 용어나 복잡한 내용도 도전 가능!)"]
    reading_level = st.selectbox("📖 독서 수준:", options=level_opts, help="독서 경험에 가장 잘 맞는 설명을 골라주세요!")

    age_group_options = ["선택안함", "초등학생 (8-13세)", "중학생 (14-16세)", "고등학생 (17-19세)"]
    student_age_group_selection = st.selectbox("🧑‍🎓 학생의 학년 그룹을 선택해주세요:", options=age_group_options, index=0, help="학생의 학년 수준을 알려주시면 난이도 조절에 큰 도움이 돼요!")

    topic = st.text_input("🔬 주요 탐구 주제:", placeholder="예: 인공지능과 직업의 미래", help="가장 핵심적인 탐구 주제를 알려주세요.")

    genre_opts = ["소설", "SF", "판타지", "역사", "과학", "수학/공학", "예술/문화", "사회/정치/경제", "인물 이야기", "에세이/철학", "기타"]
    genres = st.multiselect("🎨 선호 장르 (다중 선택 가능):", options=genre_opts, help="좋아하는 이야기 스타일을 골라주시면 취향 저격에 도움이 돼요!")

    interests = st.text_input("💡 주제 관련 특별 관심사:", placeholder="예: AI 윤리 중 알고리즘 편향성", help="주제 안에서도 궁금한 세부 내용을 적어주세요.")
    disliked_conditions = st.text_input("🚫 피하고 싶은 조건:", placeholder="예: 너무 슬픈 결말, 지나치게 전문적인 내용", help="이런 책은 추천에서 빼드릴게요!")

    form_cols = st.columns([1, 1.5, 1]) # 버튼 중앙 정렬용 컬럼
    with form_cols[1]:
        submitted = st.form_submit_button("🕊️ 도도에게 책 추천받기! ✨", use_container_width=True)


# --- 4. 추천 로직 실행 및 결과 표시 (핵심 변경 사항 반영) ---
if submitted:
    difficulty_hints_map = { # 난이도 힌트 설정 (기존과 동일)
        "초등학생 (8-13세)": "이 학생은 초등학생입니다. 매우 이해하기 쉬운 단어와 문장을 사용하고, 친절하고 상세한 설명을 제공해주세요. 추천하는 책이나 검색어도 초등학생 눈높이에 맞춰주세요.",
        "중학생 (14-16세)": "이 학생은 중학생입니다. 적절한 수준의 어휘를 사용하고, 너무 단순하거나 유치하지 않으면서도 명확한 설명을 제공해주세요. 추천하는 책이나 검색어도 중학생 수준에 적합해야 합니다.",
        "고등학생 (17-19세)": "이 학생은 고등학생입니다. 정확한 개념과 논리적인 설명을 중심으로 답변해주세요. 탐구 보고서 작성에 도움이 될 만한 심도 있는 내용이나 다양한 관점을 제시해도 좋습니다.",
        "선택안함": "학생의 연령대가 특정되지 않았습니다. 일반적인 청소년 수준을 고려하되, 너무 어렵거나 전문적인 내용은 피해주세요."
    }
    selected_difficulty_hint = difficulty_hints_map.get(student_age_group_selection, difficulty_hints_map["선택안함"])

    if not topic.strip():
        st.warning("❗ 주요 탐구 주제를 입력해주셔야 추천이 가능해요!", icon="📝")
    elif student_age_group_selection == "선택안함":
        st.info("학년 그룹을 선택하시면 도도가 더욱 정확한 난이도의 책을 추천해드릴 수 있어요! 😊 (추천은 계속 진행됩니다)")
        # 추천은 계속 진행, selected_difficulty_hint는 "선택안함"에 대한 내용
    
    # 주제가 입력되었을 때만 진행
    if topic.strip():
        st.markdown("---")
        st.markdown("<h2 class='centered-subheader'>🎁 도도의 정밀 탐색 결과!</h2>", unsafe_allow_html=True)

        with st.spinner("도도 요정이 마법 안경을 쓰고 책을 찾고 있어요... 잠시만 기다려주세요... 🧚✨"):
            student_data = {
                "reading_level": reading_level, "topic": topic,
                "student_age_group": student_age_group_selection,
                "difficulty_hint": selected_difficulty_hint,
                "age_grade": student_age_group_selection, # 프롬프트 호환성 위해 유지
                "genres": genres if genres else [],
                "interests": interests if interests else "특별히 없음",
                "liked_books": st.session_state.liked_books_list,
                "disliked_conditions": disliked_conditions if disliked_conditions else "특별히 없음"
            }

            # --- 1단계: Gemini에게 "다중 검색어" 생성 요청 (업데이트된 프롬프트 사용) ---
            search_queries_prompt = create_prompt_for_search_query(student_data)
            search_query_gen_config = genai.GenerationConfig(temperature=0.1) # 검색어는 일관성있게
            search_queries_response = get_ai_recommendation(gemini_model, search_queries_prompt, generation_config=search_query_gen_config)
            generated_search_queries = extract_search_queries_from_llm(
                search_queries_response,
                student_data["topic"],
                student_data["genres"]
            )

            if not generated_search_queries or "AI 요정님 호출 중" in search_queries_response or "AI 모델이 준비되지 않았어요" in search_queries_response or "콘텐츠 안전 문제일 수 있어요" in search_queries_response:
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
                # 각 검색어당 가져오는 책 수를 늘려 다양성 확보 (예: 15~20권)
                kakao_page_results, kakao_error_msg = search_kakao_books(query, KAKAO_API_KEY, size=15) # size 증가
                
                if kakao_error_msg:
                    search_errors.append(f"'{query}' 검색 시: {kakao_error_msg}")
                    continue
                if kakao_page_results and kakao_page_results.get("documents"):
                    for book_doc in kakao_page_results["documents"]:
                        # 출판사 필터링 (소문자로 비교)
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

            st.success(f"카카오에서 총 {len(all_kakao_books_raw)}권의 고유한 책 후보를 찾았어요! 이제 적합성과 다양성을 고려해볼게요!")

            # --- 3단계: 학생 수준 기반 1차 필터링 ---
            pre_filtered_books = []
            children_keywords = ["어린이", "초등", "초등학생", "동화", "저학년", "고학년", "그림책"]
            teen_keywords = ["청소년", "중학생", "십대", "10대", "고등학생"]

            for book_doc in all_kakao_books_raw:
                passes_filter = True
                title_lower = book_doc.get('title', '').lower()
                contents_lower = book_doc.get('contents', '').lower()
                publisher_normalized = normalize_publisher_name(book_doc.get('publisher', ''))
                
                age_group = student_data["student_age_group"]

                if "초등학생" in age_group:
                    is_children_book_evidence = False
                    if publisher_normalized in CHILDREN_PUBLISHERS_NORMALIZED: is_children_book_evidence = True
                    if any(keyword in title_lower for keyword in children_keywords): is_children_book_evidence = True
                    # 내용에 청소년/성인 키워드가 강하게 나타나면 제외 (예: "대학생", "성인")
                    if any(kw in contents_lower for kw in ["대학생을 위한", "성인 독자를 위한", "전문가를 위한"]):
                        is_children_book_evidence = False # 이런건 확실히 제외
                    if not is_children_book_evidence and not (any(kw in contents_lower for kw in children_keywords)): # 제목/출판사 증거도 없고, 내용에도 없으면
                        passes_filter = False
                
                elif "중학생" in age_group or "고등학생" in age_group:
                    # 명백한 어린이 책(그림책, 저학년 동화 등) 제외 시도
                    if publisher_normalized in CHILDREN_PUBLISHERS_NORMALIZED and not any(kw in title_lower for kw in teen_keywords + ["논픽션", "지식"]):
                        passes_filter = False # 아동 출판사인데 청소년 키워드 없으면 일단 제외
                    if any(kw in title_lower for kw in ["그림책", "유아", "만0세"]) and not any(kw in title_lower for kw in teen_keywords):
                         passes_filter = False # 명백한 유아용 타이틀 제외
                    if "초등학생" in title_lower and "고학년" not in title_lower and not any(kw in title_lower for kw in teen_keywords): # '초등학생'인데 고학년용 아니거나 청소년용 아니면 제외
                        passes_filter = False


                if passes_filter:
                    pre_filtered_books.append(book_doc)
            
            if not pre_filtered_books:
                st.markdown("<div class='highlighted-advice-block'>", unsafe_allow_html=True)
                st.markdown(f"##### 😥 이런! '{student_data['student_age_group']}' 수준에 맞는 책 후보를 카카오 검색 결과에서 찾지 못했어요...")
                prompt_for_advice = create_prompt_for_no_results_advice(student_data, generated_search_queries) # 이전 검색어 전달
                advice_text = get_ai_recommendation(gemini_model, prompt_for_advice, generation_config=genai.GenerationConfig(temperature=0.5))
                st.markdown(advice_text)
                st.markdown("</div>", unsafe_allow_html=True)
                st.stop()

            st.info(f"학생 수준 필터링 후 {len(pre_filtered_books)}권의 책으로 줄었어요. 이제 이 중에서 다양한 주제의 책을 골라볼게요!")

            # --- 4단계: TF-IDF 군집화로 다양한 주제의 책 N권 선별 ---
            N_CLUSTERS_FOR_GEMINI = 10 # Gemini에게 전달할 대표 후보 수 (최종 추천은 3권 이내)
                                      # 다양성을 위해 약간 더 많이 뽑아서 전달
            
            if len(pre_filtered_books) == 0: # 이 경우는 위에서 처리되지만, 안전장치
                 # ... (위와 동일한 결과 없음 처리) ...
                 st.stop()

            # 군집화 함수는 각 대표 책을 담은 리스트의 리스트를 반환 [[rep1], [rep2], ...]
            clustered_representative_groups = cluster_books_for_diversity(pre_filtered_books, n_clusters=N_CLUSTERS_FOR_GEMINI)
            
            # 각 그룹에서 대표 책(하나씩 들어있음)을 추출하여 최종 후보 목록 생성
            candidates_for_gemini_selection_docs = [group[0] for group in clustered_representative_groups if group] # group이 비어있지 않은 경우에만

            # 만약 클러스터링 결과가 N_CLUSTERS_FOR_GEMINI보다 적을 수 있음 (원본 책 수가 적거나 할 때)
            # 또는 너무 유사한 책들만 있어서 대표가 적게 뽑혔을 때 -> 이 경우 enriched_score로 상위권 추가 고려 가능
            # 현재는 cluster_books_for_diversity가 n_cluster만큼 뽑으려 시도하거나 그보다 적은 수의 대표를 줌

            if not candidates_for_gemini_selection_docs:
                st.markdown("<div class='highlighted-advice-block'>", unsafe_allow_html=True)
                st.markdown("##### 😥 이런! 필터링된 책들 중에서 다양한 주제의 최종 후보를 선정하지 못했어요...")
                prompt_for_advice = create_prompt_for_no_results_advice(student_data, generated_search_queries)
                advice_text = get_ai_recommendation(gemini_model, prompt_for_advice, generation_config=genai.GenerationConfig(temperature=0.5))
                st.markdown(advice_text)
                st.markdown("</div>", unsafe_allow_html=True)
                st.stop()

            for doc in candidates_for_gemini_selection_docs:
                kakao_isbn_cleaned = doc.get('cleaned_isbn', '') # 카카오에서 가져온 (이미 정리된) ISBN
                kakao_title = doc.get('title', '')
                kakao_authors_list = doc.get('authors', [])
                kakao_main_author = kakao_authors_list[0] if kakao_authors_list else "" # 첫 번째 저자 사용

                lib_info = {} # 도서관 검색 결과를 담을 딕셔너리 초기화
                doc["found_in_library"] = False # 기본값은 못 찾음
                doc["library_match_type"] = "none" # 어떻게 찾았는지 기록 (isbn, title_author, none)

                if kakao_isbn_cleaned: # 카카오 ISBN 정보가 있다면
                    lib_info_isbn = find_book_in_library_by_isbn(kakao_isbn_cleaned)
                    if lib_info_isbn.get("found_in_library"):
                        lib_info = lib_info_isbn
                        doc["found_in_library"] = True
                        doc["library_match_type"] = "isbn_match"

                # ISBN으로 못 찾았고, 제목 정보가 있고, 아직 라이브러리에서 못 찾았다면 제목/저자로 재시도
                if not doc["found_in_library"] and kakao_title:
                    lib_info_title_author = find_book_in_library_by_title_author(kakao_title, kakao_main_author)
                    if lib_info_title_author.get("found_in_library"):
                        lib_info = lib_info_title_author # 찾았으면 이 정보로 대체!
                        doc["found_in_library"] = True
                        doc["library_match_type"] = "title_author_match"
                
                # 최종적으로 도서관에서 찾았다면, 관련 정보 저장 (enriched_score_function 등에서 활용 가능)
                if doc["found_in_library"] and lib_info:
                    doc["library_isbn"] = lib_info.get("isbn") 
                    doc["library_title"] = lib_info.get("title") 
                    doc["call_number"] = lib_info.get("call_number")
                    doc["library_status"] = lib_info.get("status")
                    # 필요하다면 더 많은 정보를 doc에 추가할 수 있습니다.
                
                # 점수 계산은 found_in_library 상태가 확정된 후에 수행
                doc["score"] = enriched_score_function(doc, student_data)

            final_candidates_for_gemini, library_notice = select_final_candidates_with_library_priority(
                candidates_for_gemini_selection_docs, top_n=4  # or 원하는 N (보통 4)
            )
            st.info(library_notice)
            
            st.info(f"주제 다양성을 고려하여 엄선된 {len(candidates_for_gemini_selection_docs)}권의 최종 후보를 도도 요정에게 전달하여 최종 추천을 받을게요!")

            # --- 5단계: 정렬된 후보를 바탕으로 Gemini에게 최종 선택 및 이유 생성 요청 ---
            final_selection_prompt = create_prompt_for_final_selection(student_data, candidates_for_gemini_selection_docs)
            final_selection_gen_config = genai.GenerationConfig(temperature=0.4) # 추천 이유는 약간의 창의성 허용
            final_recs_text = get_ai_recommendation(gemini_model, final_selection_prompt, generation_config=final_selection_gen_config)

            # --- 6단계: 최종 결과 파싱 및 표시 ---
            books_data_from_ai = [] 
            intro_text_from_ai = ""
            text_after_json_block = "" # JSON 블록 이후 텍스트를 저장할 변수

            try:
                json_start_marker = "BOOKS_JSON_START"; json_end_marker = "BOOKS_JSON_END"
                start_idx = final_recs_text.find(json_start_marker); end_idx = final_recs_text.find(json_end_marker)

                if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                    intro_text_from_ai = final_recs_text[:start_idx].strip()
                    text_after_json_block = final_recs_text[end_idx + len(json_end_marker):].strip() # 먼저 정의

                    if intro_text_from_ai: 
                        st.markdown(intro_text_from_ai) # AI의 도입부 설명 표시
                    
                    json_string_raw = final_recs_text[start_idx + len(json_start_marker) : end_idx].strip()
                    if json_string_raw.startswith("```json"): json_string_raw = json_string_raw[len("```json"):].strip()
                    if json_string_raw.endswith("```"): json_string_raw = json_string_raw[:-len("```")].strip()
                    
                    if json_string_raw and json_string_raw != "[]":
                        books_data_from_ai = json.loads(json_string_raw)
                        if not isinstance(books_data_from_ai, list): 
                            st.warning("AI가 JSON 배열 형태로 주지 않았어요. 😥 결과를 확인해주세요."); books_data_from_ai = []
                    
                    # Case 1: 성공적으로 책 목록이 파싱된 경우
                    if books_data_from_ai:
                        if text_after_json_block: # JSON 이후 추가 설명이 있다면 표시
                            st.markdown("---"); st.markdown(text_after_json_block)
                    # Case 2: 책 목록이 비어있는 경우 (json_string_raw가 "[]" 였거나, 파싱 후 비워짐)
                    else: 
                        if text_after_json_block: # AI가 빈 배열과 함께 설명을 뒤에 붙였다면 표시
                            st.markdown("---"); st.markdown(text_after_json_block)
                        
                        # AI가 제공한 intro 또는 JSON 이후 텍스트에 충분한 설명이 없다고 판단될 때만 추가 조언
                        # intro_text_from_ai는 이미 위에서 markdown으로 표시되었음
                        ai_provided_sufficient_explanation = intro_text_from_ai.strip() or text_after_json_block.strip()
                        
                        if not ai_provided_sufficient_explanation:
                            st.info("도도 요정이 최종 추천할 만한 책을 찾지 못했어요. 아래 추가 조언을 확인해보세요!")
                            st.markdown("<div class='highlighted-advice-block'>", unsafe_allow_html=True)
                            st.markdown(f"##### 🧚 도도의 추가 조언 (최종 추천 실패 시)")
                            prompt_for_advice_final = create_prompt_for_no_results_advice(student_data, generated_search_queries)
                            advice_text_final = get_ai_recommendation(gemini_model, prompt_for_advice_final, generation_config=genai.GenerationConfig(temperature=0.5))
                            st.markdown(advice_text_final)
                            st.markdown("</div>", unsafe_allow_html=True)
                        # else: AI가 이미 설명을 제공했으므로 (intro 또는 text_after_json_block) 추가 조언은 생략
                
                else: # 마커를 아예 못 찾았을 경우
                    with st.container(border=True): st.markdown(final_recs_text) # AI의 전체 답변 표시
                    st.warning("앗, AI 답변에서 약속된 책 정보(JSON) 부분을 찾지 못했어요. AI의 전체 답변을 위에 표시했어요.", icon="⚠️")
                    # 이 경우에도 일반적인 "결과 없음 조언"을 추가로 표시할 수 있습니다 (선택 사항).
                    # 예: if "추천할 만한 책을 찾지 못했습니다" 등의 키워드가 final_recs_text에 없다면 추가 조언 표시
                    # st.markdown("<div class='highlighted-advice-block'>", ...)
            
            except json.JSONDecodeError as json_err:
                st.error(f"AI 생성 책 정보(JSON) 파싱 실패! 😭 내용: {json_err}", icon="🔥"); st.code(final_recs_text, language="text")
            except Exception as e: # 기타 예외
                st.error(f"책 정보 처리 중 오류: {e}", icon="💥"); st.code(final_recs_text, language="text")

            # 성공적으로 파싱된 책 데이터가 있을 경우에만 화면에 카드 형태로 표시
            if books_data_from_ai:
                if intro_text_from_ai and books_data_from_ai : st.markdown("---") # 구분을 위한 선
                
                st.markdown(f"<h3 class='centered-subheader' style='margin-top:30px; margin-bottom:15px;'>🧚 도도가 최종 추천하는 책들이에요! ({len(books_data_from_ai)}권)</h3>", unsafe_allow_html=True)

                for book_data in books_data_from_ai: # 최대 3권이 올 것으로 예상
                    if not isinstance(book_data, dict): continue # 안전장치

                    with st.container(border=True):
                        title = book_data.get("title", "제목 없음"); author = book_data.get("author", "저자 없음")
                        publisher = book_data.get("publisher", "출판사 정보 없음")
                        year = book_data.get("year", "출판년도 없음"); isbn = book_data.get("isbn")
                        reason = book_data.get("reason", "추천 이유 없음")

                        st.markdown(f"<h4 class='recommendation-card-title'>{title}</h4>", unsafe_allow_html=True)
                        st.markdown(f"<span class='book-meta'>**저자:** {author} | **출판사:** {publisher} | **출판년도:** {year}</span>", unsafe_allow_html=True)
                        if isbn: st.markdown(f"<span class='book-meta'>**ISBN:** `{isbn}`</span>", unsafe_allow_html=True)
                        st.markdown(f"<div class='reason'>{reason}</div>", unsafe_allow_html=True)

                        # 학교 도서관 소장 여부 확인 (수정된 로직)
                        gemini_isbn_str = book_data.get("isbn") 
                        gemini_title = book_data.get("title", "제목 없음") 
                        gemini_author_str = book_data.get("author", "저자 없음") # book_data의 author는 Gemini가 생성한 문자열

                        current_book_lib_info = {} # 현재 책의 최종 도서관 검색 결과를 저장할 변수
                        found_in_lib_flag = False
                        match_description = "" # 매칭 성공 시 설명

                        if gemini_isbn_str: # Gemini가 ISBN을 제공했다면
                            clean_gemini_isbn = "".join(filter(lambda x: x.isdigit() or x.upper() == 'X', str(gemini_isbn_str)))
                            if len(clean_gemini_isbn) in [10, 13]: # 유효한 길이의 ISBN인지 확인
                                isbn_search_res = find_book_in_library_by_isbn(clean_gemini_isbn)
                                if isbn_search_res.get("found_in_library"):
                                    current_book_lib_info = isbn_search_res
                                    found_in_lib_flag = True
                                    # ISBN으로 찾았을 때, 도서관 DB의 ISBN을 보여주는 것이 더 정확할 수 있습니다.
                                    match_description = f"(ISBN 일치: {current_book_lib_info.get('isbn', clean_gemini_isbn)})"
                                else: # ISBN으로 검색했지만 DB에 없거나, 검색 함수 내부 오류 발생 시
                                    current_book_lib_info = isbn_search_res # 검색 결과(오류 메시지 포함 가능) 저장
                            else: # 유효하지 않은 길이의 ISBN
                                current_book_lib_info = {"error": f"추천된 책의 ISBN '{gemini_isbn_str}' 형식이 올바르지 않아 검색할 수 없어요."}
                        else: # Gemini가 ISBN 정보를 제공하지 않은 경우
                            current_book_lib_info = {"error": "추천된 책에 ISBN 정보가 없어 ISBN으로 검색할 수 없어요."}

                        # ISBN으로 찾지 못했고 (found_in_lib_flag is False), 제목 정보가 있다면 제목/저자로 재시도
                        if not found_in_lib_flag and gemini_title != "제목 없음":
                            title_author_search_res = find_book_in_library_by_title_author(gemini_title, gemini_author_str)
                            if title_author_search_res.get("found_in_library"):
                                current_book_lib_info = title_author_search_res # 찾았으면 이 정보로 덮어쓰기
                                found_in_lib_flag = True
                                match_description = f"(제목/저자 일치. 소장본 ISBN: {current_book_lib_info.get('isbn', '정보없음')} - 추천된 판본과 다를 수 있음)"
                            else: # 제목/저자로도 못 찾았거나 오류 발생 시
                                # ISBN 검색 시 오류가 없었다면 (예: ISBN 자체가 없었거나, ISBN 검색은 성공했으나 못찾음)
                                # 제목/저자 검색 결과를 저장 (오류 메시지 포함 가능)
                                if not current_book_lib_info.get("error") or current_book_lib_info.get("found_in_library") == False : # ISBN검색이 '못찾음'으로 끝났을경우
                                    current_book_lib_info = title_author_search_res

                            # 최종 결과 표기
                        if found_in_lib_flag:
                            display_title = current_book_lib_info.get('title', gemini_title) # DB 제목 우선
                            display_status = current_book_lib_info.get('status', '정보 없음')
                            display_call_number = current_book_lib_info.get('call_number', '정보 없음')
                            status_html = f"<div class='library-status-success'>🏫 <strong>우리 학교 도서관 소장!</strong> {match_description} ✨<br>&nbsp;&nbsp;&nbsp;- 청구기호: {display_call_number}<br>&nbsp;&nbsp;&nbsp;- 소장 도서명: {display_title}<br>&nbsp;&nbsp;&nbsp;- 상태: {display_status}</div>"
                            st.markdown(status_html, unsafe_allow_html=True)
                        elif current_book_lib_info.get("error"): # ISBN 형식이 잘못되었거나, 검색 함수 자체에서 오류 메시지를 반환했을 경우
                            st.markdown(f"<div class='library-status-warning'>⚠️ {current_book_lib_info.get('error')}</div>", unsafe_allow_html=True)
                        else: # 모든 방법으로 찾아봤지만, 최종적으로 도서관에서 해당 책을 찾지 못한 경우
                            st.markdown("<div class='library-status-info'>😿 아쉽지만 이 책은 현재 학교 도서관 목록에 없어요.</div>", unsafe_allow_html=True)

            # 최종적으로 추천된 책이 없고, AI가 오류 메시지도 아닌 일반 텍스트만 반환했을 경우 (마커 없이)
            # 이 경우는 위에서 한번 처리되었지만, 최후의 보루로 AI 응답을 보여줄 수 있음.
            # (단, "AI 요정님 호출 중 오류" 등 이미 처리된 오류 메시지는 제외)
            elif not ("AI 요정님 호출 중 오류" in final_recs_text or \
                      "AI 모델이 준비되지 않았어요" in final_recs_text or \
                      "콘텐츠 안전 문제일 수 있어요" in final_recs_text or \
                      (intro_text_from_ai and ("카카오에서 책을 찾지 못했어요" in intro_text_from_ai or "추천할 만한 책을 찾지 못했나 봐요" in intro_text_from_ai or "최종 추천할 만한 책을 고르지 못했나 봐요" in intro_text_from_ai)) ) and \
                      not intro_text_from_ai.strip() and not books_data_from_ai: # books_data_from_ai가 비어있을 때
                # 위에서 마커를 찾지 못했을 때 이미 전체 final_recs_text를 보여줬으므로, 여기서는 중복 표시 안 함.
                # st.markdown("---")
                # with st.container(border=True):
                # st.markdown("도도 요정님의 답변:")
                # st.markdown(final_recs_text)
                # st.caption("도도 요정님의 답변에서 개별 책 정보를 정확히 추출하지 못했어요.")
                pass # 이미 마커 부재 시 처리됨.

# 앱 실행 시 최초 한 번만 실행될 부분 (예: 환영 메시지 등) - 필요시 추가
# if not st.session_state.get('app_already_run_once_for_welcome_message', False):
#    st.toast("도서관 요정 도도가 여러분을 기다리고 있었어요! 헤헷 😊")
#    st.session_state.app_already_run_once_for_welcome_message = True
