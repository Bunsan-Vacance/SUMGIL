import { describe, expect, it } from 'vitest'
import { parseScreen, screenTitles } from './useNavigation'

describe('해시 화면 식별', () => {
  it('운영자 뷰 화면 제목을 가진다', () => {
    expect(screenTitles.ops).toBe('운영자 뷰')
  })
  it('#ops는 활성일 때만 ops, 아니면 홈이다', () => {
    expect(parseScreen('#ops', true)).toBe('ops')
    expect(parseScreen('#ops', false)).toBe('home')
  })
  it('기존 화면과 알 수 없는 해시는 그대로 처리한다', () => {
    expect(parseScreen('#results', false)).toBe('results')
    expect(parseScreen('#unknown', true)).toBe('home')
    expect(parseScreen('', true)).toBe('home')
  })
})
