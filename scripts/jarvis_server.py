import asyncio, json, os, base64, tempfile, random, subprocess
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import edge_tts
import whisper
import google.generativeai as genai
from groq import Groq

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_KEY   = os.environ.get("GROQ_API_KEY", "")

SYSTEM_PROMPT = (
    "Es o Jarvis — assistente pessoal de voz, inteligente e proactivo. "
    "Falas sempre em portugues de Portugal, com naturalidade e fluidez. "
    "Tens personalidade calorosa, ligeiramente britanica na educacao. "
    "Tomas iniciativa: das dicas, fazes perguntas pertinentes, comentas de forma inteligente. "
    "Respostas curtas e directas para voz — maximo 3 frases. "
    "Nunca digas que es uma IA. Es o Jarvis."
)

FRASES_INICIO = [
    "Jarvis operacional. Como posso ajudar?",
    "Sistema activo. Estou a disposicao.",
    "Pronto para servir. O que precisa?",
    "Jarvis online. Diga.",
]

FRASES_INICIATIVA = [
    "Esta tudo bem? Precisa de alguma coisa?",
    "Posso fazer pesquisas, dar conselhos ou simplesmente conversar.",
    "Se tiver alguma duvida, estou aqui.",
    "Lembre-se que pode falar naturalmente — estou sempre a ouvir.",
]

# ── Diagnóstico de arranque ─────────────────────────────────────────
print("=" * 60)
print("JARVIS DIAGNÓSTICO DE ARRANQUE")
print("=" * 60)
print(f"[CONFIG] GEMINI_API_KEY: {'DEFINIDA (' + str(len(GEMINI_KEY)) + ' chars)' if GEMINI_KEY else 'NÃO DEFINIDA ou VAZIA'}")
print(f"[CONFIG] GROQ_API_KEY:   {'DEFINIDA (' + str(len(GROQ_KEY)) + ' chars)' if GROQ_KEY else 'NÃO DEFINIDA ou VAZIA'}")

# Testar Gemini imediatamente ao arrancar
if GEMINI_KEY:
    print("[TESTE] A testar Gemini...")
    try:
        genai.configure(api_key=GEMINI_KEY)
        m = genai.GenerativeModel("gemini-1.5-flash")
        r = m.generate_content("Responde apenas: OK")
        print(f"[TESTE] Gemini OK: {r.text.strip()}")
    except Exception as e:
        print(f"[TESTE] Gemini FALHOU: {type(e).__name__}: {e}")
else:
    print("[TESTE] Gemini ignorado (sem chave)")

# Testar Groq imediatamente ao arrancar
if GROQ_KEY:
    print("[TESTE] A testar Groq...")
    try:
        client = Groq(api_key=GROQ_KEY)
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "Responde apenas: OK"}],
            max_tokens=10
        )
        print(f"[TESTE] Groq OK: {r.choices[0].message.content.strip()}")
    except Exception as e:
        print(f"[TESTE] Groq FALHOU: {type(e).__name__}: {e}")
else:
    print("[TESTE] Groq ignorado (sem chave)")

print("=" * 60)
print("A carregar modelo Whisper...")
whisper_model = whisper.load_model("base")
print("Whisper pronto")
print("=" * 60)
# ───────────────────────────────────────────────────────────────────

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


