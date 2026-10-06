#!/usr/bin/env python3
"""Dependency-free local MCP stdio entrypoint for iPhone Use WDA."""
import argparse
import base64
import collections
import fcntl
import inspect
import json
import math
import os
import re
from pathlib import Path
import sys
import time
from wda_client import WDAClient, WDAError
from wda_controller import PhoneController
from wda_setup import SetupManager

VERSION="0.1.0"
PROTOCOLS=("2025-11-25","2025-06-18","2025-03-26","2024-11-05")


def obj(properties,required=()):
    return {"type":"object","properties":properties,"required":list(required),"additionalProperties":False}


def string(description="",max_length=1000,enum=None):
    result={"type":"string","minLength":1,"maxLength":max_length}
    if description:result["description"]=description
    if enum:result["enum"]=enum
    return result


def num(low,high,kind="number"):
    return {"type":kind,"minimum":low,"maximum":high}


BOOL={"type":"boolean"}
SEL=obj({k:string(max_length=2000 if k=="predicate" else 1000) for k in ("label","name","value","type","predicate")})
SEL["minProperties"]=1
OBS=string(enum=["none","tree","screenshot","both"])
EXPECT={"expect":SEL,"observe":OBS}
REGION=obj({k:num(0 if k in ("x","y") else 1,10000) for k in ("x","y","width","height")},("x","y","width","height"))
SCHEMAS={
 "observe":obj({"mode":string(enum=["tree","screenshot","both"]),"include_invisible":BOOL,"max_nodes":num(1,500,"integer"),"expensive_visibility":BOOL}),
 "find":obj({"selector":SEL,"limit":num(1,30,"integer")},("selector",)),
 "tap":obj({"selector":SEL,"x":num(0,10000),"y":num(0,10000),"observation_id":string(),**EXPECT}),
 "swipe":obj({"direction":string(enum=["up","down","left","right"]),"region":REGION,"observation_id":string(),"expect":SEL,"verify":BOOL,"max_attempts":num(1,2,"integer")}),
 "type_text":obj({"selector":SEL,"text":string(max_length=10000),"allow_newlines":BOOL,"submit":BOOL,"replace":BOOL,"observe":OBS},("selector","text")),
 "press_button":obj({"name":string(enum=["home","volumeup","volumedown"]),"observe":OBS},("name",)),
 "launch_app":obj({"bundle_id":string(),**EXPECT},("bundle_id",)),
 "wait":obj({"selector":SEL,"timeout_seconds":num(0,20)},("selector",)),
 "scroll_find":obj({"selector":SEL,"direction":string(enum=["up","down","left","right"]),"max_swipes":num(0,10,"integer")},("selector",)),
 "collect_list":obj({"row_type":string(),"max_pages":num(1,10,"integer"),"end_selector":SEL}),
 "doctor":obj({}),"ready":obj({"screenshot":BOOL}),"metrics":obj({}),
 "setup":obj({"action":string(enum=["discover","fetch","configure","build","start","stop","status"]),"udid":string(),"team_id":string(),"bundle_id":string(),"source_dir":string(max_length=4096),"local_port":num(1024,65535,"integer"),"device_port":num(1024,65535,"integer"),"job_id":string()},("action",))
}
# Each batch operation carries the same closed argument schema as its standalone tool.
BATCH_OPS=["tap","swipe","type_text","launch_app","press_button","wait","observe","scroll_find"]
SCHEMAS["batch"]=obj({"steps":{"type":"array","minItems":1,"maxItems":20,"items":{"oneOf":[obj({"op":{"type":"string","const":op},"args":SCHEMAS[op]},("op","args")) for op in BATCH_OPS]}}},("steps",))
DESCRIPTIONS={
 "doctor":"Diagnose local Xcode, USB devices, signing prerequisites and WDA health without changing the phone. Start here for setup.",
 "setup":"Manage WDA checkout, explicit signing config, nonblocking build/run jobs and loopback USB forwarding. Read iphone-wda-setup skill. Never uninstalls apps.",
 "ready":"Prove status.ready, usable session, viewport and current source; optionally test screenshot. Only this successful check establishes READY.",
 "observe":"Fresh compact phone controls or native WDA screenshot with iPhone point viewport and observation_id. Fast tree skips expensive visibility; geometry does not prove hittability.",
 "find":"Query exact semantic fields or a WDA predicate directly without a whole tree. Returns matches and rectangles; duplicates are explicit.",
 "tap":"Resolve unique, on-screen, hittable target and tap; optionally wait for an expected selector and observe in one call. Coordinate taps require fresh matching observation_id.",
 "swipe":"Short drag, verify content change, then at most one native swipe fallback. Stops on no progress. A custom region requires observation_id. Direction names describe finger movement.",
 "type_text":"Enter Unicode into a verified editable field and require exact value readback. Stops before submit on mismatch. Newlines need explicit multiline intent; submit defaults false.",
 "press_button":"Press home/volumeup/volumedown then return current state. No automatic business verification.",
 "launch_app":"Activate an app by verified bundle ID; verify foreground app and optionally expected page in one call.",
 "wait":"Bounded semantic presence polling for expected target. Presence is a UI postcondition, not proof of business correctness.",
 "batch":"Up to 20 known steps in one model round trip. Validate all arguments before actions; stop on failed postcondition, uncertainty or unverified mutation.",
 "scroll_find":"Bounded scroll until one semantic target is on screen and hittable; stop on ambiguity or no progress.",
 "collect_list":"Collect/deduplicate accessibility rows over bounded pages. Returns evidence and explicit coverage limits; always requires reconciliation before declaring business completeness.",
 "metrics":"In-process HTTP and tool timing summary without text, app data or images. Model response latency is not measured here."
}
READS={"doctor","observe","find","wait","metrics"}
TOOLS=[{"name":"wda_"+name,"description":DESCRIPTIONS[name],"inputSchema":schema,
        "annotations":{"readOnlyHint":name in READS,"destructiveHint":name not in READS,"idempotentHint":name in READS,"openWorldHint":False}} for name,schema in SCHEMAS.items()]


