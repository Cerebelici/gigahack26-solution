import { useMemo, type CSSProperties, type ReactNode, type SyntheticEvent } from "react";
import type { ParcelLookup } from "../../api/geodata";
import { CountUp } from "../../components/CountUp";
import type { MarkerGroup } from "./MapView";
import { MAP_COLORS } from "./palette";
import { asNumber, formatArea, formatHectares, formatMetres } from "./project";
import type { FieldFeature } from "./types";

const stop = (event: SyntheticEvent) => event.stopPropagation();

const cardEvents = { onClick: stop, onPointerDown: stop, onDoubleClick: stop, onWheel: stop };

const LABEL_NAMES: Record<string, string> = {
  vineyard: "Canopy",
  interrow_area: "Inter-row",
  waste: "Waste",
  row: "Row axis",
  route: "Route",
};

const LABEL_COLORS: Record<string, string> = {
  vineyard: MAP_COLORS.canopy,
  interrow_area: MAP_COLORS.interrowLine,
  waste: MAP_COLORS.waste,
  row: MAP_COLORS.row,
  route: MAP_COLORS.route,
};

const STRUCTURES = [
  { key: "regular", label: "Regular", color: "var(--green)" },
  { key: "disrupted", label: "Disrupted", color: "var(--gold)" },
  { key: "unassessable", label: "Unassessable", color: "#a9b9ae" },
] as const;

const COVERS = [
  { key: "bare_soil", label: "Bare soil" },
  { key: "vegetation", label: "Vegetation" },
  { key: "mixed", label: "Mixed" },
] as const;

const ATTRIBUTE_COLORS: Record<string, string> = {
  regular: "var(--green)",
  disrupted: "var(--gold)",
  unassessable: "#a9b9ae",
  bare_soil: "#c9a45c",
  vegetation: "var(--green)",
  mixed: "var(--violet)",
};

const text = (value: unknown) => (value === null || value === undefined || value === "" ? null : String(value));

const humanize = (value: string) => value.replace(/_/g, " ");

/** Stagger slot for list entry animations. */
const staggered = (index: number) => ({ "--i": index }) as CSSProperties;

/** Share of a total that the map reveal has drawn so far. */
const revealed = (value: number, share: number) => (share >= 1 ? value : value * share);

export function MapBanner({ children }: { children: ReactNode }) {
  return (
    <div className="gbm-banner gbm-float" role="status" {...cardEvents}>
      <span className="gbm-banner-dot" aria-hidden="true" />
      {children}
    </div>
  );
}

export function SampleBanner() {
  return <MapBanner>Sample data, not a project — sign in to open your own projects.</MapBanner>;
}

interface BlocksCardProps {
  blocks: string[];
  items: FieldFeature[];
  activeBlock: string | null;
  onChange: (block: string | null) => void;
  /** 0–1 while the map reveal is drawing rows. */
  rowShare?: number;
}

function RowSummary({ rows, share }: { rows: FieldFeature[]; share: number }) {
  const length = rows.reduce((sum, row) => sum + (row.lengthM ?? 0), 0);
  const count = Math.round(revealed(rows.length, share));
  return (
    <span className="gbm-block-meta">
      <CountUp value={count} /> {rows.length === 1 ? "row" : "rows"} ·{" "}
      <CountUp value={revealed(length, share)} format={formatMetres} />
    </span>
  );
}

