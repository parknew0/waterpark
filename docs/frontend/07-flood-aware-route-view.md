# 침수 위험 회피 경로 뷰

> 구현·확인일: 2026-08-22
>
> 상태: `MVP IMPLEMENTED`

## 사용자 흐름

`?view=emergency`의 `Move Your Car Now`를 누르면 정적 GeoJSON을 불러와 지도 화면으로 전환한다. 지도에는 다음 레이어를 표시한다.

- 주황·적색: 건물 위험점에서 만든 데모 위험 영향권
- 회색 점선: 거리만 최소화한 일반 최단경로
- 청록 실선: 침수 위험 노출 비용을 포함한 저위험 경로 후보
- 녹색 `P`: 선택된 목적 주차장 후보
- 하단 카드: 목적지, 도로거리, `Safety not verified`, OSM 출처

Kakao JavaScript 키가 있으면 `Polygon`, `Polyline`, `CustomOverlay`로 표시한다. 키가 없거나 SDK 로드가 실패하면 기존 지도 이미지 위 SVG 레이어로 같은 GeoJSON을 표시한다.

## 데이터 연결

- 원본 산출물: `outputs/routing/pohang-postech-flood-aware-route.geojson`
- 프론트 복사본: `frontend/public/data/pohang-flood-aware-route.geojson`
- 로더: `frontend/src/hooks/useFloodAwareRoute.ts`
- 타입: `frontend/src/types/routing.ts`
- 렌더러: `frontend/src/components/ParkingMap.tsx`, `frontend/src/lib/kakaoMaps.ts`

긴급 카드의 목적지·주소·거리도 같은 GeoJSON을 사용한다. 기존 Figma 고정 예시였던 월영교·상주 주소와 `156m`는 제거했다.

## 현재 데모 결과

- 출발: POSTECH 인근 `(36.014, 129.325)`
- 목적지: `효곡동 노상1`
- 도로거리: `618.3m`
- 일반 최단경로와 저위험 경로: 동일
- 위험 영향권 교차: `0m`

현재 데이터에서 두 선이 같은 것은 정상 계산 결과다. 실제 차이를 시연하려면 공식 침수·통제 폴리곤을 입력하거나 위험 노출이 있는 출발지·목적지를 사용해야 한다.

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
