# Spec — Music Tracks

Plataforma local para separar músicas em faixas (stems) e praticar com elas.

## 1. Objetivo e escopo

**Problema.** O usuário quer, no próprio Mac (Apple M4, 16 GB, macOS 26), adicionar músicas, separá-las em faixas e usá-las para praticar instrumento, cantar (karaokê) e estudar arranjos — sem serviços online.

**Entrega.** Um web app local (backend Python + frontend React servidos em `http://127.0.0.1:8765`) com:

1. Entrada de músicas por upload, por URL (YouTube e demais sites suportados pelo yt-dlp) e por pasta monitorada.
2. Fila de processamento: download → preparação → separação → análise → waveforms, com progresso visível.
3. Separação em 2, 4 ou 6 stems, escolhida por música.
4. Análise: BPM, batidas e tempos fortes (downbeats), tonalidade, acordes.
5. Player/mixer multitrack: mute/solo/volume por stem, velocidade 50–150% sem mudar o tom, transposição ±12 semitons sem mudar a velocidade, loop A-B, marcadores, metrônomo sincronizado, exibição de acordes.
6. Biblioteca: busca, ordenação, metadados e capa editáveis, tags, favoritos, notas.
7. Exportação: stem individual, ZIP com todos os stems, mix customizado; em WAV, FLAC ou MP3.
8. Interface em inglês e português do Brasil, configurável.

**Fora do escopo.** Acesso por outros dispositivos da rede (o servidor escuta só em `127.0.0.1`), autenticação, multiusuário, Docker, app desktop empacotado, letras/transcrição, playlists ordenadas (tags cumprem esse papel), edição de áudio (cortar, aplicar efeitos), pan por stem, sincronização em nuvem, Windows/Linux (pode funcionar, mas não é verificado). **Navegador suportado:** Chrome/Edge atuais; Safari pode funcionar, mas não é verificado.

## 2. Glossário

| Termo | Significado |
|---|---|
| **Música** (`song`) | Item da biblioteca: o áudio original mais tudo que deriva dele. |
| **Stem** | Faixa separada de uma música. Nomes fixos: `vocals`, `instrumental`, `drums`, `bass`, `guitar`, `piano`, `other`. |
| **Modo de stems** (`stem_mode`) | `2` → `vocals`, `instrumental`; `4` → `vocals`, `drums`, `bass`, `other`; `6` → `vocals`, `drums`, `bass`, `guitar`, `piano`, `other`. A ordem listada é a ordem de exibição no mixer. |
| **Job** | Uma execução do pipeline de processamento para uma música. |
| **Pasta de dados** (`DATA_DIR`) | Diretório onde ficam banco, áudio e caches (§6.1). |
| **Tempo de origem** | Posição em segundos no áudio original, independente da velocidade de reprodução. Todos os tempos persistidos (marcadores, loops, batidas, acordes) estão em tempo de origem. |

## 3. Arquitetura

```
navegador (React SPA) ──HTTP JSON/arquivos──▶ api (FastAPI, uvicorn, 127.0.0.1:8765)
                                                 │  SQLite (WAL)
                                                 ▼
                                   worker (processo Python separado)
                                     ├─ consome a fila de jobs (1 por vez)
                                     └─ varre a pasta monitorada a cada 5 s
```

- **Dois processos Python**, iniciados juntos por `./start.sh`: `api` e `worker`. Comunicação só via SQLite (modo WAL, `busy_timeout=5000`). O worker é separado para que separação pesada (GPU/memória) ou um crash não derrube a API, e para manter modelos carregados entre jobs.
- O frontend compilado (`frontend/dist`) é servido pela própria API em `/`; rotas desconhecidas fora de `/api` devolvem `index.html` (SPA).
- O frontend acompanha jobs por *polling* de `GET /api/jobs` a cada 1 s enquanto houver job `queued`/`running`, e a cada 10 s caso contrário (para notar itens da pasta monitorada).

### 3.1 Stack e versões

Python **3.12** (gerenciado por `uv`; `requires-python = "==3.12.*"`). Versões fixadas no `pyproject.toml`/`uv.lock`. O `pyproject.toml` declara `[tool.uv] environments = ["sys_platform == 'darwin' and platform_machine == 'arm64'"]` — sem isso o uv resolve `torch<2.3` (ramo Intel do demucs) para todas as plataformas.

| Função | Pacote |
|---|---|
| API | `fastapi`, `uvicorn[standard]`, `python-multipart` |
| Banco | `sqlalchemy` 2.x (SQLite) |
| Separação | `demucs==4.1.0`, `torch==2.14.1` (MPS) — §7.3 |
| Batidas/BPM | `beat-this==1.1.0` (CPU) |
| Tonalidade | `essentia==2.1b6.dev1389` (wheel macOS 15+ arm64, cp312) |
| Acordes, chroma | `librosa==1.0.1`, `numpy`, `scipy` |
| Áudio I/O | `soundfile`, `soxr`; `ffmpeg`/`ffprobe` do sistema (Homebrew) |
| Download | `yt-dlp[default]` (pacote Python com `yt-dlp-ejs`, não o binário do sistema), sempre com `js_runtimes={"node": {}}` (usa o Node já exigido) para resolver os desafios do YouTube. Atualização: `uv lock --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs && uv sync` |
| Metadados, capa | `mutagen`, `Pillow` |
| Time-stretch na exportação | `python-stretch==0.3.1` (Signalsmith Stretch, MIT) |
| Testes | `pytest`, `httpx` |

Frontend: Node ≥ 20, **React 19 + TypeScript + Vite**, `@tanstack/react-query`, `react-router`, **Tailwind CSS 4**, `signalsmith-stretch@1.3.2` (versão exata; o pacote não traz tipos — o projeto declara um `.d.ts` próprio). Testes: `vitest`.

Dependências de sistema verificadas por `./start.sh`: `uv`, `node`/`npm`, `ffmpeg`, `ffprobe`. Se faltar alguma, o script imprime o comando `brew install …` correspondente e sai com código 1.

## 4. Execução

