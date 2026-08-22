# 배포 실행서

> 확인일: 2026-08-23 (배포 후 갱신)
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
| `data/processed/serving-bundle/risk_grid.npz` | 6.87 MB | 격자 4밴드, 정수로 양자화 |
| `data/processed/serving-bundle/stations.json` | 0.30 MB | 기상청 관측소 11,914곳 좌표 |
| `data/processed/serving-bundle/parking.json` | 0.15 MB | 지하주차장 1,233동 |
| `data/processed/serving-bundle/grid_meta.json` | 1 KB | 좌표 → 셀 변환 |
| `data/processed/serving-bundle/risk_bands.json` | 1 KB | 위험 구간 경계 |

`FACT` 함수 코드와 번들을 합친 ZIP은 **6.91 MB**입니다. Lambda ZIP 제한 250 MB뿐 아니라 **콘솔 직접 업로드 한도 10 MB** 아래라, S3를 거치지 않고 브라우저에서 바로 올립니다.

`FACT` 격자를 float32에서 정수로 바꿔 절반으로 줄인 결과입니다. 점수는 다섯 구간을 가르고 지도를 칠하는 데만 쓰이고 응답도 확률이 아니라고 명시하므로, 1/254 눈금이 이미 값의 의미보다 촘촘합니다. 표고는 소수 한 자리로 보고하니 데시미터로 충분합니다.

## 2. 의존성: 없음

`FACT` 핸들러는 **외부 패키지를 하나도 쓰지 않습니다.** 표준 라이브러리만으로 돕니다.

| 원래 필요했던 것 | 대체 | 이유 |
| --- | --- | --- |
| pyproj | [`serverless/projection.py`](../serverless/projection.py) | 17 MB, 컴파일된 확장이라 macOS 빌드가 Lambda(Linux)에서 안 돎 |
| numpy | [`serverless/npzreader.py`](../serverless/npzreader.py) | 셀 하나 읽는 데 배열 라이브러리가 필요 없음 |

**numpy를 뺀 이유가 크기만은 아닙니다.** AWS가 관리하는 numpy 계층은 **Python 3.11까지만** 제공됩니다. 3.12 함수에서 쓰려면 계층 ARN을 직접 찾아 버전을 고정해야 하고, 그 버전이 폐기될 때마다 다시 고정해야 합니다. 표준 라이브러리만 쓰면 **낡을 계층 자체가 없습니다.**

`FACT` .npz는 .npy를 담은 zip이고 .npy는 짧은 ASCII 헤더 뒤에 리틀엔디언 원본 바이트라, `zipfile`과 `struct`만으로 읽힙니다. 이 프로젝트가 쓰는 정수 dtype만 지원하고 나머지는 조용히 잘못 읽는 대신 예외를 냅니다.

`FACT` 직접 구현한 투영을 pyproj와 20,000점에서 대조했습니다.

```text
정방향 최대 오차   0.357 mm
왕복  최대 오차   2.518 mm
격자 셀 100m 대비  0.00036 %
```

회귀 방지용 검증은 `scripts/verify_projection.py`로 언제든 다시 돌립니다. pyproj는 로컬에만 있고 Lambda에는 일부러 없습니다.

## 3. Lambda 배포

### 3-1. 패키지 만들기

