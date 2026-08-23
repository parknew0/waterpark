# 서빙 구조와 배포 준비

> 확인일: 2026-08-23
>
> 상태: `FACT` — 격자 산출·검증, 핸들러 로컬 실행까지 완료. AWS 배포는 미실행.
>
> 범위: 학습된 모델을 어떻게 서비스로 내보내는가. 배포 직전까지의 준비물과 그 근거.

## 1. 핵심 결정: 요청 시점에 모델을 돌리지 않는다

`FACT` 실측한 비용이다.

| 항목 | 값 |
| --- | ---: |
| XGBoost 모델 파일 | 1.42 MB |
| 단건 추론 | 0.5 ms |
| **DSM 원본** | **768 MB** |
| **하천 STRtree 적재** | **약 1.5 GB, 7초** |

**모델은 가벼운데 입력을 만드는 비용이 무겁다.** 요청마다 하천 인덱스를 올리면 응답이 초 단위가 되고, 컨테이너가 자주 뜨는 서버리스에서는 성립하지 않는다.

`FACT` 지형은 요청 사이에 변하지 않는다. 그래서 **오프라인에서 격자로 미리 굽고, 런타임은 조회만 한다.**

```text
[오프라인 배치]  DSM + 하천 + 침수흔적 → 모델 → 100m 격자 (14.1 MB)
[런타임]         좌표 → 격자 조회 → 기상청 강수 → 규칙 결합 → 응답
```

`FACT` 런타임에는 모델도 DSM도 하천도 올라가지 않는다.

## 2. 격자 설계 근거

### 셀 크기 100m — 라벨이 정한 값

`FACT` 침수 Polygon 6,000건을 EPSG:5179로 투영해 실측했다.

| 지표 | 값 |
| --- | ---: |
| 면적 중앙값 | 6,888 m² |
| **짧은 쪽 폭 중앙값** | **106 m** |
| 폭 30m 미만 | 7.1% |
| 폭 100m 미만 | 46.2% |

**정답의 폭이 106m인데 입력을 30m로 정밀하게 만들 이유가 없다.** 3칸 옆을 구분해도 그 차이를 채점할 라벨이 없다. 250m는 반대로 Polygon 46%가 뭉개진다.

| 격자 | 셀 수 | 판단 |
| --- | ---: | --- |
| 30m | 1.1억 | 라벨이 못 따라옴, 444 MB |
| **100m** | **1,732만** | **라벨 해상도와 일치** |
| 250m | 160만 | Polygon 46%가 한 칸에 뭉개짐 |

### 범위 — 조사 구역 + 1km 버퍼

`FACT` 전국을 다 굽는 것은 낭비다.

| 범위 | 면적 | 전국 대비 |
| --- | ---: | ---: |
| 남한 전체 | 100,000 km² | 100% |
| 침수 Polygon 합집합 | 469 km² | 0.5% |
| **+1,000m 버퍼** | **11,317 km²** | **11.3%** |

버퍼 밖은 어떤 값을 계산해도 `UNKNOWN`으로 나간다. [학습표의 음성 라벨 규칙](./10-nationwide-preprocessing-pipeline.md)이 "조사 구역 1km 이내"이므로 **계산 유효 범위와 격자 범위를 일치시킨다.**

`FACT` 경계 상자는 제주부터 강원까지 덮어 1,732만 칸이지만 실제 채워진 것은 **1,132,170칸(6.5%)** 이다. 나머지는 nodata이며 압축 후 14.1 MB다.

### 4개 밴드 — 점수만으로는 설명할 수 없다

| 밴드 | 타입 | 용도 |
| --- | --- | --- |
| `risk_score` | float32 | 지도 색칠, 순위 |
| `rel_elev_500m` | float32 | "주변보다 N m 낮습니다" |
| `elev_above_national_river` | float32 | "국가하천 수면보다 N m 높습니다" |
| `dist_flood_m` | uint16 | "과거 침수 구역까지 N m" + 조사 여부 판정 |

사용자에게 점수 하나만 보여주면 행동으로 이어지지 않는다. **근거 수치를 함께 저장한다.**

### 격자용 모델은 순위 변수를 뺐다

`FACT` 성능이 가장 좋았던 설계는 `XGB 시도순위`(가중평균 0.1329)지만, 격자에는 쓰지 않았다.

임의 지점은 어느 시도 분포에 속하는지 애매하고, 서빙 시점에 시도별 분포표를 함께 배포해야 한다. **성능과 배포 단순성을 맞바꿔** 절대값 고도 7개만으로 다시 학습했다.

