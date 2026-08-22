# 온보딩 뷰 구현

> 확인일: 2026-08-22
>
> 상태: `FACT` — Figma 두 화면을 React 컴포넌트로 구현하고 브라우저 검증을 완료했다.

## 구현 기준

| 화면 | Figma 노드 | 직접 확인한 핵심 요소 |
| --- | --- | --- |
| 차량 보호 소개 | [`54:151`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=54-151&m=dev) | 402×874, 1/2 진행률, `We save your car from the rain`, 파란 자동차, `Next` |
| 위치 권한 동의 | [`123:2151`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2151&m=dev) | 402×874, 2/2 진행률, 위치 권한 목적, `Agree & Start` |

Figma에서 제공한 파란 자동차 PNG와 위치 아이콘 SVG를 `frontend/public/assets/onboarding/`에 저장했다. 임시 Figma 에셋 URL은 코드에서 사용하지 않는다.

## 사용자 흐름

```text
차량 보호 소개
→ Next
→ 위치 권한 사용 목적 확인
→ Agree & Start
→ 브라우저 위치 권한 요청
→ 기존 Kakao 지도·주차장 검색 화면
```

`Agree & Start`는 위치 정보 사용 목적을 확인하는 명시적 동작이다. 이후 기존 `navigator.geolocation` 흐름을 실행하며, 거부하거나 확인할 수 없으면 주소 검색을 사용하라는 기존 오류 메시지를 표시한다.

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
- `viewport-fit=cover`, 기존 safe-area CSS, 48px 이상의 주요 터치 영역을 유지한다.

## 검증

- `npm run lint` 통과
- `npm run build` 통과
- 402×874에서 두 Figma 화면의 제목·진행률·에셋·버튼·하단 인디케이터 위치 확인
- `Next` 후 `?view=consent`, 브라우저 뒤로가기 후 `/` 복귀 확인
- `?view=map`에서 Kakao 지도 렌더링과 폴백 미표시 확인
- 브라우저 경고·오류 0건

품질 검토 기준은 Vercel의 [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md)를 사용했다.
