"""Automatic updates of Eden itself.

Flow (see docs/mises-a-jour.md):
    1. at start-up, at most once per ``interval_hours``, ask GitHub Releases
       for the latest published version (in a background thread);
    2. if it is newer, download the Windows installer and the release's
       SHA256SUMS.txt, and refuse the file if the checksum does not match;
    3. the verified installer is run when Eden closes (never during a mix or
       an export), silently, then Eden restarts on the new version.

Network access is injected (``http_get``) so the logic is testable offline.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from collections.abc import Callable

from packaging.version import InvalidVersion, Version

from eden import __version__
from eden.safety import eden_home

HttpGet = Callable[[str, dict[str, str]], bytes]

DEFAULT_REPO = "kimany91/eden"
INSTALLER_PATTERN = re.compile(r"^Eden[-_]Setup[-_].*\.exe$", re.I)
CHECKSUM_NAME = "SHA256SUMS.txt"


class UpdateError(RuntimeError):
    pass


class UpdateIntegrityError(UpdateError):
    """The downloaded file does not match the published checksum."""


@dataclass
class UpdateConfig:
    repo: str = DEFAULT_REPO
    enabled: bool = True
    interval_hours: float = 24.0
    api_base: str = "https://api.github.com"
    token: str | None = None  # only needed while the repository is private


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    installer_name: str | None
    installer_url: str | None
    checksum_url: str | None


def default_http_get(url: str, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(
                "Aucune version publiée trouvée (dépôt privé sans jeton d'accès, "
                "ou aucune release encore publiée)."
            ) from exc
        raise UpdateError(f"Serveur de mises à jour : erreur HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Pas de connexion au serveur de mises à jour ({exc})") from exc


def _headers(config: UpdateConfig, accept: str = "application/vnd.github+json") -> dict[str, str]:
    h = {"Accept": accept, "User-Agent": f"Eden/{__version__}"}
    if config.token:
        h["Authorization"] = f"Bearer {config.token}"
    return h


def parse_version(tag: str) -> Version | None:
    try:
        return Version(tag.lstrip("vV"))
    except InvalidVersion:
        return None


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, cur = parse_version(candidate), parse_version(current)
    return bool(new and cur and new > cur and not new.is_prerelease)


def fetch_latest_release(config: UpdateConfig, http_get: HttpGet = default_http_get) -> ReleaseInfo:
    url = f"{config.api_base}/repos/{config.repo}/releases/latest"
    try:
        payload = json.loads(http_get(url, _headers(config)))
    except json.JSONDecodeError as exc:
        raise UpdateError("Réponse du serveur de mises à jour illisible") from exc
    tag = payload.get("tag_name") or ""
    if parse_version(tag) is None:
        raise UpdateError(f"Numéro de version invalide dans la release : « {tag} »")
    installer = checksum = None
    for asset in payload.get("assets", []):
        name = asset.get("name", "")
        # The API URL (not browser_download_url) works for private repos with a token.
        asset_url = asset.get("url") or asset.get("browser_download_url")
        if INSTALLER_PATTERN.match(name):
            installer = (name, asset_url)
        elif name == CHECKSUM_NAME:
            checksum = asset_url
    return ReleaseInfo(
        version=str(parse_version(tag)),
        tag=tag,
        notes=payload.get("body") or "",
        installer_name=installer[0] if installer else None,
        installer_url=installer[1] if installer else None,
        checksum_url=checksum,
    )


def expected_checksum(sums_text: str, filename: str) -> str | None:
    for line in sums_text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == filename and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return None


def download_verified(
    release: ReleaseInfo,
    dest_dir: Path,
    config: UpdateConfig,
    http_get: HttpGet = default_http_get,
) -> Path:
    if not (release.installer_url and release.installer_name):
        raise UpdateError(f"La version {release.version} ne contient pas d'installateur Windows")
    if not release.checksum_url:
        raise UpdateError(f"La version {release.version} ne publie pas de {CHECKSUM_NAME} : refusée")
    octet = _headers(config, accept="application/octet-stream")
    sums = http_get(release.checksum_url, octet).decode("utf-8", errors="replace")
    expected = expected_checksum(sums, release.installer_name)
    if expected is None:
        raise UpdateError(f"Somme de contrôle absente pour {release.installer_name} : refusée")
    data = http_get(release.installer_url, octet)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise UpdateIntegrityError(
            f"Le fichier téléchargé est corrompu ou modifié (SHA-256 {actual[:12]}… "
            f"au lieu de {expected[:12]}…). Mise à jour annulée."
        )
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / release.installer_name
    tmp = target.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target


# -- scheduling ---------------------------------------------------------------

@dataclass
class UpdateState:
    last_check: float = 0.0
    pending_installer: str | None = None
    pending_version: str | None = None


def state_path() -> Path:
    return eden_home() / "updates" / "state.json"


def load_state(path: Path | None = None) -> UpdateState:
    path = path or state_path()
    try:
        return UpdateState(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return UpdateState()


def save_state(state: UpdateState, path: Path | None = None) -> None:
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state)), encoding="utf-8")


@dataclass
class CheckResult:
    status: str  # up_to_date | downloaded | skipped | error | available_no_installer
    message: str
    release: ReleaseInfo | None = None
    installer: Path | None = None


def check_and_download(
    config: UpdateConfig | None = None,
    http_get: HttpGet = default_http_get,
    force: bool = False,
    now: float | None = None,
    state_file: Path | None = None,
    installed: bool | None = None,
) -> CheckResult:
    """One automatic update cycle. Never raises: errors are returned as a status.

    ``installed`` tells whether Eden runs from its Windows installer (default:
    detected from PyInstaller's ``sys.frozen``); a source checkout is updated
    with git instead, so nothing is downloaded there.
    """
    if installed is None:
        installed = bool(getattr(sys, "frozen", False))
    config = config or UpdateConfig()
    if not config.enabled:
        return CheckResult("skipped", "Mises à jour automatiques désactivées")
    now = time.time() if now is None else now
    state = load_state(state_file)
    if not force and now - state.last_check < config.interval_hours * 3600:
        if state.pending_installer and Path(state.pending_installer).is_file():
            return CheckResult("downloaded", f"Version {state.pending_version} prête à installer",
                               installer=Path(state.pending_installer))
        return CheckResult("skipped", "Vérification déjà faite récemment")
    try:
        release = fetch_latest_release(config, http_get)
        state.last_check = now
        if not is_newer(release.version):
            save_state(state, state_file)
            return CheckResult("up_to_date", f"Eden {__version__} est à jour", release)
        if not installed:
            save_state(state, state_file)
            return CheckResult(
                "available_no_installer",
                f"Version {release.version} disponible (installation automatique uniquement "
                "pour la version installée d'Eden ; en développement, faites « git pull »)",
                release,
            )
        installer = download_verified(release, (state_file or state_path()).parent, config, http_get)
        state.pending_installer, state.pending_version = str(installer), release.version
        save_state(state, state_file)
        return CheckResult("downloaded", f"Version {release.version} téléchargée et vérifiée",
                           release, installer)
    except UpdateError as exc:
        save_state(state, state_file)
        return CheckResult("error", str(exc))


def installer_command(installer: Path) -> list[str]:
    """Silent Inno Setup install that closes Eden and restarts it afterwards."""
    return [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"]


def launch_pending_install(
    state_file: Path | None = None, popen=subprocess.Popen, is_windows: bool | None = None
) -> bool:
    """Called when Eden exits. Returns True if an installer was started."""
    if is_windows is None:
        is_windows = os.name == "nt"
    state = load_state(state_file)
    if not state.pending_installer or not is_windows:
        return False
    installer = Path(state.pending_installer)
    if not installer.is_file():
        return False
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    popen(installer_command(installer), creationflags=flags, close_fds=True)
    state.pending_installer = state.pending_version = None
    save_state(state, state_file)
    return True
