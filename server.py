#!/usr/bin/env python3
"""
Monitor GPS com interface gráfica (Tkinter) sobre servidor central UDP.

======================================================================
PROTOCOLO DE COMUNICAÇÃO (UDP, binário, campos fixos, little-endian)
======================================================================
Cada datagrama UDP carrega exatamente UM pacote de 20 bytes:

  Offset  Tam.  Tipo       Campo      Descrição
  ------  ----  ---------  ---------  ------------------------------------
   0       4    char[4]    header     Identificador do sensor/grupo (ASCII)
   4       4    int32      lat_raw    Latitude  em graus x 10^7  (com sinal)
   8       4    int32      lon_raw    Longitude em graus x 10^7  (com sinal)
  12       4    int32      t          Timestamp (inteiro; unidade: --time-unit)
  16       4    uint32     chksum     Soma dos bytes 0..15 (mod 2^32)

  latitude  = lat_raw / 1e7   (faixa válida: -90  .. +90)
  longitude = lon_raw / 1e7   (faixa válida: -180 .. +180)

O cliente do grupo (C++, header "RATO") envia em `t` a hora UTC no formato
hhmmss (ex.: 123519 = 12:35:19); por isso o padrão de --time-unit é
"hhmmss". Para outros clientes use "s" (epoch em segundos), "ms" (epoch em
milissegundos) ou "raw" (mostra o inteiro sem interpretar).

Fluxo: o cliente envia pacotes continuamente (fire-and-forget); o servidor
não responde. Pacotes inválidos (tamanho/checksum/faixa) são descartados,
contabilizados e listados no log da interface.

Pacote "keep-alive": lat = lon = t = 0 (cliente vivo, mas ainda sem posição
GPS/fix). Ele NÃO é tratado como localização: não vai para o mapa, histórico,
CSV, estatísticas de posição nem alertas. Serve apenas para indicar que o
cliente continua ativo (indicador "Cliente" e contador de keep-alive).

======================================================================
REQUISITOS ATENDIDOS
======================================================================
  Obrigatórios
    Valor atual do sensor ........ ReadingPanel
    Histórico gráfico 30/60 s .... TimeSeriesChart (lat e lon) + ReadingHistory
    Alerta visual fora dos limites AlertBanner, marcador vermelho no mapa,
                                   linhas de limite nos gráficos, linhas
                                   destacadas no PacketLog
    Salvar log em CSV ............ CsvLogger (botão ou --log)
  Bônus
    Limites de alerta dinâmicos .. LimitsPanel -> AlertLimits.update()
    Relatório automático ......... ReportExporter (ao fechar e/ou --report-interval)
    Registro de timestamp ........ recv_time (servidor) + timestamp (sensor)
    Indicador da última atualização  rótulo "Última atualização: HH:MM:SS (há N s)"

======================================================================
ESTRUTURA (programação orientada a objetos, sem variáveis globais)
======================================================================
  Domínio / protocolo
    GpsReading, InvalidPacket   dados imutáveis de uma leitura / pacote ruim
    Heartbeat                   pacote 0,0,0: cliente vivo, sem posição
    PacketDecoder               valida e converte os 20 bytes em GpsReading
    TimestampFormatter          formata o timestamp do cliente
    AlertLimits                 limites de alerta (configuráveis em tempo real)
    SensorStats                 estatísticas acumuladas por sensor
    ReadingHistory              janela deslizante das últimas leituras
  Entrada / saída
    UdpReceiver                 thread que recebe UDP e alimenta uma fila
    CsvLogger                   gravação CSV em tempo real
    ReportExporter              relatório-resumo da sessão (.txt)
  Interface (Tkinter)
    OnlineMapPanel              mapa com tiles (requer tkintermapview)
    CanvasMapPanel              mapa offline simples (fallback, só Tkinter)
    MapPanelFactory             escolhe qual dos dois mapas usar
    TimeSeriesChart             gráfico de histórico (Canvas)
    AlertBanner, ReadingPanel, LimitsPanel, PacketLog
    GpsMonitorApp               janela principal, orquestra tudo
  Entrada do programa
    ApplicationLauncher         argumentos de linha de comando + execução
======================================================================
"""

import argparse
import csv
import math
import queue
import socket
import struct
import sys
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

METERS_PER_DEGREE = 111_320.0  # comprimento aproximado de 1° de latitude


# ======================================================================
# Domínio / protocolo
# ======================================================================
class PacketError(ValueError):
    """Pacote UDP malformado ou inválido."""


@dataclass(frozen=True)
class GpsReading:
    """Uma leitura válida de GPS, já em unidades físicas (graus)."""

    recv_epoch: float  # instante de recepção (segundos desde 1970, UTC)
    source: str  # "ip:porta" do remetente
    sensor_id: str  # header do pacote
    lat: float  # graus
    lon: float  # graus
    timestamp: int  # timestamp bruto enviado pelo cliente

    @property
    def recv_time_iso(self) -> str:
        moment = datetime.fromtimestamp(self.recv_epoch, tz=timezone.utc)
        return moment.isoformat(timespec="milliseconds")

    @property
    def recv_time_local(self) -> str:
        return datetime.fromtimestamp(self.recv_epoch).strftime("%H:%M:%S.%f")[:-3]


@dataclass(frozen=True)
class InvalidPacket:
    """Pacote descartado, com o motivo."""

    recv_epoch: float
    source: str
    sensor_key: str
    reason: str


@dataclass(frozen=True)
class Heartbeat:
    """Pacote com lat = lon = t = 0: o cliente está vivo, mas sem posição."""

    recv_epoch: float
    source: str
    sensor_id: str


class PacketDecoder:
    """Valida e decodifica o pacote binário de 20 bytes."""

    FORMAT = struct.Struct("<4siiiI")
    SIZE = FORMAT.size  # 20 bytes
    COORD_SCALE = 1e7

    @staticmethod
    def checksum(data: bytes) -> int:
        """Soma dos primeiros 16 bytes, truncada em 32 bits."""
        return sum(data[:16]) & 0xFFFFFFFF

    @classmethod
    def sensor_key(cls, data: bytes) -> str:
        """Identificador (mesmo de pacotes inválidos) para agrupar estatísticas."""
        if len(data) < 4:
            return "?"
        return data[:4].decode("ascii", errors="replace").rstrip("\x00")

    @classmethod
    def decode(cls, data: bytes, addr) -> "GpsReading | Heartbeat":
        if len(data) != cls.SIZE:
            raise PacketError(f"tamanho inválido: {len(data)} B (esperado {cls.SIZE})")

        header, lat_raw, lon_raw, stamp, received = cls.FORMAT.unpack(data)
        calculated = cls.checksum(data)
        if calculated != received:
            raise PacketError(
                f"checksum inválido (calculado={calculated}, recebido={received})"
            )

        sensor_id = header.decode("ascii", errors="replace").rstrip("\x00")
        if lat_raw == 0 and lon_raw == 0 and stamp == 0:
            return Heartbeat(
                recv_epoch=time.time(),
                source=f"{addr[0]}:{addr[1]}",
                sensor_id=sensor_id,
            )

        lat = lat_raw / cls.COORD_SCALE
        lon = lon_raw / cls.COORD_SCALE
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            raise PacketError(f"coordenadas fora da faixa: lat={lat}, lon={lon}")

        return GpsReading(
            recv_epoch=time.time(),
            source=f"{addr[0]}:{addr[1]}",
            sensor_id=sensor_id,
            lat=lat,
            lon=lon,
            timestamp=stamp,
        )


