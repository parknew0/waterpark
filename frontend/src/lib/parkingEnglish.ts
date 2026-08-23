import type { ParkingPlace } from "../types/parking";

export interface EnglishParkingLabel {
  name: string;
  address: string;
}

const knownLabels: Record<string, EnglishParkingLabel> = {
  "효자아트홀 앞 노외주차장": {
    name: "Hyoja Art Hall Off-Street Parking Lot",
    address: "780-196 Daejam-dong, Nam-gu, Pohang-si, Gyeongsangbuk-do",
  },
  "효곡동 노상6": {
    name: "Hyogok-dong Street Parking 6",
    address: "24 Hyojadong-gil 5beon-gil, Nam-gu, Pohang-si, Gyeongsangbuk-do",
  },
  "효곡동 노상1": {
    name: "Hyogok-dong Street Parking 1",
    address: "11 Hyojadong-gil 7beon-gil, Nam-gu, Pohang-si, Gyeongsangbuk-do",
  },
  "효곡동 노상8": {
    name: "Hyogok-dong Street Parking 8",
    address: "24 Yudong-gil, Nam-gu, Pohang-si, Gyeongsangbuk-do",
  },
  "우방신세계타운(1차) 지하주차장": {
    name: "Woobang New World Town 1 Underground Parking",
    address: "7 Indeok-dong, Nam-gu, Pohang-si, Gyeongsangbuk-do",
  },
  "제철복지회관 임시주차장": {
    name: "Steel Welfare Center Temporary Parking Lot",
    address: "47-4 Indeok-dong, Nam-gu, Pohang-si, Gyeongsangbuk-do",
  },
  "청림동 노상1": {
    name: "Cheongnim-dong Street Parking 1",
    address: "1113-12 Cheongnim-dong, Nam-gu, Pohang-si, Gyeongsangbuk-do",
  },
};

const initials = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"];
const vowels = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"];
const finals = ["", "k", "k", "ks", "n", "nj", "nh", "t", "l", "lk", "lm", "lb", "ls", "lt", "lp", "lh", "m", "p", "ps", "t", "t", "ng", "t", "t", "k", "t", "p", "h"];

function romanizeHangul(value: string) {
  return Array.from(value).map((character) => {
    const code = character.charCodeAt(0) - 0xac00;
    if (code < 0 || code > 11_171) return character;
    const initial = Math.floor(code / 588);
    const vowel = Math.floor((code % 588) / 28);
    const final = code % 28;
    return `${initials[initial]}${vowels[vowel]}${finals[final]}`;
  }).join("");
}

function capitalize(value: string) {
  return value.replace(/(^|[\s,(-])([a-z])/g, (_, prefix: string, letter: string) => `${prefix}${letter.toUpperCase()}`);
}

function fallbackName(name: string) {
  const normalized = name
    .replace(/공영주차장/g, " Public Parking Lot ")
    .replace(/노외주차장/g, " Off-Street Parking Lot ")
    .replace(/주차장/g, " Parking Lot ")
    .replace(/노상\s*(\d*)/g, " Street Parking $1 ");
  return capitalize(romanizeHangul(normalized).replace(/\s+/g, " ").trim());
}

export function getEnglishAddressLabel(address: string, place: Pick<ParkingPlace, "latitude" | "longitude">) {
  if (!address) return `Lat ${place.latitude.toFixed(5)}, Lng ${place.longitude.toFixed(5)}`;
  const normalized = address
    .replace("경상북도", "Gyeongsangbuk-do,")
    .replace("포항시", "Pohang-si,")
    .replace("경산시", "Gyeongsan-si,")
    .replace("예천군", "Yecheon-gun,")
    .replace("남구", "Nam-gu,")
    .replace("북구", "Buk-gu,");
  return capitalize(romanizeHangul(normalized).replace(/\s+/g, " ").trim());
}

export function getEnglishParkingLabel(place: Pick<ParkingPlace, "name" | "address" | "latitude" | "longitude">): EnglishParkingLabel {
  return knownLabels[place.name] ?? {
    name: fallbackName(place.name),
    address: getEnglishAddressLabel(place.address, place),
  };
}
