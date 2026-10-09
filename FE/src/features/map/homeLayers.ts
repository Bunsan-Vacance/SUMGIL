import { isBackendConfigured } from '../../api/repositories'

export type HomeLayer = 'crowd' | 'bike'

export const homeLayerLabels: Record<HomeLayer, string> = { crowd: '혼잡도', bike: '따릉이' }

// 혼잡도 레이어는 백엔드의 주변 역 조회·혼잡도 일괄 조회가 있어야 그릴 수 있어 백엔드가 없으면 숨긴다.
// 비어 있으면 레이어 토글을 그리지 않는다. 기본 레이어는 첫 번째 값이다.
export const availableLayers: HomeLayer[] = isBackendConfigured ? ['crowd', 'bike'] : ['bike']
