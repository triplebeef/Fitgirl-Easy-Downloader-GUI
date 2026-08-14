import os
import re
import sys
import time
import json
import asyncio
import queue
import shutil
import threading
import traceback
from pathlib import Path
from urllib.parse import urlparse

import requests
import nodriver as uc
from bs4 import BeautifulSoup

import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk


app_title = "FitGirl Fetcher FuckingFast Downloader"
cf_wait_secs = 120
turnstile_wait_secs = 25
click_widget_after_secs = 7
typical_part_size = 524288000
build_id = "progress-state-v5-500mb-log"


def app_base_dir() -> Path:

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


base_dir = app_base_dir()
profile_dir = base_dir / ".ff_browser_profile"
default_download_dir = base_dir / "downloads"

app_folder_name = "FuckingFast-GUI"
app_icon_name = "cropped-icon-192x192.ico"
roaming_appdata = Path(
    os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
)
appdata_dir = roaming_appdata / app_folder_name
app_icon_path = appdata_dir / app_icon_name


def bundled_resource(name: str) -> Path:

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / name
    return Path(__file__).resolve().parent / name


def install_global_app_icon() -> Path | None:

    try:
        appdata_dir.mkdir(parents=True, exist_ok=True)
        source = bundled_resource(app_icon_name)

        if source.is_file():
                                                                                  
            needs_copy = not app_icon_path.is_file()
            if not needs_copy:
                try:
                    needs_copy = source.read_bytes() != app_icon_path.read_bytes()
                except OSError:
                    needs_copy = True

            if needs_copy:
                shutil.copy2(source, app_icon_path)

        return app_icon_path if app_icon_path.is_file() else None
    except OSError:
        return None


def set_windows_app_identity():

    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "FuckingFast.GUI.Downloader"
        )
    except Exception:
        pass


class GuiLogger:
    def __init__(self, event_queue: queue.Queue):
        self.event_queue = event_queue

    def _emit(self, level: str, message: str, obj=""):
        self.event_queue.put(("log", level, message, str(obj)))

    def success(self, message, obj=""):
        self._emit("SUCC", message, obj)

    def error(self, message, obj=""):
        self._emit("ERRR", message, obj)

    def warning(self, message, obj=""):
        self._emit("WARN", message, obj)

    def info(self, message, obj=""):
        self._emit("INFO", message, obj)

    def done(self, message, obj=""):
        self._emit("DONE", message, obj)


event_queue: queue.Queue = queue.Queue()
log = GuiLogger(event_queue)

progress_lock = threading.Lock()
progress_state = {
    "active": False,
    "name": "",
    "current": 0,
    "total": 0,
    "started": 0.0,
}


def set_progress_state(active=None, name=None, current=None, total=None, started=None):
    with progress_lock:
        if active is not None:
            progress_state["active"] = active
        if name is not None:
            progress_state["name"] = name
        if current is not None:
            progress_state["current"] = current
        if total is not None:
            progress_state["total"] = total
        if started is not None:
            progress_state["started"] = started


def get_progress_state():
    with progress_lock:
        return dict(progress_state)


def resolve_output_path(downloads_folder: Path, file_name: str) -> Path:
    candidates = [downloads_folder / file_name, base_dir / file_name]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def safe_filename_from_link(link: str, index: int) -> str:
    fragment_name = urlparse(link).fragment.strip()
    if fragment_name:
                                                                                 
        fragment_name = re.sub(r'[<>:"/\\|?*]+', "_", fragment_name).strip(" .")
        if fragment_name:
            return fragment_name

    file_id = file_id_from_link(link)
    return file_id or f"part_{index:03d}.bin"


def derive_game_name(links: list[str], source_url: str = "") -> str:
                                                                     
    for link in links:
        fragment = urlparse(link).fragment
        if "fitgirl-repacks.site" in fragment:
            name = fragment.split("--")[0].strip("_")
            if name:
                return sanitize_folder_name(name)

                                                                               
    if source_url:
        slug = urlparse(source_url).path.strip("/").split("/")[-1]
        if slug:
            return sanitize_folder_name(slug)

    return "downloads"


def sanitize_folder_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", name).strip(" .")
    return name[:120] or "downloads"


