# Waterpark 리서치 및 의사결정 로그

> 프로젝트가 진행되면서 조사 결과와 결정 사항을 계속 갱신한다.

## 표기 규칙

- `FACT`: 공식 또는 1차 출처로 확인된 사실
- `NOTE`: 제공된 메모나 전사본에 있으나 추가 확인이 필요한 내용
- `OPEN`: 아직 조사하거나 결정하지 않은 내용
- `DECISION`: 팀이 확정한 선택

## 확정된 프로젝트 정보

| 상태 | 내용 | 근거 |
| --- | --- | --- |
| `DECISION` | 서비스명은 `Waterpark`다. | 사용자 결정 |
| `DECISION` | 경상북도 지하주차장 침수 위험 예측 및 차량 사전 대피 안내 서비스를 만든다. | 사용자 결정 및 팀 PRD |
| `DECISION` | 선택 트랙은 `Solve local challenges in Gyeongsangbuk-do using public data.`이다. | 사용자 결정 및 Hacker Dashboard |
| `FACT` | 최소 한 개 이상의 공공데이터를 사용해야 한다. | Hacker Dashboard 및 트랙 안내 |
| `FACT` | 최신 표시 심사 기준은 기술 완성도 25%, 공공부문 활용 가능성 25%, 혁신·차별성 20%, 지속가능성·영향 20%, 프로토타입 10%다. | 2026-08-22 Hacker Dashboard |
| `NOTE` | 전사·요약 자료에는 공공 가치 35%, 기술 25%, 혁신 25%, 지속가능성 15%, 프로토타입 +10%로 기록돼 있다. | 트랙 파트너 세션 전사 및 팀 메모 |

배점 충돌은 Hacker Dashboard를 기준으로 기록하며 최종 제출 시 공식 화면을 따른다.

## 현재 작업 범위

```text
전처리에 사용할 데이터 판별 및 전처리
→ 머신러닝
→ 백엔드 구축
→ 프론트엔드 전달
```

이보다 구체적인 데이터, 모델, 서버와 프론트엔드 설계는 아직 결정되지 않았다.

## 데이터 및 전처리 관련 미확정 사항

| ID | 내용 | 상태 |
| --- | --- | --- |
| DATA-001 | 침수흔적도·기상·건물·DEM·하천 후보의 공식 제공 경로 | `FACT` — 공식 제공 경로 확인, GIS건물통합정보·건축물대장 후보와 대체 건물·DSM 확보 |
| DATA-002 | 각 데이터의 필드, 형식, 단위와 공간·시간 해상도 | `NOTE` — 건물·강수·침수 명세 확인 및 건축물대장·Overture·Copernicus 실제 처리 완료, 최종 공간 조인 검증 필요 |
| DATA-003 | 경상북도 22개 시군 필터 후 행 수, 과거 이력과 결측률 | `NOTE` — 주차장 2,010행, 대체 건물 305,058행, 표고 304,929행, 건축물대장 표제부 43,681행 확인 |
| DATA-004 | 데이터 간 위치·시간 기준 결합 방법 | `NOTE` — 구조 분석 완료, CRS·연결 키 미확정 |
| DATA-005 | XGBoost 입력과 정답 데이터로 사용할 수 있는 항목 | `NOTE` — 구조상 가능, 라벨 품질·독립 사건 수 미확인 |
| DATA-006 | 데이터별 라이선스, 호출 제한과 재배포 조건 | `OPEN` — 일부 페이지 표기만 확인 |

상세 내용은 [데이터 수집 계획](./01-data-collection-plan.md)과 [전처리 및 XGBoost 적용 가능성](./02-preprocessing-and-xgboost-feasibility.md)에 기록했다.

## 2026-08-22 데이터 제공 형식 확인 결과

- 침수흔적도 공개 샘플 CSV에서 `FLDN_*` 필드와 WKT `POLYGON` 형식의 `GEOM`을 확인했다. 전체 데이터는 활용 신청형 페이지네이션 API다.
- 기상청 ASOS 시간자료의 공식 필드는 `STN`, `TM`, `RN`, `RN_DAY`, `RN_INT`이며 포항 ASOS 지점번호는 `138`이다.
- 건축물대장 표제부에는 지하층수와 용도 속성이 있지만 위도·경도는 확인되지 않았다. 위치는 GIS건물통합정보의 SHP Polygon과 연결해야 한다.
- 공공데이터포털의 수치표고성과내역은 DEM 셀 원본이 아니라 도엽 메타데이터다. 실제 DEM 래스터는 아직 확보하지 않았다.
- VWorld 국가기본도 하천중심선은 `EPSG:5179` SHP와 테이블 정의서로 제공되며 로그인이 필요하다.