`OPEN` 이 교환의 실제 손실은 아직 재지 않았다.

## 3. 검증

`FACT` 격자 값을 이미 계산해둔 건물별 값과 대조했다.

| 항목 | 결과 |
| --- | --- |
| 대조 표본 | 2,821건 |
| 격자 미포함 | **0건** |
| 차이 중앙값 | **-0.00 m** |
| \|차이\| < 5 m | 93.7% |
| \|차이\| < 15 m | 99.9% |

격자는 100m 칸 중심에서 계산하고 건물은 실제 좌표이므로 최대 70m 어긋날 수 있다. 그 범위에서 설명되는 차이다.

`FACT` 침수 건물 19,745동이 전부 격자 범위 안에 들어간다. 버퍼 설계가 맞다는 확인이다.

## 4. 런타임 동작

### 동적 침수 회피 경로

`POST /flood-route`는 출발지·선택 주차장·시나리오 ID를 받아 616KB OSM 그래프 번들에서 두 번의 다익스트라를 실행한다. 일반 경로는 모든 간선을 허용하고, 저위험 경로는 `CURRENT` 침수 폴리곤과 교차해 사전 표시된 간선을 제외한다. 응답에는 일반·저위험 LineString 좌표열, 계산에 사용한 위험 Polygon, 거리·시간과 실제 차단 간선 수를 함께 담는다. Lambda 요청 시에는 `handler.py`가 경로를 보고 `routing.py`로 분기한다.

로컬 `npm run dev`는 `serverless/dev_server.py`와 Vite를 함께 실행하며 Vite가 `/api/flood-route`만 `127.0.0.1:8788`로 프록시한다. 다른 `/api/*`는 기존 `LAMBDA_URL` 설정을 유지한다.

`FACT` 로컬에서 핸들러를 실제로 호출한 결과다.

| 지점 | 응답 | 조사상태 | 위험도 | 근거 |
| --- | ---: | --- | --- | --- |
| 서울 관악구 | 89 ms (콜드) | SURVEYED | MODERATE | 침수구역 17m |
| 포항 형산강 | < 1 ms | SURVEYED | HIGH | 주변 대비 5.9m, 하천 대비 4.8m |
| 인천 | < 1 ms | SURVEYED | VERY_LOW | 주변 대비 23.8m |
| 강원 산간 | < 1 ms | **NOT_SURVEYED** | **UNKNOWN** | — |

`FACT` 콜드스타트 89 ms, 이후 1 ms 미만이다. 오류 처리도 확인했다: 범위 밖 좌표 422, 좌표 누락 400.

### 절대 어겨서는 안 되는 두 가지

**① 미조사를 안전으로 표시하지 않는다.**

인천은 지하층 건물 69,142동에 침수 겹침이 1동이다. 마른 곳이라서가 아니라 침수흔적 조사가 144건뿐이기 때문이다. 격자 밖은 `riskLevel: "UNKNOWN"`을 반환하고, 프론트는 이를 회색으로 칠한다. 초록색은 "낮음"이지 "모름"이 아니다.

**② `riskScore`를 확률로 부르지 않는다.**

PR-AUC로 검증한 것은 **순위 성능**이다. 절대 확률로 보정한 적이 없다. 응답 어디에도 `probability` 필드가 없고, `dataQuality.disclaimer`가 페이로드와 함께 다닌다.

## 5. 서빙 묶음

`FACT` Lambda에 올릴 전부다.

| 파일 | 크기 | 내용 |
| --- | ---: | --- |
| `risk_grid.npz` | 14.10 MB | 4밴드 격자 |
| `parking.json` | 0.15 MB | 지하주차장 확정 1,233동 |
| `grid_meta.json` | 4 KB | 좌표 → 셀 변환 정보 |
| `risk_bands.json` | 1 KB | 위험 구간 경계 |
| **합계** | **14.25 MB** | Lambda ZIP 제한 250 MB |

### 위험 구간

`FACT` 격자 자체 점수 분포의 분위수로 정했다. 임의의 반올림 값이 아니다.

| 등급 | 최소 점수 | 분위 | 강수 발령 기준 |
| --- | ---: | ---: | --- |
| VERY_HIGH | 0.8188 | 95% | 호우주의보 |
| HIGH | 0.6948 | 85% | 호우주의보 |
| MODERATE | 0.2812 | 60% | 호우경보 |
| LOW | 0.0958 | 30% | 극한호우 |
| VERY_LOW | 0.0000 | 0% | 극한호우 |

