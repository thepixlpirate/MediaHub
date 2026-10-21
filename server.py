#!/usr/bin/env python3
"""Media Hub: one login in front of Radarr, Sonarr, Lidarr, Bookarr, qBittorrent and SABnzbd.
Server-side login, SQLite settings, image cache and API proxy. API keys and passwords stay on the server
and are never sent to the browser. Python standard library only."""
import re,os,json,sqlite3,hashlib,secrets,time,threading,urllib.request,urllib.error,urllib.parse
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
CFG=os.environ.get("HUB_CONFIG","/config");PORT=int(os.environ.get("HUB_PORT","8690"));TRUST=os.environ.get("HUB_TRUST_PROXY")=="1"
HERE=os.path.dirname(os.path.abspath(__file__));CD=CFG+"/cache2";os.makedirs(CD,exist_ok=True)
for _d in (CFG+"/cache",):  # old image cache (could hold bad files from earlier versions) - wipe once
    if os.path.isdir(_d):
        for _f in os.listdir(_d):
            try:os.remove(_d+"/"+_f)
            except OSError:pass
for _f in os.listdir(CD):
    if _f.endswith(".none"):os.remove(CD+"/"+_f)
db=sqlite3.connect(CFG+"/hub.db",check_same_thread=False);L=threading.Lock()
db.executescript("create table if not exists users(name text primary key,salt blob,hash blob);create table if not exists sessions(tok text primary key,user text,exp real);create table if not exists settings(k text primary key,v text);create table if not exists fails(ip text,t real);")
try:os.chmod(CFG+"/hub.db",0o600)
except OSError:pass
def q(sql,a=()):
    with L:
        c=db.execute(sql,a);db.commit();return c.fetchall()
def get(k):
    r=q("select v from settings where k=?",(k,));return r[0][0] if r else ""
def put(k,v):q("insert or replace into settings values(?,?)",(k,v))
def hp(pw,salt):return hashlib.scrypt(pw.encode(),salt=salt,n=2**15,r=8,p=1,maxmem=64*1024*1024,dklen=32)
sha=lambda s:hashlib.sha256(s.encode()).hexdigest()
HEAD=[("X-Content-Type-Options","nosniff"),("X-Frame-Options","SAMEORIGIN"),("Referrer-Policy","no-referrer"),("Cache-Control","no-store"),
("Content-Security-Policy","default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'self'")]
import collections
T=threading.local()
PREF=collections.defaultdict(lambda:[None,0])
import socket,ipaddress
def safe(u):
    try:
        p=urllib.parse.urlsplit(u)
        if p.scheme not in("http","https") or not p.hostname or p.port not in(None,80,443):return False
        return all(ipaddress.ip_address(x[4][0]).is_global for x in socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=="https" else 80)))
    except Exception:return False
class _NoPriv(urllib.request.HTTPRedirectHandler):
    def redirect_request(s,req,fp,code,msg,hdrs,newurl):
        if not safe(newurl):raise urllib.error.URLError("blocked redirect")
        return super().redirect_request(req,fp,code,msg,hdrs,newurl)