- `./start.sh`:
  1. Verifica dependências de sistema.
  2. `uv sync` no backend.
  3. Se `frontend/dist` não existir ou algum arquivo em `frontend/src` for mais novo que `frontend/dist/index.html`: `npm ci` (só se `node_modules` faltar) e `npm run build`.
  4. Sobe `worker` e `api` (`uvicorn ... --host 127.0.0.1 --port 8765`), espera `GET /api/health` responder (até 30 s) e abre o navegador (`open http://127.0.0.1:8765`).
  5. `Ctrl+C` encerra os dois processos (trap em `SIGINT`/`SIGTERM`). Se o `worker` morrer, o script registra e o reinicia (até 3 reinícios em 5 min; depois encerra a API e sai com código 1). Se a `api` morrer, encerra o worker e sai com código 1.
- Porta ocupada: o script detecta (`lsof -i :8765`), informa e sai com código 1. Porta configurável por `MUSIC_TRACKS_PORT`.
- `./dev.sh` (exporta `MUSIC_TRACKS_DEV=1`): worker (sem reload) + API com `--reload` + `vite` dev server (porta 5173) com proxy `/api` → 8765 (`changeOrigin: true`, para passar na checagem de `Host` do §12).

## 5. Interface

### 5.1 Telas

1. **Biblioteca** (`/`): grade de cartões (capa, título, artista, duração, BPM, tom, modo de stems, estrela de favorito, tags, estado). Barra superior com busca, filtros (favoritas, tag, estado) e ordenação. Botão "Adicionar música" abre um diálogo com duas abas: **Arquivo** (arrastar e soltar ou escolher; múltiplos arquivos permitidos) e **URL**; ambas com seletor de modo de stems (padrão = configuração). Painel lateral recolhível "Fila" lista jobs ativos e os últimos 20 finalizados, com progresso, cancelar e tentar de novo.
2. **Música** (`/songs/:id`): player/mixer (§9), cabeçalho com metadados editáveis, tags, favorito, notas, exportação e "Reprocessar" (com seletor de modo, padrão = modo atual). Por estado: `pending`/`processing` → progresso do job (mesmo texto da fila) e Cancelar, sem player; `ready` → player; se houver job ativo (reprocessamento), uma faixa "Reprocessando… <progresso>" acima do player, que continua funcionando com os stems atuais, e quando o job vira `done` a página recarrega stems, peaks e análise (posição volta a 0, pausado); `failed` → erro traduzido (ou "Cancelado"), "Tentar de novo" e "Apagar".
3. **Configurações** (`/settings`): idioma, modo de stems padrão, pasta de dados, volume padrão do metrônomo, informação do sistema (dispositivo de separação, modelos baixados, versão do ffmpeg).

### 5.2 Visual

Tema escuro estilo DAW, sem modo claro. Cada stem tem uma cor fixa usada na waveform e no canal do mixer: `vocals` #F472B6, `instrumental` #A78BFA, `drums` #F59E0B, `bass` #22D3EE, `guitar` #F97316, `piano` #34D399, `other` #94A3B8. Layout funcional a partir de 1024 px de largura; abaixo disso não é otimizado.

### 5.3 Idiomas

- Idiomas: `en` e `pt-BR`. Todas as strings da UI vêm de dicionários tipados (`frontend/src/i18n/en.ts`, `pt-BR.ts`); um teste verifica que os dois têm exatamente as mesmas chaves.
- Idioma inicial: o salvo nas configurações; se nunca configurado, `pt-BR` quando `navigator.language` começa com `pt`, senão `en`.
- A API nunca devolve texto para o usuário: erros têm `code` (§8.3) e a UI traduz. Mensagens técnicas (`detail`) podem aparecer num "ver detalhes" recolhível, sem tradução.
- Nomes de stems e estados são traduzidos. Tonalidades: em `en`, letras (`A minor`, `F# major`); em `pt-BR`, solfejo com `#` (`Lá menor`, `Fá# maior`). Acordes usam letras com sustenidos nos dois idiomas (`C C# D D# E F F# G G# A A# B`, ex.: `Am`, `F#m7`); `N` aparece como "—".

## 6. Armazenamento

### 6.1 Pasta de dados

- Resolução de `DATA_DIR`, em ordem: variável `MUSIC_TRACKS_HOME`; campo `data_dir` de `~/.config/music-tracks/config.json`; padrão `~/MusicTracks`.
- Alterar a pasta pela tela de Configurações grava `config.json` e exibe o aviso "reinicie a plataforma para aplicar". **Não move dados**: a nova pasta começa vazia (ou com a biblioteca que já existir nela). A validação aceita apenas caminho absoluto (ou começando com `~`) de diretório existente e gravável, ou inexistente cujo pai seja gravável (é criado). Se `MUSIC_TRACKS_HOME` estiver definida, o campo aparece somente leitura com a explicação.
- Estrutura:

```
DATA_DIR/
  library.db
  inbox/                 pasta monitorada
    _ignorados/          arquivos rejeitados da pasta monitorada (+ <nome>.erro.txt)
  songs/<song_id>/
    original.<ext>       arquivo como recebido
    stems/<stem>.flac    44,1 kHz, estéreo, 24 bits
    peaks.json           waveforms (§7.5)
    analysis.json        análise (§7.4)
    cover.jpg            capa (opcional)
  models/                cache de modelos (TORCH_HOME e afins apontam para cá)
  logs/                  api.log, worker.log
  tmp/
    jobs/<job_id>/       pastas de trabalho dos jobs (limpo pelo worker ao iniciar)
    api/                 uploads em andamento e exportações (limpo pela API ao iniciar)
```

- `source.wav` (PCM 44,1 kHz estéreo float32) é gerado pelo `prepare` em `tmp/jobs/<job_id>/source.wav` e some com a pasta de trabalho ao fim do job, qualquer que seja o resultado. Nunca é reaproveitado entre jobs.

### 6.2 Modelo de dados (SQLite)

