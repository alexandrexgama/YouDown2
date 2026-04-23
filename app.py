import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

# Auto-ativacao do ambiente virtual
venv_path = Path(__file__).parent / "venv"
if os.name != "nt":
    venv_python = venv_path / "bin" / "python3"
else:
    venv_python = venv_path / "Scripts" / "python.exe"

if venv_python.exists() and sys.executable != str(venv_python.absolute()):
    print(f"Re-executando com o ambiente virtual: {venv_python}")
    os.execl(str(venv_python.absolute()), str(venv_python.absolute()), *sys.argv)

import yt_dlp
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file
from pyngrok import ngrok
from werkzeug.utils import secure_filename
from yt_dlp.cookies import SUPPORTED_BROWSERS, SUPPORTED_KEYRINGS

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
UPLOAD_DIR = BASE_DIR / "uploads"
DOWNLOAD_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "1024"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

FFMPEG_BIN = shutil.which("ffmpeg")
FFPROBE_BIN = shutil.which("ffprobe")

progress_store = {}
ngrok_lock = threading.Lock()
public_url_store = {
    "url": None,
    "updated_at": None,
    "enabled": os.getenv("USE_NGROK", "False").lower() == "true",
    "status": "disabled" if os.getenv("USE_NGROK", "False").lower() != "true" else "idle",
    "error": None,
}

SUPPORTED_PLATFORMS = {
    "youtube": [r"(youtube\.com|youtu\.be)"],
    "instagram": [r"instagram\.com"],
    "tiktok": [r"tiktok\.com"],
    "kwai": [r"kwai\.com", r"kw\.ai"],
    "vimeo": [r"vimeo\.com"],
    "twitter": [r"twitter\.com", r"x\.com"],
    "facebook": [r"facebook\.com", r"fb\.watch"],
}

POPULAR_COOKIE_BROWSERS = ("chrome", "edge", "firefox", "opera", "brave")
COOKIE_BROWSER_PATHS = {
    "brave": Path.home() / ".config" / "BraveSoftware" / "Brave-Browser",
    "chrome": Path.home() / ".config" / "google-chrome",
    "chromium": Path.home() / ".config" / "chromium",
    "edge": Path.home() / ".config" / "microsoft-edge",
    "firefox": Path.home() / ".mozilla" / "firefox",
    "opera": Path.home() / ".config" / "opera",
}
DEFAULT_COOKIEFILE = BASE_DIR / "cookies.txt"

VIDEO_FORMATS = {
    "mp4_best": {"ext": "mp4", "quality": "Melhor Qualidade", "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"},
    "mp4_1080": {"ext": "mp4", "quality": "1080p Full HD", "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]"},
    "mp4_720": {"ext": "mp4", "quality": "720p HD", "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"},
    "mp4_480": {"ext": "mp4", "quality": "480p SD", "format": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]"},
    "mp4_360": {"ext": "mp4", "quality": "360p", "format": "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]"},
    "webm_best": {"ext": "webm", "quality": "WebM Melhor", "format": "bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/best"},
    "webm_1080": {"ext": "webm", "quality": "WebM 1080p", "format": "bestvideo[height<=1080][ext=webm]+bestaudio[ext=webm]/best[height<=1080]"},
}

AUDIO_FORMATS = {
    "mp3_320": {"ext": "mp3", "quality": "MP3 320kbps", "format": "bestaudio", "bitrate": "320"},
    "mp3_192": {"ext": "mp3", "quality": "MP3 192kbps", "format": "bestaudio", "bitrate": "192"},
    "mp3_128": {"ext": "mp3", "quality": "MP3 128kbps", "format": "bestaudio", "bitrate": "128"},
    "wav": {"ext": "wav", "quality": "WAV Lossless", "format": "bestaudio"},
    "m4a": {"ext": "m4a", "quality": "M4A Best", "format": "bestaudio"},
    "flac": {"ext": "flac", "quality": "FLAC Lossless", "format": "bestaudio"},
    "ogg": {"ext": "ogg", "quality": "OGG Best", "format": "bestaudio"},
    "aac": {"ext": "aac", "quality": "AAC Best", "format": "bestaudio"},
}

