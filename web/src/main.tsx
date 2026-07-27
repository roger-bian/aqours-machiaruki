import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Auth0Provider } from '@auth0/auth0-react'
import 'leaflet/dist/leaflet.css'
import './index.css'
import App from './App.tsx'
import { AuthGate } from './auth/AuthGate'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Auth0Provider
      domain={import.meta.env.VITE_AUTH0_DOMAIN}
      clientId={import.meta.env.VITE_AUTH0_CLIENT_ID}
      authorizationParams={{ redirect_uri: window.location.origin }}
      useRefreshTokens
      cacheLocation="localstorage"
      // Default is 1 day (auth0-spa-js DEFAULT_SESSION_CHECK_EXPIRY_DAYS) -
      // the mount-time isAuthenticated check silently skips its token refresh
      // once this cookie expires, so after any gap longer than a day the app
      // rendered as "logged in" from a stale cached user with an actually
      // expired ID token (masked in practice by freshIdToken.ts's active
      // refresh-on-request, but this keeps the initial state honest too).
      // 30 matches Auth0's default refresh token inactivity expiration.
      sessionCheckExpiryDays={30}
    >
      <AuthGate>
        <App />
      </AuthGate>
    </Auth0Provider>
  </StrictMode>,
)
