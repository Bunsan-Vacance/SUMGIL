import { useCallback, useEffect, useRef, useState } from 'react'
import { bikePredictionRepository, bikeStockRepository } from '../../api/repositories'
import type { BikePrediction, BikePredictionRepository } from '../../api/bikePrediction'
import type { BikeStationRepository, BikeStock } from '../../api/contracts'

export type OutlookSlot = 'now' | 'in15' | 'in30'
export const OUTLOOK_OFFSETS_MINUTES = { in15: 15, in30: 30 } as const

export type StockOutlook =
  | { status: 'loading' }
  | { status: 'success'; value: BikeStock }
  | { status: 'error' }
  | { status: 'unavailable' }
export type PredictionOutlook =
  | { status: 'loading' }
  | { status: 'success'; value: BikePrediction }
  | { status: 'error' }
  | { status: 'unavailable' }

export interface OutlookState {
  stock: StockOutlook
  predictions: Record<'in15' | 'in30', PredictionOutlook>
  retry(): void
}

type Outlook = Pick<OutlookState, 'stock' | 'predictions'>

function uniform(status: 'loading' | 'unavailable'): Outlook {
  return { stock: { status }, predictions: { in15: { status }, in30: { status } } }
}

function isAbort(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

/**
 * 대여소 하나의 현재 재고와 15분·30분 뒤 예측을 병렬로 조회한다.
 * 응답은 각각 독립적으로 반영하고, 대여소가 바뀌거나 재시도하면 이전 요청을 취소한다.
 * UNAVAILABLE 응답도 success로 두며 문구는 카드가 정한다.
 */
export function useBikeStationOutlook(
  rentalId: string | null,
  stockRepository: Pick<BikeStationRepository, 'stock'> | null = bikeStockRepository,
  predictionRepository: BikePredictionRepository | null = bikePredictionRepository,
  now: () => Date = () => new Date(),
): OutlookState {
  const [state, setState] = useState<Outlook>(() => uniform(rentalId ? 'loading' : 'unavailable'))
  const [attempt, setAttempt] = useState(0)
  const requestId = useRef(0)
  const nowRef = useRef(now)
  nowRef.current = now
  // 저장소 객체가 렌더마다 새로 만들어져도 재조회 루프가 생기지 않도록 ref로 최신값만 읽는다.
  const repositoriesRef = useRef({ stockRepository, predictionRepository })
  repositoriesRef.current = { stockRepository, predictionRepository }

  useEffect(() => {
    const id = ++requestId.current
    const { stockRepository, predictionRepository } = repositoriesRef.current
    if (!rentalId) {
      setState(uniform('unavailable'))
      return
    }
    const controller = new AbortController()
    const { signal } = controller
    const current = () => !signal.aborted && id === requestId.current
    setState({
      stock: stockRepository ? { status: 'loading' } : { status: 'unavailable' },
      predictions: {
        in15: predictionRepository ? { status: 'loading' } : { status: 'unavailable' },
        in30: predictionRepository ? { status: 'loading' } : { status: 'unavailable' },
      },
    })
    if (stockRepository) {
      stockRepository
        .stock(rentalId, signal)
        .then((value) => {
          if (current()) setState((prev) => ({ ...prev, stock: { status: 'success', value } }))
        })
        .catch((error: unknown) => {
          if (!current() || isAbort(error)) return
          setState((prev) => ({ ...prev, stock: { status: 'error' } }))
        })
    }
    if (predictionRepository) {
      const base = nowRef.current().getTime()
      ;(['in15', 'in30'] as const).forEach((slot) => {
        const arrivalTime = new Date(base + OUTLOOK_OFFSETS_MINUTES[slot] * 60_000).toISOString()
        predictionRepository
          .prediction(rentalId, arrivalTime, signal)
          .then((value) => {
            if (!current()) return
            setState((prev) => ({
              ...prev,
              predictions: { ...prev.predictions, [slot]: { status: 'success', value } },
            }))
          })
          .catch((error: unknown) => {
            if (!current() || isAbort(error)) return
            setState((prev) => ({
              ...prev,
              predictions: { ...prev.predictions, [slot]: { status: 'error' } },
            }))
          })
      })
    }
    return () => {
      controller.abort()
    }
  }, [rentalId, attempt])

  const retry = useCallback(() => setAttempt((value) => value + 1), [])
  return { ...state, retry }
}
