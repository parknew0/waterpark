# 지도 홈·내 차 위치 설정 흐름

> 확인일: 2026-08-22
>
> 상태: `FACT` — Figma 관련 노드를 확인해 React로 구현하고 402×874 브라우저에서 상태 전환을 검증했다.

## Figma 구현 기준

| 역할 | 노드 | 구현 |
| --- | --- | --- |
| 지도 홈 | [`123:1415`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1415&m=dev) | 지도, 앱 제목, 현재 위치 라벨, 강수 칩, 안내 문구 |
| 내 차 위치가 설정된 지도 | [`123:1958`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1958&m=dev) | 위치 설정 완료 뒤 현재 위치·내 차·주변 주차장 `P` 마커와 `My Location` 카드 표시 |
| 가까운 주차장 시트 | [`123:2075`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2075&m=dev) | 지도 진입과 동시에 검색창·거리순 상위 3개 목록 표시 |
| 주차장 검색 입력창 | [`123:1631`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1631&m=dev) | 오른쪽 눈·검색 아이콘 없이 플레이스홀더만 표시 |
| 선택 상세 시트 | [`123:2360`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2360&m=dev) | 주차장 사진·주소·거리·침수 위험 영역·차량 위치 설정 버튼 |
| 위치 라벨 | [`123:1419`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-1419&m=dev) | 고정 포항 문구 대신 브라우저 현재 좌표를 주소로 변환해 표시 |
| 현재 위치 마커 | [`123:2320`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2320&m=dev) | 청록 방향 부채꼴과 흰 테두리 청록 점을 현재 좌표에 표시하고 기기 방위에 맞춰 회전 |
| 주차된 내 차 마커 | [`136:2639`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=136-2639&m=dev) | 주차 위치 확정 뒤 선택 지점에 37×37 차 아이콘 표시 |
| 강수 칩 | [`123:2511`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2511&m=dev) | 118×44 칩과 24×24 비 아이콘의 정렬 기준 |

Figma의 지도 이미지는 Kakao 키가 없거나 지도 로드가 실패할 때의 시각적 폴백으로 사용한다. Kakao 키가 정상인 환경에서는 실제 Kakao 지도를 렌더링한다. 목록 사진·상세 사진·위치·비·뒤로가기·검색 에셋은 임시 URL이 아니라 `frontend/public/assets/parking/`에 저장했다.

Kakao 지도 Web API 공식 문서에서 웹 지도용 다크 테마 옵션은 확인되지 않았다. 따라서 실제 Kakao 지도에서는 URL에 `/tile/`이 포함된 이미지를 직접 필터링하지 않고, 해당 이미지들을 담은 하나의 타일 부모 레이어에 grayscale·invert·hue·brightness 필터를 적용한다. 이 방식으로 Figma의 검정·청록 분위기는 유지하면서 타일별 필터 경계선을 없앤다. 현재 위치·내 차·주차장 커스텀 마커와 Kakao 저작권·브랜드 링크는 필터 대상에서 제외해 원래 색상을 유지한다.

## 실행 흐름

```text
온보딩 Next
→ 위치 권한 설명
→ Agree & Start
→ ?view=map
→ 지도 홈 위에 가까운 주차장 시트 즉시 표시
→ navigator.geolocation으로 현재 좌표 요청
→ 좌표 기준 경북 공영주차장 거리순 재정렬
→ Kakao coord2Address로 현재 위치 라벨 생성
→ 목록에서 특정 주차장 선택
→ 선택 상세 시트
→ Set My Car’s Location
→ 현재 위치·선택 지점의 내 차·나머지 주변 주차장 P 마커와 My Location 카드 표시
```

`?view=map`에 들어가면 `123:1415` 지도 위로 `123:2075` 시트를 바로 연다. 목록 또는 검색 결과에서 주차장을 고르면 `123:2360` 상세로 전환한다. 설정 버튼을 누른 뒤에만 시트를 닫고 `123:1958` 최종 지도 상태를 표시한다. 최종 지도에서는 선택한 주차장을 `P`와 중복 표시하지 않고 내 차 마커로 대체하며, 다른 주변 후보 최대 8개만 `P`로 남긴다.

가까운 주차장 시트는 처음 마운트될 때 1.2초 동안 `translateY(100%) → 0`으로 올라온다. 배경 스크림은 360ms 동안 함께 나타나며, 운영체제의 동작 줄이기 설정에서는 전역 `prefers-reduced-motion` 규칙에 따라 반복·긴 전환을 생략한다.

## 데이터와 안전 처리

