export type HomeLayer = 'crowd' | 'bike'

export const homeLayerLabels: Record<HomeLayer, string> = { crowd: '혼잡도', bike: '따릉이' }

// 346이 'crowd'를 추가한다. 비어 있으면 레이어 토글을 그리지 않는다.
export const availableLayers: HomeLayer[] = ['bike']
