"""Bounded iPhone operations with fresh state, semantic targeting and postconditions."""
import base64
import collections
import datetime as dt
from functools import wraps
import hashlib
import json
import math
from pathlib import Path
import re
import time
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import quote
from wda_client import WDAError

ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"


def fail(code, message, **details):
    raise WDAError(code, message, details=details)


def finite(value, name, low=0, high=10000):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not low <= value <= high:
        fail("invalid_argument", f"{name} must be a finite number in [{low}, {high}].")
    return value


def integer(value, name, low, high):
    finite(value, name, low, high)
    if not isinstance(value,int):
        fail("invalid_argument", f"{name} must be an integer.")
    return value


def action_result(function):
    @wraps(function)
    def wrapped(self,*args,**kwargs):
        before=self.accepted_actions
        try:return function(self,*args,**kwargs)
        except WDAError as error:
            if self.accepted_actions>before:
                error.details.update(action_executed=True,action_complete=False)
                if function.__name__=="swipe":
                    error.details.setdefault("attempts",self.accepted_actions-before)
                error.details.setdefault("verification_required","At least one phone action was accepted before the error. Read actual state; do not automatically replay the operation.")
            raise
    return wrapped


def predicate_literal(value):
    # NSPredicate rejects literal line breaks inside quoted strings. Its Unicode
    # escapes preserve exact text, including a literal backslash followed by n.
    return "".join("\\\\" if c=="\\" else "\\'" if c=="'" else f"\\u{ord(c):04x}" if ord(c)<32 or ord(c)==127 or c in "\u2028\u2029" else c for c in value)


def predicate(selector):
    if not isinstance(selector,dict) or not selector or set(selector)-{"label","name","value","type","enabled","predicate"}:
        fail("invalid_selector", "Use label/name/value/type/enabled, or a standalone WDA predicate.")
    if "predicate" in selector:
        if len(selector)!=1:
            fail("invalid_selector", "predicate cannot be mixed with exact fields.")
        result = selector["predicate"]
        if not isinstance(result,str) or not 1 <= len(result) <= 2000:
            fail("invalid_selector", "predicate must have 1..2000 characters.")
        return result
    clauses=[]
    for key,value in selector.items():
        if key=="enabled":
            if not isinstance(value,bool) and value not in ("true","false"):
                fail("invalid_selector","enabled must be a boolean or the exact tree string true/false.")
            literal="true" if value is True or value=="true" else "false"
            clauses.append("enabled == "+literal)
            continue
        if not isinstance(value,str) or not 1 <= len(value) <= 1000:
            fail("invalid_selector", "Selector fields must be nonempty strings up to 1000 characters.")
        if "\x00" in value:
            fail("invalid_selector", "Exact selector strings cannot contain NUL; NSPredicate cannot match that character reliably.")
        if key=="type" and not value.startswith("XCUIElementType"):
            value="XCUIElementType"+value
        escaped=predicate_literal(value)
        clauses.append(f"{key} == '{escaped}'")
    return " AND ".join(clauses)


