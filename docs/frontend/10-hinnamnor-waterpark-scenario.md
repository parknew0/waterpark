# 힌남노 상황으로 실행하는 Waterpark 전체 플로우

> 구현일: 2026-08-23
>
> 상태: `FACT` — 별도 아카이브 페이지를 제거하고 기존 Waterpark 앱에 격리된 과거 시나리오 입력을 연결했다.

## 목적

이 구현은 힌남노 정보를 보여주는 별도 데이터 대시보드가 아니다. **사용자가 평소 사용하는 Waterpark 앱이 힌남노 당시의 위치와 강우 조건을 입력받았다면 어떤 순서로 차량 대피를 안내했을지** 기존 UI 흐름으로 재연한다.

```text
Splash
→ Onboarding
→ Set My Car’s Location
→ Waterpark home
├─ Select a parking lot on the live map
│  ├─ High risk → Warning detail → nearest lower-risk candidate route
│  └─ Low risk → Safe detail → selected parking route
└─ Move your car right now → nearest lower-risk candidate → OSM road route
```

## 실행

```bash
cd /Users/neon/Documents/Project/waterpark/frontend
npm run dev
```

- 평상시 앱: `http://localhost:5173/`
- 힌남노 재연: `http://localhost:5173/?scenario=hinnamnor`
- 재연용 긴급 파라미터: `http://localhost:5173/?scenario=hinnamnor&view=emergency` — URL에 `view=emergency`가 있어도 첫 로드는 항상 Splash부터 시작한다.

재연 모드에서도 Splash·온보딩·지도·바텀시트·긴급 경고·상세·길찾기는 기존 Waterpark 컴포넌트를 그대로 사용한다. 차량 위치 확정 CTA를 누르면 홈 화면을 1.8초 보여준 뒤 긴급 경고가 자동으로 열린다. 긴급 CTA를 누르면 주차장 선택 화면으로 돌아가지 않고, 안전 후보별 침수 회피 경로를 계산해 도로거리가 가장 짧은 후보로 즉시 안내한다. 화면에는 `Hinnamnor Replay`나 과거 시나리오 설명을 노출하지 않는다.

힌남노 재연 URL은 발표자가 중간 화면 쿼리를 복사해 열더라도 시나리오 맥락을 건너뛰지 않도록 첫 페이지 로드에서 `view`를 무시한다. Splash 페이드아웃이 끝나면 `view`를 제거하고 정상 온보딩 흐름을 시작한다. 앱 내부 history 이동에서는 현재 화면을 유지한다.

- 홈에서 위험 후보 선택 → `Warning` 상세
- 홈에서 저위험 후보 선택 → `Safe` 상세
- `Warning` CTA 또는 긴급 CTA → 모든 안전 후보의 경로를 비교한 뒤 최인접 후보 길찾기
- `Safe` CTA → 사용자가 선택한 후보까지의 실제 OSM 도로 경로

재연 모드는 발표가 힌남노 피해 지역에서 일관되게 이어지도록 오천읍 구정길의 시연 출발점을 사용하며 발표자의 브라우저 GPS로 바꾸지 않는다. 긴급 상황에서는 저장한 내 차 위치를 출발점으로 제철복지회관과 청림동 노상1까지의 경로를 각각 계산한다. 현재 데모 입력에서는 제철복지회관 저위험 우회가 `2,594.8m`, 청림동 노상1 경로가 `1,391.0m`이므로 후자를 자동 선택하며 UI에는 `1.4km`, `6 min`으로 표시한다.

위험/안전 분기는 현재 `frontend/src/lib/parkingRisk.ts`의 API 경계 뒤에 있다. 아직 백엔드 계약이 확정되지 않아 HTTP URL이나 응답 스키마를 임의로 만들지 않았고, 힌남노 재연에서는 두 시나리오 후보를 결정적으로 분기한다.

## 시나리오 입력