`songs`
| coluna | tipo | notas |
|---|---|---|
| id | TEXT PK | UUID4 |
| title | TEXT NOT NULL | |
| artist, album | TEXT NULL | |
| duration_s | REAL NULL | preenchido após a preparação |
| source_type | TEXT | `file` \| `url` \| `watch` |
| source_url | TEXT NULL | URL original |
| source_key | TEXT NULL UNIQUE | chave de duplicidade (§8.2) |
| original_filename | TEXT NULL | |
| original_ext | TEXT NOT NULL | |
| stem_mode | INTEGER NOT NULL | 2, 4 ou 6 — modo dos stems **disponíveis** (ou solicitados, se ainda não houver) |
| status | TEXT NOT NULL | `pending` \| `processing` \| `ready` \| `failed` |
| favorite | INTEGER NOT NULL DEFAULT 0 | |
| notes | TEXT NOT NULL DEFAULT '' | até 20 000 caracteres |
| has_cover | INTEGER NOT NULL DEFAULT 0 | |
| metadata_edited | INTEGER NOT NULL DEFAULT 0 | 1 após `PATCH` de `title`/`artist`/`album` |
| bpm | REAL NULL | |
| key_label | TEXT NULL | ex.: `A minor` |
| analysis_status | TEXT NOT NULL DEFAULT 'none' | `none` \| `ok` \| `failed` |
| player_state | TEXT NOT NULL DEFAULT '{}' | JSON (§9.6) |
| created_at, updated_at | TEXT | ISO 8601 UTC |

`jobs`: `id` UUID PK, `song_id` FK (ON DELETE CASCADE), `stem_mode`, `status` (`queued` \| `running` \| `done` \| `failed` \| `canceled`), `step` (`download` \| `prepare` \| `separate` \| `analyze` \| `peaks` \| NULL), `step_detail` (`downloading_model` \| NULL; preenchido enquanto o modelo é baixado), `step_index`, `step_count`, `step_progress` (0–100), `error_code`, `error_detail`, `cancel_requested` (0/1), `attempts` (inteiro, padrão 0), `created_at`, `started_at`, `finished_at`.

`tags`: `id` INTEGER PK, `name` TEXT UNIQUE COLLATE NOCASE (1–40 caracteres, espaços nas pontas removidos). `song_tags`: (`song_id`, `tag_id`) PK, cascade nas duas FKs. Tags sem músicas são apagadas automaticamente.

`markers`: `id` UUID PK, `song_id` FK cascade, `kind` (`marker` \| `loop`), `name` (1–60), `start_s` REAL, `end_s` REAL NULL (obrigatório e > `start_s` quando `kind=loop`; nulo para `marker`), `created_at`. `start_s`/`end_s` dentro de `[0, duration_s]`. Máximo 200 por música; exceder → `VALIDATION_ERROR`. Criar/alterar marcadores exige `status=ready` (senão `SONG_NOT_READY`).

Índice `CREATE UNIQUE INDEX jobs_one_active ON jobs(song_id) WHERE status IN ('queued','running')`; `IntegrityError` nele → `JOB_ALREADY_ACTIVE` (409).

`settings`: `key` TEXT PK, `value` TEXT (JSON). Chaves: `language` (`en`\|`pt-BR`\|null), `default_stem_mode` (2\|4\|6, padrão 4), `metronome_volume` (0–100, padrão 70).

Schema criado na inicialização (`CREATE TABLE IF NOT EXISTS`); a tabela `schema_version` guarda a versão (1) para migrações futuras.

## 7. Pipeline de processamento

### 7.1 Fila

- Um job por vez, ordem FIFO por `created_at`. O worker consulta a fila a cada 1 s e assume o job com `UPDATE … SET status='running', attempts=attempts+1 WHERE id=? AND status='queued'`. Criar um job para uma música que já tem job `queued` ou `running` → erro `JOB_ALREADY_ACTIVE` (409).
- Ao criar um job para uma música sem stems, `songs.stem_mode` recebe o modo do job na mesma transação.
- **Transições de `songs.status`:** criar job (upload, URL, pasta, retry, reprocess) → `pending`, exceto se a música já tem stems (fica `ready`); worker inicia o job → `processing` (idem: música com stems continua `ready`). Ou seja, uma música com stems está sempre `ready` e tocável; o job ativo é informado à parte.
- **Recuperação:** ao iniciar, o worker (1) para cada `songs/<id>/` com algum `.old` (`stems.old/`, `peaks.json.old`, `analysis.json.old`): se o job mais recente da música ainda está `running` (troca não confirmada), apaga os `stems/`, `peaks.json` e `analysis.json` novos que existirem e renomeia todos os `.old` de volta; senão apaga os `.old`; (2) jobs `running` com `attempts < 2` voltam para `queued` (música sem stems volta para `pending`) (recomeçam do zero; o reprocessamento corrige qualquer estado intermediário); com `attempts >= 2` viram `failed` com `INTERNAL_ERROR` e `error_detail='worker crashed twice'` (a música segue as regras de estado final abaixo); (3) limpa `DATA_DIR/tmp/jobs` (nunca toca `tmp/api`).
- **Cancelamento:** `POST /api/jobs/{id}/cancel`. Job `queued` → `canceled` imediatamente. Job `running` → `cancel_requested=1`; o worker verifica a flag nos callbacks de progresso (no mínimo a cada chunk de separação e entre etapas) e encerra em até ~10 s, apagando a pasta de trabalho do job, marcando `canceled`.
- Estado da música ao final do job:
  - Sucesso → `ready`.
  - Falha/cancelamento numa música que já tinha stems (reprocessamento) → volta para `ready` com os stems antigos intactos.
  - Falha/cancelamento sem stems anteriores → `failed`.
- `POST /api/jobs/{id}/retry` (só para `failed`/`canceled`, e se a música não tiver outro job ativo) cria um novo job com o mesmo `stem_mode`. Retry de job em outro estado ou cancel de job já finalizado → 409 `INVALID_STATE`.

### 7.2 Etapas

Cada job trabalha em `DATA_DIR/tmp/jobs/<job_id>/` e só no fim faz a troca, nesta ordem: renomear `stems/`, `peaks.json`, `analysis.json` antigos para `.old` → mover os novos → `UPDATE songs` (`stem_mode`, `bpm`, `key_label`, `analysis_status`, `status`) e `UPDATE jobs SET status='done'` **na mesma transação** → apagar os `.old`. Assim um reprocessamento com falha nunca deixa a música sem stems, e a recuperação (§7.1) resolve um crash no meio da troca.

