import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "/Users/neon/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const samplePath = "outputs/gyeongbuk-buildings/gyeongbuk_buildings_elevation_sample.csv";
const municipalityPath = "outputs/gyeongbuk-buildings/gyeongbuk_buildings_by_municipality.csv";
const manifestPath = "data/processed/gyeongbuk_buildings_elevation.manifest.json";
const outputPath = "outputs/gyeongbuk-buildings/waterpark_gyeongbuk_buildings_elevation.xlsx";

const sampleCsv = (await fs.readFile(samplePath, "utf8")).replace(/^\uFEFF/, "");
const municipalityCsv = await fs.readFile(municipalityPath, "utf8");
const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));

const workbook = await Workbook.fromCSV(sampleCsv, { sheetName: "건물_표본_20000" });
const sample = workbook.worksheets.getItem("건물_표본_20000");
const sampleUsed = sample.getUsedRange();
sampleUsed.format.font = { name: "Aptos", size: 9, color: "#172033" };
sample.getRange("A1:AC1").format = {
  fill: "#17324D",
  font: { bold: true, color: "#FFFFFF" },
  rowHeight: 34,
  wrapText: true,
};
sample.freezePanes.freezeRows(1);
sample.showGridLines = false;
sampleUsed.format.autofitColumns();
for (const column of ["A:A", "D:D", "P:R", "W:AB"]) {
  sample.getRange(column).format.columnWidth = 24;
}
sample.getRange("E:F").format.numberFormat = "0.000000";
sample.getRange("T:V").format.numberFormat = "0.00";

const summary = workbook.worksheets.add("산출물_요약");
summary.getRange("A1:D12").values = [
  ["Waterpark 경상북도 건물·고도 데이터", null, null, null],
  ["구분", "값", "상태", "해석"],
  ["경북 건물 행", manifest.row_count, "생성완료", "경북 육지 행정경계로 건물 대표점을 절단"],
  ["표고 확보 행", manifest.elevation_non_null_count, "생성완료", "Copernicus GLO-30 DSM 30m"],
  ["표고 확보율", null, "수식", "표고 결측은 해안·타일 경계 등 확인 대상"],
  ["시군 수", manifest.municipality_count, "검증완료", "경북 22개 시군"],
  ["시군 결측 행", manifest.municipality_null_count, "검증완료", "0행"],
  ["공식 지하주차장 확정", manifest.underground_parking_official_confirmed_count, "미확보", "건축HUB/VWorld 로그인·서비스키 필요"],
  ["지하주차장 미상", manifest.underground_parking_unknown_count, "보수적 처리", "지하층이 있어도 지하주차장으로 추정하지 않음"],
  ["건물 원천", "Overture Maps", "대체 공개 원천", "공식 한국 건축물대장 아님"],
  ["고도 원천", "Copernicus DEM GLO-30 2021", "공개 원천", "DSM: 건물·수목 영향 가능"],
  ["전체 파일", "Parquet + CSV.GZ", "data/processed", "이 XLSX에는 20,000행 표본만 수록"],
];
summary.getRange("B5").formulas = [["=B4/B3"]];
summary.getRange("B5").format.numberFormat = "0.00%";
summary.getRange("A1:D1").merge();
summary.getRange("A1:D1").format = { fill: "#17324D", font: { bold: true, color: "#FFFFFF", size: 16 }, rowHeight: 34 };
summary.getRange("A2:D2").format = { fill: "#2F6B8A", font: { bold: true, color: "#FFFFFF" }, rowHeight: 26 };
summary.getRange("A3:D12").format.wrapText = true;
summary.getRange("A1:D12").format.autofitColumns();
summary.getRange("A:A").format.columnWidth = 28;
summary.getRange("D:D").format.columnWidth = 52;
summary.freezePanes.freezeRows(2);
summary.showGridLines = false;