class TimestampFormatter:
    """Formata o timestamp enviado pelo cliente conforme --time-unit."""

    UNITS = ("hhmmss", "s", "ms", "raw")

    def __init__(self, unit: str):
        if unit not in self.UNITS:
            raise ValueError(f"unidade de tempo desconhecida: {unit}")
        self._unit = unit

    def format(self, stamp: int) -> str:
        if self._unit == "raw":
            return str(stamp)
        if self._unit == "hhmmss":
            return self._format_hhmmss(stamp)
        try:
            seconds = stamp if self._unit == "s" else stamp / 1000.0
            moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
            return f"{stamp} ({moment.isoformat(timespec='milliseconds')})"
        except (OverflowError, OSError, ValueError):
            return str(stamp)

    @staticmethod
    def _format_hhmmss(stamp: int) -> str:
        hours, rest = divmod(stamp, 10000)
        minutes, seconds = divmod(rest, 100)
        if stamp < 0 or hours > 23 or minutes > 59 or seconds > 59:
            return str(stamp)
        return f"{stamp:06d} ({hours:02d}:{minutes:02d}:{seconds:02d} UTC)"


class AlertLimits:
    """Limites de alerta (retângulo lat/lon) alteráveis em tempo de execução."""

    FIELDS = ("lat_min", "lat_max", "lon_min", "lon_max")

    def __init__(self, lat_min, lat_max, lon_min, lon_max):
        self.lat_min = self.lat_max = self.lon_min = self.lon_max = 0.0
        self.update(lat_min, lat_max, lon_min, lon_max)

    def update(self, lat_min, lat_max, lon_min, lon_max) -> None:
        if not (-90.0 <= lat_min < lat_max <= 90.0):
            raise ValueError("Latitude: use -90 ≤ mínimo < máximo ≤ 90.")
        if not (-180.0 <= lon_min < lon_max <= 180.0):
            raise ValueError("Longitude: use -180 ≤ mínimo < máximo ≤ 180.")
        self.lat_min, self.lat_max = lat_min, lat_max
        self.lon_min, self.lon_max = lon_min, lon_max

    def check(self, reading: GpsReading) -> list:
        """Retorna a lista (vazia se tudo OK) de violações da leitura."""
        problems = []
        if reading.lat < self.lat_min:
            problems.append(f"latitude abaixo do mínimo ({self.lat_min:.6f})")
        if reading.lat > self.lat_max:
            problems.append(f"latitude acima do máximo ({self.lat_max:.6f})")
        if reading.lon < self.lon_min:
            problems.append(f"longitude abaixo do mínimo ({self.lon_min:.6f})")
        if reading.lon > self.lon_max:
            problems.append(f"longitude acima do máximo ({self.lon_max:.6f})")
        return problems


class SensorStats:
    """Estatísticas acumuladas de um sensor/grupo.

    Média e variância são calculadas de forma incremental (algoritmo de
    Welford), sem guardar todas as amostras.
    """

    def __init__(self):
        self.valid = 0
        self.invalid = 0
        self.out_of_order = 0
        self.alerts = 0
        self.heartbeats = 0
        self.last_alive_epoch = None
        self.last_reading = None
        self.first_epoch = None
        self.lat_min = self.lon_min = math.inf
        self.lat_max = self.lon_max = -math.inf
        self._lat_mean = self._lon_mean = 0.0
        self._lat_m2 = self._lon_m2 = 0.0

    def add_valid(self, reading: GpsReading, in_alert: bool) -> None:
        previous = self.last_reading
        if previous is not None and reading.timestamp < previous.timestamp:
            self.out_of_order += 1
        if self.first_epoch is None:
            self.first_epoch = reading.recv_epoch
        self.valid += 1
        self.last_alive_epoch = reading.recv_epoch
        self.alerts += int(in_alert)
        self.last_reading = reading
        self.lat_min = min(self.lat_min, reading.lat)
        self.lat_max = max(self.lat_max, reading.lat)
        self.lon_min = min(self.lon_min, reading.lon)
        self.lon_max = max(self.lon_max, reading.lon)

        delta = reading.lat - self._lat_mean
        self._lat_mean += delta / self.valid
        self._lat_m2 += delta * (reading.lat - self._lat_mean)
        delta = reading.lon - self._lon_mean
        self._lon_mean += delta / self.valid
        self._lon_m2 += delta * (reading.lon - self._lon_mean)

    def add_invalid(self) -> None:
        self.invalid += 1

    def add_heartbeat(self, epoch: float) -> None:
        self.heartbeats += 1
        self.last_alive_epoch = epoch

    @property
    def lat_mean(self) -> float:
        return self._lat_mean if self.valid else math.nan

    @property
    def lon_mean(self) -> float:
        return self._lon_mean if self.valid else math.nan

    @property
    def lat_std(self) -> float:
        """Desvio padrão amostral da latitude (graus)."""
        return math.sqrt(self._lat_m2 / (self.valid - 1)) if self.valid > 1 else 0.0

    @property
    def lon_std(self) -> float:
        """Desvio padrão amostral da longitude (graus)."""
        return math.sqrt(self._lon_m2 / (self.valid - 1)) if self.valid > 1 else 0.0

    @property
    def north_std_m(self) -> float:
        """Desvio padrão na direção Norte-Sul, em metros."""
        return self.lat_std * METERS_PER_DEGREE

    @property
    def east_std_m(self) -> float:
        """Desvio padrão na direção Leste-Oeste, em metros."""
        if not self.valid:
            return 0.0
        cos_lat = math.cos(math.radians(self._lat_mean))
        return self.lon_std * METERS_PER_DEGREE * cos_lat

    @property
    def horizontal_std_m(self) -> float:
        """Desvio horizontal combinado (raiz da soma dos quadrados), em metros."""
        return math.hypot(self.north_std_m, self.east_std_m)

    @property
    def span_m(self) -> tuple:
        """Extensão (Norte-Sul, Leste-Oeste) da área percorrida, em metros."""
        if not self.valid:
            return (0.0, 0.0)
        cos_lat = math.cos(math.radians(self._lat_mean))
        return (
            (self.lat_max - self.lat_min) * METERS_PER_DEGREE,
            (self.lon_max - self.lon_min) * METERS_PER_DEGREE * cos_lat,
        )

    @property
    def rate(self) -> float:
        """Taxa média de pacotes válidos por segundo."""
        if self.last_reading is None or self.first_epoch is None:
            return 0.0
        elapsed = self.last_reading.recv_epoch - self.first_epoch
        return self.valid / elapsed if elapsed > 0 else 0.0