| # | Etapa | O que faz | Progresso |
|---|---|---|---|
| 1 | `download` (só se `source_type=url` e `original.*` ainda não existe) | yt-dlp baixa apenas o áudio (`format=bestaudio/best`, `noplaylist=True`, `max_filesize` 500 MB; como o yt-dlp apenas pula o download nesse caso, arquivo final ausente ou `filesize`/`filesize_approx` > 500 MB → `FILE_TOO_LARGE`) em `tmp/jobs/<job_id>/` e move para `original.<ext>` ao concluir; extrai título, artista (`artist` → `creator` → `uploader`), álbum, thumbnail (convertida para `cover.jpg` 600×600 máx.). | % do yt-dlp |
| 2 | `prepare` | `ffprobe` valida (§8.1); `ffmpeg` converte para `source.wav` (44,1 kHz, estéreo — mono é duplicado — float32). Lê tags com `mutagen` (título, artista, álbum, capa embutida) **somente no primeiro job da música** (`duration_s` ainda nulo) e só para origem `file`/`watch`; reprocessamentos e retries nunca alteram metadados nem capa. Grava `duration_s`. | 0 → 100 |
| 3 | `separate` | §7.3 | % de chunks |
| 4 | `analyze` | §7.4. **Falha aqui não falha o job:** grava `analysis_status=failed` e segue. | 33/66/100 (batidas/tom/acordes) |
| 5 | `peaks` | §7.5 | 0 → 100 |

`step_count` é 5 quando a etapa `download` roda e 4 nos demais casos.

**Metadados extraídos** (`download` e `prepare`): só são gravados no primeiro job que chega à etapa (`duration_s` ainda nulo); título/artista/álbum só se `metadata_edited=0`, e capa só se `has_cover=0`. A UI mostra `"<step_index>/<step_count> <nome da etapa> <step_progress>%"`.

Título padrão quando não há metadado: nome do arquivo sem extensão (upload/pasta) ou título do vídeo (URL).

### 7.3 Separação

Motor: **`demucs==4.1.0`** (repositório do autor original; modelos em safetensors via Hugging Face), executado dentro do processo worker.

| Modo | Modelo | Stems gravados | Tempo de referência (4 min, M4/MPS) |
|---|---|---|---|
| 2 | `htdemucs_ft` | `vocals`; `instrumental` = soma de `drums`+`bass`+`other` | ~62 s |
| 4 | `htdemucs_ft` | `vocals`, `drums`, `bass`, `other` | ~62 s |
| 6 | `htdemucs_6s` | `vocals`, `drums`, `bass`, `guitar`, `piano`, `other` | ~25 s |

- Parâmetros: `demucs.api.Separator(model=..., device=..., shifts=1, overlap=0.25, split=True, progress=False, callback=cb)`; entrada `source.wav`; `separate_tensor`. Antes de gravar, calcula `peak` = máximo absoluto sobre todos os stems a gravar; se `peak > 0.99`, multiplica todos pelo mesmo fator `0.98/peak` (preserva os níveis relativos). Grava com `demucs.audio.save_audio(..., bits_per_sample=24, clip="none")`, 44,1 kHz.
- Dispositivo: `mps` se `torch.backends.mps.is_available()`, senão `cpu`. `PYTORCH_ENABLE_MPS_FALLBACK=1` definido antes de importar torch. Se a separação em `mps` levantar erro de memória ou erro de runtime do MPS, repete **uma vez** em `cpu`; falhando de novo → `OUT_OF_MEMORY` (erro de memória) ou `SEPARATION_FAILED` (outros).
- Progresso: no callback, quando `state == "end"`, `done = (model_idx_in_bag + segment_offset/audio_length) / models`; `step_progress = min(99, int(done×100))`. O callback também verifica `cancel_requested` e levanta uma exceção interna de cancelamento.
- O `Separator` de cada modelo é criado na primeira utilização e mantido em cache no worker (no máximo um modelo carregado: trocar de modelo libera o anterior e chama `torch.mps.empty_cache()`).
- Modelos: `HF_HOME=DATA_DIR/models/hf` e `TORCH_HOME=DATA_DIR/models/torch` (este para o checkpoint do `beat_this`). Na primeira execução o download (~320 MB por modelo) acontece dentro da etapa `separate`; enquanto isso o worker grava `step_detail=downloading_model` e a UI mostra "Baixando modelo (primeira vez)". Sem internet nessa situação → `SEPARATION_FAILED` com `detail` explicando.
- Aviso de qualidade exibido no seletor de modo: no modo 6 o stem de piano tem qualidade baixa e o de guitarra é razoável.

### 7.4 Análise

Entradas (sempre convertidas para mono):

| Saída | Entrada | Método |
|---|---|---|
| Batidas, downbeats, BPM | `source.wav` (mix completo) | `beat_this` `File2Beats(checkpoint_path="final0", device="cpu", dbn=False)`. BPM = `60 / mediana(diff(beats))`, arredondado a 0,1. Menos de 8 batidas → `bpm=null`, listas vazias. |
| Tonalidade | soma de todos os stems exceto `drums` (modo 2: `vocals`+`instrumental`) | `essentia.standard.KeyExtractor(profileType="bgate")` → `key`, `scale`, `strength`. Rótulo `"<key> <scale>"` (ex.: `A minor`); bemóis normalizados para sustenidos. |
| Acordes | soma de `bass`+`other`(+`guitar`+`piano`); modo 2: `instrumental` | Matcher próprio (abaixo). |

**Matcher de acordes** (`backend/app/analysis/chords.py`):
1. `y` a 22 050 Hz; `chroma_cqt(hop_length=2048, bins_per_octave=36)`.
2. Sincroniza com as batidas (`librosa.util.sync`, mediana): uma coluna por intervalo entre batidas. Sem batidas → janelas fixas de 0,5 s.
3. Templates L2-normalizados: 12 raízes × {`""`: 0,4,7; `m`: 0,3,7; `7`: 0,4,7,10; `m7`: 0,3,7,10; `maj7`: 0,4,7,11} + `N` (sem acorde).
4. Score = template · chroma normalizada; score de `N` = 0,25; tétrades recebem −0,03 (viés para tríades); colunas com energia total abaixo de 1% da mediana viram `N`.
5. Probabilidades `softmax(20 × score)`; Viterbi com matriz de transição diagonal 0,9 e o restante distribuído igualmente.
6. Junta colunas consecutivas iguais em segmentos `{start, end, label}`; segmentos com menos de 0,25 s são absorvidos pelo anterior.

