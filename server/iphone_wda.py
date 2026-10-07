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
from wda_apps import AppCatalog
from wda_screen import ScreenHub

VERSION="0.1.7"
SCREEN_URI="ui://iphone-use-wda/phone-0.1.7.html"
SCREEN_META={"ui":{"csp":{"connectDomains":[],"resourceDomains":[]},"prefersBorder":False},"openai/ui":{"availableDisplayModes":["fullscreen"],"preferredDisplayMode":"fullscreen"}}
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
SEL=obj({
 "label":string("Exact accessibility label copied from fresh nodes; real newlines and punctuation are preserved automatically. Do not use partial text.",max_length=1000),
 "name":string("Exact accessibility identifier/name copied from fresh nodes; combine with label/type to disambiguate.",max_length=1000),
 "value":string("Exact current accessibility value; not the text to enter. Omit values that change asynchronously.",max_length=1000),
 "type":string("Exact element type, e.g. Button or XCUIElementTypeButton. Not an application bundle ID.",max_length=1000),
 "enabled":{"oneOf":[{"type":"boolean"},{"type":"string","enum":["true","false"]}],"description":"Optional exact enabled filter; accepts boolean or the tree string true/false. This does not prove hittability."},
 "predicate":string("Advanced NSPredicate query used alone. Cannot be combined with label/name/value/type/enabled. Prefer exact fields so text is safely encoded.",max_length=2000)})
