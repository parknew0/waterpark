# Waterpark 경상북도 데이터 통합 실행서

> 확인일: 2026-08-22
>
> 범위: 경상북도 22개 시군 전체
>
> 상태: 공개 원자료 1종을 실제 확보·정규화했다. 핵심 학습 데이터 D1~D6은 인증·로그인 또는 연결 키 확인이 남아 있어 완전 조인 전이다.

## 1. 이번 작업의 결론

공식 전국주차장정보표준데이터 18,879행을 내려받아 경상북도 22개 시군의 2,010행을 추출했다. 이 중 1,986행은 위도·경도가 있고 24행은 좌표가 없다.

이 자료는 침수 예측의 학습 행이 아니라 **차량 대피 목적지 후보**다. 건물×호우 사건 학습표에 주차장 행을 억지로 붙이지 않는다. 대신 하나의 전달용 [통합 워크북](../data/processed/waterpark_gyeongbuk_integration.xlsx)에 다음을 담았다.

- `경북_주차장_원본`: 실제 확보한 경북 주차장 후보 2,010행
- `조인_준비상태`: 핵심 D1~D6과 보조 S1의 접근·확보 상태
- `컬럼_사전`: 현재 컬럼의 의미와 안전상 주의사항

현재 워크북은 모델 학습용 완성 데이터가 아니다.

## 2. 범위 변경

기존 외부 실행계획의 포항시 남구 파일럿 가정은 이번 데이터 수집 범위에 적용하지 않는다. 기본 필터는 경상북도 22개 시군 전체다.

```text
포항시, 경주시, 김천시, 안동시, 구미시,
영주시, 영천시, 상주시, 문경시, 경산시,
의성군, 청송군, 영양군, 영덕군, 청도군,
고령군, 성주군, 칠곡군, 예천군, 봉화군,
울진군, 울릉군
```

포항은 경상북도 전체 데이터의 한 부분으로만 취급한다.

## 3. 실제 확보한 파일

| 경로 | 내용 | 행 수 | 상태 |
| --- | --- | ---: | --- |
| `data/raw/parking_standard_header.json` | 공식 컬럼·전체 행 메타데이터 | 34개 컬럼 | `FACT` |
| `data/raw/parking_standard_page_1.json` | 전국주차장 원본 1페이지 | 10,000 | `FACT` |
| `data/raw/parking_standard_page_2.json` | 전국주차장 원본 2페이지 | 8,879 | `FACT` |
| `data/processed/gyeongbuk_parking_seed.csv` | 경북 22개 시군 정규화 결과 | 2,010 | `FACT` |
| `data/processed/gyeongbuk_parking_seed.manifest.json` | 행 수·좌표 결측·시군별 집계 | 1 | `FACT` |
| `data/processed/waterpark_gyeongbuk_integration.xlsx` | 전달용 통합 워크북 | 3개 시트 | `FACT` |

