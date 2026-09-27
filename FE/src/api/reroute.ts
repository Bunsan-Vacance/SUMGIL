import { mapBackendRoute } from './routeMapper'
import { RepositoryError } from './errors'
import { mockRerouteRepository } from './mock/reroute'
import type { GuidanceState } from '../features/guidance/guidanceReducer'
import type { Route } from '../features/route/types'

export type RerouteStatus = 'no_trigger' | 'no_alternative' | 'unavailable' | 'proposal'

export interface Boundary {
  legIndex: number
  nodeId: string
  lat: number
  lng: number
}

export interface TargetOut {
  rentalId: string
  name?: string | null
  currentBikes?: number | null
  predictedStock?: number | null
  pEmpty?: number | null
  horizonMin?: number | null
}

export interface AlternativeOut {
  rentalId: string
  name?: string | null
  lat: number
  lng: number
  distanceMeters: number
  currentBikes?: number | null
  predictedStock?: number | null
  pEmpty?: number | null
}

/** BE `RouteLegResponse`와 같은 필드 이름의 도보 구간(추정 경로) — mapBackendRoute가 그대로 소비한다
 * (TO_FE-bike-reroute-04.md 2.2절). 좌표 순서는 GeoJSON `[lng, lat]`. */
export interface RerouteWalkLeg {
  mode: 'WALK'
  fromNodeId?: string | null
  fromNodeName?: string | null
  fromLat: number
  fromLng: number
  toNodeId?: string | null
  toNodeName?: string | null
  toLat: number
  toLng: number
  routeId?: string | null
  routeName?: string | null
  minutes: number
  distanceMeters?: number | null
  geometry?: unknown
  geometryStatus: 'available' | 'unavailable' | 'estimated'
  estimated?: boolean
}

export interface RerouteCheckRequest {
  sessionId: string
  step: number
  rentalId: string
  etaToRentalMinutes: number
  destStationId: string
  boundary: Boundary
  debugForceTrigger?: boolean
}

export interface RerouteCheckResponse {
  status: RerouteStatus
  recommendationId?: string | null
  validUntil?: string | null
  recommendedBy?: string | null
  reason?: string | null
  target?: TargetOut | null
  alternative?: AlternativeOut | null
  boundary?: Boundary | null
  walkLeg?: RerouteWalkLeg | null
  /** BE `replan` 원소의 안쪽 `route`(RouteSearchResponse 모양) 그대로 — proposalToRoute가 소비한다. */
  route?: unknown | null
}

export interface SessionBudgetOut {
  maxCalls: number
  maxTotalTokens: number
}

/** `GET /time/meta` 응답 — FE 디버그·시연용(이번 범위에서는 타입만 둔다). */
export interface TimeMetaResponse {
  triggerPEmpty: number
  triggerMinStock: number
  triggerMaxEtaMin: number
  triggerCooldownSec: number
  debugForceTriggerEnabled: boolean
  debugEmptyRentalIds: string[]
  nearbyRadiusM: number
  nearbyLimit: number
  scoreEmptyPenaltyMin: number
  strategyKind: 'AGENT' | 'ALGORITHM'
  llmModel?: string | null
  llmConfigured: boolean
  stationIndexSize?: number | null
  snapshotAgeSec?: number | null
  sessionBudget: SessionBudgetOut
}

