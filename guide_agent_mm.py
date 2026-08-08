import ast
import os
import re
import threading
import time
import warnings
from queue import Queue

import chromadb
import numpy as np
import psycopg
import sounddevice as sd
import torch
from colorama import Fore
from llama_cpp import Llama
from num2words import num2words
from psycopg.rows import dict_row
from tqdm import tqdm
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, VitsModel

from bridge import reset_display, send_text, show_route
from navigation import route_to_place


MYANMAR_PLACE_NAMES = {
    "Main Entrance": "ပင်မဝင်ပေါက်",
    "Entrance B": "ဝင်ပေါက် ဘီ",
    "Main Building": "ပင်မဆောင်",
    "Workshop Left Entrance": "ဝပ်ရှော့ဘယ်ဘက်ဝင်ပေါက်",
    "Workshop Right Entrance": "ဝပ်ရှော့ညာဘက်ဝင်ပေါက်",
    "Teacher Dormitory A": "ဆရာ/ဆရာမ အိပ်ဆောင် အေ",
    "Teacher Dormitory B": "ဆရာ/ဆရာမ အိပ်ဆောင် ဘီ",
    "Teacher Dormitory C": "ဆရာ/ဆရာမ အိပ်ဆောင် စီ",
    "Teacher Dormitory D": "ဆရာ/ဆရာမ အိပ်ဆောင် ဒီ",
    "View Point": "ရှုခင်းကြည့်နေရာ",
    "Boys Dormitory A": "ကျောင်းသား အိပ်ဆောင် အေ",
    "Boys Dormitory B": "ကျောင်းသား အိပ်ဆောင် ဘီ",
    "Canteen": "စားသောက်ဆိုင်",
    "Girls Dormitory": "ကျောင်းသူ အိပ်ဆောင်",
    "Stadium": "အားကစားကွင်း",
}

MYANMAR_DIGITS = str.maketrans("0123456789.", "၀၁၂၃၄၅၆၇၈၉.")


DB_PARAMS = {
    "dbname": "misaki_en",
    "user": "azaki",
    "password": "mackenziefoy",
    "host": "localhost",
    "port": "5432",
}

QWEN_MODEL_PATH = "D:/models/qwen/qwen2.5-3b-instruct-q8_0.gguf"
EMBEDDING_MODEL_PATH = "D:/models/nomic-embed-text-v1.5.Q6_K.gguf"
TRANSLATER_MODEL_PATH = "D:/models/nllb-200-distilled-600M"
TTS_MODEL_PATH = "D:/codes/Vits_mms_finetune/finetune-hf-vits/mms-tts-mya-female-v1"

device = "cpu"
os.environ["HF_HUB_OFFLINE"] = "1"
warnings.filterwarnings("ignore")

client = chromadb.Client()
audio_queue = Queue()
gpu_lock = threading.Lock()

system_prompt = (
    "You are a friendly university guide robot. "
    "The user may type in Burmese, but you receive an English translation. "
    "Give concise spoken answers in English so the system can translate them back to Burmese. "
    "When route information has already been shown on the robot display, explain the route naturally. "
    "Do not make up classroom or facility locations that are not provided."
)

convo = [{"role": "system", "content": system_prompt}]

print("Loading Myanmar text models.")

llm = Llama(
    model_path=QWEN_MODEL_PATH,
    n_ctx=4096,
    n_gpu_layers=32,
    verbose=False,
)

text_embed = Llama(
    model_path=EMBEDDING_MODEL_PATH,
    n_ctx=2048,
    verbose=False,
    embedding=True,
)

tokenizer = AutoTokenizer.from_pretrained(TRANSLATER_MODEL_PATH)
model = AutoModelForSeq2SeqLM.from_pretrained(TRANSLATER_MODEL_PATH).to(device)
tts_model = VitsModel.from_pretrained(TTS_MODEL_PATH)
tts_tokenizer = AutoTokenizer.from_pretrained(TTS_MODEL_PATH)
tts_sample_rate = getattr(tts_model.config, "sampling_rate", 16000)


def audio_player():
    while True:
        chunk = audio_queue.get()
        if chunk is None:
            break
        sd.play(chunk, samplerate=tts_sample_rate)
        sd.wait()
        audio_queue.task_done()


player_thread = threading.Thread(target=audio_player, daemon=True)
player_thread.start()


