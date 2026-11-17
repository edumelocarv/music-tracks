import { BrowserRouter, Route, Routes } from 'react-router'
import { AppShell } from './components/AppShell'
import { LibraryPage } from './pages/LibraryPage'
import { SettingsPage } from './pages/SettingsPage'
import { SongPage } from './pages/SongPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<LibraryPage />} />
          <Route path="songs/:id" element={<SongPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<LibraryPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