class PhoneController:
    def __init__(self, client, state_dir):
        self.client, self.state_dir = client, Path(state_dir)
        self.snapshots=collections.OrderedDict()
        self.tool_records=collections.deque(maxlen=500)
        self.accepted_actions=0

    def post(self,path,payload,timeout=None,session=True):
        result=self.client.session("POST",path,payload,timeout=timeout) if session else self.client.request("POST",path,payload,timeout=timeout)
        self.accepted_actions+=1
        return result

    def viewport(self):
        v=self.client.session("GET", "/window/size")
        if not isinstance(v,dict):
            fail("invalid_response", "Missing viewport.")
        finite(v.get("width"),"width",1,10000);finite(v.get("height"),"height",1,10000)
        return {"width":v["width"],"height":v["height"],"units":"iPhone points"}

    def active_app(self,timeout=None):
        result=self.client.request("GET", "/wda/activeAppInfo",timeout=timeout).get("value") or {}
        app=result.get("bundleId")
        if not isinstance(app,str) or not app or app.startswith("local.pid."):
            fail("wda_foreground_unavailable","WDA cannot resolve a running foreground application. This is a WDA/XCTest channel problem, not a selector or schema error.",foreground_app=app,recovery={"tool":"wda_ready","arguments":{"screenshot":False},"replay_action":False})
        return app

    def tree(self, include_invisible=False, expensive_visibility=False):
        path="/source?format=xml"
        if not expensive_visibility:
            path+="&excluded_attributes=visible"
        raw=self.client.session("GET",path)
        if not isinstance(raw,str):
            fail("invalid_response", "WDA source is not XML text.")
        try:
            tree=ET.fromstring(raw)
        except ET.ParseError as exc:
            fail("invalid_response", f"WDA XML parse failed: {exc}.")
        viewport=self.viewport()
        nodes=[]
        for element in tree.iter():
            a=element.attrib
            if not any(a.get(k) for k in ("label","name","value")) and a.get("type") not in ("XCUIElementTypeAlert","XCUIElementTypeSheet"):
                continue
            try:
                rect={k:float(a.get(k,0)) for k in ("x","y","width","height")}
            except ValueError:
                continue
            if not all(math.isfinite(n) for n in rect.values()):
                continue
            intersects=rect["width"]>0 and rect["height"]>0 and rect["x"]<viewport["width"] and rect["y"]<viewport["height"] and rect["x"]+rect["width"]>0 and rect["y"]+rect["height"]>0
            if not include_invisible and (not intersects or a.get("visible")=="false"):
                continue
            if a.get("type") in ("XCUIElementTypeApplication","XCUIElementTypeWindow"):
                continue
            node={k:a[k] for k in ("type","name","label","value","enabled","visible") if k in a}
            node["rect"]=rect;node["in_viewport"]=intersects
            nodes.append(node)
        return nodes,viewport

    def region_nodes(self,nodes,region=None):
        if region:
            x,y,w,h=region["x"],region["y"],region["width"],region["height"]
            nodes=[n for n in nodes if x<=n["rect"]["x"]+n["rect"]["width"]/2<=x+w and y<=n["rect"]["y"]+n["rect"]["height"]/2<=y+h]
        # Ignore status bar clocks/battery values. Compare visible content and geometry.
        nodes=[n for n in nodes if n["type"]!="XCUIElementTypeStatusBar" and n["rect"]["y"]>=45]
        return nodes

    def signature(self,nodes,region=None):
        return hashlib.sha256(json.dumps(self.region_nodes(nodes,region),ensure_ascii=False,sort_keys=True).encode()).hexdigest()

    def remember(self,nodes,viewport,app,image_signature=None,has_tree=True):
        ident=uuid.uuid4().hex
        self.snapshots[ident]={"time":time.monotonic(),"signature":self.signature(nodes),"viewport":viewport,"app":app,"image_signature":image_signature,"nodes":nodes if has_tree else None}
        while len(self.snapshots)>32:
            self.snapshots.popitem(last=False)
        return ident

    def observe(self,mode="tree",include_invisible=False,max_nodes=100,expensive_visibility=False):
        if mode not in ("tree","screenshot","both"):
            fail("invalid_argument","mode must be tree, screenshot or both.")
        integer(max_nodes,"max_nodes",1,500)
        app=self.active_app()
        if mode=="screenshot":
            nodes,viewport=[],self.viewport()
        else:
            nodes,viewport=self.tree(include_invisible,expensive_visibility)
        result={"observation_id":self.remember(nodes,viewport,app,has_tree=mode!="screenshot"),"observed_at":dt.datetime.now(dt.timezone.utc).isoformat(),"app":app,"viewport":viewport,
                "warnings":["Viewport intersection does not prove hittability; fixed headers can occlude controls."]}
        if mode in ("tree","both"):
            result.update({"nodes":nodes[:max_nodes],"total_nodes":len(nodes),"truncated":len(nodes)>max_nodes,"visibility_computed":expensive_visibility})
            if not nodes:
                result["warnings"].append("Empty accessibility tree: inspect a screenshot for lock, iPhone Mirroring conflict, loading, or custom-rendered content before acting.")
        if mode in ("screenshot","both"):
            encoded=self.client.request("GET","/screenshot").get("value")
            try:
                data=base64.b64decode(encoded,validate=True)
            except (ValueError,TypeError) as exc:
                fail("invalid_response", "Invalid screenshot encoding.")
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                fail("invalid_response","WDA screenshot is not PNG.")
            self.snapshots[result["observation_id"]]["image_signature"]=hashlib.sha256(data).hexdigest()
            artifacts=self.state_dir/"artifacts";artifacts.mkdir(mode=0o700,parents=True,exist_ok=True)
            dest=artifacts/(dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"-"+uuid.uuid4().hex[:8]+".png")
            dest.write_bytes(data);dest.chmod(0o600)
            for old in sorted(artifacts.glob("*.png"))[:-100]:
                old.unlink()
            result["image"]={"path":str(dest),"mimeType":"image/png","coordinates":"Map image pixels to viewport points before tapping."}
        return result

    def snapshot(self,observation_id):
        old=self.snapshots.get(observation_id)
        if not old or time.monotonic()-old["time"]>30:
            fail("stale_observation","Observe again; coordinate observations expire after 30 seconds.")
        if self.active_app()!=old["app"]:
            fail("stale_observation","The foreground app changed. Observe again.")
        return old

    def guard(self,observation_id):
        old=self.snapshot(observation_id)
        if old.get("image_signature"):
            viewport=self.viewport()
            encoded=self.client.request("GET","/screenshot").get("value")
            try:signature=hashlib.sha256(base64.b64decode(encoded,validate=True)).hexdigest()
            except (ValueError,TypeError):fail("invalid_response","Invalid screenshot while checking freshness.")
            changed=signature!=old["image_signature"]
        else:
            nodes,viewport=self.tree();changed=self.signature(nodes)!=old["signature"]
        if viewport!=old["viewport"] or changed:
            fail("stale_observation","Page or orientation changed. Observe again before a coordinate action.")
        return viewport

    def guard_region(self,observation_id,region):
        old=self.snapshot(observation_id)
        if old.get("nodes") is None:
            fail("stale_observation","A custom scroll region needs a tree/both observation. Observe both, or inspect the current screen and use the default region.")
        nodes,viewport=self.tree()
        area=self.region(region,viewport)
        if viewport!=old["viewport"]:
            fail("stale_observation","Orientation or viewport changed. Observe again before scrolling.")
        previous=self.region_nodes(old["nodes"],area)
        current=self.region_nodes(nodes,area)
        # Scrolling is guarded by its target region, so an unrelated carousel
        # cannot invalidate it. Global modal changes remain a read barrier.
        modals=lambda items:[n for n in items if n["type"] in ("XCUIElementTypeAlert","XCUIElementTypeSheet")]
        if not previous or not current or self.signature(previous)!=self.signature(current) or modals(old["nodes"])!=modals(nodes):
            fail("stale_observation","Scroll target region or a modal changed. Observe tree/both again and choose a stable list region; a carousel outside the region is ignored.")
        return nodes,viewport

    def find(self,selector,limit=10):
        integer(limit,"limit",1,30)
        found=self.client.session("POST","/elements",{"using":"predicate string","value":predicate(selector)}) or []
        if not isinstance(found,list):
            fail("invalid_response","WDA elements result is not a list.")
        elements=[]
        for item in found[:limit]:
            ident=item.get(ELEMENT_KEY) or item.get("ELEMENT")
            if not isinstance(ident,str):
                continue
            route="/element/"+quote(ident,safe="")
            rect=self.client.session("GET",route+"/rect")
            elements.append({"element_id":ident,"rect":rect})
        return {"elements":elements,"matches":len(found),"truncated":len(found)>limit}

    def target(self,selector,editable=False):
        result=self.find(selector,limit=2)
        if result["matches"]==0:
            fail("no_such_element","Target not found. Read fresh state or use wda_scroll_find.")
        if result["matches"]!=1:
            fail("ambiguous_target","Several elements match. Add exact name/type/value to the selector.",matches=result["matches"])
        element=result["elements"][0]
        rect,viewport=element["rect"],self.viewport()
        cx=rect["x"]+rect["width"]/2;cy=rect["y"]+rect["height"]/2
        if rect["width"]<=0 or rect["height"]<=0 or not (0<=cx<viewport["width"] and 0<=cy<viewport["height"]):
            fail("offscreen_target","Target center is outside the viewport. Scroll into view first.")
        path="/element/"+quote(element["element_id"],safe="")
        hittable=self.client.session("GET",path+"/attribute/hittable")
        if hittable not in (True,1,"true","1"):
            fail("occluded_target","Target is not hittable. Inspect a screenshot or adjust scrolling; visible alone is insufficient.")
        if editable:
            kind=self.client.session("GET",path+"/attribute/type")
            if kind not in ("XCUIElementTypeTextField","XCUIElementTypeSearchField","XCUIElementTypeTextView"):
                fail("not_editable","Select a readable text/search field or text view. Secure fields cannot be verified.")
        return path

    def wait(self,selector,timeout_seconds=6):
        finite(timeout_seconds,"timeout_seconds",0,20)
        pred=predicate(selector)
        deadline=time.monotonic()+timeout_seconds;attempts=0
        while True:
            attempts+=1
            remaining=max(0.05,deadline-time.monotonic()) if timeout_seconds else 0.5
            found=self.client.session("POST","/elements",{"using":"predicate string","value":pred},timeout=min(remaining,2)) or []
            if found:
                return {"verified":True,"matches":len(found),"polls":attempts,"criterion":"selector exists; presence alone does not prove business success"}
            if time.monotonic()>=deadline:
                fail("postcondition_failed","Expected target did not appear within the wait budget.",polls=attempts)
            time.sleep(min(0.25,max(0,deadline-time.monotonic())))

    def after(self,expect=None,observe="tree"):
        result={"action_executed":True,"verified":False}
        if expect:
            result["postcondition"]=self.wait(expect);result["verified"]=True
        if observe!="none":
            result["observation"]=self.observe(observe)
        if not expect:
            result["verification_required"]="Read the result and check the intended page or business state. HTTP success alone is insufficient."
        return result

    @action_result
    def tap(self,selector=None,x=None,y=None,observation_id=None,expect=None,observe="tree"):
        if observe not in ("none","tree","screenshot","both"):
            fail("invalid_argument","Invalid observation mode.")
        if expect:predicate(expect)
        if selector is not None:
            if x is not None or y is not None:
                fail("invalid_argument","Choose selector or coordinates.")
            path=self.target(selector)
            self.post(path+"/click",{})
        else:
            finite(x,"x");finite(y,"y")
            viewport=self.guard(observation_id)
            if x>=viewport["width"] or y>=viewport["height"]:
                fail("invalid_argument","Coordinates are outside the iPhone viewport.")
            self.post("/wda/tap",{"x":x,"y":y})
        return self.after(expect,observe)

    @action_result
    def launch_app(self,bundle_id,expect=None,observe="tree"):
        if not isinstance(bundle_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+",bundle_id):
            fail("invalid_argument","Use the app's verified bundle ID.")
        if observe not in ("none","tree","screenshot","both"):fail("invalid_argument","Invalid observe mode.")
        if expect:predicate(expect)
        self.post("/wda/apps/activate",{"bundleId":bundle_id},timeout=45)
        if self.active_app()!=bundle_id:
            fail("postcondition_failed","The requested app is not foreground. Check login or system prompts.")
        result=self.after(expect,observe);result["foreground_verified"]=True
        return result

    @action_result
    def press_button(self,name,observe="tree"):
        if name not in ("home","volumeup","volumedown"):
            fail("invalid_argument","Supported buttons: home, volumeup, volumedown.")
        if observe not in ("none","tree","screenshot","both"):fail("invalid_argument","Invalid observe mode.")
        if name!="home":
            self.post("/wda/pressButton",{"name":name})
            return self.after(observe=observe)
        # XCTest pressButton can acknowledge Home without changing foreground.
        # WDA's dedicated endpoint activates the system application instead.
        self.post("/wda/homescreen",{},session=False)
        deadline=time.monotonic()+2
        app=None
        try:
            while True:
                app=self.active_app(timeout=max(.05,deadline-time.monotonic()))
                if app=="com.apple.springboard":break
                if time.monotonic()>=deadline:
                    fail("postcondition_failed","Home request returned, but SpringBoard did not become foreground. Inspect fresh state; do not loop on the same button.",foreground_app=app)
                time.sleep(min(.1,max(0,deadline-time.monotonic())))
            result={"action_executed":True,"verified":True,"foreground_verified":True,"foreground_app":app,"verification_scope":"Home navigation: SpringBoard is foreground; user task completion is separate."}
            if observe!="none":result["observation"]=self.observe(observe)
            return result
        except WDAError as exc:
            exc.details.update({"action_executed":True,"home_foreground_verified":app=="com.apple.springboard","verification_required":"Home was requested. Inspect fresh state before another action; do not automatically replay."})
            raise

    @action_result
    def type_text(self,selector,text,allow_newlines=False,submit=False,replace=True,observe="tree"):
        if not isinstance(text,str) or not 1<=len(text)<=10000 or "\x00" in text:
            fail("invalid_argument","text must have 1..10000 characters without NUL.")
        if ("\n" in text or "\r" in text) and not allow_newlines:
            fail("newline_requires_intent","This text contains line breaks, which can send a message. Use allow_newlines only for an observed multiline editor.")
        if observe not in ("none","tree","screenshot","both"):fail("invalid_argument","Invalid observe mode.")
        path=self.target(selector,editable=True)
        kind=self.client.session("GET",path+"/attribute/type")
        if ("\n" in text or "\r" in text) and kind!="XCUIElementTypeTextView":
            fail("newline_unsafe","Line breaks are allowed only for a verified TextView.")
        before=self.client.session("GET",path+"/attribute/value") or ""
        self.post(path+"/click",{})
        if replace:
            self.post(path+"/clear",{})
            cleared=self.client.session("GET",path+"/attribute/value")
            # Empty fields may report their placeholder; only use replace expected text for final readback.
        expected=text if replace else str(before)+text
        self.post(path+"/value",{"text":text,"frequency":30})
        actual=self.client.session("GET",path+"/attribute/value")
        if actual!=expected:
            fail("input_mismatch","Typed text did not round-trip exactly. Do not submit or blindly type it again.",expected_length=len(expected),actual_length=len(str(actual or "")))
        result={"action_executed":True,"verified":True,"exact_readback":True,"characters":len(text),"submitted":False}
        if submit:
            self.post("/wda/keys",{"value":["\n"]})
            result.update({"submitted":True,"submission_verified":False,"verification_required":"Inspect the submission result; exact field text only verified input before submission."})
        if observe!="none":result["observation"]=self.observe(observe)
        return result

    def region(self,region,viewport):
        if region is None:
            return {"x":viewport["width"]*.15,"y":viewport["height"]*.25,"width":viewport["width"]*.7,"height":viewport["height"]*.5}
        if not isinstance(region,dict) or set(region)!={"x","y","width","height"}:
            fail("invalid_argument","region must have x/y/width/height in iPhone points.")
        for k,v in region.items():finite(v,k,0 if k in ("x","y") else 1)
        if region["x"]+region["width"]>viewport["width"] or region["y"]+region["height"]>viewport["height"]:
            fail("invalid_argument","Gesture region is outside viewport.")
        return region

    def scroll_observation(self,nodes,viewport,mode):
        if mode=="none":return None
        if mode in ("screenshot","both"):
            observed=self.observe("screenshot")
            if mode=="screenshot":return observed
            # Reuse the verification tree. Do not take a second XML snapshot.
            self.snapshots[observed["observation_id"]].update(nodes=nodes,signature=self.signature(nodes))
        else:
            app=self.active_app()
            observed={"observation_id":self.remember(nodes,viewport,app),"viewport":viewport,"app":app}
        observed.update(nodes=nodes[:100],total_nodes=len(nodes),truncated=len(nodes)>100)
        return observed

    @action_result
    def swipe(self,direction="up",region=None,observation_id=None,expect=None,verify=True,max_attempts=2,observe="tree"):
        if direction not in ("up","down","left","right"):fail("invalid_argument","Invalid direction.")
        if observe not in ("none","tree","screenshot","both"):fail("invalid_argument","Invalid observe mode.")
        integer(max_attempts,"max_attempts",1,2)
        if expect:predicate(expect)
        before,viewport=self.guard_region(observation_id,region) if region is not None else self.tree()
        area=self.region(region,viewport)
        x=area["x"]+area["width"]/2;y=area["y"]+area["height"]/2
        dx=area["width"]*.32;dy=area["height"]*.32
        points={"up":(x,y+dy,x,y-dy),"down":(x,y-dy,x,y+dy),"left":(x+dx,y,x-dx,y),"right":(x-dx,y,x+dx,y)}[direction]
        baseline=self.signature(before,area)
        for attempt in range(max_attempts if verify else 1):
            strategy="short_drag" if attempt==0 else "native_swipe"
            if attempt==0:
                self.post("/wda/dragfromtoforduration",dict(zip(("fromX","fromY","toX","toY"),points),duration=.1))
            else:
                self.post("/wda/swipe",{"direction":direction,"x":x,"y":y},timeout=20)
            if not verify:
                result={"action_executed":True,"verified":False,"strategy":strategy,"verification_required":"Read actual scroll content and direction; progress verification was explicitly disabled."}
                if observe!="none":result["observation"]=self.observe(observe)
                return result
            after,v=self.tree();changed=self.signature(after,area)!=baseline
            if changed:
                result={"action_executed":True,"verified":True,"changed":True,"verification_scope":"content/geometry changed within gesture region; inspect correct direction and coverage", "attempts":attempt+1,"strategy":strategy}
                observed=self.scroll_observation(after,v,observe)
                if observed:result["observation"]=observed
                if expect:result["postcondition"]=self.wait(expect)
                return result
        details={"action_executed":True,"verified":False,"changed":False,"attempts":max_attempts,"region":area,
                 "recovery":{"next_step":"Inspect the current page and list entrance. If this is an overview, tap the actual list entry; if at the end, reconcile counts. Otherwise inspect a screenshot, modal or another stable region.","same_gesture_retry":False,"end_of_list_proven":False}}
        observed=self.scroll_observation(after,v,observe)
        if observed:details["observation"]=observed
        fail("no_scroll_progress","Gestures executed but exposed content/geometry did not change. The page may be an overview, boundary, blocked region or custom-rendered list. No progress does not prove an empty or complete list; inspect returned state and change the actual target instead of repeating.",**details)

    def scroll_find(self,selector,direction="up",max_swipes=6):
        predicate(selector);integer(max_swipes,"max_swipes",0,10)
        for count in range(max_swipes+1):
            found=self.find(selector,limit=2)
            if found["matches"]==1:
                try:
                    self.target(selector)
                    return {"verified":True,"swipes":count,**found}
                except WDAError as exc:
                    if exc.code not in ("offscreen_target","occluded_target"):raise
            elif found["matches"]>1:
                fail("ambiguous_target","Several targets match while scrolling. Refine selector.")
            if count==max_swipes:break
            self.swipe(direction,max_attempts=2)
        fail("search_exhausted","Target did not become hittable within max_swipes.",swipes=max_swipes)

    def collect_list(self,row_type="Cell",max_pages=6,end_selector=None):
        integer(max_pages,"max_pages",1,10)
        if end_selector:predicate(end_selector)
        if not isinstance(row_type,str) or not re.fullmatch(r"(?:XCUIElementType)?[A-Za-z]+",row_type):fail("invalid_argument","Invalid row_type.")
        kind=row_type if row_type.startswith("XCUIElementType") else "XCUIElementType"+row_type
        rows={};pages=[];reason="page_budget";end=False
        for index in range(max_pages):
            observed=self.observe(max_nodes=500)
            current=[n for n in observed["nodes"] if n["type"]==kind]
            for n in current:
                key=json.dumps({k:n[k] for k in ("type","name","label","value") if k in n},ensure_ascii=False,sort_keys=True)
                rows.setdefault(key,n)
            pages.append({"page":index+1,"rows_seen":len(current),"truncated":observed["truncated"]})
            if end_selector and self.find(end_selector,limit=1)["matches"]:
                try:self.target(end_selector);end=True;reason="explicit_end_marker";break
                except WDAError as exc:
                    if exc.code not in ("offscreen_target","occluded_target","ambiguous_target"):raise
            if index==max_pages-1:break
            try:self.swipe("up")
            except WDAError as exc:
                if exc.code!="no_scroll_progress":raise
                reason="no_progress";break
        return {"rows":list(rows.values()),"pages":pages,"stop_reason":reason,"end_marker_seen":end,"complete":False,
                "coverage_verified":end and not any(p["truncated"] for p in pages),
                "limitations":["Rows deduplicate by identical type/name/label/value; identical rows may collapse.","Only exposed accessibility labels are collected. Reconcile expected counts, screenshot-only fields, totals, currencies and dates before claiming business completeness."]}

    def batch(self,steps):
        if not isinstance(steps,list) or not 1<=len(steps)<=20:
            fail("invalid_argument","steps must contain 1..20 operations.")
        allowed={"tap":self.tap,"swipe":self.swipe,"type_text":self.type_text,"launch_app":self.launch_app,"press_button":self.press_button,"wait":self.wait,"observe":self.observe,"scroll_find":self.scroll_find}
        # Validate every step's shape before executing anything. Tool schemas validate nested arguments in the MCP layer.
        for step in steps:
            if not isinstance(step,dict) or set(step)-{"op","args"} or step.get("op") not in allowed or not isinstance(step.get("args",{}),dict):
                fail("invalid_argument","Each batch step needs a supported op and args object.")
        results=[]
        for index,step in enumerate(steps):
            try:
                result=allowed[step["op"]](**step.get("args",{}));results.append(result)
                # Observation is explicitly a read barrier; only mutation steps need verification before continuing.
                if step["op"] not in ("observe",) and not result.get("verified"):
                    return {"completed_steps":len(results),"stopped_at":index,"stop_reason":"verification_required","results":results,"complete":False}
                if result.get("submitted"):
                    return {"completed_steps":len(results),"stopped_at":index,"stop_reason":"submission_requires_verification","results":results,"complete":False}
            except WDAError as exc:
                return {"completed_steps":len(results),"stopped_at":index,"stop_reason":exc.code,"error":exc.as_dict(),"results":results,"complete":False}
        return {"completed_steps":len(results),"results":results,"complete":True}
