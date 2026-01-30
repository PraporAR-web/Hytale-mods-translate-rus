# -*- coding: utf-8 -*-
"""
Сбор и сохранение строк перевода: manifest, .lang, .ui, Common/Translations, JSON.
Всё для работы внутри папки mods (распаковка в mods/.extracted/<mod>/).
"""
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Optional

JSON_TEXT_KEYS = frozenset({
    "name", "description", "title", "text", "displayName", "message", "lore",
    "display_name", "desc", "label", "hint", "placeholder",
})

# --- Умный перевод с сохранением тегов ---

# Паттерн для разбиения текста на теги и обычный текст
_TAG_PATTERN = re.compile(
    r'('
    r'<[^>]+>'           # <color is="...">, </color>, <item is="..."/>
    r'|\[[A-Z]+\]'       # [TMP], [WIP] и т.д.
    r'|\\n'              # литеральный \n
    r'| \\n '            # \n с пробелами
    r')',
    re.IGNORECASE
)


def parse_tagged_text(text: str) -> list[tuple[str, bool]]:
    """
    Разбивает текст на сегменты: (содержимое, is_tag).
    is_tag=True — тег/разметка, не переводить.
    is_tag=False — обычный текст, можно переводить.
    """
    if not text:
        return []
    
    result = []
    last_end = 0
    
    for m in _TAG_PATTERN.finditer(text):
        # Текст до тега
        if m.start() > last_end:
            segment = text[last_end:m.start()]
            if segment:
                result.append((segment, False))
        # Сам тег
        result.append((m.group(0), True))
        last_end = m.end()
    
    # Остаток текста после последнего тега
    if last_end < len(text):
        segment = text[last_end:]
        if segment:
            result.append((segment, False))
    
    return result


def smart_translate(text: str, translate_func) -> tuple[str | None, str | None]:
    """
    Переводит текст, сохраняя теги <color>, <item>, [TMP], \\n и т.д.
    
    translate_func(text) -> (translated, error) — функция перевода.
    
    Возвращает (переведённый_текст, ошибка).
    """
    if not text or not text.strip():
        return None, None
    
    segments = parse_tagged_text(text)
    
    # Если тегов нет — обычный перевод
    if all(is_tag for _, is_tag in segments) or not any(is_tag for _, is_tag in segments):
        return translate_func(text)
    
    # Собираем только текстовые сегменты для перевода
    text_segments = [(i, seg) for i, (seg, is_tag) in enumerate(segments) if not is_tag and seg.strip()]
    
    if not text_segments:
        # Только теги — возвращаем как есть
        return text, None
    
    # Переводим каждый текстовый сегмент
    translated_segments = list(segments)
    errors = []
    
    for idx, seg in text_segments:
        seg_clean = seg.strip()
        if not seg_clean:
            continue
        
        tr, err = translate_func(seg_clean)
        if tr:
            # Сохраняем пробелы в начале и конце
            leading = seg[:len(seg) - len(seg.lstrip())]
            trailing = seg[len(seg.rstrip()):]
            translated_segments[idx] = (leading + tr + trailing, False)
        if err:
            errors.append(err)
    
    # Собираем результат
    result = "".join(seg for seg, _ in translated_segments)
    error = errors[0] if errors else None
    
    return result, error


def has_markup(text: str) -> bool:
    """Проверяет, содержит ли текст разметку (теги, переносы и т.д.)."""
    if not text:
        return False
    return bool(_TAG_PATTERN.search(text))


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def _is_translation_key(text: str) -> bool:
    """Игнорировать строки вида слово.слово, слово.слово.слово (ключи перевода, не текст)."""
    if not text or not text.strip():
        return False
    s = text.strip()
    if " " in s:
        return False
    parts = s.split(".")
    if len(parts) < 2:
        return False
    for p in parts:
        if not p or not p.replace("_", "").replace("-", "").isalnum():
            return False
    return True


