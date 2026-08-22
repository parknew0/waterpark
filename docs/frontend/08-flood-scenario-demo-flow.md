# 가짜 침수 상황 데모 흐름

> 구현·확인일: 2026-08-22
>
> 상태: `IMPLEMENTED DEMO`

## 실행

```bash
cd /Users/neon/Documents/Project/waterpark/frontend
npm run dev
```

브라우저에서 `http://localhost:5173/?view=emergency`를 연다. 포트가 이미 사용 중이면 Vite가 안내하는 포트를 사용하되 Kakao Developers JavaScript SDK 도메인에도 그 origin을 등록해야 한다.

## 발표용 전체 흐름

1. `?view=emergency` — Figma `90:675`: 비·경고 진동과 차량 이동 경고
2. `?view=risk-detail` — Figma `119:1140`: 현재 주차 위치의 가짜 고위험 근거
3. `?view=safe-detail` — Figma `123:1743`: 자동 선택한 저위험 주차장 후보와 근거
4. `?view=route` — Figma `90:755`: 현재 침수 폴리곤을 피해 계산한 청록색 운전 경로

각 화면은 위 URL로 직접 열 수도 있다. 정상 시연에서는 각 CTA를 누르면 순서대로 이동한다.

## 가짜 침수 데이터 만들기

저장소에는 기본 경로 위 도로 일부를 막는 합성 폴리곤 `data/demo/pohang-current-flood-scenario.geojson`이 포함돼 있다. 다음 명령이 이 폴리곤과 교차하는 OSM 간선을 제거하고 프론트 GeoJSON을 다시 만든다.

```bash
cd /Users/neon/Documents/Project/waterpark
./.venv/bin/python scripts/build_flood_aware_route.py \
  --current-flood-geojson data/demo/pohang-current-flood-scenario.geojson
```

현재 생성 결과는 다음과 같다.

- 차단 간선: 6개
- 목적지: `효곡동 노상8`
- 우회 도로거리: `2,121.9m`
- 예상 운전시간 UI: 9분
- `CURRENT` 침수 폴리곤: 1개

## Figma 반영 사항

- 상태바·다이내믹 아일랜드·홈 인디케이터는 예시 기기 크롬이므로 구현하지 않았다.
- 세 화면 모두 Figma의 402×874 배치, 색상, 카드 크기, 지도 원본 이미지를 기준으로 구현했다.
- Figma의 고정 `blahblah`, 월영교, `2.3km` 대신 계산된 출발지·목적지·거리 값을 사용한다.
- `Safe`는 절대적 안전 보증이 아니라 데모 화면의 상대적 상태다. 목적지 데이터의 `safety_verified`는 여전히 `false`다.

## 검증

- 402×874 브라우저에서 네 화면 CTA 전환 성공
- 위험 상세 `Warning`, 안전 상세 `Safe` 상태 확인
- 길찾기 화면 목적지 `효곡동 노상8`, 거리 `2.1km`, 운전 9분 표시 확인
- 현재 침수 레이어 1개와 저위험 경로 1개 렌더링 확인
- 브라우저 console error·warning 0건
- TypeScript production build와 ESLint 통과

## 출처

- [Figma 긴급 화면 `90:675`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=90-675&m=dev)
- [Figma 위험 장소 상세 `119:1140`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=119-1140&m=dev)
- [Figma 안전 장소 상세 `123:1743`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1743&m=dev)
- [Figma 길찾기 `90:755`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=90-755&m=dev)