`FACT` 강수 기준은 기상청 공식 호우특보 기준이며 학습한 값이 아니다. 근거는 [6절 4항](./06-flood-risk-modeling.md)에 있다. **지형 위험이 높을수록 낮은 강수 단계에서 알린다.**

## 6. 인프라 구성

### 권장: 같은 CloudFront에 프론트와 API를 붙인다

```text
example.com/         → S3 (React 정적 파일)
example.com/api/*    → Lambda Function URL
```

`PROPOSAL` 이렇게 하면 **백엔드 도메인이 없고 CORS 설정도 필요 없다.** 프론트 훅의 기본 엔드포인트가 `/api/flood-risk`인 이유다.

### Lambda가 필요한 진짜 이유

`FACT` 격자 조회는 원리상 브라우저에서도 가능하다. Lambda가 있어야 하는 이유는 하나다 — **기상청 API 키를 브라우저에 노출할 수 없다.**

| 항목 | 권장값 | 근거 |
| --- | --- | --- |
| 메모리 | 512 MB | 격자 14 MB + numpy 런타임. 메모리에 비례해 CPU도 늘어남 |
| 타임아웃 | 10초 | 기상청 응답 대기 포함 |
| 패키징 | ZIP + Layer | 14.25 MB이므로 250 MB 제한에 여유 |
| 환경변수 | `KMA_APIHUB_AUTH_KEY`, `BUNDLE_DIR` | 키는 Secrets Manager 권장 |
| 리전 | ap-northeast-2 | 기상청 API 지연 최소화 |

`FACT` 기상청 응답은 관측소 단위라 10분 TTL 캐시를 컨테이너 안에 둔다. 같은 지역 요청이 몰려도 외부 호출이 거의 나가지 않는다.

### DNS: Cloudflare 대 Route 53

`PROPOSAL` **Cloudflare를 권장한다.**

| 항목 | Cloudflare | Route 53 |
| --- | --- | --- |
| DNS 질의 비용 | 무료 | 100만 건당 $0.40 |
| CDN·캐싱 | 무료 플랜 포함 | CloudFront 별도 |
| SSL 인증서 | 무료·자동 | ACM 무료 (CloudFront 연동 시) |
| AWS 연동 | 표준 DNS 레코드 | 별칭 레코드로 더 매끄러움 |

해커톤 규모에서 Route 53의 이점(별칭 레코드, 헬스체크)은 크지 않고 Cloudflare가 CDN까지 무료로 덮는다.

`PROPOSAL` 다만 **Cloudflare를 쓰면 CloudFront가 불필요해진다.** 구성이 이렇게 바뀐다.

```text
Cloudflare (DNS + CDN + SSL)
  example.com/       → S3 정적 호스팅 (또는 Cloudflare Pages)
  example.com/api/*  → Lambda Function URL
```

Cloudflare Workers Routes 또는 Page Rules로 `/api/*`를 Lambda Function URL에 프록시하면 **같은 오리진이 유지되어 CORS가 여전히 필요 없다.**

`OPEN` 실제 프록시 설정은 아직 검증하지 않았다.

## 7. 남은 작업

- `OPEN` AWS 배포 실행 (Lambda 생성, Function URL, 환경변수)
- `OPEN` Cloudflare `/api/*` 프록시 설정과 CORS 실동작 확인
- `OPEN` 기상청 3시간·12시간 누적 강수. 현재 핸들러는 1시간만 조회하고 나머지는 `null`이므로 호우경보·극한호우 판정이 제한적이다
- `OPEN` 지도 전면 색칠용 타일. 격자를 PNG 타일로 구우면 클릭 전에 위험 지역을 볼 수 있다
- `OPEN` 순위 변수 제외로 인한 실제 성능 손실 측정

## 8. 재현 명령

```bash
# 격자용 모델 학습 후
./.venv/bin/python scripts/build_risk_grid.py \
  --model data/processed/ml/models/grid_risk_model.json --workers 8
./.venv/bin/python scripts/build_serving_bundle.py

# 로컬에서 핸들러 검증
cp data/processed/serving-bundle/* serverless/bundle/
cd serverless && BUNDLE_DIR=./bundle python -c "
import json, handler
print(handler.handler({'body': json.dumps({'lat':37.48,'lon':126.95})}))"
```

## 9. 관련 문서

- [전국 전처리 파이프라인](./10-nationwide-preprocessing-pipeline.md)
- [모델 설계 비교](./11-model-design-comparison.md)
- [회고와 교훈](./12-retrospective-and-lessons.md)
- [침수 위험 산출 결과](./06-flood-risk-modeling.md) — 표현 규칙
