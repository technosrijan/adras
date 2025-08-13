from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict
import os
import uuid
from web_pipeline import fail_proof

# Import functions
from splitter import classify_from_req_id

# Import web_pipeline for web lane
from web_pipeline import web_pipeline
from file_pipeline import file_pipeline
from external_pipeline import external_pipeline

# Create the FastAPI app instance
app = FastAPI(title="Adras Data Analyst Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}

@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"message": "Adras API is running"}

@app.post("/api/")
async def analyze(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()

    uploads = []
    fieldname_map = {}
    filename_map = {}

    # Collect uploads
    for key in form.keys():
        values = form.getlist(key)
        for v in values:
            if hasattr(v, "filename") and hasattr(v, "read"):
                uploads.append(v)
                fieldname_map[key.lower()] = v
                if v.filename:
                    filename_map[v.filename.lower()] = v

    if not uploads:
        raise HTTPException(status_code=400, detail="No files uploaded. questions.txt is required")

    # Find questions.txt
    qfile = None
    if "questions.txt" in fieldname_map:
        qfile = fieldname_map["questions.txt"]
    elif "questions.txt" in filename_map:
        qfile = filename_map["questions.txt"]

    if qfile is None:
        raise HTTPException(status_code=400, detail="questions.txt is required as either the field name or the uploaded filename")

    # Read and decode
    try:
        qbytes = await qfile.read()
        questions_text = qbytes.decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read questions.txt: {e}")

    # Make temp dirs
    temp_root = os.path.join(os.getcwd(), "temp")
    os.makedirs(temp_root, exist_ok=True)
    req_id = str(uuid.uuid4())
    req_dir = os.path.join(temp_root, req_id)
    images_dir = os.path.join(req_dir, "images")
    data_dir = os.path.join(req_dir, "files")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)

    background_tasks.add_task(cleanup_temp_dir, req_dir)

    # Save questions.txt
    questions_path = os.path.join(req_dir, "questions.txt")
    with open(questions_path, "wb") as f:
        f.write(qbytes)

    # Classify task
    try:
        task_type = classify_from_req_id(req_id)
        print(f"Task Type: {task_type}")
    except Exception as e:
        print(f"Error classifying task: {e}")
        task_type = None

    images_saved = []
    data_files_saved = []

    # Save other uploads
    for key in form.keys():
        for v in form.getlist(key):
            if hasattr(v, "filename") and hasattr(v, "read") and v is not qfile:
                name = v.filename or key
                ext = name.lower().rsplit('.', 1)[-1] if '.' in name else ''
                content = await v.read()
                if ext in {"png", "jpg", "jpeg"}:
                    out_path = os.path.join(images_dir, name)
                    with open(out_path, "wb") as f:
                        f.write(content)
                    images_saved.append(out_path)
                elif ext in {"csv", "xls", "xlsx"}:
                    out_path = os.path.join(data_dir, name)
                    with open(out_path, "wb") as f:
                        f.write(content)
                    data_files_saved.append(out_path)


    # 🚀 If this is a file-type task, immediately run file lane
    if task_type and task_type.lower().startswith("file"):
        try:
            result = file_pipeline(req_id)
            return JSONResponse(content=result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"File pipeline failed: {e}")

    # 🚀 If this is a web-type task, run web lane
    if task_type and task_type.lower().startswith("web"):
        try:
            result = web_pipeline(req_id)
            return JSONResponse(content=result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Web pipeline failed: {e}")

    # 🚀 If this is an external-type task, run external lane
    if task_type and task_type.lower().startswith("external"):
        try:
            result = external_pipeline(req_id)
            return JSONResponse(content=result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"External pipeline failed: {e}")

    # Default fallback response (shouldn't normally reach if other lanes implemented)
    stub = fail_proof("",questions_text)
    return JSONResponse(content=stub)

def cleanup_temp_dir(req_dir):
    import shutil
    try:
        shutil.rmtree(req_dir)
    except Exception as e:
        print(f"Failed to delete temp dir {req_dir}: {e}")



