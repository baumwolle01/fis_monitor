from pathlib import Path
from typing import Any


def strip_comments(line: str) -> str:
    """Entfernt Inline-Kommentare mit ';' oder '//' außerhalb von Anführungszeichen."""
    in_quotes = False
    quote_char = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if ch in ('"', "'"):
            if not in_quotes:
                in_quotes = True
                quote_char = ch
            elif quote_char == ch:
                in_quotes = False
        elif not in_quotes:
            if ch == ";":
                return line[:i]
            if line[i : i + 2] == "//":
                return line[:i]
        i += 1
    return line


def clean_value(raw: str) -> Any:
    """Wandelt Rohwerte in int, tuple(RGB) oder bereinigten str um."""
    val = raw.strip()
    if val.endswith(";"):
        val = val[:-1].strip()

    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        return val[1:-1]

    # RGB-Tripel wie "255, 255, 0"
    if "," in val:
        parts = [p.strip() for p in val.split(",")]
        if len(parts) == 3 and all(p.lstrip("-").isdigit() for p in parts):
            return tuple(int(p) for p in parts)

    if val.lstrip("-").isdigit():
        return int(val)

    return val


def parse_cfg(filepath: str | Path) -> dict[str, Any]:
    """Liest die custom2.cfg in eine strukturierte Dictionary-Struktur ein."""
    path = Path(filepath)
    data: dict[str, Any] = {
        "meta": {},
        "ibis_system": {},
        "anzeige": {},
        "grafikdateien": {},
        "auswahl": [],
        "sequenzen": [],
        "feldlisten": {},     # {listen_nr: [feld_nr, ...]}
        "felder": {},         # {feld_nr: {prop: val}}
        "ibis_telegramme": [],
        "linien_umsetzung": [],
        "anzeigefelder": {},  # {feld_nr: (x, y, breite, hoehe)}
    }

    current_section: str | None = None

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = strip_comments(raw_line).strip()
        if not line:
            continue

        # Sektionskopf wie [Feld=1] oder [Anzeige]
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            if current_section.startswith("Feld="):
                try:
                    feld_nr = int(current_section.split("=", 1)[1].strip())
                    data["felder"].setdefault(feld_nr, {"nr": feld_nr})
                except ValueError:
                    pass
            continue

        if "=" not in line:
            continue

        key, raw_val = line.split("=", 1)
        key = key.strip()
        val = clean_value(raw_val)

        if current_section == "Kunde":
            data["meta"][key] = val
        elif current_section == "IBISSystem":
            data["ibis_system"][key] = val
        elif current_section == "Anzeige":
            data["anzeige"][key] = val
        elif current_section == "Grafikdateien":
            data["grafikdateien"][key] = val
        elif current_section == "Auswahl" and key == "Auswahl":
            # Erwartet z. B. "0 ", "Wagen haelt inaktiv"
            if isinstance(val, str) and "," in val:
                code, label = val.split(",", 1)
                data["auswahl"].append((code.strip(), label.strip()))
        elif current_section == "Sequenz" and key == "Sequenz":
            if isinstance(val, str):
                parts = [p.strip().strip('"') for p in val.split(",")]
                if len(parts) >= 6:
                    data["sequenzen"].append({
                        "seq_nr": int(parts[0]),
                        "teil": int(parts[1]),
                        "feldliste": int(parts[2]),
                        "zeit": int(parts[3]),
                        "steuer": int(parts[4]),
                        "bild": parts[5],
                    })
        elif current_section == "Feldliste" and key == "Feld":
            if isinstance(val, str) and "," in val:
                lst_nr_s, fld_nr_s = [x.strip() for x in val.split(",", 1)]
                lst_nr, fld_nr = int(lst_nr_s), int(fld_nr_s)
                data["feldlisten"].setdefault(lst_nr, []).append(fld_nr)
        elif current_section and current_section.startswith("Feld="):
            feld_nr = int(current_section.split("=", 1)[1].strip())
            # Normalisiere Schreibweisen wie Texttyp / TextTyp
            norm_key = "TextTyp" if key.lower() == "texttyp" else key
            data["felder"].setdefault(feld_nr, {"nr": feld_nr})[norm_key] = val
        elif current_section == "IBISTelegramme" and key == "IbisDS":
            if isinstance(val, str):
                parts = [p.strip() for p in val.split(",")]
                data["ibis_telegramme"].append(parts)
        elif current_section == "LinienUmsetzung" and key == "LNR":
            if isinstance(val, str):
                parts = [p.strip() for p in val.split(",")]
                data["linien_umsetzung"].append(parts)
        elif current_section == "Anzeigefelder" and key == "Feld":
            if isinstance(val, str):
                parts = [int(p.strip()) for p in val.split(",")]
                if len(parts) == 5:
                    nr, x, y, w, h = parts
                    data["anzeigefelder"][nr] = (x, y, w, h)

    return data