CONVERSION_VIDEO_FORMATS = {
    "mp4_h264": {
        "ext": "mp4",
        "label": "MP4 H.264",
        "quality": "Compatibilidade ampla",
        "kind": "video",
        "command": ["-c:v", "libx264", "-preset", "medium", "-crf", "22", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"],
    },
    "mp4_hevc": {
        "ext": "mp4",
        "label": "MP4 H.265",
        "quality": "Arquivo menor",
        "kind": "video",
        "command": ["-c:v", "libx265", "-preset", "medium", "-crf", "28", "-c:a", "aac", "-b:a", "192k", "-tag:v", "hvc1"],
    },
    "mkv_h264": {
        "ext": "mkv",
        "label": "MKV H.264",
        "quality": "Container flexivel",
        "kind": "video",
        "command": ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-c:a", "aac", "-b:a", "192k"],
    },
    "mov_h264": {
        "ext": "mov",
        "label": "MOV H.264",
        "quality": "Edicao e Apple",
        "kind": "video",
        "command": ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "aac", "-b:a", "192k"],
    },
    "webm_vp9": {
        "ext": "webm",
        "label": "WebM VP9",
        "quality": "Web e streaming",
        "kind": "video",
        "command": ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-c:a", "libopus", "-b:a", "160k"],
    },
    "avi_xvid": {
        "ext": "avi",
        "label": "AVI Xvid",
        "quality": "Legacy",
        "kind": "video",
        "command": ["-c:v", "libxvid", "-q:v", "4", "-c:a", "libmp3lame", "-b:a", "192k"],
    },
    "gif_loop": {
        "ext": "gif",
        "label": "GIF Loop",
        "quality": "Trechos visuais",
        "kind": "video",
        "command": ["-vf", "fps=12,scale='min(960,iw)':-1:flags=lanczos", "-loop", "0"],
    },
}

CONVERSION_AUDIO_FORMATS = {
    "mp3_320": {
        "ext": "mp3",
        "label": "MP3 320kbps",
        "quality": "Alta compatibilidade",
        "kind": "audio",
        "command": ["-vn", "-c:a", "libmp3lame", "-b:a", "320k"],
    },
    "mp3_192": {
        "ext": "mp3",
        "label": "MP3 192kbps",
        "quality": "Equilibrado",
        "kind": "audio",
        "command": ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"],
    },
    "aac_256": {
        "ext": "aac",
        "label": "AAC 256kbps",
        "quality": "Streaming",
        "kind": "audio",
        "command": ["-vn", "-c:a", "aac", "-b:a", "256k"],
    },
    "m4a_aac": {
        "ext": "m4a",
        "label": "M4A AAC",
        "quality": "Apple e mobile",
        "kind": "audio",
        "command": ["-vn", "-c:a", "aac", "-b:a", "256k"],
    },
    "wav_pcm": {
        "ext": "wav",
        "label": "WAV PCM",
        "quality": "Sem perda",
        "kind": "audio",
        "command": ["-vn", "-c:a", "pcm_s16le"],
    },
    "flac_lossless": {
        "ext": "flac",
        "label": "FLAC Lossless",
        "quality": "Arquivo sem perda",
        "kind": "audio",
        "command": ["-vn", "-c:a", "flac"],
    },
    "ogg_vorbis": {
        "ext": "ogg",
        "label": "OGG Vorbis",
        "quality": "Open source",
        "kind": "audio",
        "command": ["-vn", "-c:a", "libvorbis", "-q:a", "7"],
    },
    "opus_160": {
        "ext": "opus",
        "label": "Opus 160kbps",
        "quality": "Fala e streaming",
        "kind": "audio",
        "command": ["-vn", "-c:a", "libopus", "-b:a", "160k"],
    },
}