class ReadingHistory:
    """Guarda as leituras recentes de cada sensor (janela deslizante)."""

    MAX_AGE_S = 60.0

    def __init__(self):
        self._data = {}

    def add(self, reading: GpsReading) -> None:
        buffer = self._data.setdefault(reading.sensor_id, deque())
        buffer.append(reading)
        oldest_allowed = reading.recv_epoch - self.MAX_AGE_S
        while buffer and buffer[0].recv_epoch < oldest_allowed:
            buffer.popleft()

    def series(self, sensor_id: str, attribute: str, window: float, now: float):
        """Lista de (instante, valor) dos últimos `window` segundos."""
        start = now - window
        return [
            (r.recv_epoch, getattr(r, attribute))
            for r in self._data.get(sensor_id, ())
            if r.recv_epoch >= start
        ]


# ======================================================================
# Entrada / saída
# ======================================================================
class UdpReceiver(threading.Thread):
    """Recebe datagramas UDP numa thread e publica eventos numa fila.

    Os eventos são GpsReading (válidos), Heartbeat (0,0,0) ou InvalidPacket
    (descartados). A
    interface consome a fila no seu próprio laço, evitando acesso
    concorrente a widgets Tk.
    """

    def __init__(self, host: str, port: int):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.events = queue.Queue()
        self._stop_event = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.settimeout(0.5)
        try:
            self._sock.bind((host, port))
        except OSError:
            self._sock.close()
            raise

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                data, addr = self._sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            self.events.put(self._parse(data, addr))

    @staticmethod
    def _parse(data: bytes, addr):
        try:
            return PacketDecoder.decode(data, addr)
        except PacketError as err:
            return InvalidPacket(
                recv_epoch=time.time(),
                source=f"{addr[0]}:{addr[1]}",
                sensor_key=PacketDecoder.sensor_key(data),
                reason=str(err),
            )

    def stop(self) -> None:
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=2.0)
        self._sock.close()


class CsvLogger:
    """Grava cada leitura válida em CSV (modo append, em tempo real)."""

    FIELDS = [
        "recv_time",
        "source",
        "sensor_id",
        "lat",
        "lon",
        "unit",
        "timestamp",
        "alert",
    ]

    def __init__(self):
        self._file = None
        self._writer = None
        self.path = None

    @property
    def active(self) -> bool:
        return self._file is not None

    def start(self, path) -> None:
        target = Path(path)
        is_new = not target.exists() or target.stat().st_size == 0
        self._file = open(target, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.FIELDS)
        if is_new:
            self._writer.writeheader()
            self._file.flush()
        self.path = target

    def write(self, reading: GpsReading, in_alert: bool) -> None:
        if not self.active:
            return
        self._writer.writerow(
            {
                "recv_time": reading.recv_time_iso,
                "source": reading.source,
                "sensor_id": reading.sensor_id,
                "lat": f"{reading.lat:.7f}",
                "lon": f"{reading.lon:.7f}",
                "unit": "deg",
                "timestamp": reading.timestamp,
                "alert": int(in_alert),
            }
        )
        self._file.flush()

    def stop(self) -> None:
        if self._file is not None:
            self._file.close()
        self._file = self._writer = self.path = None


class ReportExporter:
    """Gera o relatório-resumo da sessão em arquivo de texto."""

    def __init__(self, directory):
        self._directory = Path(directory)

    def export(self, stats: dict, limits: AlertLimits, session_start: datetime) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        path = self._directory / f"relatorio_gps_{now:%Y%m%d_%H%M%S}.txt"

        lines = [
            "RELATÓRIO DA SESSÃO - MONITOR GPS",
            f"Início da sessão : {session_start:%Y-%m-%d %H:%M:%S}",
            f"Geração          : {now:%Y-%m-%d %H:%M:%S}",
            "Limites de alerta: "
            f"lat [{limits.lat_min:.6f}, {limits.lat_max:.6f}]  "
            f"lon [{limits.lon_min:.6f}, {limits.lon_max:.6f}] (graus)",
            "",
        ]
        if not stats:
            lines.append("Nenhum pacote recebido.")
        for sensor_id, s in sorted(stats.items()):
            lines.append(f"Sensor '{sensor_id}'")
            lines.append(
                f"  pacotes válidos={s.valid}  inválidos={s.invalid}  "
                f"fora de ordem={s.out_of_order}  em alerta={s.alerts}  "
                f"keep-alive (0,0,0)={s.heartbeats}  "
                f"taxa média={s.rate:.2f} pkt/s"
            )
            if s.valid:
                lines.append(
                    f"  latitude : mín={s.lat_min:.7f}  máx={s.lat_max:.7f}  "
                    f"média={s.lat_mean:.7f}  desvio={s.lat_std:.7f}°"
                )
                lines.append(
                    f"  longitude: mín={s.lon_min:.7f}  máx={s.lon_max:.7f}  "
                    f"média={s.lon_mean:.7f}  desvio={s.lon_std:.7f}°"
                )
                span_ns, span_ew = s.span_m
                lines.append(
                    f"  dispersão: desvio N-S={s.north_std_m:.2f} m  "
                    f"L-O={s.east_std_m:.2f} m  horizontal={s.horizontal_std_m:.2f} m  "
                    f"extensão N-S={span_ns:.2f} m  L-O={span_ew:.2f} m"
                )
                last = s.last_reading
                lines.append(
                    f"  última posição: {last.lat:.7f}, {last.lon:.7f} "
                    f"(recebida às {last.recv_time_local})"
                )
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path


# ======================================================================
# Interface: mapas
# ======================================================================
@dataclass(frozen=True)
class MapOptions:
    """Opções do mapa online."""

    tile_server: str = ""  # vazio = padrão da biblioteca (OpenStreetMap)
    cache_path: str = ""  # arquivo SQLite para guardar tiles já baixados
    user_agent: str = "GpsMonitorIME/1.0 (trabalho academico; Python tkintermapview)"


class TileProbe(threading.Thread):
    """Testa em segundo plano se o servidor de tiles responde (diagnóstico).

    `result` fica None enquanto testa, "" se OK ou o texto do erro.
    """

    DEFAULT_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

    def __init__(self, url_template: str, user_agent: str):
        super().__init__(daemon=True)
        template = url_template or self.DEFAULT_URL
        self._url = template.replace("{z}", "0").replace("{x}", "0").replace("{y}", "0")
        self._user_agent = user_agent
        self.result = None

    def run(self) -> None:
        try:
            import requests

            response = requests.get(
                self._url, headers={"User-Agent": self._user_agent}, timeout=6
            )
            self.result = (
                ""
                if response.status_code == 200
                else f"servidor respondeu HTTP {response.status_code}"
            )
        except Exception as err:  # qualquer falha de rede vira texto de diagnóstico
            self.result = f"{type(err).__name__}: {err}"[:160]


