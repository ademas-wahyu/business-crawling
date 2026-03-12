import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ModuleNotFoundError:
    tk = None
    filedialog = messagebox = scrolledtext = ttk = None

from .app import LeadFinderService, load_niche_payload, save_niche_payload
from .defaults import (
    DEFAULT_DB_PATH,
    DEFAULT_EXCLUSION_KEYWORDS,
    DEFAULT_NICHE_PACKS_PATH,
    WORKFLOW_STATUSES,
)
from .models import LeadFilters, ScrapeConfig
from .utils import parse_multiline_text


class LeadFinderGUI:
    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        self.root.title("Lead Finder Website")
        self.root.geometry("1260x860")

        self.service = LeadFinderService(logger=self._push_log)
        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.current_rows: dict[int, dict[str, object]] = {}
        self.niche_payload = load_niche_payload(DEFAULT_NICHE_PACKS_PATH)

        self.db_path_var = tk.StringVar(value=DEFAULT_DB_PATH)
        self.niche_path_var = tk.StringVar(value=DEFAULT_NICHE_PACKS_PATH)
        self.max_scrolls_var = tk.IntVar(value=18)
        self.max_results_var = tk.IntVar(value=250)
        self.scroll_pause_var = tk.DoubleVar(value=1.5)
        self.detail_pause_var = tk.DoubleVar(value=2.0)
        self.stagnation_var = tk.IntVar(value=3)
        self.request_timeout_var = tk.DoubleVar(value=8.0)
        self.max_retries_var = tk.IntVar(value=2)
        self.audit_workers_var = tk.IntVar(value=5)
        self.audit_stale_days_var = tk.IntVar(value=14)
        self.headless_var = tk.BooleanVar(value=True)
        self.expand_locations_var = tk.BooleanVar(value=True)
        self.audit_var = tk.BooleanVar(value=True)
        self.export_path_var = tk.StringVar(value="shortlist_leads.csv")
        self.summary_var = tk.StringVar(value="Belum ada proses.")

        self.filter_city_var = tk.StringVar()
        self.filter_niche_var = tk.StringVar()
        self.filter_status_var = tk.StringVar()
        self.filter_tier_var = tk.StringVar()
        self.filter_website_var = tk.StringVar()
        self.filter_text_var = tk.StringVar()
        self.selected_lead_id: Optional[int] = None
        self.detail_workflow_var = tk.StringVar(value="new")
        self.mark_contacted_var = tk.BooleanVar(value=False)
        self.detail_name_var = tk.StringVar()
        self.detail_category_var = tk.StringVar()
        self.detail_city_var = tk.StringVar()
        self.detail_score_var = tk.StringVar()
        self.detail_website_var = tk.StringVar()
        self.detail_maps_var = tk.StringVar()

        self._build_layout()
        self._load_payload_into_ui()
        self._refresh_filter_values()
        self.refresh_inbox()
        self._poll_queue()

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(self.root)
        notebook.grid(row=0, column=0, sticky="nsew")

        self.search_tab = ttk.Frame(notebook, padding=12)
        self.inbox_tab = ttk.Frame(notebook, padding=12)
        self.export_tab = ttk.Frame(notebook, padding=12)
        notebook.add(self.search_tab, text="Pencarian")
        notebook.add(self.inbox_tab, text="Lead Inbox")
        notebook.add(self.export_tab, text="Ekspor")

        self._build_search_tab()
        self._build_inbox_tab()
        self._build_export_tab()

    def _build_search_tab(self) -> None:
        self.search_tab.columnconfigure(0, weight=1)
        self.search_tab.rowconfigure(3, weight=1)

        path_frame = ttk.LabelFrame(self.search_tab, text="File dan Database", padding=10)
        path_frame.grid(row=0, column=0, sticky="ew")
        for column in range(4):
            path_frame.columnconfigure(column, weight=1)

        ttk.Label(path_frame, text="SQLite DB").grid(row=0, column=0, sticky="w")
        ttk.Entry(path_frame, textvariable=self.db_path_var).grid(
            row=1, column=0, columnspan=3, sticky="ew", padx=(0, 8), pady=(4, 10)
        )
        ttk.Button(path_frame, text="Pilih DB", command=self._pick_db_path).grid(
            row=1, column=3, sticky="ew", pady=(4, 10)
        )

        ttk.Label(path_frame, text="Niche JSON").grid(row=2, column=0, sticky="w")
        ttk.Entry(path_frame, textvariable=self.niche_path_var).grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(4, 10)
        )
        ttk.Button(path_frame, text="Muat JSON", command=self._load_payload_file).grid(
            row=3, column=2, sticky="ew", padx=(0, 8), pady=(4, 10)
        )
        ttk.Button(path_frame, text="Simpan JSON", command=self._save_payload_file).grid(
            row=3, column=3, sticky="ew", pady=(4, 10)
        )

        content_frame = ttk.Frame(self.search_tab)
        content_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        content_frame.columnconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=1)
        content_frame.rowconfigure(0, weight=1)

        niche_frame = ttk.LabelFrame(content_frame, text="Niche Pack Aktif")
        niche_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        niche_frame.columnconfigure(0, weight=1)
        niche_frame.rowconfigure(1, weight=1)

        button_row = ttk.Frame(niche_frame)
        button_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        ttk.Button(button_row, text="Pilih Semua", command=self._select_all_packs).pack(side="left")
        ttk.Button(button_row, text="Kosongkan", command=self._clear_pack_selection).pack(
            side="left", padx=(8, 0)
        )

        self.pack_listbox = tk.Listbox(
            niche_frame,
            selectmode=tk.MULTIPLE,
            exportselection=False,
            height=10,
        )
        self.pack_listbox.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.pack_listbox.bind("<<ListboxSelect>>", self._update_pack_preview)

        preview_frame = ttk.LabelFrame(content_frame, text="Preview Pack dan Exclusion")
        preview_frame.grid(row=0, column=1, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)
        preview_frame.rowconfigure(3, weight=1)

        ttk.Label(
            preview_frame,
            text="Preview keyword pack terpilih. Untuk ubah pack, edit file JSON lalu klik Muat JSON.",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.pack_preview = scrolledtext.ScrolledText(preview_frame, height=10, wrap="word")
        self.pack_preview.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        ttk.Label(preview_frame, text="Exclusion keyword (1 baris 1 keyword)").grid(
            row=2, column=0, sticky="w", padx=8, pady=(0, 4)
        )
        self.exclusion_text = scrolledtext.ScrolledText(preview_frame, height=8, wrap="word")
        self.exclusion_text.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))

        settings_frame = ttk.LabelFrame(self.search_tab, text="Konfigurasi Pencarian", padding=10)
        settings_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        for column in range(4):
            settings_frame.columnconfigure(column, weight=1)

        ttk.Label(settings_frame, text="Wilayah (1 baris 1 kota)").grid(row=0, column=0, sticky="w")
        ttk.Label(settings_frame, text="Max scroll").grid(row=0, column=1, sticky="w")
        ttk.Label(settings_frame, text="Max hasil total").grid(row=0, column=2, sticky="w")
        ttk.Label(settings_frame, text="Batas stagnan").grid(row=0, column=3, sticky="w")

        self.location_text = scrolledtext.ScrolledText(settings_frame, height=6, wrap="word")
        self.location_text.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 10))
        self.location_text.insert("1.0", "Bandung\nCimahi\nKabupaten Bandung")
        ttk.Spinbox(settings_frame, from_=1, to=300, textvariable=self.max_scrolls_var).grid(
            row=1, column=1, sticky="ew", padx=(0, 8), pady=(4, 10)
        )
        ttk.Spinbox(settings_frame, from_=0, to=10000, textvariable=self.max_results_var).grid(
            row=1, column=2, sticky="ew", padx=(0, 8), pady=(4, 10)
        )
        ttk.Spinbox(settings_frame, from_=1, to=20, textvariable=self.stagnation_var).grid(
            row=1, column=3, sticky="ew", pady=(4, 10)
        )

        ttk.Label(settings_frame, text="Jeda scroll (detik)").grid(row=2, column=0, sticky="w")
        ttk.Label(settings_frame, text="Jeda detail (detik)").grid(row=2, column=1, sticky="w")
        ttk.Label(settings_frame, text="Timeout audit (detik)").grid(row=2, column=2, sticky="w")
        ttk.Label(settings_frame, text="Retry audit").grid(row=2, column=3, sticky="w")

        ttk.Spinbox(
            settings_frame,
            from_=0.5,
            to=10.0,
            increment=0.5,
            textvariable=self.scroll_pause_var,
        ).grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=(4, 10))
        ttk.Spinbox(
            settings_frame,
            from_=0.5,
            to=10.0,
            increment=0.5,
            textvariable=self.detail_pause_var,
        ).grid(row=3, column=1, sticky="ew", padx=(0, 8), pady=(4, 10))
        ttk.Spinbox(
            settings_frame,
            from_=1.0,
            to=30.0,
            increment=1.0,
            textvariable=self.request_timeout_var,
        ).grid(row=3, column=2, sticky="ew", padx=(0, 8), pady=(4, 10))
        ttk.Spinbox(settings_frame, from_=0, to=5, textvariable=self.max_retries_var).grid(
            row=3, column=3, sticky="ew", pady=(4, 10)
        )

        ttk.Label(settings_frame, text="Audit worker").grid(row=4, column=0, sticky="w")
        ttk.Label(settings_frame, text="Audit stale (hari)").grid(row=4, column=1, sticky="w")
        ttk.Spinbox(settings_frame, from_=1, to=20, textvariable=self.audit_workers_var).grid(
            row=5, column=0, sticky="ew", padx=(0, 8), pady=(4, 10)
        )
        ttk.Spinbox(settings_frame, from_=1, to=60, textvariable=self.audit_stale_days_var).grid(
            row=5, column=1, sticky="ew", padx=(0, 8), pady=(4, 10)
        )
        ttk.Checkbutton(
            settings_frame,
            text="Headless browser",
            variable=self.headless_var,
        ).grid(row=5, column=2, sticky="w", pady=(4, 10))
        ttk.Checkbutton(
            settings_frame,
            text="Ekspansi wilayah otomatis",
            variable=self.expand_locations_var,
        ).grid(row=5, column=3, sticky="w", pady=(4, 10))
        ttk.Checkbutton(
            settings_frame,
            text="Audit website setelah crawl",
            variable=self.audit_var,
        ).grid(row=6, column=3, sticky="w", pady=(0, 10))

        ttk.Label(
            settings_frame,
            text="0 pada max hasil berarti ambil semua lead yang sempat termuat di Maps.",
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 10))

        action_frame = ttk.Frame(self.search_tab)
        action_frame.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        action_frame.columnconfigure(0, weight=1)
        action_frame.rowconfigure(1, weight=1)

        action_bar = ttk.Frame(action_frame)
        action_bar.grid(row=0, column=0, sticky="ew")
        action_bar.columnconfigure(1, weight=1)
        self.start_button = ttk.Button(action_bar, text="Mulai Prospecting", command=self.start_search)
        self.start_button.grid(row=0, column=0, sticky="w")
        ttk.Label(action_bar, textvariable=self.summary_var).grid(row=0, column=1, sticky="e")

        log_frame = ttk.LabelFrame(action_frame, text="Log proses")
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_widget = scrolledtext.ScrolledText(log_frame, height=14, wrap="word", state="disabled")
        self.log_widget.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _build_inbox_tab(self) -> None:
        self.inbox_tab.columnconfigure(0, weight=1)
        self.inbox_tab.rowconfigure(1, weight=1)

        filter_frame = ttk.LabelFrame(self.inbox_tab, text="Filter Lead", padding=10)
        filter_frame.grid(row=0, column=0, sticky="ew")
        for column in range(7):
            filter_frame.columnconfigure(column, weight=1)

        ttk.Label(filter_frame, text="City").grid(row=0, column=0, sticky="w")
        ttk.Label(filter_frame, text="Niche").grid(row=0, column=1, sticky="w")
        ttk.Label(filter_frame, text="Status").grid(row=0, column=2, sticky="w")
        ttk.Label(filter_frame, text="Tier").grid(row=0, column=3, sticky="w")
        ttk.Label(filter_frame, text="Website").grid(row=0, column=4, sticky="w")
        ttk.Label(filter_frame, text="Cari teks").grid(row=0, column=5, sticky="w")

        self.city_filter_combo = ttk.Combobox(filter_frame, textvariable=self.filter_city_var, state="readonly")
        self.city_filter_combo.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 10))
        self.niche_filter_combo = ttk.Combobox(filter_frame, textvariable=self.filter_niche_var, state="readonly")
        self.niche_filter_combo.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(4, 10))
        self.status_filter_combo = ttk.Combobox(filter_frame, textvariable=self.filter_status_var, state="readonly")
        self.status_filter_combo.grid(row=1, column=2, sticky="ew", padx=(0, 8), pady=(4, 10))
        self.tier_filter_combo = ttk.Combobox(filter_frame, textvariable=self.filter_tier_var, state="readonly")
        self.tier_filter_combo.grid(row=1, column=3, sticky="ew", padx=(0, 8), pady=(4, 10))
        self.website_filter_combo = ttk.Combobox(filter_frame, textvariable=self.filter_website_var, state="readonly")
        self.website_filter_combo.grid(row=1, column=4, sticky="ew", padx=(0, 8), pady=(4, 10))
        ttk.Entry(filter_frame, textvariable=self.filter_text_var).grid(
            row=1, column=5, sticky="ew", padx=(0, 8), pady=(4, 10)
        )
        ttk.Button(filter_frame, text="Refresh", command=self.refresh_inbox).grid(
            row=1, column=6, sticky="ew", pady=(4, 10)
        )

        body_frame = ttk.PanedWindow(self.inbox_tab, orient=tk.HORIZONTAL)
        body_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

        table_frame = ttk.Frame(body_frame)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        body_frame.add(table_frame, weight=3)

        columns = (
            "id",
            "lead_tier",
            "lead_score",
            "nama_usaha",
            "niche_pack",
            "city",
            "website_status",
            "phone",
            "workflow_status",
        )
        self.inbox_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        headings = {
            "id": "ID",
            "lead_tier": "Tier",
            "lead_score": "Score",
            "nama_usaha": "Nama",
            "niche_pack": "Niche",
            "city": "City",
            "website_status": "Website",
            "phone": "Telepon",
            "workflow_status": "Workflow",
        }
        widths = {
            "id": 60,
            "lead_tier": 60,
            "lead_score": 70,
            "nama_usaha": 220,
            "niche_pack": 120,
            "city": 120,
            "website_status": 140,
            "phone": 140,
            "workflow_status": 120,
        }
        for column in columns:
            self.inbox_tree.heading(column, text=headings[column])
            self.inbox_tree.column(column, width=widths[column], anchor="w")
        self.inbox_tree.grid(row=0, column=0, sticky="nsew")
        self.inbox_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        detail_frame = ttk.LabelFrame(body_frame, text="Detail Lead", padding=10)
        detail_frame.columnconfigure(1, weight=1)
        body_frame.add(detail_frame, weight=2)

        ttk.Label(detail_frame, text="Nama").grid(row=0, column=0, sticky="w")
        ttk.Entry(detail_frame, textvariable=self.detail_name_var, state="readonly").grid(
            row=0, column=1, sticky="ew", pady=(0, 8)
        )
        ttk.Label(detail_frame, text="Kategori").grid(row=1, column=0, sticky="w")
        ttk.Entry(detail_frame, textvariable=self.detail_category_var, state="readonly").grid(
            row=1, column=1, sticky="ew", pady=(0, 8)
        )
        ttk.Label(detail_frame, text="City / Score").grid(row=2, column=0, sticky="w")
        ttk.Entry(detail_frame, textvariable=self.detail_city_var, state="readonly").grid(
            row=2, column=1, sticky="ew", pady=(0, 8)
        )
        ttk.Label(detail_frame, text="Ringkasan").grid(row=3, column=0, sticky="w")
        ttk.Entry(detail_frame, textvariable=self.detail_score_var, state="readonly").grid(
            row=3, column=1, sticky="ew", pady=(0, 8)
        )
        ttk.Label(detail_frame, text="Website").grid(row=4, column=0, sticky="w")
        ttk.Entry(detail_frame, textvariable=self.detail_website_var, state="readonly").grid(
            row=4, column=1, sticky="ew", pady=(0, 8)
        )
        ttk.Label(detail_frame, text="Maps URL").grid(row=5, column=0, sticky="w")
        ttk.Entry(detail_frame, textvariable=self.detail_maps_var, state="readonly").grid(
            row=5, column=1, sticky="ew", pady=(0, 8)
        )
        ttk.Label(detail_frame, text="Workflow").grid(row=6, column=0, sticky="w")
        self.detail_workflow_combo = ttk.Combobox(
            detail_frame,
            textvariable=self.detail_workflow_var,
            values=WORKFLOW_STATUSES,
            state="readonly",
        )
        self.detail_workflow_combo.grid(row=6, column=1, sticky="ew", pady=(0, 8))

        self.mark_contacted_check = ttk.Checkbutton(
            detail_frame,
            text="Tandai contacted sekarang",
            variable=self.mark_contacted_var,
        )
        self.mark_contacted_check.grid(row=7, column=1, sticky="w", pady=(0, 8))

        ttk.Label(detail_frame, text="Notes").grid(row=8, column=0, sticky="nw")
        self.notes_text = scrolledtext.ScrolledText(detail_frame, height=10, wrap="word")
        self.notes_text.grid(row=8, column=1, sticky="nsew", pady=(0, 8))
        detail_frame.rowconfigure(8, weight=1)

        ttk.Button(detail_frame, text="Simpan Update Lead", command=self.save_selected_lead).grid(
            row=9, column=1, sticky="e"
        )

    def _build_export_tab(self) -> None:
        self.export_tab.columnconfigure(0, weight=1)
        self.export_tab.rowconfigure(1, weight=1)

        frame = ttk.LabelFrame(self.export_tab, text="Ekspor Shortlist", padding=10)
        frame.grid(row=0, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text="Ekspor memakai filter aktif di tab Lead Inbox.",
        ).grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.export_path_var).grid(
            row=1, column=0, sticky="ew", padx=(0, 8), pady=(8, 0)
        )
        action_bar = ttk.Frame(frame)
        action_bar.grid(row=1, column=1, sticky="e", pady=(8, 0))
        ttk.Button(action_bar, text="Pilih File", command=self._pick_export_path).pack(side="left")
        ttk.Button(action_bar, text="Ekspor CSV", command=self.export_current_filters).pack(
            side="left", padx=(8, 0)
        )

        info = scrolledtext.ScrolledText(self.export_tab, height=10, wrap="word", state="normal")
        info.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        info.insert(
            "1.0",
            "Gunakan tab Lead Inbox untuk menyaring lead tier A/B, city, niche, dan workflow.\n"
            "Lalu klik Ekspor CSV di tab ini untuk menghasilkan shortlist siap dihubungi.",
        )
        info.config(state="disabled")

    def _load_payload_into_ui(self) -> None:
        self.pack_listbox.delete(0, tk.END)
        self.exclusion_text.delete("1.0", tk.END)

        packs = self.niche_payload.get("packs", {})
        for pack_name in packs.keys():
            self.pack_listbox.insert(tk.END, pack_name)

        for index in range(self.pack_listbox.size()):
            self.pack_listbox.selection_set(index)

        exclusions = self.niche_payload.get("excluded_keywords") or DEFAULT_EXCLUSION_KEYWORDS
        self.exclusion_text.insert("1.0", "\n".join(exclusions))
        self._update_pack_preview()

    def _load_payload_file(self) -> None:
        try:
            self.niche_payload = load_niche_payload(self.niche_path_var.get())
        except Exception as exc:
            messagebox.showerror("Gagal memuat JSON", str(exc))
            return
        self._load_payload_into_ui()
        self._push_log(f"Niche JSON dimuat dari {self.niche_path_var.get()}")

    def _save_payload_file(self) -> None:
        payload = {
            "packs": self.niche_payload.get("packs", {}),
            "excluded_keywords": parse_multiline_text(self.exclusion_text.get("1.0", tk.END)),
        }
        try:
            path = save_niche_payload(payload, self.niche_path_var.get())
        except Exception as exc:
            messagebox.showerror("Gagal simpan JSON", str(exc))
            return
        self.niche_payload = payload
        self._push_log(f"Niche JSON disimpan ke {path}")

    def _select_all_packs(self) -> None:
        self.pack_listbox.selection_set(0, tk.END)
        self._update_pack_preview()

    def _clear_pack_selection(self) -> None:
        self.pack_listbox.selection_clear(0, tk.END)
        self._update_pack_preview()

    def _selected_pack_names(self) -> list[str]:
        return [self.pack_listbox.get(index) for index in self.pack_listbox.curselection()]

    def _update_pack_preview(self, _event=None) -> None:
        packs = self.niche_payload.get("packs", {})
        selected = self._selected_pack_names()
        lines: list[str] = []
        for pack_name in selected:
            keywords = packs.get(pack_name, [])
            lines.append(f"[{pack_name}]")
            lines.extend(f"- {keyword}" for keyword in keywords)
            lines.append("")
        self.pack_preview.config(state="normal")
        self.pack_preview.delete("1.0", tk.END)
        self.pack_preview.insert("1.0", "\n".join(lines).strip() or "Belum ada pack terpilih.")
        self.pack_preview.config(state="disabled")

    def start_search(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Proses berjalan", "Tunggu proses yang sedang berjalan selesai.")
            return

        selected_packs = self._selected_pack_names()
        locations = parse_multiline_text(self.location_text.get("1.0", tk.END))
        exclusions = parse_multiline_text(self.exclusion_text.get("1.0", tk.END))
        if not selected_packs:
            messagebox.showerror("Pack kosong", "Pilih minimal satu niche pack.")
            return
        if not locations:
            messagebox.showerror("Wilayah kosong", "Isi minimal satu wilayah pencarian.")
            return

        config = ScrapeConfig(
            selected_niche_packs=selected_packs,
            niche_packs=dict(self.niche_payload.get("packs", {})),
            locations=locations,
            excluded_keywords=exclusions,
            db_path=self.db_path_var.get(),
            max_scrolls=int(self.max_scrolls_var.get()),
            max_results=int(self.max_results_var.get()),
            scroll_pause=float(self.scroll_pause_var.get()),
            detail_pause=float(self.detail_pause_var.get()),
            stagnation_limit=int(self.stagnation_var.get()),
            headless=bool(self.headless_var.get()),
            expand_locations=bool(self.expand_locations_var.get()),
            audit_websites=bool(self.audit_var.get()),
            request_timeout=float(self.request_timeout_var.get()),
            max_retries=int(self.max_retries_var.get()),
            audit_max_workers=int(self.audit_workers_var.get()),
            audit_stale_after_days=int(self.audit_stale_days_var.get()),
        )

        self._clear_log()
        self.summary_var.set("Proses berjalan...")
        self.start_button.config(state="disabled")
        self.worker = threading.Thread(target=self._run_search_worker, args=(config,), daemon=True)
        self.worker.start()

    def _run_search_worker(self, config: ScrapeConfig) -> None:
        try:
            summary = self.service.run_search(config)
            self.event_queue.put(("search_done", summary))
        except Exception as exc:
            self.event_queue.put(("error", str(exc)))

    def refresh_inbox(self) -> None:
        filters = self._current_filters()
        rows = self.service.list_leads(self.db_path_var.get(), filters)
        self.current_rows = {int(row["id"]): row for row in rows}

        for item in self.inbox_tree.get_children():
            self.inbox_tree.delete(item)

        for row in rows:
            self.inbox_tree.insert(
                "",
                tk.END,
                iid=str(row["id"]),
                values=(
                    row["id"],
                    row["lead_tier"],
                    row["lead_score"],
                    row["nama_usaha"],
                    row["niche_pack"],
                    row["city"],
                    row["website_status"],
                    row["phone"],
                    row["workflow_status"],
                ),
            )
        self._refresh_filter_values()

    def _refresh_filter_values(self) -> None:
        values = self.service.list_filter_values(self.db_path_var.get())
        self.city_filter_combo["values"] = [""] + values.get("city", [])
        self.niche_filter_combo["values"] = [""] + values.get("niche_pack", [])
        self.status_filter_combo["values"] = [""] + values.get("workflow_status", [])
        self.tier_filter_combo["values"] = [""] + values.get("lead_tier", [])
        self.website_filter_combo["values"] = [""] + values.get("website_status", [])

    def _current_filters(self) -> LeadFilters:
        return LeadFilters(
            city=self.filter_city_var.get().strip(),
            niche_pack=self.filter_niche_var.get().strip(),
            workflow_status=self.filter_status_var.get().strip(),
            lead_tier=self.filter_tier_var.get().strip(),
            website_status=self.filter_website_var.get().strip(),
            text_query=self.filter_text_var.get().strip(),
        )

    def _on_tree_select(self, _event=None) -> None:
        selection = self.inbox_tree.selection()
        if not selection:
            self.selected_lead_id = None
            return

        lead_id = int(selection[0])
        row = self.current_rows.get(lead_id)
        if not row:
            return

        self.selected_lead_id = lead_id
        self.detail_name_var.set(str(row.get("nama_usaha") or ""))
        self.detail_category_var.set(str(row.get("kategori") or ""))
        self.detail_city_var.set(str(row.get("city") or ""))
        self.detail_score_var.set(
            f"Tier {row.get('lead_tier')} | Score {row.get('lead_score')} | Website {row.get('website_status')}"
        )
        self.detail_website_var.set(str(row.get("website_url") or ""))
        self.detail_maps_var.set(str(row.get("maps_url") or ""))
        self.detail_workflow_var.set(str(row.get("workflow_status") or "new"))
        self.mark_contacted_var.set(False)
        self.notes_text.delete("1.0", tk.END)
        self.notes_text.insert("1.0", str(row.get("notes") or ""))

    def save_selected_lead(self) -> None:
        if self.selected_lead_id is None:
            messagebox.showinfo("Pilih lead", "Pilih lead di tabel terlebih dahulu.")
            return

        self.service.update_lead_workflow(
            self.db_path_var.get(),
            self.selected_lead_id,
            self.detail_workflow_var.get(),
            self.notes_text.get("1.0", tk.END),
            self.mark_contacted_var.get(),
        )
        self.mark_contacted_var.set(False)
        self.refresh_inbox()
        self._push_log(f"Lead {self.selected_lead_id} diperbarui.")

    def export_current_filters(self) -> None:
        output_path = self.export_path_var.get().strip()
        if not output_path:
            messagebox.showerror("Output kosong", "Isi nama file CSV untuk ekspor.")
            return

        path, total = self.service.export_leads(
            self.db_path_var.get(),
            self._current_filters(),
            output_path,
        )
        messagebox.showinfo("Ekspor selesai", f"{total} lead diekspor ke:\n{path}")
        self._push_log(f"Ekspor {total} lead ke {path}")

    def _pick_db_path(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Pilih file SQLite",
            defaultextension=".db",
            filetypes=[("SQLite DB", "*.db"), ("All Files", "*.*")],
        )
        if selected:
            self.db_path_var.set(selected)
            self.refresh_inbox()

    def _pick_export_path(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Simpan shortlist CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if selected:
            self.export_path_var.set(selected)

    def _push_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.event_queue.put(("log", f"[{timestamp}] {message}"))

    def _clear_log(self) -> None:
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.config(state="disabled")

    def _poll_queue(self) -> None:
        try:
            while True:
                event_type, payload = self.event_queue.get_nowait()
                if event_type == "log":
                    self.log_widget.config(state="normal")
                    self.log_widget.insert(tk.END, str(payload) + "\n")
                    self.log_widget.see(tk.END)
                    self.log_widget.config(state="disabled")
                elif event_type == "search_done":
                    summary = payload if isinstance(payload, dict) else {}
                    self.start_button.config(state="normal")
                    self.summary_var.set(
                        f"Run {summary.get('run_id')} selesai. Found {summary.get('total_found', 0)}, "
                        f"scored {summary.get('total_scored', 0)}."
                    )
                    self.refresh_inbox()
                elif event_type == "error":
                    self.start_button.config(state="normal")
                    self.summary_var.set("Terjadi error.")
                    messagebox.showerror("Proses gagal", str(payload))
        except queue.Empty:
            pass
        finally:
            self.root.after(200, self._poll_queue)


def launch_gui() -> None:
    if tk is None:
        raise RuntimeError("Tkinter tidak tersedia di Python ini.")

    root = tk.Tk()
    style = ttk.Style()
    if "clam" in style.theme_names():
        style.theme_use("clam")
    LeadFinderGUI(root)
    root.mainloop()
