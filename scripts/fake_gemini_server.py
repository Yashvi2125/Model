"""Local Fake Gemini Server for reproducible load and resilience testing.

Simulates:
- Configurable RPM limit (default: 10 requests/minute).
- 429 RESOURCE_EXHAUSTED responses with retryDelay when RPM limit is exceeded.
- Intermittent 503 UNAVAILABLE / model overload responses.
- Configurable response delays.
"""
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

PORT = 8089
RPM_LIMIT = 10
WINDOW_SECONDS = 60

request_timestamps = []
lock = threading.Lock()
call_counts = {"total": 0, "200": 0, "429": 0, "503": 0}


class FakeGeminiHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global request_timestamps
        now = time.time()
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        with lock:
            call_counts["total"] += 1
            request_timestamps = [t for t in request_timestamps if now - t < WINDOW_SECONDS]

            # 1. Check rate limit
            if len(request_timestamps) >= RPM_LIMIT:
                call_counts["429"] += 1
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                err_payload = {
                    "error": {
                        "code": 429,
                        "message": "Resource has been exhausted (e.g. check quota).",
                        "status": "RESOURCE_EXHAUSTED",
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                "retryDelay": "12s"
                            }
                        ]
                    }
                }
                self.wfile.write(json.dumps(err_payload).encode())
                return

            # Record timestamp
            request_timestamps.append(now)

            # 2. Intermittent 503 check (e.g., every 4th request simulates an overloaded server)
            if call_counts["total"] % 4 == 0:
                call_counts["503"] += 1
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                err_payload = {
                    "error": {
                        "code": 503,
                        "message": "The model is overloaded. Please try again later.",
                        "status": "UNAVAILABLE"
                    }
                }
                self.wfile.write(json.dumps(err_payload).encode())
                return

            # 3. Successful 200 response
            call_counts["200"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            # Inspect body to determine whether AutoGen OpenAI format or google-genai format
            body_str = body.decode("utf-8", errors="ignore")
            if "openai" in self.path or "chat/completions" in self.path:
                resp = {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion",
                    "created": int(now),
                    "model": "gemini-3.5-flash-lite",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "## Day 1: City Highlights\n**Morning**: Heritage walk\n**Afternoon**: Museum\n**Evening**: Riverfront\nTERMINATE_ITINERARY_PLAN"
                            },
                            "finish_reason": "stop"
                        }
                    ],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 50, "total_tokens": 100}
                }
            else:
                resp = {
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": json.dumps({"valid_places": ["Sabarmati Ashram", "Adalaj Stepwell"], "found": True, "lat": 23.03, "lon": 72.58})}],
                                "role": "model"
                            },
                            "finishReason": "STOP"
                        }
                    ]
                }
            self.wfile.write(json.dumps(resp).encode())

    def log_message(self, format, *args):
        # Silence default request logging to avoid terminal clutter
        pass


def run_fake_server():
    server = HTTPServer(("127.0.0.1", PORT), FakeGeminiHandler)
    server.serve_forever()


if __name__ == "__main__":
    print(f"Starting Fake Gemini Server on port {PORT} with RPM limit {RPM_LIMIT}...")
    run_fake_server()
