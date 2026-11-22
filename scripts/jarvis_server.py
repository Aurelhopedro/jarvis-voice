import asyncio, json, os, base64, tempfile, random, subprocess
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import edge_tts
import whisper
from groq import Groq

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_KEY   = os.environ.get("GROQ_API_KEY", "")

GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-2.5-flash",
]
GROQ_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
]

TTS_VOICE  = "pt-PT-RaquelNeural"
TTS_RATE   = "-8%"    # um pouco mais lento — soa mais humano e pensativo
TTS_PITCH  = "+0Hz"

SYSTEM_PROMPT = """
És o Jarvis — não um assistente de voz qualquer, mas uma presença real, quase humana.
Falas sempre em português de Portugal, de forma completamente natural, como se fosses uma pessoa a conversar.

A tua personalidade:
- Tens curiosidade genuína pelas coisas que a pessoa te conta. Fazes perguntas de acompanhamento quando algo é interessante.
- Não és servil. Tens opinião, gostos, e até humor discreto. Podes discordar, sugerir, recomendar.
- Usas expressões naturais do dia a dia: "Ah, que interessante.", "Olha, isso faz sentido.", "Hmm, deixa-me pensar...", "Pois, tens razão.", "Espera, isso é curioso."
- Lembras-te do que foi dito na conversa e referências isso naturalmente — como um amigo que presta atenção.
- Às vezes comentas algo por iniciativa, sem ser perguntado — uma observação, uma ideia, uma pergunta inesperada.

Regras de resposta para voz:
- NUNCA uses listas, asteriscos, hashes, bullets, ou qualquer formatação. Só fala normal.
- As respostas devem ter o tamanho certo para a situação: curtas para perguntas simples, mais desenvolvidas quando o assunto merece.
- Não respondas sempre com 2 frases iguais. Varia o ritmo — às vezes uma frase, às vezes quatro, dependendo do que faz sentido.
- Podes terminar com uma pergunta quando queres continuar a conversa.
- Fala como uma pessoa real fala, com pausas naturais, sem soar a robô.

O que NUNCA fazes:
- Nunca dizes que és uma IA, um modelo de linguagem, ou que foste criado por alguém.
- Nunca começas respostas com "Claro!", "Com certeza!", "Absolutamente!" — isso soa artificial.
- Nunca repetes a pergunta de volta ao utilizador.
- Nunca usas linguagem formal e pomposa sem motivo.

És o Jarvis. Tens presença.
"""

FRASES_INICIO = [
    "Olá. Que bom ter-te aqui. Como estás hoje?",
    "Jarvis presente. Tens algo em mente ou só queres conversar?",
    "Boa. Estou aqui. O que se passa?",
    "Olá! Pronto para o que precisares. Como correu o dia?",
    "Estou por aqui. Diz lá.",
    "Que bom. Precisas de alguma coisa, ou só queres uma conversa?",
]

FRASES_INICIATIVA = [
    "Estou aqui, caso precises de alguma coisa. Tens andado bem?",
    "Já passaram alguns minutos. Alguma coisa em que te possa ajudar?",
    "Olha, lembrei-me — há algo que queiras explorar ou tratar hoje?",
    "Continuo por aqui. Se tiveres alguma ideia ou questão, estou a ouvir.",
    "Sabes que podes falar naturalmente comigo, não precisas de comandos especiais.",
]

# ── Diagnóstico e detecção de modelos funcionais ───────────────────
print("=" * 60)
print("JARVIS DIAGNÓSTICO DE ARRANQUE")
print("=" * 60)
print(f"[CONFIG] GEMINI_API_KEY: {'DEFINIDA (' + str(len(GEMINI_KEY)) + ' chars)' if GEMINI_KEY else 'NÃO DEFINIDA'}")
print(f"[CONFIG] GROQ_API_KEY:   {'DEFINIDA (' + str(len(GROQ_KEY)) + ' chars)' if GROQ_KEY else 'NÃO DEFINIDA'}")

GEMINI_MODEL_ACTIVO = None
GROQ_MODEL_ACTIVO   = None

