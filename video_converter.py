import os
import re
import sys
import time
import ctypes
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinterdnd2 import DND_FILES, TkinterDnD


OUTPUT_FORMATS = {
    "MP4": ".mp4",
    "MOV": ".mov",
    "MKV": ".mkv",
    "AVI": ".avi",
    "MP3": ".mp3",
    "M4A": ".m4a",
    "WAV": ".wav"
}

# 避免打包成 --windowed 的 exe 后，调用 ffmpeg/ffprobe 时弹出黑色控制台窗口
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# 颜色定义
COLOR_DEFAULT = "#f0f0f0"
COLOR_SUCCESS = "#d4edda"
COLOR_FAILURE = "#f8d7da"

# 用于窗口关闭时能找到并终止正在运行的 ffmpeg 进程
current_process = None
current_output_path = None

# 当前已选中但还未开始转换的文件
selected_file_path = None


def get_app_dir():
    """返回 exe（或脚本）所在的文件夹，用作输出文件夹的默认值。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def set_dpi_awareness():
    """让程序自己处理高 DPI 缩放，避免界面被系统拉伸模糊。"""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def flash_taskbar():
    """转换完成后闪烁任务栏图标，提醒用户（即使窗口没有聚焦）。"""
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("hwnd", ctypes.c_void_p),
                ("dwFlags", ctypes.c_uint),
                ("uCount", ctypes.c_uint),
                ("dwTimeout", ctypes.c_uint),
            ]

        FLASHW_ALL = 3
        FLASHW_TIMERNOFG = 12

        params = FLASHWINFO(
            ctypes.sizeof(FLASHWINFO()),
            hwnd,
            FLASHW_ALL | FLASHW_TIMERNOFG,
            5,
            0
        )
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(params))
    except Exception:
        pass


def set_window_state_color(color):
    """把主窗口和各个区域的背景改成指定颜色，用来做完成/失败的视觉提示。"""
    root.configure(bg=color)
    for widget in (
        drop_area, percent_label, eta_label, status_label,
        top_label, output_folder_label, output_folder_row,
        output_folder_display
    ):
        widget.configure(bg=color)


def reset_window_color():
    set_window_state_color(COLOR_DEFAULT)


def get_duration(path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW
    )
    return float(result.stdout.strip())


def time_to_seconds(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def format_seconds(seconds):
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)

    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def convert_file(path):
    threading.Thread(target=convert_worker, args=(path,), daemon=True).start()


def convert_worker(path):
    global current_process, current_output_path

    selected_format = format_box.get()
    ext = OUTPUT_FORMATS[selected_format]

    base_name = os.path.splitext(os.path.basename(path))[0] + ext
    chosen_folder = output_folder_var.get().strip()
    if chosen_folder:
        output = os.path.join(chosen_folder, base_name)
    else:
        # 默认：和源文件放在同一个文件夹
        output = os.path.join(os.path.dirname(path), base_name)

    current_output_path = output
    reset_window_color()

    try:
        duration = get_duration(path)
    except Exception:
        messagebox.showerror("Error", "Could not read media duration.")
        set_window_state_color(COLOR_FAILURE)
        start_button.config(state="normal")
        select_button.config(state="normal")
        return

    if ext in [".mp3", ".m4a", ".wav"]:
        cmd = ["ffmpeg", "-y", "-i", path, "-vn", output]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            output
        ]

    start_time = time.time()

    progress_bar["value"] = 0
    percent_label.config(text="0%")
    eta_label.config(text="Estimated time remaining: calculating...")
    status_label.config(text=f"Converting: {os.path.basename(path)}")

    process = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="ignore",
        creationflags=CREATE_NO_WINDOW
    )
    current_process = process

    for line in process.stderr:
        match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
        if match:
            current = time_to_seconds(match.group(1))
            progress = min(current / duration * 100, 100)

            elapsed = time.time() - start_time
            if progress > 0:
                total_estimated = elapsed / (progress / 100)
                remaining = max(total_estimated - elapsed, 0)
                eta_text = format_seconds(remaining)
            else:
                eta_text = "calculating..."

            progress_bar["value"] = progress
            percent_label.config(text=f"{progress:.1f}%")
            eta_label.config(text=f"Estimated time remaining: {eta_text}")
            root.update_idletasks()

    process.wait()
    current_process = None

    if process.returncode == 0:
        progress_bar["value"] = 100
        percent_label.config(text="100%")
        eta_label.config(text="Estimated time remaining: 0s")
        status_label.config(text="Conversion completed")
        set_window_state_color(COLOR_SUCCESS)
        flash_taskbar()
        current_output_path = None
        start_button.config(state="normal")
        select_button.config(state="normal")
        messagebox.showinfo("Done", f"File created:\n{output}")
    else:
        status_label.config(text="Conversion failed")
        set_window_state_color(COLOR_FAILURE)
        flash_taskbar()
        start_button.config(state="normal")
        select_button.config(state="normal")
        messagebox.showerror("Conversion Failed", "Please check the file or FFmpeg installation.")


def choose_file():
    if current_process is not None:
        return
    path = filedialog.askopenfilename(
        title="Select a file",
        filetypes=[
            ("Media files", "*.ts *.mp4 *.mov *.mkv *.avi *.flv *.webm *.mp3 *.m4a *.wav"),
            ("All files", "*.*")
        ]
    )
    if path:
        set_selected_file(path)


def drop_file(event):
    if current_process is not None:
        return
    path = event.data.strip("{}")
    set_selected_file(path)


def set_selected_file(path):
    global selected_file_path
    selected_file_path = path
    reset_window_color()
    drop_area.config(text=f"Selected file:\n{os.path.basename(path)}")
    status_label.config(text="Ready. Click \"Start Conversion\" to begin.")
    progress_bar["value"] = 0
    percent_label.config(text="0%")
    eta_label.config(text="Estimated time remaining: -")
    start_button.config(state="normal")


def start_conversion():
    if not selected_file_path:
        messagebox.showwarning("No file selected", "Please select or drop a file first.")
        return
    start_button.config(state="disabled")
    select_button.config(state="disabled")
    convert_file(selected_file_path)


def choose_output_folder():
    folder = filedialog.askdirectory(title="Select output folder")
    if folder:
        output_folder_var.set(folder)


def on_close():
    global current_process

    if current_process is not None and current_process.poll() is None:
        confirm = messagebox.askyesno(
            "Conversion in progress",
            "A conversion is still running. Quit anyway and stop it?"
        )
        if not confirm:
            return

        try:
            current_process.terminate()
            current_process.wait(timeout=3)
        except Exception:
            try:
                current_process.kill()
            except Exception:
                pass

        # ffmpeg 被强制中断后留下的文件是不完整的，直接删掉避免占用磁盘/造成误用
        if current_output_path and os.path.exists(current_output_path):
            try:
                os.remove(current_output_path)
            except Exception:
                pass

    root.destroy()


set_dpi_awareness()

root = TkinterDnD.Tk()
root.title("Universal Media Converter")
root.geometry("800x650")
root.configure(bg=COLOR_DEFAULT)
root.protocol("WM_DELETE_WINDOW", on_close)

top_label = tk.Label(root, text="Output Format", bg=COLOR_DEFAULT)
top_label.pack(pady=8)

format_box = ttk.Combobox(root, values=list(OUTPUT_FORMATS.keys()), state="readonly")
format_box.set("MP4")
format_box.pack()

output_folder_var = tk.StringVar(value=get_app_dir())

output_folder_label = tk.Label(root, text="Output Folder", bg=COLOR_DEFAULT)
output_folder_label.pack(pady=(12, 2))

output_folder_row = tk.Frame(root, bg=COLOR_DEFAULT)
output_folder_row.pack(pady=(0, 4))

output_folder_entry = tk.Entry(output_folder_row, textvariable=output_folder_var, width=40)
output_folder_entry.pack(side="left", padx=(0, 4))

tk.Button(output_folder_row, text="Choose Folder...", command=choose_output_folder).pack(side="left")

output_folder_display = tk.Label(
    root,
    text="(Default: the folder this app is in. Leave blank to use the source file's folder instead.)",
    fg="gray",
    bg=COLOR_DEFAULT,
    wraplength=460
)
output_folder_display.pack(pady=(0, 0))

drop_area = tk.Label(
    root,
    text="Drag and drop a file here\nor click \"Select File\" below",
    font=("Arial", 14),
    relief="groove",
    width=40,
    height=5,
    bg=COLOR_DEFAULT
)
drop_area.pack(pady=18)

drop_area.drop_target_register(DND_FILES)
drop_area.dnd_bind("<<Drop>>", drop_file)

select_button = tk.Button(root, text="Select File", command=choose_file, width=24)
select_button.pack(pady=(0, 6))

start_button = tk.Button(root, text="Start Conversion", command=start_conversion, width=24, state="disabled")
start_button.pack()

progress_bar = ttk.Progressbar(root, length=400, mode="determinate")
progress_bar.pack(pady=15)

percent_label = tk.Label(root, text="0%", bg=COLOR_DEFAULT)
percent_label.pack()

eta_label = tk.Label(root, text="Estimated time remaining: -", bg=COLOR_DEFAULT)
eta_label.pack()

status_label = tk.Label(root, text="Waiting for file...", fg="gray", bg=COLOR_DEFAULT)
status_label.pack(pady=10)

root.mainloop()