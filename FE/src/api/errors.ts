export type RepositoryErrorCode =
  | 'route-data-not-ready'
  | 'same-origin-destination'
  | 'station-not-found'
  | 'bike-station-not-found'
  | 'coordinate-not-ready'
  | 'invalid-coordinate'
  | 'unsupported-place'
  | 'bad-request'
  | 'network'
  | 'invalid-response'

export class RepositoryError extends Error {
  readonly code: RepositoryErrorCode
  readonly status?: number

  constructor(code: RepositoryErrorCode, message: string, status?: number) {
    super(message)
    this.name = 'RepositoryError'
    this.code = code
    this.status = status
  }
}
