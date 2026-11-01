#!/usr/bin/env python3

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = "https://github.com/f1zzen/zust_strategies/raw/refs/heads/main/"
MARKER = 'winws.exe"'
STATE = ROOT / "upstream.json"


def natural_key(name: str):
    # general <- general (ALT) <- general (ALT2) <- general (ALT10)
    stem = re.sub(r"[()]", "", name.rsplit(".", 1)[0]).lower()
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", stem)]


def convert(bat: str) -> str | None:
    idx = bat.find(MARKER)
    if idx < 0:
        return None
    args = bat[idx + len(MARKER):].replace("\r\n", "\n").replace("^!", "!").strip()
    return args + "\n"


def write_if_changed(path: Path, data: bytes) -> bool:
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    up = Path(sys.argv[1]).resolve()

    state = json.loads(STATE.read_text("utf-8")) if STATE.exists() else {}
    previously_generated = set(state.get("strategies", []))
    changes: list[str] = []

    # стратегии
    generated: dict[str, str] = {}
    for bat in sorted(up.glob("general*.bat")):
        args = convert(bat.read_text("utf-8", errors="replace"))
        if args is None:
            print(f"пропуск {bat.name}: нет запуска winws.exe", file=sys.stderr)
            continue
        generated[bat.stem + ".zapret"] = args
    if not generated:
        print("в upstream не найдено ни одной стратегии — что-то сломалось", file=sys.stderr)
        return 1

    # bin
    upstream_bins = {p.name: p.read_bytes() for p in (up / "bin").glob("*.bin")}
    local_bins = {p.name for p in ROOT.glob("*.bin")}
    available_bins = local_bins | set(upstream_bins)

    # проверка ссылок
    custom = sorted(
        (p.name for p in ROOT.glob("*.zapret")
         if p.name not in generated and p.name not in previously_generated),
        key=natural_key,
    )
    all_texts = dict(generated)
    for name in custom:
        all_texts[name] = (ROOT / name).read_text("utf-8", errors="replace")
    missing = {}
    for name, text in all_texts.items():
        for ref in re.findall(r"%BIN%([^\"\s]+)", text):
            if ref not in available_bins:
                missing.setdefault(ref, []).append(name)
    if missing:
        for ref, users in missing.items():
            print(f"нет файла {ref}, нужен для: {', '.join(users)}", file=sys.stderr)
        return 1

    # запись
    for name, args in generated.items():
        if write_if_changed(ROOT / name, args.encode("utf-8")):
            changes.append(f"стратегия: {name}")
    for name in sorted(previously_generated - set(generated)):
        path = ROOT / name
        if path.exists():
            path.unlink()
            changes.append(f"удалена (нет в upstream): {name}")

    for name, data in upstream_bins.items():
        if write_if_changed(ROOT / name, data):
            changes.append(f"bin: {name}")

    lists_dir = up / "lists"
    for p in sorted(lists_dir.glob("*.txt")):
        if write_if_changed(ROOT / "lists" / p.name, p.read_bytes()):
            changes.append(f"список: {p.name}")

    strategies = sorted(generated, key=natural_key) + custom
    write_if_changed(ROOT / "list", ("\n".join(strategies) + "\n").encode())
    bins = sorted(p.name for p in ROOT.glob("*.bin"))
    write_if_changed(ROOT / "list_bin", ("\n".join(RAW + b for b in bins) + "\n").encode())

    def git(*args):
        r = subprocess.run(["git", "-C", str(up), *args], capture_output=True, text=True)
        return r.stdout.strip() or None

    version_file = up / ".service" / "version.txt"
    new_state = {
        "source": "https://github.com/flowseal/zapret-discord-youtube",
        "version": version_file.read_text().strip() if version_file.exists() else None,
        "commit": git("rev-parse", "HEAD"),
        "commitDate": git("log", "-1", "--format=%cI"),
        "strategies": sorted(generated, key=natural_key),
    }
    # онли изменения в коммит
    if changes or new_state["strategies"] != state.get("strategies"):
        STATE.write_text(json.dumps(new_state, ensure_ascii=False, indent=2) + "\n", "utf-8")

    print("\n".join(changes) if changes else "изменений нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
