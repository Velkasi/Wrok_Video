# Wrok-video

Outil **100% local** de transcription et résumé de vidéos de réunion, avec deux modes :

1. **Mode Fichier** — drag & drop ou bouton Parcourir : `.mp4 .mkv .mov .avi .webm .mp3 .wav .m4a .flac .ogg .opus .aac`. File d'attente multi-fichiers.
2. **Mode Live** — capture simultanée du **micro**, de l'**audio système** (loopback WASAPI) et de l'**écran** (multi-moniteurs sélectionnables). Sauvegarde un MP4 puis transcrit/résume.

Tout local : **Whisper medium** (faster-whisper) pour la transcription, **Llama 3.1 8B Instruct Q4** (Ollama) pour le résumé. Aucune clé API. Aucune connexion réseau requise après l'install.

Sortie : **un dossier de base** configurable. Chaque enregistrement Live a son **propre sous-dossier** contenant vidéo + résumé. Le mode Fichier reste à plat (pas de vidéo à grouper).

```
~/Documents/Resume_Wrok/
├── 2026-05-09-1430-reunion-projet-x/             ← Live : sous-dossier dédié
│   ├── 2026-05-09-1430-reunion-projet-x.mp4
│   └── 2026-05-09-1430-reunion-projet-x.md       (référence ./xxx.mp4 en relatif)
├── 2026-05-09-1500-meeting-equipe/               ← un autre Live
│   ├── 2026-05-09-1500-meeting-equipe.mp4
│   └── 2026-05-09-1500-meeting-equipe.md
└── 2026-05-09-1700-debrief-client.md             ← mode Fichier : .md à plat
```

Le `.md` référence la vidéo en chemin relatif (`./fichier.mp4`) → compatible avec tout éditeur Markdown : VS Code, Typora, Obsidian (si tu pointes ce dossier dans un vault), etc.

Dossier de base configurable dans **Fichier → Paramètres**.

> Projet Obsidian associé : `[[APP_Wrok - resume les reunions/README]]`

---

## Fonctionnalités

- **Mode Fichier** avec **drag & drop multi-fichiers** (queue automatique).
- **Mode Live** avec :
  - sources sélectionnables (micro / audio système / écran indépendamment)
  - **sélecteur d'écran** pour les configurations multi-moniteurs (rafraîchissable à la volée via le bouton ↻)
  - timer de durée + log temps réel
- **Sortie Obsidian** : frontmatter YAML, sections `Résumé exécutif / Points clés / Décisions / Actions / Transcription complète`, vidéo liée en wikilink (mode Live).
- **CPU par défaut**, GPU NVIDIA opt-in (probe auto).
- **Logs rotatifs** dans `%LOCALAPPDATA%\reunion-resume\logs\wrok-video.log`.
- **Distribution Windows clé en main** : raccourci bureau auto-installé, aucun pré-requis sauf VC++ Redistributable.

---

## Stack

| Composant | Lib |
|---|---|
| GUI | PySide6 (Qt6) |
| Transcription | faster-whisper (CTranslate2) |
| LLM résumé | Ollama (binaire embarqué) + Llama 3.1 8B Instruct Q4 |
| Capture audio | sounddevice (mic) + soundcard WASAPI (loopback) |
| Capture écran | mss + PyAV (H.264) |
| Mux/extract | ffmpeg (binaire embarqué) |
| Packaging | PyInstaller onedir |

---

## Setup (dev)

```powershell
.\scripts\bootstrap.ps1
.\.venv\Scripts\python.exe scripts\download_models.py
```

Le script `bootstrap.ps1` :
1. crée `.venv` (Python 3.12 via `uv`)
2. installe les dépendances (incl. dev + build)

`download_models.py` télécharge `ffmpeg.exe`, `ollama.exe`, le modèle Whisper medium (~1.5 GB) et Llama 3.1 8B Q4 (~4.7 GB).

Total disque après bootstrap : **~6 GB**.

---

## Lancement (dev)

```powershell
.\.venv\Scripts\python.exe -m reunion_resume                   # GUI
.\.venv\Scripts\python.exe -m reunion_resume --cli .\video.mp4 # CLI mode A
```

---

## Accélération GPU NVIDIA (auto-détectée)