def detect_platform(url: str) -> str:
    for platform, patterns in SUPPORTED_PLATFORMS.items():
        for pattern in patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return platform
    return "generic"


def get_format_options(format_type: str):
    if format_type in VIDEO_FORMATS:
        fmt = VIDEO_FORMATS[format_type]
        if not ffmpeg_available():
            progressive_map = {
                "mp4_best": "best[ext=mp4]/best",
                "mp4_1080": "best[height<=1080][ext=mp4]/best[height<=1080]/best[ext=mp4]/best",
                "mp4_720": "best[height<=720][ext=mp4]/best[height<=720]/best[ext=mp4]/best",
                "mp4_480": "best[height<=480][ext=mp4]/best[height<=480]/best[ext=mp4]/best",
                "mp4_360": "best[height<=360][ext=mp4]/best[height<=360]/best[ext=mp4]/best",
                "webm_best": "best[ext=webm]/best",
                "webm_1080": "best[height<=1080][ext=webm]/best[height<=1080]/best[ext=webm]/best",
            }
            return {
                "format": progressive_map.get(format_type, f"best[ext={fmt['ext']}]/best"),
            }
        return {
            "format": fmt["format"],
            "merge_output_format": fmt["ext"],
        }
    if format_type in AUDIO_FORMATS:
        fmt = AUDIO_FORMATS[format_type]
        return {
            "format": fmt["format"],
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": fmt["ext"],
                "preferredquality": fmt.get("bitrate", "0"),
            }],
        }
    return {}


def get_fallback_format_options(format_type: str):
    if format_type in VIDEO_FORMATS:
        fmt = VIDEO_FORMATS[format_type]
        if not ffmpeg_available():
            return {
                "format": f"best[ext={fmt['ext']}]/best",
            }
        return {
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": fmt["ext"],
        }
    if format_type in AUDIO_FORMATS:
        fmt = AUDIO_FORMATS[format_type]
        return {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": fmt["ext"],
                "preferredquality": fmt.get("bitrate", "0"),
            }],
        }
    return {}


def parse_cookies_from_browser(raw_value: str):
    value = (raw_value or "").strip()
    if not value:
        return None

    match = re.fullmatch(
        r"""(?x)
        (?P<name>[^+:]+)
        (?:\s*\+\s*(?P<keyring>[^:]+))?
        (?:\s*:\s*(?!:)(?P<profile>.+?))?
        (?:\s*::\s*(?P<container>.+))?
        """,
        value,
    )
    if match is None:
        raise ValueError(
            "YTDLP_COOKIES_FROM_BROWSER invalido. Use o formato "
            "BROWSER[+KEYRING][:PROFILE][::CONTAINER]."
        )

    browser_name, keyring, profile, container = match.group("name", "keyring", "profile", "container")
    browser_name = browser_name.lower()
    if browser_name not in SUPPORTED_BROWSERS:
        supported = ", ".join(sorted(SUPPORTED_BROWSERS))
        raise ValueError(
            f'Navegador invalido em YTDLP_COOKIES_FROM_BROWSER: "{browser_name}". '
            f"Valores suportados: {supported}."
        )

    if keyring is not None:
        keyring = keyring.upper()
        if keyring not in SUPPORTED_KEYRINGS:
            supported = ", ".join(sorted(SUPPORTED_KEYRINGS))
            raise ValueError(
                f'Keyring invalido em YTDLP_COOKIES_FROM_BROWSER: "{keyring}". '
                f"Valores suportados: {supported}."
            )

    return (browser_name, profile, keyring, container)


def get_ydlp_auth_options():
    opts = {}

    cookiefile = os.getenv("YTDLP_COOKIEFILE", "").strip()
    if cookiefile:
        cookie_path = Path(cookiefile).expanduser()
        if not cookie_path.is_file():
            raise ValueError(f"YTDLP_COOKIEFILE aponta para um arquivo inexistente: {cookie_path}")
        opts["cookiefile"] = str(cookie_path)
        return opts

    if DEFAULT_COOKIEFILE.is_file():
        opts["cookiefile"] = str(DEFAULT_COOKIEFILE)
        return opts

    cookies_from_browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = parse_cookies_from_browser(cookies_from_browser)

    return opts


