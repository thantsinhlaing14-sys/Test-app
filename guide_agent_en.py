import ast
import json
import os
import threading
import warnings

import chromadb
import numpy as np
import psycopg
import sounddevice as sd
from colorama import Fore
from kokoro import KPipeline
from llama_cpp import Llama
from psycopg.rows import dict_row
from tqdm import tqdm

from bridge import reset_display, send_text, show_route
from navigation import route_to_place


DB_PARAMS = {
    "dbname": "misaki_en",
    "user": "azaki",
    "password": "mackenziefoy",
    "host": "localhost",
    "port": "5432",
}

QWEN_MODEL_PATH = r"D:\models\qwen\qwen2.5-7b-instruct-q4_k_m.gguf"
EMBEDDING_MODEL_PATH = "D:/models/nomic-embed-text-v1.5.Q6_K.gguf"

SAMPLE_RATE = 24000

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["LLAMA_CPP_LIB"] = "0"
warnings.filterwarnings("ignore")

gpu_lock = threading.Lock()

print("Loading models.")

llm = Llama(
    model_path=QWEN_MODEL_PATH,
    n_ctx=4096,
    n_gpu_layers=24,
    verbose=False,
)

text_embed = Llama(
    model_path=EMBEDDING_MODEL_PATH,
    n_ctx=512,
    verbose=False,
    pooling_type=1,
    embedding=True,
)

pipeline = KPipeline(lang_code="a", device="cuda")

client = chromadb.Client()

system_prompt = (
    "You are a friendly university guide robot. "
    "Give concise spoken answers. "
    "When route information has already been shown on the robot display, explain the route naturally. "
    "Do not make up classroom or facility locations that are not provided."
)

convo = [{"role": "system", "content": system_prompt}]


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
        docs = results["documents"][0]

        for doc in docs:
            if doc not in results_set:
                results_set.add(doc)

    return results_set


def create_queries(prompt):
    query_msg = (
        "You are a first principle reasoning search query AI agent. "
        "Your list of search queries will be ran on an embedding database of all your conversations "
        "you have ever had with the user. With first principles create a Python list of queries to "
        "search the embeddings database for any data that would be necessary to have access to in "
        "order to correctly respond to the prompt. Your response must be a Python list with no syntax errors. "
        "Do not explain anything and do not ever generate anything but a perfect syntax Python list"
    )
    query_convo = [
        {"role": "system", "content": query_msg},
        {"role": "user", "content": "Where is the nearest toilet?"},
        {"role": "assistant", "content": '["nearest toilet", "current location", "university floor route"]'},
        {"role": "user", "content": "How do I get to classroom 101?"},
        {"role": "assistant", "content": '["classroom 101", "route to room 101", "university map"]'},
        {"role": "user", "content": prompt},
    ]

    with gpu_lock:
        response = llm.create_chat_completion(messages=query_convo, temperature=0.1)
    print(Fore.YELLOW + f'\nVector database queries: {response["choices"][0]["message"]["content"]} \n')

    try:
        return ast.literal_eval(response["choices"][0]["message"]["content"])
    except Exception:
        return [prompt]


def recall(prompt):
    try:
        queries = create_queries(prompt)
        embeddings = retrieve_embeddings(queries)
        convo.append(
            {
                "role": "user",
                "content": f"MEMORIES: {embeddings}\nUSER PROMPT: {prompt}",
            }
        )
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


def generate_tts(text_chunk, voice="af_heart", speed=1.0):
    generator = pipeline(text=text_chunk, voice=voice, speed=speed, split_pattern=r"\n+")

    wav = None
    for _, _, audio in generator:
        wav = audio

    if wav is None:
        raise RuntimeError("Kokoro returned no audio")

    return np.array(wav, dtype=np.float32)


def build_route_context(prompt):
    route = route_to_place(prompt)
    if route is None:
        return None

    show_route(json.dumps(route))
    route_sentence = (
        "The direction is shown on the display. "
        f"From {route['startName']} to {route['destinationName']}, "
        f"the distance is {route['distance']} feet and the estimated walking time is {route['walkingTimeText']}."
    )
    return (
        f"Route already shown to the user: {route_sentence} "
        "Reply with exactly that sentence in natural English. "
        "Do not include labels like start=, destination=, distance=, or any internal node names."
    )


def stream_and_tts(prompt, temperature=0.7):
    global convo
    reset_display()
    route_context = build_route_context(prompt)

    if route_context:
        prompt_for_llm = f"{route_context}\nUSER PROMPT: {prompt}"
    else:
        prompt_for_llm = prompt

    convo.append({"role": "user", "content": prompt_for_llm})
    if len(convo) > 7:
        convo = [convo[0]] + convo[-5:]

    response_text = ""
    tts_buffer = ""
    sentence_endings = {".", "!", "?", "\n"}

    with gpu_lock:
        stream = llm.create_chat_completion(
            messages=convo,
            stream=True,
            temperature=temperature,
        )

    print(Fore.LIGHTGREEN_EX + "\nAssistant:\n")

    for chunk in stream:
        delta = chunk["choices"][0]["delta"]
        if "content" not in delta:
            continue

        token = delta["content"]
        print(token, end="", flush=True)
        send_text(token)
        response_text += token
        tts_buffer += token

        if any(tts_buffer.endswith(p) for p in sentence_endings) and len(tts_buffer.strip()) > 5:
            sentence = tts_buffer.strip()
            tts_buffer = ""
            wav = generate_tts(sentence)
            sd.play(wav, samplerate=SAMPLE_RATE)
            sd.wait()

    if tts_buffer.strip():
        wav = generate_tts(tts_buffer.strip())
        sd.play(wav, samplerate=SAMPLE_RATE)
        sd.wait()

    print("\n")

    store_conversations(prompt, response_text.strip())
    convo.append({"role": "assistant", "content": response_text.strip()})


try:
    conversations = fetch_conversations()
    create_vector_db(conversations)
except Exception as exc:
    print(Fore.YELLOW + f"Memory database unavailable, continuing without recall: {exc}")


def main():
    print("Guide Robot English Test Ready.")

    while True:
        prompt = input(Fore.WHITE + "\nUser:\n")

        if not handle_prompt(prompt):
            break

def handle_prompt(prompt):
    prompt = prompt.strip()
    if not prompt:
        return True

    if prompt.lower() == "q":
        return False

    if prompt.startswith("/recall"):
        prompt = prompt[8:].strip()
        recall(prompt)
        stream_and_tts(prompt)
    elif prompt.startswith("/forget"):
        remove_last_conversation()
        if len(convo) >= 2:
            convo[:] = convo[:-2]
        print("Last memory removed.")
    else:
        stream_and_tts(prompt)

    return True


if __name__ == "__main__":
    main()
