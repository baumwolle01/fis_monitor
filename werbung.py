from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import configparser
import re
import time

import pygame

try:
    import cv2  # type: ignore
except ImportError:
    cv2 = None


@dataclass
class LNRRule:
    line_from: int
    line_to: int
    e_from: int
    e_to: int
    media: list[str]


def _number(value: str) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def _bool(value: str | int | bool, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "ja", "yes", "ein", "aktiv"}


class WerbungManager:
    """Lädt ads/werbung.ini und spielt passende Bild-/Videowerbung aus."""

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}

    def __init__(self, ini_path: Path, project_dir: Path):
        self.ini_path = Path(ini_path)
        self.project_dir = Path(project_dir)
        self.config = configparser.ConfigParser(interpolation=None, strict=False)
        self.config.optionxform = str
        self.rules: list[LNRRule] = []
        self.enabled = True
        self.mode = "zweiter_bildschirm"
        self.interval = 15.0
        self.transition_seconds = 1.0
        self.media_dir = self.project_dir / "ads"
        self.monitor = 2
        self.second_fullscreen = True
        self.main_enabled = False
        self.main_position = "unten"
        self.main_height = 200
        self._rule_key: tuple[int | None, int | None] | None = None
        self._media_index = 0
        self._media_path: Path | None = None
        self._image: pygame.Surface | None = None
        self._video = None
        self._video_fps = 25.0
        self._video_next_frame = 0.0
        self._video_frame: pygame.Surface | None = None
        self._media_started = time.monotonic()
        self._fade_started = self._media_started
        self._last_config_mtime = None
        self._warned_video = False

    def load_config(self) -> None:
        self.config.read(self.ini_path, encoding="utf-8")
        get = self.config.get
        self.enabled = _bool(get("Werbung", "Aktiv", fallback="1"), True)
        self.mode = get("Werbung", "Modus", fallback="zweiter_bildschirm").strip().lower()
        self.interval = max(0.1, self.config.getfloat("Werbung", "Intervall", fallback=15.0))
        self.transition_seconds = max(
            0.0, self.config.getfloat("Werbung", "Uebergangszeit", fallback=1.0)
        )
        folder = get("Werbung", "Medienordner", fallback="ads").strip()
        self.media_dir = (self.project_dir / folder).resolve()
        self.monitor = self.config.getint("WerbungBildschirm", "Monitor", fallback=2)
        self.second_fullscreen = _bool(
            get("WerbungBildschirm", "Vollbild", fallback="1"), True
        )
        self.main_enabled = _bool(
            get("WerbungHauptbildschirm", "Anzeigen", fallback="0"), False
        )
        self.main_position = get(
            "WerbungHauptbildschirm", "Position", fallback="unten"
        ).strip().lower()
        self.main_height = max(
            1, self.config.getint("WerbungHauptbildschirm", "Hoehe", fallback=200)
        )

        self.rules = []
        # ConfigParser überschreibt normalerweise doppelte Schlüssel. Da mehrere
        # LNR-Zeilen ausdrücklich erlaubt sind, sammeln wir diese zusätzlich
        # direkt aus der INI-Datei in ihrer ursprünglichen Reihenfolge.
        lnr_values: list[str] = []
        current_section = ""
        if self.ini_path.exists():
            for raw_line in self.ini_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                line_text = raw_line.strip()
                if not line_text or line_text.startswith((";", "#")):
                    continue
                if line_text.startswith("[") and line_text.endswith("]"):
                    current_section = line_text[1:-1].strip().lower()
                    continue
                if current_section == "werbungumsetzung" and "=" in line_text:
                    key_text, value_text = line_text.split("=", 1)
                    if key_text.strip().lower() == "lnr":
                        lnr_values.append(value_text.strip())

        if self.config.has_section("WerbungUmsetzung"):
            rules_enabled = _bool(self.config.get("WerbungUmsetzung", "Aktiv", fallback="1"), True)
            if rules_enabled:
                for raw in lnr_values:
                    parts = [p.strip().strip('"').strip("'") for p in raw.split(",")]
                    if len(parts) < 5:
                        print(f"[WERBUNG] Ungültige LNR-Zeile ignoriert: {raw}")
                        continue
                    try:
                        line_from, line_to, e_from, e_to = map(int, parts[:4])
                    except ValueError:
                        print(f"[WERBUNG] Ungültige Zahlen in LNR-Zeile: {raw}")
                        continue
                    media = [p for p in parts[4:] if p]
                    if media:
                        self.rules.append(LNRRule(line_from, line_to, e_from, e_to, media))

        try:
            self._last_config_mtime = self.ini_path.stat().st_mtime
        except OSError:
            self._last_config_mtime = None

        self._reset_media()
        print(
            f"[WERBUNG] Konfiguration geladen: {len(self.rules)} LNR-Regel(n), "
            f"Modus={self.mode}, Ordner={self.media_dir}"
        )

    def _check_reload(self) -> None:
        try:
            current = self.ini_path.stat().st_mtime
        except OSError:
            return
        if self._last_config_mtime is None or current != self._last_config_mtime:
            self.load_config()

    def _reset_media(self) -> None:
        self._close_video()
        self._image = None
        self._video_frame = None
        self._media_path = None
        self._media_started = time.monotonic()
        self._fade_started = self._media_started
        self._media_index = 0

    def _close_video(self) -> None:
        if self._video is not None:
            try:
                self._video.release()
            except Exception:
                pass
        self._video = None

    def _select_rule(self, line_raw: str, line_e_raw: str) -> tuple[int | None, int | None]:
        line_num = _number(line_raw)
        e_num = _number(line_e_raw)
        # Leere bzw. nicht numerische E-Linie entspricht 0, wie im MonitorState.
        if e_num is None:
            e_num = 0
        if line_num is None:
            line_num = 0
        return line_num, e_num

    def _matching_media(self, line: int, e_line: int) -> list[str]:
        for rule in self.rules:
            if (
                rule.line_from <= line <= rule.line_to
                and rule.e_from <= e_line <= rule.e_to
            ):
                return rule.media
        return []

    def _load_current_media(self, media_list: list[str]) -> None:
        self._close_video()
        self._image = None
        self._video_frame = None
        if not media_list:
            self._media_path = None
            return

        self._media_index %= len(media_list)
        raw_name = media_list[self._media_index]
        candidate = Path(raw_name)
        path = candidate if candidate.is_absolute() else self.media_dir / candidate
        path = path.resolve()
        self._media_path = path
        self._media_started = time.monotonic()
        self._fade_started = self._media_started

        if not path.exists():
            print(f"[WERBUNG] Medium nicht gefunden: {path}")
            return

        suffix = path.suffix.lower()
        if suffix in self.IMAGE_EXTENSIONS:
            try:
                self._image = pygame.image.load(str(path)).convert()
            except Exception as exc:
                print(f"[WERBUNG] Bild konnte nicht geladen werden ({path.name}): {exc}")
        elif suffix in self.VIDEO_EXTENSIONS:
            if cv2 is None:
                if not self._warned_video:
                    print("[WERBUNG] Videos benötigen OpenCV: python -m pip install opencv-python")
                    self._warned_video = True
                return
            try:
                self._video = cv2.VideoCapture(str(path))
                if not self._video.isOpened():
                    print(f"[WERBUNG] Video konnte nicht geöffnet werden: {path}")
                    self._close_video()
                    return
                fps = self._video.get(cv2.CAP_PROP_FPS)
                self._video_fps = fps if fps and fps > 1 else 25.0
                self._video_next_frame = 0.0
                self._read_video_frame()
            except Exception as exc:
                print(f"[WERBUNG] Videofehler ({path.name}): {exc}")
                self._close_video()
        else:
            print(f"[WERBUNG] Nicht unterstütztes Dateiformat: {path.name}")

    def _read_video_frame(self) -> None:
        if self._video is None:
            return
        ok, frame = self._video.read()
        if not ok:
            self._video_frame = None
            return
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame = frame.swapaxes(0, 1)
        self._video_frame = pygame.surfarray.make_surface(frame)

    def _advance_if_needed(self, media_list: list[str]) -> None:
        if not media_list:
            return
        now = time.monotonic()
        if self._media_path is None:
            self._load_current_media(media_list)
            return

        if self._video is not None:
            if now >= self._video_next_frame:
                self._read_video_frame()
                self._video_next_frame = now + 1.0 / max(1.0, self._video_fps)
            if self._video_frame is None:
                self._next_media(media_list)
            return

        # Bilder bleiben für Intervall Sekunden sichtbar. Nicht ladbare Dateien
        # werden ebenfalls nach diesem Intervall übersprungen.
        if now - self._media_started >= self.interval:
            self._next_media(media_list)

    def _next_media(self, media_list: list[str]) -> None:
        if not media_list:
            return
        self._media_index = (self._media_index + 1) % len(media_list)
        self._load_current_media(media_list)

    def _fit(self, surface: pygame.Surface, rect: pygame.Rect) -> pygame.Surface:
        if rect.width <= 0 or rect.height <= 0:
            return surface
        return pygame.transform.smoothscale(surface, (rect.width, rect.height))

    def _draw_media(self, target: pygame.Surface, rect: pygame.Rect) -> None:
        if rect.width <= 0 or rect.height <= 0:
            return
        source = self._video_frame if self._video is not None else self._image
        if source is None:
            pygame.draw.rect(target, (0, 0, 0), rect)
            return

        fitted = self._fit(source, rect)
        if self.transition_seconds > 0:
            alpha = min(255, int(255 * (time.monotonic() - self._fade_started) / self.transition_seconds))
            fitted.set_alpha(alpha)
        target.blit(fitted, rect.topleft)

    def draw(
        self,
        target: pygame.Surface,
        line_raw: str,
        line_e_raw: str,
        display_fields: dict[int, tuple[int, int, int, int]],
    ) -> None:
        self._check_reload()
        if not self.enabled:
            return

        line, e_line = self._select_rule(line_raw, line_e_raw)
        rule_key = (line, e_line)
        media_list = self._matching_media(line, e_line)
        if rule_key != self._rule_key:
            self._rule_key = rule_key
            self._reset_media()
        if not media_list:
            return
        self._advance_if_needed(media_list)

        mode = self.mode.replace("-", "_").replace(" ", "_")
        if mode in {"zweiter_bildschirm", "2", "feld_2", "feld2"}:
            field = display_fields.get(2)
            if not field:
                return
            x, y, w, h = field
            rect = pygame.Rect(x, y, w, h)
            if self.second_fullscreen:
                self._draw_media(target, rect)
            else:
                self._draw_media(target, rect)
        elif mode in {"hauptbildschirm", "haupt", "1", "feld_1", "feld1"}:
            if not self.main_enabled:
                return
            field = display_fields.get(1)
            if not field:
                return
            x, y, w, h = field
            if self.main_position in {"vollbild", "fullscreen", "ganz"}:
                rect = pygame.Rect(x, y, w, h)
            elif self.main_position == "oben":
                rect = pygame.Rect(x, y, w, min(self.main_height, h))
            elif self.main_position == "links":
                rect = pygame.Rect(x, y, min(self.main_height, w), h)
            elif self.main_position == "rechts":
                rect = pygame.Rect(x + max(0, w - self.main_height), y, min(self.main_height, w), h)
            else:  # unten (Standard)
                rect = pygame.Rect(x, y + max(0, h - self.main_height), w, min(self.main_height, h))
            self._draw_media(target, rect)

    def close(self) -> None:
        self._close_video()