def build_ydl_opts(**extra_opts):
    return {
        "quiet": True,
        "no_warnings": True,
        **get_ydlp_auth_options(),
        **extra_opts,
    }


def list_available_cookie_browsers():
    return [name for name, path in COOKIE_BROWSER_PATHS.items() if path.exists()]


def format_extraction_error(exc: Exception, platform: str) -> str:
    message = str(exc).strip() or "Falha ao processar a URL."
    message = re.sub(r"\x1b\[[0-9;]*m", "", message)
    message = re.sub(r"\[[0-9;]*m", "", message)
    message = re.sub(r"^ERROR:\s*", "", message, flags=re.IGNORECASE)
    lowered = message.lower()

    missing_browser = re.search(r"could not find ([a-z]+) cookies database", lowered)
    if missing_browser:
        configured_browser = missing_browser.group(1)
        available_browsers = list_available_cookie_browsers()
        available_text = ", ".join(available_browsers) if available_browsers else "nenhum navegador conhecido"
        return (
            f'O navegador configurado em YTDLP_COOKIES_FROM_BROWSER ({configured_browser}) nao foi encontrado '
            f"neste usuario. Perfis detectados: {available_text}. "
            "Ajuste o .env para um navegador existente, por exemplo chromium no Linux."
        )

    if platform == "instagram" and "empty media response" in lowered:
        browser_examples = ", ".join(POPULAR_COOKIE_BROWSERS)
        return (
            "O Instagram nao liberou a midia para acesso anonimo nesse link. "
            f"Se o post so abre com login, salve um arquivo Netscape em {DEFAULT_COOKIEFILE} "
            "ou configure YTDLP_COOKIEFILE=/caminho/cookies.txt. "
            f"Como alternativa, ainda e possivel usar YTDLP_COOKIES_FROM_BROWSER com: {browser_examples}."
        )

    if "sign in to confirm your age" in lowered or "login required" in lowered:
        return (
            "A plataforma exigiu autenticacao para liberar esse conteudo. "
            f"Use um arquivo de cookies em {DEFAULT_COOKIEFILE} ou configure YTDLP_COOKIEFILE."
        )

    if isinstance(exc, ValueError) and ("YTDLP_COOKIEFILE" in message or "YTDLP_COOKIES_FROM_BROWSER" in message):
        return message

    return f"Erro ao processar a URL: {message}"


def ffmpeg_available():
    return bool(FFMPEG_BIN)


def get_conversion_formats():
    return {
        "video": CONVERSION_VIDEO_FORMATS,
        "audio": CONVERSION_AUDIO_FORMATS,
    }


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def find_output_file(token: str):
    files = sorted(DOWNLOAD_DIR.glob(f"{token}_*"), key=lambda file: file.stat().st_mtime, reverse=True)
    return files[0] if files else None


def sanitize_output_name(name: str) -> str:
    cleaned = secure_filename(Path(name).stem) or "arquivo"
    return cleaned[:80]


def resolve_entry_url(entry: dict) -> str:
    if not entry:
        return ""

    webpage_url = (entry.get("webpage_url") or "").strip()
    if webpage_url:
        return webpage_url

    original_url = (entry.get("original_url") or "").strip()
    if original_url:
        return original_url

    entry_url = (entry.get("url") or "").strip()
    if re.match(r"^https?://", entry_url, re.IGNORECASE):
        return entry_url

    video_id = (entry.get("id") or "").strip()
    extractor = (entry.get("extractor_key") or entry.get("ie_key") or "").lower()
    if video_id and "youtube" in extractor:
        return f"https://www.youtube.com/watch?v={video_id}"

    return entry_url


