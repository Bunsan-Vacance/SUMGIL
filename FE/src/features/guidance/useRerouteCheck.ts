import { useEffect, useRef } from 'react'
import type { GuidanceState } from './guidanceReducer'
import {
  buildRerouteRequest,
  type RerouteCheckResponse,
  type RerouteRepository,
} from '../../api/reroute'

const POLL_INTERVAL_MS = 120_000

function createSessionId() {
  try {
    return crypto.randomUUID()
  } catch {
    return `session-${Date.now()}-${Math.random().toString(36).slice(2)}`
  }
}

interface UseRerouteCheckOptions {
  state: GuidanceState
  enabled: boolean
  repository: RerouteRepository | null
  debugForce?: boolean
  onProposal: (proposal: RerouteCheckResponse, legIndex: number) => void
}

/** 지하철 구간 안내 중 따릉이 대여소 고갈 가능성을 120초 주기로 확인한다(TO_FE-bike-reroute-04.md §3).
 * 조건 충족 시 즉시 1회 + 120초 간격, 조건이 깨지면 정리한다. */
export function useRerouteCheck({
  state,
  enabled,
  repository,
  debugForce = false,
  onProposal,
}: UseRerouteCheckOptions) {
  const sessionIdRef = useRef(createSessionId())
  const shownIdsRef = useRef<Set<string>>(new Set())
  const stateRef = useRef(state)
  stateRef.current = state
  const onProposalRef = useRef(onProposal)
  onProposalRef.current = onProposal

  useEffect(() => {
    // route 객체 정체성이 바뀌면(새 안내 시작·재안내 적용) 세션과 이미 보여준 추천 이력을 새로 만든다.
    sessionIdRef.current = createSessionId()
    shownIdsRef.current = new Set()
  }, [state.route])

  const eligible =
    enabled && buildRerouteRequest(state, sessionIdRef.current, { debugForce }) !== null

  useEffect(() => {
    if (!eligible || !repository) return
    let cancelled = false
    let controller: AbortController | null = null
    const runCheck = () => {
      const built = buildRerouteRequest(stateRef.current, sessionIdRef.current, { debugForce })
      if (!built) return
      controller?.abort()
      const nextController = new AbortController()
      controller = nextController
      repository
        .check(built.request, nextController.signal)
        .then((response) => {
          if (cancelled || nextController.signal.aborted) return
          if (response.status !== 'proposal' || !response.recommendationId) return
          if (shownIdsRef.current.has(response.recommendationId)) return
          if (response.validUntil && new Date(response.validUntil).getTime() < Date.now()) return
          shownIdsRef.current.add(response.recommendationId)
          onProposalRef.current(response, built.legIndex)
        })
        .catch((error: unknown) => {
          if (cancelled || nextController.signal.aborted) return
          console.debug('재안내 확인 요청이 실패했어요.', error)
        })
    }
    runCheck()
    const interval = setInterval(runCheck, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
      controller?.abort()
    }
    // eligible이 true로 바뀌는 시점에만 즉시 호출 + 주기를 새로 건다. tick마다 최신 state는
    // stateRef로 읽으므로 state 자체는 의존성에 넣지 않는다.
  }, [eligible, repository, debugForce])
}
