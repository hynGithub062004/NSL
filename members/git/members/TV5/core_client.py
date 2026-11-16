
"""TV5 client for TV4 SRv6 Core Controller REST API."""

import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode


class CoreAPIError(RuntimeError):
    pass


class CoreClient:

    def __init__(self, base_url="http://127.0.0.1:18018", timeout=5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method, endpoint, payload=None):
        url = self.base_url + endpoint

        headers = {"Accept": "application/json"}
        data = None

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}

        except HTTPError as exc:
            raise CoreAPIError(
                f"TV4 HTTP error: {exc.code}"
            ) from exc

        except (URLError, TimeoutError) as exc:
            raise CoreAPIError(
                f"Cannot connect to TV4 Core: {exc}"
            ) from exc

        except (ValueError, UnicodeError) as exc:
            raise CoreAPIError(
                "Invalid JSON response from TV4"
            ) from exc

    def health(self):
        return self._request("GET", "/health")

    def policies(self):
        return self._request("GET", "/policies")

    def core_kpi(self, slice_id):
        if slice_id not in ("embb", "urllc"):
            raise ValueError("Invalid slice_id")

        query = urlencode({"slice_id": slice_id})
        return self._request("GET", "/core-kpi?" + query)

    def events(self):
        return self._request("GET", "/v1/events")


    def preview_policy(self, request_id, slice_id, policy):
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id is required")

        if slice_id not in ("embb", "urllc"):
            raise ValueError("Invalid slice_id")

        if policy not in ("high_bandwidth", "low_latency"):
            raise ValueError("Invalid policy")

        payload = {
            "request_id": request_id,
            "slice_id": slice_id,
            "policy": policy
        }

        return self._request("POST", "/apply-policy", payload)


    def apply_policy(self, request_id, slice_id, policy, confirm):
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id is required")

        if slice_id not in ("embb", "urllc"):
            raise ValueError("Invalid slice_id")

        if policy not in ("high_bandwidth", "low_latency"):
            raise ValueError("Invalid policy")

        if confirm != "APPLY_TV4":
            raise ValueError("Explicit confirm APPLY_TV4 required")

        return self._request("POST", "/apply-policy", {
            "request_id": request_id,
            "slice_id": slice_id,
            "policy": policy,
            "confirm": confirm,
        })

        # Preview only. No "confirm" field.
        return self._request("POST", "/apply-policy", payload)