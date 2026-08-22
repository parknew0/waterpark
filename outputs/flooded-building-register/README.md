# 전국 침수 건물 산출물

전국 16개 시도의 침수 지하층 건물에 대한 지하주차장 확정, 지형·하천 특징, 모델 비교 결과다.

원본과 건물별 추출본은 재배포 조건이 확인되지 않아 로컬 전용이며, 여기에는 **집계·manifest·표본만** 둔다.

## 파일

| 파일 | 내용 |
| --- | --- |
| `flooded_building_register.manifest.json` | 건축HUB 수집 결과와 지하주차장 확정 집계 |
| `flooded_building_underground_parking_sample.csv` | 확정 결과 상위 200행 표본 |
| `national_building_terrain.manifest.json` | DSM 표고 부착 결과와 결측 사유 |
| `terrain_river_features.manifest.json` | 지형·하천 12개 변수 산출 결과 |
| `terrain_model_comparison.json` | XGBoost 대 규칙 1차 비교 (시도 홀드아웃 + 무작위 분할) |
| `terrain_model_variants.json` | 4개 변형 × 8개 시도 홀드아웃, 부트스트랩 신뢰구간 포함 |
| `flood_model_design_comparison.json` | 11개 설계 × 8개 시도 홀드아웃 최종 비교 |

## 핵심 수치

```text
침수 지하층 건물        19,488동   (사건 당시 존재한 건물)
  옥내주차 있는 필지     2,271개
  지하주차장 확정        1,233동   ← 경북 단독 9동의 137배

지하 깊이: 1층 930 / 2층 178 / 3층 60 / 4층 이상 65
```

`NO_REGISTER_ROW_COLLECTED` 1,192동은 **미수집**이며 지하주차장 없음이 아니다. 1,233동은 하한선이다.

## 모델 비교 결론

| 설계 | 가중평균 PR-AUC | 기준선 대비 |
| --- | ---: | ---: |
| XGB 시도순위 | **0.1329** | 3.52배 |
| 규칙 원본 | 0.0894 | 2.13배 |

가중평균은 시도별 양성 표본 수로 가중한 값이다. 단순평균만 보면 규칙이 앞서지만, 그것은 양성 175개 시도와 9,498개 시도를 동일하게 취급한 결과다.

`OPEN` 이 표에서 최고를 고른 것은 낙관적이다. 평가에 쓰지 않은 시도로 재확인해야 한다.

## 관련 문서

- [전국 전처리 파이프라인](../../docs/10-nationwide-preprocessing-pipeline.md)
- [모델 설계 비교](../../docs/11-model-design-comparison.md)
- [회고와 교훈](../../docs/12-retrospective-and-lessons.md)

## 재현

`docs/10-nationwide-preprocessing-pipeline.md` 7절의 명령 순서를 따른다.
