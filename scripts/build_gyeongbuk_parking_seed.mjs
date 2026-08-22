import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";

const root = process.cwd();
const rawFiles = [
  "data/raw/parking_standard_page_1.json",
  "data/raw/parking_standard_page_2.json",
];
const outputDir = path.join(root, "data/processed");
const cityCountyPattern = /(포항시|경주시|김천시|안동시|구미시|영주시|영천시|상주시|문경시|경산시|의성군|청송군|영양군|영덕군|청도군|고령군|성주군|칠곡군|예천군|봉화군|울진군|울릉군)/;

const pages = await Promise.all(
  rawFiles.map(async (file) => JSON.parse(await fs.readFile(path.join(root, file), "utf8"))),
);
const allRows = pages.flat();

function text(value) {
  return value == null ? "" : String(value).trim();
}

function numberOrNull(value) {
  const normalized = text(value).replaceAll(",", "");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function csvCell(value) {
  if (value == null) return "";
  const stringValue = String(value);
  return /[",\n\r]/.test(stringValue) ? `"${stringValue.replaceAll('"', '""')}"` : stringValue;
}

const rows = allRows
  .map((row) => {
    const address = `${text(row.RDNMADR)} ${text(row.LNMADR)}`.trim();
    const regionText = `${address} ${text(row.INSTT_NM)}`;
    const cityCounty = address.match(cityCountyPattern)?.[1] ?? regionText.match(cityCountyPattern)?.[1] ?? "";
    const identity = [row.INSTT_CODE, row.PRKPLCE_NO, row.PRKPLCE_NM, row.RDNMADR, row.LNMADR, row.LATITUDE, row.LONGITUDE]
      .map(text)
      .join("|");
    return {
      entity_type: "evacuation_parking",
      entity_id: `parking:${createHash("sha256").update(identity).digest("hex").slice(0, 20)}`,
      province: "경상북도",
      city_county: cityCounty,
      name: text(row.PRKPLCE_NM),
      road_address: text(row.RDNMADR),
      lot_address: text(row.LNMADR),
      latitude: numberOrNull(row.LATITUDE),
      longitude: numberOrNull(row.LONGITUDE),
      parking_type: text(row.PRKPLCE_TYPE),
      capacity: numberOrNull(row.PRKCMPRT),
      operation_days: text(row.OPER_DAY),
      weekday_open: text(row.WEEKDAY_OPER_OPEN_HHMM),
      weekday_close: text(row.WEEKDAY_OPER_COLSE_HHMM),
      fee_type: text(row.PARKINGCHRGE_INFO),
      managing_agency: text(row.INSTITUTION_NM),
      reference_date: text(row.REFERENCE_DATE),
      elevation_m: null,
      relative_elevation_m: null,
      historical_flood_overlap: null,
      nearest_river_distance_m: null,
      safety_verified: false,
      source_dataset: "전국주차장정보표준데이터",
      source_url: "https://www.data.go.kr/data/15012896/standard.do",
      quality_flag: cityCounty && numberOrNull(row.LATITUDE) != null && numberOrNull(row.LONGITUDE) != null
        ? "SOURCE_ONLY"
        : "MISSING_LOCATION_OR_REGION",
    };
  })
  .filter((row) => row.city_county && `${row.road_address} ${row.lot_address}`.includes("경상북도"))
  .sort((a, b) => a.city_county.localeCompare(b.city_county, "ko") || a.entity_id.localeCompare(b.entity_id));

const headers = Object.keys(rows[0]);
const csv = [headers.join(","), ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(","))].join("\n") + "\n";

const byCityCounty = Object.entries(
  rows.reduce((counts, row) => {
    counts[row.city_county] = (counts[row.city_county] ?? 0) + 1;
    return counts;
  }, {}),
).map(([city_county, row_count]) => ({ city_county, row_count }));

const manifest = {
  generated_at: new Date().toISOString(),
  scope: "경상북도 22개 시군",
  source_row_count: allRows.length,
  output_row_count: rows.length,
  city_county_count: byCityCounty.length,
  rows_with_coordinates: rows.filter((row) => row.latitude != null && row.longitude != null).length,
  rows_missing_coordinates: rows.filter((row) => row.latitude == null || row.longitude == null).length,
  safety_note: "후보 목록일 뿐 안전 주차장으로 검증되지 않았다. DEM·침수흔적·하천·현장 확인 전 대피 목적지로 사용하지 않는다.",
  by_city_county: byCityCounty,
};

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(path.join(outputDir, "gyeongbuk_parking_seed.csv"), csv, "utf8");
await fs.writeFile(path.join(outputDir, "gyeongbuk_parking_seed.manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
console.log(JSON.stringify(manifest, null, 2));
