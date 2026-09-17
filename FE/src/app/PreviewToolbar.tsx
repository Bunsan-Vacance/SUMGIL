interface Props {
  guiding: boolean
  isLiveApi: boolean
}
export default function PreviewToolbar({ guiding, isLiveApi }: Props) {
  if (isLiveApi) return null
  return (
    <div className="demo-toolbar">
      <span>
        <b>숨길</b> 화면 미리보기 · 샘플 데이터{guiding ? ' · 수동 길안내' : ''}
      </span>
    </div>
  )
}