| 입력 | 값 | 근거와 의미 |
| --- | --- | --- |
| 사용자 시연 위치 | 오천읍 구정길, `35.9816, 129.4103` | 내 차 위치와 약 480m 떨어져 첫 이동 경로가 분명히 보이는 출발점 |
| 차량 위치 | 우방신세계타운 1차 지하주차장 | 로컬 건축물대장 결합에서 6동 모두 지하주차장 용도 확인 |
| 지도 강우 칩 | `77mm` | 포항관측소 관측 기반 연구의 최대 1시간 이동누적 강우 |
| 예측 범위 UI | `1 hour` | Waterpark의 1시간 선행 위험 안내 제품 명세 |
| 대피 후보 | 제철복지회관·청림동 노상1 | 경상북도 공영주차장 가공 데이터의 실제 후보, 안전 확정 아님 |
| 제철복지회관 경로 | `2,594.8m`, UI `11 min` | 일반 최단경로의 침수 교차 간선 제거 후 재계산 |
| 자동 선택 경로 | 청림동 노상1 `1,391.0m`, UI `6 min` | 후보별 저위험 도로거리 비교 결과 최단 후보 |

시나리오 데이터는 `frontend/src/scenarios/hinnamnorScenario.ts`에 격리했다. 경로는 `scripts/build_flood_aware_route.py`를 인덕동 좌표로 실행해 `frontend/public/data/hinnamnor-waterpark-flow.geojson`에 저장했다. 따라서 기본 앱의 브라우저 GPS나 기본 경로 파일은 변경하지 않는다.

## 중요한 한계

- 현재 확보한 행정안전부 침수흔적도 경북 자료의 마지막 연도는 2021년이라 2022년 힌남노의 실제 침수 Polygon이 없다.
- 화면의 위험 영역은 로컬 상시 지표면 침수 위험도에서 생성한 정적 영역이다. 힌남노 당시 관측 침수 경계나 실제 도로 통제선이 아니다.
- `77mm`는 해당 화면 시각의 실시간 관측값이 아니라 연구에 정리된 힌남노 기간 최대 1시간 이동누적 강우다.
- 목적지는 공공 주차장 데이터와 정적 위험도를 이용한 **저위험 후보**이며, 당시 수용 가능 여부나 절대 안전을 뜻하지 않는다.
- 긴급 경고 전환 시점과 `1 hour`는 Waterpark 제품 플로우 재연을 위한 UI 시나리오다. 2022년에 실제 서비스가 산출한 예측 결과가 아니다.
- `Safe`는 실제 안전 인증이 아니라 현재 정적 위험·경로 입력에서의 상대적인 저위험 판정이다.
- `CURRENT` 폴리곤은 우회 계산을 검증하기 위한 합성 힌남노 재연 입력이며 2022년 실측 침수 경계가 아니다.
- 운영 단계에서는 합성 폴리곤을 공식 침수·도로 통제 입력으로 교체해야 한다.

## 출처

- [기상청 2022 태풍 보고서](https://www.kma.go.kr/download_01/typhoon/typreport_2022.pdf)
- [기상청 2022년 9월 기후 뉴스레터](https://www.weather.go.kr/download_02/ellinonewsletter_2022_09.pdf)
- [냉천 유역 힌남노 수문 연구](https://journal.dssms.org/articles/xml/5aEx/)
- [ADRC 대한민국 국가보고서 FY2024](https://web.adrc.asia/countryreport/KOR/2024/Korea_CountryReport_FY2024.pdf)
- [행정안전부 침수흔적도](https://www.safetydata.go.kr/disaster-data/view?dataSn=108)
- [전국주차장정보표준데이터](https://www.data.go.kr/data/15012896/standard.do)
- [OpenStreetMap 저작권과 라이선스](https://www.openstreetmap.org/copyright)
- [NetworkX shortest_path](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.generic.shortest_path.html)
