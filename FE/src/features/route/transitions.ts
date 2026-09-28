import type { Leg, TransitionType } from './types'

export function transitionLabel(type?: TransitionType) {
  switch (type) {
    case 'BOARDING':
      return '승차'
    case 'ALIGHTING':
      return '하차'
    case 'TRANSFER':
      return '환승'
    case 'BIKE_RENTAL':
      return '자전거 대여'
    case 'BIKE_RETURN':
      return '자전거 반납'
    default:
      return undefined
  }
}

export function isTransitLeg(leg: Leg) {
  return (leg.mode === 'subway' || leg.mode === 'bus') && !isTransferLeg(leg) && !leg.transitionType
}

export function isTransferLeg(leg: Leg) {
  return leg.transfer === true || leg.transitionType === 'TRANSFER'
}
