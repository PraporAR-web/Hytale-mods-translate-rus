# -*- coding: utf-8 -*-
"""
Hytale — перевод модов. Одно окно, запоминание папки, поиск/фильтр, пакетный перевод, память переводов.
"""
import json
import os
import shutil
import sys
import time
import webbrowser
import customtkinter as ctk
from pathlib import Path
from tkinter import messagebox, filedialog
import mod_manager as mm
import translation_manager as tm

GITHUB_URL = "https://github.com/PraporAR-web"


def _get_base_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CONFIG_PATH = _get_base_path() / "app_config.json"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_config(data: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _translation_memory_path(mods_path: Path) -> Path:
    return mods_path / "translation_memory.json"


def _load_translation_memory(mods_path: Path) -> dict[str, str]:
    p = _translation_memory_path(mods_path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_translation_memory(mods_path: Path, memory: dict[str, str]) -> None:
    try:
        _translation_memory_path(mods_path).write_text(
            json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _basic_translate(text: str, source_lang: str = "en", target_lang: str = "ru") -> tuple[str | None, str | None]:
    """Базовый перевод без обработки тегов."""
    text = (text or "").strip()
    if not text:
        return None, None
    if len(text) > 4500:
        text = text[:4500]
    err = None
    try:
        from deep_translator import GoogleTranslator
        out = GoogleTranslator(source=source_lang, target=target_lang).translate(text)
        if out and out.strip():
            return out.strip(), None
    except Exception as e:
        err = str(e)
    try:
        from deep_translator import GoogleTranslator
        out = GoogleTranslator(source="auto", target=target_lang).translate(text)
        if out and out.strip():
            return out.strip(), None
    except Exception as e:
        if not err:
            err = str(e)
    text_short = text[:500] if len(text) > 500 else text
    try:
        from deep_translator import MyMemoryTranslator
        out = MyMemoryTranslator(source=source_lang, target=target_lang).translate(text_short)
        if out and out.strip():
            return out.strip(), None
    except Exception as e:
        if not err:
            err = str(e)
    try:
        from deep_translator import MyMemoryTranslator
        out = MyMemoryTranslator(source="auto", target=target_lang).translate(text_short)
        if out and out.strip():
            return out.strip(), None
    except Exception as e:
        if not err:
            err = str(e)
    return None, err


# Глобальный кэш сегментов для ускорения перевода
_segment_cache: dict[str, str] = {}


def _auto_translate(text: str, source_lang: str = "en", target_lang: str = "ru", 
                    memory: dict[str, str] | None = None) -> tuple[str | None, str | None]:
    """
    Умный перевод с сохранением тегов <color>, <item>, [TMP], \\n и т.д.
    Теги остаются на месте, переводится только текст между ними.
    
    memory — словарь памяти переводов для кэширования.
    """
    text = (text or "").strip()
    if not text:
        return None, None
    
    # Сначала проверяем полное совпадение в памяти
    if memory and text in memory:
        return memory[text], None
    
    # Проверяем, есть ли разметка
    if tm.has_markup(text):
        # Умный перевод с сохранением тегов и кэшированием сегментов
        def translate_segment(seg: str) -> tuple[str | None, str | None]:
            seg_clean = seg.strip()
            if not seg_clean:
                return seg, None
            # Проверяем кэш сегментов
            if seg_clean in _segment_cache:
                return _segment_cache[seg_clean], None
            # Проверяем память
            if memory and seg_clean in memory:
                _segment_cache[seg_clean] = memory[seg_clean]
                return memory[seg_clean], None
            # Переводим
            tr, err = _basic_translate(seg_clean, source_lang, target_lang)
            if tr:
                _segment_cache[seg_clean] = tr
                if memory is not None:
                    memory[seg_clean] = tr
            return tr, err
        
        result, err = tm.smart_translate(text, translate_segment)
        # Сохраняем полный перевод в память
        if result and memory is not None:
            memory[text] = result
        return result, err
    else:
        # Обычный перевод
        result, err = _basic_translate(text, source_lang, target_lang)
        if result and memory is not None:
            memory[text] = result
        return result, err


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")
SIZE_LIST = (720, 560)
SIZE_TRANSLATE = (1020, 720)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Hytale — перевод модов")
        self.geometry(f"{SIZE_LIST[0]}x{SIZE_LIST[1]}")
        self.minsize(560, 420)
        cfg = _load_config()
        self.mods_path = Path(cfg.get("mods_path", str(mm.get_mods_folder())))
        if not self.mods_path.is_dir():
            self.mods_path = mm.get_mods_folder()
        self.mod_rows: list[ctk.CTkFrame] = []
        self.extracted_rows: list[ctk.CTkFrame] = []
        self._translate_mod: dict | None = None
        self._translate_extracted_path: Path | None = None
        self._translate_rows: list[dict] = []
        self._translate_entries: list[ctk.CTkEntry] = []
        self._translate_row_frames: list[ctk.CTkFrame] = []
        self._translate_source_lang = "en"
        self._translate_target_lang = "ru"
        self._translate_cleanup_after_pack = ctk.BooleanVar(value=False)
        self._batch_cancelled = False

        # --- Верхняя панель ---
        self.top_bar = ctk.CTkFrame(self, fg_color="transparent", height=44)
        self.top_bar.pack(fill="x", padx=16, pady=(12, 6))
        self.top_bar.pack_propagate(False)
        ctk.CTkLabel(self.top_bar, text="Папка модов:", font=("", 12)).pack(side="left", padx=(0, 8))
        self.path_label = ctk.CTkLabel(self.top_bar, text=str(self.mods_path), anchor="w", text_color=("gray50", "gray70"))
        self.path_label.pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkButton(self.top_bar, text="Открыть папку", width=100, fg_color="transparent", command=self._open_mods_folder).pack(side="right", padx=4)
        ctk.CTkButton(self.top_bar, text="Помощь", width=60, fg_color="transparent", command=self._show_help).pack(side="right", padx=4)
        ctk.CTkButton(self.top_bar, text="Выбрать…", width=90, command=self._pick_folder).pack(side="right", padx=4)
        ctk.CTkButton(self.top_bar, text="Обновить", width=80, command=self._refresh_list).pack(side="right")

        # --- Контент ---
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        # Вид «Список модов»
        self.frame_list = ctk.CTkFrame(self.content, fg_color="transparent")
        self.tabview = ctk.CTkTabview(self.frame_list, corner_radius=8)
        self.tabview.pack(fill="both", expand=True)
        self.tabview.add("Моды (JAR/ZIP)")
        self.tabview.add("Распакованные")
        mods_tab = self.tabview.tab("Моды (JAR/ZIP)")
        ext_tab = self.tabview.tab("Распакованные")
        ctk.CTkLabel(mods_tab, text="Выберите мод и нажмите «Перевести» или «Пакетный перевод» для всех.",
                     font=("", 11), text_color=("gray50", "gray70")).pack(anchor="w", pady=(0, 4))
        batch_f = ctk.CTkFrame(mods_tab, fg_color="transparent")
        batch_f.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(batch_f, text="Пакетный перевод (все моды)", width=180, command=self._batch_translate).pack(side="left", padx=(0, 8))
        self.mods_container = ctk.CTkScrollableFrame(mods_tab, fg_color="transparent")
        self.mods_container.pack(fill="both", expand=True, pady=4)
        ctk.CTkLabel(ext_tab, text="Уже распакованные моды — можно снова открыть перевод.",
                     font=("", 11), text_color=("gray50", "gray70")).pack(anchor="w", pady=(0, 8))
        self.ext_container = ctk.CTkScrollableFrame(ext_tab, fg_color="transparent")
        self.ext_container.pack(fill="both", expand=True, pady=4)

        # Вид «Перевод»
        self.frame_translate = ctk.CTkFrame(self.content, fg_color="transparent")
        trans_header = ctk.CTkFrame(self.frame_translate, fg_color=("gray90", "gray20"), corner_radius=8, height=52)
        trans_header.pack(fill="x", pady=(0, 10))
        trans_header.pack_propagate(False)
        trans_header_inner = ctk.CTkFrame(trans_header, fg_color="transparent")
        trans_header_inner.pack(fill="both", expand=True, padx=14, pady=10)
        self.btn_back = ctk.CTkButton(trans_header_inner, text="← К списку модов", width=140, fg_color="transparent", command=self._back_to_list)
        self.btn_back.pack(side="left", padx=(0, 16))
        self.translate_title = ctk.CTkLabel(trans_header_inner, text="", font=("", 14))
        self.translate_title.pack(side="left")
        ctk.CTkButton(trans_header_inner, text="Открыть папку мода", width=140, fg_color="transparent", command=self._open_extracted_folder).pack(side="right")
        trans_toolbar = ctk.CTkFrame(self.frame_translate, fg_color="transparent")
        trans_toolbar.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(trans_toolbar, text="Язык:").pack(side="left", padx=(0, 4))
        self.combo_source = ctk.CTkComboBox(trans_toolbar, values=["en", "auto"], width=70, command=lambda x: setattr(self, "_translate_source_lang", x))
        self.combo_source.pack(side="left", padx=(0, 8))
        self.combo_source.set("en")
        ctk.CTkLabel(trans_toolbar, text="→").pack(side="left", padx=4)
        self.combo_target = ctk.CTkComboBox(trans_toolbar, values=["ru"], width=50, command=lambda x: setattr(self, "_translate_target_lang", x))
        self.combo_target.pack(side="left", padx=(0, 12))
        ctk.CTkButton(trans_toolbar, text="Загрузить строки", width=120, command=self._load_strings).pack(side="left", padx=(0, 6))
        ctk.CTkButton(trans_toolbar, text="Перевести все", width=110, command=self._translate_all).pack(side="left", padx=(0, 6))
        ctk.CTkButton(trans_toolbar, text="Повторить неудачные", width=140, command=self._translate_all).pack(side="left", padx=(0, 6))
        ctk.CTkButton(trans_toolbar, text="Сохранить и собрать", width=150, command=self._save_and_pack).pack(side="left", padx=(0, 12))
        ctk.CTkCheckBox(trans_toolbar, text="Удалить распакованную папку после сборки", variable=self._translate_cleanup_after_pack, width=260).pack(side="left")
        trans_filter = ctk.CTkFrame(self.frame_translate, fg_color="transparent")
        trans_filter.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(trans_filter, text="Поиск:").pack(side="left", padx=(0, 6))
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._apply_search_filter())
        self.entry_search = ctk.CTkEntry(trans_filter, width=200, placeholder_text="по исходному тексту или переводу", textvariable=self.search_var)
        self.entry_search.pack(side="left", padx=(0, 12))
        self.filter_untranslated_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(trans_filter, text="Только без перевода", variable=self.filter_untranslated_var, command=self._apply_search_filter).pack(side="left", padx=(0, 8))
        self.progress_label = ctk.CTkLabel(trans_filter, text="", font=("", 11), text_color=("gray50", "gray70"))
        self.progress_label.pack(side="left", padx=(12, 0))
        self.translate_scroll = ctk.CTkScrollableFrame(self.frame_translate, fg_color="transparent")
        self.translate_scroll.pack(fill="both", expand=True)
        ctk.CTkLabel(self.translate_scroll, text="Нажмите «Загрузить строки» — список текстов подгрузится, совпадения из памяти переводов подставятся автоматически.",
                     text_color=("gray50", "gray70")).pack(anchor="w")

        self.frame_list.pack(fill="both", expand=True)
        self._refresh_list()

    def _open_mods_folder(self):
        p = self.mods_path
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(p)
        else:
            messagebox.showinfo("Папка", str(p))

    def _open_extracted_folder(self):
        if not self._translate_extracted_path or not self._translate_extracted_path.is_dir():
            messagebox.showwarning("Внимание", "Нет открытой папки мода.")
            return
        if os.name == "nt":
            os.startfile(self._translate_extracted_path)
        else:
            messagebox.showinfo("Папка", str(self._translate_extracted_path))

    def _save_mods_path(self):
        _save_config({"mods_path": str(self.mods_path)})

    def _show_help(self):
        w = ctk.CTkToplevel(self)
        w.title("Помощь")
        w.geometry("500x520")
        w.resizable(True, True)
        scroll = ctk.CTkScrollableFrame(w, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=16)
        text = """Инструкция по использованию

1. Папка модов
   • По умолчанию — папка mods рядом с программой. Выбранная папка сохраняется между запусками.
   • «Выбрать…» — указать другую папку с JAR/ZIP модами.
   • «Открыть папку» — открыть текущую папку модов в проводнике.

2. Список модов
   • Вкладка «Моды (JAR/ZIP)» — архивы модов. «Перевести» — открыть панель перевода для одного мода.
   • «Пакетный перевод» — по очереди: распаковка, автоперевод, сохранение и сборка _rus для каждого мода в списке.
   • Вкладка «Распакованные» — моды из mods/.extracted/. Можно снова открыть перевод.

3. Панель перевода
   • «Загрузить строки» — собрать все тексты (manifest, .lang, .ui, JSON). Совпадения из памяти переводов подставляются автоматически.
   • Язык: исходный (en / auto) и целевой (ru).
   • Поиск — фильтр по исходному тексту или переводу. «Только без перевода» — скрыть уже заполненные.
   • «Перевести все» — автоперевод пустых полей (Google / MyMemory). Во время перевода показывается прогресс.
   • «Повторить неудачные» — снова перевести только пустые поля (например после сбоя сети).
   • «Сохранить и собрать» — записать переводы в файлы и собрать мод в архив с суффиксом _rus (оригинал не трогается).
   • «Удалить распакованную папку после сборки» — очистить mods/.extracted/<имя_мода>/ после успешной сборки.
   • «Открыть папку мода» — открыть распакованную папку в проводнике.

4. Память переводов
   • В папке модов создаётся файл translation_memory.json. При загрузке строк совпадающие фразы подставляются из памяти.
   • При сохранении и сборке новые переводы добавляются в память. Так повторяющиеся фразы в разных модах переводятся один раз.

5. «← К списку модов» — вернуться к списку.

Разработчик (GitHub):"""
        ctk.CTkLabel(scroll, text=text, anchor="w", justify="left", wraplength=450).pack(anchor="w")
        link = ctk.CTkLabel(scroll, text=GITHUB_URL, anchor="w", text_color=("blue", "lightblue"), cursor="hand2")
        link.pack(anchor="w", pady=(4, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(GITHUB_URL))
        ctk.CTkButton(w, text="Закрыть", width=100, command=w.destroy).pack(pady=(0, 12))

    def _pick_folder(self):
        path = filedialog.askdirectory(initialdir=str(self.mods_path))
        if path:
            self.mods_path = Path(path)
            self.path_label.configure(text=str(self.mods_path))
            self._save_mods_path()
            self._refresh_list()

    def _apply_search_filter(self):
        if not self._translate_rows or len(self._translate_entries) != len(self._translate_rows):
            return
        q = (self.search_var.get() or "").strip().lower()
        only_empty = self.filter_untranslated_var.get()
        for i, (r, e, frame) in enumerate(zip(self._translate_rows, self._translate_entries, self._translate_row_frames)):
            src = (r.get("source") or "").lower()
            tr = (e.get() or "").lower()
            show = True
            if q and q not in src and q not in tr:
                show = False
            if only_empty and (e.get() or "").strip():
                show = False
            if show:
                frame.pack(fill="x", pady=2)
            else:
                frame.pack_forget()
        self._update_progress_label()

    def _update_progress_label(self):
        if not self._translate_rows:
            self.progress_label.configure(text="")
            return
        total = len(self._translate_rows)
        filled = sum(1 for e in self._translate_entries if (e.get() or "").strip())
        self.progress_label.configure(text=f"Заполнено: {filled} / {total}")

    def _refresh_list(self):
        for r in self.mod_rows:
            r.destroy()
        self.mod_rows.clear()
        for r in self.extracted_rows:
            r.destroy()
        self.extracted_rows.clear()
        for mod in mm.scan_mods(self.mods_path):
            row = ctk.CTkFrame(self.mods_container, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=mod["name"], width=320, anchor="w").pack(side="left", padx=(0, 12))
            ctk.CTkButton(row, text="Перевести", width=100, command=lambda m=mod: self._open_translate(m, None)).pack(side="left", padx=4)
            self.mod_rows.append(row)
        for ext in mm.get_extracted_mods(self.mods_path):
            row = ctk.CTkFrame(self.ext_container, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=ext["name"], width=320, anchor="w").pack(side="left", padx=(0, 12))
            ctk.CTkButton(row, text="Перевести", width=100, command=lambda e=ext: self._open_translate_extracted(e)).pack(side="left", padx=4)
            self.extracted_rows.append(row)

    def _batch_translate(self):
        mods = mm.scan_mods(self.mods_path)
        if not mods:
            messagebox.showinfo("Пакетный перевод", "Нет модов в папке.")
            return
        if not messagebox.askyesno("Пакетный перевод", f"Перевести все {len(mods)} модов?\nДля каждого: распаковка → автоперевод → сохранение и сборка _rus."):
            return
        try:
            from deep_translator import GoogleTranslator
        except ImportError:
            messagebox.showerror("Ошибка", "Установите: pip install deep-translator")
            return
        self._batch_cancelled = False
        ok, fail = 0, 0
        for mod in mods:
            if self._batch_cancelled:
                break
            try:
                extracted = mm.extract_mod(mod["path"], self.mods_path, mod["name"])
                rows = tm.collect_all_strings(extracted)
                memory = _load_translation_memory(self.mods_path)
                for r in rows:
                    if r["source"] in memory:
                        r["translated"] = memory[r["source"]]
                need_tr = [r for r in rows if not (r.get("translated") or "").strip()]
                for r in need_tr:
                    tr, _ = _auto_translate(r["source"], "en", "ru", memory=memory)
                    if tr:
                        r["translated"] = tr
                    time.sleep(0.15)
                for r in rows:
                    if (r.get("translated") or "").strip():
                        memory[r["source"]] = r["translated"]
                _save_translation_memory(self.mods_path, memory)
                tm.save_all_translations(extracted, rows)
                out_path = mod["path"].parent / f"{mod['path'].stem}_rus{mod['path'].suffix}"
                if mm.pack_mod(extracted, out_path, backup=False):
                    ok += 1
                self.update_idletasks()
            except Exception as e:
                fail += 1
                self.update_idletasks()
        messagebox.showinfo("Пакетный перевод", f"Готово. Успешно: {ok}, ошибок: {fail}.")

    def _open_translate(self, mod: dict, extracted_path: Path | None):
        if extracted_path and extracted_path.is_dir():
            self._translate_extracted_path = extracted_path
        else:
            try:
                self._translate_extracted_path = mm.extract_mod(mod["path"], self.mods_path, mod["name"])
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось распаковать: {e}")
                return
        self._translate_mod = mod
        self._translate_title_update()
        self._switch_to_translate_view()

    def _open_translate_extracted(self, ext: dict):
        name = ext["name"]
        archive = None
        for p in self.mods_path.iterdir():
            if p.suffix.lower() in (".jar", ".zip") and mm.safe_mod_name(p.stem) == name:
                archive = p
                break
        if not archive:
            for p in self.mods_path.iterdir():
                if p.suffix.lower() in (".jar", ".zip") and name.replace("_", "-") in p.stem:
                    archive = p
                    break
        mod = {"path": archive or (self.mods_path / f"{name}.jar"), "name": name, "type": "jar", "manifest": None}
        self._open_translate(mod, ext["path"])

    def _translate_title_update(self):
        if self._translate_mod and self._translate_extracted_path:
            self.translate_title.configure(text=f"Мод: {self._translate_mod['name']}  ·  {self._translate_extracted_path.name}")

    def _switch_to_translate_view(self):
        self.frame_list.pack_forget()
        self.frame_translate.pack(fill="both", expand=True)
        self.geometry(f"{SIZE_TRANSLATE[0]}x{SIZE_TRANSLATE[1]}")
        self._translate_rows.clear()
        for w in self._translate_entries:
            w.destroy()
        self._translate_entries.clear()
        self._translate_row_frames.clear()
        for w in self.translate_scroll.winfo_children():
            w.destroy()
        self.progress_label.configure(text="")
        ctk.CTkLabel(self.translate_scroll, text="Нажмите «Загрузить строки» — список текстов подгрузится, совпадения из памяти подставятся.",
                     text_color=("gray50", "gray70")).pack(anchor="w")

    def _back_to_list(self):
        self.frame_translate.pack_forget()
        self.frame_list.pack(fill="both", expand=True)
        self.geometry(f"{SIZE_LIST[0]}x{SIZE_LIST[1]}")
        self._translate_mod = None
        self._translate_extracted_path = None
        self._refresh_list()

    def _load_strings(self):
        if not self._translate_extracted_path or not self._translate_extracted_path.is_dir():
            messagebox.showwarning("Внимание", "Сначала выберите мод и нажмите «Перевести».")
            return
        for w in self._translate_entries:
            w.destroy()
        self._translate_entries.clear()
        self._translate_row_frames.clear()
        self._translate_rows = tm.collect_all_strings(self._translate_extracted_path)
        memory = _load_translation_memory(self.mods_path)
        for r in self._translate_rows:
            if r["source"] in memory:
                r["translated"] = memory[r["source"]]
        for w in self.translate_scroll.winfo_children():
            w.destroy()
        if not self._translate_rows:
            ctk.CTkLabel(self.translate_scroll, text="Строк не найдено.", text_color=("gray50", "gray70")).pack(anchor="w")
            return
        ctk.CTkLabel(self.translate_scroll, text=f"Найдено строк: {len(self._translate_rows)}. Поиск и фильтр выше. Заполните перевод или «Перевести все».",
                     font=("", 11), text_color=("gray60", "gray75")).pack(anchor="w", pady=(0, 8))
        for r in self._translate_rows:
            row_f = ctk.CTkFrame(self.translate_scroll, fg_color=("gray92", "gray28"), corner_radius=6, height=40)
            row_f.pack(fill="x", pady=2)
            row_f.pack_propagate(False)
            row_f_inner = ctk.CTkFrame(row_f, fg_color="transparent")
            row_f_inner.pack(fill="both", expand=True, padx=10, pady=6)
            src = (r.get("source") or "")[:55] + ("…" if len((r.get("source") or "")) > 55 else "")
            ctk.CTkLabel(row_f_inner, text=src, width=360, anchor="w", wraplength=350).pack(side="left", padx=(0, 10))
            e = ctk.CTkEntry(row_f_inner, width=380, placeholder_text="перевод", height=28)
            if r.get("translated"):
                e.insert(0, r["translated"])
            e.pack(side="left", fill="x", expand=True, padx=4)
            e.bind("<KeyRelease>", lambda *a: self._update_progress_label())
            self._translate_entries.append(e)
            self._translate_row_frames.append(row_f)
        self._apply_search_filter()

    def _translate_all(self):
        if not self._translate_rows or len(self._translate_entries) != len(self._translate_rows):
            messagebox.showwarning("Внимание", "Сначала загрузите строки.")
            return
        try:
            from deep_translator import GoogleTranslator
        except ImportError:
            messagebox.showerror("Ошибка", "Установите: pip install deep-translator")
            return
        src_lang = self._translate_source_lang
        tgt_lang = self._translate_target_lang
        total = len(self._translate_rows)
        ok, fail, done = 0, 0, 0
        last_error = None
        memory = _load_translation_memory(self.mods_path)
        for r, e in zip(self._translate_rows, self._translate_entries):
            if (e.get() or "").strip():
                done += 1
                continue
            src = (r.get("source") or "").strip()
            if not src:
                continue
            self.progress_label.configure(text=f"Перевод: {done + ok + fail} / {total}")
            self.update_idletasks()
            tr, err = _auto_translate(src, src_lang, tgt_lang, memory=memory)
            if err:
                last_error = err
            if tr:
                e.delete(0, "end")
                e.insert(0, tr)
                ok += 1
            else:
                fail += 1
            done += 1
            time.sleep(0.2)
        _save_translation_memory(self.mods_path, memory)
        self._update_progress_label()
        msg = f"Переведено: {ok}."
        if fail:
            msg += f" Не удалось: {fail}."
            if last_error:
                msg += f"\n{last_error[:100]}"
        messagebox.showinfo("Перевод", msg)

    def _save_and_pack(self):
        if not self._translate_mod or not self._translate_extracted_path:
            messagebox.showwarning("Внимание", "Нет открытого мода.")
            return
        if not self._translate_rows or len(self._translate_entries) != len(self._translate_rows):
            messagebox.showwarning("Внимание", "Сначала загрузите строки.")
            return
        for r, e in zip(self._translate_rows, self._translate_entries):
            r["translated"] = e.get().strip()
        memory = _load_translation_memory(self.mods_path)
        for r in self._translate_rows:
            if (r.get("translated") or "").strip():
                memory[r["source"]] = r["translated"]
        _save_translation_memory(self.mods_path, memory)
        tm.save_all_translations(self._translate_extracted_path, self._translate_rows)
        orig = self._translate_mod["path"]
        out_path = orig.parent / f"{orig.stem}_rus{orig.suffix}"
        if mm.pack_mod(self._translate_extracted_path, out_path, backup=False):
            if self._translate_cleanup_after_pack.get() and self._translate_extracted_path.is_dir():
                try:
                    shutil.rmtree(self._translate_extracted_path)
                except Exception:
                    pass
            messagebox.showinfo("Готово", f"Мод собран:\n{out_path.name}")
        else:
            messagebox.showwarning("Сохранено", "Переводы записаны. Сборка в архив не удалась.")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
