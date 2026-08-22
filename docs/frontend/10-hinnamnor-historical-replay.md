# 힌남노 과거 재현 화면

> 구현·확인일: 2026-08-23
>
> 상태: `ISOLATED HISTORICAL REPLAY`

## 분리 원칙

현재 GPS·현재 날짜로 작동하는 기존 Waterpark 화면은 수정하지 않는다. 과거 재현은 Vite의 별도 HTML 진입점과 별도 React 트리로 격리했다.

- 기존 앱: `http://localhost:5173/`
- 힌남노 재현: `http://localhost:5173/hinnamnor.html`
- 진입 HTML: `frontend/hinnamnor.html`
- React 진입점: `frontend/src/historical/hinnamnor-main.tsx`
- 화면: `frontend/src/historical/HinnamnorReplayApp.tsx`
- 전용 스타일: `frontend/src/historical/hinnamnor.css`
- 전용 데이터: `frontend/public/data/hinnamnor-2022-replay.json`
- 데이터 생성기: `scripts/build_hinnamnor_replay.py`

기존 `App.tsx`, 실시간 위치 훅, 현재 경로 화면에는 과거 날짜나 고정 좌표를 주입하지 않았다.

## 시연 위치

포항시 남구 인덕동 `우방신세계타운(1차)` 단지를 중심으로 잡았다.

- 위치 선택 이유: 힌남노 당시 냉천 범람과 지하주차장 침수 피해가 연결된 Waterpark의 핵심 문제를 가장 직접적으로 설명한다.
- 위치 좌표: 저장소의 경북 건물·건축물대장 결합 결과에서 같은 단지명·필지의 건물 6개 대표점 평균을 사용한다.
- 건물 데이터 확인: 6개 건물 행 모두 `CONFIRMED_BASEMENT_PARKING_USE`, 지하층수 최대 1층이다.
- 사고 사실 확인: ADRC 대한민국 국가보고서는 2022년 9월 6일 인덕동 지하주차장 사고에서 7명이 사망하고 2명이 생존했다고 기록한다.

희생이 발생한 사건이므로 화면은 게임 점수·카운트다운·선정적 표현을 사용하지 않고 `historical reconstruction`과 자료 한계를 고정 표시한다.

## 연결 데이터

| 데이터 | 화면 사용 | 상태 |
| --- | --- | --- |
| 기상청 2022 태풍 보고서 | 9월 6일 04:50 거제 동쪽 상륙 시각 | `CONFIRMED` |
| 포항관측소 실측 기반 강우 | 1시간 77.0mm, 2시간 147.9mm, 3시간 203.2mm, 6시간 314.5mm, 9시간 359.8mm, 12시간 378.7mm | `CONFIRMED IN STUDY` |
| 기상청 2022년 9월 기후자료 | 9월 6일 달력일 강수량 342.4mm | `CONFIRMED` |
| 건물·건축물대장 결합 결과 | 단지 중심, 지하주차장 확인, 지하층수, DSM 최소 표고 | `LOCAL DERIVED PUBLIC DATA` |
| OSM 냉천 선형 | 실제 지도 위 냉천 위치 표시 | `CURRENT OSM`, 2022 스냅샷 아님 |
| 붉은 확장 영역 | 시간 단계별 시각 효과 | `ILLUSTRATIVE`, 실제 침수 폴리곤 아님 |

달력일 강수량보다 9·12시간 이동누적 강수량이 큰 것은 이동창이 9월 5일과 6일 자정을 가로지를 수 있기 때문이다.

## 침수 폴리곤 한계

현재 저장소의 행정안전부 침수흔적도 경북 부분집합은 파일명에 2022가 포함되지만 실제 `fldn_yr` 최댓값은 2021이다. 따라서 힌남노 실제 침수 영역이라고 주장할 수 있는 Polygon은 현재 없다.

화면의 붉은 영역은 사건의 충격을 전달하기 위한 원형 영향 범위이며 다음 문구를 항상 표시한다.

> Red area is a reconstruction cue—not a measured flood boundary.

추후 2022 힌남노 침수흔적 Polygon 또는 검증된 위성 탐지 범위를 확보하면 이 전용 JSON의 재현 반경을 실제 Geometry로 교체한다.

## 실행

```bash
cd /Users/neon/Documents/Project/waterpark/frontend
npm run dev
```

브라우저에서 `http://localhost:5173/hinnamnor.html`을 연다. 강우·건물·하천 전용 JSON을 다시 만들려면 저장소 루트에서 다음을 실행한다.

```bash
./.venv/bin/python scripts/build_hinnamnor_replay.py
```

생성기는 로컬 건물 결과를 읽고 OSM에서 현재 냉천 선형을 조회하므로 인터넷 연결이 필요하다.

## 출처

- [기상청 2022 태풍 보고서](https://www.kma.go.kr/download_01/typhoon/typreport_2022.pdf)
- [기상청 2022년 9월 기후 뉴스레터](https://www.weather.go.kr/download_02/ellinonewsletter_2022_09.pdf)
- [냉천 유역 힌남노 수문 연구](https://journal.dssms.org/articles/xml/5aEx/)
- [ADRC 대한민국 국가보고서 FY2024](https://web.adrc.asia/countryreport/KOR/2024/Korea_CountryReport_FY2024.pdf)
- [행정안전부 침수흔적도 공식 페이지](https://www.safetydata.go.kr/disaster-data/view?dataSn=108)