def fetch_fuckingfast_links(url: str) -> list[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    links = [
        a["href"]
        for dlinks_div in soup.find_all("div", class_="dlinks")
        for a in dlinks_div.find_all("a", href=True)
        if a["href"].startswith("https://fuckingfast.co/")
    ]

                                               
    return list(dict.fromkeys(links))


def file_id_from_link(link: str) -> str:
    return urlparse(link).path.strip("/").split("/")[-1]


def download_file(download_url: str, output_path: Path, stop_event: threading.Event) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing_size = output_path.stat().st_size if output_path.is_file() else 0
    req_headers = {}
    if existing_size > 0:
        req_headers["Range"] = f"bytes={existing_size}-"

    set_progress_state(
        active=True,
        name=output_path.name,
        current=existing_size,
        total=0,
        started=time.monotonic(),
    )
    log.info("Opening download stream", output_path.name)
    response = requests.get(
        download_url,
        stream=True,
        headers=req_headers,
        timeout=(20, 90),
    )
    log.info(
        "Download stream ready",
        f"{output_path.name} · HTTP {response.status_code}",
    )

    if response.status_code == 416:
        log.success("File already complete", output_path.name)
        event_queue.put(("file_progress", 100.0, output_path.name, existing_size, existing_size))
        return True

    if response.status_code == 206:
        content_range = response.headers.get("Content-Range", "")
        match = re.search(r"/(\d+)$", content_range)
        total_size = int(match.group(1)) if match else existing_size + int(response.headers.get("content-length", 0))
        if existing_size >= total_size > 0:
            log.success("File already complete", output_path.name)
            event_queue.put(("file_progress", 100.0, output_path.name, existing_size, total_size))
            return True
        mode = "ab"
        current_size = existing_size
        log.info("Resuming download", f"{output_path.name} from {existing_size:,} bytes")
    elif response.status_code == 200:
        total_size = int(response.headers.get("content-length", 0))
        if existing_size > 0 and total_size and existing_size >= total_size:
            log.success("File already complete", output_path.name)
            event_queue.put(("file_progress", 100.0, output_path.name, existing_size, total_size))
            return True
        if existing_size > 0:
            log.warning("Server ignored Range, re-downloading", output_path.name)
        mode = "wb"
        current_size = 0
    else:
        log.error("Failed to download file", f"HTTP {response.status_code}")
        return False

    block_size = 256 * 1024
    set_progress_state(
        active=True,
        name=output_path.name,
        current=current_size,
        total=total_size,
        started=time.monotonic(),
    )

    activity_started = time.monotonic()
    activity_last_time = activity_started
    activity_last_bytes = current_size
    activity_first_report = True
    progress_last_time = activity_started

                                                                           
                                                                        
    if total_size:
        start_percent = current_size / total_size * 100.0
        log.info(
            "Download started",
            f"{output_path.name} · {start_percent:.1f}% · "
            f"{current_size:,}/{total_size:,} bytes",
        )
    else:
        log.info(
            "Download started",
            f"{output_path.name} · {current_size:,} bytes · total size unknown",
        )

    with open(output_path, mode) as f:
        for data in response.iter_content(block_size):
            if stop_event.is_set():
                set_progress_state(active=False)
                log.warning("Download stopped", output_path.name)
                return False
            if not data:
                continue
            f.write(data)
            current_size += len(data)
            percent = (current_size / total_size * 100.0) if total_size else 0.0
            set_progress_state(
                active=True,
                name=output_path.name,
                current=current_size,
                total=total_size,
            )

            activity_now = time.monotonic()
            activity_elapsed = activity_now - activity_last_time

            if activity_first_report or activity_elapsed >= 1.0:
                byte_delta = current_size - activity_last_bytes
                speed_bps = byte_delta / activity_elapsed if activity_elapsed > 0 else 0.0

                if total_size:
                    detail = (
                        f"{output_path.name} · {percent:.1f}% · "
                        f"{current_size:,}/{total_size:,} bytes · "
                        f"{speed_bps / (1024 * 1024):.2f} MB/s"
                    )
                else:
                    detail = (
                        f"{output_path.name} · "
                        f"{current_size / (1024 * 1024):.1f} MB downloaded · "
                        f"{speed_bps / (1024 * 1024):.2f} MB/s"
                    )

                activity_last_time = activity_now
                activity_last_bytes = current_size
                activity_first_report = False

    set_progress_state(
        active=False,
        name=output_path.name,
        current=current_size,
        total=total_size,
    )

    final_size = output_path.stat().st_size
    if total_size and final_size < total_size:
        log.error("Download incomplete", f"{final_size:,}/{total_size:,} bytes")
        return False

    if total_size:
        final_detail = (
            f"{output_path.name} · 100.0% · "
            f"{final_size:,}/{total_size:,} bytes"
        )
    else:
        final_detail = (
            f"{output_path.name} · "
            f"{final_size / (1024 * 1024):.1f} MB downloaded"
        )

    log.info("Download complete", final_detail)
    log.success("Successfully downloaded file", str(output_path))
    event_queue.put(("file_progress", 100.0, output_path.name, final_size, total_size or final_size))
    return True


async def js(tab, expression, await_promise=False):
    raw = await tab.evaluate(
        expression,
        await_promise=await_promise,
        return_by_value=True,
    )
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def page_ready(tab):
    state = await js(
        tab,
        """(() => {
            const title = document.title || '';
            const body = (document.body && document.body.innerText) || '';
            const hasChallenge = title.includes('Just a moment')
                || body.includes('Verifying you are human')
                || !!document.querySelector('#challenge-running, #cf-challenge-running, .cf-browser-verification');
            const hasDownload = !!document.querySelector('a.link-button')
                || !!document.querySelector('#cf-turnstile')
                || !!document.querySelector('meta[name="title"]')
                || /DOWNLOAD/i.test(body);
            return JSON.stringify({ hasChallenge, hasDownload, title });
        })()""",
    )
    if not isinstance(state, dict):
        return False
    return bool(not state.get("hasChallenge") and state.get("hasDownload"))


async def wait_for_cf_clear(tab, stop_event: threading.Event):
    log.info("Waiting for Cloudflare check", "solve/wait in browser if needed")
    last_err = None
    for i in range(cf_wait_secs):
        if stop_event.is_set():
            return False
        try:
            if await page_ready(tab):
                log.success("Cloudflare cleared", f"after {i + 1}s")
                return True
        except Exception as exc:
            last_err = exc
        await asyncio.sleep(1)
        if i and i % 15 == 0:
            extra = f" ({last_err})" if last_err else ""
            log.info("Still waiting for download page", f"{i}s{extra}")
    return False


async def has_turnstile_widget(tab):
    return await js(tab, "JSON.stringify(!!document.getElementById('cf-turnstile'))") is True


async def click_turnstile_widget(tab):
    try:
        widget = await tab.select("#cf-turnstile", timeout=2)
        await widget.mouse_click()
        return True
    except Exception:
        return False


async def wait_for_turnstile(tab, stop_event: threading.Event):
    log.info("Waiting for Turnstile token", "click checkbox if shown")
    clicked = False
    for i in range(turnstile_wait_secs):
        if stop_event.is_set():
            return None
        try:
            token = await js(
                tab,
                """JSON.stringify(
                    window.turnstileToken
                    || document.querySelector('[name="cf-turnstile-response"]')?.value
                    || ''
                )""",
            )
            if isinstance(token, str) and len(token) > 20:
                log.success("Turnstile ready", f"after {i + 1}s")
                return token
        except Exception:
            pass

        if not clicked and i == click_widget_after_secs:
            clicked = await click_turnstile_widget(tab)
            if clicked:
                log.info("Clicked Turnstile widget", "waiting for token")

        await asyncio.sleep(1)
    return None


async def post_go(tab, file_id: str, token: str):
    return await js(
        tab,
        f"""
        (async () => {{
            const response = await fetch('/f/{file_id}/go', {{
                method: 'POST',
                headers: {{
                    'content-type': 'application/x-www-form-urlencoded',
                    'hx-request': 'true',
                    'hx-current-url': location.href,
                    'referer': location.href,
                }},
                body: new URLSearchParams({{ 'cf-turnstile-response': {json.dumps(token)} }}),
            }});
            const redirect = response.headers.get('HX-Redirect')
                || response.headers.get('hx-redirect');
            const body = await response.text();
            return JSON.stringify({{
                status: response.status,
                redirect: redirect,
                body: body.slice(0, 200),
            }});
        }})()
        """,
        await_promise=True,
    )


async def resolve_direct_url(tab, link: str, stop_event: threading.Event, attempts=4):
    file_id = file_id_from_link(link)
    last_error = "unknown error"

    for attempt in range(1, attempts + 1):
        if stop_event.is_set():
            return None, "Stopped"

        await tab.get(link)

        if not await wait_for_cf_clear(tab, stop_event):
            last_error = "Stuck on Cloudflare 'Just a moment' page"
        else:
            if await has_turnstile_widget(tab):
                token = await wait_for_turnstile(tab, stop_event)
            else:
                log.info("No captcha widget on page", "session already trusted")
                token = ""

            if stop_event.is_set():
                return None, "Stopped"
            if token is None:
                last_error = "Turnstile token not ready"
            else:
                result = await post_go(tab, file_id, token)
                if not isinstance(result, dict):
                    last_error = f"Unexpected browser response: {result!r}"
                elif result.get("redirect"):
                    return result["redirect"], None
                else:
                    last_error = f"No HX-Redirect ({result.get('body') or result.get('status')})"

        if attempt < attempts and not stop_event.is_set():
            log.warning("Retrying link", f"attempt {attempt + 1}/{attempts} — {last_error}")
            await asyncio.sleep(3)

    return None, last_error


async def shutdown_browser(browser):
    try:
        browser.stop()
    except Exception:
        pass

    process = getattr(getattr(browser, "config", None), "browser_process", None)
    if process is not None:
        for _ in range(20):
            if process.poll() is not None:
                break
            await asyncio.sleep(0.1)
        else:
            try:
                process.kill()
            except Exception:
                pass

    await asyncio.sleep(0.5)


async def run_downloads(links: list[str], downloads_folder: Path, stop_event: threading.Event):
    profile_dir.mkdir(parents=True, exist_ok=True)
    downloads_folder.mkdir(parents=True, exist_ok=True)
    log.info("Launching browser", "nodriver + persistent profile")

    browser = await uc.start(
        headless=False,
        user_data_dir=str(profile_dir),
        browser_args=[
            "--window-size=900,700",
            "--disable-popup-blocking",
        ],
    )

    tab = await browser.get("about:blank")
    total_links = len(links)
    completed = 0

    try:
        for index, link in enumerate(links, start=1):
            if stop_event.is_set():
                log.warning("Stopped", "user requested stop")
                break

            event_queue.put(("overall", index - 1, total_links))
            log.info("Started processing", f"[{index}/{total_links}] {link}")

            file_name = safe_filename_from_link(link, index)
            output_path = resolve_output_path(downloads_folder, file_name)

            if output_path.is_file() and output_path.stat().st_size == typical_part_size:
                log.success("Skipping existing complete file", file_name)
                completed += 1
                event_queue.put(("overall", completed, total_links))
                continue

            try:
                download_url, err = await resolve_direct_url(tab, link, stop_event)
            except Exception as exc:
                log.error("Browser resolve failed", str(exc))
                continue

            if not download_url:
                if not stop_event.is_set():
                    log.error("Failed to get download url", err)
                continue

            log.info("Fetched download url", f"{download_url[:100]}...")

            try:
                if download_file(download_url, output_path, stop_event):
                    completed += 1
                    event_queue.put(("overall", completed, total_links))
            except Exception as exc:
                log.error("Failed to download file", str(exc))

            if not stop_event.is_set():
                await asyncio.sleep(1)
    finally:
        await shutdown_browser(browser)

    return completed


def silence_pipe_teardown_noise(unraisable):
    message = str(unraisable.exc_value)
    if isinstance(unraisable.exc_value, (ValueError, RuntimeError)) and (
        "closed pipe" in message or "Event loop is closed" in message
    ):
        return
    sys.__unraisablehook__(unraisable)


class DownloaderGUI(ctk.CTk):
                                                                            
                                                                     
    accent = "#4F7CFF"
    accent_hover = "#3E68E8"
    success_color = "#26C281"
    warning_color = "#F5A524"
    danger_color = "#F05D68"
    muted_dark = "#8D96A8"
    card_dark = "#151922"
    card_light = "#F4F6FA"
    border_dark = "#272D3A"
    border_light = "#DCE2EC"

    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        super().__init__()

                                                                             
                                                                                
        self.app_icon_path = install_global_app_icon()
        if self.app_icon_path:
            try:
                self.iconbitmap(default=str(self.app_icon_path))
            except tk.TclError:
                pass

        self.title(app_title)
        self.geometry("1080x800")
        self.minsize(900, 680)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.stop_event = threading.Event()
        self.worker_thread = None
        self.source_url = tk.StringVar()
        self.download_dir = tk.StringVar(value=str(default_download_dir))
        self.status_var = tk.StringVar(value="Ready")
        self.file_status_var = tk.StringVar(value="No active download")
        self.overall_status_var = tk.StringVar(value="0 / 0")
        self.link_count_var = tk.StringVar(value="0 links")
        self.appearance_var = tk.StringVar(value="Dark")
        self.progress_poll_name = ""
        self.progress_poll_bytes = 0
        self.progress_poll_time = time.monotonic()
        self.progress_next_log_bytes = 500 * 1024 * 1024

        self._build_ui()
        log.info("Build", build_id)
        self.after(50, self._drain_events)
        self.after(250, self._poll_download_progress)

                                                                        
                
                                                                        

    def _card(self, master, **kwargs):
        return ctk.CTkFrame(
            master,
            corner_radius=16,
            fg_color=(self.card_light, self.card_dark),
            border_width=1,
            border_color=(self.border_light, self.border_dark),
            **kwargs,
        )

    def _section_heading(self, master, title, subtitle=None):
        ctk.CTkLabel(
            master,
            text=title,
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            anchor="w",
        ).pack(fill="x")
        if subtitle:
            ctk.CTkLabel(
                master,
                text=subtitle,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=("gray45", self.muted_dark),
                anchor="w",
            ).pack(fill="x", pady=(2, 0))

    def _secondary_button(self, master, text, command, width=92):
        return ctk.CTkButton(
            master,
            text=text,
            command=command,
            width=width,
            height=34,
            corner_radius=9,
            fg_color=("gray88", "#222834"),
            hover_color=("gray80", "#2D3442"),
            text_color=("gray15", "#E8EBF2"),
            border_width=1,
            border_color=(self.border_light, self.border_dark),
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        )

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

                                                                         
        header = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 12))
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            title_box,
            text="FuckingFast (FitGirl Repacks)",
            font=ctk.CTkFont(family="Segoe UI", size=27, weight="bold"),
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box,
            text="LINK FETCHER  /  DOWNLOAD MANAGER",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=("gray45", self.muted_dark),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        header_actions = ctk.CTkFrame(header, fg_color="transparent")
        header_actions.grid(row=0, column=1, sticky="e")

        self.status_pill = ctk.CTkLabel(
            header_actions,
            textvariable=self.status_var,
            height=32,
            corner_radius=16,
            fg_color=("gray88", "#1B202B"),
            text_color=("gray30", "#CFD5E2"),
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            padx=14,
        )
        self.status_pill.pack(side="left", padx=(0, 10))

        self.appearance_switch = ctk.CTkSegmentedButton(
            header_actions,
            values=["Dark", "Light"],
            variable=self.appearance_var,
            command=self._change_appearance,
            width=142,
            height=32,
            corner_radius=9,
            selected_color=self.accent,
            selected_hover_color=self.accent_hover,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
        )
        self.appearance_switch.pack(side="left")
        self.appearance_switch.set("Dark")

                                                                         
        self.tabs = ctk.CTkTabview(
            self,
            corner_radius=16,
            fg_color=("gray94", "#10141C"),
            segmented_button_selected_color=self.accent,
            segmented_button_selected_hover_color=self.accent_hover,
            segmented_button_unselected_hover_color=("gray82", "#242B38"),
            border_width=0,
        )
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 22))
        self.tabs.add("Download")
        self.tabs.add("Activity")

        download_tab = self.tabs.tab("Download")
        activity_tab = self.tabs.tab("Activity")
        download_tab.grid_columnconfigure(0, weight=1)
        download_tab.grid_rowconfigure(1, weight=1)
        activity_tab.grid_columnconfigure(0, weight=1)
        activity_tab.grid_rowconfigure(0, weight=1)

                                                                        
        setup_card = self._card(download_tab)
        setup_card.grid(row=0, column=0, sticky="ew", padx=8, pady=(10, 10))
        setup_card.grid_columnconfigure(0, weight=1)

        setup_inner = ctk.CTkFrame(setup_card, fg_color="transparent")
        setup_inner.grid(row=0, column=0, sticky="ew", padx=18, pady=16)
        setup_inner.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            setup_inner,
            text="Source",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            setup_inner,
            text="Paste a FitGirl page and fetch its FuckingFast mirrors.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=("gray45", self.muted_dark),
            anchor="w",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 9))

        self.source_entry = ctk.CTkEntry(
            setup_inner,
            textvariable=self.source_url,
            height=40,
            corner_radius=10,
            placeholder_text="https://fitgirl-repacks.site/...",
            border_width=1,
            border_color=(self.border_light, self.border_dark),
            fg_color=("white", "#0F131B"),
            font=ctk.CTkFont(family="Segoe UI", size=12),
        )
        self.source_entry.grid(row=2, column=0, sticky="ew", padx=(0, 10))

        self.fetch_button = ctk.CTkButton(
            setup_inner,
            text="Fetch links",
            command=self.fetch_links,
            width=116,
            height=40,
            corner_radius=10,
            fg_color=self.accent,
            hover_color=self.accent_hover,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        )
        self.fetch_button.grid(row=2, column=1, sticky="e")

        divider = ctk.CTkFrame(
            setup_inner,
            height=1,
            fg_color=(self.border_light, self.border_dark),
        )
        divider.grid(row=3, column=0, columnspan=3, sticky="ew", pady=15)

        ctk.CTkLabel(
            setup_inner,
            text="Download location",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            anchor="w",
        ).grid(row=4, column=0, sticky="w")

        ctk.CTkLabel(
            setup_inner,
            text="A game-specific subfolder is created automatically.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=("gray45", self.muted_dark),
            anchor="w",
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(2, 9))

        self.destination_entry = ctk.CTkEntry(
            setup_inner,
            textvariable=self.download_dir,
            height=40,
            corner_radius=10,
            border_width=1,
            border_color=(self.border_light, self.border_dark),
            fg_color=("white", "#0F131B"),
            font=ctk.CTkFont(family="Segoe UI", size=12),
        )
        self.destination_entry.grid(row=6, column=0, sticky="ew", padx=(0, 10))

        self.browse_button = self._secondary_button(
            setup_inner, "Browse", self.choose_folder, width=116
        )
        self.browse_button.grid(row=6, column=1, sticky="e")

                                                                        
        links_card = self._card(download_tab)
        links_card.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 10))
        links_card.grid_columnconfigure(0, weight=1)
        links_card.grid_rowconfigure(1, weight=1)

        links_header = ctk.CTkFrame(links_card, fg_color="transparent")
        links_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(15, 8))
        links_header.grid_columnconfigure(0, weight=1)

        header_text = ctk.CTkFrame(links_header, fg_color="transparent")
        header_text.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header_text,
            text="Download queue",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header_text,
            text="One FuckingFast URL per line. Duplicate URLs are ignored.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=("gray45", self.muted_dark),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        toolbar = ctk.CTkFrame(links_header, fg_color="transparent")
        toolbar.grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            toolbar,
            textvariable=self.link_count_var,
            height=30,
            corner_radius=15,
            fg_color=("gray88", "#1B202B"),
            text_color=("gray35", "#BBC3D1"),
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            padx=11,
        ).pack(side="left", padx=(0, 8))

        for label, command in (
            ("Paste", self.paste_links),
            ("Import", self.load_txt),
            ("Export", self.save_txt),
        ):
            self._secondary_button(toolbar, label, command, width=72).pack(
                side="left", padx=(0, 6)
            )

        self.clear_button = ctk.CTkButton(
            toolbar,
            text="Clear",
            command=self.clear_links,
            width=66,
            height=34,
            corner_radius=9,
            fg_color="transparent",
            hover_color=("gray88", "#2A1D23"),
            text_color=("#B53A44", "#FF7A85"),
            border_width=1,
            border_color=("#E5BEC1", "#593039"),
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
        )
        self.clear_button.pack(side="left")

        self.links_text = ctk.CTkTextbox(
            links_card,
            height=170,
            corner_radius=10,
            border_width=1,
            border_color=(self.border_light, self.border_dark),
            fg_color=("white", "#0F131B"),
            wrap="none",
            font=ctk.CTkFont(family="Consolas", size=11),
            scrollbar_button_color=("gray70", "#343B49"),
            scrollbar_button_hover_color=("gray60", "#465063"),
        )
        self.links_text.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))
        self.links_text.bind("<KeyRelease>", self._links_changed)
        self.links_text.bind("<<Paste>>", lambda _e: self.after(20, self._update_link_count))
        self.links_text.bind("<<Cut>>", lambda _e: self.after(20, self._update_link_count))

                                                                        
        progress_card = self._card(download_tab)
        progress_card.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        progress_card.grid_columnconfigure(0, weight=1)

        progress_inner = ctk.CTkFrame(progress_card, fg_color="transparent")
        progress_inner.grid(row=0, column=0, sticky="ew", padx=18, pady=16)
        progress_inner.grid_columnconfigure(0, weight=1)

        file_head = ctk.CTkFrame(progress_inner, fg_color="transparent")
        file_head.grid(row=0, column=0, sticky="ew")
        file_head.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            file_head,
            text="Current file",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.file_detail_label = ctk.CTkLabel(
            file_head,
            textvariable=self.file_status_var,
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=("gray45", self.muted_dark),
            anchor="e",
        )
        self.file_detail_label.grid(row=0, column=1, sticky="e", padx=(12, 0))

        self.file_progress = ctk.CTkProgressBar(
            progress_inner,
            height=8,
            corner_radius=4,
            fg_color=("gray84", "#272D39"),
            progress_color=self.accent,
        )
        self.file_progress.grid(row=1, column=0, sticky="ew", pady=(8, 13))
        self.file_progress.set(0)

        overall_head = ctk.CTkFrame(progress_inner, fg_color="transparent")
        overall_head.grid(row=2, column=0, sticky="ew")
        overall_head.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            overall_head,
            text="Overall",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            overall_head,
            textvariable=self.overall_status_var,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=("gray40", "#B9C2D0"),
        ).grid(row=0, column=1, sticky="e")

        self.overall_progress = ctk.CTkProgressBar(
            progress_inner,
            height=8,
            corner_radius=4,
            fg_color=("gray84", "#272D39"),
            progress_color=self.success_color,
        )
        self.overall_progress.grid(row=3, column=0, sticky="ew", pady=(8, 15))
        self.overall_progress.set(0)

        controls = ctk.CTkFrame(progress_inner, fg_color="transparent")
        controls.grid(row=4, column=0, sticky="ew")
        controls.grid_columnconfigure(0, weight=1)

        self.start_button = ctk.CTkButton(
            controls,
            text="Start download",
            command=self.start_download,
            width=150,
            height=42,
            corner_radius=11,
            fg_color=self.accent,
            hover_color=self.accent_hover,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        )
        self.start_button.grid(row=0, column=0, sticky="w")

        self.stop_button = ctk.CTkButton(
            controls,
            text="Stop",
            command=self.stop_download,
            state="disabled",
            width=92,
            height=42,
            corner_radius=11,
            fg_color=("#E96A74", "#9C3542"),
            hover_color=("#D85460", "#B94350"),
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        )
        self.stop_button.grid(row=0, column=1, sticky="w", padx=(9, 0))

        self.open_folder_button = self._secondary_button(
            controls, "Open folder", self.open_download_folder, width=112
        )
        self.open_folder_button.grid(row=0, column=2, sticky="e", padx=(24, 0))

                                                                         
        activity_card = self._card(activity_tab)
        activity_card.grid(row=0, column=0, sticky="nsew", padx=8, pady=(10, 8))
        activity_card.grid_columnconfigure(0, weight=1)
        activity_card.grid_rowconfigure(1, weight=1)

        activity_header = ctk.CTkFrame(activity_card, fg_color="transparent")
        activity_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(15, 9))
        activity_header.grid_columnconfigure(0, weight=1)

        activity_title = ctk.CTkFrame(activity_header, fg_color="transparent")
        activity_title.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            activity_title,
            text="Activity log",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            activity_title,
            text="Browser, Cloudflare and download events appear here.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=("gray45", self.muted_dark),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        self._secondary_button(
            activity_header, "Clear log", self.clear_log, width=84
        ).grid(row=0, column=1, sticky="e")

        self.log_text = ctk.CTkTextbox(
            activity_card,
            corner_radius=10,
            border_width=1,
            border_color=(self.border_light, self.border_dark),
            fg_color=("white", "#0B0E14"),
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=11),
            scrollbar_button_color=("gray70", "#343B49"),
            scrollbar_button_hover_color=("gray60", "#465063"),
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))
        self.log_text.configure(state="disabled")

                                                                        
                
                                                                        

    def _change_appearance(self, mode: str):
        ctk.set_appearance_mode(mode.lower())

    def _links_changed(self, _event=None):
        self._update_link_count()

    def _update_link_count(self):
        count = len(self._get_links())
        self.link_count_var.set(f"{count} link" if count == 1 else f"{count} links")

    def clear_links(self):
        self.links_text.delete("1.0", "end")
        self._update_link_count()

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def open_download_folder(self):
        root = Path(self.download_dir.get().strip() or default_download_dir)
        links = self._get_links()
        game_name = derive_game_name(links, self.source_url.get().strip()) if links else ""
        target = root / game_name if game_name and (root / game_name).exists() else root
        target.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(target)                              
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(target)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            messagebox.showerror(app_title, f"Could not open folder:\n{exc}")

    def choose_folder(self):
        folder = filedialog.askdirectory(
            initialdir=self.download_dir.get() or str(base_dir)
        )
        if folder:
            self.download_dir.set(folder)

    def paste_links(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        cleaned = text.strip()
        if cleaned:
            self.links_text.insert("end", cleaned + "\n")
            self._update_link_count()

    def load_txt(self):
        path = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except Exception as exc:
            messagebox.showerror(app_title, f"Could not read file:\n{exc}")
            return
        self.links_text.delete("1.0", "end")
        self.links_text.insert("1.0", text)
        self._update_link_count()

    def save_txt(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile="input.txt",
        )
        if not path:
            return
        try:
            Path(path).write_text(
                self.links_text.get("1.0", "end").strip() + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            messagebox.showerror(app_title, f"Could not save file:\n{exc}")

    def fetch_links(self):
        url = self.source_url.get().strip()
        if not url:
            messagebox.showwarning(app_title, "Enter the FitGirl page URL first.")
            return
        if self.worker_thread and self.worker_thread.is_alive():
            return

        self.fetch_button.configure(state="disabled")
        self.status_var.set("Fetching links...")

        def worker():
            try:
                links = fetch_fuckingfast_links(url)
                event_queue.put(("fetched_links", links, url))
            except Exception as exc:
                event_queue.put(("error_dialog", "Failed to fetch links", str(exc)))
            finally:
                event_queue.put(("fetch_done",))

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _get_links(self) -> list[str]:
        links = []
        for line in self.links_text.get("1.0", "end").splitlines():
            link = line.strip()
            if link and link.startswith("https://fuckingfast.co/"):
                links.append(link)
        return list(dict.fromkeys(links))

    def start_download(self):
        links = self._get_links()
        if not links:
            messagebox.showwarning(
                app_title, "Add at least one valid https://fuckingfast.co/ link."
            )
            return
        if self.worker_thread and self.worker_thread.is_alive():
            return

        root = Path(self.download_dir.get().strip() or default_download_dir)
        game_name = derive_game_name(links, self.source_url.get().strip())
        downloads_folder = root / game_name

        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.fetch_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("Downloading...")
        self.file_progress.set(0)
        self.overall_progress.set(0)
        self.overall_status_var.set(f"0 / {len(links)}")
        self.tabs.set("Activity")
        log.info("Download folder", downloads_folder)
        log.info("Links to process", len(links))

        def worker():
            try:
                sys.unraisablehook = silence_pipe_teardown_noise
                completed = asyncio.run(
                    run_downloads(links, downloads_folder, self.stop_event)
                )
                event_queue.put(
                    ("download_done", completed, len(links), str(downloads_folder))
                )
            except Exception as exc:
                event_queue.put(
                    ("worker_exception", str(exc), traceback.format_exc())
                )

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def stop_download(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_event.set()
            self.status_var.set("Stopping...")
            self.stop_button.configure(state="disabled")
            log.warning(
                "Stop requested", "current operation will terminate as soon as possible"
            )

    def _set_idle(self):
        self.start_button.configure(state="normal")
        self.fetch_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    @staticmethod
    def _format_bytes(value: int) -> str:
        value = float(value or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"

    def _poll_download_progress(self):
        state = get_progress_state()
        now = time.monotonic()

        if state["active"]:
            name = state["name"]
            current = int(state["current"] or 0)
            total = int(state["total"] or 0)

            if name != self.progress_poll_name:
                self.progress_poll_name = name
                self.progress_poll_bytes = current
                self.progress_poll_time = now
                self.progress_next_log_bytes = (
                    ((current // (500 * 1024 * 1024)) + 1)
                    * (500 * 1024 * 1024)
                )

            elapsed = max(now - self.progress_poll_time, 0.001)
            byte_delta = max(current - self.progress_poll_bytes, 0)
            speed_bps = byte_delta / elapsed

            if total > 0:
                percent = min(max(current / total * 100.0, 0.0), 100.0)
                self.file_progress.set(percent / 100.0)
                self.file_status_var.set(
                    f"{name}  ·  {self._format_bytes(current)} / "
                    f"{self._format_bytes(total)}  ·  {percent:.1f}%"
                )
                detail = (
                    f"{name} · {percent:.1f}% · "
                    f"{self._format_bytes(current)} / {self._format_bytes(total)} · "
                    f"{speed_bps / (1024 * 1024):.2f} MB/s"
                )
                self.status_var.set(f"Downloading · {percent:.1f}%")
            else:
                self.file_status_var.set(
                    f"{name}  ·  {self._format_bytes(current)} downloaded"
                )
                detail = (
                    f"{name} · {self._format_bytes(current)} downloaded · "
                    f"{speed_bps / (1024 * 1024):.2f} MB/s"
                )
                self.status_var.set(
                    f"Downloading · {self._format_bytes(current)}"
                )

            if current >= self.progress_next_log_bytes:
                self._append_log("PROG", "Downloading", detail)
                while current >= self.progress_next_log_bytes:
                    self.progress_next_log_bytes += 500 * 1024 * 1024

            self.progress_poll_bytes = current
            self.progress_poll_time = now

        self.after(250, self._poll_download_progress)

    def _append_log(self, level: str, message: str, obj: str):
        from datetime import datetime

        stamp = datetime.now().strftime("%H:%M:%S")
        text = f"{stamp}  {level:<4}  {message}"
        if obj:
            text += f"  ·  {obj}"
        text += "\n"

        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain_events(self):
        processed = 0
        max_events = 100

        try:
            while processed < max_events:
                event = event_queue.get_nowait()
                processed += 1
                kind = event[0]

                if kind == "log":
                    _, level, message, obj = event
                    self._append_log(level, message, obj)

                elif kind == "fetched_links":
                    _, links, url = event
                    self.source_url.set(url)
                    self.links_text.delete("1.0", "end")
                    if links:
                        self.links_text.insert("1.0", "\n".join(links) + "\n")
                        self.status_var.set(f"Fetched {len(links)} links")
                        self._append_log(
                            "SUCC", "Matching URLs found", str(len(links))
                        )
                    else:
                        self.status_var.set("No matching links")
                        messagebox.showwarning(
                            app_title,
                            "No matching FuckingFast links were found on that page.",
                        )
                    self._update_link_count()

                elif kind == "fetch_done":
                    self.fetch_button.configure(state="normal")
                    if self.status_var.get() == "Fetching links...":
                        self.status_var.set("Ready")

                elif kind == "file_progress":
                    _, percent, name, current, total = event
                    value = max(0.0, min(100.0, percent)) / 100.0
                    self.file_progress.set(value)
                    if total:
                        self.file_status_var.set(
                            f"{name}  ·  {self._format_bytes(current)} / "
                            f"{self._format_bytes(total)}  ·  {percent:.1f}%"
                        )
                    else:
                        self.file_status_var.set(
                            f"{name}  ·  {self._format_bytes(current)} downloaded"
                        )

                elif kind == "overall":
                    _, done, total = event
                    self.overall_status_var.set(f"{done} / {total}")
                    self.overall_progress.set((done / total) if total else 0)

                elif kind == "download_done":
                    _, completed, total, folder = event
                    self._set_idle()
                    if self.stop_event.is_set():
                        self.status_var.set(f"Stopped · {completed}/{total}")
                        self._append_log(
                            "DONE", "Stopped", f"{completed}/{total} complete"
                        )
                    else:
                        self.status_var.set(f"Finished · {completed}/{total}")
                        self._append_log("DONE", "Finished", folder)
                    self.overall_status_var.set(f"{completed} / {total}")
                    self.overall_progress.set((completed / total) if total else 0)

                elif kind == "worker_exception":
                    _, message, tb = event
                    self._set_idle()
                    self.status_var.set("Error")
                    self._append_log("ERRR", message, "")
                    self._append_log("ERRR", "Traceback", tb)
                    messagebox.showerror(app_title, message)

                elif kind == "error_dialog":
                    _, title, message = event
                    self.status_var.set("Error")
                    messagebox.showerror(title, message)

        except queue.Empty:
            pass
        finally:
            if event_queue.empty():
                self.after(50, self._drain_events)
            else:
                self.after(1, self._drain_events)

    def on_close(self):
        if self.worker_thread and self.worker_thread.is_alive():
            if not messagebox.askyesno(
                app_title, "A task is still running. Stop it and close?"
            ):
                return
            self.stop_event.set()
        self.destroy()


def main():
    set_windows_app_identity()
    install_global_app_icon()
    default_download_dir.mkdir(parents=True, exist_ok=True)
    app = DownloaderGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
