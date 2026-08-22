# 지도·주소·주차장 API 연결

> 확인일: 2026-08-22
>
> 상태: Kakao JavaScript SDK 연결 코드를 구현했다. 실제 외부 호출은 프로젝트 JavaScript 키 등록 후 활성화된다.

## 선택

Kakao 지도 JavaScript API의 `services` 라이브러리를 사용한다. 브라우저에서 다음 흐름을 실행하므로 현재 단계에서는 별도 서버가 필요 없다.

```text
사용자 주소 입력
→ Geocoder.addressSearch로 기준 좌표 확인
→ Places.keywordSearch("주차장")
→ 거리순 최대 15개 표시
→ 지도 Marker와 목록 동기화
```

Kakao 공식 문서상 JavaScript SDK는 JavaScript 키와 등록된 도메인이 필요하다. REST API 키를 브라우저 코드에 넣지 않는다.

## 설정

```bash
cd frontend
cp .env.example .env
```

```dotenv
VITE_KAKAO_MAP_APP_KEY=발급받은_JavaScript_키
```

Kakao Developers에서 `http://localhost:5173`과 실제 배포 도메인을 JavaScript SDK 도메인으로 등록해야 한다. Vite의 `VITE_` 환경변수는 브라우저 번들에 포함되므로 비밀키 저장소가 아니다. 여기에 REST API 키나 서버 비밀키를 넣지 않는다.

## 키가 없을 때의 폴백

`data/processed/gyeongbuk_parking_seed.csv`의 원천 JSON에서 좌표가 있는 경북 주차장 1,986건을 `frontend/public/data/gyeongbuk-parking.json`으로 생성한다.

```bash
node scripts/build_frontend_parking_catalog.mjs
```

이 폴백은 주소·주차장명·시군명을 문자열 검색하고, 브라우저 현재 위치를 허용하면 Haversine 거리순으로 정렬한다. 외부 API 장애 때도 로우파이 상호작용을 확인하기 위한 것이며 주소 정규화 API를 대체하지 않는다.

## 공식 출처

| 출처 | 확인 내용 | 확인일 |
| --- | --- | --- |
| [Kakao 지도 Web API 가이드](https://apis.map.kakao.com/web/guide/) | JavaScript 키, SDK 도메인 등록, WGS84 위경도 | 2026-08-22 |
| [Kakao 지도 Web API 문서](https://apis.map.kakao.com/web/documentation/) | `Geocoder.addressSearch`, `Places.keywordSearch`, 거리순 정렬 | 2026-08-22 |
| [키워드 장소 검색 예제](https://apis.map.kakao.com/web/sample/keywordBasic/) | 검색 결과 Marker 표시 방식 | 2026-08-22 |
| [전국주차장정보표준데이터](https://www.data.go.kr/data/15012896/standard.do) | 경북 공영주차장 폴백 원천 | 2026-08-22 |
