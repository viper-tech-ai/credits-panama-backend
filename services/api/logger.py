import time
from aiologger import Logger
from aiologger.levels import LogLevel
from aiologger.handlers.files import AsyncFileHandler
from aiologger.formatters.base import Formatter

# Initialize the async logger
async_logger = Logger.with_default_handlers(
    name="main",
    level=LogLevel.INFO,
)

log_format = "%(asctime)s - %(levelname)s - %(message)s"
formatter = Formatter(fmt=log_format)
formatter.converter = time.gmtime

file_handler = AsyncFileHandler(filename="/home/app/logs/bot.log")
file_handler.formatter = formatter

async_logger.add_handler(file_handler)

async def shutdown_logger():
    async_logger.info("Shutting down logger")
    await async_logger.shutdown()

