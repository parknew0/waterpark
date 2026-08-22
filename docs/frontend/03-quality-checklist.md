# 프론트엔드 품질 검증 기록

> 확인일: 2026-08-22
>
> 기준: Vercel `agent-skills`의 `vercel-react-best-practices`와 `web-design-guidelines`

## 상시 검사 명령

```bash
cd frontend
npm run lint
npm run build
```

UI 변경 시 최신 [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md)를 다시 확인하고 변경한 `tsx`·`css`를 파일·라인 단위로 검토한다.

## 이번 구현에 적용한 항목

- 아이콘 버튼과 지도 Marker 대체 버튼에 접근 가능한 이름 제공
- 입력에 `label`, `name`, `autocomplete` 제공
- 클릭 동작은 `button`, 외부 장소 이동은 추후 `a`로 구현
- 모든 상호작용에 `:focus-visible` 제공
- 로딩·오류는 `aria-live`로 전달
- 긴 주차장명과 주소는 말줄임 처리하고 flex 자식에 `min-width: 0` 적용
- 모바일 safe-area와 바텀시트 `overscroll-behavior` 반영
- 숫자·거리는 `Intl.NumberFormat`과 tabular 숫자 사용
- `transition: all`, 줌 차단, 클릭 가능한 `div`를 사용하지 않음
- 외부 Kakao SDK는 키가 있을 때만 조건부 로딩
- 지도 상호작용을 사용할 수 없는 사람을 위해 같은 결과를 버튼 목록으로 제공

## 검증 결과 기록 형식

| 날짜 | 검사 | 결과 | 후속 작업 |
| --- | --- | --- | --- |
| 2026-08-22 | `npm run lint` | 통과 | 컴포넌트 변경마다 재실행 |
| 2026-08-22 | `npm run build` | TypeScript·Vite production build 통과 | API 키 입력 후 외부 SDK 실호출 재검증 |
| 2026-08-22 | 데스크톱 브라우저 | 검색·목록·선택 구조 정상 | Kakao Marker 클릭 상세 연결은 다음 단계 |
| 2026-08-22 | 402×874 모바일 | Figma 바텀시트 구조, 48×48 위치 버튼, overflow 정상 | 실제 기기 safe-area 확인 |
| 2026-08-22 | `포항시` 검색 | 포항 주차장 20개 표시, 첫 결과 주소 확인 | 검색 반경·정렬 정책은 사용자 테스트 후 조정 |
| 2026-08-22 | Kakao SDK 실호출 | 키 로딩 정상, Kakao 응답 `401 domain mismatched` | JavaScript SDK 도메인 등록 후 재검증 |

초기 브라우저 검사에서 공공 원천의 중복 관리번호 때문에 React key 경고가 발생했다. 기관·관리번호·명칭·주소·좌표의 SHA-256 안정 해시로 ID를 교체했으며 이후 새 경고는 발생하지 않았다.
