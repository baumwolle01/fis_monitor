
from dataclasses import dataclass, field
import re


@dataclass
class MonitorState:
    linie_raw: str = "000"
    linie_e_raw: str = ""
    ziel: str = ""
    naechste_hst: str = ""
    folge_hst_2: str = ""
    folge_hst_3: str = ""
    uhrzeit: str = ""
    wagen_haelt: bool = False
    aktive_sequenz: int = 0
    extra_felder: dict[int, str] = field(default_factory=dict)

    def set_linie_telegramm(self, raw_payload: str, is_e: bool = False) -> None:
        """Speichert Hauptlinie und E-Linie getrennt."""

        payload = raw_payload.strip()

        if is_e:
            self.linie_e_raw = payload
            return

        self.linie_raw = payload or "000"

        # Bei einer neuen regulären Linie die alte E-Linie zurücksetzen.
        # 000 ist hierbei ausdrücklich ausgenommen, da es als Grundlinie
        # für eine E-Linie dienen kann.
        if self.linie_raw != "000":
            self.linie_e_raw = ""

    @staticmethod
    def _extract_number(value: str) -> int | None:
        """Extrahiert eine Zahl aus einem IBIS-Linienfeld."""
        match = re.search(r"(\d+)", value)
        if not match:
            return None

        try:
            return int(match.group(1))
        except ValueError:
            return None

    def format_linie(self, linien_umsetzung: list[list[str]]) -> str:
        """
        Formatiert die Linienanzeige.

        Regeln:
        - 000 = keine normale Linie
        - 00 / 0 = keine aktive E-Linie
        - E00 wird niemals ausgegeben
        - Gültige Linienumsetzungen haben Vorrang
        - Eine aktive E-Linie wird als E<n> dargestellt
        """

        # Hauptlinie ermitteln
        main_raw = self.linie_raw.strip() or "000"
        main_num = self._extract_number(main_raw)

        # E-Linie ermitteln
        e_raw = self.linie_e_raw.strip()
        e_num = self._extract_number(e_raw)

        # 00, 0 und leere E-Linien gelten als inaktiv
        e_active = bool(e_raw) and e_num is not None and e_num > 0
        e_val = e_num if e_active else 0

        # Falls keine gültige Hauptlinie vorhanden ist
        lnr = main_num if main_num is not None else -1

        # Linienumsetzung prüfen
        for row in linien_umsetzung:
            if len(row) < 5:
                continue

            try:
                von1 = int(row[0].strip())
                bis1 = int(row[1].strip())
                von2 = int(row[2].strip())
                bis2 = int(row[3].strip())
                ersetzung = row[4].strip().strip('"')
            except (ValueError, AttributeError):
                continue

            if not ersetzung:
                continue

            # Reine Null-Auffüller für normale Bereiche nicht als Text ersetzen
            if set(ersetzung) == {"0"} and von1 > 0:
                continue

            if von1 <= lnr <= bis1 and von2 <= e_val <= bis2:
                return ersetzung

        # Nur eine tatsächlich aktive E-Linie anzeigen
        if e_active:
            return f"E{e_raw}"

        # Keine E-Linie: normale Linie anzeigen
        return main_raw
