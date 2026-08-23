# 온보딩 뷰 구현

> 확인일: 2026-08-23
>
> 상태: `FACT` — Figma 두 화면을 React 컴포넌트로 구현하고 브라우저 검증을 완료했다.

## 구현 기준

| 화면 | Figma 노드 | 직접 확인한 핵심 요소 |
| --- | --- | --- |
| 차량 보호 소개 | [`136:2756`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=136-2756&m=dev) | 402×874, 1/2 진행률, `We save your car from the rain`, 흰색 SUV, `Next` |
| 위치 권한 동의 | [`123:2151`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2151&m=dev) | 402×874, 2/2 진행률, 위치 권한 목적, `Agree & Start` |

Figma에서 제공한 흰색 SUV PNG와 위치 아이콘 SVG를 `frontend/public/assets/onboarding/`에 저장했다. 임시 Figma 에셋 URL은 코드에서 사용하지 않는다.

Figma에 표시된 iPhone 상태바·다이내믹 아일랜드·홈 인디케이터는 화면 예시용 기기 크롬으로 판단해 실제 웹 컴포넌트에서는 제외한다. 브라우저가 제공하는 시스템 UI와 중복 렌더링하지 않는다.

홈 인디케이터 자체는 그리지 않지만, 피그마가 CTA 아래에 둔 34px 레이아웃 여백은 유지한다. 따라서 402×874에서 온보딩 2·3 CTA는 공통으로 `y=778–828`이며, 위치 동의 안내문도 피그마 기준 `y=727`로 함께 정렬한다.

## 빗방울 충돌 애니메이션

- 빗방울 16개가 서로 다른 시간차로 차체의 지붕·유리·보닛 위치까지 낙하한다.
- 충돌 프레임에서 낙하선을 숨기고 작은 물방울 파편이 위·좌우로 튀도록 CSS 키프레임을 연결했다.
- 장식 레이어는 `aria-hidden`이고 클릭을 가로채지 않는다.
- 운영체제에서 동작 줄이기를 설정한 사용자는 기존 `prefers-reduced-motion` 규칙에 따라 반복 애니메이션을 보지 않는다.
- 이 효과는 물리 엔진 기반의 실시간 차체 충돌 판정이 아니라, 402×874 기준 차체 윤곽에 맞춘 충돌 지점 애니메이션이다.

## 사용자 흐름

```text
차량 보호 소개
→ Next
→ 위치 권한 사용 목적 확인
→ Agree & Start
→ 브라우저 위치 권한 요청
→ 지도 홈과 가까운 주차장 시트 동시 표시
```

`Next`는 위치 권한 설명 화면으로 이동하고 `Agree & Start`를 누르면 지도 홈으로 이동하면서 `navigator.geolocation`을 실행한다. 위치를 거부하거나 확인할 수 없으면 기본 경북 중심의 공공주차장을 보여주고 주소 검색을 사용할 수 있다.

## URL과 상태

| URL | 뷰 |
| --- | --- |
| `/` 또는 `?view=car` | 차량 보호 소개 |
| `?view=consent` | 위치 권한 동의 |
| `?view=map` | 지도·주차장 검색 |

단계 이동 때 URL을 갱신하고 브라우저 뒤로가기로 이전 단계에 돌아갈 수 있다. 별도 라우터 패키지는 추가하지 않았다.

## 반응형 처리

- 402×874 이하에서는 화면 전체를 사용한다.
- 넓은 화면에서는 402×874 프레임을 중앙에 배치한다.
- 낮은 화면에서는 자동차 크기와 하단 영역을 축소한다.
- `viewport-fit=cover`, 실제 브라우저 safe-area CSS, 48px 이상의 주요 터치 영역을 유지한다.

## 검증

- `npm run lint` 통과
- `npm run build` 통과
- 402×874에서 두 Figma 화면의 제목·진행률·에셋·버튼 위치 확인
- 402×874에서 두 CTA `y=778–828`, 위치 동의 안내문 `y=727` 확인
- 402×874에서 빗방울 낙하와 차체 충돌 물보라 프레임 확인
- `Next` 후 `?view=consent`, 브라우저 뒤로가기 후 `/` 복귀 확인
- `?view=map`에서 Kakao 지도 렌더링과 폴백 미표시 확인
- 브라우저 경고·오류 0건

품질 검토 기준은 Vercel의 [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md)를 사용했다.
