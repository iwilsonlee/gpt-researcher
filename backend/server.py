from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from backend.websocket_manager import WebSocketManager
from backend.utils import write_md_to_pdf, write_md_to_word, write_text_to_md
import time
import json
import os


class ResearchRequest(BaseModel):
    task: str
    report_type: str
    agent: str


app = FastAPI()

app.mount("/site", StaticFiles(directory="./frontend"), name="site")
app.mount("/static", StaticFiles(directory="./frontend/static"), name="static")

templates = Jinja2Templates(directory="./frontend")

manager = WebSocketManager()

# 存储文件的目录
file_directory = os.getenv("DOC_PATH", "")

# 创建存储文件的目录
if not os.path.exists(file_directory):
    os.makedirs(file_directory)


# Dynamic directory for outputs once first research is run
@app.on_event("startup")
def startup_event():
    if not os.path.isdir("outputs"):
        os.makedirs("outputs")
    app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
    app.mount("/uploads", StaticFiles(directory=file_directory), name="uploads")

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse('index.html', {"request": request, "report": None})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data.startswith("start"):
                json_data = json.loads(data[6:])
                task = json_data.get("task")
                report_type = json_data.get("report_type")
                filename = f"task_{int(time.time())}_{task}"
                report_source = json_data.get("report_source")
                if task and report_type:
                    report = await manager.start_streaming(task, report_type, report_source, websocket)
                    # Saving report as pdf
                    pdf_path = await write_md_to_pdf(report, filename)
                    # Saving report as docx
                    docx_path = await write_md_to_word(report, filename)
                    # Returning the path of saved report files
                    md_path = await write_text_to_md(report, filename)
                    await websocket.send_json({"type": "path", "output": {"pdf": pdf_path, "docx": docx_path, "md": md_path}})
                else:
                    print("Error: not enough parameters provided.")

    except WebSocketDisconnect:
        await manager.disconnect(websocket)

def save_file(file: UploadFile):
    file_path = os.path.join(file_directory, file.filename)
    with open(file_path, "wb") as f:
        f.write(file.file.read())
    return file_path

# 文件上传路由
@app.post("/upload")
async def upload_file(files: list[UploadFile] = File(...)):
    print("files:" + ''.join(str(file) for file in files))
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    uploaded_files = []
    for file in files:
        file_path = save_file(file)
        uploaded_files.append(file_path)
    return JSONResponse(content={"code": 200, "message": "Files uploaded successfully", "files": uploaded_files})

# 获取文件列表路由
@app.get("/files")
async def list_files(page: int = 1, per_page: int = 10):
    files = []
    for filename in os.listdir(file_directory):
        files.append({"name": filename})
    total_files = len(files)
    start = (page - 1) * per_page
    end = start + per_page
    return {"files": files[start:end], "totalPages": -(-total_files // per_page)}

# 删除文件路由
@app.delete("/files/{fileName}")
async def delete_file(fileName: str):
    file_path = os.path.join(file_directory, fileName)
    if os.path.exists(file_path):
        os.remove(file_path)
        return {"message": f"File '{fileName}' deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail=f"File '{fileName}' not found")
