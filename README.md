# Waterpark

JunctionX Korea 2026의 `Solve local challenges in Gyeongsangbuk-do using public data.` 트랙 프로젝트입니다.

Waterpark는 경상북도 지하주차장 이용자를 위한 **공공데이터·머신러닝 기반 침수 위험 예측 및 차량 사전 대피 안내 서비스**입니다. 프로젝트 주제와 서비스명은 확정되었습니다.

## 문서

- [해커톤 개발 가이드](./docs/hackathon-development-guide.md): 트랙 요구사항과 심사 기준에 맞춘 개발 원칙
- [데이터 수집 계획](./docs/01-data-collection-plan.md): 공식 제공처별 형식, 컬럼, 접근 방식과 수집 가능성
- [전처리 및 XGBoost 적용 가능성](./docs/02-preprocessing-and-xgboost-feasibility.md): 공간·시간 결합 방식과 학습 데이터 성립 조건
- [경상북도 데이터 통합 실행서](./docs/03-gyeongbuk-data-integration-runbook.md): 실제 확보 데이터, 조인 상태, 재현 절차와 다음 수집 순서
- [건물·강수·침수 데이터 소스 확인서](./docs/04-building-rain-flood-source-verification.md): 건물 위치·지하주차장·시간 강수·침수 기록의 공식 소스와 결합 방법
- [경상북도 건물·고도 실제 추출 결과](./docs/05-gyeongbuk-building-elevation-extraction.md): 305,058개 건물의 위경도·DSM 표고 산출물, 공식 지하주차장 인증 차단과 재실행 방법
- [프론트엔드 작업 기록](./docs/frontend/README.md): Figma 구현 기준, React 컴포넌트, 지도·주소·주차장 API와 품질 검증
- [리서치 로그](./docs/research-log.md): 확인된 사실, 미확정 사항, 조사 결과와 결정 기록
- [AGENTS.md](./AGENTS.md): 후속 AI 에이전트가 따라야 할 작업 범위

## 현재 계획

```text
전처리에 사용할 데이터 판별 및 전처리
→ 머신러닝
→ 백엔드 구축
→ 프론트엔드 전달
```

각 단계의 구체적인 데이터, 방법과 기술은 아직 결정하지 않았습니다. 프로젝트가 진행되면서 조사 결과와 결정 사항을 문서에 계속 반영합니다.

데이터 판별·전처리와 병행해 `frontend/`에서 React 로우파이를 시작했다. 현재는 지도·주소·공영주차장 검색까지만 구현했으며 침수 예측·안전 판정 백엔드 API는 아직 연결하지 않았다.
