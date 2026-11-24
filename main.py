from pathlib import Path
import threading
import pygame
from cfg_parser import parse_cfg
from ibis_receiver import IBISReceiver
from monitor_state import MonitorState


def make_fallback_bg(width: int, height: int) -> pygame.Surface:
    surf = pygame.Surface((width, height))
    surf.fill((15, 22, 36))
    pygame.draw.rect(surf, (35, 50, 75), (15, 15, width - 30, height - 30), width=2)
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


def main() -> None:
    base_dir = Path(__file__).parent
    cfg_path = base_dir / "custom.cfg"
    cfg = parse_cfg(cfg_path)

    pygame.init()
    pygame.font.init()

    anzeige1 = cfg["anzeigefelder"].get(1, (0, 0, 1366, 768))
    screen_w, screen_h = anzeige1[2], anzeige1[3]
    screen = pygame.display.set_mode((screen_w, screen_h))
    pygame.display.set_caption(f"FIS Monitor - {cfg['meta'].get('Ort', 'Test')}")

    bg_name = cfg["grafikdateien"].get("Hintergrund", "")
    bg_path = base_dir / bg_name if bg_name else None
    if bg_path and bg_path.exists():
        bg_img = pygame.transform.smoothscale(
            pygame.image.load(str(bg_path)).convert(), (screen_w, screen_h)
        )
    else:
        bg_img = make_fallback_bg(screen_w, screen_h)

    state = MonitorState()
    state_lock = threading.Lock()

    # IBIS starten (bei Bedarf serial_port="COM3" oder tcp_port=4001 / udp_port=4001 setzen)
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
                        state.ziel = "Düsseldorf Hbf"
                        state.naechste_hst = "Heinrich-Heine-Allee"
                elif event.key == pygame.K_2:
                    with state_lock:
                        state.linie_raw = "721"
                        state.ziel = "Flughafen Terminal A/B/C"
                        state.naechste_hst = "Messe Ost / Stockumer Kirchstr."
                elif event.key == pygame.K_r:
                    cfg = parse_cfg(cfg_path)

        with state_lock:
            wagen_haelt = state.wagen_haelt
            aktive_seq = state.aktive_sequenz

        screen.blit(bg_img, (0, 0))

        seq_list = cfg["sequenzen"]
        feldliste_nr = 0
        if seq_list and aktive_seq < len(seq_list):
            feldliste_nr = seq_list[aktive_seq]["feldliste"]

        aktive_felder = cfg["feldlisten"].get(feldliste_nr, [])

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

            # Sonderfall: Wagen hält mit Stopbild
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
                text = get_field_text(feld, state, cfg["linien_umsetzung"])
            if not text:
                continue

            farbe = feld.get("Farbe0", (255, 255, 255))
            if not isinstance(farbe, tuple) or len(farbe) != 3:
                farbe = (255, 255, 255)

            font_name = cfg["grafikdateien"].get(f"Font{feld.get('FontIndex', 1)}", "Arial")
            font = pygame.font.SysFont(font_name, font_h)
            surf = font.render(text, True, farbe)

            if surf.get_width() > w and w > 0:
                surf = pygame.transform.smoothscale(surf, (w, surf.get_height()))

            align = str(feld.get("Position", "links")).lower()
            draw_x = x + (w - surf.get_width()) // 2 if align == "zentriert" else x
            draw_y = y + max(0, (h - surf.get_height()) // 2)
            screen.blit(surf, (draw_x, draw_y))

        pygame.display.flip()
        clock.tick(30)

    ibis.stop()
    pygame.quit()


if __name__ == "__main__":
    main()