def build_canonical_media_url(platform: str, video_id: str, fallback_url: str = "") -> str:
    platform_name = (platform or "").strip().lower()
    media_id = (video_id or "").strip()
    fallback = (fallback_url or "").strip()

    if platform_name == "youtube" and media_id:
        return f"https://www.youtube.com/watch?v={media_id}"
    if platform_name == "vimeo" and media_id:
        return f"https://vimeo.com/{media_id}"

    return fallback


def normalize_batch_video_url(video: dict) -> str:
    if not video:
        return ""

    url = (video.get("url") or "").strip()
    platform = (video.get("platform") or "").strip()
    video_id = (video.get("id") or "").strip()

    if "googlevideo.com/videoplayback" in url or "videoplayback?" in url:
        canonical_url = build_canonical_media_url(platform, video_id, "")
        if canonical_url:
            return canonical_url

    if url and re.match(r"^https?://", url, re.IGNORECASE):
        return url

    canonical_url = build_canonical_media_url(platform, video_id, "")
    if canonical_url:
        return canonical_url

    return url


def update_progress(token: str, **fields):
    current = progress_store.get(token, {})
    current.update(fields)
    current["updated_at"] = time.time()
    progress_store[token] = current


def make_progress_hook(token: str):
    def hook(data):
        if data["status"] == "downloading":
            downloaded = data.get("downloaded_bytes", 0)
            total = data.get("total_bytes") or data.get("total_bytes_estimate", 0)
            percent = int(downloaded / total * 100) if total else 0
            update_progress(
                token,
                status="downloading",
                percent=percent,
                speed=data.get("_speed_str", "").strip(),
                eta=data.get("_eta_str", "").strip(),
                message="Baixando arquivo remoto...",
            )
        elif data["status"] == "finished":
            update_progress(
                token,
                status="processing",
                percent=99,
                speed="",
                eta="",
                message="Finalizando arquivo...",
            )

    return hook


def cleanup_old_files():
    while True:
        try:
            now = time.time()
            for folder in (DOWNLOAD_DIR, UPLOAD_DIR):
                for file in folder.glob("*"):
                    if file.is_file() and now - file.stat().st_mtime > 3600:
                        logger.info(f"Removendo arquivo antigo: {file.name}")
                        file.unlink()

            tokens_to_remove = [token for token, data in progress_store.items() if now - data.get("updated_at", 0) > 3600]
            for token in tokens_to_remove:
                del progress_store[token]
        except Exception as exc:
            logger.error(f"Erro no cleanup: {exc}")
        time.sleep(600)


def download_video(url: str, format_type: str, token: str):
    update_progress(token, status="starting", percent=0, message="Preparando download...")
    outtmpl = str(DOWNLOAD_DIR / f"{token}_%(title).80s.%(ext)s")
    platform = detect_platform(url)

    try:
        base_opts = {
            **build_ydl_opts(progress_hooks=[make_progress_hook(token)]),
            "outtmpl": outtmpl,
        }
        title = "video"

        try:
            with yt_dlp.YoutubeDL({**base_opts, **get_format_options(format_type)}) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "video")
        except Exception as exc:
            error_text = str(exc)
            if "Requested format is not available" not in error_text:
                raise

            logger.warning("Formato %s indisponivel para %s. Tentando fallback compatível.", format_type, url)
            update_progress(
                token,
                status="processing",
                percent=2,
                message="Formato exato indisponivel. Tentando variante compativel...",
            )
            with yt_dlp.YoutubeDL({**base_opts, **get_fallback_format_options(format_type)}) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "video")

        output_file = find_output_file(token)
        if output_file is None:
            raise FileNotFoundError("Arquivo nao encontrado apos download.")

        ext = VIDEO_FORMATS.get(format_type, AUDIO_FORMATS.get(format_type, {})).get("ext", output_file.suffix.lstrip("."))
        filename = output_file.name.replace(f"{token}_", "", 1)
        final_filename = f"{sanitize_output_name(output_file.name)}.{ext}"

        if not filename.lower().endswith(f".{ext}"):
            renamed = DOWNLOAD_DIR / f"{token}_{final_filename}"
            output_file.rename(renamed)
            output_file = renamed
            filename = final_filename
        else:
            filename = output_file.name.replace(f"{token}_", "", 1)

        update_progress(
            token,
            status="done",
            percent=100,
            filepath=str(output_file),
            filename=filename,
            title=title,
            format_type=format_type,
            message="Download concluido.",
        )
        logger.info(f"Download concluido: {title} ({token}) - Formato: {format_type}")
    except Exception as exc:
        logger.error(f"Erro no download ({token}): {exc}")
        update_progress(token, status="error", percent=0, message=format_extraction_error(exc, platform))