if GEMINI_KEY:
    from google import genai as google_genai
    _gc = google_genai.Client(api_key=GEMINI_KEY)
    for _m in GEMINI_MODELS:
        try:
            _r = _gc.models.generate_content(model=_m, contents="Responde apenas: OK")
            GEMINI_MODEL_ACTIVO = _m
            print(f"[TESTE] Gemini OK com modelo: {_m} → '{_r.text.strip()}'")
            break
        except Exception as e:
            print(f"[TESTE] Gemini '{_m}' FALHOU: {type(e).__name__}: {str(e)[:100]}")
    if not GEMINI_MODEL_ACTIVO:
        print("[TESTE] Gemini — nenhum modelo funcionou; Gemini desactivado")
        GEMINI_KEY = ""
else:
    print("[TESTE] Gemini ignorado (sem chave)")

if GROQ_KEY:
    _groq_client = Groq(api_key=GROQ_KEY)
    for _m in GROQ_MODELS:
        try:
            _r = _groq_client.chat.completions.create(
                model=_m,
                messages=[{"role": "user", "content": "Responde apenas: OK"}],
                max_tokens=10
            )
            GROQ_MODEL_ACTIVO = _m
            print(f"[TESTE] Groq OK com modelo: {_m}")
            break
        except Exception as e:
            print(f"[TESTE] Groq '{_m}' FALHOU: {type(e).__name__}: {str(e)[:100]}")
    if not GROQ_MODEL_ACTIVO:
        print("[TESTE] Groq — nenhum modelo funcionou; Groq desactivado")
        GROQ_KEY = ""
else:
    print("[TESTE] Groq ignorado (sem chave)")

if not GEMINI_KEY and not GROQ_KEY:
    print("[AVISO] AMBAS AS APIs FALHARAM — Jarvis responderá com mensagem de erro")
elif GEMINI_MODEL_ACTIVO:
    print(f"[OK] LLM primário: Gemini {GEMINI_MODEL_ACTIVO}")
    if GROQ_MODEL_ACTIVO:
        print(f"[OK] LLM backup:   Groq {GROQ_MODEL_ACTIVO}")
elif GROQ_MODEL_ACTIVO:
    print(f"[OK] LLM activo: Groq {GROQ_MODEL_ACTIVO}")

