import { useEffect, useRef } from 'react'
import type { GuidanceState } from './guidanceReducer'
import {
  buildRerouteRequest,
  type RerouteCheckResponse,
  type RerouteRepository,
} from '../../api/reroute'
import { buildCheckpointDelays } from './rerouteSchedule'

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

/** 지하철 구간 안내 중 따릉이 대여소 고갈 가능성을 확인한다(TO_FE-bike-reroute-04.md §3).
 * 예전의 120초 주기 폴링은 일정 기반 체크포인트로 대체했다. 조건 충족 시(그리고 step·route가 바뀔 때)
 * 즉시 1회 확인한 뒤, `buildCheckpointDelays`가 계산한 시점(환승·하차 120초 전, 대여소까지 남은
 * 시간이 30분이 되는 때, 긴 구간 중간)에만 다시 확인한다. 조건이 깨지면 예약을 모두 정리한다. */
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
    // 이 effect가 (route, step) 조합에 대해 다시 실행된 순간을 step 시작으로 본다.
    const timers = buildCheckpointDelays(stateRef.current.route, stateRef.current.step).map(
      (delay) => setTimeout(runCheck, delay),
    )
    return () => {
      cancelled = true
      timers.forEach(clearTimeout)
      controller?.abort()
    }
    // eligible이 true로 바뀌거나 route·step이 바뀔 때 즉시 호출 + 체크포인트를 새로 건다.
    // 체크포인트 시점의 최신 state는 stateRef로 읽으므로 state 전체는 의존성에 넣지 않는다.
  }, [eligible, repository, debugForce, state.route, state.step])
}