class OnlineMapPanel(ttk.Frame):
    """Mapa com tiles do OpenStreetMap (biblioteca tkintermapview)."""

    COLORS = {False: ("#1e8e3e", "#0b5d1e"), True: ("#d93025", "#8c1c13")}
    FIRST_FIX_ZOOM = 17
    description = "Mapa online (OpenStreetMap) — retângulo vermelho = limites de alerta"
    LIMIT_COLOR = "#d93025"

    def __init__(self, parent, library, limits: AlertLimits, options: MapOptions):
        super().__init__(parent)
        self._limits = limits
        self._limits_path = None
        self._map = library.TkinterMapView(
            self,
            corner_radius=0,
            database_path=options.cache_path
            if Path(options.cache_path or "").is_file()
            else None,
        )
        self._map.user_agent = (
            options.user_agent
        )  # OSM bloqueia pedidos sem identificação
        if options.tile_server:
            self._map.set_tile_server(options.tile_server, max_zoom=19)
        self._map.set_position(0.0, 0.0)
        self._map.set_zoom(2)

        self._status = tk.Label(
            self,
            text="Mapa: testando conexão com o servidor de tiles…",
            anchor="w",
            fg="#555555",
        )
        self._status.pack(side="bottom", fill="x")
        ttk.Button(self, text="Centralizar no sensor", command=self._center).pack(
            side="bottom", fill="x"
        )
        ttk.Button(
            self, text="Enquadrar limites de alerta", command=self._fit_limits
        ).pack(side="bottom", fill="x")
        self._map.pack(side="top", fill="both", expand=True)
        self._markers = {}  # sensor_id -> (marcador, em_alerta)
        self._last_position = None
        self.refresh_limits()

        self._probe = TileProbe(options.tile_server, options.user_agent)
        self._probe.start()
        self.after(500, self._check_probe)

    def _check_probe(self) -> None:
        if self._probe.result is None:
            self.after(500, self._check_probe)
        elif self._probe.result == "":
            self._status.config(text="Mapa: servidor de tiles OK", fg="#1e8e3e")
        else:
            self._status.config(
                text=f"Mapa sem tiles ({self._probe.result}). Verifique internet/proxy/firewall "
                "ou use --tile-server / --map-cache.",
                fg="#d93025",
                wraplength=600,
                justify="left",
            )

    def update_sensor(self, sensor_id: str, lat: float, lon: float, alert: bool):
        entry = self._markers.get(sensor_id)
        if entry is not None and entry[1] == alert:
            entry[0].set_position(lat, lon)
        else:
            if entry is not None:
                entry[0].delete()
            circle, outside = self.COLORS[alert]
            marker = self._map.set_marker(
                lat,
                lon,
                text=sensor_id,
                marker_color_circle=circle,
                marker_color_outside=outside,
            )
            self._markers[sensor_id] = (marker, alert)

        first_fix = self._last_position is None
        self._last_position = (lat, lon)
        if first_fix:
            self._center()
            self._map.set_zoom(self.FIRST_FIX_ZOOM)

    def _center(self) -> None:
        if self._last_position is not None:
            self._map.set_position(*self._last_position)

    def _limit_corners(self) -> list:
        lim = self._limits
        return [
            (lim.lat_min, lim.lon_min),
            (lim.lat_min, lim.lon_max),
            (lim.lat_max, lim.lon_max),
            (lim.lat_max, lim.lon_min),
            (lim.lat_min, lim.lon_min),
        ]

    def refresh_limits(self) -> None:
        """Desenha (ou atualiza) o retângulo dos limites de alerta no mapa."""
        corners = self._limit_corners()
        if self._limits_path is None:
            self._limits_path = self._map.set_path(
                corners, color=self.LIMIT_COLOR, width=3
            )
        else:
            self._limits_path.set_position_list(corners)

    def _fit_limits(self) -> None:
        lim = self._limits
        self._map.fit_bounding_box(
            (lim.lat_max, lim.lon_min), (lim.lat_min, lim.lon_max)
        )


class CanvasMapPanel(tk.Canvas):
    """Mapa offline: plano lat/lon com trilha, marcador e limites de alerta."""

    MAX_TRAIL = 300
    MIN_SPAN_DEG = 0.002
    COLORS = {False: "#1e8e3e", True: "#d93025"}

    def __init__(self, parent, limits: AlertLimits, reason: str = ""):
        super().__init__(parent, bg="#f4f1ea", highlightthickness=0)
        self.description = "Mapa offline" + (
            f" — mapa online indisponível: {reason}" if reason else ""
        )
        self._limits = limits
        self._trails = {}
        self._alerts = {}
        self.bind("<Configure>", lambda _event: self._redraw())

    def update_sensor(self, sensor_id: str, lat: float, lon: float, alert: bool):
        trail = self._trails.setdefault(sensor_id, deque(maxlen=self.MAX_TRAIL))
        if not trail or trail[-1] != (lat, lon):  # evita ponto duplicado
            trail.append((lat, lon))
        self._alerts[sensor_id] = alert
        self._redraw()

    def refresh_limits(self) -> None:
        """Redesenha o mapa com os limites de alerta atuais."""
        self._redraw()

    @staticmethod
    def _clamp(value: float) -> float:
        return max(-50000.0, min(50000.0, value))

    def _redraw(self) -> None:
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width <= 1:
            return

        if self._trails:
            lasts = [trail[-1] for trail in self._trails.values()]
            lat_c = sum(p[0] for p in lasts) / len(lasts)
            lon_c = sum(p[1] for p in lasts) / len(lasts)
            lat_span = max(p[0] for p in lasts) - min(p[0] for p in lasts)
            lon_span = max(p[1] for p in lasts) - min(p[1] for p in lasts)
        else:  # sem posição ainda: enquadra os limites de alerta
            lim = self._limits
            lat_c = (lim.lat_min + lim.lat_max) / 2
            lon_c = (lim.lon_min + lim.lon_max) / 2
            lat_span = (lim.lat_max - lim.lat_min) / 1.3
            lon_span = (lim.lon_max - lim.lon_min) / 1.3
        cos_lat = max(math.cos(math.radians(lat_c)), 0.01)
        span = max(lat_span, lon_span * cos_lat, self.MIN_SPAN_DEG) * 1.6
        scale = min(width, height) / span  # pixels por grau de latitude

        def to_px(lat, lon):
            x = width / 2 + (lon - lon_c) * scale * cos_lat
            y = height / 2 - (lat - lat_c) * scale
            return self._clamp(x), self._clamp(y)

        x0, y1 = to_px(self._limits.lat_min, self._limits.lon_min)
        x1, y0 = to_px(self._limits.lat_max, self._limits.lon_max)
        self.create_rectangle(x0, y0, x1, y1, outline="#d93025", dash=(6, 4), width=2)
        if not self._trails:
            self.create_text(
                width / 2,
                height / 2,
                text="Aguardando posição do sensor…",
                fill="#666",
            )

        for sensor_id, trail in self._trails.items():
            points = [coord for p in trail for coord in to_px(*p)]
            if len(points) >= 4:
                self.create_line(*points, fill="#7a8ba3", width=2)
            cx, cy = to_px(*trail[-1])
            color = self.COLORS[self._alerts.get(sensor_id, False)]
            self.create_oval(
                cx - 8, cy - 8, cx + 8, cy + 8, fill=color, outline="white"
            )
            self.create_text(
                cx + 12,
                cy - 12,
                text=sensor_id,
                anchor="w",
                font=("Helvetica", 10, "bold"),
            )

        meters = span * METERS_PER_DEGREE
        self.create_text(
            8,
            height - 8,
            anchor="sw",
            fill="#555",
            text=f"Largura da vista ≈ {meters:,.0f} m   |   retângulo tracejado = limites de alerta",
        )


