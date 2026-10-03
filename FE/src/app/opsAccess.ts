// 운영자 뷰는 개발 빌드이거나 VITE_OPS_VIEW=true일 때만 열린다.
// 이 검사는 접근 제어가 아니라 노출 범위 제한이다. 공개 노출은 Infra·BE 접근 정책 이후에 결정한다.
interface OpsEnv {
  DEV?: boolean
  VITE_OPS_VIEW?: string
}

export function isOpsViewEnabled(env: OpsEnv = import.meta.env): boolean {
  return env.DEV === true || env.VITE_OPS_VIEW?.trim().toLowerCase() === 'true'
}