## 2026-08-22 건물·강수·침수 소스 추가 확인 결과

- 상태: `FACT`와 `OPEN`을 항목별로 구분한다.
- VWorld GIS건물통합정보의 경북 `전체데이터(AL)` SHP 목록을 확인했다. 2026-08-22 표시 기준 최신 파일은 기준일 2026-08-09, 약 290MB다. `CH_D010`은 일간 변동분이므로 경북 전체 건물 기준표로 사용할 수 없다.
- VWorld 공식 컬럼 정의서의 `AL_D010`에는 GIS건물통합식별번호, PNU, 법정동·지번, 용도, 건물명·동명, 지상·지하층 수가 있다. SHP 대표점을 WGS84로 변환해 위도·경도를 만들 수 있다.
- 현재 건축물대장 OpenAPI는 [건축HUB 건축물대장정보 서비스](https://www.data.go.kr/data/15134735/openapi.do)다. 표제부에는 지하층 수와 옥내·옥외 주차 속성이 있고 층별개요는 `층구분코드=10`을 지하로 정의한다.
- `옥내 주차`와 `지하주차`는 동일하지 않다. 지하층 행의 주차장 용도를 확인할 수 있을 때 `confirmed`, 간접 근거만 있으면 `probable`, 근거 부족은 `unknown`으로 기록하는 규칙이 후보이다. 실제 파일 검증 전 확정 규칙은 아니다.
- 기상청 AWS 시간통계는 `TM`, `STN`, `RN_HR1`, `RN_DAY`를 제공하고 관측지점정보는 WGS84 위도·경도를 제공한다. 건물에는 해당 시각에 운영 중인 가까운 관측소 값을 연결하고 관측소 거리도 남겨야 한다.
- 기존 [행정안전부 침수흔적도](https://www.safetydata.go.kr/disaster-data/view?dataSn=108)는 WKT Polygon과 시작·종료시각을 제공한다. 새 심선·위선은 Polygon을 제공하지 않으며, 위선의 X·Y는 공식 답변상 `EPSG:3857`이다.
- 침수흔적도 중첩은 지표면 침수 양성의 대리 라벨이지 지하주차장 직접 침수 기록이 아니다. 자료 밖의 건물을 자동으로 비침수 `0`으로 만들 수 없다.
- 상세: [건물·강수·침수 데이터 소스 확인서](./04-building-rain-flood-source-verification.md)

## 2026-08-22 경상북도 전체 데이터 통합 실행 결과

- 상태: `FACT`
- 범위: 포항 파일럿이 아니라 경상북도 22개 시군 전체를 기본 데이터 수집 범위로 사용한다.
- 전국주차장정보표준데이터 공개 다운로드에서 18,879행을 확보했고, 주소의 경상북도 및 22개 시군명을 기준으로 2,010행을 추출했다.
- 경북 추출 결과 22개 시군이 모두 포함됐다. 위도·경도가 있는 행은 1,986개, 좌표 결측 행은 24개다.
- 주차구획수는 실시간 여석이 아니며, DEM·침수흔적·접근도로·기관 승인을 확인하기 전 안전 대피 주차장으로 판정하지 않는다.
- 침수흔적도 전체 API는 회원가입·활용 신청이 필요하고 샘플 다운로드는 첫 100건으로 제한된다.
- 국토지리정보원 DEM은 무료이나 국토정보플랫폼 로그인과 영역 지정 다운로드가 필요하다.
- 산출물: `data/processed/gyeongbuk_parking_seed.csv`, `data/processed/waterpark_gyeongbuk_integration.xlsx`
- 출처: [전국주차장정보표준데이터](https://www.data.go.kr/data/15012896/standard.do), [기존 침수흔적도](https://www.safetydata.go.kr/disaster-data/view?dataSn=108), [새 침수흔적도 위선](https://www.safetydata.go.kr/disaster-data/view?dataSn=3846), [국토지리정보원 DEM](https://www.data.go.kr/data/15059920/fileData.do)
- 확인일: 2026-08-22

## 2026-08-22 경상북도 건물·고도 실제 추출 결과

- 상태: `FACT` — 대체 공개 원천의 실제 다운로드·공간절단·표고 추출 완료. 공식 건축물대장 후보 수집도 이후 완료했지만, 이 Overture 건물 좌표와의 연결은 아직 하지 않았다.
- Overture Maps `2026-08-19.0` 릴리스에서 경북 경계상자 건물 634,311개와 행정경계를 내려받았다.
- `country=KR`, `region=KR-47`, `admin_level=1`, `class=land`, 명칭 `경상북도`인 행정경계로 건물 대표점을 절단해 305,058행을 만들었다.
- 경북 `admin_level=2` 시군 Polygon으로 22개 시군을 배정했으며 시군 결측은 0행이다.
- Copernicus DEM GLO-30 Public 2021의 30m DSM 타일 9개를 내려받아 304,929행에 표고를 붙였다. 표고 결측은 129행이다.
- 경북 전체 건물점 DSM 표고 중앙값은 약 64.61m다. 일부 해안 값은 -6.07m까지 있어 수직기준·해안 픽셀·DSM 오차 확인이 필요하다.
- 주변 대비 표고는 0.01도 격자 3×3 근방의 건물 대표점 DSM 최저값 대비 차이로 계산했다. HAND·지형 전체 최저값·침수심이 아니다.
- Overture의 지하층수 값은 경북에서 6행뿐이었다. 따라서 이 Overture 산출물 자체의 지하주차장 상태는 305,058행 모두 미상으로 보존했다.
- VWorld 연속수치지형도 건물 경북 파일은 `dsId=30162`, `fileNo=25`, 화면 표시 279MB로 확인했다. 비로그인 직접 호출은 0바이트였고 화면 스크립트도 로그인 여부를 검사한다.
- 건축HUB OpenAPI `15134735`는 `serviceKey`, `sigunguCd`, `bjdongCd`가 필수다. 당시에는 키가 없었으나 이후 같은 날 키와 GIS 원본을 확보해 다음 절의 후보 수집을 완료했다.
- 산출물: `data/processed/gyeongbuk_buildings_elevation.parquet`, `data/processed/gyeongbuk_buildings_elevation.csv.gz`, `outputs/gyeongbuk-buildings/waterpark_gyeongbuk_buildings_elevation.xlsx`
- 상세 문서: [경상북도 건물·고도 실제 추출 결과](./05-gyeongbuk-building-elevation-extraction.md)
- 출처: [Overture 공개 데이터](https://registry.opendata.aws/overture/), [Overture Python Client](https://docs.overturemaps.org/getting-data/overturemaps-py/), [Copernicus DEM 공개 데이터](https://registry.opendata.aws/copernicus-dem/), [VWorld 건물 데이터](https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?dsId=30162), [건축HUB API](https://www.data.go.kr/data/15134735/openapi.do)
- 확인일: 2026-08-22

## 2026-08-22 경상북도 건축물대장 API 수집 결과

- 상태: `FACT` — 건축HUB 표제부·층별개요 후보 범위 수집 완료.
- 입력 범위는 경북 GIS건물통합정보 `AL_D010_47_20251204`에서 지하층 수가 1 이상인 25,340행, 고유 PNU 21,240개다. 경북 전체 대장을 무조건 전수 호출한 결과는 아니다.
- 건축HUB 표제부 43,681행을 수집했고 지하층과 옥내주차가 함께 있는 관리건축물대장 PK 3,163개를 후보로 만들었다.
- 후보의 층별개요 26,921행을 수집했다. `층구분코드=10`, 면적 0 초과, 주용도명 또는 기타용도에 `주차장` 포함 조건으로 1,449개 관리건축물대장 PK를 `confirmed`로 분류했다.
- 지하층과 옥내주차는 있지만 층별개요에서 주차장을 확인하지 못한 1,714건은 `FALSE`가 아니라 미확인 후보로 남겼다.
- 건축물대장 API에는 위도·경도가 없다. 다음 공간 결합에서는 GIS의 PNU와 Polygon을 기준으로 같은 PNU의 여러 동·대장을 구분해야 한다.
- 전체 API 원응답과 CSV는 로컬 `data/raw/building-register/`, `data/processed/gyeongbuk-building-register/`에 저장하고 Git에서는 제외했다. 재현 스크립트, 500행 표본과 집계 manifest만 Git에 포함한다.
- 산출물 설명: [경상북도 건축물대장 수집 결과](../outputs/gyeongbuk-building-register/README.md)
- 출처: [건축HUB 건축물대장정보 API](https://www.data.go.kr/data/15134735/openapi.do), 경북 GIS건물통합정보 전체데이터
- 확인일: 2026-08-22

## 2026-08-22 프론트엔드 지도·주차장 검색 확인 결과

- 상태: `FACT` — Figma 노드 확인, React 로우파이 구현, Kakao 지도·주소·주차장 검색 실연결 완료.
- Figma 전체 `Lo-Fi` Canvas `20:7`에서 지도 홈 `117:510`과 내 차 위치 설정 `123:1610`을 구현 기준으로 선택했다.
- Kakao 지도 JavaScript SDK는 JavaScript 키와 등록 도메인이 필요하며, `services` 라이브러리에서 주소 검색과 장소 키워드 검색을 제공한다.
- React 앱은 주소를 좌표로 바꾼 뒤 `주차장`을 거리순 검색하는 흐름을 구현했다. 키가 없거나 호출이 실패하면 경북 공영주차장 좌표 보유 1,986건을 검색한다.
- Vercel `agent-skills`의 React 성능 기준과 최신 Web Interface Guidelines를 적용해 접근성, focus, 폼, 비동기 상태, safe-area, 긴 텍스트와 조건부 SDK 로딩을 확인했다.
- Kakao JavaScript 키의 SDK 도메인 등록 후 `domain mismatched` 오류는 해소됐다. 재호출은 HTTP `403`과 `App(Waterpark) disabled OPEN_MAP_AND_LOCAL service.`를 반환해 **카카오맵 → 사용 설정 → 상태 ON**이 추가로 필요하다.
- 카카오맵 설정 변경 뒤 같은 `.env` 키로 보낸 새 SDK 요청은 HTTP `401`과 `appKey is already deactivated`였다. 기존 브라우저 세션의 캐시된 SDK에서는 지도와 포항 주차장 15건 검색이 동작했으나, 캐시 없는 요청이 실패하므로 연결 완료로 판정하지 않는다. 활성 키 확인 또는 새 키 적용이 필요하다.
- 다른 계정에서 새 JavaScript 키를 발급하고 `localhost:5173`, `127.0.0.1:5173` SDK 도메인을 등록한 뒤 캐시 없는 SDK 요청 HTTP `200`을 확인했다.
- Vite 서버를 새 키로 재시작한 최종 점검에서 Kakao 지도만 렌더링됐고 폴백·지도 오류는 없었다. `경상북도 포항시` 검색은 `Kakao 실시간 검색`으로 전환되어 장소 15건을 표시했으며 브라우저 경고·오류는 0건이었다.
- Kakao 공식 문서상 2026-07-21부터 카카오맵 API 활성화가 필수이며, 개발자 계정에서 첫 번째로 활성화한 앱에만 무료 쿼터가 제공된다.
- 산출물: `frontend/`, `docs/frontend/`, `frontend/public/data/gyeongbuk-parking.json`
- 출처: [Kakao Developers 카카오맵 이해하기](https://developers.kakao.com/docs/ko/kakaomap/common), [Kakao 지도 Web API 가이드](https://apis.map.kakao.com/web/guide/), [Kakao 지도 Web API 문서](https://apis.map.kakao.com/web/documentation/), [Vercel agent-skills](https://github.com/vercel-labs/agent-skills), [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md)
- 확인일: 2026-08-22

## 2026-08-22 Kakao 지도 유료 사용 구조 확인

- 상태: `FACT` — 2026-08-22 공식 문서 기준. 단가는 추후 변경 가능.
- 2026-07-21부터 개발자 계정에서 첫 번째로 카카오맵 API를 활성화한 앱에만 무료 쿼터가 제공된다. Waterpark가 두 번째 이후 활성화 앱이면 비즈월렛 연결과 유료 API 사용 설정 후 사용량 기반으로 이용해야 한다.
- 공식 단가는 부가세 별도로 지도 Web(JavaScript) SDK 0.1원/건, 주소로 좌표 변환 0.5원/건, 키워드로 장소 검색 2원/건이다.
- 현재 프론트엔드의 `페이지 지도 로드 1회 + 주소 검색 1회`는 단순 합계 2.6원, 부가세 포함 약 2.86원으로 추정한다. 실제 청구는 각 API의 실제 호출 횟수에 따라 달라진다.
- 월별 합계에 부가세 10%가 더해지고 다음 달 1일 오전 1시경 비즈월렛으로 자동 결제된다.
- Waterpark는 공공데이터 로컬 검색을 기본으로 유지하고 Kakao 검색은 사용자 제출 시에만 호출해 불필요한 과금을 제한한다.
- 상세: [지도·주소·주차장 API 연결](./frontend/02-map-and-parking-api.md)
- 출처: [Kakao Developers 카카오맵 이해하기](https://developers.kakao.com/docs/ko/kakaomap/common), [Kakao Developers 쿼터](https://developers.kakao.com/docs/ko/getting-started/quota), [Kakao Developers 유료 API](https://developers.kakao.com/docs/ko/app-setting/paid-api)
- 확인일: 2026-08-22

## 2026-08-22 Kakao 무료 쿼터 앱 영구 삭제 여부

- 상태: `OPEN` — 무료 쿼터 대상 앱 영구 삭제 후 다른 앱에 쿼터가 재배정된다는 공식 근거를 확인하지 못함.
- Kakao Developers 화면은 무료 쿼터 대상 앱을 비활성화해도 대상을 변경할 수 없다고 안내한다.
- 공식 앱 문서는 영구 삭제한 앱은 복구할 수 없다고 명시하며, FAQ는 같은 이름으로 새 앱을 만들어도 기존 앱과 다른 서비스로 인식한다고 설명한다.
- 현재 근거로는 기존 앱 삭제 후 Waterpark가 무료 대상이 된다고 판단할 수 없다. 무료 쿼터 목적의 삭제를 보류하고, 카카오 데브톡에 기존 무료 앱 ID와 Waterpark 앱 ID를 제시해 운영진의 명시적 답변을 받는다.
- 출처: [Kakao Developers 앱 설정](https://developers.kakao.com/docs/ko/app-setting/app), [Kakao Developers FAQ](https://developers.kakao.com/docs/ko/getting-started/faq), [카카오맵 무료 쿼터 정책 공지](https://devtalk.kakao.com/t/api-notice-on-new-kakao-map-api-features-and-free-quota-policy/150222)
- 확인일: 2026-08-22

## 2026-08-22 경상북도 침수흔적도 확보 및 시간 강수 결합 결과

- 상태: `FACT` — 대체 공개 미러에서 실제 다운로드, KMA 시간 강수와 결합 완료. `D1` 원 출처(safetydata.go.kr) 정식 API는 아직 미확보.
- `safetydata.go.kr`의 `DSSP-IF-00117` 정식 API는 별도 `이용신청`과 승인 대기가 필요해 해커톤 일정상 사용하지 못했다. 대신 Esri Korea Living Atlas가 같은 행정안전부 침수흔적도를 승인서(`safetydata.go.kr/disaster-data/view?dataSn=108`)와 함께 공개 Feature Service로 미러링한 것을 사용자가 직접 확인해 GeoJSON으로 받았다.
- 미러 출처: `https://portal.esrikr.com/arcgis/rest/services/Hosted/Flood_2002_2022/FeatureServer` (2002~2022년, 2025.0판, 데이터 기준일 2024-11-27). 원 제공기관은 더 이상 이 데이터를 갱신하지 않는다고 항목 설명에 명시되어 있다.
- 파일을 직접 열어 검증했다. 좌표는 WGS84 경위도(EPSG:4326)이고, 전체 1,402행 모두 `stdg_ctpv_cd=47`(경상북도)로 이미 필터링되어 있다. 시군구 16개, 침수연도는 2002·2008·2011·2012·2018·2019·2020·2021년이다. 2022년 힌남노 기록은 없다.
- 필드는 공식 API 명세와 거의 동일하고 `objectid`, `SHAPE__Length`, `SHAPE__Area`는 Esri Feature Service가 자동으로 붙이는 필드다.
- `fldn_bgng_ymd`+`fldn_bgng_tm` 조합 기준 서로 다른 사건은 15개 날짜, 30개 (날짜, 시각) 조합이다. 포항(47111 남구 29건, 47113 북구 70건, 합 99건)은 2012·2019·2021년에만 기록이 있다.
- `fldn_bgng_tm`은 조사 추정치로 시 단위로 반올림되어 있다. 1,402행 중 75행이 `0000`으로 기록되어 있어, 이것이 자정을 뜻하는지 미기록을 뜻하는지는 확정하지 않았다.
- 30개 (날짜, 시각) 이벤트마다 KMA API허브 `AWS 시간통계`(`awsh.php`, `var=RN`, `apiList.do?seqApi=2&seqApiSub=239`)로 사건 시작시각 기준 과거 24시간의 `RN_HR1`을 시간별로 받아 `rain_1h`, `rain_6h`, `rain_24h`를 관측소별로 계산했다. 필요한 서로 다른 시간대는 427개였고, 결측(-99) 값은 제외했다.
- 포항 관측소(138)는 검증한 모든 이벤트에서 24시간 전체 자료가 존재했다. 예: 2012-09-17 태풍 산바 당일 시각별 24시간 누적 강수가 98→216mm로 늘어나는 흐름을 확인했고, 2019-10-02 23:00 시점 24시간 누적은 276.8mm(태풍 미탁)였다.
- 포항이 아닌 사건(예: 2008-07-24 안동)에서는 포항 관측소 값이 낮게 나왔다. 이벤트마다 해당 시군구에 맞는 관측소를 고르는 작업이 아직 남아 있다는 뜻이다.
- 산출물: `data/processed/gyeongbuk_flood_records.csv`(1,402행, 지오메트리 제외), `data/processed/gyeongbuk_flood_events.csv`(30행), `data/processed/gyeongbuk_flood_event_rain.csv`(20,018행, 이벤트×관측소), 원본 `data/raw/flood-trace/gyeongbuk_flood_2002_2022.geojson`
- 한계: 건물과의 공간 결합은 아직 하지 않았다(지오메트리는 CSV에서 제외, 원본 GeoJSON에는 보존). 관측소 선택은 아직 거리 기반이 아니라 전체 관측소를 남겨둔 상태다. 정식 `safetydata.go.kr` API는 여전히 미확보라 이 미러와 원 출처가 완전히 같은지는 재교차검증이 필요하다.
- 출처: [Esri Korea Living Atlas 침수흔적도 미러](https://portal.esrikr.com/arcgis/rest/services/Hosted/Flood_2002_2022/FeatureServer), [행정안전부 침수흔적도 승인서](https://www.safetydata.go.kr/disaster-data/view?dataSn=108), [기상청 API허브 AWS 시간통계](https://apihub.kma.go.kr/apiList.do?seqApi=2&seqApiSub=239)
- 확인일: 2026-08-22

## 결정 로그

| ID | 날짜 | 결정 | 상태 |
| --- | --- | --- | --- |
| D-001 | 2026-08-22 | 경상북도 공공데이터 챌린지로 참가한다. | `DECISION` |
| D-002 | 2026-08-22 | 서비스명을 Waterpark로 확정한다. | `DECISION` |
| D-003 | 2026-08-22 | 지하주차장 침수 위험 예측 및 차량 사전 대피 안내 서비스를 개발한다. | `DECISION` |
| D-004 | 2026-08-22 | 현재 개발 순서를 데이터 판별·전처리, 머신러닝, 백엔드, 프론트엔드 전달로 둔다. | `DECISION` |
| D-005 | 2026-08-22 | 데이터 수집·통합 기본 범위를 포항이 아닌 경상북도 22개 시군 전체로 둔다. | `DECISION` |
| D-006 | 2026-08-22 | 프론트엔드 로우파이는 React·TypeScript·Vite로 구현한다. | `DECISION` |
| D-007 | 2026-08-22 | 지도·주소·주차장 검색은 Kakao 지도 JavaScript SDK를 우선 사용하고, 키가 없거나 실패하면 경북 공영주차장 좌표 데이터로 전환한다. | `DECISION` |

## 조사 결과 기록 형식

```markdown
### 항목 ID — 제목

- 확인일:
- 상태: FACT / NOTE / OPEN / DECISION
- 확인 내용:
- 출처:
- 현재 단계에 주는 영향:
```

## 입력 자료

- 팀 PRD 및 행사 메모
- Day 1 오프닝 전사
- 트랙 파트너 세션 전사

원본 입력 자료는 대화 첨부파일로 제공되었으며 이 저장소에는 포함하지 않는다.

전사본은 자동 음성 인식 오류와 중복 가능성이 있으므로 공식 사실의 최종 근거로 사용하지 않는다.