def validate(value,schema,path="arguments"):
    if "oneOf" in schema:
        matches=0
        for candidate in schema["oneOf"]:
            try:validate(value,candidate,path);matches+=1
            except WDAError:pass
        if matches!=1:raise WDAError("invalid_argument",f"{path} must match exactly one allowed operation schema.")
        return
    kind=schema.get("type")
    valid={"object":lambda:isinstance(value,dict),"array":lambda:isinstance(value,list),"string":lambda:isinstance(value,str),"boolean":lambda:isinstance(value,bool),"number":lambda:not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value),"integer":lambda:not isinstance(value,bool) and isinstance(value,int)}
    if kind and not valid[kind]():raise WDAError("invalid_argument",f"{path} must be {kind}.")
    if "const" in schema and value!=schema["const"]:raise WDAError("invalid_argument",f"Invalid {path} operation.")
    if "enum" in schema and value not in schema["enum"]:raise WDAError("invalid_argument",f"Invalid {path} option.")
    if kind=="object":
        props=schema.get("properties",{})
        if schema.get("additionalProperties") is False and set(value)-set(props):raise WDAError("invalid_argument",f"Unknown fields in {path}: {', '.join(sorted(set(value)-set(props)))}.")
        if set(schema.get("required",[]))-set(value):raise WDAError("invalid_argument",f"Missing required fields in {path}.")
        if len(value)<schema.get("minProperties",0):raise WDAError("invalid_argument",f"{path} cannot be empty.")
        for k,v in value.items():
            if k in props:validate(v,props[k],path+"."+k)
    if kind in ("number","integer") and not schema.get("minimum",-math.inf)<=value<=schema.get("maximum",math.inf):raise WDAError("invalid_argument",f"{path} is out of range.")
    if kind=="string" and not schema.get("minLength",0)<=len(value)<=schema.get("maxLength",100000):raise WDAError("invalid_argument",f"{path} has invalid length.")
    if kind=="array":
        if not schema.get("minItems",0)<=len(value)<=schema.get("maxItems",100000):raise WDAError("invalid_argument",f"{path} has invalid number of items.")
        for i,v in enumerate(value):validate(v,schema["items"],f"{path}[{i}]")


def validate_semantics(name,args):
    from wda_controller import predicate
    for k in ("selector","expect","end_selector"):
        if k in args:predicate(args[k])
    if name=="tap":
        semantic="selector" in args
        coords=all(k in args for k in ("x","y","observation_id"))
        if semantic==coords or (semantic and any(k in args for k in ("x","y"))):
            raise WDAError("invalid_argument","tap requires either selector or x/y/observation_id.")
    if name=="swipe" and "region" in args and "observation_id" not in args:raise WDAError("invalid_argument","Custom swipe region requires observation_id.")
    if name=="type_text":
        if any(ord(c)<32 and c not in ("\n","\r") or ord(c)==127 for c in args["text"]):raise WDAError("invalid_argument","Control characters are not allowed in text.")
        if any(c in args["text"] for c in ("\n","\r")) and not args.get("allow_newlines",False):raise WDAError("newline_requires_intent","Line breaks require explicit multiline intent.")
    if name=="launch_app" and not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+",args["bundle_id"]):raise WDAError("invalid_argument","Use the app's verified bundle ID.")
    if name=="batch":
        for step in args["steps"]:validate_semantics(step["op"],step["args"])


