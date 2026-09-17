import { useState } from 'react'
import './App.css'
import heroImg from './assets/hero.png'
import { PreScrapeModal } from './features/scraping/components/PreScrapeModal'
import { UrlInputForm } from './features/scraping/components/UrlInputForm'
import { usePreScrape } from './features/scraping/hooks/usePreScrape'
import type { ProjectItem } from './features/scraping/types/scraping.types'

function App() {
  const { data, loading, error, run, reset } = usePreScrape()
  const [selected, setSelected] = useState<ProjectItem[]>([])

  function handleSubmit(url: string) {
    run({ url })
  }

  function handleConfirm(items: ProjectItem[]) {
    setSelected(items)
    reset()
  }

  return (
    <>
      <section id="center">
        <div className="hero">
          <img src={heroImg} className="base" width="170" height="179" alt="" />
        </div>
        <div>
          <h1>ORBIT</h1>
          <p>Detecta proyectos desde una URL fuente con pre-scraping ultrarrápido.</p>
        </div>

        <UrlInputForm onSubmit={handleSubmit} loading={loading} />

        {error && <p className="error-message">{error}</p>}

        {selected.length > 0 && (
          <div className="selection-summary">
            <h2>Proyectos seleccionados</h2>
            <ul>
              {selected.map((item) => (
                <li key={item.id}>
                  <a href={item.url} target="_blank" rel="noreferrer">
                    {item.title}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {data && !loading && (
        <PreScrapeModal items={data.items} onConfirm={handleConfirm} onClose={reset} />
      )}
    </>
  )
}

export default App