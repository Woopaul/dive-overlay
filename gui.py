"""
Dive Video Overlay Generator — GUI frontend (tkinter)
Generates SRT subtitle files from dive computer data + video files.
Supports Garmin .fit, UDDF .uddf, and CSV files, and batch video processing.
"""

import threading
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from csv_parser import CsvConfigRequired
from fit_parser import parse_dive_file, parse_csv_with_config, build_lookup
from srt_generator import generate_srt
from video_meta import get_video_meta, infer_station_name

VIDEO_TYPES = [
    ("Video files", "*.mp4 *.MP4 *.mov *.MOV *.avi *.AVI *.mkv *.MKV"),
    ("All files", "*.*"),
]
DIVE_TYPES = [
    ("Dive computer files", "*.fit *.FIT *.uddf *.UDDF *.xml *.XML *.csv *.CSV"),
    ("Garmin FIT", "*.fit *.FIT"),
    ("UDDF", "*.uddf *.UDDF *.xml *.XML"),
    ("CSV", "*.csv *.CSV"),
    ("All files", "*.*"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Dive Video Overlay Generator")
        self.resizable(True, False)
        self._build_ui()
        self._center_window()

    # ------------------------------------------------------------------ layout

    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        frame = ttk.Frame(self, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        # ── Video file list ──────────────────────────────────────────────────
        ttk.Label(frame, text="Video files").grid(row=0, column=0, sticky="nw", **pad)

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=0, column=1, sticky="ew", **pad)
        list_frame.columnconfigure(0, weight=1)

        self.video_list = tk.Listbox(list_frame, height=5, selectmode=tk.EXTENDED, width=50)
        self.video_list.grid(row=0, column=0, sticky="ew")
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.video_list.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.video_list.configure(yscrollcommand=sb.set)

        btn_frame = ttk.Frame(list_frame)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(btn_frame, text="Add files…", command=self._add_videos).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Remove selected", command=self._remove_videos).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Clear all", command=self._clear_videos).pack(side="left")

        # ── FIT file ─────────────────────────────────────────────────────────
        ttk.Label(frame, text="Dive file (.fit / .uddf / .csv / .xml)").grid(row=1, column=0, sticky="w", **pad)
        fit_row = ttk.Frame(frame)
        fit_row.grid(row=1, column=1, sticky="ew", **pad)
        fit_row.columnconfigure(0, weight=1)
        self.fit_var = tk.StringVar()
        ttk.Entry(fit_row, textvariable=self.fit_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(fit_row, text="Browse…", command=self._pick_fit).grid(row=0, column=1, padx=(6, 0))

        # ── Station name ─────────────────────────────────────────────────────
        ttk.Label(frame, text="Station name").grid(row=2, column=0, sticky="w", **pad)
        station_row = ttk.Frame(frame)
        station_row.grid(row=2, column=1, sticky="ew", **pad)
        self.station_var = tk.StringVar()
        ttk.Entry(station_row, textvariable=self.station_var, width=30).pack(side="left")
        ttk.Label(station_row, text="  (leave empty to use each video's folder name)", foreground="gray").pack(side="left")

        # ── UTC offset ───────────────────────────────────────────────────────
        ttk.Label(frame, text="UTC offset (hours)").grid(row=3, column=0, sticky="w", **pad)
        offset_row = ttk.Frame(frame)
        offset_row.grid(row=3, column=1, sticky="w", **pad)
        self.offset_var = tk.StringVar(value="9")
        ttk.Entry(offset_row, textvariable=self.offset_var, width=8).pack(side="left")
        ttk.Label(offset_row, text="  e.g. 9 = KST", foreground="gray").pack(side="left")

        # ── Time shift ───────────────────────────────────────────────────────
        ttk.Label(frame, text="Time shift (seconds)").grid(row=4, column=0, sticky="w", **pad)
        shift_row = ttk.Frame(frame)
        shift_row.grid(row=4, column=1, sticky="w", **pad)
        self.shift_var = tk.StringVar(value="0")
        ttk.Entry(shift_row, textvariable=self.shift_var, width=8).pack(side="left")
        ttk.Label(shift_row, text="  양수: 카메라가 다이빙 컴퓨터보다 빠름  /  음수: 느림", foreground="gray").pack(side="left")

        ttk.Separator(frame, orient="horizontal").grid(row=5, column=0, columnspan=3, sticky="ew", pady=8)

        # ── Progress bar ─────────────────────────────────────────────────────
        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.grid(row=6, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 4))

        # ── Generate button ───────────────────────────────────────────────────
        self.btn = ttk.Button(frame, text="Generate SRT", command=self._run)
        self.btn.grid(row=7, column=0, columnspan=3, pady=(0, 8))

        # ── Log area ──────────────────────────────────────────────────────────
        self.log = scrolledtext.ScrolledText(
            frame, height=12, width=68, state="disabled", font=("Courier", 11)
        )
        self.log.grid(row=8, column=0, columnspan=3, padx=10, pady=(0, 4))
        self.log.tag_config("ok", foreground="#007700")
        self.log.tag_config("warn", foreground="#BB6600")
        self.log.tag_config("err", foreground="#CC0000")

    def _center_window(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    # ------------------------------------------------------------------ video list management

    def _add_videos(self):
        paths = filedialog.askopenfilenames(title="Select video files", filetypes=VIDEO_TYPES)
        existing = set(self.video_list.get(0, "end"))
        for p in paths:
            if p not in existing:
                self.video_list.insert("end", p)
        if paths and not self.station_var.get():
            self.station_var.set(infer_station_name(paths[0]))

    def _remove_videos(self):
        for idx in reversed(self.video_list.curselection()):
            self.video_list.delete(idx)

    def _clear_videos(self):
        self.video_list.delete(0, "end")

    def _pick_fit(self):
        path = filedialog.askopenfilename(title="Select dive computer file (.fit or .uddf)", filetypes=DIVE_TYPES)
        if path:
            self.fit_var.set(path)

    # ------------------------------------------------------------------ logging

    def _log(self, msg: str, tag: str = ""):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------------ run

    def _run(self):
        videos = list(self.video_list.get(0, "end"))
        fit = self.fit_var.get().strip()

        if not videos:
            messagebox.showerror("Missing input", "Please add at least one video file.")
            return
        if not fit:
            messagebox.showerror("Missing input", "Please select a FIT file.")
            return
        try:
            offset = float(self.offset_var.get())
            shift = float(self.shift_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "UTC offset and time shift must be numbers.")
            return

        self._clear_log()
        self.btn.configure(state="disabled")
        self.progress["value"] = 0
        self.progress["maximum"] = len(videos)
        threading.Thread(
            target=self._batch_process,
            args=(videos, fit, self.station_var.get().strip(), offset, shift),
            daemon=True,
        ).start()

    # ------------------------------------------------------------------ processing

    def _batch_process(self, videos: list[str], fit: str, station: str, offset: float, shift: float):
        try:
            fmt = Path(fit).suffix.upper().lstrip(".")
            self._log(f"Dive file ({fmt}): {fit}")
            self._log("Parsing dive file…")

            try:
                records = parse_dive_file(fit)
            except CsvConfigRequired as e:
                # Show column mapping dialog on the main thread and wait for result
                cfg_holder = [None]
                done_event = __import__("threading").Event()

                def ask():
                    dlg = CsvMappingDialog(self, e.detected)
                    cfg_holder[0] = dlg.result
                    done_event.set()

                self.after(0, ask)
                done_event.wait()

                if cfg_holder[0] is None:
                    self._log("취소됨.", "warn")
                    return
                records = parse_csv_with_config(fit, cfg_holder[0])

            if not records:
                self._log("ERROR: No dive records found.", "err")
                return

            self._log(f"  Records : {len(records)}")
            self._log(f"  Dive    : {records[0]['timestamp']} → {records[-1]['timestamp']}")
            self._log(f"  Depth   : {min(r['depth_m'] for r in records):.1f} – {max(r['depth_m'] for r in records):.1f} m")
            if shift != 0:
                self._log(f"  Time shift: {shift:+.0f}s (카메라 시계 보정)")

            lookup = build_lookup(records)

            ok_count = 0
            for i, video in enumerate(videos, 1):
                self._log(f"\n[{i}/{len(videos)}] {Path(video).name}")
                success = self._process_one(video, lookup, station, offset, shift)
                if success:
                    ok_count += 1
                self.progress["value"] = i

            self._log(f"\n{'─'*50}")
            self._log(
                f"✅  Finished: {ok_count}/{len(videos)} files processed successfully.",
                "ok" if ok_count == len(videos) else "warn",
            )

        except Exception as e:
            self._log(f"\n❌  Fatal error: {e}", "err")
        finally:
            self.btn.configure(state="normal")

    def _process_one(self, video: str, lookup: dict, station: str, offset: float, shift: float = 0.0) -> bool:
        try:
            meta = get_video_meta(video)
            if meta["creation_time"] is None:
                self._log("  ❌  No creation_time in metadata — skipping.", "err")
                return False

            self._log(f"  Start : {meta['creation_time']}  |  Duration: {meta['duration_s']:.0f}s")

            vid_station = station or infer_station_name(video)
            output_path = Path(video).with_suffix(".srt")

            generate_srt(
                output_path=output_path,
                station=vid_station,
                video_start=meta["creation_time"],
                duration_s=meta["duration_s"],
                dive_lookup=lookup,
                utc_offset_hours=offset,
                time_shift_s=shift,
            )

            correction = timedelta(seconds=shift)
            start = (meta["creation_time"] - correction).replace(microsecond=0)
            total = int(meta["duration_s"])
            matched = sum(1 for s in range(total) if (start + timedelta(seconds=s)) in lookup)
            pct = matched / total * 100 if total else 0

            if pct < 50:
                self._log(f"  ⚠️   Matched {matched}/{total}s ({pct:.0f}%) — check timestamps.", "warn")
            else:
                self._log(f"  ✅  Matched {matched}/{total}s ({pct:.0f}%)  →  {output_path.name}", "ok")
            return True

        except Exception as e:
            self._log(f"  ❌  Error: {e}", "err")
            return False


class CsvMappingDialog(tk.Toplevel):
    """Modal dialog for mapping CSV columns to time / depth / temperature."""

    def __init__(self, parent, detected: dict):
        super().__init__(parent)
        self.title("CSV Column Mapping")
        self.resizable(False, False)
        self.grab_set()  # modal
        self.result = None  # filled on OK

        headers = detected.get("headers", [])
        none_option = "(없음 / None)"
        choices = [none_option] + headers

        pad = {"padx": 10, "pady": 5}
        ttk.Label(self, text="CSV 컬럼을 각 항목에 매핑해주세요.", font=("", 11, "bold")).grid(
            row=0, column=0, columnspan=2, padx=10, pady=(12, 6), sticky="w"
        )

        # Time column
        ttk.Label(self, text="시간 컬럼").grid(row=1, column=0, sticky="w", **pad)
        self.time_var = tk.StringVar(value=detected.get("time") or none_option)
        ttk.Combobox(self, textvariable=self.time_var, values=choices, state="readonly", width=30).grid(
            row=1, column=1, **pad
        )

        # Time mode
        ttk.Label(self, text="시간 형식").grid(row=2, column=0, sticky="w", **pad)
        self.mode_var = tk.StringVar(value=detected.get("time_mode", "absolute"))
        mode_frame = ttk.Frame(self)
        mode_frame.grid(row=2, column=1, sticky="w", **pad)
        ttk.Radiobutton(mode_frame, text="절대 시각 (날짜/시간 문자열)", variable=self.mode_var,
                        value="absolute", command=self._toggle_dive_start).pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="상대 시간 (경과 초)", variable=self.mode_var,
                        value="relative", command=self._toggle_dive_start).pack(anchor="w")

        # Dive start (only needed for relative mode)
        ttk.Label(self, text="다이브 시작 시각 (UTC)").grid(row=3, column=0, sticky="w", **pad)
        self.dive_start_var = tk.StringVar(value="2024-07-15 09:00:00")
        self.dive_start_entry = ttk.Entry(self, textvariable=self.dive_start_var, width=22)
        self.dive_start_entry.grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(self, text="형식: YYYY-MM-DD HH:MM:SS", foreground="gray").grid(
            row=4, column=1, sticky="w", padx=10, pady=(0, 4)
        )

        # Depth column
        ttk.Label(self, text="수심 컬럼 (m)").grid(row=5, column=0, sticky="w", **pad)
        self.depth_var = tk.StringVar(value=detected.get("depth") or none_option)
        ttk.Combobox(self, textvariable=self.depth_var, values=choices, state="readonly", width=30).grid(
            row=5, column=1, **pad
        )

        # Temperature column
        ttk.Label(self, text="수온 컬럼 (°C)").grid(row=6, column=0, sticky="w", **pad)
        self.temp_var = tk.StringVar(value=detected.get("temp") or none_option)
        ttk.Combobox(self, textvariable=self.temp_var, values=choices, state="readonly", width=30).grid(
            row=6, column=1, **pad
        )

        ttk.Separator(self, orient="horizontal").grid(row=7, column=0, columnspan=2, sticky="ew", pady=8)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=8, column=0, columnspan=2, pady=(0, 10))
        ttk.Button(btn_frame, text="확인", command=self._ok, width=12).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="취소", command=self.destroy, width=12).pack(side="left", padx=6)

        self._toggle_dive_start()
        self._center(parent)
        self.wait_window()

    def _toggle_dive_start(self):
        state = "normal" if self.mode_var.get() == "relative" else "disabled"
        self.dive_start_entry.configure(state=state)

    def _ok(self):
        none_option = "(없음 / None)"
        time_col = self.time_var.get()
        depth_col = self.depth_var.get()
        temp_col = self.temp_var.get()

        if time_col == none_option:
            messagebox.showerror("입력 오류", "시간 컬럼을 선택해주세요.", parent=self)
            return
        if depth_col == none_option:
            messagebox.showerror("입력 오류", "수심 컬럼을 선택해주세요.", parent=self)
            return

        cfg = {
            "time_col": time_col,
            "depth_col": depth_col,
            "temp_col": None if temp_col == none_option else temp_col,
            "time_mode": self.mode_var.get(),
        }

        if self.mode_var.get() == "relative":
            raw = self.dive_start_var.get().strip()
            try:
                dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                cfg["dive_start"] = dt
            except ValueError:
                messagebox.showerror("입력 오류", "다이브 시작 시각 형식이 잘못됐습니다.\n예: 2024-07-15 09:00:00", parent=self)
                return

        self.result = cfg
        self.destroy()

    def _center(self, parent):
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")


if __name__ == "__main__":
    app = App()
    app.mainloop()
