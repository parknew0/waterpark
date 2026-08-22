# Waterpark 경상북도 건물·고도 실제 추출 결과

> 실행일: 2026-08-22
>
> 범위: 경상북도 22개 시군 전체, 울릉도 포함
>
> 상태: 건물 대표점·위경도·30m DSM 표고를 실제 생성했다. 공식 지하주차장 여부는 인증 차단 때문에 아직 전수 확정하지 못했다.

## 1. 결과 요약

| 항목 | 결과 | 판정 |
| --- | ---: | --- |
| 경북 건물 행 | 305,058 | 생성 완료 |
| 시군 배정 | 22개 시군, 결측 0행 | 범위 검증 완료 |
| 위도·경도 | 305,058행 | 생성 완료 |
| Copernicus GLO-30 표고 | 304,929행 | 99.96% 확보 |
| 표고 결측 | 129행 | 해안·타일 경계 점검 대상 |
| Overture 지하층수 값 | 6행 | 전수성 없음 |
| 공식 지하주차장 확정 | 0행 | 인증 원본 미확보 |
| 지하주차장 미상 | 305,058행 | 임의 추정 금지 |

305,058행은 공공데이터포털의 공식 건축물대장 건물 수가 아니다. 무계정으로 즉시 받을 수 있는 Overture Maps 2026-08-19.0 건물 도형 634,311개를 경상북도 육지 행정경계의 건물 대표점으로 절단한 대체 공개 원천 결과다.

## 2. 생성 파일

| 파일 | 내용 | 용도 |
| --- | --- | --- |
| `data/processed/gyeongbuk_buildings_elevation.parquet` | 305,058행 전체, WKB 건물 도형 포함 | 공간분석·모델 전처리 기본 파일 |
| `data/processed/gyeongbuk_buildings_elevation.csv.gz` | 305,058행 전체, 도형 제외 | 일반 분석 도구 전달 |
| `data/processed/gyeongbuk_buildings_elevation.manifest.json` | 행 수·해시·원천 릴리스·한계 | 재현·검증 |
| `outputs/gyeongbuk-buildings/gyeongbuk_buildings_elevation_sample.csv` | 앞 20,000행 표본 | 빠른 열람 |
| `outputs/gyeongbuk-buildings/gyeongbuk_buildings_by_municipality.csv` | 22개 시군 통계 | 범위·분포 검증 |
| `outputs/gyeongbuk-buildings/waterpark_gyeongbuk_buildings_elevation.xlsx` | 요약·시군 통계·20,000행 표본·재실행 조건 | 팀 공유 |

전체 행 분석에는 XLSX 표본이 아니라 Parquet를 사용한다.

## 3. 실제 원천과 다운로드

### 건물과 행정경계

- 원천: Overture Maps Foundation Open Map Data
- 릴리스: `2026-08-19.0`
- 다운로드 상자: `127.7964166,35.5663752,130.9403174,37.5491021`
- 최초 건물 후보: 634,311개
- 경북 육지 경계 절단 후: 305,058개
- 경북 행정경계 식별 조건: `country=KR`, `region=KR-47`, `admin_level=1`, `class=land`, `names.primary=경상북도`
- 시군 식별 조건: 같은 경북 범위의 `admin_level=2`, 총 22개

Overture는 OSM·Esri Community Maps 등 여러 공개 원천을 결합한다. 대한민국 공식 건축물대장과 완전성·식별자가 같다고 가정하지 않는다.

### 표고

- 원천: Copernicus DEM GLO-30 Public
- 릴리스: 2021
- 형식: Cloud Optimized GeoTIFF
- 격자: 약 30m, 1 arc-second
- 사용 타일: 경북 경계와 교차하는 9개 1도 타일
- 타일 범위: `N35/E127~E129`, `N36/E127~E129`, `N37/E128~E130`

Copernicus 자료는 이름과 달리 지표면의 건물·기반시설·식생을 포함할 수 있는 DSM이다. 건축물 출입구 바닥고나 순수 지형 DTM으로 단정하지 않는다.

## 4. 컬럼 의미

| 컬럼 | 의미 | 사용 제한 |
| --- | --- | --- |
| `building_id` | Overture GERS 건물 ID | 공식 관리건축물대장PK가 아님 |
| `latitude`, `longitude` | 건물 Polygon 내부 대표점 WGS84 | 정문·주차장 입구 좌표가 아님 |
| `city_county` | 경북 시군 Polygon 공간포함 결과 | 22개 시군, 결측 0 |
| `surface_elevation_m` | 대표점의 Copernicus DSM 값 | 침수심이 아님 |
| `local_approx_1km_min_surface_elevation_m` | 0.01도 격자 3×3 근방의 건물점 DSM 최저값 | 지형 전체 최저값이 아님 |
| `relative_elevation_to_local_building_min_m` | 현재 건물 표고 - 근방 건물점 최저표고 | 스크리닝 feature 후보 |
| `underground_floor_count_overture` | 공개 지도 원천의 지하층수 | 값이 6행뿐이라 전수 feature로 부적합 |
| `underground_parking_presence` | 지하주차장 판정 상태 | 현재 모든 행 공식 미상 |
| `underground_parking_is_confirmed_official` | 한국 공식 원천 확인 여부 | 현재 모두 `false` |

