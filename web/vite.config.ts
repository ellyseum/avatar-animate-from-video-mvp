import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    allowedHosts: ['ngrok.ellyseum.dev'],
    proxy: {
      '/api': 'http://localhost:3001',
    },
  },
})
