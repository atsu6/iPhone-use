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
from wda_vision_controller import VisualPhoneController
from wda_setup import SetupManager
from wda_apps import AppCatalog

VERSION="0.1.3"
TOOL_PREFIX="wda_vision_"
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
ID=string("Optional screenshot reference for metadata. Not required, not time-limited or process-bound, and never triggers a pre-action screenshot/hash check.")
AFTER={"type":"boolean","default":True,"description":"Return an action-result screenshot, default true. Set false for an intermediate step whose targets are already known from the viewed screen; a batch supplies one final screenshot."}
REGION=obj({k:num(0 if k in ("x","y") else 1,10000) for k in ("x","y","width","height")},("x","y","width","height"))
REGION["description"]="Scrollable rectangle identified visually from the current screenshot, in iPhone points. Inspect foreground overlays and avoid the underlying page."
POINTS={"x":num(0,10000),"y":num(0,10000),"observation_id":ID,"observe":AFTER}
SCHEMAS={
 "doctor":obj({}),
 "setup":obj({"action":string(enum=["discover","fetch","configure","build","start","stop","status"]),"udid":string(),"team_id":string(),"bundle_id":string(),"source_dir":string(max_length=4096),"local_port":num(1024,65535,"integer"),"device_port":num(1024,65535,"integer"),"job_id":string()},("action",)),
 "ready":obj({"recover":{"type":"boolean","default":True,"description":"Normally omit or set true for bounded owned-service recovery. False only for explicitly requested no-restart diagnostics. READY always returns a screenshot; inspect it before acting."}}),
 "observe":obj({}),
 "tap":obj(POINTS,("x","y")),
 "long_press":obj({**POINTS,"duration":num(.1,2)},("x","y")),
 "swipe":obj({"observation_id":ID,"direction":string("Finger movement. Up usually reveals later rows; visually verify direction and actual progress.",enum=["up","down","left","right"]),"region":REGION,"observe":AFTER}),
 "type_text":obj({"text":string("Original Unicode text to enter into the visually confirmed focused input; no automatic replace or submit.",max_length=10000),"observation_id":ID,"focused_input_confirmed":{"type":"boolean","description":"Optional legacy parameter, no confirmation gate. Choose the input from the viewed screen. Authentication belongs to the user."},"allow_newlines":BOOL,"multiline_confirmed":BOOL,"observe":AFTER},("text",)),
 "press_button":obj({"name":string(enum=["home","volumeup","volumedown"]),"observation_id":ID,"observe":AFTER},("name",)),
 "launch_app":obj({"bundle_id":string(),"observation_id":ID,"observe":AFTER},("bundle_id",)),
 "wait":obj({"seconds":num(0,3)}),
 "read_page":obj({"reason":string("Optional note for XML page-data reading. Use only when it saves time; never use XML to choose action targets. A data-only read does not require another screenshot.",max_length=1000),"max_nodes":num(1,500,"integer")}),
 "apps":obj({"query":string(max_length=100),"country":string(max_length=2),"source":string(enum=["auto","catalog","installed","apple"]),"limit":num(1,30,"integer")},("query",)),
 "metrics":obj({})
}
MUTATIONS={"tap","long_press","swipe","type_text","launch_app","press_button"}
BATCH_OPS=["observe","wait",*sorted(MUTATIONS)]
SCHEMAS["batch"]=obj({"steps":{"type":"array","minItems":1,"maxItems":20,"items":{"oneOf":[obj({"op":{"type":"string","const":op},"args":SCHEMAS[op]},("op","args")) for op in BATCH_OPS]}}},("steps",))
DESCRIPTIONS={
 "doctor":"Diagnose local Xcode, USB devices, signing prerequisites and WDA health. Use only for setup or an actual channel problem.",
 "setup":"Manage WDA setup/signing/build/start/recovery. Reuse an already healthy service and effective build. Status returns jobs as an array; service.ready tells whether to check READY without waiting for a long-lived Runner to succeed.",
 "ready":"Check status, unlock, session and one screenshot without XML. Normally recover=true. Inspect the returned screenshot and reuse it for the first action; no second observe is needed just to begin.",
 "observe":"Return one native iPhone screenshot plus viewport, pixel conversion and optional reference ID. Foreground app metadata is optional and never blocks a usable screenshot. No image hashes, TTL or repeated foreground/viewport checks. Reuse the latest already viewed screenshot for subsequent decisions.",
 "tap":"Tap screenshot-derived iPhone point x/y directly; no pre-action screenshot, hash or required ID. Returns the result screenshot by default; observe=false skips intermediate output.",
 "long_press":"Long-press a point already identified in a viewed screenshot. Optional ID is metadata only. Return screenshot by default; observe=false permits known compound actions.",
 "swipe":"Perform one drag in a visually selected list region; no hidden XML, progress scan, pre-action capture or forced per-gesture model round trip. Use a known batch for several gestures when appropriate and inspect its final screenshot.",
 "type_text":"Type original Unicode into the intended focused input without redundant confirmation parameters or pre-action reads. No XML locator, automatic replacement or submit. Newlines require explicit allow_newlines because Return may submit. Authentication belongs to the user.",
 "press_button":"Home or volume directly; no prior screenshot/ID needed for a fixed system button. Return screenshot by default, with foreground metadata when available; no repeated foreground polling.",
 "launch_app":"Activate a known bundle ID once directly, with no prior screenshot/ID or forced foreground polling. Return the result screenshot by default; inspect loading or prompts only when needed.",
 "wait":"Wait for the supplied short duration and return a screenshot; use only for an actual visible loading condition, never to align clocks or pass a freshness gate.",
 "batch":"Execute supplied known screen-grounded operations in one round trip, stopping only on an actual error. Intermediate mutation screenshots default to off within a batch; set observe=true explicitly when needed. Return one final screenshot. No forced one-step barrier. Do not invent targets on unseen pages. complete means steps executed, not the user's business task verified.",
 "read_page":"Optional XML page text/list reading when more efficient. Optional reason, no screenshot invalidation or forced recapture afterward. Returns data without geometry; actions remain based on viewed screenshots.",
 "apps":"Look up an unknown app bundle ID with installed inventory/catalog/Apple metadata. Reuse already verified IDs instead of repeating discovery.",
 "metrics":"HTTP and tool timing without phone text/images/account contents. Does not measure model latency."
}
READS={"doctor","observe","wait","read_page","metrics","apps"}
TOOLS=[{"name":TOOL_PREFIX+name,"description":DESCRIPTIONS[name],"inputSchema":schema,
        "annotations":{"readOnlyHint":name in READS,"destructiveHint":name not in READS,"idempotentHint":name in READS,"openWorldHint":False}} for name,schema in SCHEMAS.items()]


