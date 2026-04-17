"""Core two-way sync engine — the brain of EthOS Drive.

Compares local and remote file states, detects changes on both sides,
resolves conflicts, and orchestrates file transfers.
"""

import logging
import os
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ethos_drive.config import SyncTask
from ethos_drive.api.client import EthosAPIClient, APIError
from ethos_drive.sync.state import SyncStateDB
from ethos_drive.sync.scanner import DirectoryScanner, FileEntry
from ethos_drive.sync.filters import FilterEngine
from ethos_drive.sync.conflict import detect_conflict, resolve_conflict, ConflictInfo
from ethos_drive.sync.versioning import VersionTracker
from ethos_drive.sync.transfer import TransferManager
from ethos_drive.utils.crypto import content_fingerprint
from ethos_drive.utils.paths import remote_to_local, local_to_remote

log = logging.getLogger(__name__)


class SyncAction:
    """A planned sync action."""

    UPLOAD = "upload"
    DOWNLOAD = "download"
    DELETE_LOCAL = "delete_local"
    DELETE_REMOTE = "delete_remote"
    MOVE_REMOTE = "move_remote"
    MOVE_LOCAL = "move_local"
    MKDIR_LOCAL = "mkdir_local"
    MKDIR_REMOTE = "mkdir_remote"
    CONFLICT = "conflict"
    SKIP = "skip"

    def __init__(self, action: str, path: str, **kwargs):
        self.action = action
        self.path = path
        self.details = kwargs

    def __repr__(self):
        return f"SyncAction({self.action}, {self.path})"


