import { useEffect, useMemo, useState } from 'react'
import { bikePredictionRepository } from '../../api/repositories'
import type { BikePrediction, BikePredictionRepository } from '../../api/bikePrediction'
import type { Leg, Route } from './types'

interface PredictionTarget {
  leg: Leg
  rentalId: string
  arrivalTime: string
}

type PredictionState =
  | { status: 'loading' }
  | { status: 'success'; value: BikePrediction }
  | { status: 'error' }
  | { status: 'unavailable'; message: string }

function unavailableMessage(route: Route) {
  return route.departedAt
    ? '이 대여소의 도착 시 예측 정보가 아직 없어요.'
    : '출발 시각이 없어 도착 시 예측을 확인할 수 없어요.'
}

function predictionTarget(route: Route): PredictionTarget | null {
  if (!route.departedAt || !Number.isFinite(new Date(route.departedAt).getTime())) return null
  let elapsedMinutes = 0
  for (const leg of route.legs) {
    if (leg.mode === 'bike') {
      const rentalId = leg.from?.rentalId?.trim()
      if (!rentalId) return null
      return {
        leg,
        rentalId,
        arrivalTime: new Date(
          new Date(route.departedAt).getTime() + elapsedMinutes * 60_000,
        ).toISOString(),
      }
    }
    elapsedMinutes += leg.minutes
  }
  return null
}

export function bikePredictionTargetForRoute(route: Route) {
  return predictionTarget(route)
}

function displayTime(value: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(value))
}

export default function BikePrediction({
  route,
  repository = bikePredictionRepository,
}: {
  route: Route
  repository?: BikePredictionRepository | null
}) {
  const hasBikeLeg = route.legs.some((leg) => leg.mode === 'bike')
  const target = useMemo(() => predictionTarget(route), [route])
  const [retryKey, setRetryKey] = useState(0)
  const [state, setState] = useState<PredictionState>(() =>
    target
      ? { status: 'loading' }
      : {
          status: 'unavailable',
          message: unavailableMessage(route),
        },
  )

  useEffect(() => {
    if (!target) {
      setState({
        status: 'unavailable',
        message: unavailableMessage(route),
      })
      return
    }
    if (!repository) {
      setState({ status: 'unavailable', message: '도착 시 따릉이 예측을 제공할 수 없어요.' })
      return
    }
    const controller = new AbortController()
    setState({ status: 'loading' })
    repository
      .prediction(target.rentalId, target.arrivalTime, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setState({ status: 'success', value })
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: 'error' })
      })
    return () => controller.abort()
  }, [repository, retryKey, route, target])

  const retry = () => {
    if (state.status === 'error') setRetryKey((value) => value + 1)
  }

  const currentPrediction =
    state.status === 'success' &&
    target &&
    state.value.rentalId === target.rentalId &&
    new Date(state.value.arrivalTime).getTime() === new Date(target.arrivalTime).getTime()
      ? state.value
      : null

  if (!hasBikeLeg) return null

  return (
    <section className="bike-prediction-card" aria-label="따릉이 대여 예측">
      <div className="bike-prediction-summary">
        <div className="bike-prediction-copy">
          <div className="bike-prediction-heading">
            <h3>따릉이 대여 예측</h3>
            {currentPrediction?.source === 'MOCK' && (
              <small className="bike-prediction-source">샘플</small>
            )}
          </div>
          {target && (
            <p className="bike-prediction-arrival">
              {target.leg.from?.name
                ? `${target.leg.from.name} · ${displayTime(target.arrivalTime)} 도착`
                : `${displayTime(target.arrivalTime)} 도착`}
            </p>
          )}
        </div>
        {currentPrediction && (
          <div className="bike-prediction-result">
            {currentPrediction.status === 'UNAVAILABLE' ? (
              <strong>도착 시 예측 정보 없음</strong>
            ) : currentPrediction.predictedBikes === null ? (
              <strong>예측 수량 없음</strong>
            ) : (
              <strong>{currentPrediction.predictedBikes}대 예상</strong>
            )}
          </div>
        )}
      </div>
      {state.status === 'error' && (
        <div className="bike-prediction-state" role="alert">
          <p>도착 시 따릉이 예측을 불러오지 못했어요.</p>
          <button className="secondary" onClick={retry}>
            다시 시도
          </button>
        </div>
      )}
      {state.status === 'unavailable' && (
        <p className="bike-prediction-state" role="status">
          {state.message}
        </p>
      )}
      {(state.status === 'success' && !currentPrediction) || state.status === 'loading' ? (
        <p className="bike-prediction-state" role="status">
          도착 시 재고를 예측하고 있어요…
        </p>
      ) : null}
    </section>
  )
}
