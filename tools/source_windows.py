"""Double-click source launcher. Preparation uses only the standard library."""
import hashlib
import http.client
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.instance import launcher_lock, open_browser, open_existing, ready
from backend.paths import windows_data_dir

FRONT = ROOT / "frontend"
VENV = ROOT / ".venv"
CACHE = ROOT / "build" / "source-launcher"


def fingerprint(files, base, version=""):
    result = hashlib.sha256(version.encode())
    for path in sorted(files):
        if path.is_file():
            result.update(path.relative_to(base).as_posix().encode() + b"\0")
            result.update(hashlib.sha256(path.read_bytes()).digest())
    return result.hexdigest()


def read_stamp(path):
    try:
        return path.read_text(encoding="ascii")
    except FileNotFoundError:
        return ""


def stamp(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(value, encoding="ascii")
    temp.replace(path)


def run(description, args, cwd=ROOT):
    print(description, flush=True)
    try:
        subprocess.run(args, cwd=cwd, check=True)
    except (OSError, subprocess.CalledProcessError) as err:
        raise RuntimeError(description + " — ошибка. Подробности указаны выше.") from err


def installed_python(requirements):
    # Inspect the target venv from the bootstrap interpreter. Unrelated developer
    # packages do not invalidate the runtime lock.
    locked = {line.split("==", 1)[0] for line in requirements.read_text().splitlines() if "==" in line}
    packages = importlib.metadata.distributions(path=[VENV / "Lib/site-packages"])
    versions = sorted((d.metadata["Name"].lower(), d.version) for d in packages
                      if d.metadata["Name"].lower() in locked)
    return hashlib.sha256(json.dumps(versions).encode()).hexdigest()


def installed_frontend(modules):
    try:
        lock = json.loads((modules / ".package-lock.json").read_text(encoding="utf-8"))
        return all((FRONT / package).is_dir() for package in lock["packages"])
    except (FileNotFoundError, KeyError, ValueError):
        return False


def prepare():
    node = shutil.which("node.exe")
    npm = shutil.which("npm.cmd")
    if not node or not npm:
        raise RuntimeError("Установите Node.js 24 с npm и снова откройте start.bat.")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if not version.startswith("v24."):
        raise RuntimeError(f"Нужен Node.js 24 с npm. Обнаружена версия {version}.")
    py = VENV / "Scripts" / "python.exe"
    if not py.exists():
        run("Создание виртуального окружения Python", [sys.executable, "-m", "venv", VENV])
    pyversion = subprocess.check_output([py, "-c", "import platform; print(platform.python_version())"], text=True).strip()
    if not pyversion.startswith("3.12."):
        raise RuntimeError("В .venv другая версия Python. Переименуйте этот каталог и повторите запуск.")
    requirements = ROOT / "requirements.txt"
    deps = fingerprint([requirements], ROOT, pyversion)
    py_stamp = VENV / ".esportsim-dependencies"
    if read_stamp(py_stamp) != deps + installed_python(requirements) or not (VENV / "Lib/site-packages/fastapi").is_dir():
        run("Установка зависимостей Python", [py, "-m", "pip", "install", "-r", requirements])
        stamp(py_stamp, deps + installed_python(requirements))

    native_lock = ROOT / "requirements-native.txt"
    native_sources = [native_lock, ROOT / "tools/build_native.py", *(ROOT / "native").rglob("*")]
    native_key = fingerprint(native_sources, ROOT, pyversion + str(VENV))
    extension = ROOT / "backend" / ("_match_native" + subprocess.check_output(
        [py, "-c", "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))"], text=True).strip())
    native_stamp = CACHE / "native.sha256"
    if not extension.is_file() or read_stamp(native_stamp) != native_key + fingerprint([extension], ROOT):
        run("Установка зависимостей сборки C++", [py, "-m", "pip", "install", "-r", native_lock])
        run("Сборка матчевого модуля (требуются Visual Studio Build Tools с C++ x64)",
            [py, "-m", "tools.build_native"])
        run("Проверка нативного модуля", [py, "-c", "from backend import _match_native"])
        stamp(native_stamp, native_key + fingerprint([extension], ROOT))

    manifest = [FRONT / "package.json", FRONT / "package-lock.json"]
    js_deps = fingerprint(manifest, FRONT, version)
    modules = FRONT / "node_modules"
    js_stamp = modules / ".esportsim-dependencies"
    if read_stamp(js_stamp) != js_deps or not installed_frontend(modules) or not all((modules / ".bin" / f"{tool}.cmd").exists() for tool in ("tsc","vite")):
        run("Установка зависимостей интерфейса", [npm, "ci", "--include=dev"], FRONT)
        stamp(js_stamp, js_deps)
    inputs = [*manifest, FRONT / "index.html", *FRONT.glob("tsconfig*.json"), *FRONT.glob("vite.config.*"),
              *FRONT.glob(".env*"), *(FRONT / "src").rglob("*"), *(FRONT / "public").rglob("*")]
    # Vite also reads VITE_* variables supplied directly by the developer.
    env = sorted((k,v) for k,v in os.environ.items() if k.startswith("VITE_") or k == "NODE_ENV")
    source = fingerprint(inputs, FRONT, js_deps + json.dumps(env))
    dist = FRONT / "dist"
    build_stamp = CACHE / "frontend.sha256"
    output = fingerprint(dist.rglob("*"), dist)
    if not (dist / "index.html").is_file() or read_stamp(build_stamp) != source + output:
        run("Сборка интерфейса", [npm, "run", "build"], FRONT)
        stamp(build_stamp, source + fingerprint(dist.rglob("*"), dist))


def stop(descriptor):
    if not descriptor.exists():
        print("Сервер EsportSim уже остановлен.")
        return
    instance = json.loads(descriptor.read_text(encoding="utf-8"))
    port, nonce = instance["port"], instance["nonce"]
    if not ready(port, nonce):
        raise RuntimeError("Сервер из профиля не отвечает. Команда остановки не отправлена.")
    origin = f"http://127.0.0.1:{port}"
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        client.request("POST", "/api/host/shutdown", headers={"Origin":origin, "X-EsportSim-Instance":nonce})
        if client.getresponse().status != 200:
            raise RuntimeError("Сервер отклонил запрос на остановку.")
    finally:
        client.close()
    deadline = time.monotonic() + 20
    while True:
        try:
            current = json.loads(descriptor.read_text(encoding="utf-8"))
        except FileNotFoundError:
            break
        if current["nonce"] != nonce:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Сервер не подтвердил завершение. Проверьте журнал запуска в профиле EsportSim.")
        time.sleep(0.1)
    print("Сервер EsportSim остановлен.")


def main():
    descriptor = windows_data_dir() / "instance.json"
    CACHE.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 600
    # Simultaneous double-clicks must not install into the same venv or dist.
    while True:
        with launcher_lock(CACHE / "prepare.lock") as acquired:
            if acquired:
                if sys.argv[1:] == ["stop"]:
                    stop(descriptor)
                    return
                if open_existing(descriptor, open_browser):
                    return
                prepare()
                process = subprocess.Popen([VENV / "Scripts/pythonw.exe", "-m", "backend.desktop"],
                                           cwd=ROOT, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)
                until = time.monotonic() + 45
                while time.monotonic() < until:
                    if descriptor.exists():
                        data = json.loads(descriptor.read_text(encoding="utf-8"))
                        if ready(data["port"], data["nonce"]):
                            print("Игра открывается в браузере.")
                            return
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)
                raise RuntimeError(r"Не удалось запустить игру. Журнал: %LOCALAPPDATA%\EsportSim\launcher.log")
        if time.monotonic() >= deadline:
            raise RuntimeError("Другой запуск ещё готовит проект. Проверьте его окно.")
        time.sleep(0.25)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"Ошибка EsportSim: {exc}", file=sys.stderr)
        sys.exit(1)
