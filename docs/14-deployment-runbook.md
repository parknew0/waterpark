# 배포 실행서

> 확인일: 2026-08-23
>
> 상태: `FACT`는 로컬에서 실제로 확인한 값, `PROPOSAL`은 아직 실행하지 않은 절차다.
>
> 대상: 정적 React 앱 + Lambda 함수 하나. 서버, 컨테이너, 데이터베이스 없음.

## 0. 전체 그림

```text
Cloudflare (DNS + CDN + SSL, 무료)
   │
   ├── example.com/         → Cloudflare Pages  (React 정적 빌드)
   └── example.com/api/*    → Lambda Function URL  (Cloudflare Worker 프록시)
```

`FACT` 프론트는 정적입니다. `npm run build`가 `dist/`에 HTML·CSS·JS만 만들고 서버 런타임이 없습니다.

```text
dist/index.html                   0.75 kB
dist/assets/index-*.css          36.14 kB
dist/assets/index-*.js          228.41 kB
```

`PROPOSAL` API를 같은 도메인 아래 두면 **CORS 설정이 필요 없습니다.** 프론트 훅의 기본 엔드포인트가 `/api/flood-risk`인 이유입니다.

## 1. 준비물 확인

`FACT` 배포 전에 로컬에서 만들어져 있어야 하는 것들입니다.

```bash
./.venv/bin/python scripts/build_risk_grid.py \
  --model data/processed/ml/models/grid_risk_model.json --workers 8
./.venv/bin/python scripts/build_serving_bundle.py
./.venv/bin/python scripts/verify_projection.py
```

| 산출물 | 크기 | 확인 |
| --- | ---: | --- |
| `data/processed/serving-bundle/risk_grid.npz` | 14.10 MB | 격자 4밴드 |
| `data/processed/serving-bundle/parking.json` | 0.15 MB | 지하주차장 1,233동 |
| `data/processed/serving-bundle/grid_meta.json` | 4 KB | 좌표 → 셀 변환 |
| `data/processed/serving-bundle/risk_bands.json` | 1 KB | 위험 구간 경계 |

`FACT` 함수 코드와 번들을 합친 ZIP은 **13 MB**입니다. Lambda ZIP 제한 250 MB에 여유가 큽니다.

## 2. 의존성: numpy 하나뿐

`FACT` 핸들러가 쓰는 외부 패키지는 numpy가 전부입니다. 좌표 투영은 [`serverless/projection.py`](../serverless/projection.py)에 직접 구현했습니다.

**왜 pyproj를 뺐는가.** 세 가지 이유입니다.

| 문제 | 내용 |
| --- | --- |
| 크기 | pyproj 17 MB (그중 PROJ 데이터 8.7 MB) |
| 이식성 | 컴파일된 확장이라 **macOS에서 빌드한 것이 Lambda(Linux)에서 안 돌아감** |
| 과잉 | 전 세계 변환 격자를 싣고 투영 하나만 씀 |

`FACT` 직접 구현한 값을 pyproj와 20,000점에서 대조했습니다.

```text
정방향 최대 오차   0.357 mm
왕복  최대 오차   2.518 mm
격자 셀 100m 대비  0.00036 %
```

회귀 방지용 검증은 `scripts/verify_projection.py`로 언제든 다시 돌립니다.

**numpy는 AWS 제공 레이어를 씁니다.** 직접 빌드하려면 Linux용으로 크로스 컴파일해야 하는데, AWS가 관리하는 레이어를 붙이면 그 과정이 없어집니다.

```text
arn:aws:lambda:ap-northeast-2:336392948345:layer:AWSSDKPandas-Python312:<버전>
```

`OPEN` 레이어 버전 번호는 리전·시점마다 다릅니다. Lambda 콘솔의 **계층 추가 → AWS 계층**에서 최신 버전을 고르면 됩니다.

## 3. Lambda 배포

### 3-1. 패키지 만들기

```bash
cd /Users/park/Desktop/waterpark
rm -rf build/lambda && mkdir -p build/lambda
cp serverless/handler.py serverless/projection.py build/lambda/
cp -r data/processed/serving-bundle build/lambda/bundle
cd build/lambda && zip -qr ../waterpark-flood-risk.zip . && cd -
```

### 3-2. 함수 생성

`PROPOSAL` 콘솔 기준 절차입니다.

1. Lambda → **함수 생성** → 새로 작성
2. 이름 `waterpark-flood-risk`, 런타임 **Python 3.12**, 아키텍처 **x86_64**
3. 생성 후 **코드 → .zip 파일 업로드**로 위 ZIP 올리기
4. **런타임 설정 → 핸들러**를 `handler.handler`로 변경

### 3-3. 계층과 설정

| 항목 | 값 | 근거 |
| --- | --- | --- |
| 계층 | AWSSDKPandas-Python312 | numpy 포함 |
| 메모리 | **512 MB** | 격자 14 MB + numpy. Lambda는 메모리에 비례해 CPU도 늘어남 |
| 타임아웃 | **10초** | 기상청 응답 대기 포함 |
| 리전 | **ap-northeast-2** | 기상청 API 지연 최소화 |

환경 변수:

```text
BUNDLE_DIR             = /var/task/bundle
KMA_APIHUB_AUTH_KEY    = (기상청 API허브 키)
```

`PROPOSAL` 키는 Secrets Manager가 정석이지만, 해커톤 규모에서는 환경 변수로 두고 **저장소에는 절대 커밋하지 않는** 것으로 충분합니다.

### 3-4. Function URL

1. **구성 → 함수 URL → 함수 URL 생성**
2. 인증 유형 **NONE** (Cloudflare 뒤에 두므로)
3. CORS는 **비활성화** — 같은 오리진으로 프록시할 것이라 불필요

