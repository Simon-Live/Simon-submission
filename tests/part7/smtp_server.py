"""A small real SMTP server for tests: STARTTLS or implicit TLS, AUTH PLAIN, scripted refusals.

It listens on 127.0.0.1 with a throwaway self-signed certificate for `localhost`; a test trusts that certificate through
`SSL_CERT_FILE`. Nothing leaves the machine. Each connection is one entry in `.sessions`.
"""

from __future__ import annotations

import base64
import datetime
import ipaddress
import socket
import ssl
import threading
from pathlib import Path
from typing import Any


def make_cert(folder: Path) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = folder / "cert.pem", folder / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    return cert_path, key_path


class SmtpServer:
    """`mode`: `starttls` (offers STARTTLS), `implicit` (TLS from the first byte) or `plain` (no TLS offered).
    `rcpt_code` / `data_code`: the answer to RCPT TO / to the end of DATA (250 accepts)."""

    def __init__(self, folder: Path, mode: str = "starttls", rcpt_code: int = 250, data_code: int = 250, reply_id: str = "queued-as-0123456789abcdef") -> None:
        self.mode, self.rcpt_code, self.data_code, self.reply_id = mode, rcpt_code, data_code, reply_id
        self.cert, self.key = make_cert(folder)
        self.sessions: list[dict[str, Any]] = []
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.load_cert_chain(self.cert, self.key)
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self) -> None:
        self._stop = True
        self._sock.close()

    def _accept(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            session: dict[str, Any] = {"tls": False, "auth": None, "rcpt": [], "data": None, "clear_commands": []}
            self.sessions.append(session)
            threading.Thread(target=self._serve, args=(conn, session), daemon=True).start()

    def _serve(self, conn: socket.socket, session: dict[str, Any]) -> None:
        try:
            if self.mode == "implicit":
                conn = self._ctx.wrap_socket(conn, server_side=True)
                session["tls"] = True
            self._talk(conn, session)
        except (OSError, ssl.SSLError):
            session["aborted"] = True
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _talk(self, conn: Any, session: dict[str, Any]) -> None:
        rfile = conn.makefile("rb")

        def say(line: str) -> None:
            conn.sendall(line.encode() + b"\r\n")

        say("220 localhost test smtp")
        while True:
            raw = rfile.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            verb = line.split(" ", 1)[0].upper()
            if not session["tls"]:
                session["clear_commands"].append(verb)
            if verb in ("EHLO", "HELO"):
                extras = ["250-localhost", "250-AUTH PLAIN"] + (["250-STARTTLS"] if self.mode == "starttls" and not session["tls"] else [])
                for item in extras:
                    say(item)
                say("250 OK")
            elif verb == "STARTTLS":
                say("220 ready")
                conn = self._ctx.wrap_socket(conn, server_side=True)
                rfile = conn.makefile("rb")
                session["tls"] = True
            elif verb == "AUTH":
                _, user, password = base64.b64decode(line.split()[-1]).decode().split("\0")
                session["auth"] = (user, password)
                say("235 ok")
            elif verb == "MAIL":
                say("250 ok")
            elif verb == "RCPT":
                session["rcpt"].append(line)
                say(f"{self.rcpt_code} recipient answer")
            elif verb == "DATA":
                say("354 go on")
                body = []
                while True:
                    chunk = rfile.readline()
                    if chunk in (b".\r\n", b""):
                        break
                    body.append(chunk)
                session["data"] = b"".join(body)
                say(f"{self.data_code} Ok {self.reply_id}")
            elif verb == "QUIT":
                say("221 bye")
                return
            else:
                say("250 ok")
