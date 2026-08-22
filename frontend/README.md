# Waterpark Frontend

Figma `Lo-Fi` 페이지의 지도 홈과 `내 차 위치 설정` 화면을 React로 옮긴 프로토타입이다.

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Kakao 지도를 사용하려면 Kakao Developers의 JavaScript 키를 `VITE_KAKAO_MAP_APP_KEY`에 넣고 `http://localhost:5173`을 JavaScript SDK 도메인으로 등록한다. 키가 없거나 API가 실패하면 `전국주차장정보표준데이터`에서 추출한 경북 좌표 보유 주차장으로 자동 전환한다.

```bash
npm run lint
npm run build
```

상세 맥락은 `docs/frontend/`에 기록한다.
