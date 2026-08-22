import type { FormEvent } from "react";
import { ParkingCard } from "./ParkingCard";
import type { ParkingPlace, SearchSource } from "../types/parking";

interface ParkingSearchPanelProps {
  query: string;
  onQueryChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  places: ParkingPlace[];
  selectedId?: string;
  onSelect: (place: ParkingPlace) => void;
  source: SearchSource;
  isLoading: boolean;
  error: string | null;
  hasKakaoKey: boolean;
}

export function ParkingSearchPanel({
  query,
  onQueryChange,
  onSubmit,
  places,
  selectedId,
  onSelect,
  source,
  isLoading,
  error,
  hasKakaoKey,
}: ParkingSearchPanelProps) {
  return (
    <section className="search-panel" aria-labelledby="parking-search-title">
      <div className="sheet-handle" aria-hidden="true" />
      <div className="panel-heading">
        <div>
          <p className="eyebrow">경상북도 22개 시군</p>
          <h2 id="parking-search-title">주차장 검색</h2>
        </div>
        <span className={`source-badge source-badge--${source}`}>
          {source === "kakao" ? "Kakao 실시간 검색" : "좌표 주차장 1,986건"}
        </span>
      </div>

      <form className="search-form" role="search" onSubmit={onSubmit}>
        <label className="visually-hidden" htmlFor="parking-query">주소 또는 주차장 이름</label>
        <input
          id="parking-query"
          name="parking-query"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="예: 경상북도 안동시 풍천면…"
          autoComplete="off"
        />
        <button type="submit" disabled={isLoading}>
          {isLoading ? "검색 중…" : "검색"}
        </button>
      </form>

      {!hasKakaoKey ? (
        <p className="setup-notice">
          Kakao 키가 없어 공공데이터로 동작 중입니다. 지도·주소 API를 켜려면 <code>.env</code>에 키를 입력하세요.
        </p>
      ) : null}
      {error ? <p className="inline-message" role="status" aria-live="polite">{error}</p> : null}

      <div className="result-heading">
        <h3>검색 결과</h3>
        <span className="tabular-nums">{places.length}개 표시</span>
      </div>

      {places.length > 0 ? (
        <ul className="parking-list">
          {places.map((place) => (
            <ParkingCard
              key={place.id}
              place={place}
              selected={selectedId === place.id}
              onSelect={onSelect}
            />
          ))}
        </ul>
      ) : (
        <div className="empty-state">
          <strong>표시할 주차장이 없습니다.</strong>
          <span>경상북도와 시군명을 포함해 다시 검색해 주세요.</span>
        </div>
      )}
    </section>
  );
}
