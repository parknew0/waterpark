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
- 산출물: `data/processed/parking/gyeongbuk_parking_seed.csv`, `outputs/reports/waterpark_gyeongbuk_integration.xlsx`
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
- 산출물: `data/processed/buildings/gyeongbuk_buildings_elevation.parquet`, `data/processed/buildings/gyeongbuk_buildings_elevation.csv.gz`, `outputs/reports/waterpark_gyeongbuk_buildings_elevation.xlsx`
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
- 전체 API 원응답과 CSV는 로컬 `data/raw/building-register/`, `data/interim/building-register/`에 저장하고 Git에서는 제외했다. 재현 스크립트, 500행 표본과 집계 manifest만 Git에 포함한다.
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
- 산출물: `data/interim/flood-trace/gyeongbuk/gyeongbuk_flood_records.csv`(1,402행, 지오메트리 제외), `data/interim/flood-trace/gyeongbuk/gyeongbuk_flood_events.csv`(30행), `data/processed/rainfall/gyeongbuk_flood_event_rain.csv`(20,018행, 이벤트×관측소), 원본 `data/raw/flood-trace/gyeongbuk_flood_2002_2022.geojson`
- 한계: 건물과의 공간 결합은 아직 하지 않았다(지오메트리는 CSV에서 제외, 원본 GeoJSON에는 보존). 관측소 선택은 아직 거리 기반이 아니라 전체 관측소를 남겨둔 상태다. 정식 `safetydata.go.kr` API는 여전히 미확보라 이 미러와 원 출처가 완전히 같은지는 재교차검증이 필요하다.
- 출처: [Esri Korea Living Atlas 침수흔적도 미러](https://portal.esrikr.com/arcgis/rest/services/Hosted/Flood_2002_2022/FeatureServer), [행정안전부 침수흔적도 승인서](https://www.safetydata.go.kr/disaster-data/view?dataSn=108), [기상청 API허브 AWS 시간통계](https://apihub.kma.go.kr/apiList.do?seqApi=2&seqApiSub=239)
- 확인일: 2026-08-22

## 2026-08-22 공식 GIS건물통합정보 확보 및 건물 특징표 생성

- 상태: `FACT` — 공식 `D4` SHP를 로컬에서 확인하고 좌표를 실제로 추출했다. 침수 라벨 결합은 아직 `OPEN`.
- 사용자가 VWorld `GIS건물통합정보` 경상북도 전체데이터를 직접 받았고, 원천자료를 `data/raw/vworld-buildings/gyeongbuk/AL_D010_47_20251204`로 정리했다. 기존 문서가 `공식 원본은 로그인 차단`으로 기록했던 `D4`가 실제로는 확보된 상태다.
- 파일 구성은 SHP 3개 묶음으로 각각 1,000,000 + 1,000,000 + 8,310 레코드이며 합계 2,008,310동이다. 세 파일은 중복이 아니라 서로 다른 분할분임을 `gis_building_id` 기준으로 확인했다.
- 좌표계는 `.prj`에 `EPSG:5186`(Korea 2000 중부원점 2010)으로 명시되어 있다. 침수흔적도(`EPSG:4326`)와 다르므로 공간 결합 전 변환이 필요하다.
- 조인 키 검증 결과 건축물대장의 `mgmBldrgstPk`(예: `122613634`)와 GIS의 `A19` 연계 ID(예: `37009`)는 형식이 달라 건물 단위 1:1 결합이 불가능했다. 유일하게 신뢰 가능한 공통 키는 `PNU`(필지)이며, 등록부 고유 PNU 20,788개가 GIS PNU에 100% 포함된다.
- PNU는 필지이므로 다대다다. 등록부는 PNU당 평균 2.10행(최대 285행), GIS는 PNU당 평균 1.19동(최대 68동)이다. 따라서 지하주차장 판정은 본질적으로 필지 단위 속성이다.
- 행 단위를 `GIS 자체 지하층수(A27) >= 1`인 건물로 정하고, 건물 폴리곤 중심점을 계산해 WGS84로 변환했다. 25,340개 후보 중 고유 25,336동 전부에 좌표가 붙었다.
- 좌표 변환은 저장소의 다른 스크립트와 같이 순수 표준 라이브러리로 Snyder 역 횡메르카토르 급수를 구현했다. `--verify-projection`으로 pyproj와 대조한 편차는 0.0000m다.
- 좌표 타당성 검증: 25,336동 전부가 경북 경위도 범위 안이며 범위 밖 0건이다. 독립 출처인 Overture 건물 305,058동과 대조했을 때 표본 400동의 최근접 거리 중앙값은 7.6m, 30m 이내가 80.6%로 같은 건물 수준이다.
- 지하주차장 확정은 필지 1,372개이며 그 위의 건물 1,787동이다. 기존 매니페스트의 `1,449`는 등록부 행 기준이고 이 값은 건물 기준이라 서로 다른 단위다.
- 확정 건물의 시군 분포는 구미 405, 경산 338, 포항 북구 195, 경주 194, 포항 남구 175동 순으로 도시 지역에 집중된다.
- 산출물: `data/processed/buildings/gyeongbuk_building_underground_parking_features.csv`(25,336행, 27컬럼)
- 한계: 지하주차장 판정은 필지 단위라 한 필지의 여러 동이 같은 값을 갖는다. 지하층이 있는 건물만 포함해 음성 표본을 이 파일만으로 만들 수 없다. `CONFIRMED`가 아닌 값은 지하주차장이 없다는 뜻이 아니다. 침수 라벨과 강수는 아직 붙이지 않았다.
- 출처: [VWorld GIS건물통합정보](https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?svcCde=NA&dsId=18), [건축HUB 건축물대장 API](https://www.data.go.kr/data/15134735/openapi.do)
- 확인일: 2026-08-22

## 2026-08-22 침수 라벨 타당성 검증 및 위험 산출 결과

- 상태: `FACT` — 실제 공간 결합, 학습, 평가까지 실행했다.
- 지하층 보유 건물 25,336동을 침수흔적 Polygon과 겹친 결과 176동(0.69%)만 침수 구역 안이고, 그 중 지하주차장 확정은 9동이다. **양성 9개로는 지하주차장 침수 지도학습이 성립하지 않는다.**
- 원인은 두 자료의 대상 지역이 다르기 때문이다. 경산시는 지하주차장 확정 338동에 침수 Polygon 0건, 구미시는 405동에 24건인 반면 봉화군은 4동에 134건이다. 침수 원인 1위는 `농경지 침수 및 농작물 피해, 하우스 파손` 312건으로 이 자료는 농경지·하천 범람 조사다.
- 따라서 조사 기록이 없는 지역을 `flood=0`으로 둘 수 없다. [전처리 계획](./02-preprocessing-and-xgboost-feasibility.md) 3.3절의 경고가 실제 데이터에서 그대로 확인됐다.
- 대체 목표로 `지표면 침수`를 학습했다. 학습표는 45,920행, 양성 2,993(6.52%)이며 음성은 같은 사건의 조사 Polygon에서 1km 이내인 건물만 인정하고 그 밖은 미확인으로 제외했다.
- 누수 차단: `distance_to_flood_polygon_m`(양성은 전부 0), `longitude`, `latitude`(같은 건물이 여러 사건에 등장)를 제외했다. 분할은 무작위 대신 사건 단위와 건물 단위로 각각 수행했다.
- 같은·연속 날짜의 30개 사건시각을 보수적으로 13개 `storm_group_id`로 묶고, 같은 폭풍이 학습·검증에 나뉘지 않도록 다시 평가했다. 폭풍 그룹 CV PR-AUC는 0.1257, 시간 순서 분할은 0.1188로 기준선 0.065보다 높지만 여전히 낮다. 건물 단위 CV는 0.8233으로 높지만 같은 호우가 양쪽에 있어 새 폭풍 성능으로 주장할 수 없다.
- **주변 대비 고도 규칙 하나의 PR-AUC가 0.249로 XGBoost 폭풍 그룹 CV 0.1257보다 높다.** 학습 없이 계산되는 값이므로 누수가 없다. 현재 데이터에서는 규칙이 모델보다 강하다.
- 강수는 안정적인 신호로 확인되지 않았다. 24시간 누적 구간별 침수율이 단조가 아니고, 한 사건 안에서 같은 관측소를 쓰는 건물은 동일한 강수값을 공유한다. 양성이 있는 사건시각은 21개지만 독립 폭풍 대리그룹은 13개뿐이라 강수-침수 관계를 분리하기에 부족하다.
- 지형은 신호가 뚜렷하다. 주변 대비 고도별 침수율은 0~2m 35.5%, 2~5m 14.8%, 5~10m 5.2%, 10~20m 0.4%, 20m 이상 0.0%로 단조 감소한다.
- 위험점수는 지형 관측값에 과거 침수 500m 이내 상향을 더한 상시 위험도로 만들고, 강수 발령 기준은 학습하지 않고 기상청 공식 호우특보 기준을 적용했다. 공식 기준은 호우주의보 3시간 60mm 또는 12시간 110mm, 호우경보 3시간 90mm 또는 12시간 180mm, 극한호우 1시간 50mm이면서 3시간 90mm 또는 1시간 72mm다.
- 위험도에는 가능성만 포함하고 지하주차장 유무·주차 대수는 피해 규모이므로 별도 컬럼으로 분리했다.
- 25,336동 상시 위험도 분포는 VERY_HIGH 341, HIGH 2,283, MODERATE 4,979, LOW 6,582, VERY_LOW 8,729, UNKNOWN 2,422다. UNKNOWN은 100m 이내 표고 공여 건물이 없는 경우다.
- 기상청 관측지점정보 CSV는 로그인 없이 `POST /tmeta/stn/selectStnListDownload.do`로 받을 수 있다. 지점정보 API(`stn_inf.php`)와 일통계 API(`sfc_aws_day.php`)는 별도 활용신청이 필요해 403이다.
- 산출물: `data/processed/ml/training/gyeongbuk_flood_training_table.csv`(45,920행), `data/processed/ml/predictions/gyeongbuk_underground_parking_risk.csv`(25,336행), `outputs/gyeongbuk-flood-model/model_report.json`
- 상세 문서: [침수 위험 산출 결과](./06-flood-risk-modeling.md)
- 출처: [기상청 예보업무 기상특보 기준](https://www.kma.go.kr/kma/biz/forecast03.jsp), [기상청 관측지점정보](https://data.kma.go.kr/tmeta/stn/selectStnList.do?pgmNo=123), [Esri Korea 침수흔적도 미러](https://portal.esrikr.com/arcgis/rest/services/Hosted/Flood_2002_2022/FeatureServer)
- 확인일: 2026-08-22

## 2026-08-22 경상북도 침수 관련 공공데이터 소스 추가 조사

- 상태: `FACT` — 공식·공공기관 페이지에서 제공 범위와 형식을 확인했다. 후보를 채택하거나 모두 수집하기로 결정한 것은 아니다.
- 실제 침수 기록, 모의 침수지도, 강수·수위 시계열과 지형·배수 인프라는 서로 다른 의미이므로 별도 역할로 분류했다.
- [홍수위험지도 SHP](https://www.data.go.kr/tcs/dss/selectFileDataDetailView.do?publicDataPk=15077744)는 전국 국가·지방하천 범람지도와 도시침수지도를 5단계 침수심·빈도별로 제공한다. 실제 과거 침수 라벨이 아니라 극한 상황을 가정한 모의 범위다.
- 홍수위험지도 페이지의 라이선스는 공공누리 제4유형이다. 파생 특징 학습·변형·재배포 허용 범위는 제공기관 확인 전 확정하지 않는다.
- [낙동강홍수통제소 수문 정보](https://www.data.go.kr/data/3039640/fileData.do)는 낙동강·태화강·형산강의 수위·강수량을 CSV로 제공하며 포항 형산교·문덕3교를 포함해 경북 다수 지점을 명시한다.
- [기상청 레이더 HSR](https://apihub.kma.go.kr/apiList.do?seqApi=5)는 2016년 이후 500m 격자·5분 주기 자료를 제공한다. 관측소 하나보다 국지 강우 차이를 표현할 후보지만 격자 전처리와 API 활용신청이 필요하다.
- [재해위험지구 WMS/WFS](https://www.data.go.kr/data/15057419/openapi.do)는 상습침수 등 지자체 지정 위험구역의 공간정보를 제공한다. [전국배수펌프장 표준데이터](https://www.data.go.kr/data/15129436/standard.do)와 [경북 재난대응용 배수펌프장](https://www.data.go.kr/dataset/3083901/fileData.do)은 배수시설 위치·일부 성능을 보강한다.
- 경북 전역의 하수관로 선형·관경·시간당 처리용량·막힘 상태를 동일한 형식으로 제공하는 공개 원천은 확인하지 못했다. 시군별 제공신청이 필요한 영역으로 남긴다.
- 국립해양조사원의 기존 조위·파고 등 35개 OpenAPI는 [2026년 제공중단 공지](https://www.data.go.kr/bbs/ntc/selectNotice.do?originId=NOTICE_0000000004473)가 있으므로 새 개발의 현재 API로 간주하지 않는다.
- 상세 목록과 판별 순서: [경상북도 침수 관련 공공데이터 소스 조사](./07-gyeongbuk-flood-data-source-catalog.md)
- 확인일: 2026-08-22

## 2026-08-22 Figma 온보딩·위치 동의 화면 구현

- 상태: `FACT` — Figma 디자인 컨텍스트와 에셋을 직접 확인해 React 구현 및 브라우저 검증 완료.
- 차량 보호 소개의 최신 기준 노드 `136:2756`은 402×874 모바일 화면, 1/2 진행률, 서비스 설명, 흰색 SUV 이미지와 `Next` CTA로 구성된다.
- 위치 동의 노드 `123:2151`은 2/2 진행률, 필수 위치 권한과 사용 목적, `Agree & Start` CTA로 구성된다.
- Figma 원본 흰색 SUV PNG와 위치 SVG를 프로젝트에 저장하고 임시 에셋 URL 의존성을 제거했다.
- 빗방울이 차체의 지정 위치에 도달하면 낙하선이 사라지고 물방울 파편이 튀는 CSS 애니메이션을 추가했다. 이는 물리 엔진 충돌 판정이 아니라 화면 크기에 맞춘 연출이며 `prefers-reduced-motion`에서 반복을 중단한다.
- Figma의 iPhone 상태바·다이내믹 아일랜드·홈 인디케이터는 예시용 기기 크롬이므로 실제 웹 UI에서 제외했다.
- 흐름은 `차량 보호 소개 → 위치 동의 → 브라우저 위치 권한 요청 → Kakao 지도`로 연결했다. URL은 `view=consent`, `view=map`으로 상태를 반영하며 뒤로가기를 지원한다.
- 402×874에서 최신 SUV 화면과 빗방울 충돌 물보라를 시각 확인했고, 1280×900 중앙 프레임 확인, lint/build, Kakao 지도 진입, 브라우저 경고·오류 0건을 검증했다.
- 상세: [온보딩 뷰 구현](./frontend/04-onboarding-views.md)
- 출처: [Figma 차량 보호 소개 `136:2756`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=136-2756&m=dev), [Figma 위치 동의 `123:2151`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2151&m=dev), [Vercel Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md)
- 확인일: 2026-08-22

## 2026-08-22 Figma 지도 홈·가까운 주차장·선택 상세 구현

- 상태: `FACT` — Figma 노드 확인, React 구현, 402×874 브라우저 전환 검증 완료. 실제 위치 권한 환경 최종 확인은 `OPEN`.
- 지도 홈 `123:1415`, 가까운 주차장 시트 `123:2075`, 주차장 선택 상세 `123:2360`, 위치 라벨 `123:1419`를 확인했다.
- 온보딩 `Next`는 `?view=consent` 위치 동의 화면으로 이동한다. `Agree & Start`를 누르면 `?view=map`으로 이동하고 지도 위 가까운 주차장 시트를 즉시 표시한다.
- 위치 권한이 허용되면 `navigator.geolocation` 좌표로 경북 공영주차장을 거리순 재정렬하고 Kakao `coord2Address` 결과를 상단 현재 위치 라벨에 표시한다.
- 위치 권한이 없으면 기본 경북 중심 결과와 상단 위치 라벨 상태를 유지한다. 지도를 가리는 별도 토스트는 제거했다. 테스트 브라우저는 위치 권한을 확보하지 못했으므로 실제 주소 표시는 아직 최종 확인하지 못했다.
- Figma 사진·아이콘은 로컬에 저장했다. Kakao 지도가 없을 때만 Figma 지도 이미지를 폴백으로 사용한다.
- Kakao 지도 Web API에는 확인 가능한 웹용 다크 테마 옵션이 없어 지도 타일 부모 레이어에 CSS 색상 필터를 한 번 적용했다. 개별 타일 필터에서 생기던 가로·세로 경계선을 제거하면서 현재 위치 마커와 Kakao 저작권·브랜드 링크는 필터 밖에 유지한다.
- 강수 API와 위험 예측 API가 아직 연결되지 않아 예시 수치 `30mm`와 특정 주차장 `High risk` 판정을 사용하지 않았다. 각각 `--mm`, `Risk assessment is not connected yet`으로 명시했다.
- 빗방울 충돌 효과는 10개에서 16개로 늘렸다.
- Figma `123:2320`의 방향 부채꼴과 청록 점 에셋을 Kakao `CustomOverlay`로 현재 좌표에 표시한다. 위치 권한 실패 시에는 마커를 표시하지 않는다.
- 가까운 주차장 시트는 지도 진입 즉시 1.2초 동안 아래에서 위로 올라오고 배경 스크림은 360ms 동안 나타난다.
- 상세: [지도 홈·내 차 위치 설정 흐름](./frontend/05-parking-home-and-location-flow.md)
- 출처: [Figma 지도 홈 `123:1415`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1415&m=dev), [가까운 주차장 `123:2075`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2075&m=dev), [선택 상세 `123:2360`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2360&m=dev), [현재 위치 라벨 `123:1419`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1419&m=dev), [현재 위치 마커 `123:2320`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2320&m=dev), [Kakao 지도 Web API 문서](https://apis.map.kakao.com/web/documentation/)
- 확인일: 2026-08-22

## 2026-08-22 지도 마커 상태·내 차 위치·기기 방향 구현

- 상태: `FACT` — Figma 노드 확인, React 구현, lint/build와 브라우저 상태 전환 검증 완료. 실제 모바일 방향 센서 확인은 `OPEN`.
- `123:1415` 지도에 진입하면 `123:2075` 가까운 주차장 목록 시트를 즉시 표시한다. 목록 선택 뒤 `123:2360` 상세를 열고 설정 버튼을 누르면 `123:1958` 최종 지도로 전환한다.
- 최종 지도는 현재 위치, 선택 좌표의 `136:2639` 내 차 마커, 선택한 곳을 제외한 주변 주차장 `P` 마커 최대 8개, 실제 주차장명·주소 카드를 함께 표시한다. 저장은 아직 브라우저 메모리 상태다.
- 방향 부채꼴은 iOS Safari의 `webkitCompassHeading`을 우선 사용한다. 절대값이 아닌 표준 `alpha`도 상대 회전 폴백으로 사용하고, 회전축은 부채꼴 이미지 내부가 아닌 현재 위치 점 중심으로 교정했다.
- 현재 위치 오버레이는 포인터 이벤트를 받지 않도록 변경하고 Kakao 지도에 드래그·스크롤 옵션을 명시했다. 402×874 브라우저에서 100px 드래그 후 내부 지도 레이어가 실제 100px 이동했다.
- 개별 타일마다 적용하던 다크 필터를 타일 부모 레이어의 단일 필터로 변경해 스크린샷의 타일 경계선을 제거했다. Figma `123:2511` 기준으로 강수 아이콘의 빗줄기 간격도 교정했다.
- Figma `123:1631`의 최종 캡처에는 검색 입력창 오른쪽 아이콘이 표시되지 않는다. 잘못 연결됐던 눈 가림 SVG와 아이콘 버튼을 모두 제거했으며 Enter/모바일 키보드 제출은 form submit으로 유지한다.
- 현재 위치 부채꼴과 점이 회전할 때 분리되던 문제는 두 요소의 중심과 Kakao anchor를 `(32px, 54px)`로 통일해 수정했다.
- 모바일에서도 프레임 폭을 402px로 제한해 생기던 좌우·하단 여백을 제거했다. 480px 이하에서는 `100vw × 100svh`를 사용하며 430×932 브라우저에서 시트 `x=0`, `width=430`, `bottom=932`를 확인했다.
- 상세 CTA는 Figma `123:2360`의 홈 인디케이터 영역 34px을 웹 하단 여백으로 유지했다. 402×874에서 버튼 하단은 828px, 화면 하단 간격은 46px이다.
- 현재 위치 마커는 단순 삼각형 배치가 아니라 Figma `123:2320`의 중첩 frame·rotator·canvas·dot 구조와 inset을 그대로 이식했다. 기본 `-135°` 위에 센서 방위를 합성하고 Kakao anchor를 점 중심에 맞췄다.
- Figma `176:2956`에 맞춰 `My Location` 색상을 청록에서 `#EDEDED`로 수정하고 카드 세로 간격을 17px·8px로 조정했다.
- 최종 카드 주차장명과 주소는 영어로 표시한다. 포항 데모 3개 지점은 명시적인 영문 표기를 사용하며 나머지는 로컬 영문자 변환 폴백을 사용한다. 외부 번역 API의 공식 번역이 아니므로 고유명사 영문 표기는 추후 검수 대상이다.
- 테스트 브라우저에서는 위치 권한을 확보하지 못해 실제 현재 위치와 센서 회전은 검증하지 못했다. 권한 실패 시 가짜 현재 위치를 표시하지 않는 처리, 목록 즉시 표시, 상세, 확정 후 주변 후보·차 마커·저장 카드 상태를 확인했다.
- 출처: [Figma 지도 홈 `123:1415`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1415&m=dev), [지도 선택 `123:1958`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1958&m=dev), [검색 입력창 `123:1631`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1631&m=dev), [상세 CTA `123:2360`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2360&m=dev), [현재 위치 마커 `123:2320`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2320&m=dev), [My Location 카드 `176:2956`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=176-2956&m=dev), [내 차 마커 `136:2639`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=136-2639&m=dev), [W3C Device Orientation and Motion](https://www.w3.org/TR/orientation-event/), [Apple DeviceOrientationEvent](https://developer.apple.com/documentation/webkitjs/deviceorientationevent)

### 2026-08-22 — 긴급 상황 화면과 경고 모션 구현

- `FACT`: Figma `90:675`는 402×874 긴급 화면이며 경고 아이콘 149px, 안전 주차장 카드 370×172px, CTA 영역 402×74px로 확인했다.
- `FACT`: Figma `90:675`와 `136:2576`의 모션 컨텍스트에는 애니메이션 노드가 없었다.
- `DECISION`: 정적 레이아웃은 Figma 디자인 컨텍스트를 따르고, 사용자 요청에 따라 26개 빗방울 낙하와 1.15초 경고 진동·외곽 원 펄스를 CSS로 추가했다.
- `FACT`: 402×874 브라우저에서 경고 아이콘 `x=126.5, y=131`, 카드 `x=16, y=506`, CTA `y=748`을 측정했고 애니메이션의 computed transform 변화도 확인했다.
- `LIMITATION`: `30min`, 배정 주차장과 `156m away`는 실제 예측·주차 여석 API 값이 아닌 Figma 프로토타입 고정값이다.
- 출처: [Figma 긴급 화면 `90:675`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=90-675&m=dev), [Figma 경고 원 `136:2576`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=136-2576&m=dev)

### 2026-08-22 — 침수 위험 회피 대피 경로 구현 가능성

- `FACT`: OSMnx는 지정 Polygon의 운전 도로를 NetworkX `MultiDiGraph`로 만들고 GraphML 저장·로드, Dijkstra 기반 가중 최단 경로와 경로 GeoDataFrame 변환을 지원한다.
- `FACT`: NetworkX 최단 경로는 간선 속성 또는 함수형 가중치를 지원하므로 거리·시간에 비음수 침수 위험 패널티를 더할 수 있다.
- `FACT`: 현재 Waterpark 위험표는 25,336개 건물 점의 상시 위험도이며 도로를 막는 현재 침수 폴리곤이나 연속 예측 격자가 아니다.
- `FACT`: 현재 공영주차장 2,010곳은 안전성·지상 여부·실시간 여석이 검증되지 않은 목적지 후보다.
- `DECISION PROPOSAL`: 현재 침수·공식 통제와 겹친 간선은 제거하고, 가까운 미래 위험과 겹친 간선은 통과 가능하되 위험 비용을 높이는 구조가 구현 가능하다.
- `LIMITATION`: 현 데이터 단계의 결과는 `안전 경로`가 아니라 `저위험 우회 경로 후보`로 표현해야 한다.
- 상세: [침수 위험 회피 대피 경로 설계](./09-flood-aware-evacuation-routing.md)
- 출처: [OSMnx User Reference](https://osmnx.readthedocs.io/en/stable/user-reference.html), [NetworkX shortest_path](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.generic.shortest_path.html), [GeoPandas sjoin](https://geopandas.org/en/latest/docs/reference/api/geopandas.sjoin.html), [OpenStreetMap Attribution Guidelines](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines)

### 2026-08-22 — 포항 침수 위험 회피 경로 MVP 구현

- `FACT`: POSTECH 인근 반경 2.5km의 OSM 운전 도로 그래프를 수집해 로컬 GraphML 캐시로 저장하는 생성기를 구현했다.
- `FACT`: 건물 `HIGH`·`VERY_HIGH` 위험점의 120m 데모 영향권과 각 도로 간선의 교차 길이를 계산하고, `length + HIGH 노출×5 + VERY_HIGH 노출×12`의 비음수 비용으로 Dijkstra 경로를 계산한다.
- `FACT`: 공영주차장 후보를 영향권 밖·도로 도달 가능 여부로 거른 결과, 기준 출발점에서는 `효곡동 노상1`, 도로거리 618.3m가 선택됐다.
- `FACT`: 이 입력에서 일반 최단경로와 저위험 경로는 동일하며 위험 영향권 교차 길이는 모두 0m다. 차이가 없는 결과를 임의 우회로로 조작하지 않았다.
- `FACT`: 긴급 화면의 기존 고정 주차장과 156m 값은 계산 GeoJSON의 목적지·주소·도로거리로 교체했다. CTA 뒤 Kakao 지도 또는 키 없는 SVG 폴백에 위험 구역, 일반 경로, 저위험 경로와 목적지를 표시한다.
- `LIMITATION`: 위험 반경은 시연 파라미터이며 목적 주차장의 안전성·실시간 여석은 검증되지 않았다. 실제 운영에는 공식 현재 침수·도로 통제 입력이 필요하다.
- 상세: [침수 위험 회피 대피 경로 설계와 구현](./09-flood-aware-evacuation-routing.md), [프론트 경로 뷰](./frontend/07-flood-aware-route-view.md)
- 출처: [OSMnx User Reference](https://osmnx.readthedocs.io/en/stable/user-reference.html), [NetworkX shortest_path](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.generic.shortest_path.html), [OpenStreetMap Attribution Guidelines](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines)

### 2026-08-22 — 가짜 현재 침수 상황과 4단계 데모 구현

- `FACT`: 기본 경로의 도로 일부를 가로지르는 합성 Polygon을 `data/demo/pohang-current-flood-scenario.geojson`으로 추가했다.
- `FACT`: 합성 폴리곤을 현재 침수 입력으로 사용하면 OSM 간선 6개가 제거되고 목적지는 `효곡동 노상8`, 우회 거리는 2,121.9m가 된다.
- `FACT`: Figma `119:1140`, `123:1743`, `90:755`를 확인해 위험 상세·안전 상세·길찾기 React 뷰를 구현했다.
- `FACT`: 긴급 경고부터 `emergency → risk-detail → safe-detail → route`로 이어지며 각 URL로 직접 진입할 수도 있다.
- `LIMITATION`: Polygon과 `30mm`, 1시간 위험, 안전시간 30분은 시연 값이다. 실제 침수·강수·안전 보증으로 발표하지 않는다.
- 상세: [가짜 침수 상황 데모 흐름](./frontend/08-flood-scenario-demo-flow.md)
- 출처: [Figma 위험 상세 `119:1140`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=119-1140&m=dev), [Figma 안전 상세 `123:1743`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1743&m=dev), [Figma 길찾기 `90:755`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=90-755&m=dev)

### 2026-08-22 — 긴급 화면 위치와 영문 주소 교정

- `FACT`: Figma `90:675`의 경고 원은 402×874 기준 `x=126.5, y=131`, 차량 프레임은 `x=167, y=171`, 뒤로가기 아이콘 중심은 `(36, 86)`이다.
- `FACT`: 기존 `max-height: 760px` CSS가 경고 원을 `y=92`로 이동시켜 뒤로가기와 간격을 깨뜨리고 있었다. 이 긴급 화면 예외를 제거했다.
- `FACT`: 차량 프레임의 상대 x좌표를 35px에서 40.5px로 교정해 Figma와 동일한 절대 x=167을 만들었다.
- `FACT`: 긴급·안전·길찾기 화면의 목적지명과 주소를 영문으로 통일했다.
- `FACT`: 402×720에서 좌표 측정, 402×874 시각 검사, TypeScript build, ESLint와 console 오류·경고 0건을 확인했다.
- 출처: [Figma 긴급 화면 `90:675`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=90-675&m=dev)

## 2026-08-22 전국 침수·건물 원본 확보 및 구조 검증

- 상태: `FACT` — 전국 원본 다운로드와 구조·스키마 검증까지 완료. 전국 학습표 생성은 아직 하지 않았다.
- 전국 침수흔적도는 38,003건, 17개 시도, Polygon 37,898건과 MultiPolygon 105건이다. 원본 geometry는 바꾸지 않았고 self-intersection 22건을 manifest에 기록했다.
- VWorld GIS건물통합정보는 침수 원천의 마지막 연도에 맞춘 2022-12-03 전국 전체데이터를 Chrome에서 선택해 내려받았다. 외부 ZIP은 17개 시도 ZIP, 내부는 24개 SHP part이고 압축 CRC가 정상이다.
- 전국 건물 DBF 헤더 합계는 13,885,793행이다. 모든 part는 동일한 23필드 `A0~A22`, 좌표계 `EPSG:5174`다.
- 공식 VWorld 컬럼 정의서와 대조한 결과 건물 ID·PNU·주소·용도·구조·면적·사용승인일·높이는 있지만 `A26 지상층수`와 `A27 지하층수`는 2022 스키마에 없다. 따라서 이 파일만으로 전국 지하층 후보를 만들 수 없다.
- 경북 2020~2022 원본도 23필드·EPSG:5174이고, 2023은 24필드·EPSG:5186, 2024~2025는 29필드·EPSG:5186다. 현재 경북 지하층 특징표는 A27이 있는 2025 스냅샷을 사용한다.
- 대용량 전국·경북 VWorld 원본과 전국 침수 GeoJSON은 재배포 조건 확인 전 로컬 전용이다. Git에는 재현 스크립트·manifest·QA·필드 사전만 포함한다.
- 산출물: `data/interim/flood-trace/korea_flood_records.csv`, `data/interim/vworld-buildings/national_2022-12-03_inventory.csv`, `data/interim/vworld-buildings/national_2022-12-03_field_dictionary.csv`, `data/catalog.csv`
- 상세: [전국 데이터 및 코드 감사](./08-national-data-and-code-audit.md)
- 출처: [Esri Korea 전국 침수흔적도](https://www.arcgis.com/home/item.html?id=36b15209737c49b3893332c71db04a27), [VWorld GIS건물통합정보](https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?svcCde=NA&dsId=18)
- 확인일: 2026-08-22

### 2026-08-23 — 워드마크·스플래시와 상세 화면 실지도 연결

- `FACT`: Figma `123:2252`의 흰색 `WATERPARK`와 스플래시 `266:3497`의 그라데이션 워드마크를 투명 배경 SVG 에셋 기반 공통 컴포넌트로 만들고 임시 `APP` 표시를 모두 교체했다.
- `FACT`: Figma `50:84`의 원본 이미지 두 개를 저장해 쿼리 없는 최초 진입 스플래시를 구현했다. 예시 iOS 상태바는 기존 UI 결정에 따라 제외했다.
- `FACT`: 위험 상세 `119:1140`과 안전 상세 `123:1743`이 `VITE_KAKAO_MAP_APP_KEY`를 받아 실제 Kakao 지도·계산 경로·마커를 표시하도록 변경했다.
- `FACT`: `localhost:5173` 브라우저에서 두 상세 화면의 Kakao 지도 타일과 접근 가능한 지도 region을 확인했고 TypeScript build와 ESLint를 통과했다.
- `LIMITATION`: Kakao 지도는 등록 origin과 활성 JavaScript 키가 필요하며, 실패 시 정적 경로 미리보기로 폴백한다.
- `DECISION`: 스플래시는 1.6초 유지 후 1.1초 동안 전체 화면을 페이드아웃하고, 페이드가 끝난 다음 온보딩으로 전환한다. Figma 원본 노드에는 별도 모션 데이터가 없어 사용자 요청을 앱 전환 명세로 기록했다.
- `DECISION`: 위험 폴리곤은 Figma `244:3303`을 기준으로 청록색 저투명도 외곽과 내부 레이어를 겹친 발광 표현을 사용한다. 상세 위험 예측 시간은 제품 설명과 같은 1시간으로 통일한다.
- 상세: [워드마크·스플래시·상세 실지도](./frontend/09-brand-splash-and-live-detail-maps.md)
- 출처: [Figma 워드마크 `123:2252`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2252&m=dev), [Figma 스플래시 `50:84`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=50-84&m=dev), [Figma 위험 상세 `119:1140`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=119-1140&m=dev), [Figma 안전 상세 `123:1743`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1743&m=dev), [Figma 청록색 위험 영역 `244:3303`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=244-3303&m=dev)

## 결정 로그

| ID | 날짜 | 결정 | 상태 |
| --- | --- | --- | --- |
| D-001 | 2026-08-22 | 경상북도 공공데이터 챌린지로 참가한다. | `DECISION` |
| D-002 | 2026-08-22 | 서비스명을 Waterpark로 확정한다. | `DECISION` |
| D-003 | 2026-08-22 | 지하주차장 침수 위험 예측 및 차량 사전 대피 안내 서비스를 개발한다. | `DECISION` |
| D-004 | 2026-08-22 | 현재 개발 순서를 데이터 판별·전처리, 머신러닝, 백엔드, 프론트엔드 전달로 둔다. | `DECISION` |
| D-005 | 2026-08-22 | 데이터 수집·통합 기본 범위를 포항이 아닌 경상북도 22개 시군 전체로 둔다. | `DECISION` |
| D-006 | 2026-08-22 | 지하주차장 침수 지도학습은 양성 9건으로 불가하므로, 규칙 기반 위험점수를 주력으로 하고 지표면 침수 XGBoost를 보조로 병행한다. | `DECISION` |
| D-007 | 2026-08-22 | 프론트엔드 로우파이는 React·TypeScript·Vite로 구현한다. | `DECISION` |
| D-008 | 2026-08-22 | 지도·주소·주차장 검색은 Kakao 지도 JavaScript SDK를 우선 사용하고, 키가 없거나 실패하면 경북 공영주차장 좌표 데이터로 전환한다. | `DECISION` |
| D-009 | 2026-08-22 | 경로 MVP는 현재 침수 영향권 간선을 제거하고 예측·상시 위험 노출에는 비음수 패널티를 적용하며, 사용자에게 `안전 경로`가 아닌 `저위험 경로 후보`로 표시한다. | `DECISION` |

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
