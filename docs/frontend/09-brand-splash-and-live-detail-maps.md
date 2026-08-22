# 워드마크·스플래시·상세 실지도

> 구현·확인일: 2026-08-23
>
> 상태: `IMPLEMENTED`

## 변경 내용

- Figma `123:2252`의 흰색 `WATERPARK` 워드마크와 스플래시 `266:3497`의 청록색 그라데이션 워드마크를 모두 SVG로 내려받아 공통 `BrandLogo` 컴포넌트의 variant로 사용한다. export에 포함된 화면 배경 사각형은 제외하고 워드마크 path와 원본 그라데이션·그림자만 유지했다. 두 로고 모두 투명 배경이며 확대해도 깨지지 않는다.
- 지도 홈과 위험·안전 상세 화면에 남아 있던 임시 `APP` 텍스트를 모두 공통 워드마크로 교체했다.
- Figma `50:84`의 원본 차량 공조 패널과 버튼 이미지를 로컬 에셋으로 저장해 최초 진입 스플래시를 구현했다.
- 쿼리 없는 최초 진입은 스플래시를 1.6초 유지하고 전체 화면을 1.1초 동안 `cubic-bezier(.4, 0, .2, 1)`로 페이드아웃한 뒤 기존 첫 온보딩으로 전환한다. `?view=emergency` 같은 발표용 직접 진입 URL은 스플래시를 건너뛴다.
- 이전에 제거하기로 한 예시 기기 UI 원칙에 따라 스플래시의 iOS 상태바는 구현하지 않았다.
- 위험 상세 `119:1140`과 안전 상세 `123:1743` 상단의 정적 지도 미리보기 대신 `VITE_KAKAO_MAP_APP_KEY`를 전달해 실제 Kakao 지도를 렌더링한다.
- 실지도에는 현재 위치, 저위험 경로, 목적지, 침수 위험 폴리곤이 기존 경로 GeoJSON을 기준으로 표시된다. 키가 없거나 SDK 로딩이 실패하면 기존 정적 경로 미리보기로 폴백한다.
- 위험 폴리곤은 Figma `244:3303`의 청록색 발광 표현을 따라, 넓고 낮은 투명도의 외곽 레이어와 선명한 내부 레이어를 겹쳐 표시한다. 기존 갈색·주황색 채움은 제거했다.
- 강수 칩은 Figma `123:2473`에서 내보낸 24×24 Cloud Rain 원본 에셋을 사용한다.
- 위험 예측 문구는 서비스의 사전 예측 설명과 맞춰 모든 상세 화면에서 `in the next 1 hour`로 통일했다.

## 실행과 직접 확인

```bash
cd /Users/neon/Documents/Project/waterpark/frontend
npm run dev
```

- 최초 스플래시: `http://localhost:5173/`를 새 탭에서 연다.
- 위험 상세: `http://localhost:5173/?view=risk-detail`
- 안전 상세: `http://localhost:5173/?view=safe-detail`

Kakao Developers의 JavaScript SDK 도메인에는 실제로 연 origin이 등록돼 있어야 한다. 현재 개발 기준 origin은 `http://localhost:5173`이다.

## 검증

- `npm run build`, `npm run lint`, `git diff --check` 통과
- 브라우저에서 스플래시 원본 이미지·워드마크, 1.1초 페이드아웃과 자동 전환 확인
- 위험·안전 상세 모두 `Kakao 지도 주차장 검색 결과` region, 실제 지도 타일, 현재 위치와 목적지 마커 렌더링 확인
- 소스의 임시 표시 문자열 `APP` 0건 확인

## Figma 출처

- [워드마크 `123:2252`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2252&m=dev)
- [스플래시 `50:84`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=50-84&m=dev)
- [위험 상세 `119:1140`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=119-1140&m=dev)
- [안전 상세 `123:1743`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1743&m=dev)
- [청록색 위험 영역·우회 경로 `244:3303`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=244-3303&m=dev)