def _should_skip_source(text: str) -> bool:
    """
    Отсеивать строки, которые не нужно переводить.
    
    Пропускаем: шаблоны {var}, %s, идентификаторы, слитые слова (AliveAlive).
    
    НЕ пропускаем (переводим): описания с тегами <color>, <item>, переносами \\n —
    это текст описаний предметов, переводчики обычно сохраняют разметку.
    """
    if not text or not text.strip():
        return True
    s = text.strip()
    # Шаблоны подстановки — ломаются при переводе
    if "{" in s and "}" in s and re.search(r"\{[a-zA-Z_%]", s):
        return True
    if "%s" in s or "%d" in s or "%(" in s:
        return True
    if re.search(r"_\s*}", s) or re.search(r"\{\s*_", s):
        return True
    if not s.replace("_", "").replace(" ", "").replace("\n", ""):
        return True
    # Идентификаторы snake_case без пробелов (Item_Name_ID)
    if " " not in s and "\n" not in s and "_" in s and all(c.isalnum() or c == "_" for c in s):
        return True
    # Слитые повторяющиеся слова (AliveAlive, TestTest)
    if " " not in s and "\n" not in s and len(s) >= 2 and s.isalpha():
        for n in range(1, len(s) // 2 + 1):
            if len(s) % n != 0:
                continue
            part = s[:n]
            if part * (len(s) // n) == s:
                return True
    return False


# --- Парсинг .lang ---
def parse_lang_content(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def lang_to_content(entries: dict[str, str], use_spaces: bool = False) -> str:
    """Формат key=value (как в оригинальных .lang Hytale) или key = value."""
    sep = " = " if use_spaces else "="
    return "\n".join(f"{k}{sep}{v}" for k, v in sorted(entries.items()))


def _extract_server_translation_keys(obj: Any) -> list[str]:
    """Рекурсивно извлекает ключи server.xxx из JSON (TranslationProperties, Name и т.д.)."""
    keys = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("server."):
                # Ключ в .lang — без префикса "server."
                keys.append(v[7:])  # убираем "server."
            elif isinstance(v, (dict, list)):
                keys.extend(_extract_server_translation_keys(v))
    elif isinstance(obj, list):
        for v in obj:
            keys.extend(_extract_server_translation_keys(v))
    return keys


def _key_case_variant(key: str) -> str:
    """benchCategories.Necronomicon <-> benchcategories.Necronomicon для совместимости."""
    if "benchcategories." in key.lower():
        if "benchcategories." in key:
            return key.replace("benchcategories.", "benchCategories.", 1)
        return key.replace("benchCategories.", "benchcategories.", 1)
    return key


def _key_to_default_display_name(key: str) -> str:
    """Генерирует читаемое имя из ключа: items.Ingredient_Voidheart.name -> Voidheart."""
    base = key.replace(".name", "").replace(".description", "")
    parts = base.split(".")
    last = parts[-1] if parts else key
    # Ingredient_Voidheart -> Voidheart, benchCategories.Necronomicon -> Necronomicon
    name = last.replace("_", " ").strip()
    if not name:
        return key
    result = name.title()
    if ".description" in key:
        result = f"Description: {result}"
    return result


# --- Извлечение строк из .ui (Text: "...", @Text = "...") ---
_UI_TEXT_PATTERN = re.compile(
    r'(Text:\s*")([^"]*)(")|(@Text\s*=\s*")([^"]*)(")',
    re.MULTILINE
)


def extract_ui_strings(content: str) -> list[tuple[int, str]]:
    """Возвращает [(позиция_в_строке, строка), ...] для подстановки при сохранении."""
    out = []
    for m in _UI_TEXT_PATTERN.finditer(content):
        if m.group(2) is not None:
            out.append((m.start(), m.group(2)))
        else:
            out.append((m.start(), m.group(5)))
    return out


def apply_ui_translations(content: str, replacements: list[tuple[str, str]]) -> str:
    """replacements = [(source, translated), ...]. Заменяет только значения в кавычках после Text: / @Text =."""
    if not replacements:
        return content
    def repl(m):
        if m.group(2) is not None:
            prefix, val, suffix = m.group(1), m.group(2), m.group(3)
            for src, tr in replacements:
                if val == src and tr:
                    return prefix + tr + suffix
            return m.group(0)
        else:
            prefix, val, suffix = m.group(4), m.group(5), m.group(6)
            for src, tr in replacements:
                if val == src and tr:
                    return prefix + tr + suffix
            return m.group(0)
    return _UI_TEXT_PATTERN.sub(repl, content)


# --- Единый сбор всех строк для перевода ---
def collect_all_strings(extracted_path: Path) -> list[dict]:
    """
    Собирает все строки из распакованного мода.
    Элемент: {type, file_rel, key, source, translated}.
    type: manifest | lang | ui | common_json | json
    """
    rows = []
    base = extracted_path

    # 1) manifest.json
    for name in ("manifest.json", "pack.json"):
        f = base / name
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            rel = f.relative_to(base).as_posix()
            if data.get("Name") and not _is_translation_key(data["Name"]) and not _should_skip_source(data["Name"]):
                rows.append({"type": "manifest", "file_rel": rel, "key": "Name", "source": data["Name"], "translated": None})
            if data.get("Description") and not _is_translation_key(data["Description"]) and not _should_skip_source(data["Description"]):
                rows.append({"type": "manifest", "file_rel": rel, "key": "Description", "source": data["Description"], "translated": None})
            for i, a in enumerate(data.get("Authors") or []):
                if isinstance(a, dict) and a.get("Name") and not _is_translation_key(a["Name"]) and not _should_skip_source(a["Name"]):
                    rows.append({"type": "manifest", "file_rel": rel, "key": f"Authors[{i}].Name", "source": a["Name"], "translated": None})
        except Exception:
            pass
        break

    # 2) Server/Languages/**/*.lang (en-US или первая локаль; ru-RU подставляем при сохранении)
    lang_root = base / "Server" / "Languages"
    lang_keys_seen: set[tuple[str, str]] = set()  # (rel, key)
    if lang_root.is_dir():
        ru_dir = lang_root / "ru-RU"
        ru_entries_by_file = {}
        if ru_dir.is_dir():
            for lf in ru_dir.glob("*.lang"):
                ru_entries_by_file[lf.name] = parse_lang_content(lf.read_text(encoding="utf-8"))
        for loc_dir in sorted(lang_root.iterdir()):
            if not loc_dir.is_dir() or loc_dir.name == "ru-RU":
                continue
            for lf in loc_dir.glob("*.lang"):
                try:
                    entries = parse_lang_content(lf.read_text(encoding="utf-8"))
                    rel = lf.relative_to(base).as_posix()
                    ru = ru_entries_by_file.get(lf.name, {})
                    for k, v in entries.items():
                        if not _is_translation_key(v) and not _should_skip_source(v):
                            lang_keys_seen.add((rel, k))
                            rows.append({"type": "lang", "file_rel": rel, "key": k, "source": v, "translated": ru.get(k)})
                except Exception:
                    pass
            break

    # 2b) Ключи server.xxx из JSON (TranslationProperties, Bench Categories и т.д.) — добавляем недостающие
    default_lang_rel = None
    en_entries_all: dict[str, str] = {}  # Все записи из en-US/*.lang
    if lang_root.is_dir():
        for loc_dir in sorted(lang_root.iterdir()):
            if loc_dir.is_dir() and loc_dir.name != "ru-RU":
                for lf in loc_dir.glob("*.lang"):
                    if lf.exists():
                        en_entries_all.update(parse_lang_content(lf.read_text(encoding="utf-8")))
                        if default_lang_rel is None:
                            default_lang_rel = lf.relative_to(base).as_posix()
                break
    if default_lang_rel:
        for jf in base.rglob("*.json"):
            if not jf.is_file() or "Languages" in jf.parts or "Translations" in jf.parts:
                continue
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                for key in _extract_server_translation_keys(data):
                    if (default_lang_rel, key) not in lang_keys_seen:
                        lang_keys_seen.add((default_lang_rel, key))
                        # Берём source из en-US, а не генерируем заглушку
                        src_val = en_entries_all.get(key) or en_entries_all.get(_key_case_variant(key)) or _key_to_default_display_name(key)
                        ru_val = None
                        if ru_dir.exists():
                            for ru_lf in ru_dir.glob("*.lang"):
                                ru_entries = parse_lang_content(ru_lf.read_text(encoding="utf-8"))
                                ru_val = ru_entries.get(key) or ru_val or ru_entries.get(_key_case_variant(key))
                        # Не добавляем если source проблемный
                        if not _should_skip_source(src_val):
                            rows.append({"type": "lang", "file_rel": default_lang_rel, "key": key, "source": src_val, "translated": ru_val})
            except Exception:
                pass

    # 3) Common/Translations/*.json (en_US.json -> ru_RU.json)
    trans_root = base / "Common" / "Translations"
    if trans_root.is_dir():
        for jf in trans_root.glob("*.json"):
            if jf.name.startswith("ru"):  # Пропускаем русские — целевые файлы
                continue
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                rel = jf.relative_to(base).as_posix()
                if isinstance(data, dict):
                    ru_file = jf.parent / "ru_RU.json"
                    ru_data = json.loads(ru_file.read_text(encoding="utf-8")) if ru_file.exists() else {}
                    for k, v in data.items():
                        if isinstance(v, str) and not _is_translation_key(v) and not _should_skip_source(v):
                            rows.append({"type": "common_json", "file_rel": rel, "key": k, "source": v, "translated": ru_data.get(k)})
                        elif isinstance(v, dict):
                            # Вложенный уровень: blocks, items, enchantments и т.д.
                            ru_inner = ru_data.get(k, {})
                            if isinstance(ru_inner, dict):
                                for k2, v2 in v.items():
                                    if isinstance(v2, str) and not _is_translation_key(v2) and not _should_skip_source(v2):
                                        rows.append({"type": "common_json", "file_rel": rel, "key": f"{k}.{k2}", "source": v2, "translated": ru_inner.get(k2)})
            except Exception:
                pass

    # 4) .ui — все Text: "..." и @Text = "..." (уникальные по файлу+строка, один перевод на все вхождения)
    seen_ui = set()
    for uf in base.rglob("*.ui"):
        if not uf.is_file():
            continue
        try:
            content = uf.read_text(encoding="utf-8")
            rel = uf.relative_to(base).as_posix()
            for pos, s in extract_ui_strings(content):
                if s.strip() and not _is_translation_key(s) and not _should_skip_source(s) and (rel, s) not in seen_ui:
                    seen_ui.add((rel, s))
                    rows.append({"type": "ui", "file_rel": rel, "key": str(pos), "source": s, "translated": None})
        except Exception:
            pass

    # 5) Server/Languages уже выше; остальные JSON с name/description и т.д.
    for jf in base.rglob("*.json"):
        if not jf.is_file() or "Languages" in jf.parts or "Translations" in jf.parts:
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            rel = jf.relative_to(base).as_posix()
            for path_t, val in _json_find_text_paths(data, ()):
                if isinstance(val, str) and val.strip() and not _is_translation_key(val) and not _should_skip_source(val):
                    key_str = _path_to_key_str(path_t)
                    rows.append({"type": "json", "file_rel": rel, "key": key_str, "source": val, "translated": None})
        except Exception:
            pass

    return rows


def _json_find_text_paths(obj: Any, path: tuple) -> list[tuple[tuple, str]]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower() if isinstance(k, str) else k
            if isinstance(k, str) and kl in JSON_TEXT_KEYS and isinstance(v, str):
                out.append((path + (k,), v))
            else:
                out.extend(_json_find_text_paths(v, path + (k,)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_json_find_text_paths(v, path + (i,)))
    return out


def _path_to_key_str(path: tuple) -> str:
    parts = []
    for p in path:
        parts.append(f"[{p}]" if isinstance(p, int) else (str(p) if not parts else "." + str(p)))
    return "".join(parts).lstrip(".")


def _key_str_to_path(s: str) -> tuple:
    parts = re.split(r"\.|\[|\]", s)
    out = []
    for p in parts:
        if p == "":
            continue
        out.append(int(p) if p.isdigit() else p)
    return tuple(out)


def _json_set_by_path(obj: Any, path: tuple, value: str) -> None:
    if len(path) == 1:
        obj[path[0]] = value
        return
    if isinstance(path[0], int):
        _json_set_by_path(obj[path[0]], path[1:], value)
    else:
        _json_set_by_path(obj[path[0]], path[1:], value)


def lang_file_rel_to_ru(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    for i, p in enumerate(parts):
        if p and p != "ru-RU" and (p.startswith("en") or (len(p) == 5 and p[2] == "-")):
            parts[i] = "ru-RU"
            break
    return "/".join(parts)


# --- Сохранение переводов обратно в файлы ---
def save_all_translations(extracted_path: Path, rows: list[dict]) -> None:
    """
    Записывает переводы из rows в файлы распакованного мода.
    Использует поле "translated"; пустые пропускает.
    """
    # По типам
    manifest_updates = {}
    lang_by_file = {}
    ui_by_file = {}
    common_json_by_file = {}
    json_by_file = {}

    lang_sources: dict[str, dict[str, str]] = {}  # ru_rel -> {key: source}
    for r in rows:
        tr = (r.get("translated") or "").strip()
        t, rel, key, src = r["type"], r["file_rel"], r["key"], r["source"]
        if t == "lang":
            lang_sources.setdefault(lang_file_rel_to_ru(rel), {})[key] = (src or "").strip()
        if not tr:
            continue
        if t == "manifest":
            if rel not in manifest_updates:
                manifest_updates[rel] = {}
            manifest_updates[rel][key] = tr
        elif t == "lang":
            ru_rel = lang_file_rel_to_ru(rel)
            lang_by_file.setdefault(ru_rel, {})[key] = tr
        elif t == "ui":
            ui_by_file.setdefault(rel, []).append((src, tr))
        elif t == "common_json":
            common_json_by_file.setdefault(rel, {})[key] = tr
        elif t == "json":
            json_by_file.setdefault(rel, []).append((key, tr))

    base = extracted_path

    for rel, kv in manifest_updates.items():
        p = base / rel
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for k, v in kv.items():
            if k == "Name":
                data["Name"] = v
            elif k == "Description":
                data["Description"] = v
            elif k.startswith("Authors[") and "].Name" in k:
                idx = int(k.split("[")[1].split("]")[0])
                if "Authors" in data and idx < len(data["Authors"]) and isinstance(data["Authors"][idx], dict):
                    data["Authors"][idx]["Name"] = v
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    for ru_rel, entries in lang_by_file.items():
        ru_path = base / ru_rel
        # Объединяем с существующим ru-RU, чтобы не потерять переводы
        existing_ru = {}
        if ru_path.exists():
            existing_ru = parse_lang_content(ru_path.read_text(encoding="utf-8"))
        existing_ru.update(entries)
        # Алиасы для ключей с разным регистром (benchcategories <-> benchCategories)
        for k, v in list(existing_ru.items()):
            alt = _key_case_variant(k)
            if alt != k and alt not in existing_ru:
                existing_ru[alt] = v
        ru_path.parent.mkdir(parents=True, exist_ok=True)
        content = lang_to_content(existing_ru, use_spaces=False)
        ru_path.write_text(content, encoding="utf-8")

        # Дополняем en-US недостающими ключами (с исходным текстом на английском)
        src_rel = ru_rel.replace("ru-RU", "en-US")
        src_path = base / src_rel
        if src_path.exists() and src_rel != ru_rel:
            existing_en = parse_lang_content(src_path.read_text(encoding="utf-8"))
            sources = lang_sources.get(ru_rel, {})
            for k, src_text in sources.items():
                if k not in existing_en and src_text:
                    existing_en[k] = src_text
            for k, v in list(existing_en.items()):
                alt = _key_case_variant(k)
                if alt != k and alt not in existing_en:
                    existing_en[alt] = v
            src_path.write_text(lang_to_content(existing_en, use_spaces=False), encoding="utf-8")

    for rel, pairs in ui_by_file.items():
        p = base / rel
        if not p.exists():
            continue
        content = p.read_text(encoding="utf-8")
        content = apply_ui_translations(content, pairs)
        p.write_text(content, encoding="utf-8")

    for rel, kv in common_json_by_file.items():
        p = base / rel
        ru_path = p.parent / "ru_RU.json"
        existing = {}
        if ru_path.exists():
            existing = json.loads(ru_path.read_text(encoding="utf-8"))
        for key_path, val in kv.items():
            # Ключ вида "enchantments.sharpness.description" — первая часть категория, остальное подключ
            parts = key_path.split(".", 1)
            if len(parts) == 1:
                existing[parts[0]] = val
            else:
                cat, subkey = parts[0], parts[1]
                if cat not in existing or not isinstance(existing[cat], dict):
                    existing[cat] = {}
                existing[cat][subkey] = val
        ru_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    for rel, key_vals in json_by_file.items():
        p = base / rel
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for key_str, val in key_vals:
            _json_set_by_path(data, _key_str_to_path(key_str), val)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# --- Работа с JAR/ZIP без распаковки (чтение .lang для совместимости) ---
def get_lang_files_from_archive(archive_path: Path) -> dict[str, dict[str, str]]:
    result = {}
    try:
        with zipfile.ZipFile(archive_path, "r") as z:
            for name in z.namelist():
                n = name.replace("\\", "/")
                if n.endswith(".lang"):
                    with z.open(name) as f:
                        result[n] = parse_lang_content(f.read().decode("utf-8", errors="replace"))
    except Exception:
        pass
    return result
