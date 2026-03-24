from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def in_colab() -> bool:
    return "google.colab" in sys.modules or "COLAB_RELEASE_TAG" in os.environ


def project_root() -> Path:
    return Path(__file__).resolve().parent


def run_command(
    command: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> int:
    printable = " ".join(shlex.quote(part) for part in command)
    print(f"$ {printable}", flush=True)
    completed = subprocess.run(command, env=env, cwd=str(project_root()))
    if check and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed.returncode


def detect_chrome_binary() -> str | None:
    candidates = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def detect_chromedriver_binary() -> str | None:
    candidates = [
        "/usr/bin/chromedriver",
        shutil.which("chromedriver"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def build_runtime_env() -> dict[str, str]:
    env = os.environ.copy()

    chrome_bin = detect_chrome_binary()
    chromedriver_bin = detect_chromedriver_binary()

    if chrome_bin:
        env["CHROME_BIN"] = chrome_bin
    if chromedriver_bin:
        env["CHROMEDRIVER"] = chromedriver_bin

    env.setdefault("PYTHONUNBUFFERED", "1")

    path_parts = [env.get("PATH", "")]
    for extra_dir in ("/usr/bin", "/usr/local/bin"):
        if extra_dir not in path_parts:
            path_parts.append(extra_dir)
    env["PATH"] = ":".join(part for part in path_parts if part)

    return env


def install_system_dependencies() -> None:
    print("Menyiapkan dependency sistem untuk Google Colab...", flush=True)
    run_command(["apt-get", "update"])
    run_command(
        [
            "apt-get",
            "install",
            "-y",
            "chromium",
            "chromium-driver",
        ]
    )


def install_python_dependencies(requirements_path: Path) -> None:
    print("Menyiapkan dependency Python...", flush=True)
    run_command([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    run_command([sys.executable, "-m", "pip", "install", "-r", str(requirements_path)])


def ensure_runtime_ready(args: argparse.Namespace) -> dict[str, str]:
    if not args.skip_colab_check and not in_colab():
        print(
            "Peringatan: file ini dirancang untuk Google Colab. "
            "Tetap lanjut karena pemeriksaan Colab dinonaktifkan atau environment kompatibel.",
            flush=True,
        )

    requirements_path = (project_root() / args.requirements).resolve()
    if not requirements_path.exists():
        raise FileNotFoundError(
            f"requirements.txt tidak ditemukan: {requirements_path}"
        )

    if not args.skip_apt:
        install_system_dependencies()
    if not args.skip_pip:
        install_python_dependencies(requirements_path)

    env = build_runtime_env()

    chrome_bin = env.get("CHROME_BIN")
    chromedriver_bin = env.get("CHROMEDRIVER")
    print(f"CHROME_BIN={chrome_bin or '-'}", flush=True)
    print(f"CHROMEDRIVER={chromedriver_bin or '-'}", flush=True)

    return env


def build_target_command(args: argparse.Namespace) -> list[str]:
    target_script = (project_root() / args.entrypoint).resolve()
    if not target_script.exists():
        raise FileNotFoundError(f"Entry point tidak ditemukan: {target_script}")

    command = [sys.executable, str(target_script)]
    command.extend(args.target_args)
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap dan jalankan crawler otomatis di Google Colab."
    )
    parser.add_argument(
        "--entrypoint",
        default="maps-crawling.py",
        help="Script utama yang akan dijalankan setelah bootstrap.",
    )
    parser.add_argument(
        "--requirements",
        default="requirements.txt",
        help="Path requirements relatif terhadap root project.",
    )
    parser.add_argument(
        "--skip-apt",
        action="store_true",
        help="Lewati instalasi package sistem Colab.",
    )
    parser.add_argument(
        "--skip-pip",
        action="store_true",
        help="Lewati instalasi package Python dari requirements.txt.",
    )
    parser.add_argument(
        "--skip-colab-check",
        action="store_true",
        help="Izinkan script tetap jalan walau bukan di environment Colab.",
    )

    parser.add_argument(
        "target_args",
        nargs=argparse.REMAINDER,
        help="Argumen tambahan untuk script target. Gunakan setelah '--'.",
    )
    return parser.parse_args()


def normalize_target_args(raw_args: list[str]) -> list[str]:
    if raw_args and raw_args[0] == "--":
        return raw_args[1:]
    return raw_args


def main() -> int:
    args = parse_args()
    args.target_args = normalize_target_args(args.target_args)

    env = ensure_runtime_ready(args)
    command = build_target_command(args)

    print("Menjalankan crawler...", flush=True)
    return run_command(command, check=False, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
