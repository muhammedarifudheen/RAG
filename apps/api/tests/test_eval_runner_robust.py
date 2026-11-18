"""One dropped connection must cost one question, not the whole run."""

import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.run_evals import main


def test_a_dropped_connection_is_one_failed_question_not_a_crashed_run(tmp_path, capsys):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body["question"])
            if len(calls) == 1:  # drop the first connection without answering
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
                self.connection.close()
                return
            out = json.dumps({"answer": "x", "citations": [], "chunks": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    path = tmp_path / "q.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"id": f"Q{i}", "question": f"question {i}?", "answerable": True, "relevant": []})
            for i in range(3)
        ),
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    url = f"http://127.0.0.1:{server.server_address[1]}"
    main(["--api", url, "--mode", "ask", "--golden", str(path), "--out", str(report)])
    server.shutdown()

    rows = json.loads(report.read_text(encoding="utf-8"))["questions"]
    assert len(rows) == 3  # the run finished
    assert rows[0]["error"] and not rows[1]["error"] and not rows[2]["error"]
    assert "Q0" in capsys.readouterr().out  # the failed question is named in the report
    assert "Connection" in rows[0]["error"] or "Disconnected" in rows[0]["error"]
