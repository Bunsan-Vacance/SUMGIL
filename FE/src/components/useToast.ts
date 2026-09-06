import { useEffect, useState } from 'react'

export function useToast() {
  const [message, setMessage] = useState('')
  useEffect(() => {
    if (!message) return
    const timeout = setTimeout(() => setMessage(''), 2800)
    return () => clearTimeout(timeout)
  }, [message])
  return { message, setMessage }
}
