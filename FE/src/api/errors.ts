export type RepositoryErrorCode =
  | 'same-origin-destination'
  | 'station-not-found'
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
