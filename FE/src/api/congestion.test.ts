import { afterEach, describe, expect, it, vi } from 'vitest'
import { RepositoryError } from './errors'
import {
  createBackendCongestionBatchRepository,
  createBackendCongestionRepository,
} from './congestion'

afterEach(() => vi.unstubAllGlobals())

const signal = new AbortController().signal

describe('혼잡도 저장소', () => {
  it('역 ID와 서울 기준 출발 시각으로 혼잡도를 조회한다', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          data: {
            targetType: 'STATION',
            targetId: '0221',
            dowType: 0,
            timeSlot: 18,
            level: 144.6,
            source: 'stat',
            updatedAt: '2026-09-15T00:00:00+09:00',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await createBackendCongestionRepository('http://be.test').get(
      'STATION',
      '0221',
      '2026-09-15T00:00:00.000Z',
      signal,
    )

    expect(result).toMatchObject({ targetId: '0221', level: 144.6, source: 'stat' })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://be.test/api/congestion?targetType=STATION&targetId=0221&departureTime=2026-09-15T09%3A00%3A00',
      expect.objectContaining({ signal }),
    )
  })

  it('데이터가 없는 성공 응답은 준비중 상태로 돌려준다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ success: true }), { status: 200 })),
    )

    await expect(
      createBackendCongestionRepository('http://be.test').get('STATION', '9999', undefined, signal),
    ).resolves.toBeUndefined()
  })

  it('혼잡도 값이 잘못되면 응답 오류로 처리한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            success: true,
            data: { targetType: 'STATION', targetId: '0221', level: -1 },
          }),
          { status: 200 },
        ),
      ),
    )

    await expect(
      createBackendCongestionRepository('http://be.test').get('STATION', '0221', undefined, signal),
    ).rejects.toBeInstanceOf(RepositoryError)
  })
})

describe('혼잡도 일괄 저장소', () => {
  const slot = (departureTime: string, level: number | null) => ({
    departureTime,
    dowType: 0,
    timeSlot: 18,
    level,
    source: level === null ? null : 'stat',
    updatedAt: level === null ? null : '2026-10-01T03:00:00Z',
  })
  const body = (overrides: Record<string, unknown> = {}) => ({
    targetType: 'STATION',
    departureTimes: ['2026-10-09T09:00:00', '2026-10-09T09:30:00'],
    targets: [
      {
        targetId: '222',
        slots: [slot('2026-10-09T09:00:00', 72.5), slot('2026-10-09T09:30:00', null)],
      },
      {
        targetId: 'S410',
        slots: [slot('2026-10-09T09:00:00', 0), slot('2026-10-09T09:30:00', 10)],
      },
    ],
    ...overrides,
  })
  const stub = (data: unknown) => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ success: true, data }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }
  const repository = createBackendCongestionBatchRepository('http://be.test')
  const callUrl = (fetchMock: ReturnType<typeof stub>) =>
    new URL(String((fetchMock.mock.calls[0] as unknown[])[0]))

  it('대상 2개 × 시각 2개를 매핑하고 null을 보존한다', async () => {
    stub(body())
    const result = await repository.batch(
      {
        targetType: 'STATION',
        targetIds: ['222', 'S410'],
        departureTimes: ['2026-10-09T09:00:00', '2026-10-09T09:30:00'],
      },
      signal,
    )
    expect(result.targets).toHaveLength(2)
    expect(result.targets[0].slots[1]).toMatchObject({ level: null, source: null, updatedAt: null })
    expect(result.targets[1].slots[0].level).toBe(0)
  })

  it('대상과 시각을 정리해 쉼표로 이어 보낸다', async () => {
    const fetchMock = stub(
      body({
        departureTimes: ['2026-10-09T09:00:00'],
        targets: [
          { targetId: '222', slots: [slot('2026-10-09T09:00:00', 1)] },
          { targetId: 'S410', slots: [slot('2026-10-09T09:00:00', 2)] },
        ],
      }),
    )
    await repository.batch(
      {
        targetType: 'STATION',
        targetIds: [' 222 ', '', '222', 'S410'],
        departureTimes: ['2026-10-09T00:00:00.000Z', '2026-10-09T09:00:00'],
      },
      signal,
    )
    const url = callUrl(fetchMock)
    expect(url.pathname).toBe('/api/congestion/batch')
    expect(url.searchParams.get('targetType')).toBe('STATION')
    expect(url.searchParams.get('targetIds')).toBe('222,S410')
    expect(url.searchParams.get('departureTimes')).toBe('2026-10-09T09:00:00')
  })

  it('departureTimes를 생략하면 쿼리에 넣지 않는다', async () => {
    const fetchMock = stub(
      body({
        departureTimes: ['2026-10-09T09:00:00'],
        targets: [{ targetId: '222', slots: [slot('2026-10-09T09:00:00', 1)] }],
      }),
    )
    await repository.batch({ targetType: 'STATION', targetIds: ['222'] }, signal)
    expect(callUrl(fetchMock).searchParams.has('departureTimes')).toBe(false)
  })

  it('대상이 비면 bad-request다', async () => {
    const fetchMock = stub(body())
    await expect(
      repository.batch({ targetType: 'STATION', targetIds: [' ', ''] }, signal),
    ).rejects.toMatchObject({ code: 'bad-request' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('상한 3종을 넘으면 서버에 보내지 않고 bad-request다', async () => {
    const fetchMock = stub(body())
    const ids = (count: number) => Array.from({ length: count }, (_, index) => 'T' + index)
    const times = (count: number) =>
      Array.from(
        { length: count },
        (_, index) => '2026-10-09T' + String(index).padStart(2, '0') + ':00:00',
      )
    await expect(
      repository.batch({ targetType: 'STATION', targetIds: ids(51) }, signal),
    ).rejects.toMatchObject({ code: 'bad-request' })
    await expect(
      repository.batch(
        { targetType: 'STATION', targetIds: ids(1), departureTimes: times(13) },
        signal,
      ),
    ).rejects.toMatchObject({ code: 'bad-request' })
    await expect(
      repository.batch(
        { targetType: 'STATION', targetIds: ids(20), departureTimes: times(11) },
        signal,
      ),
    ).rejects.toMatchObject({ code: 'bad-request' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each([
    [
      '대상 순서가 요청과 다름',
      (data: ReturnType<typeof body>) => ({ ...data, targets: [...data.targets].reverse() }),
    ],
    [
      'slots 길이가 시각 수와 다름',
      (data: ReturnType<typeof body>) => ({
        ...data,
        targets: [{ ...data.targets[0], slots: [data.targets[0].slots[0]] }, data.targets[1]],
      }),
    ],
    [
      'level이 음수',
      (data: ReturnType<typeof body>) => ({
        ...data,
        targets: [
          {
            ...data.targets[0],
            slots: [slot('2026-10-09T09:00:00', -1), data.targets[0].slots[1]],
          },
          data.targets[1],
        ],
      }),
    ],
  ])('%s이면 invalid-response다', async (_name, mutate) => {
    stub(mutate(body()))
    await expect(
      repository.batch(
        {
          targetType: 'STATION',
          targetIds: ['222', 'S410'],
          departureTimes: ['2026-10-09T09:00:00', '2026-10-09T09:30:00'],
        },
        signal,
      ),
    ).rejects.toMatchObject({ code: 'invalid-response' })
  })
})
