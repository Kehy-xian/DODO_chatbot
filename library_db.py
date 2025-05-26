# library_db.py

import sqlite3
import csv
import os

# 데이터베이스 파일 경로 (chatbot_app.py와 같은 위치에 생성될 거예요)
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
    """CSV 파일에서 도서 정보를 읽어와 DB에 저장합니다. (기존 데이터는 모두 삭제 후 새로 로드)"""
    if not os.path.exists(csv_file_path):
        print(f"이런! CSV 파일 '{csv_file_path}'을 찾을 수 없어요. 경로를 확인해주세요!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 기존 데이터를 모두 지우고 새로 로드 (필요에 따라 다른 전략 사용 가능)
    cursor.execute("DELETE FROM books")
    print("기존 도서 데이터를 모두 삭제했습니다. (새로 로드 준비)")

    try:
        with open(csv_file_path, mode='r', encoding='utf-8-sig') as file: # utf-8-sig는 BOM이 있는 UTF-8 파일도 잘 읽어요
            csv_reader = csv.DictReader(file)
            books_to_insert = []
            for row in csv_reader:
                # CSV 컬럼 이름과 DB 컬럼 이름이 일치하도록 조정 필요
                # 예시: CSV에 'ISBN13' 컬럼이 있다면 row.get('ISBN13') 사용
                books_to_insert.append((
                    row.get('isbn', '').strip(), # ISBN은 공백 제거
                    row.get('title', '').strip(),
                    row.get('author', ''),
                    row.get('publisher', ''),
                    row.get('call_number', ''),
                    row.get('publication_year', ''),
                    row.get('description', ''),
                    row.get('status', '소장중') # CSV에 status 없으면 기본값
                ))
            
            # 중복 ISBN이 있을 경우 무시하고 넘어가도록 (또는 다른 처리 가능)
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

def find_book_in_library_by_isbn(isbn_query):
    """주어진 ISBN으로 학교 도서관 DB에서 책을 검색합니다."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # ISBN은 여러 형식이 있을 수 있으므로, DB에 저장된 형식과 맞춰 검색
    # Kakao API는 ISBN10과 ISBN13을 공백으로 구분하여 제공할 수 있음
    # 여기서는 DB에 단일 ISBN이 저장되어 있다고 가정
    # 만약 DB에도 복합 ISBN이 있다면, LIKE 검색 등을 활용해야 함
    
    # 입력된 isbn_query가 여러 ISBN을 포함할 수 있으므로, 각각 시도
    possible_isbns = isbn_query.replace('-', '').split() # 하이픈 제거 및 공백으로 분리
    
    for isbn_single in possible_isbns:
        if not isbn_single: continue # 빈 문자열 스킵
        
        # 정확히 일치하는 ISBN 검색
        cursor.execute("SELECT isbn, title, author, publisher, call_number, status FROM books WHERE REPLACE(isbn, '-', '') = ?", (isbn_single,))
        book = cursor.fetchone()
        if book:
            conn.close()
            # 결과를 딕셔너리 형태로 반환하면 사용하기 편해요
            return {
                "isbn": book[0], "title": book[1], "author": book[2],
                "publisher": book[3], "call_number": book[4], "status": book[5],
                "found_in_library": True
            }
            
        # (선택적) 부분 일치 검색 (예: 13자리 ISBN의 핵심부만 일치하는지 등)
        # cursor.execute("SELECT isbn, title, author, call_number, status FROM books WHERE isbn LIKE ?", (f"%{isbn_single}%",))
        # book = cursor.fetchone()
        # if book: ...
            
    conn.close()
    return {"found_in_library": False} # 못 찾으면 False 반환

# --- 이 파일을 직접 실행했을 때 DB를 설정하도록 하는 부분 ---
if __name__ == "__main__":
    print("🏫 학교 도서관 DB 설정을 시작합니다...")
    create_library_table() # 테이블이 없으면 생성

    # CSV 파일 이름 (프로젝트 폴더 내에 있다고 가정)
    # 실제 파일 이름으로 변경해주세요!
    csv_filename = "library_books.csv" 
    
    # CSV 파일의 전체 경로를 구성합니다.
    # 이 스크립트(library_db.py)가 있는 폴더를 기준으로 경로를 찾습니다.
    script_dir = os.path.dirname(__file__) # 현재 스크립트가 있는 디렉토리
    csv_file_full_path = os.path.join(script_dir, csv_filename)
    
    load_csv_to_library_db(csv_file_full_path) # CSV 데이터 로드

    print("\n--- DB 테스트 ---")
    # 테스트용 ISBN (실제 library_books.csv에 있는 ISBN으로 바꿔서 테스트해보세요)
    test_isbn_found = "9788996991342" # '미움받을 용기' ISBN13
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