import base64, hashlib, hmac, json, logging, os, re, secrets, sqlite3, time, urllib.request, urllib.error, contextvars, threading
from datetime import datetime
from difflib import SequenceMatcher
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from html import escape as html_escape
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import rules, ai, benchmark, policy

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("TRUSTGATE_DB", os.path.join(HERE, "trustgate.db"))
os.makedirs(os.path.dirname(os.path.abspath(DB)), exist_ok=True)
ASSET_DIR = os.environ.get("TRUSTGATE_ASSET_DIR", os.path.join(HERE, "approved_visual_assets"))
TENANT_DB_DIR = os.environ.get("TRUSTGATE_TENANT_DB_DIR", os.path.join(HERE, "tenant_databases"))
TENANT = contextvars.ContextVar("trustgate_tenant", default=None)
DB_OVERRIDE = contextvars.ContextVar("trustgate_db_override", default=None)
TENANT_INIT_LOCK = threading.Lock()
INITIALIZED_TENANT_DBS = set()
TENANT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

def connect_db():
    """Use the current tenant's isolated database, or the configured single-tenant DB."""
    path = DB_OVERRIDE.get() or DB
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c

def asset_dir():
    """Return a tenant-isolated asset directory when host-based tenancy is enabled."""
    tenant = TENANT.get()
    base = os.environ.get("TRUSTGATE_ASSET_DIR", ASSET_DIR)
    path = os.path.join(base, tenant) if tenant else base
    os.makedirs(path, exist_ok=True)
    return path

def configured_tenant_hosts():
    raw = os.environ.get("TRUSTGATE_ORG_HOSTS", "").strip()
    if not raw:
        return {}
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("TRUSTGATE_ORG_HOSTS must be a JSON object mapping exact hostnames to tenant slugs.") from exc
    if not isinstance(mapping, dict) or not mapping:
        raise RuntimeError("TRUSTGATE_ORG_HOSTS must be a non-empty JSON object.")
    normalized = {}
    for host, slug in mapping.items():
        host = str(host).strip().lower().rstrip(".")
        slug = str(slug).strip().lower()
        if not host or "/" in host or ":" in host or not TENANT_SLUG_RE.fullmatch(slug):
            raise RuntimeError("Invalid host or tenant slug in TRUSTGATE_ORG_HOSTS.")
        if slug in normalized.values():
            raise RuntimeError("Each tenant must have a unique slug in TRUSTGATE_ORG_HOSTS.")
        normalized[host] = slug
    return normalized

def tenant_database_path(slug):
    if not TENANT_SLUG_RE.fullmatch(slug):
        raise RuntimeError("Invalid tenant slug.")
    base = os.environ.get("TRUSTGATE_TENANT_DB_DIR", TENANT_DB_DIR)
    os.makedirs(base, mode=0o700, exist_ok=True)
    return os.path.join(base, slug + ".sqlite3")
if os.environ.get("TRUSTGATE_PRODUCTION", "0") == "1" and os.environ.get("TRUSTGATE_COOKIE_SECURE", "0") != "1":
    raise RuntimeError("Production mode requires TRUSTGATE_COOKIE_SECURE=1 behind HTTPS.")
os.makedirs(ASSET_DIR, exist_ok=True)
app = FastAPI(title="TrustGate AI")
LOG = logging.getLogger("uvicorn.error")  # full upload errors go to the server console
now = lambda: datetime.now().strftime("%Y-%m-%d %H:%M")

def run(sql, a=()):
    c = connect_db()
    try:
        cur = c.execute(sql, a); rows = [dict(r) for r in cur.fetchall()]; c.commit()
        return rows, cur.lastrowid
    finally: c.close()
q = lambda sql, a=(): run(sql, a)[0]
one = lambda sql, a=(): (q(sql, a) or [None])[0]
ins = lambda sql, a=(): run(sql, a)[1]
log = lambda who, role, action, detail="": ins("INSERT INTO audit(at,actor,role,action,detail) VALUES(?,?,?,?,?)", (now(), who, role, action, detail))

def history_insert(c, fact_id, version, fact, actor, action, at):
    c.execute("""INSERT OR IGNORE INTO fact_history(fact_id,version,kind,subject,value,valid_from,valid_to,source,
                 source_quote,source_document_id,actor,action,at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (fact_id, version, fact["kind"], fact["subject"], fact["value"], fact["valid_from"], fact["valid_to"],
               fact["source"], fact.get("source_quote", ""), fact.get("source_document_id"), actor, action, at))

def audit_insert(c, actor, role, action, detail, at):
    c.execute("INSERT INTO audit(at,actor,role,action,detail) VALUES(?,?,?,?,?)", (at, actor, role, action, detail))

def hash_pw(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000).hex()
DEMO_EMAILS = {"creator@trustgate.demo": "asha", "reviewer@trustgate.demo": "ravi", "admin@trustgate.demo": "meena"}  # demo sign-in by email
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEMO_USERS = [("asha", "Asha", "creator", "Creator@123"), ("ravi", "Ravi", "reviewer", "Reviewer@123"), ("meena", "Meena", "admin", "Admin@123")]

def init(db_path=None):
    c = sqlite3.connect(db_path or DB)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, kind TEXT, subject TEXT, value TEXT, valid_from TEXT, valid_to TEXT, source TEXT);
    CREATE TABLE IF NOT EXISTS policy_documents(id INTEGER PRIMARY KEY, filename TEXT, uploaded_by TEXT, imported_at TEXT, content_hash TEXT, text_length INT);
    CREATE TABLE IF NOT EXISTS proposed_facts(id INTEGER PRIMARY KEY, policy_id INT, kind TEXT, subject TEXT, value TEXT, valid_from TEXT, valid_to TEXT, source TEXT, source_quote TEXT, status TEXT DEFAULT 'pending', matched_fact_id INT, created_at TEXT, reviewed_by TEXT, reviewed_at TEXT, decision TEXT);
    CREATE TABLE IF NOT EXISTS fact_history(id INTEGER PRIMARY KEY, fact_id INT, version INT, kind TEXT, subject TEXT, value TEXT, valid_from TEXT, valid_to TEXT, source TEXT, source_quote TEXT, source_document_id INT, actor TEXT, action TEXT, at TEXT, UNIQUE(fact_id,version));
        CREATE TABLE IF NOT EXISTS drafts(id INTEGER PRIMARY KEY, title TEXT, creator TEXT, status TEXT, created TEXT,
                                                                            review_decision TEXT, reviewer TEXT, reviewed_at TEXT, reviewed_version INT);
    CREATE TABLE IF NOT EXISTS versions(id INTEGER PRIMARY KEY, draft_id INT, n INT, content TEXT, filename TEXT, issues TEXT, author TEXT, at TEXT,
                                                                                image_checks TEXT NOT NULL DEFAULT '[]', request_id TEXT);
    CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, draft_id INT, author TEXT, role TEXT, text TEXT, at TEXT);
    CREATE TABLE IF NOT EXISTS issue_events(id INTEGER PRIMARY KEY, draft_id INT, version_id INT, creator TEXT, category TEXT, type TEXT, status TEXT, source TEXT);
    CREATE TABLE IF NOT EXISTS reviewer_feedback(id INTEGER PRIMARY KEY, draft_id INT, version_id INT, finding_index INT, reviewer TEXT, verdict TEXT, category TEXT, type TEXT, source TEXT, phrase TEXT, at TEXT, UNIQUE(version_id, finding_index, reviewer));
    CREATE TABLE IF NOT EXISTS benchmark_runs(id INTEGER PRIMARY KEY, at TEXT, samples INT, rules TEXT, rules_ai TEXT, ai_enabled INT);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT, actor TEXT, role TEXT, action TEXT, detail TEXT);
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, name TEXT UNIQUE, role TEXT, salt TEXT, pwd_hash TEXT);
    CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, username TEXT, expires REAL);
    CREATE TABLE IF NOT EXISTS visual_assets(id INTEGER PRIMARY KEY, name TEXT NOT NULL, stored_name TEXT NOT NULL,
        sha256 TEXT NOT NULL, dhash TEXT NOT NULL, uploaded_by TEXT NOT NULL, created_at TEXT NOT NULL, asset_type TEXT NOT NULL DEFAULT 'artwork');
    CREATE TABLE IF NOT EXISTS publications(id INTEGER PRIMARY KEY, draft_id INT NOT NULL, version INT NOT NULL,
        published_at TEXT NOT NULL, endpoint TEXT NOT NULL, response_code INT NOT NULL, published_by TEXT NOT NULL,
        response_summary TEXT NOT NULL DEFAULT '');
    """)
    columns = {row[1] for row in c.execute("PRAGMA table_info(facts)")}
    for name, declaration in (("source_quote", "TEXT NOT NULL DEFAULT ''"),
                              ("source_document_id", "INTEGER"), ("version", "INTEGER NOT NULL DEFAULT 1")):
        if name not in columns:
            c.execute(f"ALTER TABLE facts ADD COLUMN {name} {declaration}")
    visual_columns = {row[1] for row in c.execute("PRAGMA table_info(visual_assets)")}
    if "asset_type" not in visual_columns:
        c.execute("ALTER TABLE visual_assets ADD COLUMN asset_type TEXT NOT NULL DEFAULT 'artwork'")
    version_columns = {row[1] for row in c.execute("PRAGMA table_info(versions)")}
    if "image_checks" not in version_columns:
        c.execute("ALTER TABLE versions ADD COLUMN image_checks TEXT NOT NULL DEFAULT '[]'")
    if "request_id" not in version_columns:
        c.execute("ALTER TABLE versions ADD COLUMN request_id TEXT")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_versions_request_id ON versions(request_id) WHERE request_id IS NOT NULL")
    draft_columns = {row[1] for row in c.execute("PRAGMA table_info(drafts)")}
    for name, declaration in (("review_decision", "TEXT"), ("reviewer", "TEXT"),
                              ("reviewed_at", "TEXT"), ("reviewed_version", "INTEGER")):
        if name not in draft_columns:
            c.execute(f"ALTER TABLE drafts ADD COLUMN {name} {declaration}")
    production = os.environ.get("TRUSTGATE_PRODUCTION", "0") == "1"
    if production:
        # Production mode must never retain the built-in demo identities.
        c.execute("DELETE FROM sessions WHERE username IN ('asha','ravi','meena')")
        c.execute("DELETE FROM users WHERE username IN ('asha','ravi','meena')")
    elif not c.execute("SELECT 1 FROM users").fetchone():
        for uname, name, role, pw in DEMO_USERS:
            salt = secrets.token_bytes(16)
            c.execute("INSERT INTO users(username,name,role,salt,pwd_hash) VALUES(?,?,?,?,?)", (uname, name, role, salt.hex(), hash_pw(pw, salt)))
    if not c.execute("SELECT 1 FROM facts").fetchone():
        seed = [("discount", "all items", "15", "2026-01-01", "2026-12-31", "Promo Policy v2"),
                ("warranty", "Solara products", "12", "", "", "Product Warranty Record"),
                ("price", "SolaraPhone", "24999", "", "", "Price List 2026"),
                ("banned", "miracle", "", "", "", "Claims Policy"),
                ("term", "Solara Pro Max", "SolaraMax", "", "", "Naming Guide"),
                ("tone", "cheap", "affordable", "", "", "Tone Guide"),
                ("color", "primary", "#0B5FFF", "", "", "Brand Kit"),
                ("color", "accent", "#FFB703", "", "", "Brand Kit")]
        c.executemany("INSERT INTO facts(kind,subject,value,valid_from,valid_to,source) VALUES(?,?,?,?,?,?)", seed)
    for row in c.execute("""SELECT f.* FROM facts f LEFT JOIN fact_history h ON h.fact_id=f.id
                            WHERE h.fact_id IS NULL""").fetchall():
        fact = dict(row); history_insert(c, fact["id"], fact.get("version") or 1, fact, "system", "legacy baseline", now())
    c.commit(); c.close()