`analysis.json`:
```json
{"version": 1, "bpm": 120.0, "beats": [0.02, 0.52], "downbeats": [0.02, 2.02],
 "key": {"label": "A minor", "tonic": "A", "scale": "minor", "confidence": 0.81},
 "chords": [{"start": 0.0, "end": 1.95, "label": "Am"}, {"start": 1.95, "end": 3.99, "label": "F"}]}
```
`bpm` e `key` também são copiados para `songs` (para listagem/ordenação). Os modelos de análise ficam carregados no worker entre jobs.

### 7.5 Waveforms (peaks)

Para cada stem: mono (média dos canais), blocos de 512 amostras, `min` e `max` por bloco, quantizados para inteiros −127..127. `peaks.json`: `{"samples_per_peak": 512, "sample_rate": 44100, "stems": {"vocals": [min0, max0, min1, max1, ...]}}`.

## 8. Entrada de músicas

### 8.1 Validação

- Extensões aceitas (sem diferenciar maiúsculas): `mp3 wav flac m4a aac ogg opus aiff aif wma webm mp4 mkv` (vídeo: só a trilha de áudio é usada). Outras → `UNSUPPORTED_FORMAT`.
- Tamanho máximo do arquivo: 500 MB → `FILE_TOO_LARGE` (413), verificado durante o upload sem guardar o arquivo inteiro em memória.
- `ffprobe` sem stream de áudio ou arquivo corrompido → `INVALID_AUDIO`.
- Duração máxima: 15 min → `TOO_LONG`; mínima: 5 s → `TOO_SHORT`. Motivo do limite: 6 stems × 15 min decodificados no navegador ≈ 1,9 GB.
- Para upload, validações de extensão e tamanho ocorrem na requisição (falha → nada é criado). `ffprobe`/duração ocorrem na etapa `prepare` (falha → job `failed` com o código).

### 8.2 Duplicidade

- `source_key`: arquivo → `sha256:<hash do conteúdo>`; URL → `url:<extractor>:<id>` obtido com `yt_dlp` `extract_info(download=False)` (ex.: `url:youtube:dQw4w9WgXcQ`).
- Se já existir música com a mesma `source_key`: upload/URL → 409 `DUPLICATE` com `existing_song_id` (a UI oferece "Abrir existente"); pasta monitorada → arquivo vai para `inbox/_ignorados/`.

### 8.3 Upload, URL e pasta monitorada

- **Upload** (`POST /api/songs/upload`, multipart, campos `file`, `stem_mode`): grava em `tmp/api/`, calcula hash em streaming, valida, cria `songs/<id>/`, move o arquivo para `original.<ext>` e só então insere música (`pending`) + job numa única transação; se a transação falhar (ex.: `IntegrityError` → `DUPLICATE`), apaga `songs/<id>/`. Múltiplos arquivos = múltiplas requisições sequenciais pela UI, cada uma com seu próprio resultado.
- **URL** (`POST /api/songs/url`, `{url, stem_mode}`): aceita apenas `http(s)`. A API faz `extract_info(download=False)` numa thread com timeout de 30 s (`socket_timeout=15`): falha → `INVALID_URL` (422); playlist (`_type == "playlist"` sem vídeo único) → `PLAYLIST_NOT_SUPPORTED` (422); `is_live` verdadeiro → `INVALID_URL`; duração conhecida > 15 min → `TOO_LONG` (desconhecida: validada no `prepare`). Sucesso → cria música (título provisório do vídeo) + job. Erro no download dentro do job → `DOWNLOAD_FAILED`.
- **Pasta monitorada** (`DATA_DIR/inbox/`): o worker varre a cada 5 s (não recursivo; ignora arquivos ocultos e `_ignorados/`; extensões não aceitas vão para `_ignorados/` com `.erro.txt` `UNSUPPORTED_FORMAT`; nomes repetidos ali ganham sufixo ` (2)`, ` (3)`…). Um arquivo só é importado quando o tamanho e o `mtime` ficam iguais em duas varreduras seguidas (arquivo terminou de ser copiado). Importação: move para `songs/<id>/original.<ext>`, cria música (`source_type=watch`, modo = padrão das configurações) + job. A pasta `songs/<id>/` é sempre criada por quem cria a música (API ou varredura da pasta), nunca pelo processamento. Em caso de rejeição (duplicado, grande demais), move para `_ignorados/` e grava `<nome>.erro.txt` com o código. A varredura roda inclusive enquanto um job está em execução (thread separada no worker).

**Códigos de erro** (resposta `{"error": {"code": "...", "detail": "...", ...}}`): `UNSUPPORTED_FORMAT`, `FILE_TOO_LARGE`, `INVALID_AUDIO`, `TOO_LONG`, `TOO_SHORT`, `DUPLICATE`, `INVALID_URL`, `PLAYLIST_NOT_SUPPORTED`, `DOWNLOAD_FAILED`, `SEPARATION_FAILED`, `OUT_OF_MEMORY`, `DISK_FULL`, `JOB_ALREADY_ACTIVE`, `NOT_FOUND`, `VALIDATION_ERROR`, `SONG_NOT_READY`, `INVALID_STATE`, `FORBIDDEN`, `INTERNAL_ERROR`. Status HTTP: `FORBIDDEN` → 403 (§12); `UNSUPPORTED_FORMAT`, `TOO_LONG`, `TOO_SHORT`, `INVALID_URL`, `PLAYLIST_NOT_SUPPORTED`, `VALIDATION_ERROR` → 422; `FILE_TOO_LARGE` → 413; `DUPLICATE`, `JOB_ALREADY_ACTIVE`, `SONG_NOT_READY`, `INVALID_STATE` → 409; `NOT_FOUND` → 404; `INTERNAL_ERROR` → 500. `INVALID_AUDIO`, `DOWNLOAD_FAILED`, `SEPARATION_FAILED`, `OUT_OF_MEMORY` e `DISK_FULL` só ocorrem dentro de jobs (`jobs.error_code`). Dentro de jobs: `OSError` com `ENOSPC` em qualquer etapa → `DISK_FULL`; falha do `ffmpeg` na conversão do `prepare` → `INVALID_AUDIO`; qualquer outra exceção não prevista → `INTERNAL_ERROR`, com `error_detail = "<tipo>: <mensagem>"` e stack trace em `worker.log`. Em corrida que viole o `UNIQUE` de `source_key`, o `IntegrityError` é tratado como `DUPLICATE`. Antes de iniciar um job, o worker exige 2 GB livres em `DATA_DIR`; senão → `DISK_FULL`.

