# Music Tracks

Plataforma local para separar músicas em faixas (stems) e praticar com elas: mixer com mute/solo/volume, velocidade sem mudar o tom, transposição, loop A-B, metrônomo sincronizado, BPM, tonalidade e acordes. Interface em português e inglês.

Especificação completa: [`docs/spec.md`](docs/spec.md).

## Requisitos

macOS (Apple Silicon), [Homebrew](https://brew.sh) e:

```sh
brew install uv node ffmpeg
```

## Uso

```sh
./start.sh
```

Na primeira execução o script instala as dependências e compila a interface. Depois ele abre `http://127.0.0.1:8765`. A primeira separação baixa os modelos (~320 MB por modelo).

- **Pasta de dados:** `~/MusicTracks` (mude em Configurações ou com `MUSIC_TRACKS_HOME=/caminho ./start.sh`).
- **Pasta monitorada:** jogue arquivos de áudio em `~/MusicTracks/inbox/` e eles entram na fila sozinhos.
- **Porta:** `MUSIC_TRACKS_PORT=9000 ./start.sh`.
- **Atualizar o yt-dlp** (quando o YouTube parar de funcionar):
  ```sh
  cd backend && uv lock --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs && uv sync
  ```

### Modos de separação

| Modo | Faixas | Modelo | Tempo aprox. (4 min, M4) |
|---|---|---|---|
| 2 | voz, instrumental | htdemucs_ft | ~1 min |
| 4 | voz, bateria, baixo, outros | htdemucs_ft | ~1 min |
| 6 | + guitarra, piano | htdemucs_6s | ~30 s (piano com qualidade baixa) |

### Atalhos do player

`Espaço` tocar/pausar · `←/→` ±5 s · `[` / `]` marcar A/B · `L` liga/desliga loop · `M` marcador · `K` metrônomo

## Desenvolvimento

```sh
./dev.sh                                  # worker + API com reload + Vite em http://localhost:5173
cd backend && uv run pytest -q           # testes rápidos (offline)
cd backend && uv run pytest -q -m slow   # testes com modelos reais
cd frontend && npm test                  # testes do frontend
```

Estrutura: `backend/app/api` (FastAPI), `backend/app/worker` (fila e pipeline), `backend/app/analysis` (batidas, tom, acordes, waveforms), `frontend/src` (React + TypeScript).
