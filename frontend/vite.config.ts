import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

const sslCert = path.resolve(__dirname, '../ssl/cert.pem')
const sslKey  = path.resolve(__dirname, '../ssl/key.pem')
const hasSSL  = fs.existsSync(sslCert) && fs.existsSync(sslKey)

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,  // bind to 0.0.0.0 for LAN access
    https: hasSSL
      ? { cert: fs.readFileSync(sslCert), key: fs.readFileSync(sslKey) }
      : undefined,
  },
})