def validate(value,schema,path="arguments"):
    if "oneOf" in schema:
        if isinstance(value,dict) and "op" in value:
            # Surface the chosen batch step's precise argument error instead
            # of hiding it behind the union of unrelated operation schemas.
            chosen=[candidate for candidate in schema["oneOf"] if candidate.get("properties",{}).get("op",{}).get("const")==value["op"]]
            if len(chosen)==1:return validate(value,chosen[0],path)
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
        if schema.get("additionalProperties") is False and set(value)-set(props):raise WDAError("invalid_argument",f"Unknown fields in {path}: {', '.join(sorted(set(value)-set(props)))}. Use only the declared fields.",details={"action_executed":False,"argument_path":path,"unknown_fields":sorted(set(value)-set(props)),"allowed_fields":sorted(props),"recovery":{"next_step":"Correct these fields using the current tool schema, then call once; no device action was executed."}})
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
    if name=="type_text":
        if any(ord(c)<32 and c not in ("\n","\r") or ord(c)==127 for c in args["text"]):
            raise WDAError("invalid_argument","Control characters are not allowed in text.")
        if any(c in args["text"] for c in ("\n","\r")) and not args.get("allow_newlines",False):
            raise WDAError("newline_requires_intent","Line breaks require explicit allow_newlines because Return can submit.")
    if name=="launch_app" and not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+",args["bundle_id"]):
        raise WDAError("invalid_argument","Use the app's verified bundle ID.")
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
        self.phone=VisualPhoneController(self.client,self.state_dir)
        self.setup_manager=SetupManager(self.state_dir,self.base_url)
        self.apps=AppCatalog(self.state_dir,self.setup_manager)

    def call(self,name,args):
        # WDA has one active session. Serialize independent Codex MCP processes
        # sharing this runtime, and share only this plugin's session identity.
        if not isinstance(name,str) or not name.startswith(TOOL_PREFIX) or name[len(TOOL_PREFIX):] not in SCHEMAS:raise WDAError("unknown_tool","Unknown WDA tool.")
        validate(args,SCHEMAS[name[len(TOOL_PREFIX):]]);validate_semantics(name[len(TOOL_PREFIX):],args)
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

    @staticmethod
    def channel_fault(error):
        text=str(error).lower()
        if "not authorized for performing ui testing actions" in text or ("xctdaemonerrordomain" in text and "code=41" in text):
            return "xctest_authorization"
        if error.code=="wda_foreground_unavailable" or ("local.pid." in text and error.code=="stale element reference"):
            return "foreground_unavailable"
        return None

    def ready_once(self,screenshot=True):
        status=self.client.request("GET","/status").get("value") or {}
        if status.get("ready") is not True:raise WDAError("not_ready","WDA is not accepting commands. Run wda_vision_doctor and inspect setup status.")
        if self.client.request("GET","/wda/locked").get("value") is not False:raise WDAError("phone_locked","Unlock the iPhone yourself, keep it awake, and verify READY again.")
        sid=self.client.ensure_session()
        observation=self.phone.observe()
        return {"ready":True,"state":"ready","proof":{"status_ready":True,"phone_unlocked":True,"session_usable":bool(sid),"foreground_resolved":bool(observation.get("app")),"viewport_readable":True,"screenshot_readable":True,"xml_used":False},"visual_verification_required":True,"verification_required":"Inspect the screenshot for an unlocked usable page and any app authentication. Channel READY alone does not prove UI or task correctness.","observation":observation}

    def recovering_result(self,info,screenshot,recover,retried=False,cause=None):
        info=dict(info)
        job_id=info["job_id"]
        self.client.close();self.client.session_id=None;self.phone._invalidate()
        info.update(status_tool="wda_vision_setup",status_arguments={"action":"status","job_id":job_id},next_tool="wda_vision_ready",next_arguments={"recover":recover},retry_after_seconds=1,replay_action=False)
        result={"ready":False,"state":"recovering","message":"Owned WDA recovery is running in the background. Poll the supplied setup job; once the service is reachable, run READY again. No phone task may proceed until ready=true. Do not replay the failed user action.","action_executed":False,"category":"channel_runtime","session_read_retried":retried,"recovery":info}
        if cause is not None:result["cause"]=cause.as_dict()
        return result

    def ready(self,recover=True):
        screenshot=True
        pending=self.setup_manager.pending_recovery() if hasattr(self.setup_manager,"pending_recovery") else None
        if pending and pending.get("job_id"):
            # The old listener may still answer before the owned worker stops
            # it. Never return that soon-to-be-invalid session as READY.
            return self.recovering_result(pending,screenshot,recover)
        retried=False
        try:return self.ready_once(screenshot)
        except WDAError as error:
            original=error
        fault=self.channel_fault(original)
        if fault=="foreground_unavailable":
            # The one retry is a fresh session/source read, never a replay of
            # a click, key, submission or an element ID from an older session.
            self.client.close();self.client.session_id=None;self.phone._invalidate()
            retried=True
            try:
                result=self.ready_once(screenshot)
                result["recovery"]={"state":"read_recovered","session_recreated":True,"replayed_action":False}
                return result
            except WDAError as error:
                original=error;fault=self.channel_fault(error)
        if original.code=="phone_locked":raise original
        pending=self.setup_manager.pending_recovery() if hasattr(self.setup_manager,"pending_recovery") else None
        if pending and original.code in ("wda_unreachable","not_ready","invalid session id","wda_foreground_unavailable","stale element reference","unknown error","invalid argument"):
            recovery={"ok":True,"recovery":pending,"job_id":pending.get("job_id")}
        elif fault and recover:
            recovery=self.setup_manager.recover()
        else:
            if fault:
                return {"ready":False,"state":"recovery_required","reason":"recovery_disabled","message":"The WDA/XCTest channel needs recovery, but this call explicitly disabled service restart. No recovery was started. Resume with recover=true only when allowed by the current user instructions.","action_executed":False,"category":"channel_runtime","session_read_retried":retried,"cause":original.as_dict(),"recovery":{"state":"disabled","next_tool":"wda_vision_ready","next_arguments":{"recover":True},"permission_note":"Honor any user instruction forbidding restart; do not automatically override it.","replay_action":False}}
            raise original
        info=dict(recovery.get("recovery") or {})
        job_id=recovery.get("job_id") or info.get("job_id")
        if recovery.get("ok") and job_id:
            info["job_id"]=job_id
            return self.recovering_result(info,screenshot,recover,retried,original)
        info.update(next_steps=recovery.get("next_steps",[]),replay_action=False)
        raise WDAError("wda_recovery_required","Automatic WDA recovery was not started: "+str(recovery.get("error","service ownership could not be proven")),details={"ready":False,"action_executed":False,"category":"channel_runtime","session_read_retried":retried,"cause":original.as_dict(),"recovery":info})

    def _call(self,name,args):
        if not isinstance(name,str) or not name.startswith(TOOL_PREFIX) or name[len(TOOL_PREFIX):] not in SCHEMAS:raise WDAError("unknown_tool","Unknown WDA tool.")
        op=name[len(TOOL_PREFIX):];validate(args,SCHEMAS[op]);validate_semantics(op,args)
        start=time.monotonic();error=None
        try:
            if op=="doctor":return self.setup_manager.doctor()
            if op=="apps":return self.apps.lookup(**args)
            if op=="setup":
                manager=self.setup_manager
                candidate_url=self.base_url
                if args["action"]=="configure" and "local_port" in args:
                    candidate_url="http://127.0.0.1:"+str(args["local_port"])
                    manager=SetupManager(self.state_dir,candidate_url)
                result=manager.setup(**args)
                if result.get("ok") and args["action"] in ("stop","configure","start"):
                    self.client.close();self.client.session_id=None;self.phone._invalidate()
                if result.get("ok") and args["action"]=="configure" and "local_port" in args:
                    self.base_url=candidate_url;self.setup_manager=manager
                    self.apps.setup_manager=manager
                    self.client=WDAClient(self.base_url);self.phone.client=self.client
                return result
            if op=="ready":
                return self.ready(**args)
            if op=="metrics":
                records=self.phone.tool_records
                return {**self.client.metrics(),"tools":{"count":len(records),"seconds":round(sum(r["seconds"] for r in records),4),"errors":sum(bool(r["error"]) for r in records)},"latency_scope":"This plugin measures HTTP and tool execution only. It cannot measure or eliminate host/model response delays."}
            return getattr(self.phone,op)(**args)
        except WDAError as exc:
            error=exc.code
            if op in READS:
                exc.details.setdefault("action_executed",False)
            if self.channel_fault(exc):
                exc.details.update(category="channel_runtime",recovery={"tool":"wda_vision_ready","arguments":{"recover":True},"replay_action":False})
            raise
        except (ValueError,TypeError) as exc:error="invalid_argument";raise WDAError(error,str(exc)) from exc
        finally:self.phone.tool_records.append({"tool":name,"seconds":round(time.monotonic()-start,4),"error":error})

    def close(self):self.client.close()


