from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_REPOSITORY: Final = "Lioheart/Sesyjka"
API_VERSION: Final = "2022-11-28"
USER_AGENT: Final = "Sesyjka-update-checker"
SUPPORTED_CHANNELS: Final = {"deb", "rpm", "generic", "local"}


class UpdateError(RuntimeError):
    """Błąd sprawdzania, pobierania lub instalowania aktualizacji."""


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    url: str
    size: int = 0
    digest: str = ""


@dataclass(frozen=True, slots=True)
class LatestRelease:
    version: str
    tag_name: str
    html_url: str
    body: str
    assets: tuple[ReleaseAsset, ...]


def repository_name() -> str:
    value = os.environ.get("SESYJKA_UPDATE_REPOSITORY", DEFAULT_REPOSITORY).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        return DEFAULT_REPOSITORY
    return value


def release_page_url() -> str:
    return f"https://github.com/{repository_name()}/releases/latest"


def parse_version(value: str) -> tuple[int, int, int]:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", value)
    if not match:
        raise ValueError(f"Nieobsługiwany numer wersji: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_newer_version(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def _request(url: str, timeout: float = 15.0) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("Repozytorium nie ma jeszcze opublikowanego wydania.") from exc
        raise UpdateError(f"GitHub zwrócił błąd HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Nie można połączyć się z GitHub: {exc}") from exc


def fetch_latest_release(timeout: float = 15.0) -> LatestRelease:
    api_url = f"https://api.github.com/repos/{repository_name()}/releases/latest"
    try:
        payload = json.loads(_request(api_url, timeout).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise UpdateError("GitHub zwrócił nieprawidłową odpowiedź JSON.") from exc

    if not isinstance(payload, dict):
        raise UpdateError("Odpowiedź GitHub nie opisuje wydania.")

    tag_name = str(payload.get("tag_name", "")).strip()
    try:
        version_tuple = parse_version(tag_name)
    except ValueError as exc:
        raise UpdateError("Najnowsze wydanie ma nieobsługiwany numer wersji.") from exc
    version = ".".join(str(part) for part in version_tuple)

    assets: list[ReleaseAsset] = []
    for raw in payload.get("assets", []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "")).strip()
        url = str(raw.get("browser_download_url", "")).strip()
        if not name or not url.startswith("https://"):
            continue
        assets.append(
            ReleaseAsset(
                name=name,
                url=url,
                size=int(raw.get("size", 0) or 0),
                digest=str(raw.get("digest", "") or ""),
            )
        )

    return LatestRelease(
        version=version,
        tag_name=tag_name,
        html_url=str(payload.get("html_url") or release_page_url()),
        body=str(payload.get("body") or "").strip(),
        assets=tuple(assets),
    )


def _package_is_installed(command: list[str]) -> bool:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def detect_install_channel() -> str:
    configured = os.environ.get("SESYJKA_INSTALL_CHANNEL", "").strip().lower()
    if configured in SUPPORTED_CHANNELS:
        return configured

    if shutil.which("dpkg-query") and _package_is_installed(
        ["dpkg-query", "-W", "-f=${db:Status-Status}", "sesyjka"]
    ):
        return "deb"
    if shutil.which("rpm") and _package_is_installed(["rpm", "-q", "sesyjka"]):
        return "rpm"

    module_path = Path(__file__).resolve()
    if Path("/opt/sesyjka") in module_path.parents:
        return "generic"
    return "local"


def asset_for_channel(release: LatestRelease, channel: str) -> ReleaseAsset:
    version = release.version
    if channel == "deb":
        expected = f"sesyjka_{version}_all.deb"
        matches = [asset for asset in release.assets if asset.name == expected]
    elif channel == "rpm":
        prefix = f"sesyjka-{version}-"
        matches = [
            asset
            for asset in release.assets
            if asset.name.startswith(prefix) and asset.name.endswith(".noarch.rpm")
        ]
    elif channel == "generic":
        expected = f"sesyjka-{version}-linux-installer.tar.gz"
        matches = [asset for asset in release.assets if asset.name == expected]
    else:
        raise UpdateError(
            "Ta kopia została uruchomiona lokalnie. Aktualizację należy pobrać ze strony wydania."
        )

    if not matches:
        raise UpdateError(f"Wydanie {release.tag_name} nie zawiera pakietu dla kanału {channel}.")
    return matches[0]


def _download(asset: ReleaseAsset, destination: Path, timeout: float = 60.0) -> None:
    request = urllib.request.Request(asset.url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        destination.unlink(missing_ok=True)
        raise UpdateError(f"Nie udało się pobrać {asset.name}: {exc}") from exc


def _expected_digest(release: LatestRelease, asset: ReleaseAsset, directory: Path) -> str:
    if asset.digest.startswith("sha256:") and len(asset.digest) == 71:
        return asset.digest.removeprefix("sha256:").lower()

    checksum_asset = next(
        (item for item in release.assets if item.name == "SHA256SUMS"),
        None,
    )
    if checksum_asset is None:
        raise UpdateError("Wydanie nie zawiera sum kontrolnych SHA-256.")

    checksum_path = directory / checksum_asset.name
    _download(checksum_asset, checksum_path)
    try:
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise UpdateError("Nie można odczytać pliku SHA256SUMS.") from exc

    for line in lines:
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, filename = parts
        filename = filename.lstrip("*")
        if filename == asset.name and re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            return digest.lower()
    raise UpdateError(f"Brak sumy SHA-256 dla pliku {asset.name}.")


def download_release_asset(
    release: LatestRelease,
    channel: str,
    directory: Path,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    asset = asset_for_channel(release, channel)
    target = directory / asset.name
    _download(asset, target)
    expected = _expected_digest(release, asset, directory)
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != expected:
        target.unlink(missing_ok=True)
        raise UpdateError(
            f"Suma SHA-256 pliku {asset.name} jest niezgodna. Aktualizacja została przerwana."
        )
    target.chmod(0o644)
    return target


def _safe_extract_tar(archive: Path, destination: Path) -> Path:
    destination = destination.resolve()
    with tarfile.open(archive, "r:gz") as handle:
        members = handle.getmembers()
        for member in members:
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise UpdateError("Archiwum instalatora zawiera niebezpieczną ścieżkę.")
            if member.issym() or member.islnk():
                raise UpdateError("Archiwum instalatora zawiera niedozwolone dowiązanie.")
            target = (destination / member_path).resolve()
            if target != destination and destination not in target.parents:
                raise UpdateError("Archiwum instalatora wychodzi poza katalog tymczasowy.")
        handle.extractall(destination, members=members)

    scripts = list(destination.glob("*/install-linux.sh"))
    if len(scripts) != 1:
        raise UpdateError("Archiwum nie zawiera jednoznacznego skryptu install-linux.sh.")
    return scripts[0]


def _run_privileged(command: list[str]) -> None:
    pkexec = shutil.which("pkexec")
    if pkexec is None:
        raise UpdateError(
            "Brak polecenia pkexec. Zainstaluj pakiet Polkit albo wykonaj aktualizację ręcznie."
        )
    completed = subprocess.run([pkexec, *command], check=False)
    if completed.returncode != 0:
        raise UpdateError(
            f"Instalator zakończył się kodem {completed.returncode}. Aktualizacja nie została zastosowana."
        )


def install_release_asset(asset_path: Path, channel: str, work_directory: Path) -> None:
    if channel == "deb":
        apt_get = shutil.which("apt-get")
        if apt_get is None:
            raise UpdateError("Nie znaleziono apt-get wymaganego do aktualizacji pakietu DEB.")
        _run_privileged([apt_get, "install", "-y", str(asset_path)])
        return

    if channel == "rpm":
        dnf = shutil.which("dnf")
        if dnf is None:
            raise UpdateError("Nie znaleziono dnf wymaganego do aktualizacji pakietu RPM.")
        _run_privileged([dnf, "install", "-y", str(asset_path)])
        return

    if channel == "generic":
        extracted = work_directory / "installer"
        extracted.mkdir(parents=True, exist_ok=True)
        install_script = _safe_extract_tar(asset_path, extracted)
        _run_privileged(["/bin/bash", str(install_script)])
        return

    raise UpdateError("Lokalna kopia źródłowa nie może zostać nadpisana automatycznie.")


def download_and_install(release: LatestRelease, channel: str) -> None:
    with tempfile.TemporaryDirectory(prefix="sesyjka-update-") as raw_directory:
        directory = Path(raw_directory)
        directory.chmod(0o755)
        asset_path = download_release_asset(release, channel, directory)
        install_release_asset(asset_path, channel, directory)
