import threading
from io import BytesIO
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
)


class MusicPlayerApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }

    #main {
        height: 1fr;
    }

    #sidebar {
        width: 40;
        height: 100%;
        background: $panel;
        border-right: heavy $accent;
        padding: 1;
    }

    #sidebar Input {
        margin-bottom: 1;
    }

    #results_list {
        height: 1fr;
        border: solid $accent;
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
        margin-bottom: 2;
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
    ]

    def __init__(self):
        super().__init__()
        self.stream_thread = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()  # Inicia despausado
        self.is_playing = False
        self.search_results = []

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Label("[bold]Buscar Música[/bold]")
                yield Input(placeholder="Nome ou artista...", id="search_input")
                yield ListView(id="results_list")

            with Vertical(id="content"):
                yield Label("Nenhuma música selecionada", id="now-playing")

                with Horizontal(id="controls"):
                    yield Button(
                        "▶ / ⏸ (Espaço)", id="btn_toggle", variant="primary"
                    )
                    yield Button("⏹ Parar", id="btn_stop", variant="error")

                yield Label("Status: Aguardando...", id="status")

        yield Footer()

    # --- BUSCA COM YT-DLP ---

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return

        status = self.query_one("#status", Label)
        status.update("[yellow]Buscando no YouTube...[/yellow]")

        threading.Thread(
            target=self._search_youtube, args=(query,), daemon=True
        ).start()

    def _search_youtube(self, query: str) -> None:
        ydl_opts = {
            "format": "bestaudio/best/best",
            "quiet": True,
            "default_search": "ytsearch5",
            "noplaylist": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            },
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                entries = info.get("entries", [])

                self.search_results = [
                    {
                        "title": entry.get("title"),
                        "url": entry.get("webpage_url") or entry.get("url"),
                        "duration": entry.get("duration"),
                    }
                    for entry in entries
                    if entry
                ]

            self.call_from_thread(self._update_results_ui)
        except Exception as e:
            self.call_from_thread(
                self.query_one("#status", Label).update,
                f"[red]Erro na busca: {e}[/red]",
            )

    def _update_results_ui(self) -> None:
        list_view = self.query_one("#results_list", ListView)
        list_view.clear()

        for item in self.search_results:
            list_view.append(ListItem(Label(item["title"])))

        status = self.query_one("#status", Label)
        status.update("[green]Busca concluída! Selecione na lista.[/green]")

    # --- STREAMING & DECODIFICAÇÃO (PYAV + SOUNDDEVICE) ---

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is not None and index < len(self.search_results):
            selected_track = self.search_results[index]
            self._play_stream(selected_track)

    def _play_stream(self, track: dict) -> None:
        now_playing = self.query_one("#now-playing", Label)
        status = self.query_one("#status", Label)

        self._stop_audio()

        now_playing.update(f"[bold cyan]Tocando:[/bold cyan] {track['title']}")
        status.update("[yellow]Iniciando streaming...[/yellow]")

        def stream_worker():
            ydl_opts = {
                "format": "bestaudio/best",
                "quiet": True,
                "extractor_args": {
                    "youtube": {"player_client": ["android", "web"]}
                },
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(track["url"], download=False)
                    direct_url = info["url"]

                container = av.open(direct_url)
                audio_stream = next(
                    s for s in container.streams if s.type == "audio"
                )

                # Obtém a taxa de amostragem real do fluxo do YouTube (geralmente 48000 Hz)
                sample_rate = audio_stream.codec_context.sample_rate or 48000

                # Resampler configurado exatamente para o sample_rate nativo da mídia
                resampler = av.AudioResampler(
                    format="fltp", layout="stereo", rate=sample_rate
                )

                self.stop_event.clear()
                self.pause_event.set()

                # Usa a mesma taxa de amostragem do áudio para o dispositivo de saída
                with sd.OutputStream(
                    samplerate=sample_rate, channels=2, dtype="float32"
                ) as output_stream:
                    self.is_playing = True
                    self.call_from_thread(
                        status.update, "[green]Reproduzindo ♪[/green]"
                    )

                    for packet in container.demux(audio_stream):
                        if self.stop_event.is_set():
                            break

                        for frame in packet.decode():
                            if self.stop_event.is_set():
                                break

                            self.pause_event.wait()

                            resampled_frames = resampler.resample(frame)
                            if not resampled_frames:
                                continue

                            for r_frame in resampled_frames:
                                # Converte e formata os canais no formato plano (2, N_amostras)
                                audio_array = r_frame.to_ndarray()

                                if audio_array.ndim == 1:
                                    audio_array = np.vstack(
                                        (audio_array, audio_array)
                                    )

                                # Transpõe para (N_amostras, 2)
                                audio_data = np.ascontiguousarray(
                                    audio_array.T, dtype=np.float32
                                )

                                output_stream.write(audio_data)

                self.is_playing = False
            except Exception as e:
                self.is_playing = False
                self.call_from_thread(
                    status.update, f"[red]Erro ao tocar: {e}[/red]"
                )

        self.stream_thread = threading.Thread(
            target=stream_worker, daemon=True
        )
        self.stream_thread.start()

    # --- CONTROLES DE PLAY / PAUSE / STOP ---

    def _stop_audio(self) -> None:
        self.stop_event.set()
        self.pause_event.set()
        if self.stream_thread and self.stream_thread.is_alive():
            self.stream_thread.join(timeout=1.0)
        self.is_playing = False

    def action_toggle_play(self) -> None:
        self.toggle_audio()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_toggle":
            self.toggle_audio()
        elif event.button.id == "btn_stop":
            self._stop_audio()
            self.query_one("#status", Label).update("Reprodução parada.")
            self.query_one("#now-playing", Label).update(
                "Nenhuma música selecionada"
            )

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