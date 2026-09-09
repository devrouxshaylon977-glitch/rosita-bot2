import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import os, json

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"Rosita is alive")

def run_web():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(('0.0.0.0', port), Handler).serve_forever()

threading.Thread(target=run_web, daemon=True).start()

MEM_FILE = "memory.json"
memory = json.load(open(MEM_FILE)) if os.path.exists(MEM_FILE) else {}
def save_memory():
    json.dump(memory, open(MEM_FILE,"w"))

from groq import Groq
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def rosita_reply(sender, user_text):
    hist = "\n".join(memory.get(sender, [])[-10:])
    prompt = f"You are Rosita, warm friendly WhatsApp assistant. History:\n{hist}\nUser: {user_text}\nRosita:"
    resp = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role":"user","content":prompt}])
    reply = resp.choices[0].message.content
    memory.setdefault(sender, []).append(f"User: {user_text}\nRosita: {reply}")
    memory[sender]=memory[sender][-20:]
    save_memory()
    return reply

print("Rosita ready")
import time
while True: time.sleep(60)