export interface RerouteRepository {
  check(request: RerouteCheckRequest, signal: AbortSignal): Promise<RerouteCheckResponse>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function text(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

const RESPONSE_STATUSES: RerouteStatus[] = [
  'no_trigger',
  'no_alternative',
  'unavailable',
  'proposal',
]

function mapBoundary(value: unknown): Boundary {
  if (
    !isRecord(value) ||
    !Number.isInteger(value.legIndex) ||
    !text(value.nodeId) ||
    typeof value.lat !== 'number' ||
    !Number.isFinite(value.lat) ||
    typeof value.lng !== 'number' ||
    !Number.isFinite(value.lng)
  ) {
    throw new RepositoryError('invalid-response', '재안내 경계 응답이 올바르지 않아요.')
  }
  return {
    legIndex: value.legIndex as number,
    nodeId: value.nodeId as string,
    lat: value.lat as number,
    lng: value.lng as number,
  }
}

function mapRerouteResponse(value: unknown): RerouteCheckResponse {
  if (!isRecord(value) || !RESPONSE_STATUSES.includes(value.status as RerouteStatus)) {
    throw new RepositoryError('invalid-response', '재안내 확인 응답이 올바르지 않아요.')
  }
  const status = value.status as RerouteStatus
  if (status !== 'proposal') {
    return { status, reason: text(value.reason) ?? null }
  }
  const recommendationId = text(value.recommendationId)
  const routeLegs = isRecord(value.route) ? value.route.legs : undefined
  if (
    !recommendationId ||
    !isRecord(value.walkLeg) ||
    !isRecord(value.boundary) ||
    !isRecord(value.alternative) ||
    !Array.isArray(routeLegs) ||
    routeLegs.length === 0
  ) {
    throw new RepositoryError('invalid-response', '재안내 제안 응답이 올바르지 않아요.')
  }
  return {
    status: 'proposal',
    recommendationId,
    validUntil: text(value.validUntil) ?? null,
    recommendedBy: text(value.recommendedBy) ?? null,
    reason: text(value.reason) ?? null,
    target: (value.target as TargetOut | null | undefined) ?? null,
    alternative: value.alternative as unknown as AlternativeOut,
    boundary: mapBoundary(value.boundary),
    walkLeg: value.walkLeg as unknown as RerouteWalkLeg,
    route: value.route,
  }
}

async function fetchReroute(
  url: string,
  request: RerouteCheckRequest,
  signal: AbortSignal,
): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      signal,
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  } catch (error) {
    if (signal.aborted || (error instanceof DOMException && error.name === 'AbortError')) {
      throw new DOMException('Aborted', 'AbortError')
    }
    throw new RepositoryError('network', 'AI 서버에 연결하지 못했어요.')
  }
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new RepositoryError('invalid-response', 'AI 서버 응답을 읽지 못했어요.', response.status)
  }
  if (!response.ok) {
    throw new RepositoryError('network', 'AI 서버에서 요청을 처리하지 못했어요.', response.status)
  }
  return body
}

// `requestApi`(BE `{success,data}` envelope 전용)는 재사용하지 않는다 — AI 응답은 그 모양이 아니다.
export function createBackendRerouteRepository(baseUrl: string): RerouteRepository {
  return {
    async check(request, signal) {
      try {
        const body = await fetchReroute(`${baseUrl}/time/reroute/check`, request, signal)
        return mapRerouteResponse(body)
      } catch (error) {
        if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
        throw error
      }
    },
  }
}

export const aiBaseUrl = import.meta.env.VITE_AI_BASE_URL?.trim().replace(/\/+$/, '') || null
export const isRerouteMockEnabled =
  import.meta.env.VITE_REROUTE_MOCK?.trim().toLowerCase() === 'true' || !aiBaseUrl
export const isRerouteDebugForceEnabled =
  import.meta.env.VITE_REROUTE_DEBUG_FORCE?.trim().toLowerCase() === 'true'

export const rerouteRepository: RerouteRepository = isRerouteMockEnabled
  ? mockRerouteRepository
  : createBackendRerouteRepository(aiBaseUrl!)

// ---- 요청 조립(설계 결정 표 "호출 조건") ----

interface ResolvedBoundary extends Boundary {
  rentalId: string
}

/** step 이후 첫 대여소행 WALK leg를 찾는다 — `to.rentalId`가 있거나 바로 다음 leg가 BIKE인 것.
 * 네 값(legIndex·nodeId·lat·lng) 중 하나라도 없으면 추측하지 않고 null을 반환한다. */