## 9. Player e mixer

### 9.1 Motor de áudio

Tudo no navegador, com `signalsmith-stretch@1.3.2`:

- `AudioContext({sampleRate: 44100, latencyHint: "playback"})`.
- Os FLACs de todos os stems são baixados e decodificados **um de cada vez** e copiados para arrays `Float32Array` pré-alocados (2 por stem), que são **transferidos** (sem cópia) ao nó via `addBuffers(chans, chans.map(c => c.buffer))`. A UI mostra progresso "Carregando stems k/N".
- Os arrays têm o comprimento do maior stem decodificado (o resto é zero) e os 2N canais vão numa **única** chamada `addBuffers` (chamadas sucessivas concatenam no tempo).
- **Um único** nó de stretch, `SignalsmithStretch(ctx, {numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [2N]})` (sem `numberOfOutputs` explícito o processador usa só 2 canais), → `ChannelSplitter(2N)` → um `ChannelMerger(2)` + `GainNode` por stem → ganho master → destino. Um único nó garante que os stems nunca dessincronizem; mute/solo/volume agem depois do stretch e são imediatos.
- Toda mudança de reprodução (play, pause, seek, velocidade, tom, loop) é um *segmento* agendado com `node.schedule({output, input, rate, active, semitones, loopStart, loopEnd})` em `output = currentTime + latência do nó`. O frontend mantém a lista de segmentos e calcula a posição: `posição(t) = seg.input + (seg.active ? (t − seg.output) × seg.rate : 0)`, envolvida no loop quando ativo. O playhead usa `ctx.getOutputTimestamp()`.
- A lógica de tempo (segmentos → posição, batida → tempo de contexto, ganhos efetivos de mute/solo) fica em funções puras em `frontend/src/audio/timeline.ts` e `mix.ts`, cobertas por testes.

### 9.2 Controles

| Controle | Faixa / comportamento |
|---|---|
| Play/pause | Ao chegar ao fim (sem loop), pausa e volta para 0. |
| Seek | Clique na waveform/régua; ←/→ = ±5 s. |
| Volume por stem | 0–100%, padrão 100%. Ganho linear = valor/100. |
| Mute / Solo por stem | Ganho efetivo = 0 se mute, ou se algum stem está em solo e este não; senão o volume. Vários solos simultâneos permitidos. |
| Master | 0–100%. |
| Velocidade | 50–150%, passo 5% (botões) e 1% (campo numérico). Tom inalterado. |
| Transposição | −12 a +12 semitons, passo 1. Velocidade inalterada. |
| Loop A-B | Teclas `[` e `]` definem A e B na posição atual, ou arrastando na régua. `L` liga/desliga (sem as duas pontas, não faz nada). Ao ligar com o playhead fora do trecho, salta para A. Com o loop ligado, um seek para fora de [A, B] desliga o loop. Se a nova ponta inverte a ordem, a outra ponta é limpa e a nova aceita; só com ordem válida e B − A < 0,5 s a tecla é ignorada. Com uma só ponta, `player_state.loop` é salvo como `null`. |
| Marcadores | `M` cria marcador na posição atual (nome padrão "Marcador n"/"Marker n"); clique pula para ele; renomear/apagar. Loops podem ser salvos com nome e reativados. |
| Metrônomo | Liga/desliga (`K`), volume, acento no downbeat, offset −100 a +100 ms. Desabilitado se a análise falhou ou não tem batidas. |

Atalhos ativos apenas quando o foco não está num campo de texto: `Espaço` play/pause, `←/→`, `[`, `]`, `L`, `M`, `K`.

### 9.3 Metrônomo

Agendador a cada 25 ms com janela de 200 ms à frente. Para cada batida `b` (tempo de origem) que cai na janela, toca um click (`AudioBufferSourceNode`, fora do stretch) em `seg.output + (b − seg.input)/seg.rate + offset`. Dentro de loop, considera as repetições. Qualquer mudança de segmento cancela clicks agendados a partir do novo segmento e reagenda. Click: senoide curta 1 500 Hz (downbeat) / 1 000 Hz (demais), 30 ms.

### 9.4 Análise na tela

- Cabeçalho: BPM efetivo (`bpm × velocidade`, mostrando o original entre parênteses quando ≠ 100%) e tonalidade **transposta** pelos semitons atuais (ex.: `A minor`, +2 → `B minor`).
- Faixa de acordes acima das waveforms (blocos com rótulo) e acorde atual + próximo em destaque; ambos transpostos. `N` aparece como "—".
- Sem análise (`analysis_status=failed`): mostra "Análise indisponível" e o botão "Reprocessar".

### 9.5 Waveforms

Canvas por stem, desenhado a partir de `peaks.json` (sem decodificar áudio). Overlay com playhead, região A-B, marcadores e grade de compassos (downbeats). Zoom horizontal (1×, 2×, 4×, 8×) com rolagem acompanhando o playhead.

### 9.6 Estado persistido

`player_state` (salvo via `PATCH /api/songs/{id}` com debounce de 1 s e ao sair da página): `{"volumes": {stem: 0-100}, "mutes": {stem: bool}, "solos": {stem: bool}, "master": 0-100, "speed": 0.5-1.5, "semitones": -12..12, "loop": {"a": s, "b": s, "enabled": bool} | null, "metronome": {"enabled": bool, "volume": 0-100, "offset_ms": int}}`. Ao abrir a música, restaura tudo, posição em 0, pausado. Padrões: volume 100, sem mute/solo, master 100, speed 1.0, semitones 0, loop null, metrônomo desligado com `volume` = `metronome_volume` das configurações e `offset_ms` 0. Stems ausentes no estado (após reprocessar em outro modo) usam o padrão.

## 10. Exportação

Todas síncronas na API (a UI mostra "Gerando…" e baixa o arquivo); exigem `status=ready` (senão `SONG_NOT_READY`, 409) — inclusive durante um reprocessamento, com os stems atuais. São geradas em arquivo temporário em `DATA_DIR/tmp/api` e servidas com `FileResponse` (apagadas após o envio). Nome do arquivo: `<artista> - <título> [<sufixo>].<ext>` (sem artista: `<título> [<sufixo>].<ext>`), com caracteres `/\:*?"<>|` trocados por `_`.

