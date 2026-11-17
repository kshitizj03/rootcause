import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MotionConfig } from 'motion/react'
import './styles/tokens.css'
import './styles/site.css'
import App from './App.tsx'
import { oldAnchorRedirect } from './lib/anchors'

const moved = oldAnchorRedirect(location.hash)
if (moved) location.replace(moved)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <App />
    </MotionConfig>
  </StrictMode>,
)
