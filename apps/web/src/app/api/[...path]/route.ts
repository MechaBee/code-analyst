import type { NextRequest } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'content-length',
  'host',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);

function buildTargetUrl(request: NextRequest, path: string[]) {
  const base = process.env.CONTROL_PLANE_URL || 'http://control-plane:8080';
  const normalizedBase = base.endsWith('/') ? base : `${base}/`;
  const pathname = path.join('/');
  return new URL(`${pathname}${request.nextUrl.search}`, normalizedBase);
}

function filterHeaders(headers: Headers) {
  const filtered = new Headers();
  for (const [key, value] of headers.entries()) {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      filtered.set(key, value);
    }
  }
  return filtered;
}

async function proxyRequest(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const { path } = await context.params;
  const targetUrl = buildTargetUrl(request, path);
  const method = request.method.toUpperCase();

  try {
    const upstream = await fetch(targetUrl, {
      method,
      headers: filterHeaders(request.headers),
      body:
        method === 'GET' || method === 'HEAD'
          ? undefined
          : await request.text(),
      redirect: 'manual',
      cache: 'no-store',
    });

    if (!upstream.ok) {
      const contentType = upstream.headers.get('content-type') || '';
      let responsePreview: string | null = null;
      if (
        contentType.includes('application/json') ||
        contentType.startsWith('text/')
      ) {
        responsePreview = (await upstream.clone().text()).slice(0, 2000);
      }
      console.error('API proxy upstream error', {
        method,
        targetUrl: targetUrl.toString(),
        status: upstream.status,
        statusText: upstream.statusText,
        responsePreview,
      });
    }

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: filterHeaders(upstream.headers),
    });
  } catch (error) {
    console.error('API proxy request failed', {
      method,
      targetUrl: targetUrl.toString(),
      error: error instanceof Error ? error.message : String(error),
    });
    return Response.json(
      {
        detail: 'API proxy request failed.',
      },
      { status: 502 }
    );
  }
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
export const OPTIONS = proxyRequest;