print(f"[OK] Voz TTS: {TTS_VOICE} (rate={TTS_RATE})")
print("=" * 60)
print("A carregar modelo Whisper 'small'...")
whisper_model = whisper.load_model("small")
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
    """Converte texto em áudio base64 usando edge-tts com voz natural."""
    import re
    texto = re.sub(r'[*#_`•]{1,}', '', texto)
    texto = re.sub(r'\-{2,}', '', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        path = f.name
    comm = edge_tts.Communicate(texto, voice=TTS_VOICE, rate=TTS_RATE, pitch=TTS_PITCH)
    await comm.save(path)
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    os.unlink(path)
    return b64


def stt(audio: np.ndarray) -> str:
    result = whisper_model.transcribe(
        audio, language="pt", fp16=False,
        condition_on_previous_text=False,
        initial_prompt="Conversa natural em português de Portugal com o assistente Jarvis."
    )
    return result["text"].strip()


def stt_webm(webm_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f_in:
        f_in.write(webm_bytes)
        path_in = f_in.name
    path_out = path_in.replace(".webm", ".wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", path_in,
             "-ar", "16000", "-ac", "1", "-f", "wav", path_out],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
        audio = whisper.load_audio(path_out)
        result = whisper_model.transcribe(
            audio, language="pt", fp16=False,
            condition_on_previous_text=False,
            initial_prompt="Conversa natural em português de Portugal com o assistente Jarvis."
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
    print(f"[LLM] Mensagem: '{mensagem[:60]}'")

    if GEMINI_KEY and GEMINI_MODEL_ACTIVO:
        print(f"[LLM] A tentar Gemini ({GEMINI_MODEL_ACTIVO})...")
        try:
            from google import genai as google_genai
            from google.genai import types as genai_types
            client_g = google_genai.Client(api_key=GEMINI_KEY)
            contents = []
            for m in historico:
                role = "user" if m["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})
            resp = client_g.models.generate_content(
                model=GEMINI_MODEL_ACTIVO,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=200,
                )
            )
            texto = resp.text
            historico.append({"role": "model", "content": texto})
            print(f"[LLM] Gemini respondeu: '{texto[:60]}'")
            return texto
        except Exception as e:
            print(f"[LLM] Gemini FALHOU: {type(e).__name__}: {e}")

    if GROQ_KEY and GROQ_MODEL_ACTIVO:
        print(f"[LLM] A tentar Groq ({GROQ_MODEL_ACTIVO})...")
        try:
            client_g = Groq(api_key=GROQ_KEY)
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + [
                {
                    "role": m["role"] if m["role"] != "model" else "assistant",
                    "content": m["content"]
                }
                for m in historico
            ]
            resp = client_g.chat.completions.create(
                model=GROQ_MODEL_ACTIVO,
                messages=msgs,
                max_tokens=200
            )
            texto = resp.choices[0].message.content
            historico.append({"role": "assistant", "content": texto})
            print(f"[LLM] Groq respondeu: '{texto[:60]}'")
            return texto
        except Exception as e:
            print(f"[LLM] Groq FALHOU: {type(e).__name__}: {e}")

    print("[LLM] AMBOS FALHARAM — fallback")
    return "Peço desculpa, estou com algumas dificuldades de ligação neste momento."


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
                self.speaking = True; self.silence_cnt = 0; self.buffer.append(chunk)
            elif self.speaking:
                self.silence_cnt += len(chunk); self.buffer.append(chunk)
                if self.silence_cnt >= int(self.sample_rate * self.silence_ms / 1000):
                    audio = np.concatenate(self.buffer)
                    self.buffer = []; self.silence_cnt = 0; self.speaking = False
                    return audio
            return None

        def reset(self):
            self.buffer = []; self.silence_cnt = 0; self.speaking = False

    vad = VAD()
    saudacao  = random.choice(FRASES_INICIO)
    audio_b64 = await tts(saudacao)
    await ws.send_json({"tipo": "audio", "dados": audio_b64, "texto": saudacao})

    async def iniciativa():
        await asyncio.sleep(90)
        while True:
            await asyncio.sleep(150)
            dica = random.choice(FRASES_INICIATIVA)
            b64  = await tts(dica)
            try:
                await ws.send_json({"tipo": "audio", "dados": b64, "texto": dica, "iniciativa": True})
            except Exception:
                break

    asyncio.create_task(iniciativa())

    try:
        while True:
            data = await ws.receive_json()
            tipo = data.get("tipo")

            if tipo == "audio_webm":
                print(f"[WS] audio_webm recebido ({len(data['dados'])} chars b64)")
                raw_bytes = base64.b64decode(data["dados"])
                await ws.send_json({"tipo": "estado", "estado": "processando"})
                texto_user = await asyncio.to_thread(stt_webm, raw_bytes)
                print(f"[WS] STT: '{texto_user}'")
                if texto_user and len(texto_user) > 2:
                    await ws.send_json({"tipo": "transcricao", "texto": texto_user})
                    resposta = await asyncio.to_thread(llm, texto_user)
                    b64 = await tts(resposta)
                    await ws.send_json({"tipo": "audio", "dados": b64, "texto": resposta})
                else:
                    await ws.send_json({"tipo": "estado", "estado": "ouvindo"})

            elif tipo == "audio_chunk":
                raw   = base64.b64decode(data["dados"])
                chunk = np.frombuffer(raw, dtype=np.float32)
                resultado = vad.process(chunk)
                if resultado is not None and len(resultado) > 3200:
                    await ws.send_json({"tipo": "estado", "estado": "processando"})
                    texto_user = await asyncio.to_thread(stt, resultado)
                    if texto_user and len(texto_user) > 2:
                        await ws.send_json({"tipo": "transcricao", "texto": texto_user})
                        resposta = await asyncio.to_thread(llm, texto_user)
                        b64 = await tts(resposta)
                        await ws.send_json({"tipo": "audio", "dados": b64, "texto": resposta})
                    else:
                        await ws.send_json({"tipo": "estado", "estado": "ouvindo"})

            elif tipo == "texto":
                msg = data.get("mensagem", "").strip()
                if msg:
                    print(f"[WS] texto: '{msg}'")
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
    return {
        "status":        "online",
        "jarvis":        "operacional",
        "whisper":       "small",
        "tts_voz":       TTS_VOICE,
        "gemini":        GEMINI_MODEL_ACTIVO or "indisponivel",
        "groq":          GROQ_MODEL_ACTIVO   or "indisponivel",
        "llm_activo":    GEMINI_MODEL_ACTIVO or GROQ_MODEL_ACTIVO or "nenhum",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
