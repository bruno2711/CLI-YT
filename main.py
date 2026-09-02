import threading
import yt_dlp
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, ProgressBar, Static
import os
# Força o SDL a usar o driver dummy para não procurar placa de som física
os.environ["SDL_AUDIODRIVER"] = "dummy"
import pygame

class MusicPlayerApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }

    #main {
        height: 1fr;
    }

    /* Sidebar / Busca */
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

    #results-list {
        height: 1fr;
        border: solid $accent;
    }

    /* Área Principal de Reprodução */
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
        self.is_playing = False
        self.search_results = []
        
        # Tenta inicializar o som nativo; se falhar (Codespace/Docker), ativa o driver dummy
        try:
            pygame.mixer.init()
        except pygame.error:
            os.environ["SDL_AUDIODRIVER"] = "dummy"
            pygame.mixer.init()
            print("Aviso: Dispositivo de áudio não encontrado. Modo de simulação/dummy ativado.")

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main"):
            # Sidebar com busca
            with Vertical(id="sidebar"):
                yield Label("[bold]Buscar Música[/bold]")
                yield Input(placeholder="Nome ou artista...", id="search_input")
                yield ListView(id="results_list")

            # Conteúdo central com player
            with Vertical(id="content"):
                yield Label("Nenhuma música selecionada", id="now-playing")
                
                with Horizontal(id="controls"):
                    yield Button("▶ / ⏸ (Espaço)", id="btn_toggle", variant="primary")
                    yield Button("⏹ Parar", id="btn_stop", variant="error")

                yield Label("Status: Aguardando...", id="status")

        yield Footer()

    # --- BUSCA COM YT-DLP ---

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Disparado ao pressionar Enter na caixa de busca."""
        query = event.value.strip()
        if not query:
            return

        status = self.query_one("#status", Label)
        status.update("[yellow]Buscando no YouTube...[/yellow]")

        # Executa a busca em uma thread paralela para não travar a TUI
        threading.Thread(target=self._search_youtube, args=(query,), daemon=True).start()

    def _search_youtube(self, query: str) -> None:
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'default_search': 'ytsearch5',
            'noplaylist': True,
            # Força o uso de clientes móveis para evitar o bloqueio de bot
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'mweb'],
                }
            },
            # Adiciona um User-Agent de navegador comum
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                entries = info.get('entries', [])

                self.search_results = [
                    {
                        "title": entry.get("title"),
                        "url": entry.get("url"),
                        "duration": entry.get("duration"),
                    }
                    for entry in entries
                ]

            # Atualiza a interface na thread principal do Textual
            self.call_from_thread(self._update_results_ui)
        except Exception as e:
            self.call_from_thread(
                self.query_one("#status", Label).update, f"[red]Erro na busca: {e}[/red]"
            )

    def _update_results_ui(self) -> None:
        list_view = self.query_one("#results_list", ListView)
        list_view.clear()

        for item in self.search_results:
            list_view.append(ListItem(Label(item["title"])))

        status = self.query_one("#status", Label)
        status.update("[green]Busca concluída! Selecione na lista.[/green]")

    # --- REPRODUÇÃO DE ÁUDIO ---

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Disparado quando o usuário escolhe um item da lista."""
        index = event.list_view.index
        if index is not None and index < len(self.search_results):
            selected_track = self.search_results[index]
            self._play_stream(selected_track)

    def _play_stream(self, track: dict) -> None:
        now_playing = self.query_one("#now-playing", Label)
        status = self.query_one("#status", Label)

        now_playing.update(f"[bold cyan]Tocando:[/bold cyan] {track['title']}")
        status.update("[yellow]Carregando stream de áudio...[/yellow]")

        def load_and_play():
            try:
                # Carrega a URL direta do áudio no Pygame
                pygame.mixer.music.load(track["url"])
                pygame.mixer.music.play()
                self.is_playing = True
                self.call_from_thread(status.update, "[green]Reproduzindo ♪[/green]")
            except Exception as e:
                self.call_from_thread(status.update, f"[red]Erro ao tocar: {e}[/red]")

        threading.Thread(target=load_and_play, daemon=True).start()

    # --- CONTROLES ---

    def action_toggle_play(self) -> None:
        """Ação do atalho de teclado (Espaço)."""
        self.toggle_audio()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Clique nos botões da interface."""
        if event.button.id == "btn_toggle":
            self.toggle_audio()
        elif event.button.id == "btn_stop":
            pygame.mixer.music.stop()
            self.is_playing = False
            self.query_one("#status", Label).update("Reprodução parada.")
            self.query_one("#now-playing", Label).update("Nenhuma música selecionada")

    def toggle_audio(self) -> None:
        if pygame.mixer.music.get_busy():
            if self.is_playing:
                pygame.mixer.music.pause()
                self.is_playing = False
                self.query_one("#status", Label).update("Pausado ⏸")
            else:
                pygame.mixer.music.unpause()
                self.is_playing = True
                self.query_one("#status", Label).update("Reproduzindo ♪")


if __name__ == "__main__":
    app = MusicPlayerApp()
    app.run()