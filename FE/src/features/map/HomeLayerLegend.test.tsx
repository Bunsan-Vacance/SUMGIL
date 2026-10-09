// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import HomeLayerLegend from './HomeLayerLegend'

afterEach(cleanup)

describe('홈 레이어 범례', () => {
  it('따릉이 레이어면 문구와 점 두 개를 보여 준다', () => {
    const { container } = render(<HomeLayerLegend layer="bike" />)
    expect(screen.getByText('따릉이 대여 가능 대수')).toBeTruthy()
    expect(container.querySelectorAll('.legend-dot')).toHaveLength(2)
  })

  it('다른 값이면 렌더링하지 않는다', () => {
    const { container } = render(<HomeLayerLegend layer={null} />)
    expect(container.firstChild).toBeNull()
  })
})
