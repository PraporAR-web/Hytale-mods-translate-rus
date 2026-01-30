# -*- coding: utf-8 -*-
"""
Моды Hytale: сканирование папки mods, распаковка в mods/.extracted/, сборка.
"""
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Optional


def safe_mod_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def get_mods_folder() -> Path:
    """Папка с модами: рядом с exe при сборке, иначе рядом с модулем."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    mods = base / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    return mods


def get_extracted_root(mods_path: Path) -> Path:
    """Папка распакованных модов — внутри mods."""
    return mods_path / ".extracted"


def scan_mods(mods_path: Path) -> list[dict]:
    """
    Сканирует mods_path: JAR и ZIP (не папки .extracted и _disabled).
    Элемент: {path, name, type: 'jar'|'zip', manifest?}
    """
    result = []
    if not mods_path.is_dir():
        return result
    for p in mods_path.iterdir():
        if p.name.startswith(".") or p.name.startswith("_"):
            continue
        suf = p.suffix.lower()
        if suf not in (".jar", ".zip"):
            continue
        name = p.stem
        manifest = _read_manifest_from_archive(p)
        if manifest:
            name = manifest.get("Name") or manifest.get("name") or name
        result.append({
            "path": p,
            "name": name,
            "type": "jar" if suf == ".jar" else "zip",
            "manifest": manifest,
        })
    return result


def _read_manifest_from_archive(archive_path: Path) -> Optional[dict]:
    try:
        with zipfile.ZipFile(archive_path, "r") as z:
            for n in z.namelist():
                if n.endswith("manifest.json"):
                    with z.open(n) as f:
                        return json.load(f)
    except Exception:
        pass
    return None


def extract_mod(archive_path: Path, mods_path: Path, display_name: str) -> Path:
    """
    Распаковывает JAR/ZIP в mods_path/.extracted/<safe_name>/.
    Возвращает путь к распакованной папке.
    """
    root = get_extracted_root(mods_path)
    root.mkdir(parents=True, exist_ok=True)
    folder = safe_mod_name(display_name or archive_path.stem)
    out = root / folder
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "r") as z:
        z.extractall(out)
    return out


def get_extracted_mods(mods_path: Path) -> list[dict]:
    """Список распакованных модов: {path, name}."""
    root = get_extracted_root(mods_path)
    if not root.is_dir():
        return []
    return [{"path": p, "name": p.name} for p in root.iterdir() if p.is_dir()]


def pack_mod(extracted_path: Path, output_path: Path, backup: bool = True) -> bool:
    """
    Упаковывает папку в JAR или ZIP (по расширению output_path).
    При backup=True копирует существующий файл в backups/.
    """
    backup_dir = output_path.parent / "backups"
    if output_path.exists() and backup:
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_path, backup_dir / f"{output_path.stem}{output_path.suffix}.bak")
    temp = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in extracted_path.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(extracted_path).as_posix())
        temp.replace(output_path)
        return True
    except Exception:
        if temp.exists():
            try:
                temp.unlink()
            except Exception:
                pass
        return False
