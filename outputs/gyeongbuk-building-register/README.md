# 경상북도 건축물대장 수집 결과

건축HUB 건축물대장 API에서 Waterpark에 필요한 경북 지하주차장 후보를 수집한 결과다.

## 범위

경북 전체 건축물대장을 무작정 전수 호출하지 않았다. 로컬의 최신 `GIS건물통합정보` 전체데이터에서 `지하층 수(A27) >= 1`인 건물을 먼저 찾고, 그 건물들의 법정동·지번만 건축물대장 API에 조회했다.

수집 순서는 다음과 같다.

```text
GIS건물통합정보의 지하층 보유 후보
→ 건축물대장 표제부에서 지하층 수와 옥내주차 확인
→ 건축물대장 층별개요에서 지하층 용도가 '주차장'인지 확인
```

## 이 폴더의 파일

| 파일 | 내용 |
| --- | --- |
| `manifest.json` | 원천 기준일, 행 수, 판정별 집계와 한계 |
| `gyeongbuk_underground_parking_candidates_sample.csv` | 빠르게 열어볼 수 있는 500행 표본 |

전체 CSV와 API 원응답은 크고 다시 만들 수 있으므로 Git에는 올리지 않고 로컬 `data/` 아래에 둔다.

| 로컬 파일 | 내용 |
| --- | --- |
| `data/interim/building-register/gyeongbuk_gis_basement_candidates.csv` | GIS 원본에서 지하층이 있는 건물 후보 |
| `data/interim/building-register/gyeongbuk_basement_candidate_titles.csv` | 후보 지번에서 조회한 건축물대장 표제부 |
| `data/interim/building-register/gyeongbuk_probable_parking_floors.csv` | 지하층과 옥내주차가 함께 있는 후보의 층별개요 |
| `data/interim/building-register/gyeongbuk_underground_parking_candidates.csv` | 표제부와 층별개요를 합쳐 판정 상태를 붙인 전체 결과 |

## 판정값

| 값 | 뜻 |
| --- | --- |
| `CONFIRMED_BASEMENT_PARKING_USE` | 층별개요의 지하층 용도에 `주차장`이 직접 표시됨 |
| `PROBABLE_NOT_CONFIRMED_IN_FLOOR_ROWS` | 지하층과 옥내주차는 있지만 층별개요에서 주차장 용도를 확인하지 못함 |
| `UNDERGROUND_FLOOR_ONLY` | 지하층은 있으나 옥내주차 근거가 없음 |
| `GIS_BASEMENT_CANDIDATE_NOT_CONFIRMED_BY_TITLE` | GIS에는 지하층이 있으나 API 표제부 값으로 확인되지 않음 |

`confirmed`가 아닌 행을 곧바로 “지하주차장 없음”으로 해석하면 안 된다.

## 재실행

저장소 루트의 `.env`에 `DATA_GO_KR_SERVICE_KEY`를 넣은 뒤 실행한다. 키는 Git에 포함되지 않는다.

```bash
python3 scripts/download_gyeongbuk_building_register.py all --workers 1
```

중간 결과를 이어받으므로 호출이 끊겨도 같은 명령을 다시 실행할 수 있다. API가 `429`를 반환할 수 있어 기본적으로 한 번에 한 작업자로 실행하는 편이 안전하다.