class Runtime:
    def __init__(self,state_dir=None,base_url=None):
        root=state_dir or os.environ.get("WDA_STATE_DIR") or str(Path.home()/".local/share/iphone-use-wda")
        self.state_dir=Path(root).expanduser().resolve();self.state_dir.mkdir(mode=0o700,parents=True,exist_ok=True);self.state_dir.chmod(0o700)
        # Configuration is private runtime data, never a project file.
        configured_url=None
        config=self.state_dir/"config.json"
        if config.is_file():
            try:configured_url="http://127.0.0.1:"+str(json.loads(config.read_text()).get("local_port",18100))
            except (ValueError,OSError):pass
        self.base_url=base_url or os.environ.get("WDA_URL") or configured_url or "http://127.0.0.1:18100"
        self.client=WDAClient(self.base_url)
        self.phone=PhoneController(self.client,self.state_dir)
        self.setup_manager=SetupManager(self.state_dir,self.base_url)

    def call(self,name,args):
        # WDA has one active session. Serialize independent Codex MCP processes
        # sharing this runtime, and share only this plugin's session identity.
        if not isinstance(name,str) or not name.startswith("wda_") or name[4:] not in SCHEMAS:raise WDAError("unknown_tool","Unknown WDA tool.")
        validate(args,SCHEMAS[name[4:]]);validate_semantics(name[4:],args)
        lock_path=self.state_dir/"operation.lock"
        cache_path=self.state_dir/"session.json"
        with lock_path.open("a") as lock:
            lock_path.chmod(0o600)
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise WDAError("device_busy","Another iPhone WDA operation is running. Wait for it to finish before continuing; no action was executed.")
            try:
                if cache_path.is_file() and hasattr(self.client,"session_id"):
                    try:
                        cached=json.loads(cache_path.read_text())
                        sid=cached.get("session_id","")
                        if cached.get("url")==self.base_url and isinstance(sid,str) and re.fullmatch(r"[A-Za-z0-9-]{1,128}",sid):self.client.session_id=sid
                    except (ValueError,OSError,AttributeError):pass
                return self._call(name,args)
            finally:
                sid=getattr(self.client,"session_id",None)
                if sid:
                    task_temp=self.state_dir/("session-"+str(os.getpid())+".tmp")
                    try:
                        fd=os.open(task_temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                        with os.fdopen(fd,"w") as stream:json.dump({"url":self.base_url,"session_id":sid},stream)
                        os.replace(task_temp,cache_path)
                    finally:
                        if task_temp.exists():task_temp.unlink()
                elif hasattr(self.client,"session_id") and cache_path.exists():cache_path.unlink()
                fcntl.flock(lock,fcntl.LOCK_UN)

    def _call(self,name,args):
        if not isinstance(name,str) or not name.startswith("wda_") or name[4:] not in SCHEMAS:raise WDAError("unknown_tool","Unknown WDA tool.")
        op=name[4:];validate(args,SCHEMAS[op]);validate_semantics(op,args)
        start=time.monotonic();error=None
        try:
            if op=="doctor":return self.setup_manager.doctor()
            if op=="setup":
                manager=self.setup_manager
                candidate_url=self.base_url
                if args["action"]=="configure" and "local_port" in args:
                    candidate_url="http://127.0.0.1:"+str(args["local_port"])
                    manager=SetupManager(self.state_dir,candidate_url)
                result=manager.setup(**args)
                if result.get("ok") and args["action"] in ("stop","configure","start"):
                    self.client.close();self.client.session_id=None;self.phone.snapshots.clear()
                if result.get("ok") and args["action"]=="configure" and "local_port" in args:
                    self.base_url=candidate_url;self.setup_manager=manager
                    self.client=WDAClient(self.base_url);self.phone.client=self.client
                return result
            if op=="ready":
                status=self.client.request("GET","/status").get("value") or {}
                if status.get("ready") is not True:raise WDAError("not_ready","WDA is not accepting commands. Run wda_doctor and inspect setup status.")
                if self.client.request("GET","/wda/locked").get("value") is not False:raise WDAError("phone_locked","Unlock the iPhone yourself, keep it awake, and verify READY again.")
                sid=self.client.ensure_session()
                observation=self.phone.observe("both" if args.get("screenshot",True) else "tree")
                if observation.get("total_nodes",0)==0 and self.setup_manager.mirroring_running():raise WDAError("mirroring_conflict","iPhone Mirroring is running and WDA exposes an empty phone tree. Quit Mirroring, unlock if needed, then verify READY again.")
                return {"ready":True,"proof":{"status_ready":True,"phone_unlocked":True,"session_usable":bool(sid),"source_readable":True,"viewport_readable":True,"screenshot_readable":args.get("screenshot",True)},"observation":observation}
            if op=="metrics":
                records=self.phone.tool_records
                return {**self.client.metrics(),"tools":{"count":len(records),"seconds":round(sum(r["seconds"] for r in records),4),"errors":sum(bool(r["error"]) for r in records)},"latency_scope":"This plugin measures HTTP and tool execution only. It cannot measure or eliminate host/model response delays."}
            if op in ("tap","swipe","type_text","launch_app","press_button","batch","scroll_find","collect_list"):
                if self.client.request("GET","/wda/locked").get("value") is not False:raise WDAError("phone_locked","Unlock the iPhone yourself before operations; observe again afterward.")
            return getattr(self.phone,op)(**args)
        except WDAError as exc:error=exc.code;raise
        except (ValueError,TypeError) as exc:error="invalid_argument";raise WDAError(error,str(exc)) from exc
        finally:self.phone.tool_records.append({"tool":name,"seconds":round(time.monotonic()-start,4),"error":error})

    def close(self):self.client.close()


def result_content(data):
    content=[{"type":"text","text":json.dumps(data,ensure_ascii=False,allow_nan=False)}]
    # Direct image content supports visual inspection without another file-tool round trip.
    image=data.get("image") or data.get("observation",{}).get("image")
    if not image and data.get("results"):
        last=data["results"][-1];image=last.get("image") or last.get("observation",{}).get("image")
    if image and Path(image["path"]).is_file():content.append({"type":"image","data":base64.b64encode(Path(image["path"]).read_bytes()).decode(),"mimeType":"image/png"})
    return {"content":content,"structuredContent":data,"isError":"error" in data}


def serve(runtime):
    for line in sys.stdin:
        request=None
        try:
            if len(line)>1024*1024:raise ValueError("Request exceeds 1 MiB")
            request=json.loads(line,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
            if not isinstance(request,dict) or request.get("jsonrpc")!="2.0" or not isinstance(request.get("method"),str):raise ValueError("Invalid request")
            if "id" not in request:continue
            ident=request["id"]
            if isinstance(ident,bool) or not isinstance(ident,(str,int)):raise ValueError("Invalid identifier")
            params=request.get("params",{})
            if not isinstance(params,dict):raise WDAError("invalid_argument","params must be an object.")
            method=request["method"]
            if method=="initialize":
                offered=params.get("protocolVersion")
                result={"protocolVersion":offered if offered in PROTOCOLS else PROTOCOLS[0],"capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"iphone-use-wda","version":VERSION},"instructions":"Read iphone-wda-setup before setup, iphone-wda-use for tasks. READY requires status, session and observation. Use compound tools with expected postconditions; never replay uncertain mutations."}
            elif method=="ping":result={}
            elif method=="tools/list":result={"tools":TOOLS}
            elif method=="tools/call":
                try:
                    args=params.get("arguments",{})
                    result=result_content(runtime.call(params.get("name"),args))
                except WDAError as exc:result=result_content({"error":exc.as_dict()})
                except Exception as exc:
                    print("iphone-use-wda tool failure: "+type(exc).__name__,file=sys.stderr)
                    result=result_content({"error":{"code":"internal_error","message":"Local tool failed; inspect setup status or local stderr.","uncertain":True}})
            else:
                print(json.dumps({"jsonrpc":"2.0","id":ident,"error":{"code":-32601,"message":"Method not found"}}),flush=True);continue
            response={"jsonrpc":"2.0","id":ident,"result":result}
        except WDAError as exc:response={"jsonrpc":"2.0","id":request.get("id") if isinstance(request,dict) else None,"error":{"code":-32602,"message":str(exc)}}
        except (ValueError,TypeError,KeyError):response={"jsonrpc":"2.0","id":request.get("id") if isinstance(request,dict) else None,"error":{"code":-32700 if request is None else -32600,"message":"Parse error" if request is None else "Invalid request"}}
        print(json.dumps(response,ensure_ascii=False,allow_nan=False),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--state-dir");parser.add_argument("--url");parser.add_argument("--doctor",action="store_true");parser.add_argument("--ready",action="store_true")
    args=parser.parse_args();runtime=Runtime(args.state_dir,args.url)
    try:
        if args.doctor or args.ready:
            try:data=runtime.call("wda_doctor" if args.doctor else "wda_ready",{})
            except WDAError as exc:data={"error":exc.as_dict()}
            print(json.dumps(data,ensure_ascii=False));return 1 if "error" in data else 0
        serve(runtime);return 0
    finally:runtime.close()


if __name__=="__main__":sys.exit(main())
