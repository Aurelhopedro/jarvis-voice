# J.A.R.V.I.S

Assistente de voz pessoal, em português, hospedado no GitHub Actions.

## Setup (uma vez só)

### 1. Adicionar os Secrets no GitHub
Vai a **Settings → Secrets and variables → Actions → New repository secret** e adiciona:

| Secret | Onde obter |
|---|---|
| `NGROK_AUTHTOKEN` | [dashboard.ngrok.com](https://dashboard.ngrok.com) → Your Authtoken |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) → Get API key |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) → API Keys |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) → API keys (opcional) |

### 2. Criar GitHub Personal Access Token
Vai a **Settings → Developer settings → Personal access tokens → Fine-grained tokens**:
- Repository access: só o repositório do Jarvis
- Permissions: `Actions` → Read and write

## Como usar

1. Abre o `index.html` no browser do telemóvel
2. Preenche `Aurelhopedro/jarvis-voice` e o teu token
3. Clica **Iniciar Jarvis** — dispara o workflow no GitHub
4. Aguarda ~2 minutos
5. Vai a **GitHub → Actions → Jarvis** e copia o URL ngrok nos logs
6. Cola o URL no campo do servidor e clica **Ligar**
7. Fala com o Jarvis! 🎤

## Transformar em APK

1. Vai a [PWABuilder.com](https://pwabuilder.com)
2. Cola o URL do `index.html` hospedado (GitHub Pages)
3. Descarrega o APK

## Limites do plano gratuito

- Repo privado: 2.000 minutos/mês (~11 sessões de 3h)
- Gemini: 1.500 req/dia gratuito
- Groq: 14.400 req/dia gratuito
- ngrok: 1 túnel simultâneo gratuito
