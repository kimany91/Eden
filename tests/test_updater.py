import hashlib
import json

import pytest

from eden.updater import (
    UpdateConfig,
    UpdateError,
    UpdateIntegrityError,
    check_and_download,
    download_verified,
    expected_checksum,
    fetch_latest_release,
    installer_command,
    is_newer,
    launch_pending_install,
    load_state,
)

from packaging.version import Version

from eden import __version__

_cur = Version(__version__)
NEXT = f"{_cur.major}.{_cur.minor + 1}.0"  # a release newer than the running Eden
INSTALLER = b"MZ fake installer bytes"
API = "https://api.github.com/repos/kimany91/eden/releases/latest"
T0 = 1_800_000_000.0  # a realistic "now" (epoch seconds)


def fake_server(tag=f"v{NEXT}", installer=INSTALLER, published_sum=None, with_sums=True):
    digest = published_sum or hashlib.sha256(installer).hexdigest()
    assets = [{"name": f"Eden-Setup-{NEXT}.exe", "url": "https://x/asset/1"}]
    if with_sums:
        assets.append({"name": "SHA256SUMS.txt", "url": "https://x/asset/2"})
    routes = {
        API: json.dumps({"tag_name": tag, "body": "Notes", "assets": assets}).encode(),
        "https://x/asset/1": installer,
        "https://x/asset/2": f"{digest} *Eden-Setup-{NEXT}.exe\n".encode(),
    }
    calls = []

    def get(url, headers):
        calls.append((url, headers))
        if url not in routes:
            raise UpdateError("404")
        return routes[url]

    get.calls = calls
    return get


def test_version_comparison():
    assert is_newer("0.2.0", "0.1.0")
    assert is_newer("1.0.0", "0.9.9")
    assert not is_newer("0.1.0", "0.1.0")
    assert not is_newer("0.0.9", "0.1.0")
    assert not is_newer("0.3.0rc1", "0.1.0")  # pre-releases are never auto-installed
    assert not is_newer("pas-une-version", "0.1.0")


def test_fetch_latest_release_and_token():
    get = fake_server()
    rel = fetch_latest_release(UpdateConfig(token="secret"), get)
    assert rel.version == NEXT
    assert rel.installer_name == f"Eden-Setup-{NEXT}.exe"
    assert get.calls[0][1]["Authorization"] == "Bearer secret"


def test_checksum_parsing():
    h = "a" * 64
    assert expected_checksum(f"{h}  Eden-Setup-1.exe\n", "Eden-Setup-1.exe") == h
    assert expected_checksum(f"{h} *Eden-Setup-1.exe", "Eden-Setup-1.exe") == h
    assert expected_checksum(f"{h}  autre.exe", "Eden-Setup-1.exe") is None


def test_download_is_verified(tmp_path):
    rel = fetch_latest_release(UpdateConfig(), fake_server())
    path = download_verified(rel, tmp_path, UpdateConfig(), fake_server())
    assert path.read_bytes() == INSTALLER


def test_tampered_download_is_rejected(tmp_path):
    get = fake_server(published_sum="0" * 64)
    rel = fetch_latest_release(UpdateConfig(), get)
    with pytest.raises(UpdateIntegrityError):
        download_verified(rel, tmp_path, UpdateConfig(), get)
    assert not list(tmp_path.iterdir())  # nothing kept on disk


def test_release_without_checksums_is_refused(tmp_path):
    get = fake_server(with_sums=False)
    rel = fetch_latest_release(UpdateConfig(), get)
    with pytest.raises(UpdateError, match="SHA256SUMS"):
        download_verified(rel, tmp_path, UpdateConfig(), get)


def test_cycle_installed_app_downloads_once_then_throttles(tmp_path):
    state = tmp_path / "state.json"
    get = fake_server()
    r = check_and_download(UpdateConfig(), get, now=T0, state_file=state, installed=True)
    assert r.status == "downloaded" and r.installer.read_bytes() == INSTALLER
    assert load_state(state).pending_version == NEXT
    n_calls = len(get.calls)
    r2 = check_and_download(UpdateConfig(), get, now=T0 + 3600, state_file=state, installed=True)
    assert r2.status == "downloaded" and len(get.calls) == n_calls  # no new network call


def test_cycle_source_checkout_only_notifies(tmp_path):
    state = tmp_path / "state.json"
    r = check_and_download(UpdateConfig(), fake_server(), now=T0, state_file=state, installed=False)
    assert r.status == "available_no_installer"
    assert not (tmp_path / f"Eden-Setup-{NEXT}.exe").exists()


def test_cycle_up_to_date_and_errors_never_raise(tmp_path):
    state = tmp_path / "state.json"
    r = check_and_download(UpdateConfig(), fake_server(tag=f"v{__version__}"), now=T0, state_file=state)
    assert r.status == "up_to_date"

    def offline(url, headers):
        raise UpdateError("Pas de connexion")

    r = check_and_download(UpdateConfig(), offline, force=True, state_file=state)
    assert r.status == "error"
    assert check_and_download(UpdateConfig(enabled=False), offline).status == "skipped"


def test_pending_install_is_launched_silently(tmp_path):
    state = tmp_path / "state.json"
    check_and_download(UpdateConfig(), fake_server(), now=T0, state_file=state, installed=True)
    launched = []
    assert not launch_pending_install(state, popen=lambda *a, **k: None, is_windows=False)
    assert launch_pending_install(state, popen=lambda cmd, **kw: launched.append(cmd), is_windows=True)
    assert launched[0][1:3] == ["/VERYSILENT", "/SUPPRESSMSGBOXES"]
    assert load_state(state).pending_installer is None
    assert not launch_pending_install(state, popen=lambda *a, **k: None, is_windows=True)
    assert installer_command(tmp_path / "x.exe")[0].endswith("x.exe")
