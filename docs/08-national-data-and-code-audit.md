# Waterpark 전국 데이터 및 코드 감사

> 확인일: 2026-08-22
>
> 범위: 현재 로컬 워크스페이스의 전국 침수흔적도, 전국·경북 VWorld GIS건물통합정보, 가공 데이터와 `scripts/` 경로 참조
>
> 표기: `FACT`는 파일·manifest·헤더·코드에서 직접 확인한 내용, `OPEN`은 아직 확인하지 못한 내용, `PROPOSAL`은 이후 정리 제안이다.

## 1. 결론

- `FACT` 전국 침수흔적도 38,003건은 다운로드와 1차 전처리·QA까지 완료됐다.
- `FACT` 전국 VWorld GIS건물통합정보 2022 묶음의 외부 CRC, 내부 17개 시도 ZIP, 24개 Shapefile part, DBF 헤더, PRJ와 스키마를 검사했다.
- `FACT` 전국 VWorld의 DBF 헤더 행 수 합계는 13,885,793, 모든 part는 공통 23필드이며 CRS는 EPSG:5174다.
- `FACT` 공식 컬럼 정의서와 대조한 결과 2022년의 23필드는 `A0~A22`이며, `A27 지하층수`는 포함되지 않는다.
- `OPEN` deleted-record flag를 반영한 실제 유효 행 수, `A1`·PNU 품질, geometry 유효성·topology는 아직 검증하지 않았다.
- `OPEN` VWorld 원본을 GitHub나 다른 공개 장소에 재배포할 권리는 확인되지 않았다. 따라서 원본은 로컬 전용으로 취급한다.
- `FACT` 주요 Python·JavaScript 파이프라인은 새 `raw/interim/processed` 경로로 전환됐고 재실행도 완료했다. Python 스크립트는 `scripts/data_paths.py`를 공통으로 사용한다.
- `OPEN` 표고 파이프라인의 원천 Overture·DEM·경북 경계 파일은 현재 로컬에 없어 그 가공 단계만 원본부터 재현하지 못한다.
- `FACT` 전국 원본을 확보했다는 사실만으로 전국 XGBoost 학습표가 완성된 것은 아니다. 전국 강수·지형·라벨 연결과 사건 분리는 아직 구현되지 않았다.

현재 데이터별 경로·행 수·CRS·상태는 [`data/catalog.csv`](../data/catalog.csv)에서 확인한다. 카탈로그는 [`scripts/build_data_catalog.py`](../scripts/build_data_catalog.py)로 재생성한다.

## 2. 전국 침수흔적도

### 확인된 사실

| 항목 | 확인값 |
| --- | --- |
| 원본 | `data/raw/flood-trace/korea_flood_2002_2022.geojson` |
| 원본 크기 | 56,963,218 bytes |
| 행 단위 | 침수 Polygon 또는 MultiPolygon 한 건 |
| 행 수 | 38,003 |
| 원본 속성 | 16개 |
| 공간범위 | 법정 시도코드 17개 |
| CRS | EPSG:4326, longitude/latitude |
| 원천 CRS | EPSG:3857, 다운로드 시 `outSR=4326` 요청 |
| objectid | 1~38,003, 중복 없음 |
| 도형 | Polygon 37,898건, MultiPolygon 105건 |
| 좌표 누락 | 0건 |
| topology invalid | self-intersection 22건 |
| 전처리 속성표 | `data/interim/flood-trace/korea_flood_records.csv`, 38,003행 |
| 시도 QA | 17행 |
| 연도 QA | 21행 |

`FACT` 원본 SHA-256은 `e46e69e1e633144fd2d09497508281b3172a76a7e9ddb1a295d8183535f3e0ea`이며 다운로드 manifest와 전처리 manifest가 이를 검증한다.

`FACT` 연도 값은 `0`, 2002~2003, 2005~2022로 21종이다. `0`은 Esri 설명에서 원자료의 `외` 값을 변환한 것으로 안내되므로 실제 0년 사건으로 해석하면 안 된다.

`FACT` 침수 시작시각은 988건이 비어 있고 8,789건이 `0000`이다. 둘을 합한 9,777건은 신뢰할 수 있는 세부 시각으로 사용하지 않는다. 종료시각은 결측 991건, `0000` 6,933건이다.

`FACT` 현재 1차 전처리는 속성명을 바꾸지 않았고 `event_id`도 만들지 않았다. 날짜·시각 조합이 곧 독립적인 호우 사건이라는 근거가 없기 때문이다.

`FACT` 전국 원본 GeoJSON과 38,003건 전체 속성표는 재배포 조건 확인 전 로컬 전용이다. Git에는 다운로드·전처리 코드, manifest, 시도·연도별 집계 QA만 포함한다.

