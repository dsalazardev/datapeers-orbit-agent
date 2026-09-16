import { useState } from 'react'
import type { FormEvent } from 'react'
import { Loader } from './Loader'

interface UrlInputFormProps {
  onSubmit: (url: string) => void
  loading?: boolean
}

export function UrlInputForm({ onSubmit, loading = false }: UrlInputFormProps) {
  const [url, setUrl] = useState('')

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalized = url.trim()
    if (normalized) {
      onSubmit(normalized)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="url-input-form">
      <input
        type="url"
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        placeholder="https://ejemplo.com/proyectos"
        aria-label="URL a escanear"
        required
        disabled={loading}
      />
      <button type="submit" disabled={loading || url.trim().length === 0}>
        {loading ? (
          <>
            <Loader size={16} />
            Analizando…
          </>
        ) : (
          'Analizar URL'
        )}
      </button>
    </form>
  )
}