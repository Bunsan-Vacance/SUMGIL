// 운영자 뷰에서 여는 Grafana 보드 링크. 링크만 제공하고 임베드·토큰 처리는 하지 않는다.
export const grafanaBoards = [
  { uid: 'sumgil-model-quality', title: '모델 품질' },
  { uid: 'sumgil-pipeline-health', title: '파이프라인 건강' },
  { uid: 'sumgil-spark-jobs', title: 'Spark 잡' },
  { uid: 'sumgil-data-quality', title: '데이터 품질' },
] as const

export interface GrafanaLink {
  uid: string
  title: string
  /** 베이스 URL이 없으면 null. 화면은 비활성 문구를 보인다. */
  href: string | null
}

export function normalizeGrafanaBaseUrl(value: string | undefined): string | undefined {
  const trimmed = value?.trim().replace(/\/+$/, '')
  return trimmed || undefined
}

export const grafanaBaseUrl = normalizeGrafanaBaseUrl(import.meta.env.VITE_GRAFANA_BASE_URL)

export function buildGrafanaLinks(baseUrl: string | undefined = grafanaBaseUrl): GrafanaLink[] {
  const base = normalizeGrafanaBaseUrl(baseUrl)
  return grafanaBoards.map(({ uid, title }) => ({
    uid,
    title,
    href: base ? `${base}/d/${uid}` : null,
  }))
}
