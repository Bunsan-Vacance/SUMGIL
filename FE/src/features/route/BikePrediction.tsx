import { useEffect, useMemo, useState } from 'react'
import {
  bikePredictionRepository,
  bikeStockRepository,
  isBikePredictionMockEnabled,
  isBikeStockMockEnabled,
} from '../../api/repositories'
import type { BikePrediction, BikePredictionRepository } from '../../api/bikePrediction'
import type { BikeStationRepository, BikeStock } from '../../api/contracts'
import { bikePredictionTargetForRoute, bikeStockTargetForRoute } from './bikeAvailability'
import type { Route } from './types'

export { bikePredictionTargetForRoute } from './bikeAvailability'

type PredictionState =
  | { status: 'loading' }
  | { status: 'success'; value: BikePrediction }
  | { status: 'error' }
  | { status: 'unavailable'; message: string }

type StockState =
  | { status: 'loading' }
  | { status: 'success'; value: BikeStock }
  | { status: 'error' }
  | { status: 'unavailable'; message: string }

function unavailableMessage(route: Route) {
  return route.departedAt
    ? '이 대여소의 도착 시 예측 정보가 아직 없어요.'
    : '출발 시각이 없어 도착 시 예측을 확인할 수 없어요.'
}

function displayTime(value: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(value))
}

function updatedTime(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? displayTime(value) : value
}

export default function BikePrediction({
  route,
  repository = bikePredictionRepository,
  stockRepository = bikeStockRepository,
}: {
  route: Route
  repository?: BikePredictionRepository | null
  stockRepository?: Pick<BikeStationRepository, 'stock'> | null
}) {
  const hasBikeLeg = route.legs.some((leg) => leg.mode === 'bike')
  const target = useMemo(() => bikePredictionTargetForRoute(route), [route])
  const stockTargetForRoute = useMemo(() => bikeStockTargetForRoute(route), [route])
  const [retryKey, setRetryKey] = useState(0)
  const [stockRetryKey, setStockRetryKey] = useState(0)
  const [state, setState] = useState<PredictionState>(() =>
    target
      ? { status: 'loading' }
      : {
          status: 'unavailable',
          message: unavailableMessage(route),
        },
  )
  const [stockState, setStockState] = useState<StockState>(() =>
    stockTargetForRoute
      ? { status: 'loading' }
      : { status: 'unavailable', message: '현재 따릉이 재고를 확인할 수 없어요.' },
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

  useEffect(() => {
    if (!stockTargetForRoute) {
      setStockState({ status: 'unavailable', message: '현재 따릉이 재고를 확인할 수 없어요.' })
      return
    }
    if (!stockRepository) {
      setStockState({ status: 'unavailable', message: '현재 따릉이 재고를 확인할 수 없어요.' })
      return
    }
    const controller = new AbortController()
    setStockState({ status: 'loading' })
    stockRepository
      .stock(stockTargetForRoute.rentalId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setStockState({ status: 'success', value })
      })
      .catch(() => {
        if (!controller.signal.aborted) setStockState({ status: 'error' })
      })
    return () => controller.abort()
  }, [route, stockRepository, stockRetryKey, stockTargetForRoute])

  const retry = () => {
    if (state.status === 'error') setRetryKey((value) => value + 1)
  }
  const retryStock = () => {
    if (stockState.status === 'error') setStockRetryKey((value) => value + 1)
  }

  const currentPrediction =
    state.status === 'success' &&
    target &&
    state.value.rentalId === target.rentalId &&
    new Date(state.value.arrivalTime).getTime() === new Date(target.arrivalTime).getTime()
      ? state.value
      : null
  const currentStock =
    stockState.status === 'success' &&
    stockTargetForRoute &&
    stockState.value.rentalId === stockTargetForRoute.rentalId
      ? stockState.value
      : null
  if (!hasBikeLeg) return null

  return (
    <section className="bike-prediction-card" aria-label="따릉이 현재 재고 및 도착 예측">
      <div className="bike-prediction-copy">
        <h3>따릉이 대여 정보</h3>
        {(target || stockTargetForRoute)?.leg.from?.name && (
          <p className="bike-prediction-arrival">
            {(target || stockTargetForRoute)?.leg.from?.name}
          </p>
        )}
      </div>
      <div className="bike-prediction-values">
        <div className="bike-prediction-value" aria-label="현재 따릉이 재고">
          {currentStock?.status === 'AVAILABLE' && currentStock.availableBikes !== null ? (
            <>
              <span className="bike-prediction-label">현재</span>
              <strong>{currentStock.availableBikes}대</strong>
              {currentStock.availableBikes === 0 && (
                <small className="bike-prediction-stock-note">현재 대여할 자전거가 없어요.</small>
              )}
            </>
          ) : currentStock?.status === 'STALE' ? (
            <>
              <span className="bike-prediction-label">
                {currentStock.stockUpdatedAt
                  ? `마지막 확인 ${updatedTime(currentStock.stockUpdatedAt)}`
                  : '재고 기준 시각 없음'}
              </span>
              <strong>
                {currentStock.availableBikes === null
                  ? '재고 정보 없음'
                  : `${currentStock.availableBikes}대`}
              </strong>
            </>
          ) : currentStock ? (
            <>
              <strong>재고 정보 없음</strong>
              <small className="bike-prediction-stock-note">재고 기준 시각 없음</small>
            </>
          ) : stockState.status === 'loading' || stockState.status === 'success' ? (
            <span className="bike-prediction-state" role="status">
              현재 재고 확인 중…
            </span>
          ) : stockState.status === 'error' ? (
            <div className="bike-prediction-state" role="alert">
              <p>현재 재고를 불러오지 못했어요.</p>
              <button className="secondary" onClick={retryStock}>
                재고 다시 시도
              </button>
            </div>
          ) : (
            <span className="bike-prediction-state" role="status">
              {stockState.message}
            </span>
          )}
          {isBikeStockMockEnabled && currentStock && (
            <small className="bike-prediction-source">샘플</small>
          )}
        </div>
        <div className="bike-prediction-value" aria-label="도착 시 따릉이 예상">
          <span className="bike-prediction-label">
            {target ? displayTime(target.arrivalTime) : '도착 시'}
          </span>
          {currentPrediction ? (
            currentPrediction.status === 'UNAVAILABLE' ? (
              <strong>도착 시 예측 정보 없음</strong>
            ) : currentPrediction.predictedBikes === null ? (
              <strong>예측 수량 없음</strong>
            ) : (
              <>
                <strong>{currentPrediction.predictedBikes}대 예상</strong>
                {currentPrediction.predictedBikes === 0 && (
                  <small className="bike-prediction-unavailable-note">
                    도착 시 대여할 자전거가 없어요.
                  </small>
                )}
              </>
            )
          ) : state.status === 'error' ? (
            <div className="bike-prediction-state" role="alert">
              <p>도착 시 따릉이 예측을 불러오지 못했어요.</p>
              <button className="secondary" onClick={retry}>
                다시 시도
              </button>
            </div>
          ) : state.status === 'unavailable' ? (
            <p className="bike-prediction-state" role="status">
              {state.message}
            </p>
          ) : (
            <p className="bike-prediction-state" role="status">
              도착 시 재고를 예측하고 있어요…
            </p>
          )}
          {isBikePredictionMockEnabled && currentPrediction?.source === 'MOCK' && (
            <small className="bike-prediction-source">샘플</small>
          )}
        </div>
      </div>
    </section>
  )
}
