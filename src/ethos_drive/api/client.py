"""HTTP API client for communicating with EthOS server."""

import logging
import os
import time
from pathlib import Path
from typing import IO, Optional

import httpx

log = logging.getLogger(__name__)

# API timeout defaults
TIMEOUT_DEFAULT = 30
TIMEOUT_UPLOAD = 300
TIMEOUT_DOWNLOAD = 600


class APIError(Exception):
    """API request failed."""

    def __init__(self, message: str, status_code: int = 0, response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class EthosAPIClient:
    """HTTP client for the EthOS sync-drive API.

    Handles authentication, request retries, and chunked transfers.
    On 401 (token expired), automatically re-authenticates using stored
    credentials and retries the request once.
    """

    def __init__(self, server_url: str, verify_ssl: bool = True):
        self.server_url = server_url.rstrip("/")
        self.token: Optional[str] = None
        self._credentials: Optional[dict] = None  # {username, password}
        self._on_token_refreshed = None  # callback(new_token) to persist
        self._reauth_in_progress = False
        self._client = httpx.Client(
            base_url=self.server_url,
            verify=verify_ssl,
            timeout=TIMEOUT_DEFAULT,
            follow_redirects=True,
        )

    def set_token(self, token: str):
        """Set authentication token."""
        self.token = token
        self._client.headers["Authorization"] = f"Bearer {token}"

    def set_credentials(self, username: str, password: str):
        """Store credentials for automatic re-authentication on token expiry."""
        self._credentials = {"username": username, "password": password}

    def set_token_refresh_callback(self, callback):
        """Set callback invoked with new token after successful re-auth."""
        self._on_token_refreshed = callback

    def _headers(self) -> dict:
        h = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _raw_request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Execute HTTP request and return raw response."""
        kwargs.setdefault("headers", {}).update(self._headers())
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.ConnectError as e:
            raise APIError(f"Cannot connect to server: {e}") from e
        except httpx.TimeoutException as e:
            raise APIError(f"Request timed out: {e}") from e

    def _parse_response(self, resp: httpx.Response) -> dict:
        """Parse response, raise APIError on failure."""
        if resp.status_code == 401:
            raise APIError("Authentication failed", status_code=401)
        if resp.status_code == 403:
            raise APIError("Forbidden", status_code=403)
        try:
            data = resp.json()
        except Exception:
            if resp.status_code >= 400:
                raise APIError(f"HTTP {resp.status_code}: {resp.text}", status_code=resp.status_code)
            return {"ok": True}
        if resp.status_code >= 400:
            raise APIError(data.get("error", f"HTTP {resp.status_code}"), status_code=resp.status_code, response=data)
        return data

    def _try_reauth(self) -> bool:
        """Re-authenticate using stored credentials. Returns True on success."""
        if self._reauth_in_progress or not self._credentials:
            return False
        self._reauth_in_progress = True
        try:
            log.info("Token expired, re-authenticating...")
            payload = {
                "username": self._credentials["username"],
                "password": self._credentials["password"],
            }
            resp = self._raw_request("POST", "/api/auth/login", json=payload)
            data = resp.json()
            token = data.get("token")
            if data.get("totp_required"):
                log.warning("Re-auth requires TOTP — cannot auto-refresh")
                return False
            if token:
                self.set_token(token)
                if self._on_token_refreshed:
                    self._on_token_refreshed(token)
                log.info("Re-authentication successful")
                return True
            return False
        except Exception as e:
            log.warning("Re-authentication failed: %s", e)
            return False
        finally:
            self._reauth_in_progress = False

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make an authenticated API request. Returns parsed JSON.

        On 401, attempts to re-authenticate with stored credentials
        and retries the request once.
        """
        resp = self._raw_request(method, path, **kwargs)

        if resp.status_code == 401 and path != "/api/auth/login":
            if self._try_reauth():
                # Update auth header and retry
                if "headers" in kwargs:
                    kwargs["headers"].update(self._headers())
                resp = self._raw_request(method, path, **kwargs)

        return self._parse_response(resp)

    # --- Authentication ---

    def login(self, username: str, password: str, totp_code: str = "") -> dict:
        """Authenticate and get token.

        Returns dict with either:
          {"token": "..."} on success
          {"totp_required": True} if 2FA code needed
        """
        payload = {"username": username, "password": password}
        if totp_code:
            payload["totp_code"] = totp_code
        data = self._request("POST", "/api/auth/login", json=payload)
        token = data.get("token")
        if token:
            self.set_token(token)
        return data

    def check_connection(self) -> bool:
        """Test if we can reach the server and our token is valid."""
        try:
            data = self._request("GET", "/api/sync-drive/ping")
            return data.get("ok", False)
        except APIError:
            return False

    # --- Device Registration ---

    def register_device(self, device_id: str, device_name: str) -> dict:
        """Register this client as a sync device."""
        return self._request("POST", "/api/sync-drive/devices/register", json={
            "device_id": device_id,
            "device_name": device_name,
        })

    def unregister_device(self, device_id: str) -> dict:
        """Remove device registration."""
        return self._request("POST", "/api/sync-drive/devices/unregister", json={
            "device_id": device_id,
        })

    # --- Sync State ---

    def get_remote_state(self, remote_path: str, recursive: bool = True) -> dict:
        """Get file listing with metadata for a remote directory.

        Returns: {files: [{path, size, mtime_ns, xxhash, is_dir}, ...]}
        """
        return self._request("POST", "/api/sync-drive/state", json={
            "path": remote_path,
            "recursive": recursive,
        })

    def get_changes_since(self, remote_path: str, since_version: int) -> dict:
        """Get changes since a specific sync version.

        Returns: {changes: [{action, path, ...}], current_version: int}
        """
        return self._request("POST", "/api/sync-drive/changes", json={
            "path": remote_path,
            "since_version": since_version,
        })

    # --- File Operations ---

    def download_file(self, remote_path: str, local_path: str,
                      progress_callback=None) -> bool:
        """Download a file from the server with progress tracking."""
        headers = self._headers()
        local_dir = os.path.dirname(local_path)
        os.makedirs(local_dir, exist_ok=True)

        # Use temp file for atomic write
        tmp_path = local_path + ".ethos-tmp"
        try:
            with self._client.stream("GET", "/api/sync-drive/download",
                                     params={"path": remote_path},
                                     headers=headers,
                                     timeout=TIMEOUT_DOWNLOAD) as resp:
                if resp.status_code != 200:
                    raise APIError(f"Download failed: HTTP {resp.status_code}",
                                   status_code=resp.status_code)

                total = int(resp.headers.get("content-length", 0))
                downloaded = 0

                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total:
                            progress_callback(downloaded, total)

            # Atomic rename
            if os.path.exists(local_path):
                os.replace(tmp_path, local_path)
            else:
                os.rename(tmp_path, local_path)

            return True

        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def upload_file(self, local_path: str, remote_path: str,
                    chunk_size: int = 4 * 1024 * 1024,
                    progress_callback=None) -> dict:
        """Upload a file to the server using chunked upload."""
        file_size = os.path.getsize(local_path)

        # Small files: single upload
        if file_size <= chunk_size:
            with open(local_path, "rb") as f:
                return self._request("POST", "/api/sync-drive/upload", files={
                    "file": (os.path.basename(local_path), f),
                }, data={
                    "path": remote_path,
                })

        # Large files: chunked upload
        init_resp = self._request("POST", "/api/sync-drive/upload/init", json={
            "path": remote_path,
            "size": file_size,
            "filename": os.path.basename(local_path),
        })
        session_id = init_resp["session_id"]

        try:
            offset = 0
            chunk_index = 0
            with open(local_path, "rb") as f:
                while offset < file_size:
                    chunk_data = f.read(chunk_size)
                    if not chunk_data:
                        break

                    self._request("POST", "/api/sync-drive/upload/chunk",
                                  files={"chunk": ("chunk", chunk_data)},
                                  data={
                                      "session_id": session_id,
                                      "offset": str(offset),
                                      "index": str(chunk_index),
                                  },
                                  timeout=TIMEOUT_UPLOAD)

                    offset += len(chunk_data)
                    chunk_index += 1
                    if progress_callback:
                        progress_callback(offset, file_size)

            return self._request("POST", "/api/sync-drive/upload/complete", json={
                "session_id": session_id,
            })

        except Exception:
            # Abort on failure
            try:
                self._request("POST", "/api/sync-drive/upload/abort", json={
                    "session_id": session_id,
                })
            except Exception:
                pass
            raise

    def delete_remote(self, remote_path: str) -> dict:
        """Delete a file or directory on the server."""
        return self._request("POST", "/api/sync-drive/delete", json={
            "path": remote_path,
        })

    def create_remote_dir(self, remote_path: str) -> dict:
        """Create a directory on the server."""
        return self._request("POST", "/api/sync-drive/mkdir", json={
            "path": remote_path,
        })

    def move_remote(self, src_path: str, dst_path: str) -> dict:
        """Move/rename a file on the server."""
        return self._request("POST", "/api/sync-drive/move", json={
            "src": src_path,
            "dst": dst_path,
        })

    # --- Versioning ---

    def get_versions(self, remote_path: str) -> dict:
        """Get version history for a file."""
        return self._request("GET", "/api/sync-drive/versions", params={
            "path": remote_path,
        })

    def restore_version(self, remote_path: str, version_id: int) -> dict:
        """Restore a specific version of a file."""
        return self._request("POST", "/api/sync-drive/versions/restore", json={
            "path": remote_path,
            "version_id": version_id,
        })

    # --- Browse ---

    def list_roots(self) -> dict:
        """List available root locations (home, disks, network mounts)."""
        return self._request("GET", "/api/sync-drive/roots")

    def browse(self, remote_path: str = "/") -> dict:
        """List directory contents for folder browsing in UI."""
        return self._request("GET", "/api/sync-drive/browse", params={
            "path": remote_path,
        })

    def close(self):
        """Close the HTTP client."""
        self._client.close()