### 아직 확인하지 않은 것

- `OPEN` 22개 invalid Polygon을 어떤 방식으로 복구할지 정하지 않았다.
- `OPEN` 동일 태풍·집중호우에 속한 여러 날짜·시각·지역 기록을 하나의 사건으로 묶는 규칙이 없다.
- `OPEN` 전국 학습에 사용할 조사영향권과 pseudo-negative 생성 규칙을 전국 단위로 검증하지 않았다.
- `OPEN` 원 제공기관과 Esri Korea 조건상 가공본·모델·원본 geometry를 어디까지 재배포할 수 있는지 최종 확인하지 않았다.

원본 도형은 수정하지 않는다. 복구가 필요하면 원본 objectid를 유지한 별도 중간 파일과 복구 전후 QA를 만든다.

## 3. 전국 VWorld GIS건물통합정보 2022

### 확인된 사실

| 항목 | 확인값 |
| --- | --- |
| 경로 | `data/raw/vworld-downloads/national/2022-12-03/vworld_gis_buildings_national_2022-12-03.zip` |
| 크기 | 1,548,576,788 bytes, 약 1.44 GiB |
| SHA-256 | `4bd30f10312bb7914e412c516e19c7e41f1ab049a09961b1d4d8c36bf354194d` |
| 외부 ZIP 내부 | 시도별 ZIP 17개 |
| Shapefile part | 24개 |
| DBF 헤더 행 수 합계 | 13,885,793 |
| DBF 필드 | 모든 part에서 동일한 23개 (`A0`~`A22`) |
| CRS | 모든 part EPSG:5174 |
| 외부 ZIP CRC | 정상 |
| 원본 추출 | 영구 추출하지 않고 임시 스트리밍 검사 |
| 기준일 | 모든 내부 ZIP 이름에 `20221203` 표기 |
| Git 정책 | `.gitignore` 적용, 로컬 전용 |

확인한 시도코드는 `11, 26, 27, 28, 29, 30, 31, 36, 41, 42, 43, 44, 45, 46, 47, 48, 50`이다. 시도별 DBF 헤더 행 수는 다음과 같다.

| 시도코드 | DBF 헤더 행 수 | SHP part |
| --- | ---: | ---: |
| 11 | 668,529 | 1 |
| 26 | 453,165 | 1 |
| 27 | 308,122 | 1 |
| 28 | 283,169 | 1 |
| 29 | 185,405 | 1 |
| 30 | 168,550 | 1 |
| 31 | 237,763 | 1 |
| 36 | 75,124 | 1 |
| 41 | 2,175,360 | 3 |
| 42 | 731,992 | 1 |
| 43 | 809,570 | 1 |
| 44 | 1,285,338 | 2 |
| 45 | 922,826 | 1 |
| 46 | 1,588,671 | 2 |
| 47 | 2,014,201 | 3 |
| 48 | 1,613,531 | 2 |
| 50 | 364,477 | 1 |

검증 결과는 `data/interim/vworld-buildings/national_2022-12-03_inventory.csv`과 `national_2022-12-03_manifest.json`에 남겼다. 13,885,793은 DBF 헤더에 선언된 행 수이며, deleted-record flag를 아직 세지 않았으므로 “실제 유효 건물 수”로 단정하지 않는다.

### 2022 전국 파일에서 실제로 쓸 수 있는 컬럼

공식 VWorld 컬럼 정의서(2026-01-02판)의 `AL_D010` 773~801행과 실제 DBF 스키마를 대조했다. 2022 전국 파일에 있는 23개 필드는 다음 범주다.

- 식별·조인: `A0 원천도형ID`, `A1 GIS건물통합식별번호`, `A2 PNU`, `A19 건축물ID`, `A21 참조체계연계키`
- 주소·행정: `A3 법정동코드`, `A4 법정동명`, `A5 지번`, `A6~A7 특수지 정보`
- 건물 특징 후보: `A8~A9 용도`, `A10~A11 구조`, `A12 건축물면적`, `A13 사용승인일자`, `A14 연면적`, `A15 대지면적`, `A16 높이`, `A17 건폐율`, `A18 용적률`
- 품질·기준일: `A20 위반건축물여부`, `A22 데이터기준일자`

`A23~A28`은 이 파일에 없다. 특히 Waterpark가 경북 추론에서 사용하는 `A27 지하층수`가 없으므로, 이 2022 전국 묶음 하나만으로 전국 지하층·지하주차장 후보를 만들 수 없다. 전국 자료는 우선 건물 위치·형태·용도와 과거 침수의 공간 관계를 확인하는 데 쓸 수 있고, 지하층 판정은 별도 건축HUB 자료나 더 최신 스키마가 필요하다.

