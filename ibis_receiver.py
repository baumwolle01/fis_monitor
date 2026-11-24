import socket
import threading
from monitor_state import MonitorState

try:
    import serial  # type: ignore
except ImportError:
    serial = None


def decode_ibis_text(text: str) -> str:
    replacements = {"[": "Ä", "\\": "Ö", "]": "Ü", "{": "ä", "|": "ö", "}": "ü", "~": "ß"}
    for ibis_char, normal_char in replacements.items():
        text = text.replace(ibis_char, normal_char)
    return text


def calc_ibis_checksum(payload_with_cr: bytes) -> int:
    cs = 0x7F
    for b in payload_with_cr:
        cs ^= b
    return cs & 0x7F


def build_ibis_frame(text: str) -> bytes:
    raw = text.encode("latin-1", errors="replace") + b"\r"
    cs = calc_ibis_checksum(raw)
    return raw + bytes([cs])


class IBISReceiver:
    def __init__(self, state: MonitorState, lock: threading.Lock,
                 serial_port: str | None = None, baudrate: int = 1200,
                 tcp_port: int | None = None, udp_port: int | None = None,
                 verify_checksum: bool = False) -> None:
        self.state, self.lock = state, lock
        self.serial_port, self.baudrate = serial_port, baudrate
        self.tcp_port, self.udp_port = tcp_port, udp_port
        self.verify_checksum = verify_checksum
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._ser = None

    def start(self) -> None:
        if self.serial_port:
            if serial is None:
                print("[IBIS] Warnung: 'pyserial' fehlt (python -m pip install pyserial).")
            else:
                t = threading.Thread(target=self._serial_loop, daemon=True)
                t.start()
                self._threads.append(t)
        if self.tcp_port:
            t = threading.Thread(target=self._tcp_loop, daemon=True)
            t.start()
            self._threads.append(t)
        if self.udp_port:
            t = threading.Thread(target=self._udp_loop, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop_event.set()

    def _send_reply(self, reply_text: str) -> None:
        frame = build_ibis_frame(reply_text)
        if self._ser and self._ser.is_open:
            try:
                self._ser.write(frame)
            except Exception as exc:
                print(f"[IBIS] Antwort-Fehler: {exc}")

    def handle_telegram(self, raw: str) -> None:
        msg = raw.strip("\r\n\x00")
        if not msg:
            return
        with self.lock:
            if msg == "a":
                self._send_reply("a0")
                print("[IBIS] DS020 Statusanfrage -> DS120 gesendet")
                return
            if msg.startswith("aX"):
                text = decode_ibis_text(msg[2:].strip())
                if text:
                    self.state.naechste_hst = text
                print(f"[IBIS] DS021X/aA -> {text}")
                return
            if msg.startswith("lE"):
                e_payload = msg[2:].strip()
                self.state.set_linie_telegramm(e_payload, is_e=True)
                print(f"[IBIS] DS001a Linie-E -> {e_payload}")
                return
            cmd = msg[0]
            payload = msg[1:].strip()
            if cmd == "l":
                self.state.set_linie_telegramm(payload, is_e=False)
                print(f"[IBIS] DS001 Linie -> {self.state.linie_raw}")
                return
            if msg.startswith("aA"):
                zieltext = decode_ibis_text(msg[4:].strip())
                self.state.ziel = zieltext
                print(f"[IBIS] DS021 Ziel (aA) -> {zieltext}")
                return
            if msg.startswith("zA3"):
                zieltext = decode_ibis_text(msg[3:].strip())
                self.state.ziel = zieltext
                print(f"[IBIS] DS003a Ziel (zA3) -> {zieltext}")
                return
            if msg.startswith("zA2"):
                zieltext = decode_ibis_text(msg[3:].strip())
                self.state.ziel = zieltext
                print(f"[IBIS] DS003a Ziel (zA2) -> {zieltext}")
                return
            if msg.startswith("zA1"):
                zieltext = decode_ibis_text(msg[3:].strip())
                self.state.ziel = zieltext
                print(f"[IBIS] DS003a Ziel (zA) -> {zieltext}")
                return
            if msg.startswith("zA"):
                zieltext = decode_ibis_text(msg[2:].strip())
                self.state.ziel = zieltext
                print(f"[IBIS] DS003a Ziel (zA) -> {zieltext}")
                return
            if msg.startswith("v"):
                self.state.naechste_hst = decode_ibis_text(payload)
                print(f"[IBIS] Nächste Hst ({cmd}) -> {self.state.naechste_hst}")
                return
            if msg.startswith("zI"):
                payload = decode_ibis_text(msg[3:].strip())
                self.state.naechste_hst = payload
                print(f"[IBIS] Nächste Hst ({cmd}) -> {payload}")
                return
            if cmd == "f":
                sep = "|" if "|" in payload else "\\"
                parts = [decode_ibis_text(p.strip()) for p in payload.split(sep)]
                if len(parts) >= 1 and parts[0]:
                    self.state.folge_hst_2 = parts[0]
                if len(parts) >= 2 and parts[1]:
                    self.state.folge_hst_3 = parts[1]
                print(f"[IBIS] Folge-Hst -> {self.state.folge_hst_2} | {self.state.folge_hst_3}")
                return
            if cmd == "u":
                digits = "".join(ch for ch in payload if ch.isdigit())
                if len(digits) >= 4:
                    self.state.uhrzeit = f"{digits[:2]}:{digits[2:4]}"
                elif payload:
                    self.state.uhrzeit = payload
                print(f"[IBIS] DS005 Uhrzeit -> {self.state.uhrzeit}")
                return
            if cmd == "w":
                active = payload in ("1", "true", "aktiv", "ein")
                self.state.wagen_haelt = active
                self.state.aktive_sequenz = 1 if active else 0
                print(f"[IBIS] Wagen hält -> {active}")
                return
            if msg.startswith("xI"):
                active = msg[2:].strip() in ("1", "01")
                self.state.wagen_haelt = active
                self.state.aktive_sequenz = 1 if active else 0
                print(f"[IBIS] Steuersignal xI -> {active}")
                return
            print(f"[IBIS] Unbekanntes/unbehandeltes Telegramm: {msg!r}")

    def _serial_loop(self) -> None:
        assert self.serial_port is not None
        while not self._stop_event.is_set():
            try:
                with serial.Serial(self.serial_port, baudrate=self.baudrate,
                                   bytesize=serial.SEVENBITS, parity=serial.PARITY_EVEN,
                                   stopbits=serial.STOPBITS_TWO, timeout=0.2,
                                   write_timeout=0.5) as ser:
                    self._ser = ser
                    print(f"[IBIS] Seriell verbunden: {self.serial_port} @ {self.baudrate} 7E2")
                    buf = bytearray()
                    skip_next_checksum = False
                    while not self._stop_event.is_set():
                        try:
                            chunk = ser.read(64)
                        except Exception as read_exc:
                            print(f"[IBIS] Read-Fehler: {read_exc}")
                            break
                        if not chunk:
                            continue
                        print(f"[IBIS] RAW RX ({len(chunk)}B): {chunk!r}")
                        for b in chunk:
                            if skip_next_checksum:
                                skip_next_checksum = False
                                if self.verify_checksum:
                                    expected = calc_ibis_checksum(bytes(buf) + b"\r")
                                    if (b & 0x7F) != expected:
                                        print(f"[IBIS] Prüfsumme ungültig: {buf!r}")
                                        buf.clear()
                                        continue
                                if buf:
                                    self.handle_telegram(buf.decode("latin-1", errors="replace"))
                                    buf.clear()
                                continue
                            if b == 0x0D:
                                skip_next_checksum = True
                            elif b == 0x0A:
                                if buf:
                                    self.handle_telegram(buf.decode("latin-1", errors="replace"))
                                    buf.clear()
                            else:
                                buf.append(b & 0x7F)
            except Exception as exc:
                print(f"[IBIS] Seriell-Fehler ({self.serial_port}): {exc}")
            finally:
                self._ser = None
            if not self._stop_event.is_set():
                self._stop_event.wait(1.0)

    def _tcp_loop(self) -> None:
        assert self.tcp_port is not None
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.settimeout(0.5)
        try:
            srv.bind(("0.0.0.0", self.tcp_port))
            srv.listen(4)
            print(f"[IBIS] TCP-Server lauscht auf Port {self.tcp_port}")
            while not self._stop_event.is_set():
                try:
                    conn, _ = srv.accept()
                except TimeoutError:
                    continue
                with conn:
                    conn.settimeout(0.5)
                    while not self._stop_event.is_set():
                        try:
                            data = conn.recv(1024)
                        except TimeoutError:
                            continue
                        if not data:
                            break
                        for part in data.split(b"\r"):
                            clean = part[1:] if len(part) > 1 and part[0] < 0x20 else part
                            if clean:
                                self.handle_telegram(clean.decode("latin-1", errors="replace"))
        except Exception as exc:
            print(f"[IBIS] TCP-Fehler: {exc}")
        finally:
            srv.close()

    def _udp_loop(self) -> None:
        assert self.udp_port is not None
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        try:
            sock.bind(("0.0.0.0", self.udp_port))
            print(f"[IBIS] UDP-Listener lauscht auf Port {self.udp_port}")
            while not self._stop_event.is_set():
                try:
                    data, _ = sock.recvfrom(2048)
                except TimeoutError:
                    continue
                for part in data.split(b"\r"):
                    clean = part[1:] if len(part) > 1 and part[0] < 0x20 else part
                    if clean:
                        self.handle_telegram(clean.decode("latin-1", errors="replace"))
        except Exception as exc:
            print(f"[IBIS] UDP-Fehler: {exc}")
        finally:
            sock.close()