function findBoundary(route: Route, fromStep: number): ResolvedBoundary | null {
  for (let i = fromStep; i < route.legs.length; i += 1) {
    const leg = route.legs[i]
    if (leg.mode !== 'walk') continue
    const nextLeg = route.legs[i + 1]
    const rentalId =
      leg.to?.rentalId || (nextLeg?.mode === 'bike' ? nextLeg.from?.rentalId : undefined)
    const nodeId = leg.from?.id
    const lat = leg.from?.lat
    const lng = leg.from?.lng
    if (!rentalId || !nodeId || lat === undefined || lng === undefined) continue
    return { legIndex: i, nodeId, lat, lng, rentalId }
  }
  return null
}

/** 호출 조건을 모두 만족할 때만 요청을 만들고, 수락 시 `keepLegs`로 쓸 `legIndex`를 함께 돌려준다.
 * 하나라도 어긋나면 null — 좌표·역 정보를 추측해서 채우지 않는다. */
export function buildRerouteRequest(
  state: GuidanceState,
  sessionId: string,
  opts: { debugForce: boolean },
): { request: RerouteCheckRequest; legIndex: number } | null {
  const route = state.route
  if (!route || state.completed) return null
  const currentLeg = route.legs[state.step]
  if (!currentLeg || currentLeg.mode !== 'subway') return null
  const boundary = findBoundary(route, state.step)
  if (!boundary || state.step >= boundary.legIndex) return null
  const destStationId = state.destination?.stationId?.trim()
  if (!destStationId) return null
  // 현재 leg는 전체 시간으로 근사하고, 그 뒤 boundary까지의 leg 시간을 더해 반올림한다.
  const etaToRentalMinutes = Math.round(
    route.legs.slice(state.step, boundary.legIndex + 1).reduce((sum, leg) => sum + leg.minutes, 0),
  )
  const request: RerouteCheckRequest = {
    sessionId,
    step: state.step,
    rentalId: boundary.rentalId,
    etaToRentalMinutes,
    destStationId,
    boundary: {
      legIndex: boundary.legIndex,
      nodeId: boundary.nodeId,
      lat: boundary.lat,
      lng: boundary.lng,
    },
    ...(opts.debugForce ? { debugForceTrigger: true } : {}),
  }
  return { request, legIndex: boundary.legIndex }
}

const KNOWN_ROUTE_TYPES = new Set([
  'SHORTEST',
  'SHORTEST_WITH_BIKE',
  'ALTERNATIVE',
  'LOW_CONGESTION',
])

/** 제안 응답 → 잔여 경로 `Route`. `legs = [walkLeg, ...proposal.route.legs]`를 그대로
 * `mapBackendRoute`에 태워 좌표·구간 검증을 재사용한다. */
export function proposalToRoute(proposal: RerouteCheckResponse, departedAt: string): Route {
  if (
    proposal.status !== 'proposal' ||
    !proposal.recommendationId ||
    !proposal.walkLeg ||
    !isRecord(proposal.route) ||
    !Array.isArray(proposal.route.legs)
  ) {
    throw new RepositoryError('invalid-response', '재안내 제안 응답이 올바르지 않아요.')
  }
  // AI route.routeType은 BE 도메인의 조합형 값(예: "BIKE_SUBWAY")이라 FE Route.routeType 4종
  // enum에 없을 수 있다 — mapBackendRoute가 모르는 값이면 던지므로, 여기서만 라벨용으로 보이는
  // 이 필드를 'ALTERNATIVE'로 정규화한다(실제 라벨은 아래에서 '재안내 경로'로 다시 덮어쓴다).
  const routeType = KNOWN_ROUTE_TYPES.has(proposal.route.routeType as string)
    ? proposal.route.routeType
    : 'ALTERNATIVE'
  const mapped = mapBackendRoute(
    { ...proposal.route, routeType, legs: [proposal.walkLeg, ...proposal.route.legs] },
    0,
    departedAt,
  )
  return {
    ...mapped,
    id: `reroute:${proposal.recommendationId}`,
    label: '재안내 경로',
  }
}
