import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const repo = resolve(import.meta.dirname, '../../..');
const read = (path: string) => readFileSync(resolve(repo, path), 'utf8');

describe('единый origin и режимы запуска', () => {
  it('не превращает ошибки API в SPA и запрещает private API', () => {
    for (const name of ['nginx.conf', 'nginx.dev.conf']) {
      const config = read(`deploy/web/${name}`);
      expect(config).toContain('location ^~ /api/v1/');
      expect(config).toContain('location ^~ /internal/');
      expect(config).toContain('include /etc/nginx/og1-proxy-headers.conf');
      const headers = read('deploy/web/proxy-headers.conf');
      expect(headers).toContain('proxy_intercept_errors off');
      expect(headers).toContain('proxy_next_upstream off');
      expect(headers).toContain('proxy_set_header X-Forwarded-For $remote_addr');
      expect(headers).toContain('proxy_set_header X-Forwarded-Proto $scheme');
    }
  });
  it('разделяет Vite HMR и статическую production сборку', () => {
    expect(read('deploy/web/nginx.dev.conf')).toContain('proxy_set_header Upgrade $http_upgrade');
    expect(read('deploy/web/nginx.conf')).not.toContain('proxy_set_header Upgrade');
    expect(read('services/frontend/nginx.conf')).toContain('try_files $uri $uri/ /index.html');
    const image = read('services/frontend/Dockerfile');
    expect(image).toContain('--frozen-lockfile');
    expect(image).toContain('COPY --from=build');
    expect(image).not.toContain('pnpm start');
  });
  it('production сбрасывает прямые ports и исходники Backoffice', () => {
    const config = read('compose.production.yaml');
    for (const name of [
      'schedule-api',
      'analytics-api',
      'document-api',
      'gateway-api',
      'backoffice-api',
      'schedule-postgres',
      'schedule-kafka',
      'schedule-redis',
      'gateway-postgres',
      'backoffice-postgres',
      'document-postgres',
      'analytics-clickhouse',
    ]) {
      expect(config).toMatch(new RegExp(`${name}:\\s+ports: !reset \\[\\]`));
    }
    expect(config).toContain('volumes: !reset []');
    expect(config).toContain('gunicorn');
    expect(config).not.toContain('runserver');
  });
});
