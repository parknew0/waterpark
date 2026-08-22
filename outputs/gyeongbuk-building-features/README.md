# 경상북도 건물 지하주차장 특징표

건축물대장 수집 결과와 공식 `GIS건물통합정보` 건물 도형을 합쳐 머신러닝에 바로 넣을 수 있는 형태로 만든 표다.

원자료인 [건축물대장 수집 결과](../gyeongbuk-building-register/README.md)는 83개 컬럼에 좌표가 없고 필지 단위 다대다여서 그대로 학습에 쓸 수 없다. 이 표는 그 세 가지를 정리한 것이다.

| 원자료의 문제 | 이 표에서의 처리 |
| --- | --- |
| 좌표가 없어 침수·강수와 결합 불가 | 건물 폴리곤 중심점을 WGS84 경위도로 계산 |
| `PNU`(필지) 기준이라 행이 다대다 | 행 단위를 건물 하나로 고정하고 등록부는 필지 단위로 집계 |
| 83개 컬럼 대부분이 침수와 무관 | 위치·규모·지하주차 근거 중심의 27개 컬럼만 유지 |

## 행 단위

```text
한 행 = GIS건물통합정보에서 자체 지하층수(A27)가 1 이상인 건물 한 동
```

총 25,336동이다. 경상북도의 모든 건물이 아니라 **지하층이 있는 건물만** 들어 있다.

## 주요 컬럼

| 컬럼 | 뜻 |
| --- | --- |
| `building_id` | GIS건물통합식별번호 |
| `pnu` | 필지 코드. 건축물대장과 연결하는 키 |
| `longitude`, `latitude` | 건물 폴리곤 중심점, WGS84 |
| `footprint_area_m2` | 건물 바닥 면적 |
| `underground_floor_count_gis` | GIS 기준 지하층 수 |
| `underground_parking_status` | 지하주차장 판정 |
| `underground_parking_confirmed` | 확정이면 1, 아니면 0 |
| `indoor_parking_slots_max` | 필지 내 옥내주차 최대 대수 |
| `total_floor_area_max_m2` | 필지 내 최대 연면적 |
| `main_purpose_name` | 주용도 |
| `approval_year_min` | 최초 사용승인 연도 |
| `register_rows_on_parcel` | 이 필지에서 집계한 등록부 행 수 |

## 판정 분포

| 값 | 건물 수 |
| --- | ---: |
| `UNDERGROUND_FLOOR_ONLY` | 21,077 |
| `CONFIRMED_BASEMENT_PARKING_USE` | 1,787 |
| `PROBABLE_NOT_CONFIRMED_IN_FLOOR_ROWS` | 1,727 |
| `GIS_ONLY_NO_REGISTER_ROW` | 539 |
| `GIS_BASEMENT_CANDIDATE_NOT_CONFIRMED_BY_TITLE` | 206 |

확정 1,787동은 필지 1,372개 위에 있다. 등록부 매니페스트의 `1,449`는 **등록부 행** 기준이고 이 값은 **건물** 기준이므로 단위가 다르다.

## 좌표 검증

- 25,336동 전부가 경상북도 경위도 범위 안이며 범위 밖은 0건이다.
- 좌표 변환은 순수 표준 라이브러리로 구현했고 `pyproj`와의 편차는 0.0000m다.
- 독립 출처인 Overture 건물 305,058동과 대조했을 때 표본 400동의 최근접 거리 중앙값은 7.6m이고 30m 이내가 80.6%다.

## 한계

- **지하주차장 판정은 필지 단위다.** 한 필지에 여러 동이 있으면 모두 같은 값을 받는다.
- 지하층이 있는 건물만 있으므로 **이 파일만으로는 음성 표본을 만들 수 없다.**
- `CONFIRMED`가 아니라고 해서 지하주차장이 없다는 뜻이 아니다. 층별개요에 주차장 용도 표기가 없었다는 뜻이다.
- 좌표는 폴리곤 중심점이며 측량 성과가 아니다.
- 침수 라벨과 강수량은 아직 붙지 않았다. 위치 기준으로 따로 결합해야 한다.

## 재실행

```bash
python3 scripts/build_gyeongbuk_building_features.py
```

좌표 변환만 따로 검증하려면 `pyproj`가 설치된 환경에서 실행한다.

```bash
python3 scripts/build_gyeongbuk_building_features.py --verify-projection
```
