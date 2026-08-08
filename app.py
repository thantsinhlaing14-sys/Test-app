import logging
import threading
from queue import Queue
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from bridge import get_output_mode, reset_display, send_event, send_text, set_output_mode
from demo_interactions import get_interactions, run_interaction
from motion_commands import MOTION_COMMANDS, send_motion_command

app = Flask(__name__)
interaction_queue = Queue()

@app.route("/")
def index():
    return render_template("index.html", interactions=get_interactions())

@app.route("/admin")
def admin():
    return render_template("admin.html", interactions=get_interactions())

@app.route("/motion")
def motion():
    return render_template("motion.html", motions=MOTION_COMMANDS)

@app.route("/local-ai")
def local_ai():
    return render_template("local_ai.html")

@app.route("/api/interactions")
def interactions():
    return jsonify({"interactions": get_interactions()})

@app.route("/api/motion")
def motion_commands():
    return jsonify({"motions": MOTION_COMMANDS})

@app.route("/api/motion/<motion_id>/send", methods=["POST"])
def send_motion(motion_id):
    motion = next((item for item in MOTION_COMMANDS if item["id"] == motion_id), None)
    if motion is None:
        return jsonify({"error": "unknown motion command"}), 404

    return jsonify(send_motion_command(motion))

@app.route("/api/interactions/<interaction_id>/play", methods=["POST"])
def play_interaction(interaction_id):
    interaction = next((item for item in get_interactions() if item["id"] == interaction_id), None)
    if interaction is None:
        return jsonify({"error": "unknown interaction"}), 404

    interaction_queue.put(interaction)
    return jsonify({"queued": True, "interaction": interaction})

@app.route("/api/output-mode", methods=["GET", "POST"])
def output_mode():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        mode = data.get("mode")
        if mode not in ("laptop", "phone"):
            return jsonify({"error": "mode must be 'laptop' or 'phone'"}), 400
        set_output_mode(mode)
    return jsonify({"mode": get_output_mode()})

@app.route("/api/local-ai/stream", methods=["POST"])
def local_ai_stream():
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    from ai import run_local_ai_stream

    return Response(
        stream_with_context(run_local_ai_stream(prompt)),
        mimetype="text/plain",
    )

@app.route("/api/prompt", methods=["POST"])
def submit_prompt():
    data = request.get_json(silent=True) or {}
    interaction_id = data.get("interactionId") or data.get("prompt")
    if not interaction_id:
        return jsonify({"error": "interactionId is required"}), 400
    return play_interaction(str(interaction_id))

@app.route("/stream")
def stream():
    def generate():
        while True:
            chunk = display_queue.get()
            yield chunk + "\n"

    from bridge import display_queue

    return Response(generate(), mimetype="text/plain")

def run_demo_worker():
    while True:
        interaction = interaction_queue.get()
        try:
            run_interaction(interaction)
        except Exception as e:
            reset_display()
            send_text(f"Demo interaction error: {e}")
            send_event("done")
        finally:
            interaction_queue.task_done()

if __name__ == "__main__":
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    threading.Thread(target=run_demo_worker, daemon=True).start()

    print("Guide Robot Demo Display Starting on Port 7070")
    app.run(host="0.0.0.0", port=7070, debug=False, threaded=True, use_reloader=False)
