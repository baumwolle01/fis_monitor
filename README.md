# fis_monitor

FIS-Monitor mit Werbeintegration
=================================

Dateien
-------
main.py - Hauptprogramm mit FIS- und Werbeausgabe
werbung.py - Werbe-Manager (LNR-Regeln, Bilder, Videos)
ads/werbung.ini - Werbekonfiguration
cfg_parser.py - CFG-Parser
monitor_state.py - IBIS-Zustand
ibis_receiver.py - IBIS-Empfang

Installation
------------
1. Dateien in deinen Projektordner kopieren.
2. Die Inhalte von ads/werbung.ini und die custom.cfg anpassen.
3. Werbebilder/-videos in den Ordner ads/ legen.
4. Abhängigkeiten installieren:

   python -m pip install pygame pyserial opencv-python

   Sollte der Fehler: "ERROR: Failed to build 'pygame' when getting requirements to build wheel" auftreten, dann statt "pygame" besser "pygame-ce" nutzen
   pyserial ist nur für COM-Port-Empfang erforderlich.
   OpenCV wird für Videowiedergabe benötigt. Videos werden ohne Ton abgespielt.

Start
-----
   python main.py

Tasten
------
ESC = Beenden
H   = Wagen hält umschalten
1   = Testlinie 555
2   = Testlinie 8 mit lE 5 (Testet die passende LNR-Regel)
R   = custom.cfg und werbung.ini neu laden

LNR-Regeln
----------
LNR = Linien-von, Linien-bis, lE-von, lE-bis, Medium1, Medium2, ...

Linie UND lE müssen im jeweiligen Bereich liegen. Regeln werden von oben
nach unten geprüft; die erste passende Regel gewinnt. LNR = 0,0,0,0 ist
keine Sonderregel, sondern trifft ausschließlich auf Linie 0 und lE 0.

Bilder bleiben für Intervall Sekunden sichtbar. Videos laufen bis zum Ende
und werden danach durch das nächste Medium ersetzt. Ein Video wird am Ende
nicht automatisch wiederholt, solange weitere Medien in der Regel folgen.

Bildschirm-/Feldhinweis
-----------------------
Die Anzeigefelder werden dynamisch aus [Anzeigefelder] gelesen. Das Programm
erstellt eine gemeinsame Zeichenfläche bis zur maximalen rechten/unteren
Feldkante und zeichnet Werbung in die Koordinaten von Feld 2 bzw. Feld 1.

Wichtig: In dieser Variante ist Monitor=2 ein dokumentierter Konfigurationswert;
die Ausgabe erfolgt innerhalb der gemeinsamen Pygame-Zeichenfläche. Für
separate native Fenster auf zwei unabhängigen Windows-Monitoren wäre eine
andere Fensterverwaltung erforderlich.

Modus:
- zweiter_bildschirm: Werbung wird auf Feld 2 gezeichnet.
- hauptbildschirm: Werbung wird nur gezeichnet, wenn Anzeigen=1; Position
  und Hoehe bestimmen den Werbebereich in Feld 1.

Datensätze
----------
Aktuell werden folgende Datensätze unterstützt:
- DS001
- DS001a
- DS003a
- DS021
- DS009
- DS003c
- DS005 (Uhrzeit)

TODO
----
- LVA Datensätze hinzufügen
- Physischer Hagen Hält Eingang (Nur SBC)