number_pattern = re.compile(r"\d+(\.\d+)?(?:,\d{3})*")


def normalize_numwords(text):
    return text.replace(",", "").replace(" and ", " ")


def numbers_to_words(text):
    def repl(match):
        token = match.group(0).replace(",", "")
        if "." in token:
            whole, frac = token.split(".", 1)
            whole_words = num2words(int(whole), lang="en")
            frac_words = " ".join(num2words(int(d), lang="en") for d in frac)
            return normalize_numwords(f"{whole_words} point {frac_words}")

        try:
            return normalize_numwords(num2words(int(token), lang="en"))
        except Exception:
            return match.group(0)

    return number_pattern.sub(repl, text)


def to_myanmar_number(value):
    return str(value).translate(MYANMAR_DIGITS)


def format_walking_time_mm(seconds):
    seconds_text = to_myanmar_number(seconds)
    if seconds < 60:
        return f"{seconds_text} စက္ကန့်"

    minutes = seconds // 60
    remaining_seconds = seconds % 60
    minutes_text = to_myanmar_number(minutes)

    if remaining_seconds == 0:
        return f"{minutes_text} မိနစ်"

    remaining_text = to_myanmar_number(remaining_seconds)
    return f"{minutes_text} မိနစ် {remaining_text} စက္ကန့်"


def translate(text, src_lang, target_lang):
    tokenizer.src_lang = src_lang
    inputs = tokenizer(text, return_tensors="pt").to(device)
    generated_tokens = model.generate(
        **inputs,
        forced_bos_token_id=tokenizer.convert_tokens_to_ids(target_lang),
        max_length=512,
    )
    return tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]


def connect_db():
    return psycopg.connect(**DB_PARAMS)


def fetch_conversations():
    conn = connect_db()
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT * FROM conversations")
        rows = cursor.fetchall()
    conn.close()
    return rows


def store_conversations(prompt, response):
    try:
        conn = connect_db()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO conversations (timestamp, prompt, response) VALUES (CURRENT_TIMESTAMP, %s, %s)",
                (prompt, response),
            )
            conn.commit()
        conn.close()
    except Exception as exc:
        print(Fore.YELLOW + f"Could not store conversation memory: {exc}")


def remove_last_conversation():
    conn = connect_db()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM conversations WHERE id = (SELECT MAX(id) FROM conversations)")
        conn.commit()
    conn.close()


def create_vector_db(conversations):
    name = "conversations"
    try:
        client.delete_collection(name=name)
    except Exception:
        pass

    collection = client.create_collection(name=name)
    for c in conversations:
        text = f"prompt:{c['prompt']} response:{c['response']}"
        with gpu_lock:
            embedding = text_embed.create_embedding(text)["data"][0]["embedding"]
        collection.add(ids=[str(c["id"])], embeddings=[embedding], documents=[text])


def retrieve_embeddings(queries, n_results=2):
    results_set = set()
    collection = client.get_collection(name="conversations")

    for query in tqdm(queries):
        with gpu_lock:
            query_embedding = text_embed.create_embedding(query)["data"][0]["embedding"]
        results = collection.query(query_embeddings=[query_embedding], n_results=n_results)
        for doc in results["documents"][0]:
            if doc not in results_set:
                results_set.add(doc)

    return results_set


def create_queries(prompt):
    query_msg = (
        "You are a first principle reasoning search query AI agent. "
        "Your list of search queries will be ran on an embedding database of all your conversations "
        "you have ever had with the user. Return only a valid Python list of search queries."
    )
    query_convo = [
        {"role": "system", "content": query_msg},
        {"role": "user", "content": "Where is the nearest toilet?"},
        {"role": "assistant", "content": '["nearest toilet", "current location", "university floor route"]'},
        {"role": "user", "content": prompt},
    ]

    with gpu_lock:
        response = llm.create_chat_completion(messages=query_convo, temperature=0.1)

    try:
        return ast.literal_eval(response["choices"][0]["message"]["content"])
    except Exception:
        return [prompt]


def recall(prompt):
    try:
        queries = create_queries(prompt)
        embeddings = retrieve_embeddings(queries)
        convo.append({"role": "user", "content": f"MEMORIES: {embeddings}\nUSER PROMPT: {prompt}"})
    except Exception as exc:
        print(Fore.YELLOW + f"Recall unavailable: {exc}")


