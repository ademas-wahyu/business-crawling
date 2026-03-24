from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


def in_colab() -> bool:
    return "google.colab" in sys.modules or "COLAB_RELEASE_TAG" in os.environ


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_command(
    command: list[str],
    *,
    check: bool = True,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> int:
    printable = " ".join(shlex.quote(part) for part in command)
    print(f"$ {printable}", flush=True)
    completed = subprocess.run(command, cwd=str(cwd or project_root()), env=env)
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"Command gagal dengan exit code {completed.returncode}: {printable}"
        )
    return completed.returncode


def _detect_existing_binary(candidates: Iterable[str | None]) -> str | None:
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def detect_chrome_binary() -> str | None:
    return _detect_existing_binary(
        [
            os.environ.get("GOOGLE_CHROME_BIN"),
            os.environ.get("CHROME_BIN"),
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("google-chrome"),
        ]
    )


def detect_chromedriver_binary() -> str | None:
    return _detect_existing_binary(
        [
            os.environ.get("CHROMEDRIVER_PATH"),
            os.environ.get("CHROMEDRIVER"),
            "/usr/bin/chromedriver",
            "/usr/lib/chromium-browser/chromedriver",
            "/usr/lib/chromium/chromedriver",
            shutil.which("chromedriver"),
        ]
    )


def build_runtime_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()

    chrome_bin = detect_chrome_binary()
    chromedriver_bin = detect_chromedriver_binary()

    if chrome_bin:
        env["GOOGLE_CHROME_BIN"] = chrome_bin
        env["CHROME_BIN"] = chrome_bin
    if chromedriver_bin:
        env["CHROMEDRIVER_PATH"] = chromedriver_bin
        env["CHROMEDRIVER"] = chromedriver_bin

    env.setdefault("PYTHONUNBUFFERED", "1")

    path_items = [item for item in env.get("PATH", "").split(":") if item]
    for extra_dir in ("/usr/bin", "/usr/local/bin"):
        if extra_dir not in path_items:
            path_items.append(extra_dir)
    env["PATH"] = ":".join(path_items)

    if extra_env:
        env.update(extra_env)

    return env


def install_colab_runtime(
    *,
    requirements_path: str | Path = "requirements.txt",
    install_system_packages: bool = True,
    install_python_packages: bool = True,
    upgrade_pip: bool = True,
    allow_non_colab: bool = False,
) -> dict[str, str]:
    if not allow_non_colab and not in_colab():
        raise RuntimeError(
            "Environment ini bukan Google Colab. "
            "Set allow_non_colab=True jika ingin tetap menjalankan bootstrap."
        )

    root = project_root()
    req_path = Path(requirements_path)
    if not req_path.is_absolute():
        req_path = root / req_path
    if not req_path.exists():
        raise FileNotFoundError(f"requirements.txt tidak ditemukan: {req_path}")

    if install_system_packages:
        print("Menyiapkan dependency sistem untuk runtime browser...", flush=True)
        run_command(["apt-get", "update", "-y"], cwd=root)
        run_command(
            [
                "apt-get",
                "install",
                "-y",
                "chromium",
                "chromium-driver",
            ],
            cwd=root,
        )

    if install_python_packages:
        print("Menyiapkan dependency Python...", flush=True)
        if upgrade_pip:
            run_command(
                [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
                cwd=root,
            )
        run_command(
            [sys.executable, "-m", "pip", "install", "-r", str(req_path)],
            cwd=root,
        )

    env = build_runtime_env()

    print(f"GOOGLE_CHROME_BIN={env.get('GOOGLE_CHROME_BIN', '-')}", flush=True)
    print(f"CHROMEDRIVER_PATH={env.get('CHROMEDRIVER_PATH', '-')}", flush=True)

    return env


def run_colab_cli(
    cli_args: list[str] | None = None,
    *,
    entrypoint: str | Path = "maps-crawling.py",
    bootstrap: bool = True,
    requirements_path: str | Path = "requirements.txt",
    install_system_packages: bool = True,
    install_python_packages: bool = True,
    upgrade_pip: bool = False,
    allow_non_colab: bool = False,
    extra_env: dict[str, str] | None = None,
) -> int:
    root = project_root()
    script_path = Path(entrypoint)
    if not script_path.is_absolute():
        script_path = root / script_path
    if not script_path.exists():
        raise FileNotFoundError(f"Entry point tidak ditemukan: {script_path}")

    if bootstrap:
        env = install_colab_runtime(
            requirements_path=requirements_path,
            install_system_packages=install_system_packages,
            install_python_packages=install_python_packages,
            upgrade_pip=upgrade_pip,
            allow_non_colab=allow_non_colab,
        )
    else:
        if not allow_non_colab and not in_colab():
            raise RuntimeError(
                "Environment ini bukan Google Colab. "
                "Set allow_non_colab=True jika ingin tetap menjalankan helper ini."
            )
        env = build_runtime_env()

    if extra_env:
        env.update(extra_env)

    command = [sys.executable, str(script_path)]
    if cli_args:
        command.extend(cli_args)

    return run_command(command, check=False, cwd=root, env=env)


__all__ = [
    "build_runtime_env",
    "detect_chrome_binary",
    "detect_chromedriver_binary",
    "in_colab",
    "install_colab_runtime",
    "project_root",
    "run_colab_cli",
    "run_command",
]