def build_ffmpeg_command(input_path: Path, output_path: Path, preset: dict):
    return [
        FFMPEG_BIN,
        "-y",
        "-i",
        str(input_path),
        *preset["command"],
        str(output_path),
    ]


def convert_media_file(input_path: Path, original_name: str, format_key: str, token: str):
    formats = get_conversion_formats()
    preset = formats["video"].get(format_key) or formats["audio"].get(format_key)
    if preset is None:
        update_progress(token, status="error", percent=0, message="Formato de conversao invalido.")
        return

    if not ffmpeg_available():
        update_progress(
            token,
            status="error",
            percent=0,
            message="FFmpeg nao esta instalado no sistema. Instale o ffmpeg para usar o conversor.",
        )
        return

    output_name = f"{sanitize_output_name(original_name)}.{preset['ext']}"
    output_path = DOWNLOAD_DIR / f"{token}_{output_name}"
    update_progress(token, status="processing", percent=15, message="Preparando conversao...", filename=output_name)

    try:
        command = build_ffmpeg_command(input_path, output_path, preset)
        logger.info("Executando conversao FFmpeg: %s", " ".join(command))
        update_progress(token, status="processing", percent=40, message="Convertendo arquivo...")
        completed = subprocess.run(command, capture_output=True, text=True, check=False)

        if completed.returncode != 0:
            error_text = (completed.stderr or completed.stdout or "Falha ao converter o arquivo.").strip()
            raise RuntimeError(error_text.splitlines()[-1])

        if not output_path.exists():
            raise FileNotFoundError("Arquivo convertido nao foi gerado.")

        update_progress(
            token,
            status="done",
            percent=100,
            filepath=str(output_path),
            filename=output_name,
            title=Path(original_name).stem,
            format_type=format_key,
            size=format_size(output_path.stat().st_size),
            message="Conversao concluida.",
        )
    except Exception as exc:
        logger.error(f"Erro na conversao ({token}): {exc}")
        update_progress(token, status="error", percent=0, message=f"Erro na conversao: {exc}")
    finally:
        try:
            input_path.unlink(missing_ok=True)
        except Exception:
            logger.warning("Nao foi possivel remover o upload temporario: %s", input_path)


def set_ngrok_state(*, status: str, url=None, error=None):
    public_url_store["status"] = status
    public_url_store["url"] = url
    public_url_store["error"] = error
    public_url_store["updated_at"] = time.time()


def stop_ngrok():
    with ngrok_lock:
        try:
            ngrok.kill()
            set_ngrok_state(status="stopped", url=None, error=None)
            logger.info("Sessao local do ngrok encerrada.")
        except Exception as exc:
            logger.warning(f"Falha ao encerrar ngrok: {exc}")
            set_ngrok_state(status="error", url=None, error=str(exc))


