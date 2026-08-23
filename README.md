# Waterpark

JunctionX Korea 2026의 `Solve local challenges in Gyeongsangbuk-do using public data.` 트랙 프로젝트입니다.

Waterpark는 경상북도 지하주차장 이용자를 위한 **공공데이터·머신러닝 기반 침수 위험 예측 및 차량 사전 대피 안내 서비스**입니다. 프로젝트 주제와 서비스명은 확정되었습니다!

## 문서

- [해커톤 개발 가이드](./docs/hackathon-development-guide.md): 트랙 요구사항과 심사 기준에 맞춘 개발 원칙
- [데이터 수집 계획](./docs/01-data-collection-plan.md): 공식 제공처별 형식, 컬럼, 접근 방식과 수집 가능성
- [전처리 및 XGBoost 적용 가능성](./docs/02-preprocessing-and-xgboost-feasibility.md): 공간·시간 결합 방식과 학습 데이터 성립 조건
- [경상북도 데이터 통합 실행서](./docs/03-gyeongbuk-data-integration-runbook.md): 실제 확보 데이터, 조인 상태, 재현 절차와 다음 수집 순서
- [건물·강수·침수 데이터 소스 확인서](./docs/04-building-rain-flood-source-verification.md): 건물 위치·지하주차장·시간 강수·침수 기록의 공식 소스와 결합 방법
- [경상북도 건물·고도 실제 추출 결과](./docs/05-gyeongbuk-building-elevation-extraction.md): 건물 위경도·DSM 표고와 건축물대장 지하주차장 후보의 실제 추출 결과
- [경상북도 건축물대장 수집 결과](./outputs/gyeongbuk-building-register/README.md): API 수집 파일, 판정값과 재실행 방법
- [프론트엔드 작업 기록](./docs/frontend/README.md): Figma 구현 기준, React 컴포넌트, 지도·주소·주차장 API와 품질 검증
- [침수 위험 산출 결과](./docs/06-flood-risk-modeling.md): 침수 라벨 타당성 검증, 지형 규칙 기반 위험점수와 XGBoost 평가
- [경상북도 침수 관련 공공데이터 소스 조사](./docs/07-gyeongbuk-flood-data-source-catalog.md): 실제 침수, 모의 위험지도, 강수·수위, 지형·배수 자료의 전체 후보와 우선순위
- [데이터 폴더 안내와 전체 카탈로그](./data/README.md): `raw/interim/processed` 구분과 현재 35개 데이터 자산의 경로·행 수·상태
- [전국 데이터 및 코드 감사](./docs/08-national-data-and-code-audit.md): 전국 침수·건물 다운로드 검증 결과, 필드 한계와 남은 확인 사항
- [전국 확장 타당성 검증](./docs/09-national-expansion-feasibility.md): 서울·경북 실측 비교, 지하주차장 확정 기대치와 남은 수집 대상
- [전국 전처리 파이프라인](./docs/10-nationwide-preprocessing-pipeline.md): 원본부터 학습표까지 각 단계와 그렇게 결정한 이유
- [모델 설계 비교](./docs/11-model-design-comparison.md): 11개 설계를 8개 시도 홀드아웃으로 실측 비교
- [회고와 교훈](./docs/12-retrospective-and-lessons.md): 틀렸던 판단, 어떻게 발견했는지, 방법론으로 남길 것
- [서빙 구조와 배포 준비](./docs/13-serving-architecture-and-deployment.md): 격자 사전계산, Lambda 핸들러, 인프라 구성 근거
- [배포 실행서](./docs/14-deployment-runbook.md): Cloudflare 연결과 Lambda 배포 단계별 절차
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

데이터 판별·전처리와 병행해 `frontend/`에서 React 로우파이를 시작했다. 현재 온보딩·위치 동의·지도·주소·공영주차장 검색까지 구현했으며 침수 예측·안전 판정 백엔드 API는 아직 연결하지 않았다.