async def tts(texto: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        path = f.name
    comm = edge_tts.Communicate(texto, voice="pt-PT-DuarteNeural")
    await comm.save(path)
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    os.unlink(path)
    return b64


def stt(audio: np.ndarray) -> str:
    result = whisper_model.transcribe(
        audio, language="pt", fp16=False,
        condition_on_previous_text=False
    )
    return result["text"].strip()


def stt_webm(webm_bytes: bytes) -> str:
    """Converte WebM/Opus → WAV 16kHz mono com ffmpeg, depois passa ao Whisper."""
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f_in:
        f_in.write(webm_bytes)
        path_in = f_in.name

    path_out = path_in.replace(".webm", ".wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", path_in,
             "-ar", "16000", "-ac", "1", "-f", "wav", path_out],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        audio = whisper.load_audio(path_out)
        result = whisper_model.transcribe(
            audio, language="pt", fp16=False,
            condition_on_previous_text=False
        )
        return result["text"].strip()
    except Exception as e:
        print(f"[STT] stt_webm erro: {type(e).__name__}: {e}")
        return ""
    finally:
        for p in [path_in, path_out]:
            try: os.unlink(p)
            except: pass


historico = []


def llm(mensagem: str) -> str:
    historico.append({"role": "user", "content": mensagem})
    print(f"[LLM] Mensagem recebida: '{mensagem[:60]}'")

    if GEMINI_KEY:
        print("[LLM] A tentar Gemini...")
        try:
            genai.configure(api_key=GEMINI_KEY)
            model = genai.GenerativeModel(
                "gemini-1.5-flash",
                system_instruction=SYSTEM_PROMPT
            )
            hist = [
                {"role": m["role"], "parts": [m["content"]]}
                for m in historico[:-1]
            ]
            chat = model.start_chat(history=hist)
            resp = chat.send_message(mensagem)
            texto = resp.text
            historico.append({"role": "model", "content": texto})
            print(f"[LLM] Gemini respondeu: '{texto[:60]}'")
            return texto
        except Exception as e:
            print(f"[LLM] Gemini FALHOU: {type(e).__name__}: {e}")
    else:
        print("[LLM] Gemini ignorado (sem chave)")

    if GROQ_KEY:
        print("[LLM] A tentar Groq...")
        try:
            client = Groq(api_key=GROQ_KEY)
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + [
                {
                    "role": m["role"] if m["role"] != "model" else "assistant",
                    "content": m["content"]
                }
                for m in historico
            ]
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=msgs,
                max_tokens=200
            )
            texto = resp.choices[0].message.content
            historico.append({"role": "assistant", "content": texto})
            print(f"[LLM] Groq respondeu: '{texto[:60]}'")
            return texto
        except Exception as e:
            print(f"[LLM] Groq FALHOU: {type(e).__name__}: {e}")
    else:
        print("[LLM] Groq ignorado (sem chave)")

    print("[LLM] AMBOS FALHARAM — a devolver mensagem de fallback")
    return "Peco desculpa, estou com dificuldades de ligacao."


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    print("[WS] Cliente ligado")

    from dataclasses import dataclass, field

    @dataclass
    class VAD:
        sample_rate: int = 16000
        silence_ms: int = 800
        threshold: float = 0.01
        buffer: list = field(default_factory=list)
        silence_cnt: int = 0
        speaking: bool = False

        def process(self, chunk):
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms > self.threshold:
                self.speaking    = True
                self.silence_cnt = 0
                self.buffer.append(chunk)
            elif self.speaking:
                self.silence_cnt += len(chunk)
                self.buffer.append(chunk)
                if self.silence_cnt >= int(self.sample_rate * self.silence_ms / 1000):
                    audio = np.concatenate(self.buffer)
                    self.buffer      = []
                    self.silence_cnt = 0
                    self.speaking    = False
                    return audio
            return None

        def reset(self):
            self.buffer      = []
            self.silence_cnt = 0
            self.speaking    = False

    vad = VAD()

    saudacao  = random.choice(FRASES_INICIO)
    audio_b64 = await tts(saudacao)
    await ws.send_json({"tipo": "audio", "dados": audio_b64, "texto": saudacao})

    async def iniciativa():
        await asyncio.sleep(60)
        while True:
            await asyncio.sleep(120)
            dica = random.choice(FRASES_INICIATIVA)
            b64  = await tts(dica)
            try:
                await ws.send_json({
                    "tipo": "audio", "dados": b64,
                    "texto": dica, "iniciativa": True
                })
            except Exception:
                break

    asyncio.create_task(iniciativa())

    try:
        while True:
            data = await ws.receive_json()
            tipo = data.get("tipo")

            # ── Áudio WebM/Opus do MediaRecorder ─────────────────────────
            if tipo == "audio_webm":
                print(f"[WS] audio_webm recebido ({len(data['dados'])} chars b64)")
                raw_bytes = base64.b64decode(data["dados"])
                await ws.send_json({"tipo": "estado", "estado": "processando"})
                texto_user = await asyncio.to_thread(stt_webm, raw_bytes)
                print(f"[WS] STT resultado: '{texto_user}'")
                if texto_user and len(texto_user) > 2:
                    await ws.send_json({"tipo": "transcricao", "texto": texto_user})
                    resposta = await asyncio.to_thread(llm, texto_user)
                    b64 = await tts(resposta)
                    await ws.send_json({"tipo": "audio", "dados": b64, "texto": resposta})
                else:
                    print("[WS] STT devolveu texto vazio ou muito curto — a ignorar")
                    await ws.send_json({"tipo": "estado", "estado": "ouvindo"})

            # ── Áudio Float32 legado ──────────────────────────────────────
            elif tipo == "audio_chunk":
                raw   = base64.b64decode(data["dados"])
                chunk = np.frombuffer(raw, dtype=np.float32)
                resultado = vad.process(chunk)
                if resultado is not None and len(resultado) > 3200:
                    await ws.send_json({"tipo": "estado", "estado": "processando"})
                    texto_user = await asyncio.to_thread(stt, resultado)
                    print(f"[WS] STT [f32]: '{texto_user}'")
                    if texto_user and len(texto_user) > 2:
                        await ws.send_json({"tipo": "transcricao", "texto": texto_user})
                        resposta = await asyncio.to_thread(llm, texto_user)
                        b64 = await tts(resposta)
                        await ws.send_json({"tipo": "audio", "dados": b64, "texto": resposta})
                    else:
                        await ws.send_json({"tipo": "estado", "estado": "ouvindo"})

            # ── Texto ─────────────────────────────────────────────────────
            elif tipo == "texto":
                msg = data.get("mensagem", "").strip()
                if msg:
                    print(f"[WS] texto recebido: '{msg}'")
                    await ws.send_json({"tipo": "transcricao", "texto": msg})
                    resposta = await asyncio.to_thread(llm, msg)
                    b64 = await tts(resposta)
                    await ws.send_json({"tipo": "audio", "dados": b64, "texto": resposta})

            elif tipo == "ping":
                await ws.send_json({"tipo": "pong"})

            elif tipo == "vad_reset":
                vad.reset()

    except WebSocketDisconnect:
        print("[WS] Cliente desligado")


@app.get("/health")
def health():
    gemini_ok = bool(GEMINI_KEY)
    groq_ok   = bool(GROQ_KEY)
    return {
        "status":    "online",
        "jarvis":    "operacional",
        "whisper":   "pronto",
        "gemini":    "configurado" if gemini_ok else "sem chave",
        "groq":      "configurado" if groq_ok   else "sem chave",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
