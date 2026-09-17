import { useMemo, useState } from 'react'
import type { ProjectItem } from '../types/scraping.types'
import { MAX_SELECTED_ITEMS } from '../types/scraping.types'

interface PreScrapeModalProps {
  items: ProjectItem[]
  onConfirm: (selected: ProjectItem[]) => void
  onClose: () => void
}

const SOURCE_LABELS: Record<ProjectItem['source'], string> = {
  meta: 'Metadatos',
  card: 'Tarjeta',
  link: 'Enlace',
}

export function PreScrapeModal({ items, onConfirm, onClose }: PreScrapeModalProps) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const selectedItems = useMemo(
    () => items.filter((item) => selectedIds.has(item.id)),
    [items, selectedIds],
  )
  const limitReached = selectedItems.length >= MAX_SELECTED_ITEMS

  function toggle(item: ProjectItem) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(item.id)) {
        next.delete(item.id)
      } else if (next.size < MAX_SELECTED_ITEMS) {
        next.add(item.id)
      }
      return next
    })
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Proyectos detectados" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <header className="modal-header">
          <div className="modal-title-block">
            <h2>Proyectos detectados</h2>
            <p className="modal-subtitle">
              {items.length} {items.length === 1 ? 'proyecto' : 'proyectos'} encontrados
            </p>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Cerrar">
            &times;
          </button>
        </header>

        <div className="modal-progress" aria-live="polite">
          <span className="modal-progress-label">
            {selectedItems.length === 0
              ? 'Selecciona los proyectos de interés'
              : 'Selección'}
          </span>
          <span className="modal-progress-count">
            {selectedItems.length} / {MAX_SELECTED_ITEMS}
          </span>
          <div className="modal-progress-bar" role="progressbar" aria-valuenow={selectedItems.length} aria-valuemin={0} aria-valuemax={MAX_SELECTED_ITEMS}>
            <div
              className="modal-progress-fill"
              style={{ width: `${(selectedItems.length / MAX_SELECTED_ITEMS) * 100}%` }}
            />
          </div>
        </div>

        {items.length === 0 ? (
          <p className="modal-empty">No se detectaron proyectos en esta URL.</p>
        ) : (
          <ul className="project-list">
            {items.map((item, index) => {
              const selected = selectedIds.has(item.id)
              const disabled = !selected && limitReached
              const rowClass = [
                'project-item',
                selected ? 'is-selected' : '',
                disabled ? 'is-disabled' : '',
              ]
                .filter(Boolean)
                .join(' ')
              return (
                <li key={item.id}>
                  <label className={rowClass}>
                    <input
                      type="checkbox"
                      className="project-checkbox"
                      checked={selected}
                      disabled={disabled}
                      onChange={() => toggle(item)}
                    />
                    <span className="project-index">{index + 1}</span>
                    <span className="project-body">
                      <span className="project-title">{item.title || item.url}</span>
                      <span className="project-url">{item.url}</span>
                    </span>
                    <span className={`project-source source-${item.source}`}>
                      {SOURCE_LABELS[item.source]}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        )}

        <footer className="modal-footer">
          <span className="modal-footer-hint">
            {selectedItems.length === 0
              ? 'Selecciona al menos un proyecto'
              : limitReached
                ? `Límite de ${MAX_SELECTED_ITEMS} alcanzado`
                : ''}
          </span>
          <div className="modal-actions">
            <button type="button" className="modal-btn ghost" onClick={onClose}>
              Cancelar
            </button>
            <button
              type="button"
              className="modal-btn primary"
              disabled={selectedItems.length === 0}
              onClick={() => onConfirm(selectedItems)}
            >
              Confirmar {selectedItems.length > 0 && `(${selectedItems.length})`}
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}