class MapPanelFactory:
    """Usa o mapa online se 'tkintermapview' estiver instalada; senão, o offline."""

    @staticmethod
    def create(parent, limits: AlertLimits, options: MapOptions):
        try:
            import tkintermapview
        except ImportError as err:
            print(
                f"[Aviso] mapa online indisponível, usando mapa offline: {err}",
                file=sys.stderr,
            )
            return CanvasMapPanel(parent, limits, reason=str(err))
        return OnlineMapPanel(parent, tkintermapview, limits, options)


# ======================================================================
# Interface: widgets
# ======================================================================
class TimeSeriesChart(tk.Canvas):
    """Gráfico de linha (valor x tempo) dos últimos N segundos."""

    MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM = 80, 12, 24, 24
    MAX_POINTS = 600
    MIN_SPAN = 2e-5  # ≈ 2 m: evita escala "explodir" com valor constante

    def __init__(self, parent, title: str, color: str):
        super().__init__(
            parent,
            bg="white",
            height=125,
            highlightthickness=1,
            highlightbackground="#bbbbbb",
        )
        self._title = title
        self._color = color
        self._points = []
        self._now = time.time()
        self._window = 30
        self._limit_low = None
        self._limit_high = None
        self.bind("<Configure>", lambda _event: self._redraw())

    def update_data(self, points, now, window, limit_low, limit_high) -> None:
        self._points = points
        self._now = now
        self._window = window
        self._limit_low = limit_low
        self._limit_high = limit_high
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width <= 1:
            return
        left = self.MARGIN_LEFT
        right = width - self.MARGIN_RIGHT
        top = self.MARGIN_TOP
        bottom = height - self.MARGIN_BOTTOM

        self.create_text(
            left, 4, anchor="nw", text=self._title, font=("Helvetica", 10, "bold")
        )
        self.create_rectangle(left, top, right, bottom, outline="#888888")
        for i in range(5):
            x = left + (right - left) * i / 4
            seconds = -self._window + self._window * i / 4
            self.create_line(x, top, x, bottom, fill="#eeeeee")
            self.create_text(
                x, bottom + 3, anchor="n", text=f"{seconds:g}s", font=("Helvetica", 8)
            )

        if not self._points:
            self.create_text(
                (left + right) / 2,
                (top + bottom) / 2,
                text="sem dados na janela",
                fill="#888888",
            )
            return

        values = [v for _t, v in self._points]
        low, high = min(values), max(values)
        span = max(high - low, self.MIN_SPAN)
        center = (high + low) / 2
        y_min = center - span * 0.6
        y_max = center + span * 0.6

        def to_px(instant, value):
            x = left + (instant - (self._now - self._window)) / self._window * (
                right - left
            )
            y = bottom - (value - y_min) / (y_max - y_min) * (bottom - top)
            return x, y

        for i in range(3):
            value = y_min + (y_max - y_min) * i / 2
            y = bottom - (bottom - top) * i / 2
            self.create_line(left, y, right, y, fill="#eeeeee")
            self.create_text(
                left - 4, y, anchor="e", text=f"{value:.6f}", font=("Helvetica", 8)
            )

        for limit in (self._limit_low, self._limit_high):
            if limit is not None and y_min <= limit <= y_max:
                _x, y = to_px(self._now, limit)
                self.create_line(left, y, right, y, fill="#d93025", dash=(5, 3))

        step = len(self._points) // self.MAX_POINTS + 1
        sampled = self._points[::step]
        coords = [c for point in sampled for c in to_px(*point)]
        if len(coords) >= 4:
            self.create_line(*coords, fill=self._color, width=2)
        last_x, last_y = to_px(*self._points[-1])
        self.create_oval(
            last_x - 3, last_y - 3, last_x + 3, last_y + 3, fill=self._color, outline=""
        )


class AlertBanner(tk.Label):
    """Faixa colorida de estado: aguardando / dentro dos limites / ALERTA."""

    def __init__(self, parent):
        super().__init__(
            parent, font=("Helvetica", 13, "bold"), pady=6, anchor="w", padx=10
        )
        self.show_waiting()

    def show_waiting(self) -> None:
        self.config(text="Aguardando dados do sensor…", bg="#e0e0e0", fg="#333333")

    def show_no_fix(self) -> None:
        self.config(
            text="Cliente ativo, mas sem posição GPS (aguardando fix)…",
            bg="#fff3cd",
            fg="#7a5b00",
        )

    def show_ok(self) -> None:
        self.config(text="✔ Dentro dos limites", bg="#c8f0d2", fg="#0b5d1e")

    def show_alert(self, message: str) -> None:
        self.config(text=f"⚠ ALERTA: {message}", bg="#d93025", fg="white")


class ReadingPanel(ttk.LabelFrame):
    """Valor atual do sensor selecionado."""

    def __init__(self, parent, formatter: TimestampFormatter):
        super().__init__(parent, text="Valor atual do sensor", padding=8)
        self._formatter = formatter
        names = ("sensor", "lat", "lon", "timestamp", "recv")
        self._vars = {name: tk.StringVar(value="—") for name in names}

        rows = (
            ("Sensor/Grupo:", "sensor", ("Helvetica", 11, "bold")),
            ("Latitude:", "lat", ("Helvetica", 16, "bold")),
            ("Longitude:", "lon", ("Helvetica", 16, "bold")),
            ("Timestamp (sensor):", "timestamp", ("Helvetica", 10)),
            ("Recebido em:", "recv", ("Helvetica", 10)),
        )
        for row, (caption, key, font) in enumerate(rows):
            ttk.Label(self, text=caption).grid(
                row=row, column=0, sticky="w", padx=(0, 8)
            )
            ttk.Label(self, textvariable=self._vars[key], font=font).grid(
                row=row, column=1, sticky="w"
            )

    def show(self, reading: GpsReading) -> None:
        self._vars["sensor"].set(reading.sensor_id)
        self._vars["lat"].set(f"{reading.lat:+.6f} °")
        self._vars["lon"].set(f"{reading.lon:+.6f} °")
        self._vars["timestamp"].set(self._formatter.format(reading.timestamp))
        self._vars["recv"].set(f"{reading.recv_time_local}  de {reading.source}")


