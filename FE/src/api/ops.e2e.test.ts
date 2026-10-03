import { describe, expect, it } from 'vitest'
import { createBackendOpsRepository } from './ops'

// 운영자 뷰 E2E — 실제 BE(`/api/ops/**`)에 붙여 데이터 계층(검증·변환)이 실응답과 맞는지 본다.
// 기본 실행(`npm test`)에서는 건너뛴다. 로컬 BE·PG·Redis를 띄우고 표본을 넣은 뒤:
//   VITE_OPS_E2E_BASE_URL=http://localhost:8080 npx vitest run src/api/ops.e2e.test.ts
// 표본은 BE/docs/ops-api.md 계약 기준이며 날짜는 BE가 Asia/Seoul 오늘로 처리한다.

const baseUrl = import.meta.env.VITE_OPS_E2E_BASE_URL?.replace(/\/+$/, '')
const run = baseUrl ? describe : describe.skip

run('운영자 뷰 BE 연동(E2E)', () => {
  const repository = createBackendOpsRepository(baseUrl ?? '')
  const signal = new AbortController().signal

  it('대여소 재고·예측 일괄 조회가 계약대로 변환된다', async () => {
    const result = await repository.bikeStockOverview(
      { sw: { lat: 37.42, lng: 126.76 }, ne: { lat: 37.72, lng: 127.19 }, limit: 50 },
      signal,
    )
    expect(result.source).toBe('api')
    const { data } = result
    expect(data.count).toBe(data.items.length)
    expect(typeof data.truncated).toBe('boolean')
    expect(data.generatedAt).not.toBeNull()
    expect(data.items.length).toBeGreaterThan(0)
    for (const item of data.items) {
      expect(['AVAILABLE', 'STALE', 'UNAVAILABLE']).toContain(item.stockStatus)
      expect(['AVAILABLE', 'UNAVAILABLE']).toContain(item.predictionStatus)
      // 일괄 조회는 표만 읽으므로 출처는 항상 TABLE이다.
      expect(item.predictionSource).toBe('TABLE')
      if (item.predictionStatus === 'UNAVAILABLE') {
        expect(item.predictedBikes).toBeNull()
        expect(item.availabilityProbability).toBeNull()
      }
      if (item.stockStatus === 'UNAVAILABLE') expect(item.availableBikes).toBeNull()
    }
    // 표본에 재고 0대·재고 null·예측 있음이 하나씩은 있어야 null/0 구분이 실제로 검증된다.
    expect(data.items.some((i) => i.availableBikes === 0)).toBe(true)
    expect(data.items.some((i) => i.availableBikes === null)).toBe(true)
    expect(data.items.some((i) => i.predictionStatus === 'AVAILABLE')).toBe(true)
  })

  it('히트맵이 슬롯 10~47 고정 축으로 오고 빈 셀은 null이다', async () => {
    const { source, data } = await repository.congestionHeatmap({}, signal)
    expect(source).toBe('api')
    expect(data.source).toBe('congestion_pred')
    expect(data.slotFrom).toBe(10)
    expect(data.slotTo).toBe(47)
    expect(data.lines.length).toBeGreaterThan(0)
    for (const line of data.lines) {
      expect(line.cells).toHaveLength(38)
      expect(line.cells[0].timeSlot).toBe(10)
      expect(line.cells[37].timeSlot).toBe(47)
    }
    const filled = data.lines.flatMap((l) => l.cells).filter((c) => c.level !== null)
    const empty = data.lines.flatMap((l) => l.cells).filter((c) => c.level === null)
    expect(filled.length).toBeGreaterThan(0)
    expect(empty.length).toBeGreaterThan(0)
    for (const cell of empty) {
      expect(cell.nLinks).toBe(0)
      expect(cell.maxLevel).toBeNull()
    }
  })

  it('데이터 없는 날짜는 오류가 아니라 빈 결과다', async () => {
    const { data } = await repository.congestionHeatmap({ date: '2020-01-01' }, signal)
    expect(data.lines).toEqual([])
    expect(data.generatedAt).toBeNull()
    expect(data.predictorVersions).toEqual([])
  })

  it('잘못된 bbox는 요청 전에 거절된다', async () => {
    await expect(
      repository.bikeStockOverview(
        { sw: { lat: 37.72, lng: 126.76 }, ne: { lat: 37.42, lng: 127.19 } },
        signal,
      ),
    ).rejects.toMatchObject({ code: 'bad-request' })
  })
})
