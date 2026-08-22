# 침수 위험 회피 경로 뷰

> 구현·확인일: 2026-08-23
>
> 상태: `MVP IMPLEMENTED`

## 사용자 흐름

`?view=emergency`의 `Move Your Car Now`를 누르면 정적 GeoJSON을 불러와 `위험 장소 상세 → 안전 장소 상세 → 우회 길찾기`로 전환한다. 최종 지도에는 다음 레이어를 표시한다.

- 청록 발광 영역: 건물 위험점과 현재 침수에서 만든 데모 위험 영향권
- 회색 점선: 거리만 최소화한 일반 최단경로
- 청록 실선: 침수 위험 노출 비용을 포함한 저위험 경로 후보
- 녹색 `P`: 선택된 목적 주차장 후보
- 상단 카드: 현재 위치와 목적지
- 하단 카드: 1시간 예측 범위, OSM 도로 속성 기반 예상 운전시간, 계산 도로거리

`?view=route`의 `EvacuationRouteView`도 `VITE_KAKAO_MAP_APP_KEY`를 받아 실제 Kakao 지도를 표시한다. 경로는 직선 목업이 아니라 OSM 운전 도로 그래프에서 계산한 `lower_risk_route` 좌표열이며, `Polygon`, `Polyline`, `CustomOverlay`로 실제 좌표에 맞춰 렌더링한다. 지도는 드래그·확대·축소할 수 있다. 키가 없거나 SDK 로드가 실패할 때만 기존 지도 이미지 위 SVG 레이어로 같은 GeoJSON을 표시한다. Figma `244:3303`과 다르게 임의로 추가했던 파란 경로 출처 문구는 제거했고, 뒤로가기 아이콘은 Figma SVG 원본 비율을 유지한다.

## 데이터 연결

- 원본 산출물: `outputs/routing/pohang-postech-flood-aware-route.geojson`
- 프론트 복사본: `frontend/public/data/pohang-flood-aware-route.geojson`
- 로더: `frontend/src/hooks/useFloodAwareRoute.ts`
- 타입: `frontend/src/types/routing.ts`
- 렌더러: `frontend/src/components/ParkingMap.tsx`, `frontend/src/lib/kakaoMaps.ts`

긴급 카드의 목적지·주소·거리도 같은 GeoJSON을 사용한다. 기존 Figma 고정 예시였던 월영교·상주 주소와 `156m`는 제거했다.

길찾기 하단 카드도 고정 문자열을 사용하지 않는다. `distance_m`은 OSM 도로 경로 길이, `travel_time_s`는 OSM 도로의 속도 속성으로 계산한 예상 이동시간, `forecast_horizon_minutes`는 모델 예측 범위다. 현재 데모 출력은 각각 `2,121.9m`, `509.3초`(UI 올림 `9 min`), `60분`(UI `1 hour`)이다. `Safe time`은 Figma 라벨을 유지한 것이며 실제 안전 보장 시간이 아니라 1시간 예측 범위를 뜻한다.

## 기본 데이터 결과

- 출발: POSTECH 인근 `(36.014, 129.325)`
- 목적지: `효곡동 노상1`
- 도로거리: `618.3m`
- 일반 최단경로와 저위험 경로: 동일
- 위험 영향권 교차: `0m`

현재 데이터에서 두 선이 같은 것은 정상 계산 결과다. 실제 차이를 시연하려면 공식 침수·통제 폴리곤을 입력하거나 위험 노출이 있는 출발지·목적지를 사용해야 한다.

## 가짜 침수 시연 결과

- 입력: `data/demo/pohang-current-flood-scenario.geojson`
- 제거된 도로 간선: 6개
- 재선택 목적지: `효곡동 노상8`
- 우회 도로거리: `2,121.9m`
- OSM 속도 기반 예상 운전시간: `509.3초` → UI `9 min`
- 모델 예측 범위: `60분` → UI `1 hour`
- UI 표시: 현재 침수 폴리곤 청록 발광 영역, 저위험 우회선 청록색

이 시나리오는 발표 화면 전환과 우회 계산 검증만을 위한 합성 데이터다. 실제 포항 침수 현황으로 설명하면 안 된다.

## 안전 표현 제한

- UI와 데이터 모두 `safe route`가 아니라 `lower-risk route candidate`로 표현한다.
- 목적 주차장의 `safety_verified`는 `false`다.
- 위험 영향 반경 `120m`는 공식 침수 경계가 아니라 시연용 파라미터다.
- 실시간 도로 통제, 주차 여석과 현장 상태는 아직 연결하지 않았다.
- 실제 재난 시 재난문자·공식 도로 통제·현장 안내를 우선해야 한다.

## 검증

- Python 문법 검사 및 생성기 실행 성공
- GeoJSON 필수 레이어 6개 생성
- React TypeScript production build 성공
- ESLint 성공
- OSM 경로 출처를 결과 데이터와 UI에 표시
- `localhost:5173/?view=route`에서 실제 Kakao 타일, OSM 도로 경로, 현재 위치·목적지·위험 영역 렌더링 확인
