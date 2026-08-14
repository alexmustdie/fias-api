import logging
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from clients.fias_client import FiasClient
from adapters.excel import ExcelAdapter
from core.services import AddressNormalizer #, DailyLimiter
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


tasks: Dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Запуск сервиса нормализации адресов")
    yield
    logger.info("Остановка сервиса")


app = FastAPI(title="Address Normalizer", lifespan=lifespan)

# Раздача статических файлов
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    """Главная страница"""
    return FileResponse(static_dir / "index.html")


@app.post("/api/start_process")
async def upload_excel(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """Загрузить Excel и запустить обработку в фоне"""
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Нужен Excel-файл (.xlsx или .xls)")

    # Сохраняем во временный файл
    input_dir = Path(tempfile.gettempdir()) / "address_service"
    input_dir.mkdir(exist_ok=True)

    task_id = str(uuid.uuid4())
    input_path = input_dir / f"{task_id}_input.xlsx"
    output_path = input_dir / f"{task_id}_output.xlsx"

    with open(input_path, "wb") as f:
        f.write(await file.read())

    # Создаём запись о задаче
    tasks[task_id] = {
        "status": "processing",
        "progress": 0,
        "processed": 0,
        "total": 0,
        "error": None,
        "download_url": None,
    }

    # Запускаем обработку в фоне
    background_tasks.add_task(process_file, task_id, input_path, output_path)

    return {"task_id": task_id, "status": "processing"}


async def process_file(task_id: str, input_path: Path, output_path: Path):
    """Фоновая задача обработки файла"""
    try:
        io = ExcelAdapter()
        records = io.read(str(input_path))

        tasks[task_id]["total"] = len(records)
        tasks[task_id]["processed"] = 0

        # daily_limiter = DailyLimiter(
        #     limit=settings.fias_daily_limit,
        #     counter_file=settings.fias_daily_limit_file,
        # )

        async with FiasClient() as client:
            normalizer = AddressNormalizer(
                client=client,
                concurrency=1,
                # daily_limiter=daily_limiter,
            )

            def on_progress(done: int, total: int):
                tasks[task_id]["processed"] = done
                tasks[task_id]["progress"] = int(done * 100 / total) if total else 0

            results = await normalizer.normalize_many(records, on_progress=on_progress)

        io.write(str(output_path), results)

        errors = sum(1 for r in results if r.error)
        tasks[task_id].update({
            "status": "completed",
            "progress": 100,
            "processed": len(results),
            "result": {
                "processed": len(results),
                "errors": errors,
                "results": [
                    {
                        "id": r.id,
                        "full_address": r.full_address,
                        "status": r.status,
                        "error": r.error,
                    }
                    for r in results
                ],
                "download_url": f"/api/download/{task_id}",
            },
            "download_url": f"/api/download/{task_id}",
        })

    except Exception as e:
        logger.exception(f"Ошибка в задаче {task_id}")
        tasks[task_id].update({
            "status": "failed",
            "error": str(e),
        })


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Получить статус задачи"""
    if task_id not in tasks:
        raise HTTPException(404, "Задача не найдена")
    return tasks[task_id]


@app.get("/api/download/{task_id}")
async def download_result(task_id: str):
    """Скачать результат"""
    output_path = Path(tempfile.gettempdir()) / "address_service" / f"{task_id}_output.xlsx"
    if not output_path.exists():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(
        path=output_path,
        filename=f"normalized_{task_id[:8]}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# @app.get("/api/stats")
# async def get_stats():
#     """Статистика использования (дневной лимит)."""
#     limiter = DailyLimiter(
#         limit=settings.fias_daily_limit,
#         counter_file=settings.fias_daily_limit_file,
#     )
#     used = limiter.get_today_count()
#     return {
#         "daily_limit": settings.fias_daily_limit,
#         "used_today": used,
#         "remaining": max(0, settings.fias_daily_limit - used),
#     }