def text_chunker(token_stream):
    buffer = ""
    sentence_endings = {".", "!", "?", "\n"}

    for token in token_stream:
        buffer += token
        if any(buffer.endswith(p) for p in sentence_endings) and len(buffer.strip()) > 5:
            yield buffer.strip()
            buffer = ""

    if buffer.strip():
        yield buffer.strip()


def generate_tts(text_chunk):
    inputs = tts_tokenizer(text_chunk, return_tensors="pt")
    with torch.no_grad():
        output = tts_model(**inputs).waveform
    return output.squeeze().cpu().numpy().astype(np.float32)


def build_route_context(prompt):
    route = route_to_place(prompt)
    if route is None:
        return None

    route["displayLanguage"] = "mm"
    route["startNameLocalized"] = MYANMAR_PLACE_NAMES.get(route["startName"], route["startName"])
    route["destinationNameLocalized"] = MYANMAR_PLACE_NAMES.get(
        route["destinationName"],
        route["destinationName"],
    )
    route["distanceLocalized"] = to_myanmar_number(route["distance"])
    route["distanceUnitLocalized"] = "ပေ"
    route["walkingTimeTextLocalized"] = format_walking_time_mm(route["walkingTimeSeconds"])
    show_route(route)

    route_sentence = (
        "The direction is shown on the display. "
        f"From {route['startName']} to {route['destinationName']}, "
        f"the distance is {numbers_to_words(str(route['distance']))} feet "
        f"and the estimated walking time is {numbers_to_words(route['walkingTimeText'])}."
    )
    return (
        f"Route already shown to the user: {route_sentence} "
        "Reply with exactly that sentence in natural English. "
        "Do not include labels like start=, destination=, distance=, or any internal node names."
    )


def stream_and_tts(english_prompt, temperature=0.7):
    global convo
    reset_display()
    route_context = build_route_context(english_prompt)

    prompt_for_llm = f"{route_context}\nUSER PROMPT: {english_prompt}" if route_context else english_prompt
    convo.append({"role": "user", "content": prompt_for_llm})
    if len(convo) > 7:
        convo = [convo[0]] + convo[-5:]

    response_text = ""

    with gpu_lock:
        stream = llm.create_chat_completion(messages=convo, stream=True, temperature=temperature)

    print(Fore.LIGHTGREEN_EX + "\nAssistant:\n")
    token_gen = (
        chunk["choices"][0]["delta"]["content"]
        for chunk in stream
        if "content" in chunk["choices"][0]["delta"]
    )

    for sentence in text_chunker(token_gen):
        response_text += sentence + " "
        start_time = time.perf_counter()
        burmese_sentence = translate(numbers_to_words(sentence), "eng_Latn", "mya_Mymr")
        elapsed = time.perf_counter() - start_time

        print(sentence, end=" ", flush=True)
        print(Fore.YELLOW + f"\nTranslated sentence in {elapsed:.2f}s: {burmese_sentence}")
        send_text(burmese_sentence + " ")
        audio_queue.put(generate_tts(burmese_sentence))

    audio_queue.join()
    print("\n")

    english_response = response_text.strip()
    store_conversations(english_prompt, english_response)
    convo.append({"role": "assistant", "content": english_response})


def handle_prompt(burmese_prompt):
    burmese_prompt = burmese_prompt.strip()
    if not burmese_prompt:
        return True

    if burmese_prompt.lower() == "q":
        return False

    english_prompt = translate(burmese_prompt, "mya_Mymr", "eng_Latn")
    print(Fore.WHITE + f"\nUser Burmese: {burmese_prompt}")
    print(Fore.WHITE + f"User English: {english_prompt}")

    if english_prompt.startswith("/recall"):
        prompt = english_prompt[8:].strip()
        recall(prompt)
        stream_and_tts(prompt)
    elif english_prompt.startswith("/forget"):
        remove_last_conversation()
        if len(convo) >= 2:
            convo[:] = convo[:-2]
        print("Last memory removed.")
    else:
        stream_and_tts(english_prompt)

    return True


try:
    conversations = fetch_conversations()
    create_vector_db(conversations)
except Exception as exc:
    print(Fore.YELLOW + f"Memory database unavailable, continuing without recall: {exc}")
