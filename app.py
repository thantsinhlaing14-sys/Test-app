import logging
import threading
from queue import Queue
from flask import Flask, Response, jsonify, render_template, request

from bridge import display_queue

app = Flask(__name__)
prompt_queue = Queue()
current_mode = {"language": "en"}
agents = {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin")
def admin():
    return render_template("admin.html")


@app.route("/api/mode", methods=["GET", "POST"])
def mode():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        language = data.get("language", "").lower()
        if language not in {"en", "mm"}:
            return jsonify({"error": "language must be en or mm"}), 400

        current_mode["language"] = language

    return jsonify(current_mode)


@app.route("/api/prompt", methods=["POST"])
def submit_prompt():
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    prompt_queue.put({"language": current_mode["language"], "prompt": prompt})
    return jsonify({"queued": True, "language": current_mode["language"]})


@app.route("/stream")
def stream():
    def generate():
        while True:
            chunk = display_queue.get()
            yield chunk + "\n"

    return Response(generate(), mimetype="text/plain")


def run_guide_agent():
    print("Guide Robot prompt worker ready.")

    while True:
        item = prompt_queue.get()
        try:
            if item["language"] == "mm":
                if "mm" not in agents:
                    import guide_agent_mm

                    agents["mm"] = guide_agent_mm
                agents["mm"].handle_prompt(item["prompt"])
            else:
                if "en" not in agents:
                    import guide_agent_en

                    agents["en"] = guide_agent_en
                agents["en"].handle_prompt(item["prompt"])
        except Exception as exc:
            print(f"Prompt worker error: {exc}")
        finally:
            prompt_queue.task_done()


if __name__ == "__main__":
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    threading.Thread(target=run_guide_agent, daemon=True).start()

    print("Display Starting on Port 5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True, use_reloader=False)