전체 매핑은 `data/interim/vworld-buildings/national_2022-12-03_field_dictionary.csv`에 저장했다. 공식 XLSX 원본은 재배포 조건 확인 전 로컬 전용이며 SHA-256은 `46dd29c6ab681c1e34cf00d91f8f2fe68b7e1868a853315eaa292838238ecb0f`다.

### 아직 확인하지 않은 것

- `OPEN` deleted-record flag를 제외한 실제 유효 DBF 행 수
- `OPEN` SHP geometry 레코드 수와 DBF 행 수의 일치 여부
- `OPEN` `A1` 공백·중복 및 PNU 품질
- `OPEN` geometry 손상·유효성·topology와 시도별 bbox
- `OPEN` 2022년 건물만으로 2002~2022년 과거 사건을 설명할 때 생기는 시간 불일치 규모
- `OPEN` 원본 및 내부 파일의 공개 재배포 권리

카탈로그의 전국 VWorld `row_count=13,885,793`, `column_count=23`, `member_count=17`, `crs=EPSG:5174`는 위 검증 결과를 반영한다. `member_count`는 외부 ZIP의 시도 ZIP 수이며, 24개 Shapefile part 수는 인벤토리에 따로 기록한다.

### 재배포 원칙

소스 페이지의 `CC BY` 배지는 확인했다. 다만 원본 파일 재호스팅·2차 배포에 필요한 조건은 아직 검토하지 않았다. 그 조건이 확인되기 전에는 다음을 하지 않는다.

- Git에 `-f`로 원본 ZIP 또는 추출 SHP 추가
- GitHub Release, Drive 공개 링크 등으로 원본 복제
- 원본이 포함된 Docker image·앱 bundle 배포

현재 허용 범위는 로컬에서 구조와 품질을 검사하고, 재현 코드와 원본에서 비식별적으로 집계한 QA를 저장하는 수준으로 제한한다.

## 4. 경북 VWorld 2020~2025

### 확인된 사실

경북 원본은 `data/raw/vworld-buildings/gyeongbuk/`로 정리돼 있으며 매년 3개 Shapefile 분할 묶음이다. `(2)`, `(3)`은 전체 복사본이 아니라 같은 연도의 다음 분할이다.

| 기준일 | DBF 행 합계 | 필드 수 | CRS |
| --- | ---: | ---: | --- |
| 2020-12-05 | 2,023,861 | 23 | EPSG:5174 |
| 2021-12-04 | 2,015,814 | 23 | EPSG:5174 |
| 2022-12-03 | 2,014,201 | 23 | EPSG:5174 |
| 2023-12-04 | 2,007,948 | 24 | EPSG:5186 |
| 2024-12-04 | 2,009,337 | 29 | EPSG:5186 |
| 2025-12-04 | 2,008,310 | 29 | EPSG:5186 |

`FACT` 필드 수가 `23 → 24 → 29`로 변했다. 여러 연도를 세로로 합치려면 컬럼 정의와 타입을 기준일별로 먼저 정규화해야 한다.

`FACT` `A1`은 완전한 기본키가 아니다. 2020·2021년에는 빈 `A1`이 각각 31,542건, 42,034건이고, 모든 연도에서 비어 있지 않은 중복 `A1`도 확인됐다. 건물 이력 연결에는 `A1`만 쓰지 않고 PNU, 도형, 주소·동명과 기준일을 함께 검증해야 한다.

`FACT` 현재 경북 최종 건물 특징표는 2025-12-04 스냅샷을 사용했다. 2020~2024 스냅샷은 아직 과거 사건별 건물 존재 여부를 판정하는 코드에 연결되지 않았다.

## 5. 현재 데이터 구조

현재 구조는 다음 단계로 구분된다.

```text
data/raw/        원본과 API 원응답
data/interim/    속성 정규화, QA, 후보 판정
data/processed/  건물·강수·학습·위험·주차장 결과
outputs/         사람이 보는 표본, manifest, 모델 보고서
```

`FACT` 도메인별 processed 경로는 만들어졌다.

- `data/processed/buildings/`
- `data/processed/rainfall/`
- `data/processed/ml/training/`
- `data/processed/ml/predictions/`
- `data/processed/parking/`

`FACT` 건축물대장 후보는 최종 결과가 아니므로 `data/interim/building-register/`에 있다.

`FACT` KMA UTF-8 관측소 파일은 내용상 중간 변환본이지만 아직 `data/raw/kma-stations/kma_station_list.csv`에 있다. 카탈로그가 이를 `stage=interim`으로 표시한다.

## 6. 코드 경로 감사

### 경로 전환 상태

