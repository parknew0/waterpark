import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const csvText = await fs.readFile("data/processed/gyeongbuk_parking_seed.csv", "utf8");
const parkingBook = await Workbook.fromCSV(csvText, { sheetName: "경북_주차장_원본" });
const parkingSheet = parkingBook.worksheets.getItem("경북_주차장_원본");
const used = parkingSheet.getUsedRange();
used.format.font = { name: "Aptos", size: 10, color: "#172033" };
parkingSheet.getRange(`A1:Y1`).format = {
  fill: "#17324D",
  font: { bold: true, color: "#FFFFFF" },
  rowHeight: 28,
  wrapText: true,
};
parkingSheet.freezePanes.freezeRows(1);
parkingSheet.showGridLines = false;
used.format.autofitColumns();
for (const column of ["A:A", "B:B", "E:G", "O:O", "X:X", "Y:Y"]) {
  parkingSheet.getRange(column).format.columnWidth = 24;
}

const readiness = parkingBook.worksheets.add("조인_준비상태");
readiness.getRange("A1:H8").values = [
  ["ID", "데이터", "역할", "경북 범위", "접근", "현재 확보", "주요 조인", "판정"],
  ["D1", "침수흔적도", "라벨", "경북 전체 필터", "회원가입·활용신청", "미확보", "건물 Polygon 공간교차 + 사건시각", "BLOCKED_AUTH"],
  ["D2", "ASOS/AWS 강수", "시간 feature", "경북 관측소", "파일/API", "미확보", "관측소·기준시각", "OPEN_SELECTION"],
  ["D3", "건축물대장", "건물 속성", "경북 22개 시군", "파일/API", "미확보", "관리PK 또는 법정동·지번", "OPEN_KEY"],
  ["D4", "GIS건물통합정보", "기준 건물 Polygon", "경북 22개 시군", "VWorld 로그인", "미확보", "건물 식별자", "BLOCKED_LOGIN"],
  ["D5", "DEM", "고도·경사", "경북 전체", "국토정보플랫폼 로그인", "미확보", "건물 위치 래스터 추출", "BLOCKED_LOGIN"],
  ["D6", "하천중심선", "하천 거리", "경북 전체 clip", "VWorld 로그인", "미확보", "건물-선 최근접 거리", "BLOCKED_LOGIN"],
  ["S1", "전국주차장 표준데이터", "대피 후보", "경북 22개 시군", "공개 다운로드", "2,010행 확보", "좌표 공간조인", "SOURCE_ONLY"],
];
readiness.getRange("A1:H1").format = { fill: "#17324D", font: { bold: true, color: "#FFFFFF" }, rowHeight: 28 };
readiness.getRange("A2:H8").format.wrapText = true;
readiness.getRange("A1:H8").format.autofitColumns();
readiness.getRange("B:B").format.columnWidth = 24;
readiness.getRange("F:H").format.columnWidth = 24;
readiness.freezePanes.freezeRows(1);
readiness.showGridLines = false;

const dictionary = parkingBook.worksheets.add("컬럼_사전");
dictionary.getRange("A1:D14").values = [
  ["구분", "컬럼", "설명", "주의"],
  ["공통", "entity_type", "객체 종류", "현재는 evacuation_parking"],
  ["공통", "entity_id", "기관·관리번호·명칭·주소·좌표의 안정 해시 식별자", "학습용 building_id와 다름"],
  ["위치", "latitude/longitude", "WGS84 위경도", "원천 결측 가능"],
  ["주차장", "capacity", "주차구획수", "실시간 여석이 아님"],
  ["정적위험", "elevation_m", "DEM에서 추출할 표고", "현재 미확보"],
  ["정적위험", "relative_elevation_m", "주변 대비 상대고도", "현재 미확보"],
  ["정적위험", "historical_flood_overlap", "침수흔적 중첩 여부", "현재 미확보"],
  ["정적위험", "nearest_river_distance_m", "최근접 하천 거리", "현재 미확보"],
  ["검증", "safety_verified", "재난 대피 목적지 검증 여부", "모든 행 false"],
  ["품질", "quality_flag", "현 단계 품질 상태", "SOURCE_ONLY는 안전 판정 아님"],
  ["출처", "source_dataset", "원본 데이터명", "출처 추적"],
  ["출처", "source_url", "공식 상세 페이지", "접근일 별도 기록"],
  ["범위", "province/city_county", "경상북도 및 22개 시군", "포항 한정 아님"],
];
dictionary.getRange("A1:D1").format = { fill: "#17324D", font: { bold: true, color: "#FFFFFF" }, rowHeight: 28 };
dictionary.getRange("A1:D14").format.wrapText = true;
dictionary.getRange("A1:D14").format.autofitColumns();
dictionary.getRange("B:D").format.columnWidth = 30;
dictionary.freezePanes.freezeRows(1);
dictionary.showGridLines = false;

const inspection = await parkingBook.inspect({ kind: "sheet,region", maxChars: 3000, tableMaxRows: 5, tableMaxCols: 8 });
console.log(inspection.ndjson ?? inspection);
const output = await SpreadsheetFile.exportXlsx(parkingBook);
await output.save("data/processed/waterpark_gyeongbuk_integration.xlsx");
const preview = await parkingBook.render({ sheetName: "조인_준비상태", autoCrop: "all", scale: 1, format: "png" });
await fs.writeFile("/tmp/waterpark_gyeongbuk_integration_preview.png", new Uint8Array(await preview.arrayBuffer()));
