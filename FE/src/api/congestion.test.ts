import { afterEach, describe, expect, it, vi } from 'vitest'
import { RepositoryError } from './errors'
import { createBackendCongestionRepository } from './congestion'

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