- 가까운 주차장 목록은 기존 경북 공영주차장 좌표 데이터 1,986건을 현재 좌표와의 거리순으로 정렬한다.
- 주소 검색어를 제출하면 기존 Kakao 장소 검색 또는 공공데이터 폴백을 사용한다.
- 현재 위치 주소는 Kakao 지도 SDK의 `Geocoder.coord2Address`로 역지오코딩한다.
- 위치 좌표를 확보하면 Kakao `CustomOverlay`로 Figma `123:2320` 마커를 표시하고 지도 bounds 계산에도 현재 좌표를 포함한다.
- iOS Safari의 `webkitCompassHeading`을 우선 사용하고, 표준 방향 이벤트의 `alpha`도 상대 방향 폴백으로 사용해 현재 위치 마커의 부채꼴만 회전한다.
- 방향 센서 API는 보안 컨텍스트와 사용자 권한의 영향을 받는다. 절대 방향을 받을 수 없으면 회전은 가능해도 진북 기준은 보장하지 않으며, 센서값 자체가 없으면 Figma 기본 각도를 유지한다.
- 주차장 확정 후 Figma `136:2639` 차 아이콘, 나머지 주변 `P` 마커, 선택 주차장 이름·주소 카드를 표시한다. 현재 구현은 브라우저 메모리 상태이며 새로고침 후 보존하지 않는다.
- 현재 위치를 확인하지 못한 경우 기본 중심 좌표를 현재 위치처럼 표시하지 않고 마커를 생략한다.
- 위치 권한을 거부하거나 사용할 수 없으면 상단 위치 라벨로 상태를 알리고, 지도를 가리는 별도 토스트는 표시하지 않는다.
- 강수량 API가 연결되지 않았으므로 Figma 예시의 `30mm`를 실제 값처럼 표시하지 않고 `--mm`로 둔다.
- 위험 예측 API가 연결되지 않았으므로 Figma 예시의 `High risk`를 특정 주차장 판정처럼 사용하지 않는다. 상세 화면은 `Prototype`과 `Risk assessment is not connected yet`을 표시한다.

## 검증

- `npm run lint` 통과
- `npm run build` 통과
- 402×874에서 가까운 주차장 시트 배치 확인
- 목록 첫 항목 선택 후 상세 시트 전환 확인
- 상세에서 목록으로 돌아가는 버튼 확인
- `Next → ?view=consent → Agree & Start → ?view=map` 전환과 목록 시트 즉시 표시 확인
- Kakao 지도 상태 변경 후 내부 컨트롤 중복 0건 확인
- 목록 시트 상태 후보 마커 0개, 확정 상태 나머지 후보 최대 8개·내 차 마커 1개 확인
- 목록 선택→상세→확정 뒤 `My Location` 카드의 주차장명·주소 확인
- 개별 타일이 아니라 타일 부모 레이어에 다크 필터를 한 번 적용해 타일 경계선이 보이지 않는 것 확인
- 402×874에서 지도를 100px 드래그해 내부 지도 좌표가 실제로 100px 이동하는 것 확인
- 현재 위치 오버레이의 포인터 이벤트를 제거하고 회전축을 현재 위치 점 중심으로 교정
- Figma `123:2511` 기준으로 강수 아이콘의 세 빗줄기 간격 교정
- 현재 위치 부채꼴의 회전 중심, 현재 위치 점의 중심, Kakao 오버레이 anchor를 `(32px, 54px)`로 통일해 회전 시 부채꼴과 점이 분리되지 않는지 확인
- 480px 이하 화면에서 모바일 프레임을 `100vw × 100svh`로 확장하고, 430×932 검증에서 시트 rect가 `x=0`, `width=430`, `bottom=932`인지 확인
- Figma `123:1631` 기준으로 검색 입력창의 잘못된 눈 아이콘과 아이콘 버튼을 모두 제거하고 내부 이미지·버튼 0개 확인
- Figma `123:2320`의 중첩 레이어·inset·기본 `-135°` 회전을 그대로 구현하고, 센서 방위는 이 기본 회전에 합성한다. Kakao anchor는 Figma 점 중심에 맞춘 `x=0.3`, `y=0.71`이다.
- Figma `123:2360`에서 홈 인디케이터가 차지하던 34px 공간을 웹 CTA 하단 여백으로 반영했다. 402×874에서 버튼은 `top=778`, `bottom=828`, 화면 하단 간격 `46px`이다.
- Figma `176:2956`에 따라 `My Location`을 강조색이 아닌 `#EDEDED`로 표시하고 라벨→주차장명 간격 17px, 주차장명→주소 간격 8px을 적용했다.
- 최종 카드의 주차장명·주소는 영문으로 표시한다. 포항 데모 주차장 3곳은 검토한 영문 표기를 사용하고, 다른 동적 결과는 한글 음절을 영문자로 변환하는 폴백을 사용한다. 이는 외부 번역 API 결과가 아니다.
- 임시 검증 좌표에서 Figma 현재 위치 마커 64×64 렌더링, 청록색 유지와 anchor 위치 확인 후 임시 좌표 제거
- 브라우저 경고·오류 0건

테스트 브라우저에서는 위치 권한을 확보하지 못해 기본 중심 데이터가 표시됐다. 실제 위치 라벨과 실제 거리순 결과는 사용자가 브라우저 위치 권한을 허용한 환경에서 최종 확인해야 한다.

출처: [Kakao 지도 Web API 문서](https://apis.map.kakao.com/web/documentation/), [Figma 상세 CTA `123:2360`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=123-2360&m=dev), [Figma My Location 카드 `176:2956`](https://www.figma.com/design/rq2THpj29lq6OhqCq6xcAw/-Junction--Uneducated-Kids?node-id=176-2956&m=dev), [W3C Device Orientation and Motion](https://www.w3.org/TR/orientation-event/), [Apple DeviceOrientationEvent](https://developer.apple.com/documentation/webkitjs/deviceorientationevent)
