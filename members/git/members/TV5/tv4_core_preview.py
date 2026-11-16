"""TV5 -> TV4 Core API: read-only inspection and PREVIEW-ONLY policy requests.

This script NEVER sends the TV4 confirmation token. It is a safe first-step
connectivity/integration diagnostic, not proof of real policy application or E2E KPI.

From NSL-main root (Python 3.11+):
  python members/TV5/tv4_core_preview.py --base-url http://127.0.0.1:18018 check
  python members/TV5/tv4_core_preview.py --base-url http://127.0.0.1:18018 preview --slice embb --policy low_latency
  python members/TV5/tv4_core_preview.py --base-url http://127.0.0.1:18018 kpi --slice urllc
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


class TV4APIError(RuntimeError):
    """Connection, HTTP, or JSON payload error when calling TV4."""


class TV4PreviewClient:
    """Minimal stdlib HTTP client that cannot send a confirmed apply operation."""

    def __init__(self, base_url: str, timeout_s: float = 5.0):
        url = base_url.rstrip('/')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('base_url must be a plain http(s) host:port, e.g. http://127.0.0.1:18018')
        if timeout_s <= 0:
            raise ValueError('timeout_s must be positive')
        self.base_url = url
        self.timeout_s = timeout_s

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not path.startswith('/') or '://' in path:
            raise ValueError('Only relative API paths are permitted')
        if method not in ('GET', 'POST'):
            raise ValueError('Only GET and POST are supported')
        data = None
        headers = {'Accept': 'application/json'}
        if payload is not None:
            if method != 'POST':
                raise ValueError('POST required for JSON payloads')
            if 'confirm' in payload:
                raise ValueError('Confirmation is forbidden in preview-only TV5 client')
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        req = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout_s) as response:
                body = response.read().decode('utf-8')
        except HTTPError as exc:
            err = exc.read().decode('utf-8', errors='replace')[:1200]
            raise TV4APIError(f'TV4 returned HTTP {exc.code} at {path}: {err}') from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise TV4APIError(f'Cannot connect to TV4 at {self.base_url}{path}: {exc}') from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise TV4APIError(f'TV4 returned non-JSON data at {path}') from exc

    def health(self) -> Any:
        return self._request('GET', '/health')

    def policies(self) -> Any:
        return self._request('GET', '/policies')

    def events(self) -> Any:
        return self._request('GET', '/v1/events')

    def core_kpi(self, slice_id: str) -> Any:
        if slice_id not in ('embb', 'urllc'):
            raise ValueError('slice_id must be embb or urllc')
        return self._request('GET', '/core-kpi?' + urlencode({'slice_id': slice_id}))

    def preview(self, slice_id: str, policy: str, request_id: str | None = None) -> dict[str, Any]:
        if slice_id not in ('embb', 'urllc'):
            raise ValueError('slice_id must be embb or urllc')
        if policy not in ('high_bandwidth', 'low_latency'):
            raise ValueError('Unsupported SRv6 policy')
        request_id = request_id or ('tv5-preview-' + uuid.uuid4().hex[:16])
        if not request_id or len(request_id) > 120:
            raise ValueError('Invalid request_id')
        # The preview request has EXACTLY these three keys: never include confirm.
        return self._request('POST', '/apply-policy', {
            'request_id': request_id, 'slice_id': slice_id, 'policy': policy,
        })


def _policy_state(response: Any) -> dict[str, Any]:
    """Only compare stable routing fields, excluding refresh timestamps."""
    if not isinstance(response, dict):
        raise TV4APIError('/policies response is not an object')
    slices = response.get('slices')
    if not isinstance(slices, dict):
        raise TV4APIError('/policies response does not contain a slices object')
    result: dict[str, Any] = {}
    for slice_id in ('embb', 'urllc'):
        item = slices.get(slice_id)
        if not isinstance(item, dict):
            raise TV4APIError('/policies response is missing slice ' + slice_id)
        result[slice_id] = {
            key: item.get(key) for key in ('active_policy', 'routing_table', 'route_raw', 'path', 'rule_present')
        }
    return result


def _save(out_dir: Path, basename: str, value: Any) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / basename
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Saved:', target)
    return target


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='TV5 preview-only connectivity diagnostic for TV4 GNS3 SRv6 API')
    p.add_argument('--base-url', default=os.environ.get('TV4_CORE_URL', 'http://127.0.0.1:18018'))
    p.add_argument('--timeout', type=float, default=5.0, help='HTTP request timeout, seconds')
    p.add_argument('--out-dir', default='members/TV5/results/tv4_preview', help='where to save JSON evidence')
    commands = p.add_subparsers(dest='command', required=True)
    commands.add_parser('check', help='GET health + policies + both historical KPI snapshots')
    preview = commands.add_parser('preview', help='POST preview WITHOUT confirm, and compare policies before/after')
    preview.add_argument('--slice', choices=['embb', 'urllc'], required=True)
    preview.add_argument('--policy', choices=['high_bandwidth', 'low_latency'], required=True)
    preview.add_argument('--request-id', default=None)
    kpi = commands.add_parser('kpi', help='GET historical Core KPI for one slice')
    kpi.add_argument('--slice', choices=['embb', 'urllc'], required=True)
    commands.add_parser('events', help='GET TV4 controller events')
    args = p.parse_args(argv)
    client = TV4PreviewClient(args.base_url, args.timeout)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = Path(args.out_dir) / stamp
    try:
        if args.command == 'check':
            health = client.health()
            policies = client.policies()
            _save(folder, 'health.json', health)
            _save(folder, 'policies.json', policies)
            for sid in ('embb', 'urllc'):
                response = client.core_kpi(sid)
                _save(folder, f'core_kpi_{sid}.json', response)
                measurement = response.get('measurement', {}) if isinstance(response, dict) else {}
                if measurement.get('is_live') is not True:
                    print(f'WARNING: {sid} KPI is NOT live; do not merge as measured End-to-End KPI')
                kpi_data = response.get('core_kpi', {}) if isinstance(response, dict) else {}
                if kpi_data.get('switching_time_ms') is None:
                    print(f'INFO: {sid} switching_time_ms is unmeasured/null')
            print('TV4 GET requests completed. This does NOT prove live Core control.')
        elif args.command == 'preview':
            before = client.policies()
            _save(folder, 'policies_before.json', before)
            request_id = args.request_id or ('tv5-preview-' + uuid.uuid4().hex[:16])
            _save(folder, 'preview_request.json', {
                'request_id': request_id, 'slice_id': args.slice, 'policy': args.policy,
            })
            result = client.preview(args.slice, args.policy, request_id)
            _save(folder, 'preview_response.json', result)
            after = client.policies()
            _save(folder, 'policies_after.json', after)
            unchanged = _policy_state(before) == _policy_state(after)
            _save(folder, 'preview_validation.json', {
                'mode': 'PREVIEW_ONLY_NO_CONFIRM',
                'slice_id': args.slice, 'requested_policy': args.policy,
                'both_slice_route_states_unchanged': unchanged,
                'note': 'Compares observed route snapshots only; not a proof of future apply or path steering.',
            })
            print('Preview request sent WITHOUT confirm.')
            print('Both slice route snapshots unchanged:', unchanged)
            if not unchanged:
                print('STOP: Core routing states changed; investigate TV4 before any further requests.', file=sys.stderr)
                return 2
        elif args.command == 'kpi':
            response = client.core_kpi(args.slice)
            _save(folder, f'core_kpi_{args.slice}.json', response)
            if not response.get('measurement', {}).get('is_live', False):
                print('WARNING: historical KPI, not a live End-to-End measurement')
        elif args.command == 'events':
            _save(folder, 'events.json', client.events())
    except (TV4APIError, ValueError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
