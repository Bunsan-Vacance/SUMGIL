import { describe, expect, it } from 'vitest'
import { isOpsViewEnabled } from './opsAccess'

describe('운영자 뷰 접근 플래그', () => {
  it('개발 빌드에서는 열린다', () => {
    expect(isOpsViewEnabled({ DEV: true })).toBe(true)
  })
  it('운영 빌드는 VITE_OPS_VIEW=true일 때만 열린다', () => {
    expect(isOpsViewEnabled({ DEV: false, VITE_OPS_VIEW: 'true' })).toBe(true)
    expect(isOpsViewEnabled({ DEV: false, VITE_OPS_VIEW: ' TRUE ' })).toBe(true)
    expect(isOpsViewEnabled({ DEV: false })).toBe(false)
    expect(isOpsViewEnabled({ DEV: false, VITE_OPS_VIEW: 'false' })).toBe(false)
    expect(isOpsViewEnabled({ DEV: false, VITE_OPS_VIEW: '1' })).toBe(false)
  })
})
