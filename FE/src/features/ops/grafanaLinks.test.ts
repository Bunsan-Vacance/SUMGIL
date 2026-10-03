import { describe, expect, it } from 'vitest'
import { buildGrafanaLinks, normalizeGrafanaBaseUrl } from './grafanaLinks'

describe('Grafana 보드 링크', () => {
  it('베이스 URL이 없으면 href가 null이다', () => {
    const links = buildGrafanaLinks(undefined)
    expect(links).toHaveLength(4)
    expect(links.every((link) => link.href === null)).toBe(true)
    expect(buildGrafanaLinks('  ').every((link) => link.href === null)).toBe(true)
  })
  it('끝 슬래시를 제거하고 /d/uid로 만든다', () => {
    const links = buildGrafanaLinks('https://example.com/grafana//')
    expect(links.map((link) => link.href)).toEqual([
      'https://example.com/grafana/d/sumgil-model-quality',
      'https://example.com/grafana/d/sumgil-pipeline-health',
      'https://example.com/grafana/d/sumgil-spark-jobs',
      'https://example.com/grafana/d/sumgil-data-quality',
    ])
    expect(links.map((link) => link.title)).toEqual([
      '모델 품질',
      '파이프라인 건강',
      'Spark 잡',
      '데이터 품질',
    ])
  })
  it('빈 문자열은 미설정으로 본다', () => {
    expect(normalizeGrafanaBaseUrl('')).toBeUndefined()
    expect(normalizeGrafanaBaseUrl(' http://g/ ')).toBe('http://g')
  })
})
