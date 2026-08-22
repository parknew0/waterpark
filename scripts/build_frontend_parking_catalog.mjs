import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";

const root = process.cwd();
const sourceFiles = [
  "data/raw/parking_standard_page_1.json",
  "data/raw/parking_standard_page_2.json",
];
const cityCountyPattern = /(포항시|경주시|김천시|안동시|구미시|영주시|영천시|상주시|문경시|경산시|의성군|청송군|영양군|영덕군|청도군|고령군|성주군|칠곡군|예천군|봉화군|울진군|울릉군)/;

const pages = await Promise.all(
  sourceFiles.map(async (file) => JSON.parse(await fs.readFile(path.join(root, file), "utf8"))),
);

function clean(value) {
  return value == null ? "" : String(value).trim();
}

function numberOrNull(value) {
  const normalized = clean(value).replaceAll(",", "");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

const parking = pages
  .flat()
  .flatMap((row) => {
    const roadAddress = clean(row.RDNMADR);
    const lotAddress = clean(row.LNMADR);
    const address = roadAddress || lotAddress;
    const latitude = numberOrNull(row.LATITUDE);
    const longitude = numberOrNull(row.LONGITUDE);
    const cityCounty = `${address} ${clean(row.INSTT_NM)}`.match(cityCountyPattern)?.[1];
    if (!address.includes("경상북도") || !cityCounty || latitude == null || longitude == null) return [];
    const identity = [row.INSTT_CODE, row.PRKPLCE_NO, row.PRKPLCE_NM, row.RDNMADR, row.LNMADR, row.LATITUDE, row.LONGITUDE]
      .map(clean)
      .join("|");
    return [{
      id: `public:${createHash("sha256").update(identity).digest("hex").slice(0, 20)}`,
      name: clean(row.PRKPLCE_NM) || "이름 없는 공영주차장",
      address,
      cityCounty,
      latitude,
      longitude,
      capacity: numberOrNull(row.PRKCMPRT),
      parkingType: clean(row.PRKPLCE_TYPE),
      source: "public-data",
    }];
  })
  .sort((a, b) => a.cityCounty.localeCompare(b.cityCounty, "ko") || a.name.localeCompare(b.name, "ko"));

const output = path.join(root, "frontend/public/data/gyeongbuk-parking.json");
await fs.mkdir(path.dirname(output), { recursive: true });
await fs.writeFile(output, `${JSON.stringify(parking)}\n`, "utf8");
console.log(JSON.stringify({ output, rows: parking.length }, null, 2));
