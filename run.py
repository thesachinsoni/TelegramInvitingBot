import schedule

from telegram_bot import updater
from thread_svc import start_schedule, run_threaded, perform_tasks


schedule.every().second.do(perform_tasks)
run_threaded(start_schedule)

updater.start_polling()