| Exportação | Endpoint | Sufixo |
|---|---|---|
| Stem individual | `GET /api/songs/{id}/export/stem/{stem}?format=wav\|flac\|mp3` | nome do stem |
| ZIP de stems | `GET /api/songs/{id}/export/zip?format=...` | `stems` |
| Mix customizado | `POST /api/songs/{id}/export/mix` | `mix` |

Formatos (padrão `wav` quando omitido): `wav` (PCM 24 bits), `flac` (24 bits), `mp3` (320 kbps CBR, via ffmpeg/libmp3lame); todos 44,1 kHz estéreo.

Mix: corpo `{"gains": {stem: 0.0–1.0}, "speed": 0.5–1.5, "semitones": -12..12, "start_s": null|n, "end_s": null|n, "format": "..."}`. A UI preenche `gains` com os ganhos efetivos atuais (mute/solo já resolvidos, multiplicados pelo master) e oferece as opções "aplicar velocidade e tom" (padrão desligado → envia 1.0/0) e "somente o trecho A-B" (se houver loop). O servidor recorta, soma com os ganhos, aplica `python-stretch` se `speed≠1` ou `semitones≠0` e, se o pico passar de 1,0, normaliza para pico 0,98. `start_s` nulo = 0, `end_s` nulo = `duration_s`; exige `0 ≤ start_s < end_s ≤ duration_s` e `end_s − start_s ≥ 0,5`. Stem em `gains` fora do modo atual, ou `speed`/`semitones` fora da faixa → `VALIDATION_ERROR`; stems omitidos têm ganho 0. Todos os ganhos zero → `VALIDATION_ERROR`.

## 11. API

Prefixo `/api`; JSON; erros no formato e com os status do §8.3. Os formatos exatos das respostas (objetos `Song`, `Job`, `Marker`, `Settings`, `Health` e envelopes) estão em [`api-contract.md`](api-contract.md), que faz parte desta spec.

| Método e rota | Descrição |
|---|---|
| `GET /health` | `{ok, device: "mps"\|"cpu", ffmpeg: versão, yt_dlp: versão, data_dir, models_cached: bool}` (`true` se `htdemucs_ft`, `htdemucs_6s` e o checkpoint `final0` estão em `DATA_DIR/models`) |
| `GET /songs?q=&tag=&favorite=&status=&sort=created_at\|title\|artist\|bpm\|duration_s&order=asc\|desc` | Lista (sem paginação). `q` busca em título, artista, álbum, notas e tags, sem diferenciar maiúsculas nem acentos (filtragem em Python após normalizar com `unicodedata` NFKD sem diacríticos). Padrão `created_at desc`; nulos sempre no fim. |
| `POST /songs/upload`, `POST /songs/url` | §8.3. Resposta 201 com a música e o job. |
| `GET /songs/{id}` | Música + tags + job ativo/último + `stems` (lista na ordem do modo). |
| `PATCH /songs/{id}` | Campos editáveis: `title` (1–200), `artist`, `album` (0–200; vazio → null), `favorite`, `notes`, `tags` (lista completa, substitui), `player_state`. |
| `DELETE /songs/{id}` | Pede cancelamento do job ativo e aguarda até 10 s; em seguida apaga linhas e pasta de qualquer forma. 204. O worker trata o sumiço como cancelamento: um `UPDATE jobs` de progresso que afeta 0 linhas levanta a exceção de cancelamento; antes de escrever em `songs/<id>/` (download, troca) confirma que a música existe; nunca cria `songs/<id>/`; se a música sumiu, apaga a pasta de trabalho e encerra sem gravar nada. |
| `PUT /songs/{id}/cover` (multipart, jpg/png ≤ 10 MB; outro formato → `UNSUPPORTED_FORMAT`, maior → `FILE_TOO_LARGE`) / `GET /songs/{id}/cover` / `DELETE /songs/{id}/cover` | Capa redimensionada para no máximo 600×600 JPEG. |
| `POST /songs/{id}/reprocess` `{stem_mode}` | Cria job; 409 se já houver job ativo. |
| `GET /songs/{id}/stems/{stem}.flac` | Arquivo do stem (`Cache-Control: no-cache` + ETag). |
| `GET /songs/{id}/peaks`, `GET /songs/{id}/analysis` | JSONs do §7.4/§7.5; 404 se ausentes. |
| `GET/POST /songs/{id}/markers`, `PATCH/DELETE /songs/{id}/markers/{mid}` | CRUD de marcadores/loops. |
| export | §10 |
| `GET /jobs?limit=20` | Jobs `queued`/`running` + últimos `limit` finalizados, com título da música. |
| `POST /jobs/{id}/cancel`, `POST /jobs/{id}/retry` | §7.1 |
| `GET /tags` | `[{name, count}]` |
| `GET /settings`, `PUT /settings` (atualização parcial) | Chaves do §6.2 + `data_dir` (§6.1) + `data_dir_locked` (bool) + `restart_required` (bool). |

## 12. Requisitos não funcionais

- **Segurança:** servidor só em `127.0.0.1`. A API responde 403 `FORBIDDEN` se o `Host` não for `127.0.0.1:<porta>` ou `localhost:<porta>` (DNS rebinding), e a requisições mutáveis cujo `Origin`, quando presente, não seja a própria origem (com `MUSIC_TRACKS_DEV=1`, também `http://localhost:5173` e `http://127.0.0.1:5173`); CORS não é habilitado. Todo `{id}`/`{stem}` é validado (UUID; stem do modo atual) antes de montar caminhos — nenhum caminho vem do cliente. URLs: apenas `http`/`https`.
- **Desempenho (referência, M4):** separação de 4 min em qualidade máxima conforme §7.3; análise < 15 s; abrir uma música de 4 min com 4 stems e começar a tocar < 5 s; listagem de 500 músicas < 300 ms.
- **Logs:** `DATA_DIR/logs/api.log` e `worker.log` (rotação 5 × 5 MB), com início/fim de cada etapa, duração e erros com stack trace.
- **Robustez:** crash do worker não corrompe biblioteca (troca atômica §7.2; recuperação §7.1).

## 13. Testes e critérios de aceite