`FACT` 발급되는 URL 형식: `https://<id>.lambda-url.ap-northeast-2.on.aws/`

### 3-5. 동작 확인

```bash
curl -s -X POST 'https://<id>.lambda-url.ap-northeast-2.on.aws/' \
  -H 'content-type: application/json' \
  -d '{"lat":37.48,"lon":126.95}' | head -c 400
```

`FACT` 로컬에서 같은 입력의 결과입니다. 배포 후 이 값과 맞는지 대조합니다.

```text
riskLevel   MODERATE
riskScore   0.2854
evidence    relativeElevationM 14.5 / distanceToFloodTraceM 17
```

## 4. Cloudflare 연결

### 4-1. 도메인 등록

1. Cloudflare 가입 → **Add a site** → 도메인 입력
2. 표시되는 **네임서버 2개**를 도메인 구입처(가비아·후이즈 등)의 네임서버 설정에 입력
3. 전파 대기 (보통 수 분 ~ 수 시간)

`FACT` 이 단계가 끝나야 아래가 동작합니다. Cloudflare 대시보드에 `Active`로 뜨면 완료입니다.

### 4-2. 프론트 배포 — Cloudflare Pages

`PROPOSAL` Pages를 쓰면 S3도 CloudFront도 필요 없습니다.

1. Cloudflare → **Workers & Pages → Create → Pages → Connect to Git**
2. 이 저장소 연결, 브랜치 `main`
3. 빌드 설정:

```text
Framework preset     Vite
Build command        npm run build
Build output         dist
Root directory       frontend
```

4. 환경 변수 (필요 시):

```text
VITE_KAKAO_MAP_APP_KEY = (카카오 지도 키)
```

`FACT` `VITE_FLOOD_RISK_API`는 **설정하지 않습니다.** 미설정 시 기본값 `/api/flood-risk`가 쓰이고, 그게 같은 도메인 경로입니다.

5. 배포 후 **Custom domains**에서 도메인 연결

### 4-3. `/api/*` → Lambda 프록시

`PROPOSAL` Pages Functions로 처리합니다. `frontend/functions/api/[[path]].ts`를 만들면 Cloudflare가 자동 인식합니다.

```typescript
export const onRequest: PagesFunction<{ LAMBDA_URL: string }> = async (ctx) => {
  const url = new URL(ctx.request.url);
  const target = ctx.env.LAMBDA_URL.replace(/\/$/, "") + url.pathname.replace(/^\/api/, "");
  return fetch(target, {
    method: ctx.request.method,
    headers: { "content-type": "application/json" },
    body: ctx.request.method === "POST" ? await ctx.request.text() : undefined,
  });
};
```

Pages 환경 변수에 `LAMBDA_URL`을 넣습니다.

**이 구조의 이점:**

| 항목 | 효과 |
| --- | --- |
| CORS | 같은 오리진이라 설정 자체가 불필요 |
| Lambda URL 노출 | 브라우저에 안 보임 |
| 백엔드 도메인 | 필요 없음 |

## 5. 배포 후 점검

`PROPOSAL` 순서대로 확인합니다.

```bash
# 1) 정적 앱
curl -sI https://example.com | head -3

# 2) API 프록시
curl -s -X POST https://example.com/api/flood-risk \
  -H 'content-type: application/json' \
  -d '{"lat":37.48,"lon":126.95}' | head -c 300

# 3) 미조사 지역이 UNKNOWN으로 나오는지 (가장 중요)
curl -s -X POST https://example.com/api/flood-risk \
  -H 'content-type: application/json' \
  -d '{"lat":37.80,"lon":128.50}' | grep -o '"riskLevel":"[^"]*"'
```

`FACT` 3번은 `"riskLevel":"UNKNOWN"`이 나와야 합니다. 여기서 낮은 위험도가 나오면 **미조사 지역을 안전으로 표시하는 것**이고, [6절 7항](./06-flood-risk-modeling.md)이 금지한 상태입니다.

## 6. 비용

`PROPOSAL` 해커톤 규모 추정입니다.

| 항목 | 비용 |
| --- | --- |
| Cloudflare (DNS·CDN·SSL·Pages) | 무료 |
| Lambda 요청 100만 건 | 약 $0.20 |
| Lambda 실행 (512MB, 100ms, 100만 건) | 약 $0.83 |
| 도메인 | 구입처 정책 |

`FACT` 트래픽이 없으면 Lambda 비용이 0입니다. 호우 시에만 몰리는 이 서비스 특성에 맞습니다. EC2였다면 평상시에도 인스턴스 비용이 나갑니다.

## 7. 알려진 미완 사항

- `OPEN` 기상청 3시간·12시간 누적 강수가 없습니다. 현재 1시간만 조회하고 나머지는 `null`이라 **호우경보·극한호우 판정이 제한적**입니다. 추측값을 넣지 않은 이유는 없는 값을 지어내면 경보가 틀리기 때문입니다.
- `OPEN` Cloudflare Pages Functions 프록시를 실제로 배포해 확인하지 않았습니다.
- `OPEN` 지도 전면 색칠용 타일이 없습니다. 격자를 PNG 타일로 구우면 클릭 전에 위험 지역을 볼 수 있습니다.
- `OPEN` 격자 갱신 자동화가 없습니다. 현재는 로컬에서 수동 실행 후 재배포합니다.

## 8. 관련 문서

- [서빙 구조와 배포 준비](./13-serving-architecture-and-deployment.md) — 왜 격자를 미리 굽는가
- [전국 전처리 파이프라인](./10-nationwide-preprocessing-pipeline.md)
- [침수 위험 산출 결과](./06-flood-risk-modeling.md) — 표현 규칙
