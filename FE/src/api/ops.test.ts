import { afterEach, describe, expect, it, vi } from 'vitest'
import { RepositoryError } from './errors'
import { createBackendOpsRepository } from './ops'

const BASE = 'https://api.example.test'
const bounds = { sw: { lat: 37.4, lng: 126.8 }, ne: { lat: 37.7, lng: 127.2 } }

const item = {
  rentalId: 'ST-1',
  name: '테스트 대여소',
  lat: 37.5,
  lng: 127.0,
  rackCount: 12,
  availableBikes: 0,
  stockStatus: 'AVAILABLE',
  stockUpdatedAt: '2026-10-03T09:00:00+09:00',
  predictedBikes: null,
  availabilityProbability: null,
  predictionStatus: 'UNAVAILABLE',
  predictionSource: null,
  predictedAt: null,
}
const overview = {
  arrivalTime: '2026-10-03T09:30:00+09:00',
  count: 2,
  truncated: false,
  generatedAt: '2026-10-03T09:00:05+09:00',
  items: [item, { ...item, rentalId: 'ST-2', availableBikes: null, stockStatus: 'UNAVAILABLE' }],
}
const heatmap = {
  date: '2026-10-03',
  source: 'congestion_pred',
  generatedAt: '2026-10-03T00:10:00+09:00',
  predictorVersions: ['v1'],
  slotFrom: 10,
  slotTo: 47,
  lines: [
    {
      lineId: '2',
      lineName: '2호선',
      cells: [
        { timeSlot: 10, level: 80, nLinks: 40, nFallback: 2, maxLevel: 130 },
        { timeSlot: 11, level: null, nLinks: null, nFallback: null, maxLevel: null },
      ],
    },
  ],
}

