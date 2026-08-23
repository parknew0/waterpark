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
2. `?view=map` — 실제 Kakao 지도에서 현재 위험 주차장과 저위험 후보 중 하나를 직접 선택
3. 선택 결과가 고위험이면 `?view=risk-detail` — Figma `119:1140`
4. 선택 결과가 저위험이면 `?view=safe-detail` — Figma `123:1743`
5. 안전 상세의 CTA를 누르면 `?view=route` — Figma `90:755`: 실제 Kakao 지도 위에 현재 침수 폴리곤을 피해 OSM 도로망으로 계산한 청록색 운전 경로

위험 상세와 안전 상세는 앞뒤로 이어지는 화면이 아니라 **주차장 침수 위험 판정 결과에 따른 상호 배타적 분기**다. 현재는 `frontend/src/lib/parkingRisk.ts`의 데모 어댑터가 현재 주차 위치를 `danger`, 계산된 저위험 후보를 `safe`로 반환한다. 백엔드 계약이 정해지면 이 어댑터만 실제 API 호출로 교체한다.

위험 주차장을 선택하면 위험 상세의 지도 목적지도 선택한 주차장으로 바뀐다. 힌남노 데모는 오천읍 구정길의 사용자 시연 위치에서 저장한 내 차 위치까지 OSRM 도로 경로를 새로 계산한다. 안전 후보를 선택하면 출발점을 저장한 내 차 위치로 바꾸고 선택 주차장까지 다시 계산한다. 따라서 상세 지도에는 각 단계의 실제 출발점에서 선택한 `P` 마커까지 도로 형태의 서로 다른 경로가 보인다.

각 화면은 URL로 직접 열 수도 있다. 위험 상세 CTA는 다시 지도 선택 화면으로 돌아가고, 안전 상세 CTA만 길찾기로 이동한다.

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
- 세 화면 모두 Figma의 402×874 배치, 색상과 카드 크기를 기준으로 구현했다. 위험·안전 상세와 최종 길찾기 지도는 2026-08-23부터 정적 원본 이미지가 아니라 실제 Kakao 지도와 계산 경로를 사용한다.
- Figma의 고정 `blahblah`, 월영교, `2.3km` 대신 계산된 출발지·목적지·거리 값을 사용한다.
- `Safe`는 절대적 안전 보증이 아니라 데모 화면의 상대적 상태다. 목적지 데이터의 `safety_verified`는 여전히 `false`다.

## 검증

- 402×874 브라우저에서 `긴급 → 지도 선택 → 위험 또는 안전` 분기와 안전→길찾기 전환 성공
- 같은 지도에서 현재 주차 위치 선택 시 `Warning`, 저위험 후보 선택 시 `Safe` 상태 확인
- 긴급·안전 상세·길찾기 화면 목적지 `Hyogok-dong Street Parking 8` 영문 표기 확인
- 길찾기 화면 거리 `2.1km`, 운전 9분 표시 확인
- 위험 주차장 선택 후 상세 지도 목적지와 `P` 마커가 선택한 위험 주차장으로 일치하는지 확인
- 길찾기 출발지·목적지 점 사이 점선과 아래 방향 화살촉 확인
- 현재 침수 레이어 1개와 저위험 경로 1개 렌더링 확인
- 브라우저 console error·warning 0건
- TypeScript production build와 ESLint 통과

## 출처

- [Figma 긴급 화면 `90:675`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=90-675&m=dev)
- [Figma 위험 장소 상세 `119:1140`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=119-1140&m=dev)
- [Figma 안전 장소 상세 `123:1743`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1743&m=dev)
- [Figma 길찾기 `90:755`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=90-755&m=dev)
