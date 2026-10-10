import { departureAtToIso, serializeRouteQuery } from '../../app/routeQuery'
import type { RouteQuery } from '../../app/routeQuery'
import type { Place } from '../route/types'

/** 공유 링크를 만든다. base는 origin+pathname이며, 지금보다 미래인 출발 시각만 싣는다. */
export function buildShareUrl(base: string, query: RouteQuery, now = new Date()): string {
  const keepAt =
    query.departureAt !== undefined && new Date(departureAtToIso(query.departureAt)) > now
  const { departureAt: _departureAt, ...rest } = query
  return `${base}#results?${serializeRouteQuery(keepAt ? query : rest)}`
}

export function shareText(origin: Place, destination: Place): string {
  return `${origin.name} → ${destination.name} 경로`
}

export type ShareOutcome = 'shared' | 'copied' | 'cancelled' | 'failed'

export interface SharePayload {
  title: string
  text: string
  url: string
}

/** navigator 중 공유에 쓰는 부분. 일부 브라우저에는 없을 수 있어 모두 선택 항목이다. */
interface ShareEnv extends Partial<Pick<Navigator, 'share' | 'canShare'>> {
  clipboard?: Pick<Clipboard, 'writeText'>
}

/**
 * 시스템 공유 시트를 우선 쓰고, 안 되면 클립보드로 복사한다.
 * 사용자 제스처를 잃지 않도록 share 호출 전에 await하지 않는다.
 */
export async function shareLink(
  payload: SharePayload,
  env: ShareEnv = navigator,
): Promise<ShareOutcome> {
  if (
    typeof env.share === 'function' &&
    (typeof env.canShare !== 'function' || env.canShare(payload))
  ) {
    try {
      await env.share(payload)
      return 'shared'
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return 'cancelled'
    }
  }
  try {
    if (!env.clipboard) return 'failed'
    await env.clipboard.writeText(payload.url)
    return 'copied'
  } catch {
    return 'failed'
  }
}
