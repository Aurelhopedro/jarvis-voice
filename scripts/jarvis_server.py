import asyncio, json, os, base64, tempfile, random
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


class VAD:
    def __init__(self, sample_rate=16000, silence_ms=800, threshold=0.01):
        self.sample_rate  = sample_rate
        self.silence_samp = int(sample_rate * silence_ms / 1000)
        self.threshold    = threshold
        self.buffer       = []
        self.silence_cnt  = 0
        self.speaking     = False

    def process(self, chunk: np.ndarray):
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        if rms > self.threshold:
            self.speaking    = True
            self.silence_cnt = 0
            self.buffer.append(chunk)
        elif self.speaking:
            self.silence_cnt += len(chunk)
            self.buffer.append(chunk)
            if self.silence_cnt >= self.silence_samp:
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


print("A carregar modelo Whisper...")
whisper_model = whisper.load_model("base")
print("Whisper pronto")

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


historico = []


def llm(mensagem: str) -> str:
    historico.append({"role": "user", "content": mensagem})
    if GEMINI_KEY:
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
            return texto
        except Exception as e:
            print(f"Gemini falhou: {e}")
    if GROQ_KEY:
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
            return texto
        except Exception as e:
            print(f"Groq falhou: {e}")
    return "Peco desculpa, estou com dificuldades de ligacao."


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    print("Cliente ligado")
    vad = VAD(sample_rate=16000, silence_ms=800, threshold=0.01)
    saudacao = random.choice(FRASES_INICIO)
    audio_b64 = await tts(saudacao)
    await ws.send_json({"tipo": "audio", "dados": audio_b64, "texto": saudacao})

    async def iniciativa():
        await asyncio.sleep(60)
        while True:
            await asyncio.sleep(120)
            dica = random.choice(FRASES_INICIATIVA)
            b64 = await tts(dica)
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
            if tipo == "audio_chunk":
                raw   = base64.b64decode(data["dados"])
                chunk = np.frombuffer(raw, dtype=np.float32)
                resultado = vad.process(chunk)
                if resultado is not None and len(resultado) > 3200:
                    await ws.send_json({"tipo": "estado", "estado": "processando"})
                    texto_user = stt(resultado)
                    print(f"User: {texto_user}")
                    if texto_user and len(texto_user) > 2:
                        await ws.send_json({"tipo": "transcricao", "texto": texto_user})
                        resposta = llm(texto_user)
                        print(f"Jarvis: {resposta}")
                        b64 = await tts(resposta)
                        await ws.send_json({"tipo": "audio", "dados": b64, "texto": resposta})
                    else:
                        await ws.send_json({"tipo": "estado", "estado": "ouvindo"})
            elif tipo == "texto":
                msg = data.get("mensagem", "").strip()
                if msg:
                    print(f"User [texto]: {msg}")
                    await ws.send_json({"tipo": "transcricao", "texto": msg})
                    resposta = llm(msg)
                    print(f"Jarvis: {resposta}")
                    b64 = await tts(resposta)
                    await ws.send_json({"tipo": "audio", "dados": b64, "texto": resposta})
            elif tipo == "ping":
                await ws.send_json({"tipo": "pong"})
            elif tipo == "vad_reset":
                vad.reset()
    except WebSocketDisconnect:
        print("Cliente desligado")


@app.get("/health")
def health():
    return {"status": "online", "jarvis": "operacional", "whisper": "pronto"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