원자료는 2026-08-22에 [공공데이터포털 전국주차장정보표준데이터](https://www.data.go.kr/data/15012896/standard.do)의 공개 다운로드 요청을 사용해 확보했다.

## 4. 현재 조인 상태

| ID | 데이터 | 역할 | 접근 상태 | 판정 |
| --- | --- | --- | --- | --- |
| `D1` | 침수흔적도 | 건물×사건 라벨 | 회원가입·활용신청 필요 | `BLOCKED_AUTH` |
| `D2` | ASOS/AWS 강수 | 시간별 강수 feature | 지점·기간 선택 필요 | `OPEN_SELECTION` |
| `D3` | 건축물대장 | 지하층·용도·주차 속성 | 파일/API와 연결 키 확인 필요 | `OPEN_KEY` |
| `D4` | GIS건물통합정보 | 기준 건물 Polygon | VWorld 로그인 필요 | `BLOCKED_LOGIN` |
| `D5` | DEM | 표고·상대고도·경사 | 국토정보플랫폼 로그인 필요 | `BLOCKED_LOGIN` |
| `D6` | 하천중심선 | 최근접 하천 거리 | VWorld 로그인 필요 | `BLOCKED_LOGIN` |
| `S1` | 전국주차장 표준데이터 | 대피 후보 | 공개 다운로드 완료 | `SOURCE_ONLY` |

침수흔적도 API는 회원가입과 활용 신청이 필요하고 샘플 다운로드는 조회 결과의 첫 100건으로 제한된다. DEM은 무료지만 국토정보플랫폼 로그인과 영역 지정 다운로드가 필요하다. 따라서 두 자료를 다운로드 완료로 기록하지 않는다.

## 5. 하나의 학습 데이터로 만드는 기준

최종 모델 데이터의 행 정의는 다음과 같다.

```text
한 행 = building_id + event_id + as_of_time
```

```text
building_id, event_id, as_of_time,
main_purpose, underground_floor_count, parking_capacity,
elevation_m, relative_elevation_m, slope,
nearest_river_distance_m,
rain_1h, rain_6h, rain_24h,
historical_flood_overlap, overlap_ratio, flooded_within_60m,
source_version, quality_flag
```

### 5.1 기준 건물과 공간 조인

`D4 GIS건물통합정보`의 Polygon을 기준으로 `building_id`를 정한다. `D3 건축물대장`은 관리PK를 우선 검사하고, 불가능하면 법정동 코드·본번·부번 조합을 사용한다.

- 건물 Polygon 또는 대표점에서 `D5 DEM` 표고를 추출한다.
- 주변 창으로 상대고도와 경사를 만든다.
- `D6 하천중심선`과 건물 Polygon 사이 최소 거리를 계산한다.
- `D1 침수 Polygon`과 건물 Polygon의 교차 면적 비율을 계산한다.

거리·면적 계산은 미터 단위 투영좌표계에서 수행한다. 실제 입력 파일의 CRS 확인 전 특정 EPSG를 확정하지 않는다.

### 5.2 시간 조인과 라벨

침수 사건의 기준시각 이전 1·6·24시간 강수량을 경북 관측소에서 계산한다. 관측소 한 곳의 값을 경북 전체 건물에 복제하지 않는다. 최근접 관측소, 거리 제한과 결측 대체 규칙은 실제 지점 분포 확인 후 결정한다.

침수 Polygon과 겹치지 않는다는 이유만으로 `flood=0`을 만들지 않는다. 같은 사건의 조사 범위 안에서 비침수로 확인된 건물만 음성 후보로 쓴다. 건물별 침수 시작시각이 없으면 `flooded_within_60m` 확률 모델을 바로 학습하지 않는다.

## 6. 주차장 데이터 사용법

현재 CSV의 `elevation_m`, `relative_elevation_m`, `historical_flood_overlap`, `nearest_river_distance_m`은 비어 있고 `safety_verified`는 전부 `false`다. 다음을 확인하기 전 “안전 주차장”이라고 부르지 않는다.

- 지상·옥외 여부
- DEM 상대고도와 과거 침수 중첩
- 접근 도로 위험 여부
- 운영기관의 재난 대피 활용 승인
- 실시간 여석의 별도 확보 여부

표준데이터의 `capacity`는 주차구획수이며 실시간 여석이 아니다.

## 7. 재현 방법

원본 JSON이 있는 상태에서 다음 순서로 다시 만든다.

```bash
node scripts/build_gyeongbuk_parking_seed.mjs
node scripts/build_gyeongbuk_integration_workbook.mjs
```

두 번째 스크립트는 Codex 번들의 `@oai/artifact-tool` 런타임을 전제로 한다. 원자료 갱신 시 전국 행 수, 경북 행 수, 22개 시군 포함 여부, `entity_id` 중복과 좌표 결측을 다시 검사한다.

## 8. 다음 수집 순서

1. `D4 GIS건물통합정보` 경북 22개 시군 파일과 정의서를 확보한다.
2. `D3 건축물대장` 경북 파일을 확보해 연결 키와 매칭률을 계산한다.
3. `D1 침수흔적도` 활용 신청 후 경북 전체 페이지를 받아 사건 수·시각 결측률을 계산한다.
4. `D5 DEM`과 `D6 하천중심선`을 경북 경계로 클리핑한다.
5. `D2`는 경북 관측소 목록·기간·결측을 본 뒤 ASOS/AWS 조합을 결정한다.
6. D1~D6이 갖춰진 뒤 건물×사건×시각 학습표를 생성한다.

## 9. 검증 결과

- 경북 행 수: 2,010
- 고유 `entity_id`: 2,010
- 포함 시군: 22개
- 좌표 보유: 1,986
- 좌표 결측: 24
- XLSX 컨테이너 검사: 정상
- `entity_id`는 원천의 관리번호 중복을 피하기 위해 기관·관리번호·명칭·주소·좌표의 안정 해시로 만들었다.

## 10. 공식 출처

| 출처 | 확인 내용 | 확인일 |
| --- | --- | --- |
| [전국주차장정보표준데이터](https://www.data.go.kr/data/15012896/standard.do) | 전국 원본 공개 다운로드, 표준 컬럼 | 2026-08-22 |
| [침수흔적도](https://www.safetydata.go.kr/disaster-data/view?dataSn=3846) | API 활용신청, 샘플 100건 제한 | 2026-08-22 |
| [국토지리정보원 DEM](https://www.data.go.kr/data/15059920/fileData.do) | IMG, 무료, 로그인·영역 지정 다운로드 | 2026-08-22 |
| [GIS건물통합정보](https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?svcCde=NA&dsId=18) | 건물 Polygon 후보, 로그인 필요 | 2026-08-22 |
| [국가기본도 하천중심선](https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?svcCde=MK&dsId=20250122DS00008) | 하천 선형과 정의서 후보 | 2026-08-22 |

## 11. 한계

- D1~D6 전체 원본을 아직 확보하지 못했으므로 모델용 완전 조인은 없다.
- 주차장 표준데이터는 제공기관별 갱신 시점과 품질 편차가 있을 수 있다.
- VWorld·침수흔적도의 가공·재배포 조건은 각각 다시 확인해야 한다.
- 경북 전역 단일 모델이 적합한지는 독립 침수 사건 수와 시군별 데이터 편차를 본 뒤 판단한다.
