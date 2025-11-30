from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
    
    def log_message(self, format, *args):
        pass  # Disable logging

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthHandler)
    print("🩺 Health server running on port 8000")
    server.serve_forever()

if __name__ == '__main__':
    run_health_server()