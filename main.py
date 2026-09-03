import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import av
import numpy as np
import sounddevice as sd
import yt_dlp
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    Select,
)

# Tenta carregar variáveis do .env se existir, sem obrigar o usuário a ter um
try:
    from dotenv import load_dotenv
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

socket.setdefaulttimeout(15)

# Diretório para salvar o token do usuário na pasta de configurações do sistema
CONFIG_DIR = Path.home() / ".config" / "meu-player-tui"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
TOKEN_FILE = CONFIG_DIR / "token.json"

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
MUSIC_CATEGORY_ID = "10"

# Credenciais padrão da aplicação Desktop para o fluxo do usuário
DEFAULT_CLIENT_ID = os.environ.get(
    "GOOGLE_CLIENT_ID",
    "50790974670-qshvlqkejhu0ksj76v0t0lpcq3krm593.apps.googleusercontent.com"  # Substitua pelas suas credenciais reais do GCP (Desktop App)
)
DEFAULT_CLIENT_SECRET = os.environ.get(
    "GOOGLE_CLIENT_SECRET",
    "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"  # Substitua pelas suas credenciais reais do GCP (Desktop App)
)


def get_client_config():
    """Retorna a configuração OAuth 2.0 padrão para aplicação desktop."""
    return {
        "installed": {
            "client_id": DEFAULT_CLIENT_ID,
            "client_secret": DEFAULT_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080/"],
        }
    }


def get_youtube_service(interactive=False):
    """Obtém a conexão com a API do YouTube para ver as curtidas do usuário."""
    creds = None

    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w", encoding="utf-8") as token:
                token.write(creds.to_json())
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if not interactive:
            return None

        client_config = get_client_config()
        flow = InstalledAppFlow.from_client_config(
            client_config,
            SCOPES,
            redirect_uri="http://localhost:8080/",
        )

        creds = flow.run_local_server(
            port=8080,
            prompt="consent",
            access_type="offline",
        )

        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


class MusicPlayerApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }

    #main {
        height: 1fr;
    }

    #sidebar {
        width: 44;
        height: 100%;
        background: $panel;
        border-right: heavy $accent;
        padding: 1;
    }

    #sidebar Input {
        margin-bottom: 1;
    }

    #auth-buttons {
        height: 3;
        margin-bottom: 1;
    }

    #auth-buttons Button {
        margin-right: 1;
    }

    #results_list {
        height: 1fr;
        border: solid $accent;
    }

    #btn_load_more {
        width: 100%;
        margin-top: 1;
    }

    #content {
        width: 1fr;
        height: 100%;
        padding: 2;
        align: center middle;
    }

    #now-playing {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    #visualizer {
        text-align: center;
        color: $success;
        height: 2;
        margin-bottom: 1;
    }

    #progress-container {
        height: 3;
        align: center middle;
        margin-bottom: 1;
    }

    #progress-container ProgressBar {
        width: 1fr;
    }

    #volume-container {
        height: 3;
        align: center middle;
        margin-bottom: 1;
    }

    #volume-container Button {
        margin: 0 1;
    }

    #controls {
        height: 3;
        align: center middle;
    }

    #controls Button {
        margin: 0 1;
    }

    #status {
        margin-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("q", "quit", "Sair"),
        ("space", "toggle_play", "Play/Pause"),
        ("up", "volume_up", "Aumentar Vol"),
        ("down", "volume_down", "Diminuir Vol"),
    ]

    def __init__(self):
        super().__init__()
        self.stream_thread = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()

        self.is_playing = False
        self.raw_results = []
        self.filtered_results = []
        self.youtube_api = None

        # Paginação e Busca
        self.next_page_token = None
        self.last_query = ""
        self.last_source_type = None  # 'search' ou 'liked'
        self.is_loading_more = False

        # Áudio
        self.volume = 0.8
        self.duration_seconds = 0
        self.current_position_seconds = 0
        self.seek_target_seconds = None

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Label("[bold]Buscar ou Conta[/bold]")
                yield Input(placeholder="Nome ou artista...", id="search_input")

                with Horizontal(id="auth-buttons"):
                    yield Button("🔑 Login", id="btn_login", variant="primary")
                    yield Button("👍 Curtidas", id="btn_liked", variant="default")

                yield Label("[bold]Filtro de Conteúdo:[/bold]")
                yield Select(
                    [("🎵 Apenas Músicas", "music"), ("🎬 Todos os Vídeos", "all")],
                    value="music",
                    id="filter_select",
                    allow_blank=False,
                )

                yield ListView(id="results_list")
                yield Button("➕ Carregar Mais Músicas", id="btn_load_more", variant="default")

            with Vertical(id="content"):
                yield Label("Nenhuma música selecionada", id="now-playing")

                yield Label("░░░░░░░░░░░░░░░░░░░░", id="visualizer")

                # Linha do Tempo e Progresso
                with Horizontal(id="progress-container"):
                    yield Label("00:00 ", id="time_current")
                    yield ProgressBar(id="song_progress", total=100, show_percentage=False)
                    yield Label(" 00:00", id="time_total")

                # Controle de Volume
                with Horizontal(id="volume-container"):
                    yield Button("🔉 -", id="btn_vol_down")
                    yield Label(" Volume: 80% ", id="vol_label")
                    yield Button("🔊 +", id="btn_vol_up")

                with Horizontal(id="controls"):
                    yield Button("⏪ -10s", id="btn_rewind")
                    yield Button("▶ / ⏸ (Espaço)", id="btn_toggle", variant="primary")
                    yield Button("⏩ +10s", id="btn_forward")
                    yield Button("⏹ Parar", id="btn_stop", variant="error")

                yield Label("Status: Pronto.", id="status")

        yield Footer()

    def on_mount(self) -> None:
        def auto_auth():
            self.youtube_api = get_youtube_service(interactive=False)
            status = self.query_one("#status", Label)
            if self.youtube_api:
                self.call_from_thread(status.update, "[green]Sessão de usuário carregada com sucesso![/green]")

        threading.Thread(target=auto_auth, daemon=True).start()

    # --- FILTRAGEM E ATUALIZAÇÃO ---

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "filter_select":
            self._apply_filter_and_update_ui()

    def _apply_filter_and_update_ui(self) -> None:
        filter_type = self.query_one("#filter_select", Select).value

        if filter_type == "music":
            self.filtered_results = [
                item for item in self.raw_results if item.get("is_music")
            ]
        else:
            self.filtered_results = list(self.raw_results)

        list_view = self.query_one("#results_list", ListView)
        list_view.clear()

        for item in self.filtered_results:
            tag = "🎵" if item.get("is_music") else "🎬"
            list_view.append(ListItem(Label(f"{tag} {item['title']}")))

        status = self.query_one("#status", Label)
        status.update(f"[green]Exibindo {len(self.filtered_results)} item(ns).[/green]")

    # --- AUTENTICAÇÃO E CURTIDAS COM PAGINAÇÃO ---

    def _authenticate_youtube(self) -> None:
        status = self.query_one("#status", Label)
        status.update("[yellow]Abra o navegador para autorizar o acesso...[/yellow]")

        try:
            self.youtube_api = get_youtube_service(interactive=True)
            self.call_from_thread(status.update, "[green]Login realizado com sucesso![/green]")
        except Exception as e:
            self.call_from_thread(status.update, f"[red]Erro na autenticação: {e}[/red]")

    def _fetch_liked_videos(self, load_more=False) -> None:
        status = self.query_one("#status", Label)
        status.update("[yellow]Carregando músicas curtidas...[/yellow]")

        def fetch_task():
            try:
                if not self.youtube_api:
                    self.youtube_api = get_youtube_service(interactive=True)

                kwargs = {
                    "part": "snippet",
                    "myRating": "like",
                    "maxResults": 20,
                }
                if load_more and self.next_page_token:
                    kwargs["pageToken"] = self.next_page_token

                request = self.youtube_api.videos().list(**kwargs)
                response = request.execute()

                items = response.get("items", [])
                self.next_page_token = response.get("nextPageToken")

                new_items = [
                    {
                        "title": item["snippet"]["title"],
                        "url": f"https://www.youtube.com/watch?v={item['id']}",
                        "is_music": item["snippet"].get("categoryId") == MUSIC_CATEGORY_ID,
                    }
                    for item in items
                ]

                if load_more:
                    self.raw_results.extend(new_items)
                else:
                    self.raw_results = new_items

                self.last_source_type = "liked"
                self.is_loading_more = False
                self.call_from_thread(self._apply_filter_and_update_ui)

            except Exception as e:
                self.is_loading_more = False
                self.call_from_thread(status.update, f"[red]Erro ao carregar curtidas: {e}[/red]")

        if not self.is_loading_more:
            self.is_loading_more = True
            threading.Thread(target=fetch_task, daemon=True).start()

    # --- BUSCA COM YT-DLP E PAGINAÇÃO ---

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return

        self.last_query = query
        self.next_page_token = None
        self.raw_results = []

        status = self.query_one("#status", Label)
        status.update("[yellow]Buscando no YouTube...[/yellow]")

        threading.Thread(
            target=self._search_youtube, args=(query, False), daemon=True
        ).start()

    def _search_youtube(self, query: str, load_more=False) -> None:
        offset = len(self.raw_results) + 1 if load_more else 1

        ydl_opts = {
            "format": "bestaudio/best/best",
            "quiet": True,
            "playliststart": offset,
            "playlistend": offset + 15,
            "default_search": f"ytsearch{offset + 15}",
            "noplaylist": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                entries = info.get("entries", [])

                new_entries = [
                    {
                        "title": entry.get("title"),
                        "url": entry.get("webpage_url") or entry.get("url"),
                        "duration": entry.get("duration", 0),
                        "is_music": entry.get("categories") and "Music" in entry.get("categories") or True,
                    }
                    for entry in entries
                    if entry
                ]

            if load_more:
                self.raw_results.extend(new_entries)
            else:
                self.raw_results = new_entries

            self.last_source_type = "search"
            self.is_loading_more = False
            self.call_from_thread(self._apply_filter_and_update_ui)
        except Exception as e:
            self.is_loading_more = False
            self.call_from_thread(
                self.query_one("#status", Label).update,
                f"[red]Erro na busca: {e}[/red]",
            )

    def _load_more_content(self) -> None:
        if self.is_loading_more:
            return

        if self.last_source_type == "liked":
            self._fetch_liked_videos(load_more=True)
        elif self.last_source_type == "search" and self.last_query:
            self.is_loading_more = True
            threading.Thread(
                target=self._search_youtube, args=(self.last_query, True), daemon=True
            ).start()

    # --- REPRODUÇÃO E ÁUDIO ---

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is not None and index < len(self.filtered_results):
            selected_track = self.filtered_results[index]
            self._play_stream(selected_track)

            if index >= len(self.filtered_results) - 2:
                self._load_more_content()

    def _play_stream(self, track: dict) -> None:
        now_playing = self.query_one("#now-playing", Label)
        status = self.query_one("#status", Label)

        self._stop_audio()

        now_playing.update(f"[bold cyan]Tocando:[/bold cyan] {track['title']}")
        status.update("[yellow]Obtendo áudio...[/yellow]")

        def stream_worker():
            max_retries = 3
            retry_count = 0

            self.stop_event.clear()
            self.pause_event.set()

            while retry_count <= max_retries and not self.stop_event.is_set():
                try:
                    ydl_opts = {
                        "format": "bestaudio/best",
                        "quiet": True,
                        "nocheckcertificate": True,
                    }

                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(track["url"], download=False)
                        direct_url = info["url"]
                        self.duration_seconds = info.get("duration", 0)

                    container_options = {
                        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        "reconnect": "1",
                        "reconnect_streamed": "1",
                        "reconnect_delay_max": "5",
                    }

                    container = av.open(direct_url, options=container_options)
                    audio_stream = next(s for s in container.streams if s.type == "audio")
                    sample_rate = audio_stream.codec_context.sample_rate or 48000
                    time_base = float(audio_stream.time_base)

                    if self.current_position_seconds > 0:
                        target_pts = int(self.current_position_seconds / time_base)
                        container.seek(target_pts, stream=audio_stream)

                    resampler = av.AudioResampler(format="fltp", layout="stereo", rate=sample_rate)

                    with sd.OutputStream(
                        samplerate=sample_rate, channels=2, dtype="float32"
                    ) as output_stream:
                        self.is_playing = True
                        self.call_from_thread(status.update, "[green]Reproduzindo ♪[/green]")

                        for packet in container.demux(audio_stream):
                            if self.stop_event.is_set():
                                break

                            if self.seek_target_seconds is not None:
                                target_pts = int(self.seek_target_seconds / time_base)
                                container.seek(target_pts, stream=audio_stream)
                                self.current_position_seconds = self.seek_target_seconds
                                self.seek_target_seconds = None
                                continue

                            for frame in packet.decode():
                                if self.stop_event.is_set():
                                    break

                                self.pause_event.wait()

                                if frame.pts is not None:
                                    self.current_position_seconds = frame.pts * time_base

                                resampled_frames = resampler.resample(frame)
                                if not resampled_frames:
                                    continue

                                for r_frame in resampled_frames:
                                    audio_array = r_frame.to_ndarray()

                                    if audio_array.ndim == 1:
                                        audio_array = np.vstack((audio_array, audio_array))

                                    audio_array = audio_array * self.volume
                                    audio_data = np.ascontiguousarray(audio_array.T, dtype=np.float32)

                                    output_stream.write(audio_data)

                                    rms = np.sqrt(np.mean(audio_data ** 2))
                                    self.call_from_thread(self._update_playback_ui, rms)

                    break

                except (av.FFmpegError, OSError, Exception) as e:
                    if self.stop_event.is_set():
                        break

                    retry_count += 1
                    if retry_count <= max_retries:
                        self.call_from_thread(
                            status.update,
                            f"[yellow]Conexão perdida. Reconectando ({retry_count}/{max_retries})...[/yellow]",
                        )
                        time.sleep(1)
                    else:
                        self.is_playing = False
                        self.call_from_thread(status.update, f"[red]Erro ao tocar: {e}[/red]")

            self.is_playing = False
            self.call_from_thread(self._reset_playback_ui)

        self.stream_thread = threading.Thread(target=stream_worker, daemon=True)
        self.stream_thread.start()

    def _update_playback_ui(self, rms_volume: float) -> None:
        curr_str = time.strftime("%M:%S", time.gmtime(self.current_position_seconds))
        tot_str = time.strftime("%M:%S", time.gmtime(self.duration_seconds))

        self.query_one("#time_current", Label).update(f"{curr_str} ")
        self.query_one("#time_total", Label).update(f" {tot_str}")

        progress_bar = self.query_one("#song_progress", ProgressBar)
        if self.duration_seconds > 0:
            progress_bar.progress = (self.current_position_seconds / self.duration_seconds) * 100

        bars = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
        level = min(int(rms_volume * 35), len(bars) - 1)
        char = bars[level]

        meter_str = f"░▒▓█ {char * 12} █▓▒░"
        self.query_one("#visualizer", Label).update(meter_str)

    def _reset_playback_ui(self) -> None:
        self.query_one("#visualizer", Label).update("░░░░░░░░░░░░░░░░░░░░")
        self.query_one("#song_progress", ProgressBar).progress = 0
        self.query_one("#time_current", Label).update("00:00 ")
        self.query_one("#time_total", Label).update(" 00:00")

    # --- CONTROLES E ATALHOS ---

    def _stop_audio(self) -> None:
        self.stop_event.set()
        self.pause_event.set()
        if self.stream_thread and self.stream_thread.is_alive():
            self.stream_thread.join(timeout=1.0)
        self.is_playing = False

    def action_toggle_play(self) -> None:
        self.toggle_audio()

    def action_volume_up(self) -> None:
        self._adjust_volume(0.05)

    def action_volume_down(self) -> None:
        self._adjust_volume(-0.05)

    def _adjust_volume(self, delta: float) -> None:
        self.volume = max(0.0, min(1.0, self.volume + delta))
        vol_pct = int(self.volume * 100)
        self.query_one("#vol_label", Label).update(f" Volume: {vol_pct}% ")

    def _seek(self, seconds_delta: float) -> None:
        new_pos = max(0, self.current_position_seconds + seconds_delta)
        if self.duration_seconds > 0:
            new_pos = min(self.duration_seconds - 1, new_pos)
        self.seek_target_seconds = new_pos

    def on_button_pressed(self, event: Button.Pressed) -> None:
        b_id = event.button.id
        if b_id == "btn_toggle":
            self.toggle_audio()
        elif b_id == "btn_stop":
            self._stop_audio()
            self._reset_playback_ui()
            self.query_one("#status", Label).update("Reprodução parada.")
            self.query_one("#now-playing", Label).update("Nenhuma música selecionada")
        elif b_id == "btn_vol_up":
            self._adjust_volume(0.1)
        elif b_id == "btn_vol_down":
            self._adjust_volume(-0.1)
        elif b_id == "btn_rewind":
            self._seek(-10)
        elif b_id == "btn_forward":
            self._seek(10)
        elif b_id == "btn_login":
            threading.Thread(target=self._authenticate_youtube, daemon=True).start()
        elif b_id == "btn_liked":
            self.last_query = ""
            self.next_page_token = None
            self._fetch_liked_videos()
        elif b_id == "btn_load_more":
            self._load_more_content()

    def toggle_audio(self) -> None:
        if not self.stream_thread or not self.stream_thread.is_alive():
            return

        if self.is_playing:
            self.pause_event.clear()
            self.is_playing = False
            self.query_one("#status", Label).update("Pausado ⏸")
        else:
            self.pause_event.set()
            self.is_playing = True
            self.query_one("#status", Label).update("Reproduzindo ♪")


if __name__ == "__main__":
    app = MusicPlayerApp()
    app.run()