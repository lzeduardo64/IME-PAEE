#!/usr/bin/env python3
"""
Servidor central UDP para recepção de dados de GPS.

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

Unidade física do valor: graus decimais (deg).
  latitude  = lat_raw / 1e7   (faixa válida: -90  .. +90)
  longitude = lon_raw / 1e7   (faixa válida: -180 .. +180)

Checksum: soma sem sinal de todos os bytes dos offsets 0..15, truncada
em 32 bits. (Equivale a somar os 20 bytes com o campo chksum zerado.)

Fluxo: o cliente envia pacotes continuamente (fire-and-forget); o servidor
não responde. Pacotes inválidos (tamanho/checksum/faixa) são descartados e
contabilizados.

Saídas do servidor:
  - console (texto legível ou JSON Lines, via --format)
  - arquivo CSV opcional (--log), uma linha por pacote, gravado em tempo real
======================================================================
"""

import argparse
import csv
import json
import socket
import struct
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

PACKET_FORMAT = struct.Struct("<4siiii")
PACKET_SIZE = PACKET_FORMAT.size  # 20 bytes
COORD_SCALE = 1e7
UNIT = "deg"

CSV_FIELDS = [
    "recv_time",
    "source",
    "sensor_id",
    "lat",
    "lon",
    "unit",
    "timestamp",
    "checksum_ok",
]


@dataclass
class GpsReading:
    recv_time: str  # instante de recepção no servidor (ISO 8601, UTC)
    source: str  # ip:porta do remetente
    sensor_id: str  # header do pacote
    lat: float  # graus
    lon: float  # graus
    unit: str  # sempre "deg"
    timestamp: int  # timestamp bruto enviado pelo cliente
    checksum_ok: bool


class SensorStats:
    """Estatísticas por sensor/grupo."""

    def __init__(self):
        self.valid = 0
        self.invalid = 0
        self.out_of_order = 0
        self.last_t = None
        self.first_seen = time.monotonic()
        self.last_seen = self.first_seen

    def rate(self):
        dt = self.last_seen - self.first_seen
        return self.valid / dt if dt > 0 else 0.0


def compute_checksum(data: bytes) -> int:
    """Soma dos primeiros 16 bytes, truncada em 32 bits."""
    return sum(data[:16]) & 0xFFFFFFFF


def decode_packet(data: bytes, addr) -> GpsReading:
    """Valida e converte um pacote bruto em unidades físicas.

    Levanta ValueError se o pacote for inválido.
    """
    if len(data) != PACKET_SIZE:
        raise ValueError(
            f"tamanho inválido: {len(data)} bytes (esperado {PACKET_SIZE})"
        )

    header, lat_raw, lon_raw, t, received_chksum = PACKET_FORMAT.unpack(data)
    # unpack "i" é com sinal; o checksum é uint32
    received_chksum &= 0xFFFFFFFF

    calculated = compute_checksum(data)
    checksum_ok = calculated == received_chksum
    if not checksum_ok:
        raise ValueError(
            f"checksum inválido (calculado={calculated}, recebido={received_chksum})"
        )

    lat = lat_raw / COORD_SCALE
    lon = lon_raw / COORD_SCALE
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise ValueError(f"coordenadas fora da faixa: lat={lat}, lon={lon}")

    return GpsReading(
        recv_time=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        source=f"{addr[0]}:{addr[1]}",
        sensor_id=header.decode("ascii", errors="replace").rstrip("\x00"),
        lat=lat,
        lon=lon,
        unit=UNIT,
        timestamp=t,
        checksum_ok=checksum_ok,
    )


def format_timestamp(t: int, time_unit: str) -> str:
    """Formata o timestamp conforme a unidade informada."""
    if time_unit == "raw":
        return str(t)
    try:
        seconds = t if time_unit == "s" else t / 1000.0
        iso = datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        )
        return f"{t} ({iso})"
    except (OverflowError, OSError, ValueError):
        return str(t)


