# YouDow - Workspace de mídia

Aplicação web para download remoto, playlists em lote, conversão local de arquivos e operação de link público em uma única interface.

## Plataformas Suportadas

- YouTube
- Instagram
- TikTok
- Kwai
- Vimeo
- Twitter/X
- Facebook
- E muitas outras (via yt-dlp)

## Formatos Disponíveis

### Vídeo
- **MP4** (Melhor qualidade, 1080p, 720p, 480p, 360p)
- **WebM** (Melhor qualidade, 1080p)

### Áudio
- **MP3** (320kbps, 192kbps, 128kbps)
- **WAV** (Lossless)
- **FLAC** (Lossless)
- **M4A** (Melhor qualidade)
- **OGG** (Melhor qualidade)
- **AAC** (Melhor qualidade)

## Instalação

```bash
# Instalar dependências
pip install -r requirements.txt

# Executar a aplicação
python app.py
```

A aplicação estará disponível em `http://localhost:5000`

## Uso

### Workspace principal (/)
1. Use o modo `Captura` para baixar um link individual.
2. Use o modo `Playlist` para carregar uma coleção, selecionar itens e baixar em lote.
3. Use o modo `Conversão` para enviar um arquivo local e convertê-lo para outro formato.
4. Acompanhe o progresso e a entrega final no painel lateral direito.

### Compatibilidade (/browse)
- A rota `/browse` continua disponível.
- Ela abre a mesma workspace com a área de playlist ativa por padrão.

## Recursos

- Download de vídeos individuais por URL
- Download em lote para playlists, canais e coleções
- Conversão local com presets de vídeo e áudio
- Controle de status do ngrok e cópia de link público
- Barra de progresso em tempo real
- Interface única, responsiva e reorganizada por fluxos

## Requisitos

- Python 3.8+
- FFmpeg (para processamento de áudio/vídeo)
- Flask
- yt-dlp

## Nota

Os arquivos baixados são armazenados temporariamente na pasta `downloads/` e são removidos após 1 hora.

## Cookies para Instagram/Facebook

Alguns links dessas plataformas não liberam mídia sem autenticação. Se você não quer depender do navegador, use um arquivo `cookies.txt` em formato Netscape na raiz do projeto:

```bash
/home/kali/YouDow/cookies.txt
```

Se `YTDLP_COOKIEFILE` estiver vazio e esse arquivo existir, o app usa esse caminho automaticamente.

Se preferir outro local, configure no `.env`:

```bash
YTDLP_COOKIEFILE=/caminho/para/cookies.txt
```

O uso de `YTDLP_COOKIES_FROM_BROWSER` continua disponível só como alternativa:

```bash
YTDLP_COOKIES_FROM_BROWSER=firefox
```

Exemplos úteis no Linux/Kali com suporte no `yt-dlp`: `chrome`, `edge`, `firefox`, `opera` e `brave`.

Se você usa Chromium no Linux, configure `YTDLP_COOKIES_FROM_BROWSER=chromium`. O nome do perfil é diferente de `chrome`.

O formato de `YTDLP_COOKIES_FROM_BROWSER` segue `BROWSER[+KEYRING][:PROFILE][::CONTAINER]`.