def start_ngrok(force_restart=False):
    auth_token = os.getenv("NGROK_AUTHTOKEN")
    if not auth_token or auth_token == "seu_token_aqui":
        set_ngrok_state(status="error", url=None, error="NGROK_AUTHTOKEN nao configurado.")
        logger.warning("NGROK_AUTHTOKEN nao configurado ou invalido no .env.")
        return

    with ngrok_lock:
        try:
            set_ngrok_state(status="starting", url=None, error=None)
            if force_restart:
                ngrok.kill()

            ngrok.set_auth_token(auth_token)
            tunnel = ngrok.connect(addr=FLASK_PORT, proto="http")
            public_url = tunnel.public_url
            set_ngrok_state(status="online", url=public_url, error=None)
            logger.info(f"ngrok tunnel disponivel em: {public_url}")
            print(f"\n\033[95mLink publico YouDow:\033[0m \033[94m{public_url}\033[0m\n")
        except Exception as exc:
            error_text = str(exc)
            set_ngrok_state(status="error", url=None, error=error_text)
            logger.error(f"Falha ao iniciar ngrok: {error_text}")


@app.route("/")
def index():
    initial_tab = request.args.get("tab", "download").strip().lower()
    if initial_tab not in {"download", "playlist", "convert"}:
        initial_tab = "download"
    return render_template("index.html", initial_tab=initial_tab, flask_port=FLASK_PORT)


@app.route("/browse")
def browse():
    return render_template("index.html", initial_tab="playlist", flask_port=FLASK_PORT)


@app.route("/api/public-url")
def get_public_url():
    return jsonify({
        "public_url": public_url_store["url"],
        "updated_at": public_url_store["updated_at"],
        "enabled": public_url_store["enabled"],
        "status": public_url_store["status"],
        "error": public_url_store["error"],
    })


@app.route("/api/ngrok/start", methods=["POST"])
def api_start_ngrok():
    public_url_store["enabled"] = True
    threading.Thread(target=start_ngrok, kwargs={"force_restart": True}, daemon=True).start()
    return jsonify({"message": "Inicializacao do ngrok em andamento."})


@app.route("/api/ngrok/stop", methods=["POST"])
def api_stop_ngrok():
    public_url_store["enabled"] = False
    threading.Thread(target=stop_ngrok, daemon=True).start()
    return jsonify({"message": "Encerramento do ngrok solicitado."})


@app.route("/api/formats")
def get_formats():
    return jsonify({
        "video": {key: {"quality": value["quality"], "ext": value["ext"]} for key, value in VIDEO_FORMATS.items()},
        "audio": {key: {"quality": value["quality"], "ext": value["ext"]} for key, value in AUDIO_FORMATS.items()},
    })


@app.route("/api/conversion-formats")
def get_conversion_formats_api():
    return jsonify({
        "video": {
            key: {"label": value["label"], "quality": value["quality"], "ext": value["ext"], "kind": value["kind"]}
            for key, value in CONVERSION_VIDEO_FORMATS.items()
        },
        "audio": {
            key: {"label": value["label"], "quality": value["quality"], "ext": value["ext"], "kind": value["kind"]}
            for key, value in CONVERSION_AUDIO_FORMATS.items()
        },
        "ffmpeg_available": ffmpeg_available(),
        "ffprobe_available": bool(FFPROBE_BIN),
        "max_upload_mb": MAX_UPLOAD_MB,
    })


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json()
    url = (data or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "URL nao informada"}), 400

    platform = detect_platform(url)

    try:
        with yt_dlp.YoutubeDL(build_ydl_opts(skip_download=True)) as ydl:
            info = ydl.extract_info(url, download=False)

        if info.get("_type") == "playlist":
            videos = []
            for entry in info.get("entries", []):
                if entry:
                    entry_url = resolve_entry_url(entry)
                    videos.append({
                        "id": entry.get("id"),
                        "title": entry.get("title", "Unknown"),
                        "url": entry_url,
                        "thumbnail": entry.get("thumbnail"),
                        "duration": entry.get("duration"),
                        "uploader": entry.get("uploader"),
                        "platform": platform,
                    })
            return jsonify({
                "type": "playlist",
                "title": info.get("title", "Playlist"),
                "videos": videos,
                "count": len(videos),
                "platform": platform,
            })

        return jsonify({
            "type": "video",
            "title": info.get("title", "Sem titulo"),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration"),
            "platform": platform,
            "uploader": info.get("uploader", ""),
            "description": info.get("description", "")[:500] if info.get("description") else "",
        })
    except Exception as exc:
        return jsonify({"error": format_extraction_error(exc, platform)}), 400


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json()
    url = (data or {}).get("url", "").strip()
    format_type = (data or {}).get("format", "mp4_best")

    if not url:
        return jsonify({"error": "URL nao informada"}), 400

    token = str(uuid.uuid4())
    threading.Thread(target=download_video, args=(url, format_type, token), daemon=True).start()
    return jsonify({"token": token})