init()

@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Multi-tenant mode uses exact, administrator-configured host mappings and a
    # separate SQLite database plus asset directory for each organisation.
    tenant_token = db_token = None
    if os.environ.get("TRUSTGATE_MULTI_TENANT", "0") == "1":
        try:
            host_map = configured_tenant_hosts()
        except RuntimeError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=500)
        host = (request.url.hostname or "").lower().rstrip(".")
        slug = host_map.get(host)
        if not slug:
            return JSONResponse({"detail": "This host is not mapped to an organisation."}, status_code=421)
        path = tenant_database_path(slug)
        tenant_asset_path = os.path.join(os.environ.get("TRUSTGATE_ASSET_DIR", ASSET_DIR), slug)
        os.makedirs(tenant_asset_path, mode=0o700, exist_ok=True)
        if path not in INITIALIZED_TENANT_DBS:
            with TENANT_INIT_LOCK:
                if path not in INITIALIZED_TENANT_DBS:
                    init(path)
                    INITIALIZED_TENANT_DBS.add(path)
        tenant_token = TENANT.set(slug)
        db_token = DB_OVERRIDE.set(path)
    try:
        response = await call_next(request)
    finally:
        if db_token is not None:
            DB_OVERRIDE.reset(db_token)
        if tenant_token is not None:
            TENANT.reset(tenant_token)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if os.environ.get("TRUSTGATE_COOKIE_SECURE", "0") == "1":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

COOKIE, TTL, FAILS = "tg_session", 8 * 3600, {}
sha = lambda t: hashlib.sha256(t.encode()).hexdigest()

def current(request: Request):
    """The signed-in user, from the session cookie. Role comes from the server, never from the browser."""
    t = request.cookies.get(COOKIE)
    s = t and one("SELECT u.username, u.name, u.role, s.expires FROM sessions s JOIN users u ON u.username=s.username WHERE s.token_hash=?", (sha(t),))
    if not s or s["expires"] < time.time(): raise HTTPException(401, "Please sign in.")
    return s

def allow(*roles):
    def dep(me=Depends(current)):
        if me["role"] not in roles: raise HTTPException(403, f"The {me['role']} role can't do this.")
        return me
    return dep

def wait_left(k):
    c = FAILS.get(k); return int(c[1] - time.time()) + 1 if c and c[1] > time.time() else 0
def fail(k):
    c = FAILS.setdefault(k, [0, 0]); c[0] += 1
    if c[0] >= 5: c[0], c[1] = 0, time.time() + 60

class Login(BaseModel):
    username: str; password: str; role: str

@app.post("/api/login")
def login(b: Login, response: Response):
    k = b.username.strip().lower()[:120]; k = DEMO_EMAILS.get(k, k)
    if wait_left(k): raise HTTPException(429, f"Too many failed attempts. Try again in {wait_left(k)} seconds.")
    u = one("SELECT * FROM users WHERE username=?", (k,))
    salt = bytes.fromhex(u["salt"]) if u else b"x" * 16  # hash even for unknown users so timing does not reveal them
    good = hmac.compare_digest(hash_pw(b.password, salt), u["pwd_hash"] if u else "0" * 64) and u is not None
    if not good:
        fail(k); log(k or "-", "-", "sign-in failed", ""); raise HTTPException(401, "Incorrect username or password.")
    if u["role"] != b.role:
        raise HTTPException(403, f"This account is a {u['role'].capitalize()} account. Choose the {u['role'].capitalize()} role to sign in.")
    FAILS.pop(k, None); open_session(response, k)
    log(u["name"], u["role"], "signed in", ""); return {"username": k, "name": u["name"], "role": u["role"]}

