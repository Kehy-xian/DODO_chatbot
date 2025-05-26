# DODO_chatbot
## 🛠️ 설치 및 실행 방법

1. **필수 패키지 설치**
    ```bash
    pip install -r requirements.txt
    ```

2. **API 키 환경변수(.env) 파일 작성**
    ```
    GEMINI_API_KEY=your-gemini-api-key
    KAKAO_REST_API_KEY=your-kakao-api-key
    ```

3. **앱 실행**
    ```bash
    streamlit run chatbot_app.py
    ```

---

## ⚙️ 환경/엔진 안내 (사이드바에 표시됨)

- **AI 모델:** `gemini-2.0-flash-lite` (기본값, 1.5-pro 등 대체 가능)
- **분당 요청 수(RPM):** 약 30회 (모델별 차이)
- **일일 요청 수(RPD):** 약 1,500회 (모델별 차이)
- **동시 사용 예상:** 7~15명 (무료 등급 기준, 상황에 따라 상이)

> *실제 할당량은 Google/Kakao 정책에 따라 달라질 수 있습니다.*

---

## 👤 연락처 / 피드백

- **총괄 디렉터:** 꾸물
- **문의:** [zambi23@gmail.com](mailto:zambi23@gmail.com)
- **블로그:** [꾸물책장](https://blog.naver.com/snailslowclub)

---

## 💡 참고 및 유의사항

- AI의 추천은 참고용입니다. 실제로 책을 선택할 때는 반드시 추가 검증(책 소개, 평점, 서평 등)을 확인해주세요.
- 추천 결과는 Kakao Book API의 실제 검색 결과와 도서관 소장 데이터에 따라 달라질 수 있습니다.
- 학교/기관 내 도서관 소장 도서 DB 연동(옵션) 지원

---

## 📝 LICENSE

MIT License (수정 및 재배포 자유, 단 상업적 사용 시 반드시 문의)