def print_reading(r: GpsReading, fmt: str, time_unit: str):
    if fmt == "json":
        print(json.dumps(asdict(r), ensure_ascii=False), flush=True)
    else:
        print(f"[{r.recv_time}] de {r.source}")
        print(f" -> Sensor/Grupo: '{r.sensor_id}'")
        print(f" -> Latitude:     {r.lat:.6f} {r.unit}")
        print(f" -> Longitude:    {r.lon:.6f} {r.unit}")
        print(f" -> Timestamp:    {format_timestamp(r.timestamp, time_unit)}")
        print(" -> Status:       Checksum OK\n", flush=True)


def print_summary(stats: dict):
    print("\n[Servidor] Resumo da sessão:")
    if not stats:
        print("  Nenhum pacote recebido.")
        return
    for sensor_id, s in stats.items():
        print(
            f"  '{sensor_id}': válidos={s.valid} inválidos={s.invalid} "
            f"fora_de_ordem={s.out_of_order} taxa_média={s.rate():.2f} pkt/s"
        )


def start_server(port, host, fmt, log_path, time_unit):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))

    # Mensagens informativas vão para stderr para não poluir a saída JSON.
    print(f"[Servidor GPS] Escutando em {host}:{port}...", file=sys.stderr)
    print(
        "Aguardando pacotes UDP do cliente C++... (Ctrl+C para sair)\n", file=sys.stderr
    )

    log_file = None
    log_writer = None
    if log_path:
        new_file = not _file_has_content(log_path)
        log_file = open(log_path, "a", newline="", encoding="utf-8")
        log_writer = csv.DictWriter(log_file, fieldnames=CSV_FIELDS)
        if new_file:
            log_writer.writeheader()
            log_file.flush()
        print(f"[Servidor GPS] Gravando log CSV em '{log_path}'", file=sys.stderr)

    stats = {}  # sensor_id -> SensorStats

    try:
        while True:
            data, addr = server_socket.recvfrom(1024)

            try:
                reading = decode_packet(data, addr)
            except ValueError as err:
                # Sem sensor_id confiável: agrupa em "?" se o header não for legível
                key = (
                    data[:4].decode("ascii", errors="replace").rstrip("\x00")
                    if len(data) >= 4
                    else "?"
                )
                stats.setdefault(key, SensorStats()).invalid += 1
                print(
                    f"[Descartado] de {addr[0]}:{addr[1]} -> ERRO: {err}\n",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            s = stats.setdefault(reading.sensor_id, SensorStats())
            s.valid += 1
            s.last_seen = time.monotonic()
            if s.last_t is not None and reading.timestamp < s.last_t:
                s.out_of_order += 1
                print(
                    f"[Aviso] '{reading.sensor_id}': pacote fora de ordem "
                    f"(t={reading.timestamp} < último={s.last_t})",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                s.last_t = reading.timestamp

            print_reading(reading, fmt, time_unit)

            if log_writer:
                log_writer.writerow(asdict(reading))
                log_file.flush()  # tempo real: não deixa dados presos no buffer

    except KeyboardInterrupt:
        print("\n[Servidor] Encerrado.", file=sys.stderr)
    finally:
        server_socket.close()
        if log_file:
            log_file.close()
        print_summary(stats)


def _file_has_content(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return bool(f.read(1))
    except FileNotFoundError:
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Servidor UDP para recepção de dados GPS (protocolo binário de 20 bytes)."
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8080,
        help="Porta UDP em que o servidor irá escutar (padrão: 8080)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Endereço de escuta (padrão: 0.0.0.0)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["text", "json"],
        default="text",
        help="Formato de saída no console (padrão: text)",
    )
    parser.add_argument(
        "-l",
        "--log",
        metavar="ARQUIVO.csv",
        default=None,
        help="Grava cada leitura válida em um arquivo CSV (modo append)",
    )
    parser.add_argument(
        "--time-unit",
        choices=["raw", "s", "ms"],
        default="raw",
        help="Unidade do timestamp do cliente; 's' ou 'ms' (epoch) exibe também em ISO 8601 (padrão: raw)",
    )

    args = parser.parse_args()
    start_server(args.port, args.host, args.format, args.log, args.time_unit)