def open_session(response, username):
    q("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    t = secrets.token_urlsafe(32); q("INSERT INTO sessions(token_hash,username,expires) VALUES(?,?,?)", (sha(t), username, time.time() + TTL))
    response.set_cookie(COOKIE, t, max_age=TTL, httponly=True, samesite="lax", secure=os.environ.get("TRUSTGATE_COOKIE_SECURE", "0") == "1", path="/")

class Register(BaseModel):
    name: str = ""; email: str = ""; password: str = ""

@app.post("/api/register")
def register(b: Register, response: Response):
    """Local demo sign-up. Production sign-up is disabled until an organisation/invitation flow is configured."""
    if os.environ.get("TRUSTGATE_PRODUCTION", "0") == "1":
        raise HTTPException(403, "Public registration is disabled in production. Ask your organisation administrator for an account.")
    name, email, pw = " ".join(b.name.split())[:40], b.email.strip().lower(), b.password
    if len(name) < 2: raise HTTPException(400, "Enter your name (at least 2 characters).")
    if len(email) > 120 or not EMAIL_RE.match(email): raise HTTPException(400, "Enter a valid email address.")
    if not 8 <= len(pw) <= 128 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise HTTPException(400, "Password must be 8 to 128 characters and include a letter and a number.")
    if email in DEMO_EMAILS or one("SELECT 1 FROM users WHERE username=?", (email,)):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    if one("SELECT 1 FROM users WHERE lower(name)=?", (name.lower(),)):
        raise HTTPException(409, "That name is already taken. Add a surname or initial.")
    salt = secrets.token_bytes(16)
    try: ins("INSERT INTO users(username,name,role,salt,pwd_hash) VALUES(?,?,?,?,?)", (email, name, "creator", salt.hex(), hash_pw(pw, salt)))
    except sqlite3.IntegrityError: raise HTTPException(409, "That email or name is already registered.")
    open_session(response, email); log(name, "creator", "registered", email)
    return {"username": email, "name": name, "role": "creator"}

@app.post("/api/logout")
def logout(request: Request, response: Response):
    t = request.cookies.get(COOKIE)
    if t:
        s = one("SELECT u.name, u.role FROM sessions s JOIN users u ON u.username=s.username WHERE s.token_hash=?", (sha(t),))
        q("DELETE FROM sessions WHERE token_hash=?", (sha(t),))
        if s: log(s["name"], s["role"], "signed out", "")
    response.delete_cookie(COOKIE, path="/"); return {}

@app.get("/api/me")
def whoami(me=Depends(current)): return {"username": me["username"], "name": me["name"], "role": me["role"], "organization": TENANT.get() or "default"}

class Fact(BaseModel):
    kind: str; subject: str; value: str = ""; valid_from: str = ""; valid_to: str = ""; source: str = ""
class PolicyUpload(BaseModel):
    filename: str; file_b64: str; include_ai: bool = False
class VisualAssetUpload(BaseModel):
    name: str; filename: str; file_b64: str; asset_type: str = "artwork"
class ProposalEdit(BaseModel):
    kind: str; subject: str; value: str = ""; valid_from: str = ""; valid_to: str = ""
class ProposalDecision(BaseModel):
    decision: str
class Sub(BaseModel):
    title: str = ""; text: str = ""; filename: str = ""; file_b64: str = ""
    request_id: str = ""; expected_version: int | None = None
class Note(BaseModel):
    text: str
class Decision(BaseModel):
    decision: str; comment: str = ""; expected_version: int | None = None

@app.get("/api/facts")
def facts(me=Depends(current)): return q("SELECT * FROM facts ORDER BY kind, id")

@app.post("/api/facts")
def add_fact(f: Fact, me=Depends(allow("admin"))):
    u = me["name"]
    if f.kind not in ("discount", "warranty", "price", "banned", "term", "tone", "color", "claim"): raise HTTPException(400, "Unknown fact type.")
    at = now(); values = f.model_dump()
    c = connect_db()
    try:
        with c:
            cur = c.execute("INSERT INTO facts(kind,subject,value,valid_from,valid_to,source) VALUES(?,?,?,?,?,?)",
                            (f.kind, f.subject, f.value, f.valid_from, f.valid_to, f.source))
            fact_id = cur.lastrowid
            fact = {**values, "source_quote": "", "source_document_id": None}
            history_insert(c, fact_id, 1, fact, u, "created", at)
            audit_insert(c, u, me["role"], "fact added", f"{f.kind}: {f.subject}", at)
    finally: c.close()
    return {"id": fact_id}

@app.put("/api/facts/{fid}")
def update_fact(fid: int, f: Fact, me=Depends(allow("admin"))):
    if f.kind not in ("discount", "warranty", "price", "banned", "term", "tone", "color", "claim"):
        raise HTTPException(400, "Unknown fact type.")
    c = connect_db(); at = now(); actor = me["name"]
    try:
        with c:
            old = c.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone()
            if not old: raise HTTPException(404, "Fact not found.")
            old = dict(old); previous_version = old.get("version") or 1
            history_insert(c, fid, previous_version, old, actor, "snapshot", at)
            version = previous_version + 1
            values = f.model_dump()
            fact_fields = ("kind", "subject", "value", "valid_from", "valid_to")
            evidence_reset = bool(old.get("source_document_id") and any(values[key] != old[key] for key in fact_fields))
            source_quote = "" if evidence_reset else old.get("source_quote", "")
            source_document_id = None if evidence_reset else old.get("source_document_id")
            if old.get("source_document_id") and not evidence_reset:
                values["source"] = old["source"]
            elif evidence_reset:
                values["source"] = "Manual update"
            new_fact = {**values, "source": values["source"], "source_quote": source_quote,
                        "source_document_id": source_document_id}
            c.execute("""UPDATE facts SET kind=?,subject=?,value=?,valid_from=?,valid_to=?,source=?,source_quote=?,
                         source_document_id=?,version=? WHERE id=?""",
                      (f.kind, f.subject, f.value, f.valid_from, f.valid_to, values["source"], source_quote,
                       source_document_id, version, fid))
            history_insert(c, fid, version, new_fact, actor, "updated", at)
            detail = f"fact {fid} v{version}: {f.kind}: {f.subject}"
            if evidence_reset: detail += "; policy evidence cleared after manual edit"
            audit_insert(c, actor, me["role"], "fact edited", detail, at)
    finally: c.close()
    return {"id": fid, "version": version}

@app.get("/api/facts/{fid}/evidence")
def fact_evidence(fid: int, me=Depends(current)):
    """Read-only source and version trail for reviewers; no mutation permissions are granted."""
    fact = one("SELECT * FROM facts WHERE id=?", (fid,))
    history = q("SELECT * FROM fact_history WHERE fact_id=? ORDER BY version", (fid,))
    if not fact and not history: raise HTTPException(404, "Approved fact evidence not found.")
    return {"fact": fact, "history": history}


@app.get("/api/facts/{fid}/history")
def fact_history(fid: int, me=Depends(allow("admin"))):
    if not one("SELECT id FROM facts WHERE id=?", (fid,)) and not one("SELECT fact_id FROM fact_history WHERE fact_id=?", (fid,)):
        raise HTTPException(404, "Fact not found.")
    return q("SELECT * FROM fact_history WHERE fact_id=? ORDER BY version", (fid,))

@app.delete("/api/facts/{fid}")
def del_fact(fid: int, me=Depends(allow("admin"))):
    u = me["name"]; c = connect_db(); at = now()
    try:
        with c:
            row = c.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone()
            if not row: raise HTTPException(404, "Fact not found.")
            row = dict(row); version = (row.get("version") or 1) + 1
            history_insert(c, fid, version, row, u, "deleted", at)
            c.execute("DELETE FROM facts WHERE id=?", (fid,))
            audit_insert(c, u, me["role"], "fact removed", str(fid), at)
    finally: c.close()
    return {}

def _normalized(value):
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

def _matching_fact(candidate):
    subject = _normalized(candidate["subject"])
    if not subject:
        return None
    matches = []
    for existing in q("SELECT id,subject FROM facts WHERE kind=?", (candidate["kind"],)):
        ratio = SequenceMatcher(None, subject, _normalized(existing["subject"])).ratio()
        if ratio >= 0.84:
            matches.append((ratio, existing["id"]))
    return max(matches)[1] if matches else None

@app.post("/api/policies/import")
def import_policy(b: PolicyUpload, me=Depends(allow("admin"))):
    filename = os.path.basename(b.filename.strip())
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in (".docx", ".pdf", ".txt"):
        raise HTTPException(400, "Upload a DOCX, PDF or TXT policy.")
    try: data = base64.b64decode(b.file_b64, validate=True)
    except Exception: raise HTTPException(400, "The upload arrived damaged. Choose the file again.")
    if not data: raise HTTPException(400, "That file is empty.")
    if len(data) > MAX_UPLOAD: raise HTTPException(400, "That file is larger than 10 MB.")
    try: text = rules.read_text(filename, data)
    except Exception:
        LOG.exception("policy file could not be read")
        raise HTTPException(400, "That policy file could not be read. Check that it is a valid DOCX, PDF or UTF-8 TXT.")
    if not text.strip(): raise HTTPException(400, "No readable text was found in that policy file.")
    candidates = policy.extract(text, filename)
    ai_state = "not requested"
    if b.include_ai:
        if not ai.available(): raise HTTPException(400, "AI extraction is not enabled. Configure the AI service or import without AI.")
        try:
            candidates.extend(policy.validate_ai(ai.extract_policy_facts(text), text, filename))
            ai_state = "completed"
        except Exception as e:
            ai_state = "failed"
            log(me["name"], me["role"], "policy AI extraction failed", f"{type(e).__name__}: {str(e)[:120]}")
    unique = []
    seen = set()
    for item in candidates:
        key = (item["kind"], _normalized(item["subject"]), item["value"], item["valid_from"], item["valid_to"])
        if key not in seen:
            seen.add(key); unique.append(item)
    at = now(); c = connect_db()
    try:
        with c:
            cur = c.execute("INSERT INTO policy_documents(filename,uploaded_by,imported_at,content_hash,text_length) VALUES(?,?,?,?,?)",
                            (filename, me["name"], at, hashlib.sha256(data).hexdigest(), len(text)))
            policy_id = cur.lastrowid
            for item in unique:
                c.execute("""INSERT INTO proposed_facts(policy_id,kind,subject,value,valid_from,valid_to,source,source_quote,
                             matched_fact_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                          (policy_id, item["kind"], item["subject"], item["value"], item["valid_from"], item["valid_to"],
                           filename, item["quote"], _matching_fact(item), at))
            audit_insert(c, me["name"], me["role"], "policy imported", f"{filename}: {len(unique)} proposals", at)
    finally: c.close()
    return {"id": policy_id, "filename": filename, "proposals": len(unique), "ai": ai_state}

@app.get("/api/policy-proposals")
def policy_proposals(status: str = "pending", me=Depends(allow("admin"))):
    if status not in ("pending", "approved", "rejected", "all"):
        raise HTTPException(400, "Unknown proposal status.")
    where = "" if status == "all" else "WHERE p.status=?"
    args = () if status == "all" else (status,)
    return q(f"""SELECT p.*, d.filename, f.subject matched_subject, f.value matched_value
                 FROM proposed_facts p JOIN policy_documents d ON d.id=p.policy_id
                 LEFT JOIN facts f ON f.id=p.matched_fact_id {where} ORDER BY p.id DESC""", args)

@app.put("/api/policy-proposals/{proposal_id}")
def edit_proposal(proposal_id: int, b: ProposalEdit, me=Depends(allow("admin"))):
    row = one("SELECT * FROM proposed_facts WHERE id=? AND status='pending'", (proposal_id,))
    if not row: raise HTTPException(404, "Pending proposal not found.")
    candidate = {**b.model_dump(), "quote": row["source_quote"]}
    validated = policy.validate_ai([candidate], row["source_quote"], row["source"])
    if len(validated) != 1: raise HTTPException(400, "The edited fact is invalid or its evidence does not match the source quote.")
    value = validated[0]; match = _matching_fact(value)
    q("""UPDATE proposed_facts SET kind=?,subject=?,value=?,valid_from=?,valid_to=?,matched_fact_id=? WHERE id=?""",
      (value["kind"], value["subject"], value["value"], value["valid_from"], value["valid_to"], match, proposal_id))
    log(me["name"], me["role"], "proposal edited", f"proposal {proposal_id}: {value['kind']} {value['subject']}")
    return {"id": proposal_id, "matched_fact_id": match}

@app.post("/api/policy-proposals/{proposal_id}/decision")
def decide_proposal(proposal_id: int, b: ProposalDecision, me=Depends(allow("admin"))):
    if b.decision not in ("add", "update", "reject"):
        raise HTTPException(400, "Choose add, update, or reject.")
    c = connect_db(); at = now(); actor = me["name"]
    try:
        with c:
            row = c.execute("SELECT * FROM proposed_facts WHERE id=? AND status='pending'", (proposal_id,)).fetchone()
            if not row: raise HTTPException(404, "Pending proposal not found.")
            row = dict(row); fact_id = None
            if b.decision != "reject":
                candidate = {"kind": row["kind"], "subject": row["subject"], "value": row["value"],
                             "valid_from": row["valid_from"], "valid_to": row["valid_to"],
                             "quote": row["source_quote"]}
                if len(policy.validate_ai([candidate], row["source_quote"], row["source"])) != 1:
                    raise HTTPException(400, "This proposal is invalid or its evidence no longer matches.")
                if b.decision == "update":
                    if not row["matched_fact_id"]: raise HTTPException(400, "This proposal has no suggested existing fact to update.")
                    old = c.execute("SELECT * FROM facts WHERE id=?", (row["matched_fact_id"],)).fetchone()
                    if not old: raise HTTPException(409, "The matched fact no longer exists. Review the proposal again.")
                    old = dict(old); fact_id = old["id"]; version = (old.get("version") or 1) + 1
                    history_insert(c, fact_id, old.get("version") or 1, old, actor, "snapshot", at)
                    c.execute("""UPDATE facts SET kind=?,subject=?,value=?,valid_from=?,valid_to=?,source=?,source_quote=?,
                                 source_document_id=?,version=? WHERE id=?""",
                              (row["kind"], row["subject"], row["value"], row["valid_from"], row["valid_to"], row["source"],
                               row["source_quote"], row["policy_id"], version, fact_id))
                    active = {**candidate, "source": row["source"], "source_quote": row["source_quote"],
                              "source_document_id": row["policy_id"]}
                    history_insert(c, fact_id, version, active, actor, "updated from policy", at)
                else:
                    cur = c.execute("""INSERT INTO facts(kind,subject,value,valid_from,valid_to,source,source_quote,source_document_id,version)
                                       VALUES(?,?,?,?,?,?,?,?,1)""",
                                    (row["kind"], row["subject"], row["value"], row["valid_from"], row["valid_to"], row["source"],
                                     row["source_quote"], row["policy_id"]))
                    fact_id = cur.lastrowid
                    active = {**candidate, "source": row["source"], "source_quote": row["source_quote"],
                              "source_document_id": row["policy_id"]}
                    history_insert(c, fact_id, 1, active, actor, "created from policy", at)
            status = "rejected" if b.decision == "reject" else "approved"
            c.execute("UPDATE proposed_facts SET status=?,reviewed_by=?,reviewed_at=?,decision=? WHERE id=?",
                      (status, actor, at, b.decision, proposal_id))
            audit_insert(c, actor, me["role"], f"policy proposal {status}", f"proposal {proposal_id}; fact {fact_id or '-'}", at)
    finally: c.close()
    return {"status": status, "fact_id": fact_id}

MAX_UPLOAD = 10 * 1024 * 1024
IMG = (".png", ".jpg", ".jpeg")

def check_text(text, fx):
    """Rules first, then (if a key is set) the AI layer. AI adds review-only findings and never blocks a check."""
    issues = rules.check(text, fx, include_verified=True)
    if ai.available():
        try:
            issues = sorted(issues + ai.find_missed_claims(text, fx, issues), key=lambda i: i["start"])
            if len(text) > ai.MAX_CHARS * ai.MAX_CHUNKS: log("AI", "system", "ai check partial", f"only the first {ai.MAX_CHARS * ai.MAX_CHUNKS} characters were reviewed by AI; rules covered all of it")
        except Exception as e: log("AI", "system", "ai check skipped", f"{type(e).__name__}: {str(e)[:100]}")
    return issues

def visual_dhash(data):
    """64-bit difference hash for approximate whole-image duplicate screening, not logo-in-layout detection."""
    from PIL import Image
    import io
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("L").resize((9, 8))
        pixels = list(image.get_flattened_data())
    bits = [pixels[row * 9 + col] > pixels[row * 9 + col + 1] for row in range(8) for col in range(8)]
    return "".join("1" if bit else "0" for bit in bits)


@app.get("/api/visual-assets")
def list_visual_assets(me=Depends(allow("admin"))):
    return q("SELECT id,name,sha256,uploaded_by,created_at,asset_type FROM visual_assets ORDER BY id DESC")


@app.post("/api/visual-assets")
def add_visual_asset(asset: VisualAssetUpload, me=Depends(allow("admin"))):
    name = " ".join(asset.name.split())[:100]
    asset_type = (asset.asset_type or "artwork").strip().lower()
    if asset_type not in ("logo", "artwork"):
        raise HTTPException(400, "Asset type must be logo or artwork.")
    filename = asset.filename.lower()
    if len(name) < 2: raise HTTPException(400, "Give the approved asset a descriptive name.")
    if not filename.endswith((".png", ".jpg", ".jpeg")): raise HTTPException(400, "Approved visual references must be PNG or JPG images.")
    if len(asset.file_b64) > 4 * ((MAX_UPLOAD + 2) // 3): raise HTTPException(400, "The image must be 10 MB or smaller.")
    try: data = base64.b64decode(asset.file_b64, validate=True)
    except Exception: raise HTTPException(400, "The image upload is malformed.")
    if not data or len(data) > MAX_UPLOAD: raise HTTPException(400, "The image must be non-empty and 10 MB or smaller.")
    if not rules.is_image_signature(data): raise HTTPException(400, "The file is not a valid PNG or JPEG image.")
    try: rules.load_image(data)
    except rules.ImageValidationError as exc: raise HTTPException(400, str(exc))
    except rules.ImageTooLargeError as exc: raise HTTPException(400, str(exc))
    digest = hashlib.sha256(data).hexdigest()
    if one("SELECT id FROM visual_assets WHERE sha256=?", (digest,)):
        raise HTTPException(409, "This exact image is already registered as an approved visual reference.")
    stored = secrets.token_hex(16) + (".png" if data.startswith(b"\x89PNG") else ".jpg")
    path = os.path.join(asset_dir(), stored)
    with open(path, "wb") as handle: handle.write(data)
    try:
        asset_id = ins("INSERT INTO visual_assets(name,stored_name,sha256,dhash,uploaded_by,created_at,asset_type) VALUES(?,?,?,?,?,?,?)",
                       (name, stored, digest, visual_dhash(data), me["name"], now(), asset_type))
    except Exception:
        try: os.remove(path)
        except OSError: pass
        raise
    log(me["name"], me["role"], "approved visual reference added", f"asset {asset_id}: {name}")
    return {"id": asset_id, "name": name, "asset_type": asset_type}


@app.delete("/api/visual-assets/{asset_id}")
def delete_visual_asset(asset_id: int, me=Depends(allow("admin"))):
    row = one("SELECT * FROM visual_assets WHERE id=?", (asset_id,))
    if not row: raise HTTPException(404, "Visual reference not found.")
    q("DELETE FROM visual_assets WHERE id=?", (asset_id,))
    try: os.remove(os.path.join(asset_dir(), row["stored_name"]))
    except OSError: pass
    log(me["name"], me["role"], "approved visual reference removed", f"asset {asset_id}: {row['name']}")
    return {"deleted": asset_id}


def match_embedded_logo(poster_bytes, logo_refs):
    """Search for approved logo templates inside a larger poster at multiple scales.

    This is a screening aid, not robust logo recognition. It reports the best
    normalized template score and location for human confirmation.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    poster_arr = np.frombuffer(poster_bytes, dtype=np.uint8)
    poster = cv2.imdecode(poster_arr, cv2.IMREAD_GRAYSCALE)
    if poster is None:
        return None
    ph, pw = poster.shape[:2]
    if max(ph, pw) > 1800:
        scale = 1800 / max(ph, pw)
        poster = cv2.resize(poster, (max(1, int(pw * scale)), max(1, int(ph * scale))), interpolation=cv2.INTER_AREA)
        ph, pw = poster.shape[:2]
    best_result = None
    for ref in logo_refs:
        path = os.path.join(asset_dir(), ref["stored_name"])
        try:
            logo = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if logo is None:
                continue
            lh, lw = logo.shape[:2]
            # Skip full-canvas/oversized reference art; logo references should be cropped tightly.
            if lw < 12 or lh < 8 or lw > pw or lh > ph:
                continue
            # Search reasonable logo sizes; cap attempts for predictable latency.
            scales = [0.12 + i * (0.76 / 19) for i in range(20)]
            scales = sorted(scales, key=lambda sc: abs((lw * sc) / max(pw, 1) - 0.22))
            for sc in scales:
                tw, th = int(lw * sc), int(lh * sc)
                if tw < 10 or th < 8 or tw >= pw or th >= ph:
                    continue
                template = cv2.resize(logo, (tw, th), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_CUBIC)
                result = cv2.matchTemplate(poster, template, cv2.TM_CCOEFF_NORMED)
                _, score, _, loc = cv2.minMaxLoc(result)
                score = float(score) if score == score else 0.0
                if best_result is None or score > best_result[1]:
                    best_result = (ref, score, (int(loc[0]), int(loc[1]), tw, th))
        except (OSError, cv2.error):
            continue
    return best_result


def check_image_upload(name, data, fx):
    """Run bounded local checks, then optional vision transcription, with explicit availability reporting."""
    try: issues, checks, info = rules.inspect_image(data, fx)
    except rules.ImageTooLargeError as e: raise HTTPException(400, str(e))
    except rules.ImageValidationError as e: raise HTTPException(400, str(e))
    except ImportError:
        LOG.exception("image check needs a missing package")
        raise HTTPException(500, "The server is missing the Pillow package for image checks. Run: pip install -r requirements.txt, then restart the server.")
    refs = q("SELECT id,name,dhash,stored_name,asset_type FROM visual_assets ORDER BY id")
    if not refs:
        checks.append({"name": "Approved visual reference", "status": "unavailable", "detail": "No approved reference images are configured."})
    else:
        current_hash = visual_dhash(data)
        artwork_refs = [ref for ref in refs if ref.get("asset_type", "artwork") == "artwork"]
        if artwork_refs:
            matches = [(sum(a != b for a, b in zip(current_hash, ref["dhash"])), ref) for ref in artwork_refs]
            distance, best = min(matches, key=lambda pair: pair[0])
            similarity = round((64 - distance) / 64 * 100)
            if distance <= 6:
                checks.append({"name": "Approved visual reference", "status": "passed", "detail": f"Whole-image perceptual match to '{best['name']}' ({similarity}% hash similarity). This indicates similar artwork, not complete brand compliance."})
            else:
                checks.append({"name": "Approved visual reference", "status": "review", "detail": f"No near-duplicate whole-image match found. Closest artwork: '{best['name']}' ({similarity}% hash similarity)."})
        logo_refs = [ref for ref in refs if ref.get("asset_type") == "logo"]
        if logo_refs:
            logo_result = match_embedded_logo(data, logo_refs)
            if logo_result is None:
                checks.append({"name": "Embedded approved logo", "status": "unavailable", "detail": "OpenCV logo matching is unavailable; embedded logo presence was not assessed."})
            else:
                logo, score, box = logo_result
                if score >= 0.82:
                    checks.append({"name": "Embedded approved logo", "status": "passed", "detail": f"Likely match to approved logo '{logo['name']}' (template similarity {score:.0%}); detected region x={box[0]}, y={box[1]}, width={box[2]}, height={box[3]}. Confirm visually because image matching can produce false positives."})
                elif score >= 0.58:
                    checks.append({"name": "Embedded approved logo", "status": "review", "detail": f"Possible but uncertain match to approved logo '{logo['name']}' (template similarity {score:.0%}). Confirm logo presence and appearance manually."})
                else:
                    checks.append({"name": "Embedded approved logo", "status": "warning", "detail": f"No confident match to the {len(logo_refs)} approved logo reference(s) was found (best score {score:.0%}). The logo may be absent, altered, too small, or obscured; a human should inspect the image."})
    head, text, why = f"[Image: {name}]", "", ""
    if not ai.available():
        why = "Vision/OCR is not configured; visible image text was not checked."
        checks.append({"name": "Visible text extraction", "status": "unavailable", "detail": why})
    else:
        try:
            text = ai.read_image_text(data)
            truncated = len(text) > ai.MAX_CHARS
            if truncated:
                text = text[:ai.MAX_CHARS]
                why = "Vision transcription was truncated; all visible image text was not checked."
            elif not text:
                why = "Vision returned no readable text; visible image text is not verified."
            extraction_status = "review" if truncated else "completed" if text else "no_text_returned"
            extraction_detail = (f"Vision transcription exceeded {ai.MAX_CHARS} characters and was truncated; inspect the original image."
                                 if truncated else "Vision returned a transcription. Related findings require visual confirmation."
                                 if text else "Vision returned no readable text; this does not establish that the image contains no text.")
            checks.append({"name": "Visible text extraction", "status": extraction_status, "detail": extraction_detail})
        except Exception as e:
            log("AI", "system", "image text skipped", type(e).__name__)
            why = "Vision/OCR failed; visible image text was not checked."
            checks.append({"name": "Visible text extraction", "status": "failed", "detail": why})
    if why:
        issues.append(dict(type="Image text not read", category="Asset rule issues", phrase="image", start=0, end=0, detected="not read",
                   approved="text extraction unavailable", source="Asset rules", reason=why + " A reviewer should read it.", suggestion=None,
                   status="needs_review", classification="Needs human review"))
    if not text: return head, issues, checks
    shift = len(head) + 1  # the stored copy is "[Image: name]" + newline + the text read from the picture
    for i in check_text(text, fx):
        i["status"] = "needs_review"
        i["classification"] = "Needs human review"
        i["reason"] = "Confirm the vision transcription in the original image. " + i["reason"]
        i["suggestion"] = None
        i["by"] = "Vision"
        i["start"] += shift; i["end"] += shift; issues.append(i)
    return head + "\n" + text, issues, checks

def run_check(s):
    fx = q("SELECT * FROM facts")
    if s.file_b64:
        n = s.filename.lower()
        if not n.endswith(IMG + (".txt", ".docx", ".pdf")):
            raise HTTPException(400, "Upload a TXT, DOCX, PDF, PNG or JPG file." + (" Old .doc files are not supported: open it in Word and Save as .docx." if n.endswith(".doc") else ""))
        if len(s.file_b64) > 4 * ((MAX_UPLOAD + 2) // 3):
            raise HTTPException(400, "That file is larger than 10 MB. Compress it or split it and retry.")
        try: data = base64.b64decode(s.file_b64)
        except Exception: raise HTTPException(400, "The upload arrived damaged. Choose the file again.")
        if not data: raise HTTPException(400, "That file is empty.")
        if len(data) > MAX_UPLOAD: raise HTTPException(400, "That file is larger than 10 MB. Compress it or split it and retry.")
        if rules.is_image_signature(data) and not n.endswith(IMG):
            raise HTTPException(400, "This file contains PNG or JPEG image data. Upload it with a .png, .jpg or .jpeg extension.")
        if n.endswith(IMG):
            if not rules.is_image_signature(data):
                raise HTTPException(400, "The file contents are not a supported PNG or JPEG image.")
            return check_image_upload(s.filename, data, fx)
        try: text = rules.read_text(n, data)
        except Exception:
            LOG.exception("file could not be read")
            raise HTTPException(400, "That PDF couldn't be read. It may be damaged or password-protected. Re-save it without a password and retry." if n.endswith(".pdf")
                                else "That file couldn't be read. A DOCX must be a real Word .docx file (not a renamed .doc or PDF). Re-save it as .docx or .txt and retry.")
        if not text.strip():
            raise HTTPException(400, "This PDF has no selectable text (it may be a scan). Export its pages as PNG or JPG and upload those instead." if n.endswith(".pdf")
                                else "No readable text was found in that file. Text inside images or text boxes can't be read: paste the copy instead.")
    else: text = s.text
    if not text.strip(): raise HTTPException(400, "Add some text or a file to check.")
    return text, check_text(text, fx), []

def validate_request_id(request_id):
    if request_id and not re.fullmatch(r"[0-9a-fA-F-]{36}", request_id):
        raise HTTPException(400, "Request ID must be a UUID.")

def find_duplicate_submission(c, request_id, creator):
    if not request_id:
        return None
    return c.execute("""SELECT d.id, v.n FROM versions v JOIN drafts d ON d.id=v.draft_id
                        WHERE v.request_id=? AND d.creator=?""", (request_id, creator)).fetchone()

def save_version(c, did, user, s, checked, request_id=None, expected_version=None):
    content, issues, image_checks = checked
    current_version = c.execute("SELECT COALESCE(MAX(n),0) FROM versions WHERE draft_id=?", (did,)).fetchone()[0]
    if expected_version is not None and expected_version != current_version:
        raise HTTPException(409, f"This draft changed since you opened version {expected_version}. Reload version {current_version} before resubmitting.")
    n = current_version + 1
    at = now()
    cur = c.execute("""INSERT INTO versions(draft_id,n,content,filename,issues,author,at,image_checks,request_id)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (did, n, content, s.filename, json.dumps(issues), user, at, json.dumps(image_checks), request_id or None))
    vid = cur.lastrowid
    for i in issues:
        if i.get("classification") == "Verified against approved evidence":
            continue
        c.execute("INSERT INTO issue_events(draft_id,version_id,creator,category,type,status,source) VALUES(?,?,?,?,?,?,?)",
                  (did, vid, user, i["category"], i["type"], i["status"], i["source"]))
    c.execute("""UPDATE drafts SET status='Pending review',review_decision=NULL,reviewer=NULL,
                 reviewed_at=NULL,reviewed_version=NULL WHERE id=?""", (did,))
    audit_insert(c, user, "creator", f"version {n} checked", f"draft {did}: {len(issues)} unresolved findings", at)
    return n

@app.post("/api/drafts")
def new_draft(s: Sub, me=Depends(allow("creator"))):
    u = me["name"]
    if not s.title.strip(): raise HTTPException(400, "Give the draft a title.")
    validate_request_id(s.request_id)
    if s.request_id:
        duplicate = one("""SELECT d.id FROM versions v JOIN drafts d ON d.id=v.draft_id
                          WHERE v.request_id=? AND d.creator=?""", (s.request_id, u))
        if duplicate: return {"id": duplicate["id"], "duplicate": True}
    checked = run_check(s)
    c = connect_db()
    try:
        c.execute("BEGIN IMMEDIATE")
        duplicate = find_duplicate_submission(c, s.request_id, u)
        if duplicate:
            c.commit()
            return {"id": duplicate[0], "duplicate": True}
        cur = c.execute("INSERT INTO drafts(title,creator,status,created) VALUES(?,?,?,?)",
                        (s.title, u, "Pending review", now()))
        did = cur.lastrowid
        version = save_version(c, did, u, s, checked, s.request_id)
        c.commit()
        return {"id": did, "version": version, "duplicate": False}
    except sqlite3.IntegrityError:
        c.rollback()
        duplicate = one("""SELECT d.id FROM versions v JOIN drafts d ON d.id=v.draft_id
                          WHERE v.request_id=? AND d.creator=?""", (s.request_id, u)) if s.request_id else None
        if duplicate: return {"id": duplicate["id"], "duplicate": True}
        raise HTTPException(409, "This draft submission conflicts with an existing record.")
    except sqlite3.Error:
        c.rollback(); LOG.exception("draft submission transaction failed")
        raise HTTPException(503, "The draft could not be saved. Retry with the same request ID to avoid a duplicate.")
    finally: c.close()

def latest(did): return one("SELECT * FROM versions WHERE draft_id=? ORDER BY n DESC LIMIT 1", (did,))

@app.get("/api/drafts")
def drafts(me=Depends(current)):
    out = q("SELECT * FROM drafts WHERE creator=? ORDER BY id DESC", (me["name"],)) if me["role"] == "creator" else q("SELECT * FROM drafts ORDER BY id DESC")
    for d in out:
        v = latest(d["id"]); d["version"] = v["n"]
        d["open_issues"] = sum(i.get("classification") != "Verified against approved evidence" for i in json.loads(v["issues"]))
        d["review_decision"] = d.get("review_decision") or ("approve" if d["status"] == "Ready to publish" else None)
        d["published"] = False
    return out

@app.get("/api/drafts/{did}")
def draft(did: int, me=Depends(current)):
    d = one("SELECT * FROM drafts WHERE id=?", (did,))
    if not d: raise HTTPException(404, "Draft not found.")
    if me["role"] == "creator" and d["creator"] != me["name"]: raise HTTPException(403, "You can only open your own drafts.")
    vs = q("SELECT * FROM versions WHERE draft_id=? ORDER BY n", (did,))
    feedback = q("SELECT version_id, finding_index, reviewer, verdict, at FROM reviewer_feedback WHERE draft_id=?", (did,))
    for v in vs:
        v["issues"] = json.loads(v["issues"]); v["image_checks"] = json.loads(v.get("image_checks") or "[]")
        v["fixed"] = rules.apply_fixes(v["content"], v["issues"])
        marks = {f["finding_index"]: f for f in feedback if f["version_id"] == v["id"]}
        for index, issue in enumerate(v["issues"]):
            issue["feedback"] = marks.get(index)
    d["versions"], d["comments"] = vs, q("SELECT * FROM comments WHERE draft_id=? ORDER BY id", (did,))
    publication = one("SELECT id,version,published_at,published_by,response_code,response_summary FROM publications WHERE draft_id=? ORDER BY id DESC LIMIT 1", (did,))
    d["review"] = {"decision": d.get("review_decision"), "reviewer": d.get("reviewer"),
                    "reviewed_at": d.get("reviewed_at"), "version": d.get("reviewed_version"),
                    "published": bool(publication and publication["version"] == d.get("reviewed_version")),
                    "publication": publication}
    return d

@app.get("/api/drafts/{did}/report", response_class=HTMLResponse)
def review_report(did: int, me=Depends(current)):
    """Printable, self-contained approval report. It is a report, not proof of publication."""
    d = one("SELECT * FROM drafts WHERE id=?", (did,))
    if not d: raise HTTPException(404, "Draft not found.")
    if me["role"] == "creator" and d["creator"] != me["name"]:
        raise HTTPException(403, "You can only open reports for your own drafts.")
    v = latest(did)
    issues = json.loads(v["issues"])
    comments = q("SELECT * FROM comments WHERE draft_id=? ORDER BY id", (did,))
    publication = one("SELECT version,published_at,published_by,response_code,response_summary FROM publications WHERE draft_id=? ORDER BY id DESC LIMIT 1", (did,))
    def e(value): return html_escape(str(value if value is not None else ""))
    finding_html = "".join(
        "<article><h3>" + e(i.get("type", "Finding")) + "</h3><p><b>Classification:</b> " + e(i.get("classification", i.get("status", "Needs human review"))) +
        "</p><p><b>Phrase:</b> <code>" + e(i.get("phrase") or i.get("detected", "")) + "</code></p><p>" + e(i.get("reason", "")) +
        "</p><p><b>Expected:</b> " + e(i.get("approved", "Not specified")) + "</p><p><b>Source:</b> " + e(i.get("source", "Not recorded")) +
        "</p>" + ("<p><b>Suggested correction:</b> " + e(i["suggestion"]) + "</p>" if i.get("suggestion") else "") +
        "".join("<blockquote><b>" + e(ev.get("source_document") or ev.get("source") or "Approved source") + "</b><br>" +
               e(ev.get("kind", "")) + ": " + e(ev.get("subject", "")) + " = " + e(ev.get("value", "")) +
               ("<br><q>" + e(ev.get("source_quote")) + "</q>" if ev.get("source_quote") else "") + "</blockquote>" for ev in i.get("evidence", [])) + "</article>"
        for i in issues)
    comment_html = "".join("<li><b>" + e(c["author"]) + " (" + e(c["role"]) + ", " + e(c["at"]) + "):</b> " + e(c["text"]) + "</li>" for c in comments)
    status = e(d.get("status", "")); decision = e(d.get("review_decision") or "Not yet decided")
    template = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TrustGate review report</title>
<style>body{font:16px/1.55 system-ui,sans-serif;max-width:900px;margin:36px auto;padding:0 20px;color:#172033}h1,h2{line-height:1.2}header{border-bottom:2px solid #dce3ef;padding-bottom:16px}.meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.meta p{background:#f4f7fb;padding:10px;border-radius:8px}article{border:1px solid #dce3ef;border-radius:10px;padding:16px;margin:14px 0;break-inside:avoid}blockquote{border-left:3px solid #2b63d9;padding:8px 12px;background:#f7f9fc;margin:10px 0}code,pre{white-space:pre-wrap;overflow-wrap:anywhere}.toolbar{position:sticky;top:0;background:white;padding:10px 0}@media print{.toolbar{display:none}body{margin:0;max-width:none}}</style></head><body><div class="toolbar"><button onclick="window.print()">Print / Save as PDF</button></div>
<header><h1>TrustGate AI · Review report</h1><p>Evidence-based content governance record. Approval is not publication.</p></header>
<div class="meta"><p><b>Draft</b><br>@@TITLE@@</p><p><b>Status</b><br>@@STATUS@@</p><p><b>Creator</b><br>@@CREATOR@@</p><p><b>Version</b><br>@@VERSION@@</p><p><b>Decision</b><br>@@DECISION@@</p><p><b>Reviewer</b><br>@@REVIEWER@@</p><p><b>Reviewed at</b><br>@@REVIEWED_AT@@</p><p><b>Findings</b><br>@@COUNT@@ (including review prompts)</p><p><b>Publishing integration</b><br>@@PUBLICATION@@</p></div>
<h2>Content</h2><pre>@@CONTENT@@</pre><h2>Findings and approved evidence</h2>@@FINDINGS@@<h2>Comments</h2><ul>@@COMMENTS@@</ul><footer><p>Generated @@GENERATED@@. External publication was not performed by TrustGate.</p></footer></body></html>"""
    replacements = {
        "@@TITLE@@": e(d["title"]), "@@STATUS@@": status, "@@CREATOR@@": e(d["creator"]),
        "@@VERSION@@": e(v["n"]), "@@DECISION@@": decision,
        "@@REVIEWER@@": e(d.get("reviewer") or "Not yet assigned"),
        "@@REVIEWED_AT@@": e(d.get("reviewed_at") or "Not yet reviewed"), "@@COUNT@@": str(len(issues)),
        "@@PUBLICATION@@": e((f"Webhook accepted for version {publication['version']} at {publication['published_at']}; verify actual publication in destination." if publication else "No publishing webhook event recorded.")),
        "@@CONTENT@@": e(v["content"]),
        "@@FINDINGS@@": finding_html or "<p>No findings were generated. This does not guarantee that the content is accurate or compliant.</p>",
        "@@COMMENTS@@": comment_html or "<li>No comments recorded.</li>", "@@GENERATED@@": e(now())}
    body = template
    for token, value in replacements.items(): body = body.replace(token, value)
    return HTMLResponse(body, headers={"Content-Disposition": f'inline; filename="trustgate-review-{did}-v{v["n"]}.html"', "Cache-Control": "no-store"})


@app.post("/api/drafts/{did}/resubmit")
def resubmit(did: int, s: Sub, me=Depends(allow("creator"))):
    u = me["name"]
    validate_request_id(s.request_id)
    d = one("SELECT * FROM drafts WHERE id=?", (did,))
    if not d: raise HTTPException(404, "Draft not found.")
    if d["creator"] != u: raise HTTPException(403, "Only the draft's creator can resubmit it.")
    if s.request_id:
        duplicate = one("SELECT n FROM versions WHERE draft_id=? AND request_id=?", (did, s.request_id))
        if duplicate: return {"version": duplicate["n"], "duplicate": True}
    if d["status"] != "Returned":
        raise HTTPException(409, "A draft can only be revised after a reviewer returns it.")
    checked = run_check(s)
    c = connect_db()
    try:
        c.execute("BEGIN IMMEDIATE")
        current = c.execute("SELECT creator,status FROM drafts WHERE id=?", (did,)).fetchone()
        if not current: raise HTTPException(404, "Draft not found.")
        if current[0] != u: raise HTTPException(403, "Only the draft's creator can resubmit it.")
        duplicate = find_duplicate_submission(c, s.request_id, u)
        if duplicate:
            if duplicate[0] != did: raise HTTPException(409, "Request ID was already used for another draft.")
            c.commit(); return {"version": duplicate[1], "duplicate": True}
        if current[1] != "Returned": raise HTTPException(409, "Draft state changed while this version was being checked. Reload and retry.")
        version = save_version(c, did, u, s, checked, s.request_id, s.expected_version)
        c.commit()
        return {"version": version, "duplicate": False}
    except sqlite3.IntegrityError:
        c.rollback()
        duplicate = one("SELECT n FROM versions WHERE draft_id=? AND request_id=?", (did, s.request_id)) if s.request_id else None
        if duplicate: return {"version": duplicate["n"], "duplicate": True}
        raise HTTPException(409, "This version conflicts with an existing submission.")
    except sqlite3.Error:
        c.rollback(); LOG.exception("draft resubmission transaction failed")
        raise HTTPException(503, "The new draft version could not be saved. Retry with the same request ID.")
    finally: c.close()

@app.post("/api/drafts/{did}/comments")
def comment(did: int, n: Note, me=Depends(allow("creator", "reviewer"))):
    u, x_role = me["name"], me["role"]; d = one("SELECT * FROM drafts WHERE id=?", (did,))
    if not d: raise HTTPException(404, "Draft not found.")
    if x_role == "creator" and d["creator"] != u: raise HTTPException(403, "You can only comment on your own drafts.")
    if not n.text.strip(): raise HTTPException(400, "Write a comment first.")
    ins("INSERT INTO comments(draft_id,author,role,text,at) VALUES(?,?,?,?,?)", (did, u, x_role, n.text, now()))
    log(u, x_role, "comment", f"draft {did}"); return {}

@app.post("/api/drafts/{did}/decision")
def decide(did: int, d: Decision, me=Depends(allow("reviewer"))):
    u, x_role = me["name"], me["role"]
    if d.decision not in ("approve", "return"): raise HTTPException(400, "Choose approve or return.")
    c = connect_db()
    try:
        c.execute("BEGIN IMMEDIATE")
        draft_row = c.execute("SELECT status FROM drafts WHERE id=?", (did,)).fetchone()
        if not draft_row: raise HTTPException(404, "Draft not found.")
        if draft_row[0] != "Pending review": raise HTTPException(409, "This draft is no longer pending review.")
        v = c.execute("SELECT id,n,issues FROM versions WHERE draft_id=? ORDER BY n DESC LIMIT 1", (did,)).fetchone()
        if not v: raise HTTPException(404, "Draft version not found.")
        if d.expected_version is not None and d.expected_version != v[1]:
            raise HTTPException(409, f"This draft changed while you were reviewing it. Reload version {v[1]} before deciding.")
        open_n = sum(i.get("classification") != "Verified against approved evidence" for i in json.loads(v[2]))
        if (d.decision == "return" or open_n) and not d.comment.strip():
            raise HTTPException(400, "Add a comment: it is required to return a draft or approve one with open findings.")
        at = now(); status = "Ready to publish" if d.decision == "approve" else "Returned"
        if d.comment.strip():
            c.execute("INSERT INTO comments(draft_id,author,role,text,at) VALUES(?,?,?,?,?)", (did, u, x_role, d.comment, at))
        c.execute("""UPDATE drafts SET status=?,review_decision=?,reviewer=?,reviewed_at=?,reviewed_version=?
                     WHERE id=? AND status='Pending review'""",
                  (status, d.decision, u, at, v[1], did))
        action = "draft approved by reviewer" if d.decision == "approve" else "draft returned by reviewer"
        detail = f"draft {did} version {v[1]}; {open_n} unresolved findings"
        if d.comment.strip(): detail += f"; feedback: {d.comment[:500]}"
        audit_insert(c, u, x_role, action, detail, at)
        c.commit()
        return {"status": status, "review_decision": "Approved by reviewer" if d.decision == "approve" else "Returned to creator",
                "reviewer": u, "reviewed_at": at, "reviewed_version": v[1], "published": False}
    except sqlite3.Error:
        c.rollback(); LOG.exception("review decision transaction failed")
        raise HTTPException(503, "The review decision could not be saved. Reload the draft before retrying.")
    finally: c.close()

class FindingFeedback(BaseModel):
    version_id: int; finding_index: int; verdict: str

@app.post("/api/drafts/{did}/feedback")
def finding_feedback(did: int, f: FindingFeedback, me=Depends(allow("reviewer"))):
    v = one("SELECT * FROM versions WHERE id=? AND draft_id=?", (f.version_id, did))
    if not v: raise HTTPException(404, "Draft version not found.")
    issues = json.loads(v["issues"])
    if f.finding_index < 0 or f.finding_index >= len(issues): raise HTTPException(404, "Finding not found.")
    if f.verdict not in ("correct", "false_alarm"): raise HTTPException(400, "Choose correct or false alarm.")
    issue = issues[f.finding_index]; u = me["name"]
    q("""INSERT INTO reviewer_feedback(draft_id,version_id,finding_index,reviewer,verdict,category,type,source,phrase,at)
          VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(version_id,finding_index,reviewer) DO UPDATE SET
          verdict=excluded.verdict,category=excluded.category,type=excluded.type,source=excluded.source,
          phrase=excluded.phrase,at=excluded.at""",
      (did, f.version_id, f.finding_index, u, f.verdict, issue["category"], issue["type"], issue["source"], issue["phrase"], now()))
    log(u, me["role"], "finding feedback", f"draft {did} v{v['n']} finding {f.finding_index + 1}: {f.verdict}")
    return {"verdict": f.verdict}

@app.get("/api/publishing/status")
def publishing_status(me=Depends(allow("reviewer", "admin"))):
    url = os.environ.get("TRUSTGATE_PUBLISH_WEBHOOK_URL", "").strip()
    token = os.environ.get("TRUSTGATE_PUBLISH_WEBHOOK_TOKEN", "")
    enabled = bool(url and token and (url.startswith("https://") or os.environ.get("TRUSTGATE_ALLOW_INSECURE_WEBHOOK") == "1"))
    return {"enabled": enabled, "provider": "configured webhook" if enabled else "not configured"}


@app.post("/api/drafts/{did}/publish")
def publish_approved_draft(did: int, me=Depends(allow("reviewer", "admin"))):
    """Send a reviewed version to an operator-configured webhook; no endpoint is accepted from the browser."""
    url = os.environ.get("TRUSTGATE_PUBLISH_WEBHOOK_URL", "").strip()
    token = os.environ.get("TRUSTGATE_PUBLISH_WEBHOOK_TOKEN", "")
    if not url or not token:
        raise HTTPException(503, "Publishing is not configured. Ask the deployment administrator to configure the publishing webhook.")
    if not url.startswith("https://") and os.environ.get("TRUSTGATE_ALLOW_INSECURE_WEBHOOK") != "1":
        raise HTTPException(503, "The publishing webhook must use HTTPS.")
    d = one("SELECT * FROM drafts WHERE id=?", (did,))
    if not d: raise HTTPException(404, "Draft not found.")
    if d["status"] != "Ready to publish": raise HTTPException(409, "Only reviewer-approved drafts can be sent to the publishing integration.")
    v = latest(did)
    if not v or d.get("reviewed_version") != v["n"]:
        raise HTTPException(409, "The latest draft version has not been approved.")
    previous = one("SELECT id FROM publications WHERE draft_id=? AND version=?", (did, v["n"]))
    if previous: raise HTTPException(409, "This exact approved version has already been sent to the publishing integration.")
    payload = {"event": "trustgate.content.approved", "draft_id": did, "title": d["title"], "version": v["n"],
               "content": v["content"], "creator": d["creator"], "reviewer": d["reviewer"],
               "approved_at": d["reviewed_at"], "approved_findings": json.loads(v["issues"]),
               "publication_note": "TrustGate approved this version for publishing; the receiving integration is responsible for final publication."}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(token.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    req = urllib.request.Request(url, data=raw, method="POST", headers={"Content-Type": "application/json",
        "Authorization": "Bearer " + token, "X-TrustGate-Signature": "sha256=" + signature,
        "User-Agent": "TrustGate-AI/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            code = int(response.status)
            if code < 200 or code >= 300: raise HTTPException(502, "The publishing integration did not accept the approved draft.")
            summary = "Webhook accepted the approved version. Confirm actual publication in the receiving system."
    except HTTPException:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log(me["name"], me["role"], "publishing webhook failed", f"draft {did} v{v['n']}: {type(exc).__name__}")
        raise HTTPException(502, "The publishing integration could not be reached. The draft remains approved but is not confirmed published.")
    at = now()
    ins("INSERT INTO publications(draft_id,version,published_at,endpoint,response_code,published_by,response_summary) VALUES(?,?,?,?,?,?,?)",
        (did, v["n"], at, url, code, me["name"], summary))
    log(me["name"], me["role"], "approved draft sent to publishing webhook", f"draft {did} v{v['n']}; HTTP {code}")
    return {"sent": True, "draft_id": did, "version": v["n"], "sent_at": at, "response_code": code,
            "message": summary, "published": False}


@app.get("/api/ai/status")
def ai_status(me=Depends(current)): return {"enabled": ai.available(), "model": ai.MODEL if ai.available() else ""}

@app.post("/api/drafts/{did}/ai-rewrite")
def ai_rewrite(did: int, me=Depends(allow("creator"))):
    u, x_role = me["name"], me["role"]; d = one("SELECT * FROM drafts WHERE id=?", (did,))
    if not d or d["creator"] != u: raise HTTPException(403, "Only the draft's creator can request a rewrite.")
    if not ai.available(): raise HTTPException(400, "AI is not enabled. Set ANTHROPIC_API_KEY and restart the server.")
    v = latest(did)
    if v["content"].startswith("[Image:"): raise HTTPException(400, "AI rewrite works on text drafts only.")
    try: text = ai.rewrite(v["content"], q("SELECT * FROM facts"), json.loads(v["issues"]))
    except Exception: raise HTTPException(502, "The AI service did not respond. Try again in a moment.")
    log(u, x_role, "ai rewrite", f"draft {did} v{v['n']}"); return {"text": text}

@app.get("/api/analytics")
def analytics(me=Depends(allow("reviewer", "admin"))):
    st = {r["status"]: r["c"] for r in q("SELECT status, COUNT(*) c FROM drafts GROUP BY status")}
    rep = sum(r["c"] - 1 for r in q("SELECT COUNT(*) c FROM issue_events GROUP BY creator, type HAVING c > 1"))
    latest = one("SELECT * FROM benchmark_runs ORDER BY id DESC LIMIT 1")
    if latest:
        latest["rules"] = json.loads(latest["rules"])
        latest["rules_ai"] = json.loads(latest["rules_ai"]) if latest["rules_ai"] else None
    clarity = q("""SELECT COALESCE(NULLIF(source, '-'), category) name, category, type,
                    COUNT(*) votes, SUM(CASE WHEN verdict='false_alarm' THEN 1 ELSE 0 END) false_alarms
                    FROM reviewer_feedback GROUP BY source, category, type
                    ORDER BY false_alarms DESC, votes DESC, name LIMIT 10""")
    for row in clarity: row["dispute_rate"] = round(row["false_alarms"] / row["votes"] * 100, 1)
    return {"drafts": sum(st.values()), "approved": st.get("Ready to publish", 0), "returned": st.get("Returned", 0),
            "pending": st.get("Pending review", 0), "repeated": rep,
            "by_category": q("SELECT category name, COUNT(*) c FROM issue_events GROUP BY category ORDER BY c DESC"),
            "by_source": q("SELECT source name, COUNT(*) c FROM issue_events WHERE source != '-' GROUP BY source ORDER BY c DESC LIMIT 5"),
            "benchmark": latest, "guideline_clarity": clarity}

@app.post("/api/benchmark/run")
def run_benchmark(me=Depends(allow("reviewer", "admin"))):
    try:
        evaluation = benchmark.evaluate(include_ai=True)
    except Exception as e:
        log(me["name"], me["role"], "benchmark AI failed", type(e).__name__)
        raise HTTPException(502, "The AI benchmark could not complete. The rules-only results were not saved.")
    rules_score = evaluation["deterministic"]
    combined_score = evaluation.get("ai_assisted")
    configuration = evaluation["configuration"]
    rules_score["configuration"] = configuration
    if combined_score:
        combined_score["configuration"] = configuration
    enabled = configuration["ai"] == "claude_vision_language_model"
    at = now()
    run_id = ins("INSERT INTO benchmark_runs(at,samples,rules,rules_ai,ai_enabled) VALUES(?,?,?,?,?)",
                 (at, evaluation["evaluated_examples"], json.dumps(rules_score),
                  json.dumps(combined_score) if combined_score else None, int(enabled)))
    log(me["name"], me["role"], "benchmark run",
        f"run {run_id}: dataset {evaluation['dataset_version']}, {evaluation['evaluated_examples']} labelled drafts; AI {configuration['ai']}")
    return {"id": run_id, "at": at, "samples": evaluation["evaluated_examples"],
            "dataset_version": evaluation["dataset_version"], "configuration": configuration,
            "rules": rules_score, "rules_ai": combined_score, "ai_enabled": enabled}

@app.get("/api/audit")
def audit(me=Depends(allow("reviewer", "admin"))):
    return q("SELECT * FROM audit ORDER BY id DESC LIMIT 100")

app.mount("/", StaticFiles(directory=os.path.join(HERE, "..", "frontend"), html=True), name="ui")