SEL["description"]="Choose exact label/name/value/type/enabled fields, or a standalone predicate. Do not copy rect, visible, in_viewport or other observation fields into selector. Target must match uniquely."
SEL["examples"]=[{"label":"返回","type":"Button","enabled":True}]
SEL["minProperties"]=1
OBS=string("Post-action output, default none. Use tree/both when the next decision needs the resulting page; this is shared next-step context, not mandatory proof of this action. screenshot returns an image. Explicit expect/verify controls verification separately.",enum=["none","tree","screenshot","both"])
OBS["default"]="none"
EXPECT={"expect":SEL,"observe":OBS}
VERIFY={"type":"boolean","default":False,"description":"Opt in to this operation's result check. Default false executes once and defers checking to the next required observation or final key checkpoint. Never blindly replay an uncertain mutation."}
REGION=obj({k:num(0 if k in ("x","y") else 1,10000) for k in ("x","y","width","height")},("x","y","width","height"))
REGION["description"]="Scroll rectangle in iPhone points, not screenshot pixels. observation_id is optional. Omit region for the central area, or use the actual list bounds. With verify=true, the region must fit current viewport and native modal bounds."
SCHEMAS={
 "observe":obj({"mode":string("Standalone observation output, default tree. Use mode here; observe is a post-action option on mutation tools. none is not a standalone observation mode.",enum=["tree","screenshot","both"]),"include_invisible":BOOL,"max_nodes":num(1,500,"integer"),"expensive_visibility":BOOL}),
 "find":obj({"selector":SEL,"limit":num(1,30,"integer")},("selector",)),
 "tap":obj({"selector":SEL,"x":num(0,10000),"y":num(0,10000),"observation_id":string("Optional ID from this Runtime. Checks app/viewport context, not whole-page pixel equality or age."),**EXPECT}),
 "swipe":obj({"direction":string("Finger movement; up usually reveals later rows. Default up.",enum=["up","down","left","right"]),"region":REGION,"observation_id":string("Optional ID from this Runtime; checks app/viewport context, not numeric/carousel text changes or age."),"expect":SEL,"verify":{**VERIFY,"description":"Default false performs one gesture without XML progress reads or fallback. True checks stable row/anchor geometry progress and permits bounded alternatives. Numeric refresh alone is not progress."},"max_attempts":num(1,2,"integer"),"observe":OBS}),
 "type_text":obj({"selector":SEL,"text":string(max_length=10000),"allow_newlines":BOOL,"submit":BOOL,"replace":BOOL,"verify":{**VERIFY,"description":"Default false enters the full intended text once without value readback. True checks exact value and stops before submit on mismatch. Secure fields require user takeover."},**EXPECT},("selector","text")),
 "press_button":obj({"name":string(enum=["home","volumeup","volumedown"]),"verify":VERIFY,**EXPECT},("name",)),
 "launch_app":obj({"bundle_id":string(),"verify":VERIFY,**EXPECT},("bundle_id",)),
 "wait":obj({"selector":SEL,"timeout_seconds":num(0,20)},("selector",)),
 "scroll_find":obj({"selector":SEL,"direction":string(enum=["up","down","left","right"]),"max_swipes":num(0,10,"integer")},("selector",)),
 "collect_list":obj({"row_type":string(),"max_pages":num(1,10,"integer"),"end_selector":SEL}),
 "apps":obj({"query":string(max_length=100),"country":string(max_length=2),"source":string(enum=["auto","catalog","installed","apple"]),"limit":num(1,30,"integer")},("query",)),
 "doctor":obj({}),"ready":obj({"screenshot":{"type":"boolean","default":True,"description":"Also verify screenshot; false retains status/session/source/viewport/unlock checks."},"recover":{"type":"boolean","default":True,"description":"Normal task startup: omit or set true, so a persistent local.pid/XCTest fault can queue one bounded restart of a proven owned WDA. Use false only for an explicitly requested diagnostic/no-restart check, not a routine precheck. False is respected and returns ready=false, state=recovery_required when restart is needed; queued recovery returns state=recovering. Neither state proves readiness."}}),"metrics":obj({}),
 "setup":obj({"action":string(enum=["discover","fetch","configure","build","start","stop","status"]),"udid":string(),"team_id":string(),"bundle_id":string(),"source_dir":string(max_length=4096),"local_port":num(1024,65535,"integer"),"device_port":num(1024,65535,"integer"),"job_id":string()},("action",))
}
# Each batch operation carries the same closed argument schema as its standalone tool.
BATCH_OPS=["tap","swipe","type_text","launch_app","press_button","wait","observe","scroll_find"]
SCHEMAS["batch"]=obj({"steps":{"type":"array","minItems":1,"maxItems":20,"items":{"oneOf":[obj({"op":{"type":"string","const":op},"args":SCHEMAS[op]},("op","args")) for op in BATCH_OPS]}}},("steps",))
SCHEMAS["ready"]["examples"]=[{"recover":True,"screenshot":False}]
SCHEMAS["screen"]=obj({"action":string("Default open displays the live iPhone sidebar. Pause before password/Face ID takeover; resume only after the user confirms completion.",enum=["open","pause","resume"])})
SCHEMAS["screen_frame"]=obj({"after_seq":num(0,9007199254740991,"integer"),"last_event_id":num(0,9007199254740991,"integer")})
DESCRIPTIONS={
 "doctor":"Diagnose local Xcode, USB devices, signing prerequisites and WDA health without changing the phone. Start here for setup.",
 "setup":"Manage WDA checkout, explicit signing config, nonblocking build/run jobs and loopback USB forwarding. Read iphone-wda-setup skill. Never uninstalls apps.",
 "ready":"Prepare the channel before phone tasks. Normally omit recover or set true; do not disable it for a routine precheck. Healthy output has ready=true. ready=false with state=recovering/recovery_required is a normal status result, not task success: follow recovery guidance and check READY again. Actual recovery refusal/failure remains an error. No phone action is replayed.",
 "observe":"Fresh compact phone controls or native WDA screenshot with iPhone point viewport and observation_id. Fast tree skips expensive visibility; geometry does not prove hittability.",
 "find":"Query exact semantic fields or a WDA predicate directly without a whole tree. Returns matches and rectangles; duplicates are explicit.",
 "tap":"Resolve a unique on-screen hittable selector, or tap point coordinates with optional contextual observation_id. Execute once optimistically; expect opts into a postcondition. Request tree/both if the next decision needs the new page.",
 "swipe":"Default: one fast gesture, no XML progress checks, observe=none. Optional region/observation_id. Use observe=tree/both to plan the next step; verify=true opts into bounded geometry progress checks/fallback. A verified no-progress result does not prove an empty or complete list; inspect the actual list or boundary instead of repeating.",
 "type_text":"Enter the full intended Unicode text once into a unique editable nonsecure field; no short-text trial or mandatory readback. verify=true opts into exact readback before submit; expect opts into a page postcondition. Newlines need explicit intent; submit defaults false. Never replay uncertain input/submission.",
 "press_button":"Home uses the dedicated WDA homescreen endpoint once; default skips foreground polling. verify=true checks SpringBoard for Home, expect can check a page. Volume effects cannot be semantically verified.",
 "launch_app":"Activate once using a resolved bundle ID, optimistically by default. verify=true polls foreground up to five seconds; expect checks the intended page. Request observation for the next decision. Never blindly replay uncertain activation.",
 "wait":"Bounded semantic presence polling for expected target. Presence is a UI postcondition, not proof of business correctness.",
 "batch":"Up to 20 known steps in one model round trip. Routine unverified actions continue optimistically with intermediate observe=none. Stop on actual error, failed explicit check, uncertainty or submission without an explicit result expectation. Observe the last step when the next decision needs page context.",
 "scroll_find":"Bounded scroll until one semantic target is on screen and hittable; stop on ambiguity or no progress.",
 "collect_list":"Collect/deduplicate accessibility rows over bounded pages. Returns evidence and explicit coverage limits; always requires reconciliation before declaring business completeness.",
 "metrics":"In-process HTTP and tool timing summary without text, app data or images. Model response latency is not measured here."
}
DESCRIPTIONS["apps"]="Resolve a real bundle ID by installed-device inventory, bundled verified aliases, or Apple's Search API. Query app name before launch instead of guessing. Store metadata does not prove installation; check installed_verified and publisher/country."
READS={"doctor","observe","find","wait","metrics","apps"}
READS.update(("screen","screen_frame"))
DESCRIPTIONS["screen"]="Open the live iPhone screen in the Codex side panel. No phone actions or UI controls. Pause the preview before password/Face ID user takeover; resume after explicit completion. READY also opens this view by default."
DESCRIPTIONS["screen_frame"]="App-only cached live preview and action cursor events. Never reads XML, starts sessions or occupies the phone operation lock."


