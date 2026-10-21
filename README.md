# PAEE

Módulo em C++ projetado para leitura e parsing de sentenças NMEA/GNSS provenientes de arquivos locais de log ou interfaces seriais em tempo real.

## Recursos

- **Parsing NMEA/GNSS:** Suporte às sentenças `$GPGGA`, `$GPRMC`, `$GPGLL`, `$GPVTG`, `$GPGSA`, `$GPGSV` e suas variações `$GN...`.
- **Suporte Multiplataforma:**
  - **x86 / x86_64:** Leitura local a partir de arquivo de log NMEA (`output.nmea`).
  - **ARM / AArch64:** Configuração e leitura direta de porta serial (`/dev/ttyST2` a 9600 baud, 8N1).
- **Conversão Geográfica:** Conversão automática de coordenadas NMEA (graus/minutos) para Graus Decimais.

## Requisitos

- **Compilador C++:** `g++` (GCC) ou `clang++` compatível com C++11 ou superior.
- **Ferramenta de Build:** `make`.
- **Gerador de Documentação:** `doxygen` e `graphviz` *(opcional)*.

## Compilação e Uso

Para compilar o projeto:

```bash
make
```

Para limpar os arquivos de build e o executável:

```bash
make clean
```

Para gerar a documentação Doxygen (HTML/LaTeX):
```bash
make docs
```

Para executar o programa:
```bash
build/GpsSensor
```
