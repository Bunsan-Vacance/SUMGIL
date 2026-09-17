import { expect, it } from 'vitest'
import { mockPlaceRepository, mockRouteRepository } from './repositories'
import { places } from './fixtures'

it('취소된 검색은 결과를 돌려주지 않는다', async () => {
  const request = new AbortController()
  const result = mockRouteRepository.search(
    { origin: places[0], destination: places[1] },
    request.signal,
  )
  request.abort()
  await expect(result).rejects.toMatchObject({ name: 'AbortError' })
})
it('장소 검색은 공백을 정리하고 등록된 후보만 반환한다', async () => {
  const result = await mockPlaceRepository.search(' 도곡역 ', new AbortController().signal)
  expect(result).toHaveLength(3)
  expect(result.every((place) => place.name.includes('도곡역'))).toBe(true)
})
