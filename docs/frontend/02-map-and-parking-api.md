# 지도·주소·주차장 API 연결

> 확인일: 2026-08-22
>
> 상태: Kakao JavaScript SDK 연결 코드를 구현했다. JavaScript 키와 SDK 도메인은 확인됐고, Kakao Developers의 카카오맵 API 활성화가 남았다.

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

Kakao Developers에서 다음 두 설정을 모두 완료해야 한다.

1. **앱 → 플랫폼 키 → JavaScript 키 → JavaScript SDK 도메인**에 `http://localhost:5173`, `http://127.0.0.1:5173`, 실제 배포 도메인을 등록한다.
2. **카카오맵 → 사용 설정 → 상태**를 `ON`으로 켠다.

Vite의 `VITE_` 환경변수는 브라우저 번들에 포함되므로 비밀키 저장소가 아니다. 여기에 REST API 키나 서버 비밀키를 넣지 않는다.

## 키가 없을 때의 폴백

`data/processed/gyeongbuk_parking_seed.csv`의 원천 JSON에서 좌표가 있는 경북 주차장 1,986건을 `frontend/public/data/gyeongbuk-parking.json`으로 생성한다.

```bash
node scripts/build_frontend_parking_catalog.mjs
```

이 폴백은 주소·주차장명·시군명을 문자열 검색하고, 브라우저 현재 위치를 허용하면 Haversine 거리순으로 정렬한다. 외부 API 장애 때도 로우파이 상호작용을 확인하기 위한 것이며 주소 정규화 API를 대체하지 않는다.

## 화면에 표시되는 주차장 출처

| 화면 배지 | 원천 | 범위와 한계 |
| --- | --- | --- |
| `좌표 주차장 1,986건` | 공공데이터포털 `전국주차장정보표준데이터`의 경북 2,010건 중 좌표 보유 행 | 공영·민영 표준 등록 자료. 안전 대피 장소나 실시간 여석으로 검증되지 않음 |
| `Kakao 실시간 검색` | Kakao `Places.keywordSearch` 응답 | 검색 시점의 장소 결과 최대 15건. 공공주차장으로 한정되지 않으며 Waterpark 안전 판정과 무관 |

초기 화면은 공공데이터 1,986건을 기본으로 사용하고, Kakao 키와 도메인이 정상이며 사용자가 주소를 검색했을 때만 Kakao 장소 결과로 전환한다.

## 2026-08-22 실제 연결 점검

- `.env`의 32자 JavaScript 키 로딩과 production build는 정상이다.
- 최초 점검에서는 `http://localhost:5173`과 `http://127.0.0.1:5173` 모두 HTTP `401 domain mismatched`였다.
- JavaScript SDK 도메인 등록 후 재점검에서는 도메인 오류가 사라지고 HTTP `403`과 `App(Waterpark) disabled OPEN_MAP_AND_LOCAL service.` 응답을 받았다.
- 이는 키와 호출 도메인은 인식됐지만 **카카오맵 → 사용 설정 → 상태**가 활성화되지 않았음을 뜻한다. 공식 안내상 2026-07-21부터 카카오맵 API 사용 전에 이 설정을 `ON`으로 켜야 한다.
- 카카오맵 사용 설정 후 SDK 응답 HTTP `200`, 실제 지도 DOM, 주소 검색 결과의 `Kakao 실시간 검색` 배지, 브라우저 오류 로그를 다시 확인한다.

## 2026-08-22 유료 사용 구조

2026-07-21부터 개발자 계정에서 **첫 번째로 카카오맵 API를 활성화한 앱에만 무료 쿼터**가 제공된다. Waterpark가 두 번째 이후 활성화 앱이면 비즈월렛 연결과 유료 API 사용 설정이 필요하고, 무료 구간 없이 사용량 기준으로 과금되는 것으로 공식 문서에 안내돼 있다.

| Waterpark 현재 호출 | 공식 단가(부가세 별도) | 호출 시점 |
| --- | ---: | --- |
| 지도 Web(JavaScript) SDK | 0.1원/건 | 페이지에서 Kakao 지도를 불러올 때 |
| 주소로 좌표 변환 | 0.5원/건 | 검색어를 기준 좌표로 변환할 때 |
| 키워드로 장소 검색 | 2원/건 | 기준 좌표 주변의 `주차장`을 검색할 때 |

현재 구현의 단순 추정치는 다음과 같다.

```text
페이지 로드 1회 + 주소 검색 1회
= 0.1원 + 0.5원 + 2원
= 2.6원(부가세 별도), 약 2.86원(부가세 포함)
```

실제 청구액은 각 API의 실제 호출 횟수로 계산한다. 한 페이지에서 검색만 반복하면 지도 SDK 로드 비용은 매 검색마다 발생하지 않을 수 있으므로, 아래 금액은 보수적으로 `방문 1회당 검색 1회`를 가정한 예시다.

| 방문·검색 수 | 부가세 포함 단순 추정 |
| ---: | ---: |
| 100회 | 약 286원 |
| 1,000회 | 약 2,860원 |
| 10,000회 | 약 28,600원 |

비용을 줄일 때는 공공데이터 1,986건의 로컬 검색을 기본으로 유지하고 Kakao 장소 검색을 사용자가 명시적으로 검색할 때만 호출한다. 주소 기준 거리 정렬이 필요하지 않은 화면은 주소 변환 호출을 생략할 수 있다. 해커톤 데모 단계에서는 자동 반복 호출·검색어 입력 중 호출을 피하고, 제출 전에 [통계 → 유료 사용량]과 [유료 API → 유료 API 사용 내역]을 확인한다.

유료 사용 절차는 `비즈월렛 생성 → 결제 카드 등록 → 앱과 비즈월렛 연결 → 유료 API 사용 설정` 순서다. 월별 사용량과 예상 금액을 확인할 수 있고, 합계에 부가세 10%가 더해져 다음 달 1일 오전 1시경 자동 결제된다.

## 공식 출처

| 출처 | 확인 내용 | 확인일 |
| --- | --- | --- |
| [Kakao Developers 카카오맵 이해하기](https://developers.kakao.com/docs/ko/kakaomap/common) | 카카오맵 API 활성화 경로, JavaScript 키·SDK 도메인, 2026-07-21 이후 무료 쿼터 정책 | 2026-08-22 |
| [Kakao Developers 쿼터](https://developers.kakao.com/docs/ko/getting-started/quota) | 무료 쿼터와 지도 SDK·주소 변환·장소 검색 단가 | 2026-08-22 |
| [Kakao Developers 유료 API](https://developers.kakao.com/docs/ko/app-setting/paid-api) | 비즈월렛 연결, 유료 사용 설정, 사용량 확인, 부가세와 결제 시점 | 2026-08-22 |
| [Kakao 지도 Web API 가이드](https://apis.map.kakao.com/web/guide/) | JavaScript 키, SDK 도메인 등록, WGS84 위경도 | 2026-08-22 |
| [Kakao 지도 Web API 문서](https://apis.map.kakao.com/web/documentation/) | `Geocoder.addressSearch`, `Places.keywordSearch`, 거리순 정렬 | 2026-08-22 |
| [키워드 장소 검색 예제](https://apis.map.kakao.com/web/sample/keywordBasic/) | 검색 결과 Marker 표시 방식 | 2026-08-22 |
| [전국주차장정보표준데이터](https://www.data.go.kr/data/15012896/standard.do) | 경북 공영주차장 폴백 원천 | 2026-08-22 |