```bash
cd /Users/park/Desktop/waterpark
rm -rf build/lambda && mkdir -p build/lambda
cp serverless/handler.py serverless/projection.py serverless/npzreader.py build/lambda/
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
| 계층 | **없음** | 표준 라이브러리만 씀 |
| 메모리 | **512 MB** | 격자 6.9 MB 상주 + 기상청 12회 병렬 조회. Lambda는 메모리에 비례해 CPU도 늘어남 |
| 타임아웃 | **10초** | 기상청 응답 대기 포함 |
| 리전 | **ap-northeast-2** | 기상청 API 지연 최소화 |

환경 변수:

```text
BUNDLE_DIR             = /var/task/bundle
KMA_APIHUB_AUTH_KEY    = (기상청 API허브 키)
```

`FACT` **키를 헷갈리면 조용히 실패합니다.** 이 값은 `apihub.kma.go.kr`에서 발급한 키여야 하고, `data.go.kr` 키와 형태가 다릅니다. 실제로 후자를 넣어 한참 헤맸습니다.

| 출처 | 길이 | 문자 |
| --- | --- | --- |
| API허브 (맞음) | 22자 | 영숫자와 `_` |
| data.go.kr (틀림) | 88자 | `+` `/` `=` 포함 |

`FACT` 요청 URL에서 `authKey`는 **퍼센트 인코딩하지 않고 그대로** 붙입니다. 인코딩하면 게이트웨이가 거부합니다. `tm`은 정시여야 하며(`YYYYMMDDHH00`), 분이 `30`이면 HTTP 200에 데이터 0행이 돌아옵니다.

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

### 4-2-1. 로컬 개발에서 `/api/*` 붙이기

`FACT` `vite dev`는 Pages Functions를 실행하지 않습니다. 그대로 두면 `/api/flood-risk`가 로컬에서 404가 나고, 코드와 무관한 이유로 앱이 고장 난 것처럼 보입니다.

`FACT` [`frontend/vite.config.ts`](../frontend/vite.config.ts)에 개발 전용 프록시를 넣어 해결했습니다. 프론트 담당자는 이것만 하면 됩니다.

```bash
cd frontend && cp .env.example .env.local && npm run dev
```

`FACT` `.env.local`의 `LAMBDA_URL`을 채우면 개발과 배포가 **같은 상대 경로**를 씁니다.

`FACT` Lambda URL을 프론트 코드에 직접 넣으면 안 됩니다. Function URL은 CORS 헤더를 보내지 않아 브라우저가 차단합니다. 프록시는 Node에서 돌아 그 제약을 받지 않습니다.

`FACT` `LAMBDA_URL`은 `VITE_` 접두사가 없어 클라이언트 번들에 들어가지 않습니다. `server` 설정은 개발 전용이라 빌드 산출물에 포함되지 않습니다.

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

Pages 환경 변수에 `LAMBDA_URL`을 넣습니다. **Production과 Preview 양쪽에 넣어야 합니다.** Cloudflare는 환경별로 변수를 따로 두므로, Production에만 넣으면 브랜치 미리보기가 전부 503으로 죽습니다.

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

- `DONE` 기상청 3시간·12시간 누적 강수를 붙였습니다. 정시 12회를 병렬로 조회해 합산하며, 관측소 좌표는 응답에 없어 `stations.json`(11,914곳)으로 최근접을 찾습니다.
- `DONE` 기상청 조회 실패를 `CALM`이 아니라 `UNKNOWN`으로 보고합니다. 조회에 실패한 것을 "비가 오지 않는다"로 표시하면, 미조사 지역을 안전으로 칠하는 것과 같은 오류입니다.
- `OPEN` Cloudflare Pages Functions 프록시를 실제로 배포해 확인하지 않았습니다. 로컬은 Vite 프록시로 확인했습니다.
- `OPEN` 프론트가 API를 부르는 곳은 강수량 배지 하나뿐입니다. `alert.level`로 화면을 자동 전환하는 부분이 비어 있어, "차 빼세요" 화면은 아직 손으로 눌러야 나옵니다.
- `OPEN` `EmergencyView`의 "Estimated safe time 30min"은 API에 대응하는 값이 없습니다. 침수흔적도에 시각이 없어 남은 시간을 학습할 수 없으므로, 숫자를 지어내는 대신 `alert.reasons`로 바꿔야 합니다.
- `OPEN` 지도 전면 색칠용 타일이 없습니다. 격자를 PNG 타일로 구우면 클릭 전에 위험 지역을 볼 수 있습니다.
- `OPEN` 격자 갱신 자동화가 없습니다. 현재는 로컬에서 수동 실행 후 재배포합니다.

## 8. 관련 문서

- [서빙 구조와 배포 준비](./13-serving-architecture-and-deployment.md) — 왜 격자를 미리 굽는가
- [전국 전처리 파이프라인](./10-nationwide-preprocessing-pipeline.md)
- [침수 위험 산출 결과](./06-flood-risk-modeling.md) — 표현 규칙
