import sqlite3
import csv
import os

DB_PATH = "school_library.db"

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
                    row.get('status', '소장중')
                ))
            cursor.executemany("""
                INSERT OR IGNORE INTO books (isbn, title, author, publisher, call_number, publication_year, description, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, books_to_insert)
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
    cursor.execute("SELECT isbn, title, author, publisher, call_number, status FROM books")
    books = cursor.fetchall()
    conn.close()

    # 검색어에서 가능한 모든 버전 추출
    q_isbns = all_isbn_versions(isbn_query)
    if not q_isbns: return {"found_in_library": False}

    for book in books:
        db_isbn = book[0]
        db_isbns = all_isbn_versions(db_isbn)
        if q_isbns & db_isbns:
            return {
                "isbn": book[0], "title": book[1], "author": book[2],
                "publisher": book[3], "call_number": book[4], "status": book[5],
                "found_in_library": True
            }
    return {"found_in_library": False}

# --- 직접 실행시 DB 초기화 및 테스트 코드 (원하는 경우만 사용) ---
if __name__ == "__main__":
    print("🏫 학교 도서관 DB 설정을 시작합니다...")
    create_library_table()  # 테이블 생성

    # CSV 파일 이름(같은 폴더에 있는 파일명!)
    csv_filename = "library_books.csv"
    script_dir = os.path.dirname(__file__)
    csv_file_full_path = os.path.join(script_dir, csv_filename)

    load_csv_to_library_db(csv_file_full_path)  # CSV 데이터 로드

    print("\n--- DB 테스트 ---")
    # 테스트용 ISBN (library_books.csv에 있는 ISBN10/13 중 아무거나!)
    test_isbn_list = [
        "9788996991342",  # 13자리
        "8996991341",     # 10자리
        "9788996991342",  # 13자리 (중복)
        "1234567890"      # 없는 번호
    ]
    for test_isbn in test_isbn_list:
        book_info = find_book_in_library_by_isbn(test_isbn)
        if book_info["found_in_library"]:
            print(f"✅ '{test_isbn}' 책 찾음!: {book_info['title']} (청구기호: {book_info['call_number']})")
        else:
            print(f"❌ '{test_isbn}' 책 없음.")

    print("\n🏫 학교 도서관 DB 설정 및 테스트 완료!")