@app.route("/api/convert-file", methods=["POST"])
def start_conversion():
    upload = request.files.get("file")
    format_key = (request.form.get("format") or "").strip()

    if upload is None or not upload.filename:
        return jsonify({"error": "Selecione um arquivo para converter."}), 400
    if not format_key:
        return jsonify({"error": "Selecione um formato de conversao."}), 400

    formats = get_conversion_formats()
    if format_key not in formats["video"] and format_key not in formats["audio"]:
        return jsonify({"error": "Formato de conversao invalido."}), 400

    token = str(uuid.uuid4())
    original_name = secure_filename(upload.filename) or f"arquivo_{token}"
    input_path = UPLOAD_DIR / f"{token}_{original_name}"
    upload.save(input_path)

    update_progress(
        token,
        status="starting",
        percent=5,
        title=original_name,
        filename=original_name,
        size=format_size(input_path.stat().st_size),
        message="Upload recebido. Aguardando conversao...",
    )

    threading.Thread(
        target=convert_media_file,
        args=(input_path, original_name, format_key, token),
        daemon=True,
    ).start()

    return jsonify({"token": token})


@app.route("/api/download-batch", methods=["POST"])
def start_batch_download():
    data = request.get_json()
    videos = (data or {}).get("videos", [])
    format_type = (data or {}).get("format", "mp4_best")

    if not videos:
        return jsonify({"error": "Nenhum video selecionado"}), 400

    results = []
    for video in videos:
        url = normalize_batch_video_url(video)
        title = video.get("title", "video")
        if not url:
            results.append({"title": title, "success": False, "error": "URL invalida"})
            continue

        token = str(uuid.uuid4())
        update_progress(token, status="starting", percent=0, title=title, message="Preparando download...", source_url=url)
        threading.Thread(target=download_video, args=(url, format_type, token), daemon=True).start()
        time.sleep(0.1)
        results.append({"title": title, "token": token, "url": url})

    return jsonify({"results": results})


@app.route("/api/progress/<token>")
def get_progress(token: str):
    return jsonify(progress_store.get(token, {"status": "not_found"}))


@app.route("/api/file/<token>")
def serve_file(token: str):
    data = progress_store.get(token, {})
    if data.get("status") != "done":
        return jsonify({"error": "Arquivo nao disponivel"}), 404

    filepath = data["filepath"]
    filename = data["filename"]

    if not os.path.exists(filepath):
        return jsonify({"error": "Arquivo nao encontrado"}), 404

    return send_file(filepath, as_attachment=True, download_name=filename)


def shutdown_session():
    time.sleep(0.75)
    stop_ngrok()

    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception as exc:
        logger.error(f"Falha ao encerrar processo principal: {exc}")
        os._exit(0)


@app.route("/api/shutdown", methods=["POST"])
def shutdown_app():
    logger.warning("Solicitacao de encerramento recebida pelo frontend.")
    threading.Thread(target=shutdown_session, daemon=True).start()
    return jsonify({"message": "Aplicacao sera encerrada."})


if __name__ == "__main__":
    threading.Thread(target=cleanup_old_files, daemon=True).start()

    if public_url_store["enabled"]:
        threading.Thread(target=start_ngrok, daemon=True).start()

    app.run(debug=False, host="0.0.0.0", port=FLASK_PORT)
