from tasks import TASKS, push_task_event

def job_submitted(event):
    if event.job_id in TASKS:
        TASKS[event.job_id]["status"] = "queued"
        push_task_event("queued", TASKS[event.job_id])

def job_executed(event):
    if event.job_id in TASKS:
        TASKS[event.job_id]["status"] = "completed"
        TASKS[event.job_id]["last_run"] = str(event.scheduled_run_time)
        push_task_event("complete", TASKS[event.job_id])

def job_error(event):
    if event.job_id in TASKS:
        TASKS[event.job_id]["status"] = "error"
        push_task_event("error", {
            "id": event.job_id,
            "error": str(event.exception)
        })