`FACT` 주요 Python·JavaScript 파이프라인은 평평했던 이전 경로에서 도메인별 `raw/interim/processed` 경로로 전환됐고, 새 경로에서 재실행도 완료했다.

- `build_flood_training_table.py`, `train_flood_model.py`, `build_underground_parking_risk.py`: `processed/buildings`, `processed/rainfall`, `processed/ml` 경로 사용
- `build_gyeongbuk_building_features.py`, `download_gyeongbuk_building_register.py`: `raw/vworld-buildings/gyeongbuk`, `raw/building-register`, `interim/building-register` 경로 사용
- `build_gyeongbuk_flood_rain_dataset.py`: `interim/flood-trace/gyeongbuk`, `raw/kma-*`, `processed/rainfall` 경로 사용
- 표고·주차장·보고서 생성 스크립트: `processed/buildings`, `processed/parking`, `outputs/reports` 경로 사용
- `download_korea_flood_trace.py`, `prepare_korea_flood_trace.py`: 전국 침수 원본·QA 경로 사용
- `inspect_vworld_national_archive.py`: 전국 VWorld ZIP을 영구 추출하지 않고 인벤토리·manifest 생성
- `build_data_catalog.py`: 현재 파일을 읽어 `data/catalog.csv` 재생성

`FACT` Python 파이프라인은 `scripts/data_paths.py`를 import해 공통 경로 상수를 사용한다. JavaScript 스크립트는 각 파일에 새 정규 경로를 명시한다.

### 남은 재현 공백

`FACT` `build_gyeongbuk_building_elevation_dataset.py`가 요구하는 `data/raw/overture/`, `data/raw/dem/`, `data/interim/gyeongbuk_boundary.geojson`은 현재 로컬에 없다. 가공 Parquet·CSV는 있지만 표고 파이프라인만 원시 입력부터 재생성하지 못한다. 이는 경로 오류가 아니라 원시 파일 부재다.

### 전국 학습 관련 현재 경계

현재 전국에 대해 구현된 범위는 다음까지다.

```text
전국 침수 GeoJSON 다운로드
→ 원본·CRS·건수·필드·topology 검증
→ geometry 없는 전국 속성표와 시도·연도 QA

전국 VWorld 건물 ZIP 다운로드
→ 17개 시도 ZIP·24개 SHP part 인벤토리
→ CRC·DBF 헤더·PRJ·공통 23필드 검증
```

아직 구현되지 않은 범위는 다음이다.

- 전국 VWorld DBF deleted flag·키·geometry 품질 검증과 학습 특징 정규화
- 사건 당시 존재한 건물 또는 격자 기준표 생성
- 전국 사건 단위 정의
- 전국 강수·레이더·수위 연결
- 전국 지형 특징 연결
- 전국 학습표 생성
- 경북 완전 홀드아웃 평가

따라서 “전국 데이터 다운로드 완료”와 “전국 XGBoost 학습 가능”을 같은 상태로 표시하지 않는다.

## 7. 안전한 다음 정리 순서

아래는 `PROPOSAL`이며 채택 결정은 아니다.

1. 주요 경로 전환과 재실행 결과를 유지하고, 새 스크립트도 Python에서는 `data_paths.py`를 사용한다.
2. 전국 VWorld에서 deleted-record flag, `A1`·PNU 공백·중복, SHP↔DBF 레코드 수, geometry 유효성·topology를 스트리밍 또는 임시 추출로 검사한다.
3. 전국 원본에서 만든 manifest와 시도별 QA만 Git에 포함하고 원본·추출 SHP는 계속 ignore한다.
4. 대조 완료된 공통 23필드 중 식별·PNU·용도·구조·면적·사용승인일 최소 컬럼만 정규화한다. 지하층수는 2022 파일에 없으므로 별도 원천으로 다룬다.
5. 과거 2002~2022 사건에 2022년 건물 스냅샷을 붙일 때 생기는 시간 불일치를 먼저 정량화한다.
6. 전국 학습 실험을 하더라도 경북 사건을 완전히 분리한 평가표를 먼저 고정한다.

## 8. 재현 명령

전국 침수 원본이 로컬에 있다는 전제에서 다음 검증은 다시 실행할 수 있다.

```bash
python3 scripts/download_korea_flood_trace.py
python3 scripts/prepare_korea_flood_trace.py
python3 scripts/inspect_vworld_national_archive.py
python3 scripts/build_data_catalog.py
```

대용량 원본이 Git에 없다는 것은 누락이 아니라 의도된 정책이다. 다만 README만으로 재현하려면 각 다운로드의 승인·로그인 조건과 원본 이용조건을 별도로 명확히 적어야 한다.
