import QaPage from '../pages/QaPage.jsx'
import IngestPage from '../pages/IngestPage.jsx'
import SearchPage from '../pages/SearchPage.jsx'
import AnalyzePage from '../pages/AnalyzePage.jsx'
import DashboardPage from '../pages/DashboardPage.jsx'
import GraphPage from '../pages/GraphPage.jsx'
import PetPage from '../pages/PetPage.jsx'

export default function Pages({ currentPage, settings, openDetails, closeDetails }) {
  switch (currentPage) {
    case 'ingest': return <IngestPage />
    case 'search': return <SearchPage settings={settings} openDetails={openDetails} />
    case 'analyze': return <AnalyzePage />
    case 'dashboard': return <DashboardPage />
    case 'graph': return <GraphPage openDetails={openDetails} />
    case 'pet': return <PetPage />
    default: return <QaPage settings={settings} />
  }
}