export function BlocksCard({ blocks, items, activeBlock, onChange, rowShare = 1 }: BlocksCardProps) {
  const rows = items.filter((item) => item.label === "row");
  return (
    <aside className="gbm-card gbm-blocks gbm-float" {...cardEvents}>
      <div className="gbm-card-title">
        <h2>Blocks</h2>
        <span>
          <CountUp value={blocks.length} /> {blocks.length === 1 ? "block" : "blocks"}
        </span>
      </div>
      <ul className="gbm-block-list gbm-stagger">
        <li style={staggered(0)}>
          <button
            type="button"
            className={activeBlock === null ? "gbm-block is-active" : "gbm-block"}
            onClick={() => onChange(null)}
          >
            <span className="gbm-block-name">All blocks</span>
            <RowSummary rows={rows} share={rowShare} />
          </button>
        </li>
        {blocks.map((block, index) => (
          <li key={block} style={staggered(index + 1)}>
            <button
              type="button"
              className={activeBlock === block ? "gbm-block is-active" : "gbm-block"}
              onClick={() => onChange(activeBlock === block ? null : block)}
            >
              <span className="gbm-block-name">{block}</span>
              <RowSummary rows={rows.filter((row) => row.block === block)} share={rowShare} />
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}

function SectionHead({ title, meta }: { title: string; meta?: ReactNode }) {
  return (
    <div className="gbm-section-head">
      <h4>{title}</h4>
      {meta !== undefined && <span>{meta}</span>}
    </div>
  );
}

function AttributeValue({ value }: { value: string }) {
  return (
    <span className="gbm-attr">
      <span className="gbm-dot" style={{ background: ATTRIBUTE_COLORS[value] ?? "var(--muted)" }} />
      {humanize(value)}
    </span>
  );
}

function KeyValues({ rows }: { rows: Array<{ term: string; value: ReactNode | null }> }) {
  return (
    <dl className="gbm-kv gbm-stagger">
      {rows
        .filter(({ value }) => value !== null)
        .map(({ term, value }, index) => (
          <div key={term} style={staggered(index)}>
            <dt>{term}</dt>
            <dd>{value}</dd>
          </div>
        ))}
    </dl>
  );
}

function ObjectDetail({ item, onClear }: { item: FieldFeature; onClear: () => void }) {
  const isRow = item.label === "row";
  const name = LABEL_NAMES[item.label] ?? humanize(item.label);
  const structure = text(item.props.row_structure);
  const cover = text(item.props.interrow_cover);
  const grapevines = asNumber(item.props.grapevine_count);
  const areaHa = asNumber(item.props.area_ha) ?? (item.areaM2 === null ? null : item.areaM2 / 10_000);
  const title = isRow ? (item.rowId ?? "Row") : (text(item.props.route_id) ?? name);

  return (
    <section className="gbm-section gbm-detail" aria-live="polite">
      <div className="gbm-detail-head">
        <div>
          <div className="gbm-eyebrow">
            <span className="gbm-dot" style={{ background: LABEL_COLORS[item.label] ?? "var(--muted)" }} />
            {isRow ? "Row axis" : name}
          </div>
          <h3>{title}</h3>
        </div>
        <button type="button" className="gbm-text-btn" onClick={onClear}>
          Clear
        </button>
      </div>

      {isRow ? (
        <>
          <div className="gbm-stat-pair">
            <div className="gbm-stat">
              <span className="gbm-stat-value">{grapevines === null ? "—" : <CountUp value={grapevines} />}</span>
              <span className="gbm-stat-label">Grapevines</span>
            </div>
            <div className="gbm-stat">
              <span className="gbm-stat-value">
                {item.lengthM === null ? "—" : <CountUp value={item.lengthM} format={formatMetres} />}
              </span>
              <span className="gbm-stat-label">Total length</span>
            </div>
          </div>
          <KeyValues
            rows={[
              { term: "Block", value: item.block || "—" },
              { term: "Structure", value: structure ? <AttributeValue value={structure} /> : "—" },
            ]}
          />
        </>
      ) : (
        <KeyValues
          rows={[
            { term: "Label", value: item.label },
            { term: "Block", value: item.block || "—" },
            { term: "Row", value: item.rowId },
            { term: "Area", value: item.areaM2 === null ? null : <CountUp value={item.areaM2} format={formatArea} /> },
            { term: "Area (ha)", value: areaHa === null ? null : <CountUp value={areaHa} format={formatHectares} /> },
            {
              term: "Length",
              value: item.lengthM === null ? null : <CountUp value={item.lengthM} format={formatMetres} />,
            },
            { term: "Structure", value: structure ? <AttributeValue value={structure} /> : null },
            { term: "Inter-row cover", value: cover ? <AttributeValue value={cover} /> : null },
          ]}
        />
      )}
    </section>
  );
}

function StructureBubbles({ counts, share }: { counts: Record<string, number>; share: number }) {
  const max = Math.max(1, ...STRUCTURES.map((s) => counts[s.key] ?? 0));
  return (
    <div className="gbm-bubbles">
      {STRUCTURES.map((structure) => {
        const count = Math.round(revealed(counts[structure.key] ?? 0, share));
        const size = 38 + 30 * (count / max);
        return (
          <div key={structure.key} className="gbm-bubble-item">
            <span
              className="gbm-bubble"
              style={{ width: size, height: size, "--bubble": structure.color, opacity: count ? 1 : 0.35 } as CSSProperties}
            >
              <CountUp value={count} />
            </span>
            <span className="gbm-bubble-label">{structure.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function RowBars({
  rows,
  selectedId,
  share,
  onSelect,
}: {
  rows: FieldFeature[];
  selectedId: number | null;
  share: number;
  onSelect: (fid: number) => void;
}) {
  const max = Math.max(1, ...rows.map((row) => row.lengthM ?? 0));
  if (rows.length === 0) return <p className="gbm-empty">No row axes in this tile.</p>;
  return (
    <ul className="gbm-bars gbm-stagger">
      {rows.map((row, index) => (
        <li key={row.fid} style={staggered(index)}>
          <button
            type="button"
            className={row.fid === selectedId ? "gbm-bar is-active" : "gbm-bar"}
            onClick={() => onSelect(row.fid)}
          >
            <span className="gbm-bar-label">{row.rowId ?? `#${row.fid}`}</span>
            <span className="gbm-bar-track">
              <span className="gbm-bar-fill" style={{ width: `${(revealed(row.lengthM ?? 0, share) / max) * 100}%` }} />
            </span>
            <span className="gbm-bar-value">
              <CountUp value={revealed(row.lengthM ?? 0, share)} format={formatMetres} />
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

interface CoverStat {
  key: string;
  label: string;
  count: number;
  area: number;
}

function CoverRadar({ stats, share }: { stats: CoverStat[]; share: number }) {
  const cx = 120;
  const cy = 92;
  const radius = 58;
  const angles = [-90, 30, 150].map((deg) => (deg * Math.PI) / 180);
  const point = (angle: number, r: number) => `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
  const ring = (fraction: number) => angles.map((a) => point(a, radius * fraction)).join(" ");

  const maxCount = Math.max(1, ...stats.map((s) => s.count));
  const maxArea = Math.max(1e-9, ...stats.map((s) => s.area));
  const shape = (values: number[], max: number) =>
    angles.map((a, i) => point(a, radius * Math.max(0.07, values[i] / max))).join(" ");

  return (
    <div className="gbm-radar">
      <svg viewBox="0 0 240 180" role="img" aria-label="Inter-row cover by count and area">
        {[1 / 3, 2 / 3, 1].map((fraction) => (
          <polygon key={fraction} points={ring(fraction)} className="gbm-radar-ring" />
        ))}
        {angles.map((a) => (
          <line key={a} x1={cx} y1={cy} x2={cx + radius * Math.cos(a)} y2={cy + radius * Math.sin(a)} className="gbm-radar-axis" />
        ))}
        <polygon points={shape(stats.map((s) => s.area), maxArea)} className="gbm-radar-area" />
        <polygon points={shape(stats.map((s) => s.count), maxCount)} className="gbm-radar-count" />
        {stats.map((stat, i) => {
          const a = angles[i];
          const x = cx + (radius + 16) * Math.cos(a);
          const y = cy + (radius + 16) * Math.sin(a) + (i === 0 ? -2 : 10);
          return (
            <text key={stat.key} x={x} y={y} textAnchor="middle" className="gbm-radar-label">
              {stat.label} · {Math.round(revealed(stat.count, share))}
            </text>
          );
        })}
      </svg>
      <div className="gbm-radar-legend">
        <span>
          <i style={{ background: "var(--violet)" }} /> Objects
        </span>
        <span>
          <i style={{ background: "var(--green)" }} /> Area
        </span>
      </div>
    </div>
  );
}

interface DetailCardProps {
  items: FieldFeature[];
  selected: FieldFeature | null;
  onSelect: (fid: number | null) => void;
  /** 0–1 while the map reveal is drawing rows and polygons. */
  rowShare?: number;
  polygonShare?: number;
}

export function DetailCard({ items, selected, onSelect, rowShare = 1, polygonShare = 1 }: DetailCardProps) {
  const summary = useMemo(() => {
    const rows = items.filter((item) => item.label === "row");
    const structureCounts: Record<string, number> = {};
    for (const row of rows) {
      const key = text(row.props.row_structure);
      if (key) structureCounts[key] = (structureCounts[key] ?? 0) + 1;
    }
    const longest = [...rows].sort((a, b) => (b.lengthM ?? 0) - (a.lengthM ?? 0)).slice(0, 5);
    const totalLength = rows.reduce((sum, row) => sum + (row.lengthM ?? 0), 0);
    const interrows = items.filter((item) => item.label === "interrow_area");
    const covers: CoverStat[] = COVERS.map(({ key, label }) => {
      const matching = interrows.filter((item) => item.props.interrow_cover === key);
      return {
        key,
        label,
        count: matching.length,
        area: matching.reduce((sum, item) => sum + (item.areaM2 ?? 0), 0),
      };
    });
    return { rows, structureCounts, longest, totalLength, interrowCount: interrows.length, covers };
  }, [items]);

  return (
    <aside className="gbm-card gbm-detail-card gbm-float" {...cardEvents}>
      {selected && <ObjectDetail item={selected} onClear={() => onSelect(null)} />}

      <section className="gbm-section">
        <SectionHead
          title="Row structure"
          meta={
            <>
              <CountUp value={Math.round(revealed(summary.rows.length, rowShare))} /> rows
            </>
          }
        />
        <StructureBubbles counts={summary.structureCounts} share={rowShare} />
      </section>

      <section className="gbm-section">
        <SectionHead
          title="Longest rows"
          meta={
            <>
              Σ <CountUp value={revealed(summary.totalLength, rowShare)} format={formatMetres} />
            </>
          }
        />
        <RowBars rows={summary.longest} selectedId={selected?.fid ?? null} share={rowShare} onSelect={onSelect} />
      </section>

      <section className="gbm-section">
        <SectionHead
          title="Inter-row cover"
          meta={
            <>
              <CountUp value={Math.round(revealed(summary.interrowCount, polygonShare))} /> polygons
            </>
          }
        />
        {summary.interrowCount === 0 ? (
          <p className="gbm-empty">No inter-row polygons in this tile.</p>
        ) : (
          <CoverRadar stats={summary.covers} share={polygonShare} />
        )}
      </section>
    </aside>
  );
}

export type ParcelPhase = "loading" | "ready" | "error";

export function ParcelCard({
  phase,
  lookup,
  error,
  onClear,
}: {
  phase: ParcelPhase;
  lookup: ParcelLookup | null;
  error: string | null;
  onClear: () => void;
}) {
  const parcel = phase === "ready" ? (lookup?.parcel ?? null) : null;
  const title =
    parcel?.cadastralCode ??
    (phase === "loading" ? "Looking up…" : phase === "error" ? "Lookup failed" : "No parcel");

  return (
    <aside className="gbm-card gbm-parcel-card gbm-float" aria-live="polite" aria-label="Cadastral parcel" {...cardEvents}>
      <div className="gbm-detail-head">
        <div>
          <div className="gbm-eyebrow">
            <span className="gbm-dot" style={{ background: MAP_COLORS.parcel }} />
            Cadastral parcel
          </div>
          <h3>{title}</h3>
        </div>
        <button type="button" className="gbm-text-btn" onClick={onClear}>
          Clear
        </button>
      </div>
      {phase === "loading" && <p className="gbm-empty">Asking the cadastral service…</p>}
      {phase === "error" && <p className="gbm-empty">{error}</p>}
      {phase === "ready" && !parcel && <p className="gbm-empty">No cadastral parcel at this point.</p>}
      {parcel && (
        <KeyValues
          rows={[
            { term: "Parcel", value: parcel.parcelCode },
            { term: "Area", value: parcel.area },
            { term: "Land use", value: parcel.landUse },
            { term: "Property", value: parcel.propertyType },
            { term: "Locality", value: parcel.locality },
            { term: "District", value: parcel.district },
          ]}
        />
      )}
    </aside>
  );
}

const LEGEND = [
  { group: "canopy", label: "Canopy", fill: MAP_COLORS.canopy, border: MAP_COLORS.canopyLine, kind: "area" },
  { group: "interrow", label: "Inter-row", fill: MAP_COLORS.interrow, border: MAP_COLORS.interrowLine, kind: "area" },
  { group: "row", label: "Row", fill: MAP_COLORS.row, border: MAP_COLORS.row, kind: "line" },
  { group: "waste", label: "Waste", fill: "transparent", border: MAP_COLORS.waste, kind: "box" },
  { group: "route", label: "Route", fill: MAP_COLORS.route, border: MAP_COLORS.route, kind: "line" },
  { group: "parcel", label: "Parcel", fill: MAP_COLORS.parcel, border: MAP_COLORS.parcelLine, kind: "area" },
] as const satisfies ReadonlyArray<{ group: MarkerGroup; label: string; fill: string; border: string; kind: string }>;

interface LegendChipProps {
  hidden: ReadonlySet<MarkerGroup>;
  onToggle: (group: MarkerGroup) => void;
}

export function LegendChip({ hidden, onToggle }: LegendChipProps) {
  return (
    <div className="gbm-legend gbm-float" role="group" aria-label="Map layers" {...cardEvents}>
      {LEGEND.map((entry) => {
        const shown = !hidden.has(entry.group);
        return (
          <button
            key={entry.group}
            type="button"
            className={shown ? "gbm-legend-item" : "gbm-legend-item is-off"}
            aria-pressed={shown}
            title={shown ? `Hide ${entry.label.toLowerCase()}` : `Show ${entry.label.toLowerCase()}`}
            onClick={() => onToggle(entry.group)}
          >
            <i
              className={`gbm-swatch gbm-swatch-${entry.kind}`}
              style={{ background: entry.fill, borderColor: entry.border }}
            />
            {entry.label}
          </button>
        );
      })}
    </div>
  );
}
