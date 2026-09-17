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
    <section className="bike-prediction-card" aria-label="도착 시 따릉이 예측">
      <header>
        <div>
          <h3>도착 시 따릉이 예측</h3>
          {target?.leg.from?.name && <small>{target.leg.from.name}</small>}
        </div>
        <span>예측</span>
      </header>
      {target && (
        <p className="bike-prediction-arrival">
          대여소 도착 예상 {displayTime(target.arrivalTime)}
        </p>
      )}
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
      {currentPrediction && (
        <div className="bike-prediction-result">
          {currentPrediction.predictedBikes === null ? (
            <strong>예측 수량 없음</strong>
          ) : (
            <strong>{currentPrediction.predictedBikes}대 예상</strong>
          )}
          <p>
            {currentPrediction.status === 'AVAILABLE'
              ? '현재 재고가 아니라 도착 시각 기준 예측이에요.'
              : '도착 시 예측을 제공할 수 없어요.'}
          </p>
          {currentPrediction.availabilityProbability !== null && (
            <small>
              대여 가능성 {Math.round(currentPrediction.availabilityProbability * 100)}%
            </small>
          )}
          <small>
            {currentPrediction.source === 'MOCK' ? '미리보기 예측' : '모델 산출'}
            {currentPrediction.predictedAt &&
              ` · 산출 ${displayTime(currentPrediction.predictedAt)}`}
          </small>
        </div>
      )}
    </section>
  )
}