const ok = (data: unknown) =>
  new Response(JSON.stringify({ success: true, data }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
const stubFetch = (response: Response | (() => Promise<Response>)) => {
  const fetchMock = vi
    .fn()
    .mockImplementation(typeof response === 'function' ? response : () => Promise.resolve(response))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => vi.unstubAllGlobals())

describe('운영자 뷰 실제 저장소', () => {
  it('재고 개요를 조회해 source=api로 돌려주고 0과 null을 구분한다', async () => {
    const fetchMock = stubFetch(ok(overview))
    const result = await createBackendOpsRepository(BASE).bikeStockOverview(
      { ...bounds, arrivalTime: '2026-10-03T09:30:00+09:00', limit: 200 },
      new AbortController().signal,
    )
    const url = new URL(fetchMock.mock.calls[0][0] as string)
    expect(url.pathname).toBe('/api/ops/bike-stations/stock-overview')
    expect(url.searchParams.get('swLat')).toBe('37.4')
    expect(url.searchParams.get('neLng')).toBe('127.2')
    expect(url.searchParams.get('limit')).toBe('200')
    expect(url.searchParams.get('arrivalTime')).toBe('2026-10-03T09:30:00+09:00')
    expect(result.source).toBe('api')
    expect(result.data.items).toHaveLength(2)
    expect(result.data.items[0].availableBikes).toBe(0)
    expect(result.data.items[1].availableBikes).toBeNull()
    expect(result.data.items[0].predictedBikes).toBeNull()
  })

  it('히트맵을 조회하고 null 셀을 보존한다', async () => {
    const fetchMock = stubFetch(ok(heatmap))
    const result = await createBackendOpsRepository(BASE).congestionHeatmap(
      { date: '2026-10-03' },
      new AbortController().signal,
    )
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/api/ops/congestion/heatmap?date=2026-10-03`)
    expect(result.source).toBe('api')
    expect(result.data.lines[0].cells[0].level).toBe(80)
    expect(result.data.lines[0].cells[1]).toMatchObject({ level: null, nLinks: null })
  })

  it('date 생략 시 쿼리 없이 호출하고, 성공한 빈 결과는 오류가 아니다', async () => {
    const fetchMock = stubFetch(ok({ ...heatmap, lines: [] }))
    const result = await createBackendOpsRepository(BASE).congestionHeatmap(
      {},
      new AbortController().signal,
    )
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/api/ops/congestion/heatmap`)
    expect(result.data.lines).toEqual([])
  })

  it('success:false는 RepositoryError다', async () => {
    stubFetch(
      new Response(JSON.stringify({ success: false, error: { code: 'X' } }), { status: 200 }),
    )
    await expect(
      createBackendOpsRepository(BASE).congestionHeatmap({}, new AbortController().signal),
    ).rejects.toBeInstanceOf(RepositoryError)
  })

  it('HTTP 오류는 RepositoryError로 던지고 상태 코드를 보존한다', async () => {
    stubFetch(new Response(JSON.stringify({ success: false }), { status: 500 }))
    await expect(
      createBackendOpsRepository(BASE).bikeStockOverview(bounds, new AbortController().signal),
    ).rejects.toMatchObject({ name: 'RepositoryError', status: 500 })
  })

  it('네트워크 실패는 network 오류다', async () => {
    stubFetch(() => Promise.reject(new TypeError('failed')))
    await expect(
      createBackendOpsRepository(BASE).bikeStockOverview(bounds, new AbortController().signal),
    ).rejects.toMatchObject({ code: 'network' })
  })

  it('잘못된 행(좌표·상태·숫자)은 버리고 나머지는 유지한다', async () => {
    stubFetch(
      ok({
        ...overview,
        items: [
          item,
          { ...item, rentalId: 'BAD-LAT', lat: 999 },
          { ...item, rentalId: 'BAD-NAN', availableBikes: 'many' },
          { ...item, rentalId: 'BAD-STATUS', stockStatus: 'WHATEVER' },
          { ...item, rentalId: '' },
          null,
        ],
      }),
    )
    const result = await createBackendOpsRepository(BASE).bikeStockOverview(
      bounds,
      new AbortController().signal,
    )
    expect(result.data.items.map((row) => row.rentalId)).toEqual(['ST-1'])
  })

  it('잘못된 셀·호선은 버린다', async () => {
    stubFetch(
      ok({
        ...heatmap,
        lines: [
          {
            lineId: '1',
            lineName: '1호선',
            cells: [
              { timeSlot: 10, level: 70, nLinks: 3, nFallback: 0, maxLevel: 90 },
              { timeSlot: 99, level: 70, nLinks: 3, nFallback: 0, maxLevel: 90 },
              { timeSlot: 12, level: -5, nLinks: 3, nFallback: 0, maxLevel: 90 },
              { timeSlot: 13, level: '70', nLinks: 3, nFallback: 0, maxLevel: 90 },
            ],
          },
          { lineName: 'id 없음', cells: [] },
        ],
      }),
    )
    const result = await createBackendOpsRepository(BASE).congestionHeatmap(
      {},
      new AbortController().signal,
    )
    expect(result.data.lines).toHaveLength(1)
    expect(result.data.lines[0].cells.map((cell) => cell.timeSlot)).toEqual([10])
  })

  it('바깥 구조가 틀리면 invalid-response다', async () => {
    stubFetch(ok({ items: 'nope' }))
    await expect(
      createBackendOpsRepository(BASE).bikeStockOverview(bounds, new AbortController().signal),
    ).rejects.toMatchObject({ code: 'invalid-response' })
  })

  it('비정상 bbox·date는 요청 전에 거부한다', async () => {
    const fetchMock = stubFetch(ok(overview))
    const repository = createBackendOpsRepository(BASE)
    await expect(
      repository.bikeStockOverview({ sw: bounds.ne, ne: bounds.sw }, new AbortController().signal),
    ).rejects.toMatchObject({ code: 'bad-request' })
    await expect(
      repository.congestionHeatmap({ date: '2026/10/03' }, new AbortController().signal),
    ).rejects.toMatchObject({ code: 'bad-request' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('중단된 요청은 AbortError다', async () => {
    const controller = new AbortController()
    stubFetch(
      () =>
        new Promise((_resolve, reject) => {
          controller.signal.addEventListener('abort', () =>
            reject(new DOMException('Aborted', 'AbortError')),
          )
        }),
    )
    const pending = createBackendOpsRepository(BASE).bikeStockOverview(bounds, controller.signal)
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })
})
