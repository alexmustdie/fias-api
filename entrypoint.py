import asyncio
import glob
import logging
import os
import sys

from adapters.excel import ExcelAdapter
from clients.fias_client import FiasClient
from core.services import AddressNormalizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INPUT_DIR = os.getenv("NETWORK_INPUT_DIR", os.path.join(os.path.dirname(__file__), "input"))
OUTPUT_DIR = os.getenv("NETWORK_OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "output"))


def get_input_file() -> str:
    files = glob.glob(os.path.join(INPUT_DIR, "*.xlsx"))
    if not files:
        raise FileNotFoundError(f"Нет xlsx файлов в {INPUT_DIR}")
    return max(files, key=os.path.getmtime)


async def run() -> None:
    input_path = get_input_file()
    logger.info(f"Входной файл: {input_path}")

    io = ExcelAdapter()
    records = io.read(input_path)
    logger.info(f"Записей к обработке: {len(records)}")

    async with FiasClient() as client:
        normalizer = AddressNormalizer(client=client, concurrency=1)

        def on_progress(done: int, total: int) -> None:
            logger.info(f"Обработано {done}/{total}")

        results = await normalizer.normalize_many(records, on_progress=on_progress)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "result.xlsx")
    io.write(output_path, results)

    errors = sum(1 for r in results if r.error)
    logger.info(f"Готово. Обработано: {len(results)}, ошибок: {errors}")


if __name__ == "__main__":
    try:
        asyncio.run(run())
        sys.exit(0)
    except Exception:
        logger.exception("Ошибка выполнения")
        sys.exit(1)
