import http from 'k6/http';
import { check, sleep } from 'k6';

const base = __ENV.BASE_URL || 'http://host.docker.internal:8001';
export const options = {
  vus: 2,
  duration: '30s',
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max'],
  thresholds: {
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
    http_req_duration: ['p(95)<3000'],
  },
};

export default function () {
  const response = http.get(`${base}/api/v1/dashboard/snapshot?history_limit=20`, { timeout: '15s' });
  let data;
  try { data = response.json(); } catch { data = null; }
  check(response, {
    'snapshot complete and fresh': () => response.status === 200 && data?.complete === true && data?.stale === false,
  });
  sleep(1);
}
