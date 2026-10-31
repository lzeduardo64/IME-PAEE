import argparse
import socket
import struct


def start_server(port):
    HOST = "0.0.0.0"
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, port))

    print(f"[Servidor GPS] Escutando em {HOST}:{port}...")
    print("Aguardando pacotes UDP do cliente C++...\n")

    # Tamanho exato: 4 (header) + 4 (lat) + 4 (lon) + 4 (t) + 4 (chksum) = 20 bytes
    PACKET_SIZE = 20

    try:
        while True:
            data, addr = server_socket.recvfrom(1024)

            if len(data) < PACKET_SIZE:
                continue

            # Desempacota usando little-endian ('<') com 4siiii (20 bytes)
            header_bytes, lat_raw, lon_raw, t, received_chksum = struct.unpack(
                "<4siiii", data[:PACKET_SIZE]
            )
            header_str = header_bytes.decode("ascii", errors="ignore")

            # Converte de volta para float dividindo por 10^7
            lat = lat_raw / 10000000.0
            lon = lon_raw / 10000000.0

            # Recalcula o checksum (soma dos primeiros 16 bytes, zerando os últimos 4)
            chksum_zeroed = data[:16] + b"\x00\x00\x00\x00"
            calculated_chksum = sum(chksum_zeroed) & 0xFFFFFFFF

            print(f"[Recebido de {addr}]")
            print(f" -> Header:    '{header_str}'")
            print(f" -> Latitude:  {lat:.6f}")
            print(f" -> Longitude: {lon:.6f}")
            print(f" -> Timestamp: {t}")
            print(
                f" -> Checksum:  Calculado={calculated_chksum} | Recebido={received_chksum}"
            )

            if calculated_chksum == received_chksum:
                print(" -> Status:    Checksum OK!\n")
            else:
                print(" -> Status:    ERRO: Checksum inválido!\n")

    except KeyboardInterrupt:
        print("\n[Servidor] Encerrado.")
    finally:
        server_socket.close()


if __name__ == "__main__":
    # Configuração do parser de argumentos da linha de comando
    parser = argparse.ArgumentParser(
        description="Servidor UDP para recepção de dados GPS."
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8080,
        help="Porta UDP em que o servidor irá escutar (padrão: 8080)",
    )

    args = parser.parse_args()
    start_server(args.port)