class LimitsPanel(ttk.LabelFrame):
    """Edição dinâmica dos limites de alerta."""

    CAPTIONS = {
        "lat_min": "Latitude mín:",
        "lat_max": "Latitude máx:",
        "lon_min": "Longitude mín:",
        "lon_max": "Longitude máx:",
    }

    def __init__(self, parent, limits: AlertLimits, on_change):
        super().__init__(parent, text="Limites de alerta (graus)", padding=8)
        self._limits = limits
        self._on_change = on_change
        self._vars = {
            name: tk.StringVar(value=f"{getattr(limits, name):.6f}")
            for name in AlertLimits.FIELDS
        }
        for index, name in enumerate(AlertLimits.FIELDS):
            row, col = divmod(index, 2)
            ttk.Label(self, text=self.CAPTIONS[name]).grid(
                row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2
            )
            ttk.Entry(self, textvariable=self._vars[name], width=12).grid(
                row=row, column=col * 2 + 1, padx=(0, 10)
            )
        ttk.Button(self, text="Aplicar limites", command=self._apply).grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0)
        )

    def _apply(self) -> None:
        try:
            values = {
                n: float(v.get().replace(",", ".")) for n, v in self._vars.items()
            }
        except ValueError:
            messagebox.showerror(
                "Limites inválidos", "Informe apenas valores numéricos.", parent=self
            )
            return
        try:
            self._limits.update(**values)
        except ValueError as err:
            messagebox.showerror("Limites inválidos", str(err), parent=self)
            return
        self._on_change()


class PacketLog(ttk.Frame):
    """Tabela com os últimos pacotes recebidos (mais recente no topo)."""

    COLUMNS = (
        ("hora", "Recebido", 100),
        ("sensor", "Sensor", 70),
        ("lat", "Latitude", 110),
        ("lon", "Longitude", 110),
        ("timestamp", "Timestamp", 120),
        ("status", "Status", 500),
    )
    MAX_ROWS = 200

    def __init__(self, parent):
        super().__init__(parent)
        self._tree = ttk.Treeview(
            self, columns=[c[0] for c in self.COLUMNS], show="headings", height=5
        )
        for key, caption, width in self.COLUMNS:
            self._tree.heading(key, text=caption)
            self._tree.column(key, width=width, anchor="w", stretch=(key == "status"))
        self._tree.tag_configure("alert", background="#fbd5d1")
        self._tree.tag_configure("invalid", background="#e6e6e6", foreground="#7a1f1f")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def add_reading(self, reading: GpsReading, problems: list) -> None:
        status = "ALERTA: " + "; ".join(problems) if problems else "OK"
        self._insert(
            (
                reading.recv_time_local,
                reading.sensor_id,
                f"{reading.lat:.6f}",
                f"{reading.lon:.6f}",
                str(reading.timestamp),
                status,
            ),
            "alert" if problems else "ok",
        )

    def add_invalid(self, packet: InvalidPacket) -> None:
        local = datetime.fromtimestamp(packet.recv_epoch).strftime("%H:%M:%S.%f")[:-3]
        self._insert(
            (
                local,
                packet.sensor_key,
                "—",
                "—",
                "—",
                f"DESCARTADO ({packet.source}): {packet.reason}",
            ),
            "invalid",
        )

    def _insert(self, values, tag: str) -> None:
        self._tree.insert("", 0, values=values, tags=(tag,))
        children = self._tree.get_children()
        for extra in children[self.MAX_ROWS :]:
            self._tree.delete(extra)


