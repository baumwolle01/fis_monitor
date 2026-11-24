from pathlib import Path
import threading
import pygame

from cfg_parser import parse_cfg
from ibis_receiver import IBISReceiver
from monitor_state import MonitorState
from werbung import WerbungManager


def make_fallback_bg(width: int, height: int) -> pygame.Surface:
    surf = pygame.Surface((width, height))
    surf.fill((15, 22, 36))
    pygame.draw.rect(surf, (35, 50, 75), (15, 15, max(1, width - 30), max(1, height - 30)), width=2)
    return surf


def make_fallback_stop(width: int, height: int) -> pygame.Surface:
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    pygame.draw.rect(surf, (210, 35, 35), surf.get_rect(), border_radius=10)
    font = pygame.font.SysFont("Arial", max(24, height // 2), bold=True)
    txt = font.render("WAGEN HÄLT", True, (255, 255, 255))
    surf.blit(txt, txt.get_rect(center=surf.get_rect().center))
    return surf


def get_field_text(feld: dict, state: MonitorState, linien_umsetzung: list) -> str:
    text_typ = str(feld.get("TextTyp", "")).lower()

    if text_typ == "linie":
        return state.format_linie(linien_umsetzung)
    if text_typ == "zieltextds021":
        return state.ziel
    if text_typ == "haltestelleds009":
        return state.naechste_hst
    if text_typ == "haltestelleds021":
        hst_idx = int(feld.get("HstIndex", 2))
        return state.folge_hst_2 if hst_idx == 2 else state.folge_hst_3
    if text_typ == "uhrzeit":
        return state.uhrzeit
    if text_typ == "statisch":
        return str(feld.get("Wagenhaelt", ""))
    return state.extra_felder.get(feld.get("nr", -1), "")


def get_canvas_size(cfg: dict) -> tuple[int, int]:
    """Ermittelt die Gesamtfläche aus allen dynamisch konfigurierten Anzeigefeldern."""
    fields = cfg.get("anzeigefelder", {})
    if not fields:
        return 1366, 768
    right = max((x + w for x, y, w, h in fields.values()), default=1366)
    bottom = max((y + h for x, y, w, h in fields.values()), default=768)
    return max(1, right), max(1, bottom)


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    cfg_path = base_dir / "custom.cfg"
    cfg = parse_cfg(cfg_path)

    pygame.init()
    pygame.font.init()

    screen_w, screen_h = get_canvas_size(cfg)
    # Ein gemeinsamer Zeichenbereich: Feld 1 und Feld 2 verwenden dieselben
    # dynamischen X/Y-Koordinaten aus [Anzeigefelder].
    screen = pygame.display.set_mode((screen_w, screen_h))
    pygame.display.set_caption(f"FIS Monitor - {cfg['meta'].get('Ort', 'Test')}")

    bg_name = cfg["grafikdateien"].get("Hintergrund", "")
    bg_path = base_dir / str(bg_name) if bg_name else None
    if bg_path and bg_path.exists():
        bg_img = pygame.image.load(str(bg_path)).convert()
    else:
        bg_img = make_fallback_bg(screen_w, screen_h)

    state = MonitorState()
    state_lock = threading.Lock()

    ads = WerbungManager(base_dir / "ads" / "werbung.ini", base_dir)
    ads.load_config()

    ibis = IBISReceiver(
        state=state,
        lock=state_lock,
        serial_port="COM11",
        baudrate=1200,
        tcp_port=4001,
        udp_port=4001,
    )
    ibis.start()

    clock = pygame.time.Clock()
    running = True

    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_h:
                        with state_lock:
                            state.wagen_haelt = not state.wagen_haelt
                            state.aktive_sequenz = 1 if state.wagen_haelt else 0
                    elif event.key == pygame.K_1:
                        with state_lock:
                            state.linie_raw = "555"
                            state.linie_e_raw = ""
                            state.ziel = "Düsseldorf Hbf"
                            state.naechste_hst = "Heinrich-Heine-Allee"
                    elif event.key == pygame.K_2:
                        with state_lock:
                            state.linie_raw = "8"
                            state.linie_e_raw = "5"
                            state.ziel = "Lummerland"
                            state.naechste_hst = "Musterhaltestelle"
                    elif event.key == pygame.K_r:
                        cfg = parse_cfg(cfg_path)
                        ads.load_config()
                        new_w, new_h = get_canvas_size(cfg)
                        if (new_w, new_h) != screen.get_size():
                            screen = pygame.display.set_mode((new_w, new_h))
                            screen_w, screen_h = new_w, new_h
                            bg_img = make_fallback_bg(screen_w, screen_h)
                            if bg_path and bg_path.exists():
                                bg_img = pygame.transform.smoothscale(
                                    pygame.image.load(str(bg_path)).convert(),
                                    (screen_w, screen_h),
                                )

            with state_lock:
                wagen_haelt = state.wagen_haelt
                aktive_seq = state.aktive_sequenz
                line_raw = state.linie_raw
                line_e_raw = state.linie_e_raw

            # Gesamte Zeichenfläche zunächst schwarz
            screen.fill((0, 0, 0))

            # Hintergrund ausschließlich auf Feld 1 zeichnen
            feld1 = cfg["anzeigefelder"].get(1)

            if feld1:
                x, y, w, h = feld1

                hintergrund = pygame.transform.smoothscale(
                    bg_img, (w, h)
                )

                screen.blit(hintergrund, (x, y))

            seq_list = cfg["sequenzen"]
            feldliste_nr = 0
            if seq_list and aktive_seq < len(seq_list):
                feldliste_nr = seq_list[aktive_seq]["feldliste"]

            aktive_felder = cfg["feldlisten"].get(feldliste_nr, [])

            # Die FIS-Zeichnung bleibt wie bisher. Werbeflächen werden danach
            # darübergelegt, damit Werbung im Hauptbildschirm sichtbar ist.
            for feld_nr in aktive_felder:
                feld = cfg["felder"].get(feld_nr)
                if not feld:
                    continue

                text_typ = str(feld.get("TextTyp", "")).lower()
                if feld_nr == 13 or text_typ == "bilder":
                    continue

                x = int(feld.get("XPosition", 0))
                y = int(feld.get("YPosition", 0))
                w = int(feld.get("Breite", 200))
                h = int(feld.get("Hoehe", 50))
                font_h = int(feld.get("Fonthoehe", max(14, h - 4)))

                if feld_nr == 12 and wagen_haelt:
                    stop_name = str(feld.get("Stopbild", "stop.png"))
                    stop_path = base_dir / stop_name
                    if stop_path.exists():
                        stop_img = pygame.transform.smoothscale(
                            pygame.image.load(str(stop_path)).convert_alpha(), (w, h)
                        )
                    else:
                        stop_img = make_fallback_stop(w, h)
                    screen.blit(stop_img, (x, y))
                    continue

                with state_lock:
                    text_value = get_field_text(feld, state, cfg["linien_umsetzung"])
                if not text_value:
                    continue

                farbe = feld.get("Farbe0", (255, 255, 255))
                if not isinstance(farbe, tuple) or len(farbe) != 3:
                    farbe = (255, 255, 255)

                font_name = cfg["grafikdateien"].get(
                    f"Font{feld.get('FontIndex', 1)}", "Arial"
                )
                font = pygame.font.SysFont(str(font_name), max(1, font_h))
                text_surface = font.render(str(text_value), True, farbe)

                if text_surface.get_width() > w and w > 0:
                    text_surface = pygame.transform.smoothscale(
                        text_surface, (w, text_surface.get_height())
                    )

                align = str(feld.get("Position", "links")).lower()
                draw_x = x + (w - text_surface.get_width()) // 2 if align == "zentriert" else x
                draw_y = y + max(0, (h - text_surface.get_height()) // 2)
                screen.blit(text_surface, (draw_x, draw_y))

            # Werbeausgabe: Modus zweiter_bildschirm nutzt Feld 2.
            # Modus hauptbildschirm nutzt Feld 1 bzw. den konfigurierten unteren Bereich.
            ads.draw(
                screen,
                line_raw=line_raw,
                line_e_raw=line_e_raw,
                display_fields=cfg.get("anzeigefelder", {}),
            )

            pygame.display.flip()
            clock.tick(30)
    finally:
        ads.close()
        ibis.stop()
        pygame.quit()


if __name__ == "__main__":
    main()
