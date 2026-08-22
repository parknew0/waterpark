# Waterpark 데이터 디렉터리

> 확인일: 2026-08-22
>
> 이 폴더에는 원본, 중간 결과, 모델 입력·출력이 함께 있다. 파일의 정확한 현재 위치와 행 수는 [`catalog.csv`](./catalog.csv)를 기준으로 확인한다.

## 가장 먼저 알아둘 것

- `raw`는 내려받은 원본이다. 원본의 값이나 도형을 직접 고치지 않는다.
- `interim`은 원본을 정규화하거나 검사하기 위해 만든 중간 결과다.
- `processed`는 분석·모델·서비스가 실제로 읽는 가공 결과다.
- 카탈로그의 빈 `row_count`는 0행이 아니라 **아직 행 수를 확인하지 않았다는 뜻**이다.
- `READY_WITH_LIMITATIONS`는 파일을 사용할 수 있지만 라벨·공간범위·시각 또는 원천 자체에 중요한 한계가 있다는 뜻이다.
- VWorld 전국·경북 원본은 소스 페이지의 `CC BY` 배지는 확인했지만, 원본 재호스팅·2차 배포 조건을 검토하지 않았으므로 현재 **로컬 전용**이다. Git에 강제로 추가하지 않는다.

## 폴더 역할

```text
data/
├── raw/          내려받은 원본과 API 원응답
├── interim/      정규화·필터·QA·후보 판정 결과
├── processed/    모델과 서비스가 사용하는 데이터
├── catalog.csv   현재 데이터 목록
└── README.md     이 안내서
```

### `raw`

현재 주요 원본은 다음과 같다.

- `flood-trace/`: 전국·경북 침수흔적 GeoJSON과 전국 원본 검증 manifest
- `vworld-buildings/gyeongbuk/`: 2020~2025년 경북 GIS건물통합정보 Shapefile
- `vworld-downloads/national/2022-12-03/`: 전국 17개 시도 건물 ZIP 묶음. 원본을 영구 추출하지 않고 CRC·DBF·PRJ·스키마를 검사했다.
- `building-register/`: 건축HUB 표제부·층별개요 API 원응답과 실행 체크포인트
- `kma-rain/`, `kma-stations/`: KMA 강수 원응답과 관측지점정보
- `parking_standard_*.json`: 전국주차장정보표준데이터 원본 페이지

Shapefile은 하나의 `.shp`만으로 완성되지 않는다. 같은 basename의 `.shp`, `.shx`, `.dbf`, `.prj`, `.cpg` 또는 `.fix`를 항상 한 묶음으로 보존한다.

### `interim`

- `flood-trace/`: 전국 속성표, 시도·연도 QA, 경북 사건 후보
- `building-register/`: GIS 지하층 후보와 건축물대장 후보 판정표
- `vworld-buildings/`: 전국 2022 원본의 24개 Shapefile part 인벤토리, 23개 필드 사전과 검증 manifest. DBF 헤더 행 수 합계는 13,885,793, CRS는 모두 EPSG:5174다.

전국 13,885,793행은 DBF 헤더에 선언된 행 수의 합계다. deleted-record flag를 아직 세지 않았으므로 실제 유효 레코드 수와 다를 가능성은 남아 있다. `A1` 공백·중복과 geometry 유효성·topology도 아직 확인하지 않았다.

중요하게, 2022 전국 스냅샷의 23개 필드는 `A0~A22`다. `A26 지상층수`와 `A27 지하층수`는 2024~2025의 29필드 스키마에만 있고 이 전국 파일에는 없다. 따라서 전국 2022 자료는 건물 위치·PNU·용도·구조·면적·사용승인일 등을 제공하지만, 전국 지하층 여부 원천으로는 사용할 수 없다. 정확한 대응은 `national_2022-12-03_field_dictionary.csv`에서 확인한다.

전국 침수 원본의 self-intersection 22건은 원본에서 고치지 않았다. 이후 공간 연산에 복구본이 필요하면 별도 `interim/geometry-repaired/`에 만들고 원본 objectid와 복구 방법을 기록한다.

전국 전체 속성표 `flood-trace/korea_flood_records.csv`도 원본 38,003건의 속성을 그대로 담으므로 재배포 조건 확인 전에는 로컬 전용이다. Git에는 재현 스크립트, manifest와 시도·연도별 집계 QA만 둔다.

### `processed`

- `buildings/`: 건물 좌표·지하층·지하주차장 근거·대체 표고 특징
- `rainfall/`: 침수 시작일시와 관측소별 누적 강수 특징
- `ml/training/`: XGBoost 실험용 학습표
- `ml/predictions/`: 규칙 또는 모델이 만든 위험 결과
- `parking/`: 경북 공영주차장 후보

`gyeongbuk_flood_training_table.csv`의 정답은 **지하주차장 침수 여부가 아니라 지표면 침수 여부**다. 이 차이를 지우거나 이름만 바꿔 지하주차장 침수 정답처럼 사용하면 안 된다.

## 카탈로그 다시 만들기

저장소 루트에서 실행한다.

```bash
python3 scripts/build_data_catalog.py
```

이 명령은 다음만 읽는다.

- CSV·CSV.GZ의 실제 레코드와 헤더
- JSON·JSONL의 실제 레코드와 키
- DBF 헤더의 행·필드 수
- ZIP 중앙 디렉터리의 파일 목록과 검증된 인벤토리 값
- 파일과 디렉터리의 실제 바이트 수

대용량 ZIP을 풀거나 원본을 수정하지 않는다. Parquet 행 수처럼 표준 라이브러리만으로 읽지 않는 값은 검증된 manifest 값을 사용하며 카탈로그의 `verification_status`에 그 근거를 표시한다.

## 카탈로그 상태 읽는 법

| 컬럼 | 의미 |
| --- | --- |
| `stage` | `raw`, `interim`, `processed`, `run-log` |
| `row_count` | 실제 파싱값 또는 검증 manifest 값. 빈칸은 미확인 |
| `column_count` | 실제로 확인한 데이터 필드 수 |
| `member_count` | ZIP처럼 컨테이너 형식인 파일 안에서 확인한 멤버 수 |
| `crs` | 실제 PRJ·manifest 확인값 또는 `OPEN` |
| `availability_status` | 지금 사용할 수 있는지와 제한 여부 |
| `verification_status` | 무엇을 실제로 검사했는지 |
| `repository_policy` | Git 추적 또는 로컬 전용 정책 |
| `license_status` | 재사용·재배포 조건 확인 상태 |
| `derived_from` | 이 결과를 만든 상위 데이터셋 ID |

## 원본과 Git

- `.gitignore`에 포함된 대용량 원본은 로컬에만 둔다.
- 다른 팀원이 같은 파일을 다시 받을 수 있도록 다운로드 스크립트, URL, 기준일, SHA-256, 행 수를 manifest와 문서에 남긴다.
- 재배포 권리가 확인되지 않은 원본 ZIP·SHP를 GitHub Release나 다른 저장소에 올리지 않는다.
- API 인증키는 `.env`에만 두며 CSV, 로그, manifest에 기록하지 않는다.

전국 데이터와 코드의 현재 한계는 [전국 데이터 및 코드 감사](../docs/08-national-data-and-code-audit.md)에 정리되어 있다.
