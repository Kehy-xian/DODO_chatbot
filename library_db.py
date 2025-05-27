import sqlite3
import csv
import os

DB_PATH = "school_library.db"
# books_cache = []

def create_library_table():
    """학교 도서관 책 정보를 저장할 테이블을 생성합니다."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            isbn TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT,
            publisher TEXT,
            call_number TEXT,
            publication_year TEXT,
            description TEXT,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()
    print(f"📚 '{DB_PATH}'에 'books' 테이블 준비 완료 (또는 이미 존재함)!")

def load_csv_to_library_db(csv_file_path):
    """CSV 파일에서 도서 정보를 읽어와 DB에 저장합니다."""
    if not os.path.exists(csv_file_path):
        print(f"이런! CSV 파일 '{csv_file_path}'을 찾을 수 없어요. 경로를 확인해주세요!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM books")
    print("기존 도서 데이터를 모두 삭제했습니다. (새로 로드 준비)")

    try:
        with open(csv_file_path, mode='r', encoding='utf-8-sig') as file:
            csv_reader = csv.DictReader(file)
            books_to_insert = []
            for row in csv_reader:
                books_to_insert.append((
                    row.get('isbn', '').strip(),
                    row.get('title', '').strip(),
                    row.get('author', ''),
                    row.get('publisher', ''),
                    row.get('call_number', ''),
                    row.get('publication_year', ''),
                    row.get('description', ''),
                    row.get('status', '소장중') # 기본값을 '소장중'으로 하는 것이 좋아 보입니다.
                ))
            cursor.executemany("""
                INSERT OR IGNORE INTO books (isbn, title, author, publisher, call_number, publication_year, description, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, books_to_insert) # 중복 ISBN 로드 시 무시하도록 INSERT OR IGNORE 사용
            conn.commit()
            print(f"🎉 CSV 파일 '{csv_file_path}'에서 {len(books_to_insert)}건의 도서 정보를 DB에 성공적으로 로드했어요!")
    except FileNotFoundError:
        print(f"😿 이런! CSV 파일 '{csv_file_path}'을 찾을 수 없어요. 경로를 확인해주세요!")
    except Exception as e:
        print(f"😿 CSV 로드 중 오류 발생!: {e}")
    finally:
        conn.close()

def clean_isbn(isbn):
    """ISBN의 하이픈, 공백, 대소문자 X 등 불필요한 문자 모두 제거"""
    if not isbn: return ''
    return ''.join(filter(lambda x: x.isdigit() or x.upper() == 'X', str(isbn))).upper()

def normalize_text_for_matching(text_str):
    """검색 및 비교를 위해 텍스트를 정규화합니다 (소문자, 공백/일부 특수문자 제거)."""
    if not isinstance(text_str, str):
        return ""
    processed_text = text_str.lower()
    # 제거할 일반적인 특수문자 및 공백 처리 (필요에 따라 확장)
    for char_to_remove in [" ", "-", ":", ",", ".", "'", '"', "[", "]", "(", ")", "/", "\\", "&", "#", "+", "_", "~", "!", "?", "*"]:
        processed_text = processed_text.replace(char_to_remove, "")
    return processed_text

def isbn10_to_isbn13(isbn10):
    """ISBN-10을 ISBN-13으로 변환 (문자열 반환, 하이픈 등 제거 자동)"""
    isbn10 = clean_isbn(isbn10)
    if len(isbn10) != 10: return None
    core = "978" + isbn10[:-1]
    s = 0
    for i, c in enumerate(core):
        s += int(c) * (1 if i % 2 == 0 else 3)
    check = (10 - (s % 10)) % 10
    return core + str(check)

def isbn13_to_isbn10(isbn13):
    """ISBN-13을 ISBN-10으로 변환 (978 프리픽스만 변환 가능)"""
    isbn13 = clean_isbn(isbn13)
    if not isbn13.startswith("978") or len(isbn13) != 13: return None
    core = isbn13[3:-1]
    s = 0
    for i, c in enumerate(core):
        s += int(c) * (10 - i)
    check = 11 - (s % 11)
    if check == 10:
        check_digit = "X"
    elif check == 11:
        check_digit = "0"
    else:
        check_digit = str(check)
    return core + check_digit

def all_isbn_versions(isbn):
    """주어진 ISBN 문자열에서 ISBN-10/13 가능한 모든 버전 세트로 반환"""
    isbn = clean_isbn(isbn)
    versions = set()
    if len(isbn) == 10:
        versions.add(isbn)
        v13 = isbn10_to_isbn13(isbn)
        if v13: versions.add(v13)
    elif len(isbn) == 13:
        versions.add(isbn)
        v10 = isbn13_to_isbn10(isbn)
        if v10: versions.add(v10)
    return versions

def is_isbn_match(query_isbn, db_isbn):
    """입력 ISBN과 DB ISBN이 10/13 버전 포함하여 일치하는지 판단"""
    if not query_isbn or not db_isbn: return False
    return len(all_isbn_versions(query_isbn).intersection(all_isbn_versions(db_isbn))) > 0