def published_schema(name):
    if name!="batch":return SCHEMAS[name]
    # Codex's default schema compaction budget is 5KB. Deduplicate repeated
    # selectors/output options so it retains every op/args branch. Runtime
    # validation still uses the full closed SCHEMAS above, without $ref parsing.
    def compact(value,references=True):
        if references and value==SEL:return {"$ref":"#/$defs/selector"}
        if references and value==OBS:return {"$ref":"#/$defs/observe"}
        if isinstance(value,dict):return {k:compact(v,references) for k,v in value.items() if k not in ("description","examples")}
        if isinstance(value,list):return [compact(v,references) for v in value]
        return value
    schema=compact(SCHEMAS[name])
    schema["$defs"]={"selector":compact(SEL,False),"observe":compact(OBS,False)}
    return schema


TOOLS=[{"name":"wda_"+name,"description":DESCRIPTIONS[name],"inputSchema":published_schema(name),
        "annotations":{"readOnlyHint":name in READS,"destructiveHint":name not in READS,"idempotentHint":name in READS,"openWorldHint":False}} for name,schema in SCHEMAS.items()]
for tool in TOOLS:
    if tool["name"] in ("wda_ready","wda_screen"):
        tool["_meta"]={"ui":{"resourceUri":SCREEN_URI}}
    if tool["name"]=="wda_screen":
        tool.update(title="手机屏幕")
        tool["_meta"]["openai/ui"]={"entrypoints":[{"type":"thread"}]}
        tool["annotations"].update(readOnlyHint=False,destructiveHint=False,idempotentHint=True)
    if tool["name"]=="wda_screen_frame":tool["_meta"]={"ui":{"visibility":["app"]}}


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
    from wda_controller import predicate
    for k in ("selector","expect","end_selector"):
        if k in args:predicate(args[k])
    if name=="tap":
        semantic="selector" in args
        coords=all(k in args for k in ("x","y"))
        if semantic==coords or (semantic and any(k in args for k in ("x","y"))):
            raise WDAError("invalid_argument","tap requires either selector or x/y; observation_id is optional.")
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
        self.apps=AppCatalog(self.state_dir,self.setup_manager)
        self.screen=ScreenHub(self.state_dir)
        self.phone.screen=self.screen

    def call(self,name,args):
        # WDA has one active session. Serialize independent Codex MCP processes
        # sharing this runtime, and share only this plugin's session identity.
        if not isinstance(name,str) or not name.startswith("wda_") or name[4:] not in SCHEMAS:raise WDAError("unknown_tool","Unknown WDA tool.")
        validate(args,SCHEMAS[name[4:]]);validate_semantics(name[4:],args)
        # Cached preview polling does not share the WDA action/session lock.
        if name=="wda_screen_frame":return self.screen.frame(**args)
        if name=="wda_screen":
            action=args.get("action","open")
            if action=="pause":self.screen.set_paused(True)
            elif action=="resume":self.screen.set_paused(False)
            return self.screen.start()
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

    def ready_once(self,screenshot):
        status=self.client.request("GET","/status").get("value") or {}
        if status.get("ready") is not True:raise WDAError("not_ready","WDA is not accepting commands. Run wda_doctor and inspect setup status.")
        if self.client.request("GET","/wda/locked").get("value") is not False:raise WDAError("phone_locked","Unlock the iPhone yourself, keep it awake, and verify READY again.")
        sid=self.client.ensure_session()
        observation=self.phone.observe("both" if screenshot else "tree")
        if observation.get("total_nodes",0)==0 and self.setup_manager.mirroring_running():raise WDAError("mirroring_conflict","iPhone Mirroring is running and WDA exposes an empty phone tree. Quit Mirroring, unlock if needed, then verify READY again.")
        return {"ready":True,"state":"ready","proof":{"status_ready":True,"phone_unlocked":True,"session_usable":bool(sid),"foreground_resolved":True,"source_readable":True,"viewport_readable":True,"screenshot_readable":screenshot},"observation":observation}

    def recovering_result(self,info,screenshot,recover,retried=False,cause=None):
        info=dict(info)
        job_id=info["job_id"]
        self.client.close();self.client.session_id=None;self.phone.snapshots.clear()
        info.update(status_tool="wda_setup",status_arguments={"action":"status","job_id":job_id},next_tool="wda_ready",next_arguments={"screenshot":screenshot,"recover":recover},retry_after_seconds=1,replay_action=False)
        result={"ready":False,"state":"recovering","message":"Owned WDA recovery is running in the background. Poll the supplied setup job; once the service is reachable, run READY again. No phone task may proceed until ready=true. Do not replay the failed user action.","action_executed":False,"category":"channel_runtime","session_read_retried":retried,"recovery":info}
        if cause is not None:result["cause"]=cause.as_dict()
        return result

    def ready(self,screenshot=True,recover=True):
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
            self.client.close();self.client.session_id=None;self.phone.snapshots.clear()
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
                return {"ready":False,"state":"recovery_required","reason":"recovery_disabled","message":"The WDA/XCTest channel needs recovery, but this call explicitly disabled service restart. No recovery was started. Resume with recover=true only when allowed by the current user instructions.","action_executed":False,"category":"channel_runtime","session_read_retried":retried,"cause":original.as_dict(),"recovery":{"state":"disabled","next_tool":"wda_ready","next_arguments":{"screenshot":screenshot,"recover":True},"permission_note":"Honor any user instruction forbidding restart; do not automatically override it.","replay_action":False}}
            raise original
        info=dict(recovery.get("recovery") or {})
        job_id=recovery.get("job_id") or info.get("job_id")
        if recovery.get("ok") and job_id:
            info["job_id"]=job_id
            return self.recovering_result(info,screenshot,recover,retried,original)
        info.update(next_steps=recovery.get("next_steps",[]),replay_action=False)
        raise WDAError("wda_recovery_required","Automatic WDA recovery was not started: "+str(recovery.get("error","service ownership could not be proven")),details={"ready":False,"action_executed":False,"category":"channel_runtime","session_read_retried":retried,"cause":original.as_dict(),"recovery":info})

    def _call(self,name,args):
        if not isinstance(name,str) or not name.startswith("wda_") or name[4:] not in SCHEMAS:raise WDAError("unknown_tool","Unknown WDA tool.")
        op=name[4:];validate(args,SCHEMAS[op]);validate_semantics(op,args)
        start=time.monotonic();error=None;activity=None
        try:
            if op not in ("doctor","apps","setup","metrics"):
                try:activity=self.screen.begin(op)
                except Exception:pass
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
                    self.client.close();self.client.session_id=None;self.phone.snapshots.clear()
                if result.get("ok") and args["action"]=="configure" and "local_port" in args:
                    self.base_url=candidate_url;self.setup_manager=manager
                    self.apps.setup_manager=manager
                    self.client=WDAClient(self.base_url);self.phone.client=self.client
                return result
            if op=="ready":
                try:self.screen.start()
                except Exception:pass
                return self.ready(**args)
            if op=="metrics":
                records=self.phone.tool_records
                return {**self.client.metrics(),"tools":{"count":len(records),"seconds":round(sum(r["seconds"] for r in records),4),"errors":sum(bool(r["error"]) for r in records)},"latency_scope":"This plugin measures HTTP and tool execution only. It cannot measure or eliminate host/model response delays."}
            if op in ("tap","swipe","type_text","launch_app","press_button","batch","scroll_find","collect_list"):
                if self.client.request("GET","/wda/locked").get("value") is not False:raise WDAError("phone_locked","Unlock the iPhone yourself before operations; observe again afterward.")
            return getattr(self.phone,op)(**args)
        except WDAError as exc:
            error=exc.code
            if exc.code=="phone_locked" or (exc.code=="not_editable" and exc.details.get("secure_field")):
                try:self.screen.set_paused(True)
                except Exception:pass
            if op in READS:
                exc.details.setdefault("action_executed",False)
            if self.channel_fault(exc):
                exc.details.update(category="channel_runtime",recovery={"tool":"wda_ready","arguments":{"screenshot":False},"replay_action":False})
            raise
        except (ValueError,TypeError) as exc:error="invalid_argument";raise WDAError(error,str(exc)) from exc
        finally:
            if activity is not None:
                try:self.screen.end(activity)
                except Exception:pass
            self.phone.tool_records.append({"tool":name,"seconds":round(time.monotonic()-start,4),"error":error})

    def close(self):self.screen.close();self.client.close()


