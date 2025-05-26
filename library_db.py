# library_db.py

import sqlite3
import csv
import os

# DB 파일 경로 (chatbot_app.py와 같은 폴더)
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

    # 기존 데이터 모두 삭제 후 새로 로드
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

def find_book_in_library_by_isbn(isbn_query):
    """
    주어진 ISBN(여러 개/복합 형태 포함 가능)으로 학교 도서관 DB에서 책을 검색합니다.
    - ISBN은 반드시 clean_isbn() 함수로 정규화하여 비교 (비교오류 100% 방지)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # isbn_query에서 하이픈, 공백, 대소문자X 모두 제거하여 복수 후보화
    possible_isbns = [clean_isbn(x) for x in isbn_query.replace('-', ' ').split()]
    possible_isbns = [x for x in possible_isbns if x]

    # DB 내 모든 ISBN을 불러와서 클린값과 비교 (속도에 영향 없음)
    cursor.execute("SELECT isbn, title, author, publisher, call_number, status FROM books")
    books = cursor.fetchall()
    for book in books:
        db_isbn = clean_isbn(book[0])
        if db_isbn in possible_isbns:
            conn.close()
            return {
                "isbn": book[0], "title": book[1], "author": book[2],
                "publisher": book[3], "call_number": book[4], "status": book[5],
                "found_in_library": True
            }
    conn.close()
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
    # 테스트용 ISBN (library_books.csv에 있는 ISBN으로 테스트!)
    test_isbn_found = "9788996991342"  # 예: '미움받을 용기'
    test_isbn_not_found = "1234567890"

    book_info = find_book_in_library_by_isbn(test_isbn_found)
    if book_info["found_in_library"]:
        print(f"✅ '{test_isbn_found}' 책 찾음!: {book_info['title']} (청구기호: {book_info['call_number']})")
    else:
        print(f"❌ '{test_isbn_found}' 책 없음.")

    book_info = find_book_in_library_by_isbn(test_isbn_not_found)
    if book_info["found_in_library"]:
        print(f"✅ '{test_isbn_not_found}' 책 찾음!: {book_info['title']}")
    else:
        print(f"❌ '{test_isbn_not_found}' 책 없음.")

    print("\n🏫 학교 도서관 DB 설정 및 테스트 완료!")
