import { describe, expect, it, vi } from 'vitest'
import { parseRouteQuery } from '../../app/routeQuery'
import { buildShareUrl, shareLink, shareText } from './shareRoute'
import type { Place } from '../route/types'

const origin: Place = { id: 's1', name: '역삼역', address: '서울', kind: '역', stationId: 'S-1' }
const destination: Place = {
  id: 'p1',
  name: '강남 카페',
  address: '서울',
  kind: '장소',
  lat: 37.5,
  lng: 127.03,
}
const payload = {
  title: '숨길',
  text: '역삼역 → 강남 카페 경로',
  url: 'https://sumgil.test/#results',
}
const now = new Date('2026-10-09T09:00:00.000Z')

describe('buildShareUrl', () => {
  it('base 뒤에 #results 해시 쿼리를 붙인다', () => {
    const url = buildShareUrl('https://sumgil.test/app', { origin, destination }, now)
    expect(url.startsWith('https://sumgil.test/app#results?')).toBe(true)
    const [beforeHash, hash] = url.split('#')
    expect(beforeHash).not.toContain('?')
    expect(parseRouteQuery(hash.slice('results?'.length))).toEqual({ origin, destination })
  })

  it('과거 at은 생략한다', () => {
    const url = buildShareUrl(
      'https://sumgil.test/',
      { origin, destination, departureAt: '2026-10-09T17:00' },
      now,
    )
    expect(url).not.toContain('at=')
  })

  it('미래 at은 포함한다', () => {
    const url = buildShareUrl(
      'https://sumgil.test/',
      { origin, destination, departureAt: '2026-10-09T18:30' },
      now,
    )
    expect(parseRouteQuery(url.split('#')[1].slice('results?'.length))?.departureAt).toBe(
      '2026-10-09T18:30',
    )
  })
})

describe('shareText', () => {
  it('출발지 → 도착지 경로 문구를 만든다', () => {
    expect(shareText(origin, destination)).toBe('역삼역 → 강남 카페 경로')
  })
})

describe('shareLink', () => {
  const clipboard = () => ({ writeText: vi.fn().mockResolvedValue(undefined) })

  it('share가 성공하면 shared다', async () => {
    const share = vi.fn().mockResolvedValue(undefined)
    const cb = clipboard()
    expect(await shareLink(payload, { share, clipboard: cb })).toBe('shared')
    expect(share).toHaveBeenCalledWith(payload)
    expect(cb.writeText).not.toHaveBeenCalled()
  })

  it('share를 await 없이 동기적으로 호출한다', () => {
    const share = vi.fn().mockResolvedValue(undefined)
    void shareLink(payload, { share })
    expect(share).toHaveBeenCalledTimes(1)
  })

  it('AbortError는 cancelled이고 클립보드를 쓰지 않는다', async () => {
    const share = vi.fn().mockRejectedValue(new DOMException('취소', 'AbortError'))
    const cb = clipboard()
    expect(await shareLink(payload, { share, clipboard: cb })).toBe('cancelled')
    expect(cb.writeText).not.toHaveBeenCalled()
  })

  it('share가 거부되면 복사한다', async () => {
    const share = vi.fn().mockRejectedValue(new Error('실패'))
    const cb = clipboard()
    expect(await shareLink(payload, { share, clipboard: cb })).toBe('copied')
    expect(cb.writeText).toHaveBeenCalledWith(payload.url)
  })

  it('share가 없으면 복사한다', async () => {
    const cb = clipboard()
    expect(await shareLink(payload, { clipboard: cb })).toBe('copied')
  })

  it('canShare가 false면 share 없이 복사한다', async () => {
    const share = vi.fn()
    const cb = clipboard()
    const canShare = vi.fn().mockReturnValue(false)
    expect(await shareLink(payload, { share, canShare, clipboard: cb })).toBe('copied')
    expect(share).not.toHaveBeenCalled()
  })

  it('클립보드가 없으면 failed다', async () => {
    expect(await shareLink(payload, {})).toBe('failed')
  })

  it('클립보드가 거부하면 failed다', async () => {
    const cb = { writeText: vi.fn().mockRejectedValue(new Error('거부')) }
    expect(await shareLink(payload, { clipboard: cb })).toBe('failed')
  })
})