# ======================================================================
# Janela principal
# ======================================================================
class GpsMonitorApp(tk.Tk):
    """Janela principal: consome a fila do receptor e atualiza as views."""

    POLL_MS = 100
    VIEW_MS = 250
    MAX_EVENTS_PER_POLL = 500
    FRESH_S = 2.0  # até aqui: verde
    STALE_S = 5.0  # acima daqui: vermelho (sem dados)

    def __init__(
        self,
        receiver: UdpReceiver,
        limits: AlertLimits,
        time_unit: str,
        log_path,
        report_dir,
        report_interval: int,
        map_options: MapOptions,
    ):
        super().__init__()
        self.title(f"Monitor GPS — UDP {receiver.host}:{receiver.port}")
        self.geometry("1280x800")
        self.minsize(1000, 700)

        self._receiver = receiver
        self._limits = limits
        self._formatter = TimestampFormatter(time_unit)
        self._history = ReadingHistory()
        self._logger = CsvLogger()
        self._exporter = ReportExporter(report_dir)
        self._stats = {}
        self._alerts = {}
        self._session_start = datetime.now()
        self._last_valid_epoch = None
        self._last_alive_epoch = None  # qualquer pacote válido ou keep-alive
        self._report_interval = report_interval
        self._map_options = map_options

        self._selected = tk.StringVar()
        self._window = tk.IntVar(value=30)
        self._auto_report_on_exit = tk.BooleanVar(value=True)
        self._log_button_text = tk.StringVar(value="Iniciar gravação CSV…")
        self._log_status = tk.StringVar(value="Gravação CSV: desligada")

        self._build_ui()
        if log_path:
            self._start_logging(log_path)

        self.protocol("WM_DELETE_WINDOW", self._shutdown)
        self._receiver.start()
        self.after(self.POLL_MS, self._poll)
        self.after(self.VIEW_MS, self._refresh_views)
        if self._report_interval > 0:
            self.after(self._report_interval * 1000, self._periodic_report)

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(6, 6, 6, 0))
        header.pack(side="top", fill="x")
        self._banner = AlertBanner(header)
        self._banner.pack(side="left", fill="x", expand=True)
        side_info = ttk.Frame(header)
        side_info.pack(side="right", padx=(10, 0))
        self._freshness = tk.Label(
            side_info,
            text="Última atualização: —",
            font=("Helvetica", 11, "bold"),
            fg="#555555",
        )
        self._freshness.pack(anchor="e")
        self._alive = tk.Label(
            side_info,
            text="Cliente: aguardando…",
            font=("Helvetica", 10, "bold"),
            fg="#555555",
        )
        self._alive.pack(anchor="e")
        self._counters = ttk.Label(
            side_info, text="Válidos: 0   Inválidos: 0   Keep-alive: 0"
        )
        self._counters.pack(anchor="e")

        self._packet_log = PacketLog(self)
        self._packet_log.pack(side="bottom", fill="x", padx=6, pady=6)

        charts = ttk.Frame(self)
        charts.pack(side="bottom", fill="x", padx=6)
        self._lat_chart = TimeSeriesChart(charts, "Histórico — latitude (°)", "#1a73e8")
        self._lon_chart = TimeSeriesChart(
            charts, "Histórico — longitude (°)", "#e37400"
        )
        self._lat_chart.pack(side="left", fill="both", expand=True, padx=(0, 3))
        self._lon_chart.pack(side="left", fill="both", expand=True, padx=(3, 0))

        middle = ttk.PanedWindow(self, orient="horizontal")
        middle.pack(side="top", fill="both", expand=True, padx=6, pady=6)

        map_box = ttk.LabelFrame(middle, text="Última localização conhecida")
        self._map = MapPanelFactory.create(map_box, self._limits, self._map_options)
        ttk.Label(map_box, text=self._map.description, foreground="#666666").pack(
            side="bottom", anchor="w"
        )
        self._map.pack(fill="both", expand=True)
        middle.add(map_box, weight=3)

        side = ttk.Frame(middle, padding=(8, 0, 0, 0))
        middle.add(side, weight=1)
        self._build_side_panel(side)

    def _build_side_panel(self, side: ttk.Frame) -> None:
        self._reading_panel = ReadingPanel(side, self._formatter)
        self._reading_panel.pack(fill="x")

        view = ttk.LabelFrame(side, text="Visualização", padding=6)
        view.pack(fill="x", pady=4)
        ttk.Label(view, text="Sensor:").pack(side="left")
        self._sensor_box = ttk.Combobox(
            view, textvariable=self._selected, state="readonly", width=7
        )
        self._sensor_box.pack(side="left", padx=6)
        ttk.Label(view, text="Janela:").pack(side="left", padx=(8, 0))
        for seconds in (30, 60):
            ttk.Radiobutton(
                view, text=f"{seconds} s", value=seconds, variable=self._window
            ).pack(side="left", padx=3)

        LimitsPanel(side, self._limits, self._on_limits_changed).pack(fill="x")

        files = ttk.LabelFrame(side, text="Arquivos", padding=6)
        files.pack(fill="x", pady=4)
        buttons = ttk.Frame(files)
        buttons.pack(fill="x")
        ttk.Button(
            buttons, textvariable=self._log_button_text, command=self._toggle_logging
        ).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(
            buttons, text="Exportar relatório", command=self._export_report
        ).pack(side="left", fill="x", expand=True, padx=(3, 0))
        ttk.Label(
            files, textvariable=self._log_status, wraplength=380, foreground="#555555"
        ).pack(anchor="w", pady=(3, 0))
        ttk.Checkbutton(
            files,
            text="Exportar relatório ao fechar",
            variable=self._auto_report_on_exit,
        ).pack(anchor="w")

    # ------------------------------------------------------------------
    # Consumo da fila de eventos
    # ------------------------------------------------------------------
    def _poll(self) -> None:
        for _ in range(self.MAX_EVENTS_PER_POLL):
            try:
                event = self._receiver.events.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, GpsReading):
                self._handle_reading(event)
            elif isinstance(event, Heartbeat):
                self._handle_heartbeat(event)
            else:
                self._handle_invalid(event)
        self.after(self.POLL_MS, self._poll)

    def _handle_reading(self, reading: GpsReading) -> None:
        problems = self._limits.check(reading)
        in_alert = bool(problems)

        stats = self._stats.setdefault(reading.sensor_id, SensorStats())
        stats.add_valid(reading, in_alert)
        self._history.add(reading)
        self._alerts[reading.sensor_id] = problems
        self._last_valid_epoch = reading.recv_epoch
        self._last_alive_epoch = reading.recv_epoch
        self._register_sensor(reading.sensor_id)

        self._map.update_sensor(reading.sensor_id, reading.lat, reading.lon, in_alert)
        self._packet_log.add_reading(reading, problems)
        self._write_log(reading, in_alert)

    def _handle_heartbeat(self, beat: Heartbeat) -> None:
        """Pacote 0,0,0: só registra que o cliente está vivo (sem posição)."""
        self._stats.setdefault(beat.sensor_id, SensorStats()).add_heartbeat(
            beat.recv_epoch
        )
        self._last_alive_epoch = beat.recv_epoch

    def _handle_invalid(self, packet: InvalidPacket) -> None:
        self._stats.setdefault(packet.sensor_key, SensorStats()).add_invalid()
        self._packet_log.add_invalid(packet)

    def _register_sensor(self, sensor_id: str) -> None:
        known = list(self._sensor_box["values"])
        if sensor_id not in known:
            known.append(sensor_id)
            self._sensor_box["values"] = sorted(known)
        if not self._selected.get():
            self._selected.set(sensor_id)

    def _on_limits_changed(self) -> None:
        """Reavalia a última posição de cada sensor com os novos limites."""
        for sensor_id, stats in self._stats.items():
            last = stats.last_reading
            if last is not None:
                problems = self._limits.check(last)
                self._alerts[sensor_id] = problems
                self._map.update_sensor(sensor_id, last.lat, last.lon, bool(problems))
        self._map.refresh_limits()

    # ------------------------------------------------------------------
    # Atualização periódica das views
    # ------------------------------------------------------------------
    def _refresh_views(self) -> None:
        now = time.time()
        self._refresh_banner(now)
        self._refresh_freshness(now)
        self._refresh_alive(now)
        self._refresh_counters()
        self._refresh_selected_sensor(now)
        self.after(self.VIEW_MS, self._refresh_views)

    def _refresh_banner(self, now: float) -> None:
        alive_recently = (
            self._last_alive_epoch is not None
            and now - self._last_alive_epoch <= self.STALE_S
        )
        position_stale = (
            self._last_valid_epoch is None
            or now - self._last_valid_epoch > self.STALE_S
        )
        if alive_recently and position_stale:
            self._banner.show_no_fix()
            return
        active = {sid: p for sid, p in self._alerts.items() if p}
        if active:
            text = "  |  ".join(f"{sid}: {', '.join(p)}" for sid, p in active.items())
            self._banner.show_alert(text)
        elif self._alerts:
            self._banner.show_ok()
        else:
            self._banner.show_waiting()

    def _refresh_freshness(self, now: float) -> None:
        if self._last_valid_epoch is None:
            self._freshness.config(text="Última atualização: aguardando…", fg="#555555")
            return
        age = now - self._last_valid_epoch
        clock = datetime.fromtimestamp(self._last_valid_epoch).strftime("%H:%M:%S")
        if age <= self.FRESH_S:
            color, prefix = "#1e8e3e", "Última atualização"
        elif age <= self.STALE_S:
            color, prefix = "#e37400", "Última atualização"
        else:
            color, prefix = "#d93025", "SEM DADOS — última"
        self._freshness.config(text=f"{prefix}: {clock} (há {age:.1f} s)", fg=color)

    def _refresh_alive(self, now: float) -> None:
        if self._last_alive_epoch is None:
            self._alive.config(text="Cliente: aguardando…", fg="#555555")
            return
        age = now - self._last_alive_epoch
        if age <= self.FRESH_S:
            self._alive.config(text=f"Cliente: ativo (há {age:.1f} s)", fg="#1e8e3e")
        elif age <= self.STALE_S:
            self._alive.config(text=f"Cliente: ativo (há {age:.1f} s)", fg="#e37400")
        else:
            self._alive.config(
                text=f"Cliente: SEM SINAL (há {age:.1f} s)", fg="#d93025"
            )

    def _refresh_counters(self) -> None:
        valid = sum(s.valid for s in self._stats.values())
        invalid = sum(s.invalid for s in self._stats.values())
        beats = sum(s.heartbeats for s in self._stats.values())
        self._counters.config(
            text=f"Válidos: {valid}   Inválidos: {invalid}   Keep-alive: {beats}"
        )

    def _refresh_selected_sensor(self, now: float) -> None:
        sensor_id = self._selected.get()
        stats = self._stats.get(sensor_id)
        if stats is None or stats.last_reading is None:
            return
        self._reading_panel.show(stats.last_reading)
        window = self._window.get()
        self._lat_chart.update_data(
            self._history.series(sensor_id, "lat", window, now),
            now,
            window,
            self._limits.lat_min,
            self._limits.lat_max,
        )
        self._lon_chart.update_data(
            self._history.series(sensor_id, "lon", window, now),
            now,
            window,
            self._limits.lon_min,
            self._limits.lon_max,
        )

    # ------------------------------------------------------------------
    # Log CSV e relatórios
    # ------------------------------------------------------------------
    def _toggle_logging(self) -> None:
        if self._logger.active:
            self._stop_logging()
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Salvar log CSV",
            defaultextension=".csv",
            initialfile="gps_log.csv",
            filetypes=[("CSV", "*.csv"), ("Todos os arquivos", "*.*")],
        )
        if path:
            self._start_logging(path)

    def _start_logging(self, path) -> None:
        try:
            self._logger.start(path)
        except OSError as err:
            messagebox.showerror("Erro ao abrir arquivo", str(err), parent=self)
            return
        self._log_button_text.set("Parar gravação CSV")
        self._log_status.set(f"Gravando em: {self._logger.path}")

    def _stop_logging(self) -> None:
        self._logger.stop()
        self._log_button_text.set("Iniciar gravação CSV…")
        self._log_status.set("Gravação CSV: desligada")

    def _write_log(self, reading: GpsReading, in_alert: bool) -> None:
        try:
            self._logger.write(reading, in_alert)
        except OSError as err:
            self._stop_logging()
            messagebox.showerror("Falha na gravação do CSV", str(err), parent=self)

    def _export_report(self, silent: bool = False):
        try:
            path = self._exporter.export(self._stats, self._limits, self._session_start)
        except OSError as err:
            if not silent:
                messagebox.showerror(
                    "Erro ao exportar relatório", str(err), parent=self
                )
            return None
        if not silent:
            messagebox.showinfo(
                "Relatório exportado", f"Arquivo gerado:\n{path}", parent=self
            )
        return path

    def _periodic_report(self) -> None:
        if self._stats:
            self._export_report(silent=True)
        self.after(self._report_interval * 1000, self._periodic_report)

    # ------------------------------------------------------------------
    def _shutdown(self) -> None:
        self._receiver.stop()
        self._logger.stop()
        if self._auto_report_on_exit.get() and self._stats:
            self._export_report(silent=True)
        self.destroy()