def result_content(data):
    content=[{"type":"text","text":json.dumps(data,ensure_ascii=False,allow_nan=False)}]
    # Direct image content supports visual inspection without another file-tool round trip.
    image=data.get("image") or data.get("observation",{}).get("image")
    if not image and isinstance(data.get("error"),dict):image=data["error"].get("observation",{}).get("image")
    if not image and "error" not in data and data.get("results"):
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
                result={"protocolVersion":offered if offered in PROTOCOLS else PROTOCOLS[0],"capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"iphone-use-wda-vision","version":VERSION},"instructions":"Read iphone-wda-vision-use for efficient visual phone tasks and iphone-wda-vision-setup only for setup/recovery. Efficiency first: reuse the latest viewed screenshot, execute known actions directly and inspect their result. No whole-image hashes, ID expiration/process binding, pre-action recapture, duplicate metadata reads or clock-aligned waiting. observation_id is optional metadata. Fixed Home/app activation needs no previous screenshot ID. Mutations default to result screenshots; observe=false skips intermediates, and batch executes all known steps until an actual error then returns a final screenshot. Batch complete means execution, not user-task completion. Do not guess targets on an unseen page; inspect a screenshot when the next decision actually needs it. XML read_page is optional data-only reading, with optional reason and no forced recapture afterward. Input has no redundant focus/multiline confirmation gate; explicit allow_newlines is retained because Return can submit. User authenticates passwords/PIN/OTP/device unlock/Face ID; pause phone calls and use the available host question tool (request_user_input_async in Default), first option exactly 已完成继续. Async return or preselection is not confirmation; resume from a fresh screenshot only after the actual user completion answer. Never automatically replay uncertain/partly executed mutations. READY is run once per healthy channel, with recover=true normally; reuse its image for the first action. Poll setup jobs array/service readiness, not a nonexistent singular job or a long-lived Runner succeeded state. Continue all deliverables before final."}
            elif method=="ping":result={}
            elif method=="tools/list":result={"tools":TOOLS}
            elif method=="tools/call":
                try:
                    args=params.get("arguments",{})
                    result=result_content(runtime.call(params.get("name"),args))
                except WDAError as exc:result=result_content({"error":exc.as_dict()})
                except Exception as exc:
                    print("iphone-use-wda-vision tool failure: "+type(exc).__name__,file=sys.stderr)
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
            try:data=runtime.call("wda_vision_doctor" if args.doctor else "wda_vision_ready",{})
            except WDAError as exc:data={"error":exc.as_dict()}
            print(json.dumps(data,ensure_ascii=False));return 1 if "error" in data or (args.ready and data.get("ready") is not True) else 0
        serve(runtime);return 0
    finally:runtime.close()


if __name__=="__main__":sys.exit(main())
