export type Mode = 'walk' | 'subway' | 'bus' | 'bike'
export type Priority = 'fast' | 'calm'
export interface Place {
  id: string
  name: string
  address: string
  kind: string
  lat?: number
  lng?: number
  placeUrl?: string
}
export interface Leg {
  mode: Mode
  title: string
  note: string
  minutes: number
}
export interface Route {
  id: string
  label: string
  minutes: number
  walk: number
  transfers: number
  crowd: number
  modes: Mode[]
  line: string
  legs: Leg[]
}