def find_book_in_library_by_isbn(isbn_query):
    """
    주어진 ISBN(숫자/문자/혼합, 10/13자리, 하이픈/공백 포함 가능)으로 도서관 DB에서 책을 검색.
    - ISBN-10/ISBN-13 모두 상호 변환해서 완벽히 매칭(섞여 있어도 문제 없음)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # publication_year, description 컬럼도 함께 SELECT 하도록 수정 (필요시)
    cursor.execute("SELECT isbn, title, author, publisher, call_number, status, publication_year, description FROM books")
    books_from_db = cursor.fetchall() # 변수명 변경 (books_cache와의 혼동 방지)
    conn.close()

    q_isbns = all_isbn_versions(isbn_query)
    if not q_isbns: return {"found_in_library": False, "error": "유효하지 않거나 빈 ISBN으로 검색 요청"}

    for book_tuple in books_from_db:
        db_isbn_raw = book_tuple[0]
        # all_isbn_versions 함수는 이미 내부적으로 clean_isbn을 호출하므로, db_isbn_raw를 바로 사용 가능
        db_isbns = all_isbn_versions(db_isbn_raw)
        if q_isbns & db_isbns: # set의 교집합(&) 연산자로 일치하는 버전이 있는지 확인
            return {
                "isbn": book_tuple[0], "title": book_tuple[1], "author": book_tuple[2],
                "publisher": book_tuple[3], "call_number": book_tuple[4], "status": book_tuple[5],
                "publication_year": book_tuple[6], "description": book_tuple[7], # 추가된 필드 반환
                "found_in_library": True
            }
    return {"found_in_library": False, "error": f"DB에서 ISBN '{isbn_query}'(검색 시도 버전: {q_isbns})를 찾을 수 없음"}

def find_book_in_library_by_title_author(title_query, author_query):
    """주어진 책 제목과 저자로 DB에서 책을 찾아 반환합니다."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # publication_year, description 컬럼도 함께 SELECT 하도록 수정
    cursor.execute("SELECT isbn, title, author, publisher, call_number, status, publication_year, description FROM books")
    books_from_db = cursor.fetchall()
    conn.close()
    
    normalized_title_query = normalize_text_for_matching(title_query)
    normalized_author_query = normalize_text_for_matching(author_query)

    if not normalized_title_query:
        return {"found_in_library": False, "error": "검색할 도서명이 제공되지 않았습니다."}

    matched_books = []
    for book_tuple in books_from_db:
        db_isbn_raw = book_tuple[0] 
        db_title_raw = book_tuple[1]
        db_author_raw = book_tuple[2]
        
        normalized_db_title = normalize_text_for_matching(db_title_raw)
        normalized_db_author = normalize_text_for_matching(db_author_raw)
        
        title_match = False
        if normalized_title_query and normalized_db_title and \
           (normalized_title_query in normalized_db_title or normalized_db_title in normalized_title_query):
            title_match = True
        
        author_match = False
        if not author_query: 
            author_match = True
        elif normalized_author_query and normalized_db_author and \
             (normalized_author_query in normalized_db_author or normalized_db_author in normalized_author_query):
            author_match = True
            
        if title_match and author_match:
            matched_books.append({
                "isbn": db_isbn_raw, 
                "title": db_title_raw,
                "author": db_author_raw,
                "publisher": book_tuple[3],
                "call_number": book_tuple[4],
                "status": book_tuple[5],
                "publication_year": book_tuple[6], # 추가된 필드 반환
                "description": book_tuple[7],      # 추가된 필드 반환
                "found_in_library": True,
                "match_type": "title_author_match"
            })
            
    if matched_books:
        return matched_books[0] # 간단히 첫 번째 찾은 책 반환
        
    return {"found_in_library": False, "title_searched": title_query, "author_searched": author_query}

# --- 직접 실행시 DB 초기화 및 테스트 코드 (원하는 경우만 사용) ---
if __name__ == "__main__":
    print("🏫 학교 도서관 DB 설정을 시작합니다...")
    create_library_table()

    csv_filename = "library_books.csv"
    script_dir = os.path.dirname(__file__)
    csv_file_full_path = os.path.join(script_dir, csv_filename)

    load_csv_to_library_db(csv_file_full_path)

    print("\n--- DB 테스트 ---")
    test_isbn_list = [
        "9788996991342",
        "8996991341",
        "9788996991342",
        "1234567890",
        "9791198363503", # 아몬드 ISBN
        "9788954650212"  # 세계를 건너 너에게 갈게 ISBN
    ]
    for test_isbn in test_isbn_list:
        book_info = find_book_in_library_by_isbn(test_isbn)
        if book_info["found_in_library"]:
            print(f"✅ [ISBN Test] '{test_isbn}' 책 찾음!: {book_info['title']} (청구기호: {book_info['call_number']})")
        else:
            print(f"❌ [ISBN Test] '{test_isbn}' 책 없음. 오류: {book_info.get('error', '정보 없음')}")

    print("\n--- 제목/저자 테스트 ---")
    # 아래는 예시입니다. 실제 library_books.csv에 있는 제목/저자로 테스트해보세요.
    test_title_author_list = [
        ("아몬드", "손원평"),                      # 아몬드 (판본 다를 수 있음)
        ("세계를 건너 너에게 갈게", "이꽃님"),        # 세계를 건너 (판본 다를 수 있음)
        ("미움받을 용기", "기시미 이치로"),          # 미움받을 용기
        ("존재하지 않는 책 제목", "존재하지 않는 저자") # 없는 책
    ]
    for title, author in test_title_author_list:
        book_info = find_book_in_library_by_title_author(title, author)
        if book_info["found_in_library"]:
            print(f"✅ [Title/Author Test] '{title} ({author})' 책 찾음!: {book_info['title']} (ISBN: {book_info['isbn']})")
        else:
            print(f"❌ [Title/Author Test] '{title} ({author})' 책 없음. 오류: {book_info.get('error', '정보 없음')}")
            
    print("\n🏫 학교 도서관 DB 설정 및 테스트 완료!")