경북 전체 표고 중앙값은 약 64.61m다. 포항시 건물 중앙값은 약 8.86m로 계산됐지만, 이 수치를 침수 확률이나 안전 기준으로 직접 사용하지 않는다. 해안 일부에는 -6.07m까지 값이 있어 수직기준·해안 픽셀·DSM 오차를 추가 검토해야 한다.

## 5. 지하주차장 정확값이 비어 있는 이유

### 확인한 공식 경로

1. 건축HUB 표제부는 `관리건축물대장PK`, `지하층수`, 옥내·옥외 자주식·기계식 주차대수를 제공한다.
2. 건축HUB 층별개요는 지하층 코드와 주용도·기타용도·면적을 제공한다.
3. VWorld 연속수치지형도 건물 경북 파일은 `dsId=30162`, `fileNo=25`, 표시 용량 279MB다.

### 실제 차단

- VWorld 직접 다운로드 호출은 로그인하지 않은 세션에 0바이트를 반환했다.
- VWorld 화면 코드도 다운로드 전에 로그인 여부를 검사한다.
- 건축HUB OpenAPI `15134735`는 공공데이터포털 서비스키가 필수다.
- 건축HUB 공개 화면에서 경상북도와 22개 시군 필터·필드 목록은 확인했지만, 전수 내보내기에는 인증 또는 정상 조회 실행이 필요했다.
- 현재 실행 환경에는 공공데이터포털 서비스키와 로그인된 외부 브라우저 세션이 없었다.

따라서 `지하층수 > 0` 또는 `옥내주차대수 > 0`을 지하주차장 `TRUE`로 바꾸지 않았다. 정보 없음도 `FALSE`로 바꾸지 않았다.

## 6. 공식 지하주차장 값을 채우는 재실행 규칙

### 필요한 원본

- 건축HUB 표제부: 경북 22개 시군
- 건축HUB 층별개요: 경북 22개 시군
- VWorld 건물_경북 SHP 또는 GIS건물통합정보

### 판정

```text
has_underground_parking = TRUE
if exists floor_row where
    floor_type_code == "10"
    and excluded_area_flag != "1"
    and area > 0
    and (main_use_name or other_use contains "주차장")
```

표제부와 층별개요는 `관리건축물대장PK`로 결합한다. 현재 Overture 건물과 공식 SHP의 식별자는 다르므로, 공식 SHP 확보 후 관리PK 또는 법정동·본번·부번·동명칭의 연결 가능성을 먼저 측정한다.

## 7. 침수 모델에 넣기 전 추가 필수 항목

- 침수흔적도 또는 실제 침수 사건 라벨
- 강우 사건 시계열과 관측소/격자 매칭
- 하천·배수로·하수관망·배수분구
- HAND 또는 유출 방향을 반영한 상대고도
- 주차장 입구 위치·경사로 최저점·방수턱 높이
- 공식 지하주차장 존재 여부의 결측률·표본 정확도

현재 `surface_elevation_m`과 상대고도는 정적 취약도 후보일 뿐, 단독으로 “침수된다/안 된다”를 판정하지 않는다.

## 8. 재현

임시 Python 의존성에 `overturemaps`, `pyarrow`, `shapely`, `rasterio`, `pandas`가 필요하다.

```bash
python scripts/build_gyeongbuk_building_elevation_dataset.py
node scripts/build_gyeongbuk_building_elevation_workbook.mjs
```

입력·출력 SHA-256은 `data/processed/gyeongbuk_buildings_elevation.manifest.json`에 기록했다.

## 9. 출처

| 출처 | 확인 내용 | 확인일 |
| --- | --- | --- |
| [Overture Python Client](https://docs.overturemaps.org/getting-data/overturemaps-py/) | bbox 기반 건물·행정경계 다운로드 | 2026-08-22 |
| [Overture AWS 공개 데이터](https://registry.opendata.aws/overture/) | 공개 GeoParquet 원천·라이선스 | 2026-08-22 |
| [Overture 릴리스](https://docs.overturemaps.org/release-calendar/) | 최신 릴리스 판별 | 2026-08-22 |
| [Copernicus DEM AWS 공개 데이터](https://registry.opendata.aws/copernicus-dem/) | GLO-30 COG 공개 버킷·DSM 설명 | 2026-08-22 |
| [Copernicus DEM 데이터 구조](https://copernicus-dem-30m.s3.amazonaws.com/readme.html) | 1도 타일명·해상도·형식 | 2026-08-22 |
| [연속수치지형도 건물](https://www.data.go.kr/data/15125047/fileData.do) | 공식 건물 SHP의 VWorld 경로 | 2026-08-22 |
| [VWorld 건물 데이터](https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?dsId=30162) | 경북 파일 번호·용량·로그인 검사 | 2026-08-22 |
| [건축HUB 건축물대장정보 서비스](https://www.data.go.kr/data/15134735/openapi.do) | 표제부·층별개요 API와 서비스키 필수 | 2026-08-22 |
