# Waterpark 프론트엔드 작업 기록

이 폴더는 프론트엔드의 결정, 구현 상태, 외부 API와 검증 결과를 누적 기록한다. Figma는 바뀔 수 있으므로 구현 기준 노드와 확인일을 함께 남긴다.

## 현재 상태

- 확인일: 2026-08-22
- 구현 단계: 로우파이 컴포넌트와 지도·주차장 검색 연결
- 앱 경로: `frontend/`
- Figma 파일: `Junction / Uneducated Kids`
- 기준 노드: 지도 홈 `117:510`, 내 차 위치 설정 `123:1610`
- 범위: 경상북도 22개 시군

## 문서

- [구조와 컴포넌트](./01-architecture-and-components.md)
- [지도·주소·주차장 API](./02-map-and-parking-api.md)
- [품질 검증 기록](./03-quality-checklist.md)
- [온보딩 뷰와 빗방울 충돌 효과](./04-onboarding-views.md)

화면이나 API 결정이 바뀌면 코드와 이 문서를 같은 커밋에서 수정한다.
