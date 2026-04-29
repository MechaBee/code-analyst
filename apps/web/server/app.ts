import express from 'express';
import { createProxyMiddleware } from 'http-proxy-middleware';
import type { Request, Response } from 'express';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();

// Proxy API calls to the control-plane
app.use(
  '/api',
  createProxyMiddleware({
    target: process.env.CONTROL_PLANE_URL || 'http://control-plane:8080',
    changeOrigin: true,
    pathRewrite: { '^/api': '' },
  })
);

const isDev = process.env.NODE_ENV === 'development';

if (isDev) {
  // In dev, proxy all non-API routes to the Next.js dev server
  app.use(
    '/',
    createProxyMiddleware({
      target: 'http://localhost:3001',
      changeOrigin: true,
      ws: true,
    })
  );
} else {
  // Serve static files from Next.js build output
  const distPath = path.join(__dirname, '../dist');
  app.use(express.static(distPath));

  // SPA fallback
  app.get('*', (_req, res) => {
    res.sendFile(path.join(distPath, 'index.html'));
  });
}

export default app;