class SyncEngine(QObject):
    """Two-way sync engine for a single sync task.

    Algorithm:
    1. Scan local directory tree
    2. Fetch remote state from server
    3. Compare both against last-known synced state (from local DB)
    4. Classify each file: upload, download, delete, conflict, skip
    5. Resolve conflicts per configured strategy
    6. Execute planned actions (transfers, deletes, mkdirs)
    7. Update local state DB
    """

    progress = Signal(dict)       # {file, action, percent, speed}
    conflict = Signal(dict)       # {path, local_fp, remote_fp}
    completed = Signal(dict)      # {uploaded, downloaded, deleted, conflicts, errors}

    def __init__(self, task: SyncTask, api_client: EthosAPIClient,
                 state_db: SyncStateDB, watcher=None,
                 max_concurrent: int = 3):
        super().__init__()
        self.task = task
        self.api = api_client
        self.db = state_db
        self.watcher = watcher
        self._cancelled = False

        self.filter_engine = FilterEngine(
            rules=task.filters,
            sync_hidden=task.sync_hidden,
            syncignore_path=os.path.join(task.local_path, ".syncignore"),
        )
        self.version_tracker = VersionTracker(state_db, task.id)
        self.transfer_mgr = TransferManager(
            api_client=api_client,
            max_concurrent=max_concurrent,
            max_upload_kbps=task.max_upload_kbps,
            max_download_kbps=task.max_download_kbps,
        )
        self.transfer_mgr.progress_updated.connect(self._on_transfer_progress)

    def _on_transfer_progress(self, info: dict):
        """Forward TransferManager progress to engine signal."""
        self.progress.emit({
            "phase": "syncing",
            "file": info.get("path", ""),
            "action": info.get("direction", "transfer"),
            "percent": info.get("percent", 0),
            "speed": info.get("speed_bps", 0),
            "eta": info.get("eta_seconds", 0),
            "transferred": info.get("transferred", 0),
            "total": info.get("total", 0),
        })

    def _make_progress_cb(self, path: str, direction: str):
        """Create progress callback for direct API upload/download calls."""
        from .transfer import TransferProgress
        prog = TransferProgress(path, 0, direction)
        with self.transfer_mgr._lock:
            self.transfer_mgr._active[path] = prog

        def cb(transferred, total):
            prog.transferred_bytes = transferred
            prog.total_bytes = total
            prog._record_sample()
            self.progress.emit({
                "phase": "syncing",
                "file": path,
                "action": direction,
                "percent": round(prog.percent, 1),
                "speed": int(prog.speed_bps),
                "eta": int(prog.eta_seconds),
                "transferred": transferred,
                "total": total,
            })

        def cleanup():
            with self.transfer_mgr._lock:
                self.transfer_mgr._active.pop(path, None)

        return cb, cleanup

    def full_sync(self):
        """Perform a complete two-way sync."""
        if self._cancelled:
            return

        log.info("Full sync starting: %s", self.task.name)
        start = time.time()
        stats = {"uploaded": 0, "downloaded": 0, "deleted": 0, "conflicts": 0, "errors": 0}

        try:
            # Step 1: Scan local
            self.progress.emit({"phase": "scanning", "file": "Scanning local files...",
                                "action": "scan", "percent": 0, "speed": 0})
            scanner = DirectoryScanner(
                root=self.task.local_path,
                filters=self.task.filters,
                sync_hidden=self.task.sync_hidden,
                selective_paths=self.task.selective_paths,
            )
            local_files = scanner.scan(compute_hashes=True)

            # Step 2: Fetch remote state
            self.progress.emit({"phase": "scanning", "file": "Fetching remote state...",
                                "action": "scan", "percent": 25, "speed": 0})
            try:
                log.info("Requesting remote state for: %s", self.task.remote_path)
                remote_data = self.api.get_remote_state(self.task.remote_path)
                remote_files = {f["path"]: f for f in remote_data.get("files", [])}
                log.info("Remote state: %d files", len(remote_files))
            except APIError as e:
                log.error("Cannot fetch remote state: %s", e)
                self.progress.emit({"phase": "error", "file": f"Error: {e}",
                                    "action": "error", "percent": 0, "speed": 0})
                stats["errors"] += 1
                return stats
            except Exception as e:
                log.error("Unexpected error fetching remote state: %s", e, exc_info=True)
                self.progress.emit({"phase": "error", "file": f"Connection error: {e}",
                                    "action": "error", "percent": 0, "speed": 0})
                stats["errors"] += 1
                return stats

            # Step 3: Load last synced state from DB
            synced_state = {f["path"]: f for f in self.db.get_all_files(self.task.id)}

            # Step 4: Plan actions
            self.progress.emit({"phase": "planning", "file": "Comparing files...",
                                "action": "plan", "percent": 50, "speed": 0})
            actions = self._plan_sync(local_files, remote_files, synced_state)

            # Step 5: Execute actions — transfers run concurrently
            total_actions = len(actions)
            self.progress.emit({"phase": "syncing",
                                "file": f"Syncing {total_actions} items...",
                                "action": "sync", "percent": 0, "speed": 0,
                                "total": total_actions, "done": 0})

            # Split: sequential ops first, then batch transfers
            sequential = []
            transfers = []
            for action in actions:
                if action.action in (SyncAction.UPLOAD, SyncAction.DOWNLOAD):
                    transfers.append(action)
                else:
                    sequential.append(action)

            done_count = [0]
            stats_lock = threading.Lock()

            def _emit_progress(action):
                done_count[0] += 1
                pct = (done_count[0] / total_actions * 100) if total_actions else 100
                self.progress.emit({
                    "phase": "syncing", "file": action.path,
                    "action": action.action, "percent": round(pct, 1),
                    "speed": 0, "total": total_actions, "done": done_count[0],
                })

            # Run mkdir/delete/move/conflict actions sequentially
            for action in sequential:
                if self._cancelled:
                    break
                try:
                    self._execute_action(action, stats)
                except Exception as e:
                    log.error("Action failed %s: %s", action, e)
                    stats["errors"] += 1
                    self.db.log_action(self.task.id, action.action, action.path,
                                       detail=str(e), success=False)
                _emit_progress(action)

            # Run uploads/downloads concurrently via thread pool
            if transfers and not self._cancelled:
                from concurrent.futures import ThreadPoolExecutor, as_completed

                def _run_transfer(action):
                    local_stats = {"uploaded": 0, "downloaded": 0, "errors": 0}
                    if self._cancelled:
                        return action, local_stats
                    try:
                        self._execute_action(action, local_stats)
                    except Exception as e:
                        log.error("Transfer failed %s: %s", action, e)
                        local_stats["errors"] += 1
                        self.db.log_action(self.task.id, action.action, action.path,
                                           detail=str(e), success=False)
                    return action, local_stats

                max_workers = self.transfer_mgr.max_concurrent
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {pool.submit(_run_transfer, a): a for a in transfers}
                    for future in as_completed(futures):
                        if self._cancelled:
                            break
                        action, local_stats = future.result()
                        with stats_lock:
                            stats["uploaded"] += local_stats["uploaded"]
                            stats["downloaded"] += local_stats["downloaded"]
                            stats["errors"] += local_stats["errors"]
                        _emit_progress(action)

            # Update task state
            elapsed = time.time() - start
            self.db.update_task_state(self.task.id,
                                      last_full_sync=time.time(),
                                      files_synced=stats["uploaded"] + stats["downloaded"])

            log.info("Sync complete: %s (%.1fs) — up:%d down:%d del:%d conflicts:%d errors:%d",
                     self.task.name, elapsed,
                     stats["uploaded"], stats["downloaded"], stats["deleted"],
                     stats["conflicts"], stats["errors"])

        except Exception as e:
            log.error("Full sync failed: %s", e)
            stats["errors"] += 1

        self.completed.emit(stats)
        return stats

    def _plan_sync(self, local_files: dict[str, FileEntry],
                   remote_files: dict[str, dict],
                   synced_state: dict[str, dict]) -> list[SyncAction]:
        """Compare local, remote, and synced state to plan sync actions."""
        actions = []
        all_paths = set()
        all_paths.update(local_files.keys())
        all_paths.update(remote_files.keys())
        all_paths.update(synced_state.keys())

        # Build hash→path maps for move detection during full sync.
        # A move looks like: synced path A gone locally + new local path B with same hash.
        local_only_by_hash: dict[str, str] = {}   # xxhash -> path (new local files)
        gone_local_by_hash: dict[str, str] = {}    # xxhash -> path (deleted local, still on remote)
        moved_pairs: dict[str, str] = {}            # new_path -> old_path

        for path in sorted(all_paths):
            local = local_files.get(path)
            remote = remote_files.get(path)
            synced = synced_state.get(path)
            has_local = local is not None
            has_remote = remote is not None
            was_synced = synced is not None

            # New local file (not on server, never synced) — candidate move target
            if has_local and not has_remote and not was_synced:
                if not local.is_dir and local.xxhash:
                    local_only_by_hash[local.xxhash] = path

            # Locally deleted, still on server, was synced — candidate move source
            if not has_local and has_remote and was_synced:
                h = synced.get("local_xxhash", "")
                if h:
                    gone_local_by_hash[h] = path

        # Match moves: same xxhash in both sets
        for h, new_path in local_only_by_hash.items():
            old_path = gone_local_by_hash.get(h)
            if old_path:
                moved_pairs[new_path] = old_path

        # Paths handled by moves (skip in normal classification)
        move_handled = set()
        for new_p, old_p in moved_pairs.items():
            move_handled.add(new_p)
            move_handled.add(old_p)
            actions.append(SyncAction(SyncAction.MOVE_REMOTE, new_p, src_path=old_p))

        for path in sorted(all_paths):
            if path in move_handled:
                continue
            if self.filter_engine.should_exclude(path):
                continue

            local = local_files.get(path)
            remote = remote_files.get(path)
            synced = synced_state.get(path)

            action = self._classify_file(path, local, remote, synced)
            if action:
                actions.append(action)

        # Sort: directories first, then moves, then files, deletes last
        def sort_key(a):
            if a.action in (SyncAction.MKDIR_LOCAL, SyncAction.MKDIR_REMOTE):
                return (0, a.path)
            if a.action in (SyncAction.MOVE_REMOTE, SyncAction.MOVE_LOCAL):
                return (1, a.path)
            if a.action in (SyncAction.DELETE_LOCAL, SyncAction.DELETE_REMOTE):
                return (3, a.path)
            return (2, a.path)

        actions.sort(key=sort_key)
        return actions

    def _classify_file(self, path: str,
                       local: Optional[FileEntry],
                       remote: Optional[dict],
                       synced: Optional[dict]) -> Optional[SyncAction]:
        """Classify what action is needed for a single file."""
        has_local = local is not None
        has_remote = remote is not None
        was_synced = synced is not None

        # Both exist — check for changes
        if has_local and has_remote:
            if local.is_dir or remote.get("is_dir"):
                return None  # Directories just need to exist

            local_fp = {"size": local.size, "mtime_ns": local.mtime_ns, "xxhash": local.xxhash}
            remote_fp = {
                "size": remote.get("size", 0),
                "mtime_ns": remote.get("mtime_ns", 0),
                "xxhash": remote.get("xxhash", ""),
            }

            # If fingerprints match, already in sync
            if local_fp.get("xxhash") and local_fp["xxhash"] == remote_fp.get("xxhash"):
                if not was_synced:
                    self.db.mark_synced(self.task.id, path, **{
                        "local_size": local_fp["size"],
                        "local_mtime_ns": local_fp["mtime_ns"],
                        "local_xxhash": local_fp["xxhash"],
                        "remote_size": remote_fp["size"],
                        "remote_mtime_ns": remote_fp["mtime_ns"],
                        "remote_xxhash": remote_fp["xxhash"],
                    })
                return None

            # Check for conflict (both sides changed)
            if was_synced:
                conflict_info = detect_conflict(path, local_fp, remote_fp, synced)
                if conflict_info:
                    return SyncAction(SyncAction.CONFLICT, path,
                                      conflict=conflict_info,
                                      local_fp=local_fp, remote_fp=remote_fp)

            # One side changed — determine which
            if was_synced:
                local_changed = (
                    local_fp.get("xxhash") != synced.get("local_xxhash")
                )
                remote_changed = (
                    remote_fp.get("xxhash") != synced.get("remote_xxhash")
                )

                if local_changed and not remote_changed:
                    if self.task.direction != "download_only":
                        return SyncAction(SyncAction.UPLOAD, path, local_fp=local_fp)
                elif remote_changed and not local_changed:
                    if self.task.direction != "upload_only":
                        return SyncAction(SyncAction.DOWNLOAD, path, remote_fp=remote_fp)
            else:
                # First sync — remote is source of truth
                if self.task.direction != "upload_only":
                    return SyncAction(SyncAction.DOWNLOAD, path, remote_fp=remote_fp)

        # Only local — upload to server
        elif has_local and not has_remote:
            if was_synced:
                # Was synced before, now gone from server = remote deleted
                if self.task.direction != "upload_only":
                    return SyncAction(SyncAction.DELETE_LOCAL, path)
            else:
                # New local file
                if self.task.direction != "download_only":
                    if local.is_dir:
                        return SyncAction(SyncAction.MKDIR_REMOTE, path)
                    return SyncAction(SyncAction.UPLOAD, path,
                                      local_fp={"size": local.size, "mtime_ns": local.mtime_ns,
                                                 "xxhash": local.xxhash})

        # Only remote — download from server
        elif not has_local and has_remote:
            if was_synced:
                # Was synced before, now gone locally = local deleted
                if self.task.direction != "download_only":
                    return SyncAction(SyncAction.DELETE_REMOTE, path)
            else:
                # New remote file
                if self.task.direction != "upload_only":
                    if remote.get("is_dir"):
                        return SyncAction(SyncAction.MKDIR_LOCAL, path)
                    return SyncAction(SyncAction.DOWNLOAD, path,
                                      remote_fp=remote)

        # Was synced but now gone from both sides
        elif not has_local and not has_remote and was_synced:
            self.db.mark_deleted(self.task.id, path)

        return None

    def _execute_action(self, action: SyncAction, stats: dict):
        """Execute a single sync action."""
        path = action.path
        local_abs = remote_to_local(path, self.task.local_path)

        if action.action == SyncAction.UPLOAD:
            log.info("Uploading: %s", path)
            remote_path = os.path.join(self.task.remote_path, path).replace("\\", "/")

            # Record version before overwriting
            existing = self.db.get_file(self.task.id, path)
            if existing and existing.get("remote_xxhash"):
                self.version_tracker.record_version(
                    path, existing["remote_size"],
                    existing["remote_xxhash"], existing["remote_mtime_ns"],
                )

            progress_cb, cleanup = self._make_progress_cb(path, "upload")
            t0 = time.time()
            try:
                resp = self.api.upload_file(local_abs, remote_path,
                                            progress_callback=progress_cb)
            finally:
                cleanup()

            local_fp = content_fingerprint(local_abs)
            file_size = local_fp["size"] if local_fp else 0
            if local_fp:
                # Use server-returned xxhash for remote state (content is same)
                remote_xxhash = resp.get("xxhash", local_fp["xxhash"]) if isinstance(resp, dict) else local_fp["xxhash"]
                self.db.mark_synced(self.task.id, path,
                                    local_size=local_fp["size"],
                                    local_mtime_ns=local_fp["mtime_ns"],
                                    local_xxhash=local_fp["xxhash"],
                                    remote_size=local_fp["size"],
                                    remote_mtime_ns=local_fp["mtime_ns"],
                                    remote_xxhash=remote_xxhash)
            self.db.log_action(self.task.id, "upload", path,
                               bytes_transferred=file_size,
                               duration_ms=int((time.time() - t0) * 1000))
            stats["uploaded"] += 1

        elif action.action == SyncAction.DOWNLOAD:
            log.info("Downloading: %s", path)
            remote_path = os.path.join(self.task.remote_path, path).replace("\\", "/")

            # Suppress file watcher to prevent re-upload loop
            if self.watcher:
                self.watcher.suppress(local_abs, duration=10.0)

            # Record version of local file before overwriting
            if os.path.exists(local_abs):
                fp = content_fingerprint(local_abs)
                if fp:
                    self.version_tracker.record_version(
                        path, fp["size"], fp["xxhash"], fp["mtime_ns"],
                    )

            progress_cb, cleanup = self._make_progress_cb(path, "download")
            t0 = time.time()
            try:
                self.api.download_file(remote_path, local_abs,
                                       progress_callback=progress_cb)
            finally:
                cleanup()

            fp = content_fingerprint(local_abs)
            remote_fp = action.details.get("remote_fp", {})
            file_size = fp["size"] if fp else 0
            if fp:
                self.db.mark_synced(self.task.id, path,
                                    local_size=fp["size"],
                                    local_mtime_ns=fp["mtime_ns"],
                                    local_xxhash=fp["xxhash"],
                                    remote_size=remote_fp.get("size", fp["size"]),
                                    remote_mtime_ns=remote_fp.get("mtime_ns", fp["mtime_ns"]),
                                    remote_xxhash=remote_fp.get("xxhash", fp["xxhash"]))
            self.db.log_action(self.task.id, "download", path,
                               bytes_transferred=file_size,
                               duration_ms=int((time.time() - t0) * 1000))
            stats["downloaded"] += 1

        elif action.action == SyncAction.DELETE_LOCAL:
            log.info("Deleting local: %s", path)
            if os.path.isdir(local_abs):
                import shutil
                shutil.rmtree(local_abs, ignore_errors=True)
            elif os.path.exists(local_abs):
                os.unlink(local_abs)
            self.db.mark_deleted(self.task.id, path)
            self.db.log_action(self.task.id, "delete_local", path)
            stats["deleted"] += 1

        elif action.action == SyncAction.DELETE_REMOTE:
            log.info("Deleting remote: %s", path)
            remote_path = os.path.join(self.task.remote_path, path).replace("\\", "/")
            self.api.delete_remote(remote_path)
            self.db.mark_deleted(self.task.id, path)
            self.db.log_action(self.task.id, "delete_remote", path)
            stats["deleted"] += 1

        elif action.action == SyncAction.MOVE_REMOTE:
            src_path = action.details.get("src_path", "")
            log.info("Moving remote: %s -> %s", src_path, path)
            remote_src = os.path.join(self.task.remote_path, src_path).replace("\\", "/")
            remote_dst = os.path.join(self.task.remote_path, path).replace("\\", "/")

            try:
                self.api.move_remote(remote_src, remote_dst)
            except APIError:
                log.warning("Server move failed, falling back to upload: %s -> %s", src_path, path)
                try:
                    self.api.delete_remote(remote_src)
                except APIError:
                    pass
                if os.path.isfile(local_abs):
                    self.api.upload_file(local_abs, remote_dst)

            self.db.mark_deleted(self.task.id, src_path)
            fp = content_fingerprint(local_abs)
            if fp:
                self.db.mark_synced(self.task.id, path,
                                    local_size=fp["size"],
                                    local_mtime_ns=fp["mtime_ns"],
                                    local_xxhash=fp["xxhash"],
                                    remote_size=fp["size"],
                                    remote_mtime_ns=fp["mtime_ns"],
                                    remote_xxhash=fp["xxhash"])
            self.db.log_action(self.task.id, "move_remote", path, detail=f"from {src_path}")

        elif action.action == SyncAction.MOVE_LOCAL:
            src_path = action.details.get("src_path", "")
            src_abs = remote_to_local(src_path, self.task.local_path)
            log.info("Moving local: %s -> %s", src_path, path)
            if os.path.exists(src_abs):
                os.makedirs(os.path.dirname(local_abs), exist_ok=True)
                if self.watcher:
                    self.watcher.suppress(src_abs, duration=10.0)
                    self.watcher.suppress(local_abs, duration=10.0)
                os.rename(src_abs, local_abs)
            self.db.mark_deleted(self.task.id, src_path)
            fp = content_fingerprint(local_abs)
            if fp:
                self.db.mark_synced(self.task.id, path,
                                    local_size=fp["size"],
                                    local_mtime_ns=fp["mtime_ns"],
                                    local_xxhash=fp["xxhash"],
                                    remote_size=fp["size"],
                                    remote_mtime_ns=fp["mtime_ns"],
                                    remote_xxhash=fp["xxhash"])
            self.db.log_action(self.task.id, "move_local", path, detail=f"from {src_path}")

        elif action.action == SyncAction.MKDIR_LOCAL:
            os.makedirs(local_abs, exist_ok=True)
            self.db.upsert_file(self.task.id, path, is_dir=1, status="synced")

        elif action.action == SyncAction.MKDIR_REMOTE:
            remote_path = os.path.join(self.task.remote_path, path).replace("\\", "/")
            self.api.create_remote_dir(remote_path)
            self.db.upsert_file(self.task.id, path, is_dir=1, status="synced")

        elif action.action == SyncAction.CONFLICT:
            conflict_info = action.details.get("conflict")
            resolution = resolve_conflict(
                conflict_info, self.task.conflict_strategy, self.task.local_path
            )

            if resolution["action"] == "ask":
                self.conflict.emit({
                    "path": path,
                    "local_fp": action.details.get("local_fp"),
                    "remote_fp": action.details.get("remote_fp"),
                })
                self.db.add_conflict(self.task.id, path,
                                     action.details.get("local_fp", {}),
                                     action.details.get("remote_fp", {}))
                stats["conflicts"] += 1
            elif resolution["action"] == "upload":
                new_action = SyncAction(SyncAction.UPLOAD, path,
                                        local_fp=action.details.get("local_fp"))
                self._execute_action(new_action, stats)
            elif resolution["action"] == "download":
                new_action = SyncAction(SyncAction.DOWNLOAD, path,
                                        remote_fp=action.details.get("remote_fp"))
                self._execute_action(new_action, stats)
            elif resolution["action"] == "skip":
                log.info("Skipping conflicted file: %s", path)
                stats["conflicts"] += 1

    def process_local_changes(self, changes: list[dict]):
        """Process incremental local changes from the file watcher."""
        if self.task.direction == "download_only":
            return

        for change in changes:
            if self._cancelled:
                break
            path = change["path"]
            action = change["action"]

            if self.filter_engine.should_exclude(path):
                continue

            try:
                if action == "moved":
                    src_path = change.get("src_path", "")
                    dst_path = path
                    abs_path = change.get("abs_path", remote_to_local(dst_path, self.task.local_path))

                    remote_src = os.path.join(self.task.remote_path, src_path).replace("\\", "/")
                    remote_dst = os.path.join(self.task.remote_path, dst_path).replace("\\", "/")

                    try:
                        self.api.move_remote(remote_src, remote_dst)
                    except APIError:
                        # Server move failed — fall back to delete + upload
                        log.warning("Server-side move failed, falling back to upload: %s -> %s", src_path, dst_path)
                        self.api.delete_remote(remote_src)
                        if os.path.isfile(abs_path):
                            self.api.upload_file(abs_path, remote_dst)

                    # Update state DB: remove old path, add new
                    self.db.mark_deleted(self.task.id, src_path)
                    if os.path.isfile(abs_path):
                        fp = content_fingerprint(abs_path)
                        if fp:
                            self.db.mark_synced(self.task.id, dst_path,
                                                local_size=fp["size"],
                                                local_mtime_ns=fp["mtime_ns"],
                                                local_xxhash=fp["xxhash"],
                                                remote_size=fp["size"],
                                                remote_mtime_ns=fp["mtime_ns"],
                                                remote_xxhash=fp["xxhash"])
                    elif os.path.isdir(abs_path):
                        self.db.upsert_file(self.task.id, dst_path, is_dir=1, status="synced")
                        # For directory moves, update all children paths in state DB
                        self._update_children_paths(src_path, dst_path)

                    self.db.log_action(self.task.id, "move_remote", dst_path,
                                       detail=f"from {src_path}")

                elif action in ("created", "modified"):
                    abs_path = change.get("abs_path", remote_to_local(path, self.task.local_path))
                    if os.path.isfile(abs_path):
                        remote_path = os.path.join(self.task.remote_path, path).replace("\\", "/")
                        resp = self.api.upload_file(abs_path, remote_path)
                        fp = content_fingerprint(abs_path)
                        if fp:
                            remote_xxhash = resp.get("xxhash", fp["xxhash"]) if isinstance(resp, dict) else fp["xxhash"]
                            self.db.mark_synced(self.task.id, path,
                                                local_size=fp["size"],
                                                local_mtime_ns=fp["mtime_ns"],
                                                local_xxhash=fp["xxhash"],
                                                remote_size=fp["size"],
                                                remote_mtime_ns=fp["mtime_ns"],
                                                remote_xxhash=remote_xxhash)
                        self.db.log_action(self.task.id, "upload", path)

                elif action == "deleted":
                    remote_path = os.path.join(self.task.remote_path, path).replace("\\", "/")
                    self.api.delete_remote(remote_path)
                    self.db.mark_deleted(self.task.id, path)
                    self.db.log_action(self.task.id, "delete_remote", path)

            except Exception as e:
                log.error("Failed to sync local change %s %s: %s", action, path, e)
                self.db.log_action(self.task.id, action, path, detail=str(e), success=False)

    def process_remote_changes(self, changes: list[dict]):
        """Process remote change notifications from SocketIO."""
        if self.task.direction == "upload_only":
            return

        for change in changes:
            if self._cancelled:
                break
            path = change.get("path", "")
            action = change.get("action", "")

            # Make path relative to task remote root
            if path.startswith(self.task.remote_path):
                path = os.path.relpath(path, self.task.remote_path).replace("\\", "/")

            if self.filter_engine.should_exclude(path):
                continue

            local_abs = remote_to_local(path, self.task.local_path)

            try:
                if action == "moved":
                    # Server-side move — replicate locally
                    src_rel = change.get("src_path", "")
                    if src_rel.startswith(self.task.remote_path):
                        src_rel = os.path.relpath(src_rel, self.task.remote_path).replace("\\", "/")
                    src_abs = remote_to_local(src_rel, self.task.local_path)
                    if os.path.exists(src_abs):
                        os.makedirs(os.path.dirname(local_abs), exist_ok=True)
                        if self.watcher:
                            self.watcher.suppress(src_abs, duration=10.0)
                            self.watcher.suppress(local_abs, duration=10.0)
                        os.rename(src_abs, local_abs)
                    self.db.mark_deleted(self.task.id, src_rel)
                    fp = content_fingerprint(local_abs) if os.path.isfile(local_abs) else None
                    if fp:
                        self.db.mark_synced(self.task.id, path,
                                            local_size=fp["size"],
                                            local_mtime_ns=fp["mtime_ns"],
                                            local_xxhash=fp["xxhash"],
                                            remote_size=change.get("size", fp["size"]),
                                            remote_mtime_ns=change.get("mtime_ns", fp["mtime_ns"]),
                                            remote_xxhash=change.get("xxhash", fp["xxhash"]))
                    self.db.log_action(self.task.id, "move_local", path, detail=f"from {src_rel}")

                elif action in ("created", "modified"):
                    remote_full = os.path.join(self.task.remote_path, path).replace("\\", "/")
                    # Suppress watcher to prevent re-upload loop
                    if self.watcher:
                        self.watcher.suppress(local_abs, duration=10.0)
                    self.api.download_file(remote_full, local_abs)
                    fp = content_fingerprint(local_abs)
                    if fp:
                        self.db.mark_synced(self.task.id, path,
                                            local_size=fp["size"],
                                            local_mtime_ns=fp["mtime_ns"],
                                            local_xxhash=fp["xxhash"],
                                            remote_size=change.get("size", fp["size"]),
                                            remote_mtime_ns=change.get("mtime_ns", fp["mtime_ns"]),
                                            remote_xxhash=change.get("xxhash", fp["xxhash"]))
                    self.db.log_action(self.task.id, "download", path)

                elif action == "deleted":
                    if os.path.exists(local_abs):
                        if os.path.isdir(local_abs):
                            import shutil
                            shutil.rmtree(local_abs, ignore_errors=True)
                        else:
                            os.unlink(local_abs)
                    self.db.mark_deleted(self.task.id, path)
                    self.db.log_action(self.task.id, "delete_local", path)

            except Exception as e:
                log.error("Failed to process remote change %s %s: %s", action, path, e)

    def cancel(self):
        """Cancel ongoing sync."""
        self._cancelled = True
        self.transfer_mgr.cancel_all()

    def _update_children_paths(self, old_parent: str, new_parent: str):
        """After a directory move, update all child paths in the state DB."""
        all_files = self.db.get_all_files(self.task.id)
        old_prefix = old_parent.rstrip("/") + "/"
        for f in all_files:
            if f["path"].startswith(old_prefix):
                old_child = f["path"]
                new_child = new_parent.rstrip("/") + "/" + old_child[len(old_prefix):]
                self.db.mark_deleted(self.task.id, old_child)
                self.db.upsert_file(
                    self.task.id, new_child,
                    is_dir=f.get("is_dir", 0),
                    local_size=f.get("local_size"),
                    local_mtime_ns=f.get("local_mtime_ns"),
                    local_xxhash=f.get("local_xxhash"),
                    remote_size=f.get("remote_size"),
                    remote_mtime_ns=f.get("remote_mtime_ns"),
                    remote_xxhash=f.get("remote_xxhash"),
                    status="synced",
                )
