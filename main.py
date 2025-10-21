from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi import Body
from fastapi.responses import JSONResponse
import os, csv, sqlite3
from io import StringIO

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="super-secret-session-key")

# Create folders if they don't exist
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_FILE = "data.db"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# Initialize DB
def init_db():
    print("🛠️ Initializing database...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            admission_number TEXT UNIQUE NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            is_active INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    print("✅ Database initialized.")

def get_db_connection():
    return sqlite3.connect(DB_FILE)

init_db()

@app.get("/", response_class=HTMLResponse)
def student_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def handle_student_login(request: Request, username: str = Form(...)):
    print(f"🔐 Student login attempt with admission number: {username}")
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE admission_number = ?", (username,)).fetchone()
    active_link = conn.execute("SELECT url FROM links WHERE is_active = 1 LIMIT 1").fetchone()
    conn.close()
    if student:
        print("✅ Student found. Redirecting to active form.")
        if active_link:
            return RedirectResponse(url=active_link[0], status_code=302)
        return templates.TemplateResponse("student_dashboard.html", {"request": request, "msg": "No active form link set."})
    print("❌ Invalid admission number.")
    return templates.TemplateResponse("login.html", {"request": request, "msg": "Invalid Admission Number."})

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login(request: Request, msg: str = ""):
    return templates.TemplateResponse("admin_login.html", {"request": request, "msg": msg})

@app.post("/admin/login")
def handle_admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    print(f"🔐 Admin login attempt with username: {username}")
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        print("✅ Admin login successful.")
        request.session["admin"] = True
        return RedirectResponse("/admin/dashboard", status_code=303)
    print("❌ Admin login failed.")
    return RedirectResponse("/admin/login?msg=Invalid+credentials", status_code=303)

@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    if not request.session.get("admin"):
        print("🔒 Admin not logged in. Redirecting.")
        return RedirectResponse("/admin/login?msg=Please+login", status_code=303)

    conn = get_db_connection()
    students = conn.execute("SELECT * FROM students").fetchall()
    links = conn.execute("SELECT * FROM links").fetchall()
    active_link = conn.execute("SELECT * FROM links WHERE is_active = 1 LIMIT 1").fetchone()
    conn.close()
    print(f"📋 Loaded {len(students)} students, {len(links)} links.")
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "students": students,
        "links": links,
        "active_link": active_link
    })

@app.post("/admin/upload_link")
def upload_link(request: Request, name: str = Form(...), link: str = Form(...)):
    print(f"🔗 Uploading link: {name} - {link}")
    if not name.strip() or not link.strip():
        return RedirectResponse("/admin/dashboard?msg=Invalid+link+data", status_code=303)
    conn = get_db_connection()
    conn.execute("INSERT INTO links (name, url) VALUES (?, ?)", (name, link))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/set_active_link")
def set_active_link(link_id: str = Form(...)):
    print(f"🔄 Setting active link ID: {link_id}")
    if not link_id.isdigit():
        return RedirectResponse("/admin/dashboard?msg=Invalid+link+ID", status_code=303)
    conn = get_db_connection()
    conn.execute("UPDATE links SET is_active = 0")
    conn.execute("UPDATE links SET is_active = 1 WHERE id = ?", (int(link_id),))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/upload_csv")
async def upload_csv(csv_file: UploadFile = File(...)):
    print(f"📥 Uploading CSV: {csv_file.filename}")
    content = await csv_file.read()
    print("🧾 Raw CSV content:")
    print(content.decode("utf-8"))
    reader = csv.reader(StringIO(content.decode("utf-8")))
    conn = get_db_connection()
    for row in reader:
        print(f"➡️ Processing row: {row}")
        if len(row) >= 2 and row[0].strip() and row[1].strip():
            try:
                conn.execute("INSERT INTO students (name, admission_number) VALUES (?, ?)", (row[0].strip(), row[1].strip()))
                print(f"✅ Inserted student: {row[0].strip()} ({row[1].strip()})")
            except sqlite3.IntegrityError:
                print(f"⚠️ Duplicate admission number skipped: {row[1].strip()}")
                continue
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/add_student")
def add_student(name: str = Form(...), admission_number: str = Form(...)):
    print(f"➕ Adding student: {name} ({admission_number})")
    if not name.strip() or not admission_number.strip():
        print("❌ Invalid student data")
        return RedirectResponse("/admin/dashboard?msg=Invalid+student+data", status_code=303)
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO students (name, admission_number) VALUES (?, ?)", (name, admission_number))
        conn.commit()
        print("✅ Student added")
    except sqlite3.IntegrityError:
        print("⚠️ Duplicate student, not added")
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/delete_student")
def delete_student(admission_number: str = Form(...)):
    print(f"🗑️ Deleting student with admission number: {admission_number}")
    conn = get_db_connection()
    conn.execute("DELETE FROM students WHERE admission_number = ?", (admission_number,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/delete_all_students")
def delete_all_students():
    print("🧹 Deleting all students")
    conn = get_db_connection()
    conn.execute("DELETE FROM students")
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.get("/admin/logout")
def admin_logout(request: Request):
    print("🚪 Admin logged out")
    request.session.clear()
    return RedirectResponse("/admin/login?msg=Logged+out", status_code=303)

@app.post("/student_login")
async def student_login_json(data: dict = Body(...)):
    admission_number = data.get("admission_number")
    print(f"🔐 JSON Student login attempt: {admission_number}")

    if not admission_number:
        return JSONResponse({"detail": "Admission number is required."}, status_code=400)

    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE admission_number = ?", (admission_number,)).fetchone()
    active_link = conn.execute("SELECT url FROM links WHERE is_active = 1 LIMIT 1").fetchone()
    conn.close()

    if not student:
        print("❌ Invalid student login (JSON)")
        return JSONResponse({"detail": "Invalid Admission Number."}, status_code=401)

    if not active_link:
        print("❌ No active form link set")
        return JSONResponse({"detail": "No form link set."}, status_code=404)

    print("✅ Student login success (JSON), opening form...")
    return JSONResponse({"form_link": active_link[0]})

# ✅ Global error logging
@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    print(f"🔥 Unhandled error: {exc}")
    return PlainTextResponse(f"Internal Server Error: {exc}", status_code=500)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    print(f"🔥 HTTP exception: {exc.detail}")
    return PlainTextResponse(f"HTTP Error: {exc.detail}", status_code=exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"🔥 Validation error: {exc}")
    return PlainTextResponse(f"Validation Error: {exc}", status_code=422)
