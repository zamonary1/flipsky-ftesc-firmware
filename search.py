#!/usr/bin/env python3
"""
Поиск прошивок Cortex-M4 (AT32F403ARCT7) в бинарном файле.
Ищет таблицу векторов: первые два слова — указатель стека (в SRAM) и вектор сброса (во Flash, нечётный).
Извлекает найденные блоки в отдельные .bin файлы.
"""

import os
import sys
import struct
import argparse
import mmap
import re

# Диапазоны адресов для AT32F403ARCT7
SRAM_START = 0x20000000
SRAM_END   = 0x20038000   # 224 КБ (0x38000)
FLASH_START = 0x08000000
FLASH_END   = 0x08040000   # 256 КБ

def is_valid_stack(addr):
    """адрес в SRAM и выровнен по 8 байтам"""
    return (SRAM_START <= addr <= SRAM_END) and (addr % 8 == 0)

def is_valid_reset(addr):
    """адрес в Flash и является нечётным (Thumb mode)."""
    return (FLASH_START <= addr <= FLASH_END) and (addr & 1) == 1

def find_firmware_offsets(data):
    """
    Ищет смещения, с которых начинается таблица векторов.
    Проверяет первые два слова, а также третье (NMI) для дополнительной фильтрации.
    Возвращает список смещений.
    """
    offsets = []
    data_len = len(data)
    # Читаем по 12 байт (3 слова), чтобы проверить и NMI
    for offset in range(data_len - 12):
        # Читаем три 32-битных слова в little-endian
        try:
            sp = struct.unpack_from('<I', data, offset)[0]
            reset = struct.unpack_from('<I', data, offset + 4)[0]
            nmi = struct.unpack_from('<I', data, offset + 8)[0]
        except:
            break

        # Основные условия
        if not is_valid_stack(sp):
            continue
        if not is_valid_reset(reset):
            continue
        # Дополнительная проверка NMI (тоже должен быть адресом во Flash, нечётным)
        if not is_valid_reset(nmi):
            continue

        # Также можно убедиться, что reset != sp (обычно так и есть)
        if reset == sp:
            continue

        # Проверка, что это не пустая область (все FF или 00)
        # Проверяем первые 4 байта (стек) не равны 0xFFFFFFFF и не равны 0
        if sp == 0xFFFFFFFF or sp == 0:
            continue

        # Если все проверки пройдены, добавляем смещение
        offsets.append(offset)

    return offsets

def get_strings_with_prefix(buffer: bytes, prefix, min_len=4):
    # аналог команды strings из линукса
    # поиск последовательностей ascii
    pattern = rb'[\x20-\x7E]{' + str(min_len).encode() + rb',}'
    strings = re.findall(pattern, buffer)

    result = []
    for s in strings:
        decoded = s.decode('utf-8', errors='ignore')
        if decoded.startswith(prefix):
            result.append(decoded)
    return result

def extract_blocks(filepath, offsets, block_size, output_dir='.'):
    """
    Извлекает блоки данных из файла по указанным смещениям.
    block_size = 0 означает извлечь до конца файла.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    file_size = os.path.getsize(filepath)
    with open(filepath, 'rb') as f:
        for i, off in enumerate(offsets):
            # Определяем размер блока
            if block_size == 0:
                size = file_size - off
            else:
                size = min(block_size, file_size - off)

            f.seek(off)
            data = f.read(size)

            fw_names = get_strings_with_prefix(data, "FT85")

            if fw_names.count == 0: # строк не найдено
                fw_names = ["UNKNOWN"]

            out_name = f"firmware_{off:08X}-{'_'.join(fw_names)}.bin"
            out_path = os.path.join(output_dir, out_name)
            with open(out_path, 'wb') as out:
                out.write(data)
            print(f"[+] Извлечён блок по смещению 0x{off:08X} размером {size} байт -> {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Поиск прошивок Cortex-M4 (AT32F403ARCT7) в бинарном файле."
    )
    parser.add_argument('file', help="Путь к бинарному файлу")
    parser.add_argument('-b', '--block-size', type=int, default=0x40000,
                        help="Размер извлекаемого блока в байтах (по умолчанию 256 КБ = 0x40000). "
                             "Укажите 0, чтобы извлечь до конца файла.")
    parser.add_argument('-o', '--output-dir', default='extracted',
                        help="Папка для сохранения извлечённых файлов (по умолчанию 'extracted')")

    args = parser.parse_args()

    try:
        with open(args.file, 'rb') as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                data = mm  # data ведёт себя как bytes
                print(f"[*] Размер файла: {len(mm)} байт")

                print("[*] Поиск смещений...")
                offsets = find_firmware_offsets(mm)
                print(f"[*] Найдено потенциальных начал: {len(offsets)}")

                if offsets:
                    print("[*] Найденные смещения:")
                    for off in offsets:
                        print(f"    0x{off:08X}")

                    # Извлечение блоков
                    print("[*] Извлечение блоков...")
                    extract_blocks(args.file, offsets, args.block_size, args.output_dir)

                else:
                    print("[!] Не найдено ни одного подходящего начала прошивки.")
    except Exception as e:
        print(f"[!] Ошибка: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