def result_content(data):
    content=[{"type":"text","text":json.dumps(data,ensure_ascii=False,allow_nan=False)}]
    # Direct image content supports visual inspection without another file-tool round trip.
    image=data.get("image") or data.get("observation",{}).get("image")
    if not image and isinstance(data.get("error"),dict):image=data["error"].get("observation",{}).get("image")
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
                result={"protocolVersion":offered if offered in PROTOCOLS else PROTOCOLS[0],"capabilities":{"tools":{"listChanged":False},"resources":{"listChanged":False}},"serverInfo":{"name":"iphone-use-wda","version":VERSION},"instructions":"The live iPhone screen opens in the side panel with READY; use wda_screen to reopen it. Before password/Face ID takeover call wda_screen(action=pause); after user confirmation call resume, then continue. Widget frames are display context, never substitute for a model observation or final verification. Read iphone-wda-setup before setup and iphone-wda-use for tasks. Normal startup uses wda_ready with recover=true or omitted; only ready=true permits tasks. Reuse READY's observation. For recovering follow its setup job until service is ready, then READY again; respect explicit no-restart instructions. Resolve unknown bundle IDs with wda_apps. Execute routine actions optimistically: observe=none and verify=false are defaults, verified=false/verification_deferred=true is normal and does not require a separate verification call. If the next decision needs the resulting page, request observe=tree/both in the action and inspect previous success while planning that next step. Chain known steps in batch; explicit expect/verify opts into checking key outcomes. Verify final critical results before reporting completion. Retry or replan only after observing a definite failure; never replay uncertain input/submission or an already executed multi-step operation wholesale. No_scroll_progress from explicit verification does not prove empty/complete data. Standalone observation uses mode, mutation output uses observe. For passwords or Face ID ask the user to authenticate on iPhone, pause phone calls, then resume remaining work from fresh state after confirmation. Operation action_complete/verified fields do not mean the user's entire task is complete. Track all deliverables, give commentary progress and continue tools while work remains; final only after completion or a concrete blocker. For an unavailable MCP binding use the skill's direct Runtime fallback with the same operation lock."}
            elif method=="ping":result={}
            elif method=="tools/list":result={"tools":TOOLS}
            elif method=="resources/list":
                result={"resources":[{"uri":SCREEN_URI,"name":"iPhone WDA Screen","title":"手机屏幕","mimeType":"text/html;profile=mcp-app","_meta":SCREEN_META}]}
            elif method=="resources/read":
                if params.get("uri")!=SCREEN_URI:raise WDAError("invalid_argument","Unknown screen resource URI.")
                html=(Path(__file__).resolve().parents[1]/"assets/phone-screen.html").read_text()
                result={"contents":[{"uri":SCREEN_URI,"mimeType":"text/html;profile=mcp-app","text":html,"_meta":SCREEN_META}]}
            elif method=="tools/call":
                try:
                    args=params.get("arguments",{})
                    data=runtime.call(params.get("name"),args)
                    result={"content":[],"structuredContent":data,"isError":False} if params.get("name")=="wda_screen_frame" else result_content(data)
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
            print(json.dumps(data,ensure_ascii=False));return 1 if "error" in data or (args.ready and data.get("ready") is not True) else 0
        serve(runtime);return 0
    finally:runtime.close()


if __name__=="__main__":sys.exit(main())
