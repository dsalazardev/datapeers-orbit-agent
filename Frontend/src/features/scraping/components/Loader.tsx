interface LoaderProps {
  size?: number
}

export function Loader({ size = 16 }: LoaderProps) {
  return (
    <span
      className="loader"
      style={{ width: size, height: size }}
      role="status"
      aria-label="Cargando"
    />
  )
}