const municipality = workbook.worksheets.add("시군별_통계");
const municipalityRows = municipalityCsv
  .replace(/^\uFEFF/, "")
  .trim()
  .split(/\r?\n/)
  .map((line, rowIndex) => line.split(",").map((value, index) => rowIndex === 0 || index === 0 ? value : Number(value)));
municipality.getRange(`A1:H${municipalityRows.length}`).values = municipalityRows;
municipality.getRange("A1:H1").format = { fill: "#17324D", font: { bold: true, color: "#FFFFFF" }, rowHeight: 32, wrapText: true };
municipality.getRange(`A2:H${municipalityRows.length}`).format.numberFormat = "0.00";
municipality.getRange(`A1:H${municipalityRows.length}`).format.autofitColumns();
municipality.getRange("A:A").format.columnWidth = 16;
municipality.getRange("B:H").format.columnWidth = 22;
municipality.freezePanes.freezeRows(1);
municipality.showGridLines = false;

const notes = workbook.worksheets.add("판정_및_재실행");
notes.getRange("A1:D13").values = [
  ["항목", "현재 값", "판정", "정확값 확보 방법"],
  ["건물 목록·위경도", "305,058행", "대체 공개 원천 확보", "VWorld 연속수치지형도 건물_경북.zip 로그인 다운로드 후 교체"],
  ["표고", "304,929행", "1차 선별 가능", "국토정보플랫폼 수치표고모델로 교체하고 수직기준 확인"],
  ["상대고도", "약 1km 근방 건물점 DSM 최저값 대비", "스크리닝 전용", "HAND·배수분구·침수흔적·하천망과 결합"],
  ["지하층수", "Overture 6행만 값 있음", "전수성 없음", "건축HUB 표제부 ugrndFlrCnt 수집"],
  ["지하주차장 여부", "305,058행 미상", "모델 입력 불가", "건축HUB 층별개요 지하층+주차장 용도 또는 공식 주차장대장 결합"],
  ["VWorld 파일", "dsId=30162, fileNo=25, 279MB", "로그인 차단 확인", "VWorld 로그인 세션에서 경북 ZIP 다운로드"],
  ["건축HUB", "시도·시군구 필터 확인", "API키/전수 내보내기 필요", "data.go.kr 15134735 활용신청·서비스키 발급"],
  ["FALSE 처리 금지", "미상은 UNKNOWN", "확정", "지하층수 0 또는 정보 없음만으로 지하주차장 없음 단정 금지"],
  ["DSM 주의", "건물·수목 포함 가능", "확정", "침수 수위와 직접 비교 금지"],
  ["음수 표고", "해안 일부 존재", "검토 필요", "지오이드·조위·DSM 오차와 해안 픽셀 확인"],
  ["전체 데이터", "Parquet 32MB / CSV.GZ 16MB", "생성완료", "data/processed에서 사용"],
  ["XLSX 범위", "20,000행 표본", "의도적 제한", "전수 분석은 Parquet 사용"],
];
notes.getRange("A1:D1").format = { fill: "#17324D", font: { bold: true, color: "#FFFFFF" }, rowHeight: 30 };
notes.getRange("A1:D13").format.wrapText = true;
notes.getRange("A1:D13").format.autofitColumns();
notes.getRange("A:D").format.columnWidth = 30;
notes.getRange("D:D").format.columnWidth = 54;
notes.freezePanes.freezeRows(1);
notes.showGridLines = false;

const inspection = await workbook.inspect({ kind: "sheet,region", maxChars: 5000, tableMaxRows: 6, tableMaxCols: 8 });
console.log(inspection.ndjson ?? inspection);
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
const preview = await workbook.render({ sheetName: "산출물_요약", autoCrop: "all", scale: 1, format: "png" });
await fs.writeFile("outputs/gyeongbuk-buildings/waterpark_gyeongbuk_buildings_elevation_preview.png", new Uint8Array(await preview.arrayBuffer()));