# ======================================================================
# Ponto de entrada
# ======================================================================
class ApplicationLauncher:
    """Lê os argumentos de linha de comando e executa a aplicação."""

    @staticmethod
    def build_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Monitor GPS (servidor UDP + interface Tkinter)."
        )
        parser.add_argument(
            "-p", "--port", type=int, default=8080, help="porta UDP (padrão: 8080)"
        )
        parser.add_argument(
            "--host", default="0.0.0.0", help="endereço de escuta (padrão: 0.0.0.0)"
        )
        parser.add_argument(
            "-l",
            "--log",
            metavar="ARQUIVO.csv",
            default=None,
            help="já inicia gravando o CSV neste arquivo",
        )
        parser.add_argument(
            "--time-unit",
            choices=list(TimestampFormatter.UNITS),
            default="hhmmss",
            help="formato do timestamp do cliente: hhmmss = hora UTC (padrão), "
            "s/ms = epoch, raw = inteiro sem interpretar",
        )
        parser.add_argument(
            "--lat-min", type=float, default=-23.10, help="limite mínimo de latitude"
        )
        parser.add_argument(
            "--lat-max", type=float, default=-22.70, help="limite máximo de latitude"
        )
        parser.add_argument(
            "--lon-min", type=float, default=-43.80, help="limite mínimo de longitude"
        )
        parser.add_argument(
            "--lon-max", type=float, default=-43.10, help="limite máximo de longitude"
        )
        parser.add_argument(
            "--report-dir",
            default="relatorios",
            help="pasta dos relatórios (padrão: relatorios)",
        )
        parser.add_argument(
            "--report-interval",
            type=int,
            default=0,
            metavar="SEG",
            help="exporta relatório a cada SEG segundos (0 = só ao fechar)",
        )
        parser.add_argument(
            "--tile-server",
            default="",
            metavar="URL",
            help="servidor de tiles alternativo, ex.: https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        )
        parser.add_argument(
            "--map-cache",
            default="",
            metavar="ARQUIVO.db",
            help="banco SQLite de tiles PRÉ-BAIXADO com tkintermapview.OfflineLoader (somente leitura)",
        )
        return parser

    @classmethod
    def run(cls, argv=None) -> int:
        args = cls.build_parser().parse_args(argv)

        try:
            limits = AlertLimits(args.lat_min, args.lat_max, args.lon_min, args.lon_max)
        except ValueError as err:
            print(f"[Erro] limites inválidos: {err}", file=sys.stderr)
            return 2

        try:
            receiver = UdpReceiver(args.host, args.port)
        except OSError as err:
            print(
                f"[Erro] não foi possível escutar em {args.host}:{args.port}: {err}",
                file=sys.stderr,
            )
            return 1

        try:
            map_options = MapOptions(
                tile_server=args.tile_server, cache_path=args.map_cache
            )
            app = GpsMonitorApp(
                receiver,
                limits,
                args.time_unit,
                args.log,
                args.report_dir,
                args.report_interval,
                map_options,
            )
        except tk.TclError as err:
            receiver.stop()
            print(
                f"[Erro] não foi possível abrir a interface gráfica: {err}",
                file=sys.stderr,
            )
            return 1

        print(
            f"[Servidor GPS] Escutando em {args.host}:{args.port} (UDP)",
            file=sys.stderr,
        )
        app.mainloop()
        return 0


if __name__ == "__main__":
    sys.exit(ApplicationLauncher.run())