Backend (`pytest`). Fora de `@pytest.mark.slow`, o separador é um *fake* (gera stems com filtros simples) e o detector de batidas também (batidas a cada 0,5 s a partir de 0); `essentia` e o matcher rodam reais. A suíte rápida roda offline.

1. Upload válido cria música `pending` + job `queued`; formatos/tamanhos inválidos retornam o código correto e não criam nada.
2. Duplicidade por hash (upload) e por `extractor:id` (URL, com yt-dlp mockado) → 409 `DUPLICATE` com `existing_song_id`.
3. Pipeline completo com separador fake: música termina `ready`, com os stems do modo, `peaks.json` e `analysis.json`.
4. Falha na análise (exceção injetada no analisador) → música `ready`, `analysis_status=failed`.
5. Reprocessamento que falha mantém os stems antigos e `status=ready`.
6. Cancelamento de job `queued` e `running`; recuperação de job `running` após reinício do worker.
7. Pasta monitorada: arquivo em cópia (tamanho mudando) não é importado; arquivo estável é importado; inválido vai para `_ignorados/` com `.erro.txt`.
8. Matcher de acordes: áudio sintético Am–F–C–G, 2 s cada, batidas a cada 0,5 s → rótulos `Am, F, C, G` com fronteiras a ±0,5 s. (`slow`) BPM real: clicks a 120 BPM sobre os acordes → `bpm` entre 119 e 121.
9. Export mix: ganhos aplicados, normalização de pico, stems inválidos rejeitados, `speed=0.5` dobra a duração (±1%).
10. Busca sem acento/maiúsculas; tags criadas/removidas; ordenação com nulos no fim.
11. Validação de caminhos: `stem` fora do modo → 404.
12. Segurança: `Host` estranho → 403; `POST` com `Origin` de outra origem → 403 (inclusive `http://localhost:5173` sem `MUSIC_TRACKS_DEV`); `POST` sem `Origin` → aceito.
13. Recuperação: `.old` presentes com job `running` → antigos restaurados e novos apagados; com job `done` → `.old` apagados; job `running` com `attempts=2` → `failed`.
14. Estados: retry de job `done` e cancel de job `failed` → 409 `INVALID_STATE`; reprocess com job ativo → 409 `JOB_ALREADY_ACTIVE`; export de música `failed` → 409 `SONG_NOT_READY`; `DELETE` com job `running` → 204 e o worker não recria a pasta; duas criações simultâneas de job para a mesma música → uma aceita e uma 409.
15. Marcadores: `loop` com `end_s <= start_s` ou fora de `[0, duration_s]` → 422; o 201º → 422. `PUT /settings` com `data_dir` relativo, ou alterando `data_dir` com `MUSIC_TRACKS_HOME` definida → 422.
16. URL (yt-dlp mockado): playlist → `PLAYLIST_NOT_SUPPORTED`; `is_live`, exceção/timeout ou `ftp://…` → `INVALID_URL`; `duration=901` → `TOO_LONG`; em nenhum caso a música é criada.
17. Export stem/ZIP: cada `format` gera arquivo 44,1 kHz estéreo no formato pedido; artista `AC/DC`, título `Back: In?` → `AC_DC - Back_ In_ [vocals].mp3`; o ZIP contém `<stem>.<ext>` para cada stem do modo; `format` inválido → 422.
18. Separação (fake): erro de memória em `mps` → repete em `cpu`; falhando de novo → `OUT_OF_MEMORY`; menos de 2 GB livres (`shutil.disk_usage` mockado) → `DISK_FULL`; `OSError(ENOSPC)` injetado em `peaks` → `DISK_FULL`.
19. `prepare`: arquivo de 3 s → `TOO_SHORT`; 15 min 1 s → `TOO_LONG`; `.mp3` corrompido → `INVALID_AUDIO`; em todos, job e música `failed`.
20. Pasta monitorada: hash igual ao de música existente → `_ignorados/` com `.erro.txt` contendo `DUPLICATE`.
21. Reprocessar do modo 4 para o 6 (fake) → `stem_mode=6`, `GET /songs/{id}` lista os 6 stems na ordem do glossário, `stems/` só com os 6 FLACs.
22. Metadados: upload de MP3 com tags ID3 e capa embutida → título, artista, álbum e capa das tags; `PATCH title` + reprocess → título preservado; `DELETE cover` + reprocess → sem capa; job que falha depois do `prepare` + `DELETE cover` + retry → sem capa; reprocess nunca altera `artist`/`album`.
23. Download (yt-dlp mockado gerando áudio): `step_count=5`, `original.<ext>` criado, artista por `artist`→`creator`→`uploader`, thumbnail vira `cover.jpg` ≤ 600×600; exceção no download → `DOWNLOAD_FAILED`; retry com `original.*` existente → `step_count=4`.
24. Capa: PNG 2000×1000 → `GET /cover` devolve JPEG 600×300; `.gif` → 422 `UNSUPPORTED_FORMAT`; 11 MB → 413; sem capa → 404.

Frontend (`vitest`):

25. `timeline.ts`: posição com mudanças de velocidade, pausa, seek e loop; mapeamento batida → tempo de contexto.
26. `mix.ts`: ganhos efetivos com mute/solo/master.
27. Transposição de acordes e tonalidades (`Am` +2 → `Bm`; `B` +1 → `C`; `A minor` −3 → `F# minor`) e exibição (`A minor` em pt-BR → `Lá menor`).
28. Paridade de chaves `en`/`pt-BR`.
29. Loop A-B (função pura): `[` depois de B limpa B; B − A = 0,4 s → ignorado; seek fora do trecho com loop ligado → loop desligado.
30. Restauração de `player_state`: `{}` → padrões do §9.6 com `metronome.volume = metronome_volume`; estado do modo 4 aberto no modo 6 → `guitar`/`piano` com padrão, demais preservados.

Aceite manual (com uma música real): adicionar por upload, URL do YouTube (sem aviso de formato limitado no `worker.log`) e pasta; acompanhar a fila; tocar com 4 e 6 stems; solo do baixo a 70% com +2 semitons; loop A-B sem cortes audíveis; metrônomo alinhado às batidas a 50% e 150%; exportar mix sem voz em MP3.

## 14. Questões em aberto

Nenhuma bloqueante.
