import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { opsRepository } from '../api/repositories'
import { buildGrafanaLinks } from '../features/ops/grafanaLinks'
import CongestionHeatmapView from '../features/ops/CongestionHeatmap'
import {
  destroyStockOverlays,
  syncStockOverlays,
  type StockOverlay,
} from '../features/ops/bikeStockLayer'
import { useOpsMap, type OpsBounds } from '../features/ops/useOpsMap'
import {
  SEOUL_BOUNDS,
  STOCK_GOOD_MIN,
  STOCK_LOW_MAX,
  stockLevel,
  useOpsData,
  type OpsDatasetState,
} from '../features/ops/useOpsData'
import type { BikeStockOverview, CongestionHeatmap } from '../features/ops/types'

// 운영자 뷰 데스크톱 화면. 개발 전용 진입점(#ops)에서만 렌더링된다.
// 좌측은 지도 bbox 기준 대여소 재고 레이어, 우측은 호선×시간대 혼잡도 히트맵이다.

function SampleBadge({ source }: { source?: string }) {
  return source === 'mock' ? <span className="ops-badge">샘플</span> : null
}

function DatasetBody<T>({
  state,
  children,
}: {
  state: OpsDatasetState<T>
  children: (data: T) => ReactNode
}) {
  if (state.data === undefined) {
    if (state.status === 'idle' || state.status === 'loading') {
      return <p role="status">불러오는 중…</p>
    }
    if (state.status === 'error') {
      return (
        <p role="alert" className="ops-error">
          오류: {state.error}
        </p>
      )
    }
    return state.status === 'empty' ? <p>데이터 없음</p> : null
  }
  // 이전 데이터가 있으면 재조회 중·재조회 실패에도 내용을 유지하고 알림만 덧붙인다.
  return (
    <>
      <p className="ops-refreshing" aria-live="polite">
        {state.refreshing ? '갱신 중…' : ''}
      </p>
      {state.error && (
        <p role="alert" className="ops-error">
          갱신 실패: {state.error} (이전 데이터를 표시 중)
        </p>
      )}
      {state.status === 'empty' ? <p>데이터 없음</p> : children(state.data)}
    </>
  )
}

const STOCK_LEGEND = [
  { level: 'low', label: `부족 ≤${STOCK_LOW_MAX}` },
  { level: 'mid', label: `보통 ${STOCK_LOW_MAX + 1}~${STOCK_GOOD_MIN - 1}` },
  { level: 'good', label: `여유 ≥${STOCK_GOOD_MIN}` },
  { level: 'unknown', label: '알 수 없음' },
] as const

function StockLegend() {
  return (
    <ul className="ops-stock-legend" aria-label="재고 마커 범례">
      {STOCK_LEGEND.map((item) => (
        <li key={item.level}>
          <i className={`ops-stock-${item.level}`} />
          {item.label}
        </li>
      ))}
    </ul>
  )
}

function StockSummary({ data }: { data: BikeStockOverview }) {
  const levels = { low: 0, mid: 0, good: 0, unknown: 0 }
  let zero = 0
  let nullStock = 0
  for (const item of data.items) {
    levels[stockLevel(item.availableBikes, item.predictedBikes)] += 1
    if (item.availableBikes === 0) zero += 1
    if (item.availableBikes === null) nullStock += 1
  }
  return (
    <ul className="ops-list">
      <li>대여소 {data.items.length}곳</li>
      <li>
        부족 {levels.low} · 보통 {levels.mid} · 여유 {levels.good} · 알 수 없음 {levels.unknown}
      </li>
      <li>
        재고 0대 {zero}곳 · 재고 알 수 없음 {nullStock}곳
      </li>
      <li>산출 시각 {data.generatedAt ?? '알 수 없음'}</li>
    </ul>
  )
}

function HeatmapMeta({ data }: { data: CongestionHeatmap }) {
  return (
    <p className="ops-meta">
      {data.date} · 출처 {data.source} · 산출 시각 {data.generatedAt ?? '알 수 없음'}
    </p>
  )
}

export default function OpsPage() {
  const links = useMemo(() => buildGrafanaLinks(), [])
  const mapRef = useRef<HTMLDivElement>(null)
  const [bounds, setBounds] = useState<OpsBounds>(SEOUL_BOUNDS)
  const { handle, mapError } = useOpsMap(mapRef, setBounds)
  const { stock, heatmap, refreshStock, refreshHeatmap } = useOpsData({
    repository: opsRepository,
    bounds,
  })

  // 재조회 중에도 이전 data가 유지되므로 마커를 지우지 않는다. 새 데이터가 오면 차이만 반영한다.
  // 첫 조회 중에는 items가 없어 아무것도 그리지 않는다.
  const overlays = useRef<Map<string, StockOverlay>>(new Map())
  const items = stock.data?.items
  useEffect(() => {
    if (!handle || !items) return
    overlays.current = syncStockOverlays(handle.maps, handle.map, items, overlays.current)
  }, [handle, items])
  useEffect(() => {
    const current = overlays
    return () => {
      destroyStockOverlays(current.current)
      current.current = new Map()
    }
  }, [handle])
  return (
    <main className="ops-page">
      <p className="ops-narrow-notice">데스크톱에서 확인해 주세요</p>
      <div className="ops-body">
        <header className="ops-header">
          <h1>운영자 뷰 (개발 전용)</h1>
          <nav aria-label="Grafana 보드" className="ops-links">
            {links.map((link) =>
              link.href ? (
                <a key={link.uid} href={link.href} target="_blank" rel="noreferrer">
                  {link.title}
                </a>
              ) : (
                <span key={link.uid} aria-disabled="true" className="ops-link-disabled">
                  {link.title} · Grafana 주소 미설정
                </span>
              ),
            )}
          </nav>
        </header>
        <div className="ops-grid">
          <section className="ops-section" aria-labelledby="ops-bike-title">
            <h2 id="ops-bike-title">
              대여소 재고·예측
              <SampleBadge source={stock.source} />
            </h2>
            {mapError && (
              <p role="alert" className="ops-error">
                {mapError}
              </p>
            )}
            <StockLegend />
            <div className="ops-map-wrap">
              <div ref={mapRef} className="ops-map" aria-label="대여소 재고 지도" />
            </div>
            {stock.data?.truncated && (
              <p className="ops-notice">지도 범위 안 대여소가 많아 일부만 표시됩니다</p>
            )}
            <DatasetBody state={stock}>{(data) => <StockSummary data={data} />}</DatasetBody>
            {stock.error !== undefined && (
              <button type="button" onClick={refreshStock}>
                다시 시도
              </button>
            )}
          </section>
          <section className="ops-section" aria-labelledby="ops-heatmap-title">
            <h2 id="ops-heatmap-title">
              호선×시간대 혼잡도
              <SampleBadge source={heatmap.source} />
            </h2>
            <DatasetBody state={heatmap}>
              {(data) => (
                <>
                  <HeatmapMeta data={data} />
                  <CongestionHeatmapView data={data} />
                </>
              )}
            </DatasetBody>
            {heatmap.error !== undefined && (
              <button type="button" onClick={refreshHeatmap}>
                다시 시도
              </button>
            )}
          </section>
        </div>
      </div>
    </main>
  )
}