Les libs CUDA (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-runtime-cu12`) sont **incluses dans les deps par défaut** et embarquées dans le build PyInstaller.

Au démarrage, le code :
1. Probe la présence de `cublas64_12.dll` + `cudnn_ops64_9.dll` + `cudart64_12.dll`
2. **Si trouvées + GPU NVIDIA dispo** → Whisper en `device=cuda compute_type=float16` (~5-10× plus rapide)
3. **Sinon** → fallback automatique CPU + `int8` (l'app reste 100% fonctionnelle)

Le `.exe` reste **transportable sur n'importe quel PC Windows**, qu'il ait un GPU NVIDIA ou pas. Sur les machines sans GPU, les libs CUDA sont juste du poids mort (~2 GB) mais ne plantent pas.

Logs au lancement (`%LOCALAPPDATA%\reunion-resume\logs\wrok-video.log`) :

```
[INFO] DLLs nvidia ajoutées (4 dossiers) : ['cublas', 'cuda_nvrtc', 'cuda_runtime', 'cudnn']
[INFO] CUDA disponible : cublas + cudnn + cudart chargeables
[INFO] Whisper chargé : model=… device=cuda compute_type=float16
```

ou en l'absence de GPU :

```
[WARNING] CUDA indisponible (manque : ...) → Whisper en CPU
[INFO] Whisper chargé : model=… device=cpu compute_type=int8
```

---

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
.\.venv\Scripts\python.exe -m ruff check src/ tests/
```

---

## Build & distribution clé en main

```powershell
.\scripts\make.ps1                      # build + dossier portable (défaut)
.\scripts\make.ps1 -Format zip          # build + .zip via tar/7-Zip
.\scripts\make.ps1 -SkipDownload        # modèles déjà DL
.\scripts\make.ps1 -OnlyPackage         # build déjà fait, juste re-empaqueter
.\scripts\make.ps1 -IncludeVCRedist     # embarque vc_redist.x64.exe
```

Format `dir` (défaut) car :
- `Compress-Archive` PowerShell plante au-delà de 2 GB
- Un dossier de 11 GB se copie aussi vite qu'un zip qui ne compresserait que ~5%

### Déploiement sur un autre PC Windows

1. Copier le dossier `Wrok-video-vX.Y.Z-win64\` (ou le `.zip` selon le format)
2. Sur la machine cible : double-clic **`Installer (raccourci bureau).bat`**
   → crée le raccourci **Wrok-video** sur le Bureau et dans le menu Démarrer
3. Lancer l'app depuis le raccourci

Pas d'install Python, pas d'install Ollama, pas de clé API. Tout embarqué.

Pré-requis machine cible : Windows 10/11 64-bit + VC++ Redistributable 2015-2022 (généralement déjà là).

---

## Configuration

`config\default.yaml` est embarqué. Les overrides utilisateur vont dans :

```
%APPDATA%\reunion-resume\config.yaml
```

Override par deep merge. Exemples utiles :

```yaml
whisper:
  model: "small"          # 4× plus rapide que medium sur CPU
  beam_size: 1            # +30% rapidité
  device: "cuda"          # forcer GPU (sinon auto)
  compute_type: "float16" # int8/int8_float16/float16/float32

recording:
  screen:
    monitor: 2            # capturer écran secondaire
    fps: 5                # alléger le MP4
```

Le menu **Fichier → Paramètres** de la GUI persiste également dans ce fichier.

---

## Architecture

```
src/reunion_resume/
├── __main__.py            # entrypoint + CoInitializeEx STA (avant tout import)
├── app.py                 # bootstrap PySide6 + logging fichier
├── config.py              # pydantic + merge yaml
├── paths.py               # _MEIPASS-aware
├── core/
│   ├── transcriber.py     # faster-whisper + probe CUDA + auto-discovery DLLs
│   ├── summarizer.py      # client Ollama + prompts FR
│   ├── ollama_runtime.py  # spawn + healthcheck du serveur
│   ├── recorder.py        # 3 threads (mic, sys, screen) + list_monitors()
│   ├── mixer.py           # ffmpeg subprocess (extract/mix amix/mux)
│   ├── obsidian.py        # rendu Markdown + frontmatter
│   └── pipeline.py        # orchestration File/Live (lazy load)
└── gui/
    ├── main_window.py     # QTabWidget + DnD global + UIPI fix
    ├── file_tab.py        # drag-drop + queue + Parcourir
    ├── live_tab.py        # 3 sources + sélecteur écran multi-moniteurs
    ├── workers.py         # FileWorker + LiveWorker (signaux Qt)
    └── settings_dlg.py    # config persistée APPDATA
```

---

## Notes techniques (gotchas Windows)

- **Python 3.12** imposé : 3.13/3.14 incompatibles avec wheels `ctranslate2` / `av`.
- **COM apartment** : `CoInitializeEx(NULL, COINIT_APARTMENTTHREADED)` appelé tout en haut de `__main__.py` avant tout autre import. Sans ça, certaines deps (PyAV, soundcard, ctranslate2) initialisent COM en MTA et Qt OleInitialize échoue → drag-drop et file dialogs cassés silencieusement.
- **UIPI drag-drop** : `ChangeWindowMessageFilterEx` appliqué au HWND après `show()` pour autoriser les messages drag depuis l'Explorer (sinon filtré entre niveaux d'intégrité différents).
- **Cross-thread Qt** : signaux Qt natifs au lieu de `QMetaObject.invokeMethod` par nom. `@Slot()` sur les méthodes ciblées par signal.
- **Imports absolus dans `__main__.py`** (PyInstaller exécute ce module comme `__main__`, pas comme `reunion_resume.__main__`).
- **WASAPI loopback** : `soundcard` capture la sortie haut-parleurs sans câble virtuel.
- **Ollama** : sous-process enfant de la GUI, tué à la fermeture (`atexit` + Qt `closeEvent`).
- **Scripts `.ps1` en pur ASCII** : PowerShell 5.1 lit en CP1252 sans BOM, casse les UTF-8.

---

## Liens projet

- Plan brainstorm : `C:\Users\kbout\.claude\plans\melodic-yawning-sloth.md`
- Vault Obsidian : `C:\01_Claude_Vault\Claude_Code\Projects\APP_Wrok - resume les reunions\`
- Logs runtime : `%LOCALAPPDATA%\reunion-resume\logs\wrok-video.log`
- Config user : `%APPDATA%\reunion-resume\config.yaml`
