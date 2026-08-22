# Waterpark Frontend

Figma `Lo-Fi` 페이지의 온보딩, 위치 동의, 지도 홈과 `내 차 위치 설정` 화면을 React로 옮긴 프로토타입이다.

```bash
cd frontend
nano .env
npm install
npm run dev
```

Kakao 지도를 사용하려면 Kakao Developers의 JavaScript 키를 `VITE_KAKAO_MAP_APP_KEY`에 넣고 `http://localhost:5173`을 JavaScript SDK 도메인으로 등록한다. 키가 없거나 API가 실패하면 `전국주차장정보표준데이터`에서 추출한 경북 좌표 보유 주차장으로 자동 전환한다.

화면별 직접 확인 주소:

- 차량 보호 온보딩: `http://localhost:5173/?view=car`
- 위치 권한 동의: `http://localhost:5173/?view=consent`
- 지도·주차장 검색: `http://localhost:5173/?view=map`

```bash
npm run lint
npm run build
```

상세 맥락은 `docs/frontend/`에 기록한다.