OPEN=urllib.request.build_opener(_NoPriv)
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CSEM=threading.BoundedSemaphore(6)
def isimg(d):return bool(d) and (d[:3]==b"\xff\xd8\xff" or d[:4]==b"\x89PNG" or d[:4]==b"GIF8" or (d[:4]==b"RIFF" and d[8:12]==b"WEBP"))
QBC={};QBF={}
def qb_login(b):
    if time.time()-QBF.get(b,0)<30:return False  # don't hammer qBittorrent (it bans IPs after repeated failed logins)
    d=urllib.parse.urlencode({"username":get("qbittorrent.user"),"password":get("qbittorrent.pass")}).encode()
    rq=urllib.request.Request(b.rstrip("/")+"/api/v2/auth/login",data=d,method="POST",headers={"Referer":b.rstrip("/")+"/","Content-Type":"application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(rq,timeout=8) as r:ck=r.headers.get("Set-Cookie","");r.read()
    except Exception:return False
    m=re.search(r"[A-Za-z_]*SID[A-Za-z0-9_]*=[^;]+",ck)
    if m:QBC[b]=m.group(0);return True
    QBF[b]=time.time();return False
def upstream(path,method="GET",body=None,ctype=None,timeout=10):
    sv=T.sv;key=get(sv+"key");bases=[b for b in (get(sv+"local"),get(sv+"remote")) if b]
    if PREF[sv][0] in bases and time.time()-PREF[sv][1]<60:bases=[PREF[sv][0]]+[b for b in bases if b!=PREF[sv][0]]
    last=(502,b'{"error":"Cannot reach the service"}',"application/json")
    for b in bases:
        for attempt in (0,1):
            h={}
            if ctype:h["Content-Type"]=ctype
            if sv=="qbittorrent.":
                h["Referer"]=b.rstrip("/")+"/"
                if QBC.get(b):h["Cookie"]=QBC[b]
            elif sv!="sabnzbd." and key:h["X-Api-Key"]=key
            try:
                with urllib.request.urlopen(urllib.request.Request(b.rstrip("/")+path,data=body,method=method,headers=h),timeout=timeout) as r:
                    PREF[sv][0],PREF[sv][1]=b,time.time();return r.status,r.read(),r.headers.get("Content-Type","application/json")
            except urllib.error.HTTPError as e:
                if sv=="qbittorrent." and e.code==403 and attempt==0 and get(sv+"user") and qb_login(b):continue
                return e.code,e.read(),e.headers.get("Content-Type","application/json")
            except Exception:break
    return last
class H(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1";server_version="Media"
    def log_message(s,*a):pass
    def out(s,code,body=b"",ct="application/json",extra=()):
        if isinstance(body,(dict,list)):body=json.dumps(body).encode()
        s.send_response(code);s.send_header("Content-Type",ct);s.send_header("Content-Length",str(len(body)))
        for k,v in [h for h in HEAD if h[0] not in {x[0] for x in extra}]+list(extra):s.send_header(k,v)
        s.end_headers();s.wfile.write(body)
    def ip(s):return (s.headers.get("X-Forwarded-For","").split(",")[0].strip() if TRUST else "")or s.client_address[0]
    def user(s):
        for p in s.headers.get("Cookie","").split(";"):
            k,_,v=p.strip().partition("=")
            if k=="hub" and v:
                r=q("select user from sessions where tok=? and exp>?",(sha(v),time.time()))
                if r:return r[0][0]
    def body(s):return getattr(s,"_b",b"")
    def js(s):
        try:return json.loads(s.body() or b"{}")
        except Exception:return {}
    def cookie(s,tok,age=None):
        c=f"hub={tok}; Path=/; HttpOnly; SameSite=Strict"+(f"; Max-Age={age}" if age is not None else "")
        if s.headers.get("X-Forwarded-Proto")=="https":c+="; Secure"
        return [("Set-Cookie",c)]
    def route(s,m):
        try:
            s._b=b"";n=int(s.headers.get("Content-Length") or 0)
            if n>40_000_000:s.close_connection=True;return s.out(413,{"error":"too large"})
            if n:s._b=s.rfile.read(n)  # always consume the body, or it corrupts the next request on this keep-alive connection
            return s._route(m)
        except (BrokenPipeError,ConnectionResetError):raise
        except Exception:return s.out(500,{"error":"server error"})
    def _route(s,m):
        u=urllib.parse.urlsplit(s.path);p=u.path;T.sv="";mm=re.match(r"/s/(radarr|sonarr|lidarr|bookarr|qbittorrent|sabnzbd)(/.*)?$",p)
        if mm:
            T.sv=mm.group(1)+".";p=mm.group(2) or "/"
            if m=="GET" and p=="/":return s.out(200,open(HERE+"/static/"+mm.group(1)+".html","rb").read(),"text/html; charset=utf-8")
        if m=="GET" and p in("/logo.png","/icon.png") and not T.sv:
            try:return s.out(200,open(HERE+"/static/icon.png","rb").read(),"image/png",[("Cache-Control","public, max-age=86400")])
            except OSError:return s.out(404,{})
        ai=re.fullmatch(r"/apps/(radarr|sonarr|lidarr|bookarr|qbittorrent|sabnzbd)\.svg",p)
        if m=="GET" and ai and not T.sv:
            try:return s.out(200,open(HERE+"/static/apps/"+ai.group(1)+".svg","rb").read(),"image/svg+xml",[("Cache-Control","public, max-age=86400"),("Content-Security-Policy","default-src 'none'; style-src 'unsafe-inline'")])
            except OSError:return s.out(404,{})
        if m!="GET" and s.headers.get("X-Requested-With")!="hub":return s.out(403,{"error":"forbidden"})
        if m=="GET" and p=="/":return s.out(200,open(HERE+"/static/index.html","rb").read(),"text/html; charset=utf-8")
        if p=="/auth/me":return s.out(200,{"user":s.user(),"setup":not q("select 1 from users"),"ver":10})
        if p=="/auth/setup" and m=="POST":
            if q("select 1 from users"):return s.out(403,{"error":"already set up"})
            d=s.js();n,pw=str(d.get("u","")).strip(),str(d.get("p",""))
            if not n or len(pw)<8:return s.out(400,{"error":"bad"})
            salt=secrets.token_bytes(16);q("insert into users values(?,?,?)",(n,salt,hp(pw,salt)));return s.session(n,d)
        if p=="/auth/login" and m=="POST":
            ip=s.ip();q("delete from fails where t<?",(time.time()-900,))
            if q("select count(*) from fails where ip=?",(ip,))[0][0]>=5:return s.out(429,{"error":"locked"})
            d=s.js();r=q("select salt,hash from users where name=?",(str(d.get("u","")),))
            ok=bool(r) and secrets.compare_digest(hp(str(d.get("p","")),r[0][0]),r[0][1])
            if not ok:
                q("insert into fails values(?,?)",(ip,time.time()));time.sleep(1);return s.out(401,{"error":"bad login"})
            q("delete from fails where ip=?",(ip,));return s.session(d["u"],d)
        if p=="/auth/logout" and m=="POST":
            for c in s.headers.get("Cookie","").split(";"):
                k,_,v=c.strip().partition("=")
                if k=="hub":q("delete from sessions where tok=?",(sha(v),))
            return s.out(200,{},extra=s.cookie("",0))
        if not s.user():return s.out(401,{"error":"login required"})
        if p=="/auth/password" and m=="POST":
            d=s.js();nm=s.user();r=q("select salt,hash from users where name=?",(nm,));nw=str(d.get("new",""))
            if not r or not secrets.compare_digest(hp(str(d.get("old","")),r[0][0]),r[0][1]):
                time.sleep(1);return s.out(403,{"error":"wrong password"})
            if len(nw)<8:return s.out(400,{"error":"too short"})
            sl=secrets.token_bytes(16);q("update users set salt=?,hash=? where name=?",(sl,hp(nw,sl),nm));q("delete from sessions where user=?",(nm,));return s.session(nm,{"remember":True})
        if p=="/hub/settings":
            if m=="POST":
                d=s.js()
                for k in("local","remote"):
                    v=str(d.get(k,"")).strip().rstrip("/")
                    if v and not v.startswith(("http://","https://")):return s.out(400,{"error":"URL must start with http:// or https://"})
                    put(T.sv+k,v)
                if str(d.get("key","")).strip():put(T.sv+"key",str(d["key"]).strip())
                if "user" in d:put(T.sv+"user",str(d["user"]).strip())
                if str(d.get("pass","")):put(T.sv+"pass",str(d["pass"]))
                PREF[T.sv][0]=None;QBC.clear();QBF.clear()
            return s.out(200,{"local":get(T.sv+"local"),"remote":get(T.sv+"remote"),"hasKey":bool(get(T.sv+"key")),"user":get(T.sv+"user"),"hasPass":bool(get(T.sv+"pass"))})
        if p=="/hub/dismissed" and T.sv:
            k=T.sv+"dismissed"
            try:cur=json.loads(get(k) or "{}")
            except Exception:cur={}
            if not isinstance(cur,dict):cur={}
            if m=="POST":
                d=s.js().get("set",{})
                if isinstance(d,dict):
                    for a,b in list(d.items())[:300]:
                        a=str(a)[:240]
                        if b in("r","d"):cur[a]=b
                        else:cur.pop(a,None)
                    if len(cur)>1500:cur=dict(list(cur.items())[-1500:])
                    put(k,json.dumps(cur))
            return s.out(200,{"m":cur})
        if p=="/cover":return s.cover(urllib.parse.parse_qs(u.query))
        if p=="/hub/diag":
            d,a=s.getcover(urllib.parse.parse_qs(u.query),True);return s.out(200,{"ok":bool(d),"attempts":a})
        if T.sv=="sabnzbd." and p=="/sabapi":
            qp=[(k,v) for k,v in urllib.parse.parse_qsl(u.query,keep_blank_values=True) if k not in("apikey","ma_username","ma_password","output")]
            if get("sabnzbd.key"):qp.append(("apikey",get("sabnzbd.key")))
            elif get("sabnzbd.user"):qp+= [("ma_username",get("sabnzbd.user")),("ma_password",get("sabnzbd.pass"))]
            qp.append(("output","json"))
            b=s.body() if m in("POST","PUT","DELETE") else None
            c,data,ct=upstream("/api?"+urllib.parse.urlencode(qp),m,b,s.headers.get("Content-Type") if b else None,timeout=30)
            return s.out(c,data,ct)
        if re.match(r"/api/v[123]/",p):
            b=s.body() if m in("POST","PUT","DELETE") else None
            slow=re.search(r"/(release|manualimport|rename|retag|command|test|testall|action/[^/]+|search/[a-z]+|rss/[a-zA-Z]+)$",p)
            c,data,ct=upstream(p+("?"+u.query if u.query else ""),m,b,s.headers.get("Content-Type") if b else None,timeout=120 if slow else 20)
            return s.out(c,data,ct)
        s.out(404,{"error":"not found"})
    def session(s,name,d):
        tok=secrets.token_urlsafe(32);age=2592000 if d.get("remember") else 43200
        q("delete from sessions where exp<?",(time.time(),));q("insert into sessions values(?,?,?)",(sha(tok),name,time.time()+age))
        return s.out(200,{"user":name},extra=s.cookie(tok,age if d.get("remember") else None))
    def getcover(s,qs,diag=False):
        att=[];paths=[]
        for u in qs.get("u",[])[:10]:
            i=u.find("/MediaCover/");p=u[i:].split("?")[0] if i>=0 else ""
            if p and re.fullmatch(r"/MediaCover/[A-Za-z0-9_/.\-]+\.(jpg|jpeg|png|webp)",p) and ".." not in p and p not in paths:paths.append(p)
        for gd in qs.get("g",[])[:2]:
            i=gd.find("/MediaCover/");gd=gd[i:] if i>=0 else ""
            if re.fullmatch(r"/MediaCover/(?:(?:Artists|Authors|Albums|Books)/)?\d+",gd):paths+=[x for x in (gd+"/"+n for n in ("poster.jpg","cover.jpg","fanart.jpg","banner.jpg")) if x not in paths]
        rs=qs.get("r",[])[:8];nm=(qs.get("n",[""])[0] or "").strip()[:100]
        if not paths and not rs and not nm:return None,[("no image info","")]
        f=CD+"/"+hashlib.sha1((T.sv+"|".join(paths+rs)+"|"+nm).encode()).hexdigest()[:24]
        if not diag:
            if os.path.exists(f):
                if time.time()-os.path.getmtime(f)<7*86400:
                    d=open(f,"rb").read()
                    if isimg(d):return d,[("cached","")]
                try:os.remove(f)
                except OSError:pass
            if os.path.exists(f+".none") and time.time()-os.path.getmtime(f+".none")<120:return None,[("recently failed","")]
        data=None;transient=False
        with CSEM:
            for p in paths:
                base,ext=p.rsplit(".",1)
                for cand in (base+"-250."+ext,p):
                    c,d,ct=upstream(cand+"?apikey="+urllib.parse.quote(get(T.sv+"key")));att.append((cand,str(c)))
                    if c==200 and isimg(d):data=d;break
                    if c>=500 or c==429:transient=True
                if data:break
            if not data:
                for r in rs:
                    r2=r.replace("/original/","/w342/")
                    for ru in ([ "https://"+r2[7:],r2] if r2.startswith("http://") else [r2]):
                        if not safe(ru):att.append((ru[:90],"blocked or can't resolve"));continue
                        try:
                            with OPEN.open(urllib.request.Request(ru,headers={"User-Agent":UA,"Accept":"image/*,*/*;q=0.8"}),timeout=10) as x:d=x.read(3_000_000)
                            if isimg(d):data=d;att.append((ru[:90],"200"));break
                            att.append((ru[:90],"not an image"))
                        except urllib.error.HTTPError as e:
                            att.append((ru[:90],str(e.code)))
                            if e.code>=500 or e.code==429:transient=True
                        except Exception as e:att.append((ru[:90],type(e).__name__));transient=True
                    if data:break
        if not data and nm:  # last resort for artists: public Deezer artist picture, matched by exact name
            try:
                with OPEN.open(urllib.request.Request("https://api.deezer.com/search/artist?limit=5&q="+urllib.parse.quote(nm),headers={"User-Agent":UA}),timeout=10) as x:j=json.loads(x.read(300000))
                norm=lambda z:re.sub(r"[^a-z0-9]","",str(z).lower())
                hit=next((a for a in j.get("data",[]) if norm(a.get("name"))==norm(nm)),None);pic=hit and (hit.get("picture_big") or hit.get("picture_medium"))
                if pic and safe(pic):
                    with OPEN.open(urllib.request.Request(pic,headers={"User-Agent":UA}),timeout=10) as x:d=x.read(3_000_000)
                    if isimg(d):data=d;att.append(("deezer: "+nm,"200"))
                    else:att.append(("deezer: "+nm,"not an image"))
                else:att.append(("deezer: "+nm,"no match"))
            except Exception as e:att.append(("deezer: "+nm,type(e).__name__));transient=True
        if data:open(f,"wb").write(data)
        elif not diag and not transient:open(f+".none","w").write("")
        return data,att
    def cover(s,qs):
        d,att=s.getcover(qs)
        if not d:return s.out(404,{})
        ct="image/png" if d[:4]==b"\x89PNG" else "image/webp" if d[8:12]==b"WEBP" else "image/jpeg"
        return s.out(200,d,ct,[("Cache-Control","private, max-age=86400")])
    def handle_one_request(s):
        try:super().handle_one_request()
        except Exception:pass
    do_GET=lambda s:s.route("GET")
    do_POST=lambda s:s.route("POST")
    do_PUT=lambda s:s.route("PUT")
    do_DELETE=lambda s:s.route("DELETE")
if __name__=="__main__":
    print(f"MediaHub running on port {PORT} (data in {CFG})");ThreadingHTTPServer(("0.0.0.0",PORT),H).serve_forever()
